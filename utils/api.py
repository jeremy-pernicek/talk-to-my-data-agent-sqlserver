# Copyright 2024 DataRobot, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from __future__ import annotations

import ast
import asyncio
import functools
import inspect
import json
import logging
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from types import ModuleType, TracebackType
from typing import (
    Any,
    AsyncGenerator,
    Type,
    TypeVar,
    cast,
)

import datarobot as dr
import instructor
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import polars as pl
import psutil
import scipy
import sklearn
import statsmodels as sm
from datarobot.client import RESTClientObject
from joblib import Memory
from openai import AsyncOpenAI
from openai.types.chat.chat_completion_message_param import ChatCompletionMessageParam
from openai.types.chat.chat_completion_system_message_param import (
    ChatCompletionSystemMessageParam,
)
from openai.types.chat.chat_completion_user_message_param import (
    ChatCompletionUserMessageParam,
)
from plotly.subplots import make_subplots
from pydantic import ValidationError

sys.path.append(os.path.dirname(os.path.realpath(__file__)))
from utils import prompts, tools
from utils.analyst_db import AnalystDB, DataSourceType
from utils.code_execution import (
    InvalidGeneratedCode,
    MaxReflectionAttempts,
    execute_python,
    reflect_code_generation_errors,
)
from utils.data_cleansing_helpers import (
    add_summary_statistics,
    process_column,
)
from utils.database_helpers import get_external_database
from utils.logging_helper import get_logger, log_api_call
from utils.resources import LLMDeployment
from utils.schema import (
    AnalysisError,
    AnalystChatMessage,
    AnalystDataset,
    BusinessAnalysisGeneration,
    ChartGenerationExecutionResult,
    ChatRequest,
    CleansedDataset,
    CodeGeneration,
    Component,
    DatabaseAnalysisCodeGeneration,
    DataDictionary,
    DataDictionaryColumn,
    DataRegistryDataset,
    DictionaryGeneration,
    DownloadedRegistryDataset,
    EnhancedQuestionGeneration,
    GetBusinessAnalysisMetadata,
    GetBusinessAnalysisRequest,
    GetBusinessAnalysisResult,
    QuestionListGeneration,
    RunAnalysisRequest,
    RunAnalysisResult,
    RunAnalysisResultMetadata,
    RunChartsRequest,
    RunChartsResult,
    RunDatabaseAnalysisRequest,
    RunDatabaseAnalysisResult,
    RunDatabaseAnalysisResultMetadata,
    Tool,
    ValidatedQuestion,
)

logger = get_logger()
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("openai.http_client").setLevel(logging.WARNING)

VALUE_ERROR_MESSAGE = "Input data cannot be empty (no dataset provided)"
DEFAULT_LLM_GATEWAY_MODEL = "azure/gpt-4o"
DEFAULT_LLM_GATEWAY_MODEL_SMALL = "azure/gpt-4o-mini"


def log_memory() -> None:
    process = psutil.Process()
    memory = process.memory_info().rss / 1024 / 1024  # MB
    logger.info(f"Memory usage: {memory:.2f} MB")


@functools.cache
def initialize_deployment() -> tuple[RESTClientObject, str]:
    """Initialize either LLM Gateway or DataRobot-hosted LLM deployment based on environment settings and credential priority."""
    try:
        dr_client = dr.Client()
        chat_agent_deployment_id = LLMDeployment().id
        if chat_agent_deployment_id is None:
            raise ValueError(
                "LLM Deployment ID is required but not found. Please check your infrastructure setup."
            )
        deployment_chat_base_url = (
            f"{dr_client.endpoint.rstrip('/')}/deployments/{chat_agent_deployment_id}/"
        )
        logger.info(
            f"Using the DataRobot-hosted LLM deployment (configured at infrastructure time) at: {deployment_chat_base_url}"
        )
        return dr_client, deployment_chat_base_url

    except ValidationError as e:
        raise ValueError(
            "Unable to load Deployment ID."
            "If running locally, verify you have selected the correct "
            "stack and that it is active using `pulumi stack output`. "
            "If running in DataRobot, verify your runtime parameters have been set correctly."
        ) from e


class AsyncLLMClient:
    async def __aenter__(self) -> instructor.AsyncInstructor:
        dr_client, deployment_base_url = initialize_deployment()
        self.openai_client = AsyncOpenAI(
            api_key=dr_client.token,
            base_url=deployment_base_url,
            timeout=90,
            max_retries=2,
        )
        self.client = instructor.from_openai(
            self.openai_client, mode=instructor.Mode.MD_JSON
        )
        return self.client

    async def __aexit__(
        self,
        exc_type: Type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.openai_client.close()  # Properly close the client


ALTERNATIVE_LLM_BIG = "datarobot-deployed-llm"
ALTERNATIVE_LLM_SMALL = "datarobot-deployed-llm"
DICTIONARY_BATCH_SIZE = 10
MAX_REGISTRY_DATASET_SIZE = 400e6  # aligns to 400MB set in streamlit config.toml
DISK_CACHE_LIMIT_BYTES = 512e6
DICTIONARY_PARALLEL_BATCH_SIZE = 2
DICTIONARY_TIMEOUT = 45.0

_memory = Memory(tempfile.gettempdir(), verbose=0)
_memory.clear(warn=False)  # clear cache on startup

T = TypeVar("T")


def cache(f: T) -> T:
    """Cache function and coroutine results to disk using joblib."""
    cached_f = _memory.cache(f)

    if asyncio.iscoroutinefunction(f):

        async def awrapper(*args: Any, **kwargs: Any) -> Any:
            in_cache = cached_f.check_call_in_cache(*args, **kwargs)
            result = await cached_f(*args, **kwargs)
            if not in_cache:
                _memory.reduce_size(DISK_CACHE_LIMIT_BYTES)
            else:
                logger.info(
                    f"Using previously cached result for function `{f.__name__}`"
                )
            return result

        return cast(T, awrapper)
    else:

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            in_cache = cached_f.check_call_in_cache(*args, **kwargs)
            result = cached_f(*args, **kwargs)
            if not in_cache:
                _memory.reduce_size(DISK_CACHE_LIMIT_BYTES)
            else:
                logger.info(
                    f"Using previously cached result for function `{f.__name__}`"  # type: ignore[attr-defined]
                )
            return result

        return cast(T, wrapper)


# This can be large as we are not storing the actual datasets in memory, just metadata
def list_registry_datasets(limit: int = 100) -> list[DataRegistryDataset]:
    """
    Fetch datasets from Data Registry with specified limit

    Args:
        limit: int
        Datasets to retrieve. Max value: 100
    """

    url = f"datasets?limit={limit}"

    # Get all datasets and manually limit the results
    datasets = dr.client.get_client().get(url).json()["data"]

    return [
        DataRegistryDataset(
            id=ds["datasetId"],
            name=ds["name"],
            created=(
                ds["creationDate"][:10] if "creationDate" in ds else "N/A"  # %Y-%m-%d
            ),
            size=(
                f"{ds['datasetSize'] / (1024 * 1024):.1f} MB"
                if "datasetSize" in ds
                else "N/A"
            ),
        )
        for ds in datasets
    ]


async def download_registry_datasets(
    dataset_ids: list[str], analyst_db: AnalystDB
) -> list[DownloadedRegistryDataset]:
    """Load selected datasets as pandas DataFrames

    Args:
        *args: list of dataset IDs to download

    Returns:
        list[AnalystDataset]: Dictionary of dataset names and data
    """
    downloaded_datasets = []
    datasets = [dr.Dataset.get(id_) for id_ in dataset_ids]
    if (
        sum([ds.size for ds in datasets if ds.size is not None])
        > MAX_REGISTRY_DATASET_SIZE
    ):
        raise ValueError(
            f"The requested Data Registry datasets must total <= {int(MAX_REGISTRY_DATASET_SIZE)} bytes"
        )

    result_datasets: list[AnalystDataset] = []
    for dataset in datasets:
        try:
            df = dataset.get_as_dataframe()
            result_datasets.append(AnalystDataset(name=dataset.name, data=df))
            logger.info(f"Successfully downloaded {dataset.name}")
        except Exception as e:
            logger.error(f"Failed to read dataset {dataset.name}: {str(e)}")
            downloaded_datasets.append(
                DownloadedRegistryDataset(name=dataset.name, error=str(e))
            )
            continue
    for result_dataset in result_datasets:
        await analyst_db.register_dataset(
            result_dataset, DataSourceType.REGISTRY, dataset.size or 0
        )
        downloaded_datasets.append(DownloadedRegistryDataset(name=result_dataset.name))
    return downloaded_datasets


async def _get_dictionary_batch(
    columns: list[str], df: pl.DataFrame, batch_size: int = 5
) -> list[DataDictionaryColumn]:
    """Process a batch of columns to get their descriptions"""

    # Get sample data and stats for just these columns
    # Convert timestamps to ISO format strings for JSON serialization
    try:
        logger.debug(f"Processing batch of {len(columns)} columns")
        sample_data = {}
        logger.debug("Converting datetime columns to ISO format")
        num_samples = 10
        for col in columns:
            if df[col].dtype.is_temporal():
                # Convert timestamps to ISO format strings
                sample_data[col] = (
                    df.select(
                        pl.col(col)
                        .cast(pl.Datetime)
                        .map_elements(
                            lambda x: x.isoformat() if x is not None else None
                        )
                    )
                    .head(num_samples)
                    .to_dict()
                )
            else:
                # For non-datetime columns, just take the samples as is
                sample_data[col] = df.select(pl.col(col)).head(num_samples).to_dict()

        # Handle numeric summary
        numeric_summary = {}
        logger.debug("Calculating numeric summaries")
        for col in columns:
            if df[col].dtype.is_numeric():
                desc = df[col].describe()
                numeric_summary[col] = desc.to_dict()

        # Get categories for non-numeric columns
        categories = []
        logger.debug("Getting categories for non-numeric columns")
        for column in columns:
            if not df[column].dtype.is_numeric():
                try:
                    value_counts = (
                        df[column].sample(n=1000, seed=42).value_counts().head(10)
                    )
                    # Convert any timestamp values to strings
                    if df[column].dtype.is_temporal():
                        value_counts[column] = value_counts[column].cast(pl.String)
                    categories.append({column: value_counts[column].to_list()})
                except Exception:
                    continue

        # Create messages for OpenAI
        messages: list[ChatCompletionMessageParam] = [
            ChatCompletionSystemMessageParam(
                role="system", content=prompts.SYSTEM_PROMPT_GET_DICTIONARY
            ),
            ChatCompletionUserMessageParam(
                role="user", content=f"Data:\n{sample_data}\n"
            ),
            ChatCompletionUserMessageParam(
                role="user", content=f"Statistical Summary:\n{numeric_summary}\n"
            ),
        ]

        if categories:
            messages.append(
                ChatCompletionUserMessageParam(
                    role="user", content=f"Categorical Values:\n{categories}\n"
                )
            )
        logger.debug(
            f"total_characters: {len(''.join([str(msg) for msg in messages]))}"
        )
        # Get descriptions from OpenAI
        async with AsyncLLMClient() as client:
            completion: DictionaryGeneration = await client.chat.completions.create(
                response_model=DictionaryGeneration,
                model=ALTERNATIVE_LLM_SMALL,
                messages=messages,
            )

        # Convert to dictionary format
        descriptions = completion.to_dict()

        # Only return descriptions for requested columns
        return [
            DataDictionaryColumn(
                column=col,
                description=descriptions.get(col, "No description available"),
                data_type=str(df[col].dtype),
            )
            for col in columns
        ]

    except ValueError as e:
        logger.error(f"Invalid dictionary response: {str(e)}")
        return [
            DataDictionaryColumn(
                column=col,
                description="No valid description available",
                data_type=str(df[col].dtype),
            )
            for col in columns
        ]


@log_api_call
async def get_dictionary(dataset: AnalystDataset) -> DataDictionary:
    """Process a single dataset with parallel column batch processing"""

    try:
        logger.info(f"Processing dataset {dataset.name} init")
        # Convert JSON to DataFrame
        df_full = dataset.to_df()
        df = df_full.sample(n=min(10000, len(df_full)), seed=42)

        # Add debug logging
        logger.info(f"Processing dataset {dataset.name} with shape {df.shape}")

        # Handle empty dataset
        if df.is_empty():
            logger.warning(f"Dataset {dataset.name} is empty")
            return DataDictionary(
                name=dataset.name,
                column_descriptions=[],
            )

        # Split columns into batches
        column_batches = [
            list(df.columns[i : i + DICTIONARY_BATCH_SIZE])
            for i in range(0, len(df.columns), DICTIONARY_BATCH_SIZE)
        ]
        logger.info(
            f"Created {len(column_batches)} batches for {len(df.columns)} columns"
        )

        # Create a semaphore to limit concurrent tasks to 2
        sem = asyncio.Semaphore(DICTIONARY_PARALLEL_BATCH_SIZE)

        async def throttled_get_dictionary_batch(
            batch: list[str],
        ) -> list[DataDictionaryColumn]:
            try:
                async with sem:
                    return await asyncio.wait_for(
                        _get_dictionary_batch(batch, df, DICTIONARY_BATCH_SIZE),
                        timeout=DICTIONARY_TIMEOUT,
                    )
            except asyncio.TimeoutError:
                logger.warning(f"Timeout processing batch: {batch}")
                return [
                    DataDictionaryColumn(
                        column=col,
                        description="No Description Available",
                        data_type=str(df[col].dtype),
                    )
                    for col in batch
                ]
            except Exception as e:
                logger.error(f"Error processing batch {batch}: {str(e)}")
                return [
                    DataDictionaryColumn(
                        column=col,
                        description="No Description Available",
                        data_type=str(df[col].dtype),
                    )
                    for col in batch
                ]

        tasks = [throttled_get_dictionary_batch(batch) for batch in column_batches]

        results = await asyncio.gather(*tasks, return_exceptions=True)
        # Filter out any exceptions and flatten results
        dictionary: list[DataDictionaryColumn] = []
        for result in results:
            if isinstance(result, BaseException):
                logger.error(f"Task failed with error: {str(result)}")
                continue
            dictionary.extend(result)

        logger.info(
            f"Created dictionary with {len(dictionary)} entries for dataset {dataset.name}"
        )

        return DataDictionary(
            name=dataset.name,
            column_descriptions=dictionary,
        )

    except Exception:
        return DataDictionary(
            name=dataset.name,
            column_descriptions=[
                DataDictionaryColumn(
                    column=c,
                    data_type=str(dataset.to_df()[c].dtype),
                    description="No Description Available",
                )
                for c in dataset.columns
            ],
        )


def _validate_question_feasibility(
    question: str, available_columns: list[str]
) -> ValidatedQuestion | None:
    """Validate if a question can be answered with available data

    Checks if common data elements mentioned in the question exist in columns
    """
    # Convert question and columns to lowercase for matching
    question_lower = question.lower()
    columns_lower = [col.lower() for col in available_columns]

    # Extract potential column references from question
    words = set(re.findall(r"\b\w+\b", question_lower))

    # Find matches and missing terms
    found_columns = [col for col in columns_lower if any(word in col for word in words)]

    is_valid = len(found_columns) > 0
    if is_valid:
        return ValidatedQuestion(
            question=question,
        )
    return None


@log_api_call
async def suggest_questions(
    datasets: list[AnalystDataset], max_columns: int = 40
) -> list[ValidatedQuestion]:
    """Generate and validate suggested analysis questions

    Args:
        dictionary: DataFrame containing data dictionary
        max_columns: Maximum number of columns to include in prompt

    Returns:
        Dict containing:
            - questions: list of validated question objects
            - metadata: Dictionary of processing information
    """
    # Validate input
    dictionary = sum(
        [
            DataDictionary.from_analyst_df(
                ds.to_df(),
                column_descriptions=f"Column from dataset {ds.name}",
            ).column_descriptions
            for ds in datasets
        ],
        [],
    )

    if len(dictionary) < 1:
        raise ValueError("Dictionary DataFrame cannot be empty")

    # Limit columns for OpenAI prompt
    total_columns = len(dictionary)
    if total_columns > max_columns:
        # Take first and last 20 columns
        half_max = max_columns // 2
        first_half = dictionary[:half_max]
        last_half = dictionary[-half_max:]

        # Remove any duplicates
        dictionary = first_half + last_half

        # deduplicate
        dictionary = list({item.column: item for item in dictionary}.values())

    # Convert dictionary to format expected by OpenAI
    dict_data = {
        "columns": [d.column for d in dictionary],
        "descriptions": [d.description for d in dictionary],
        "data_types": [d.data_type for d in dictionary],
    }

    # Create OpenAI messages
    messages: list[ChatCompletionMessageParam] = [
        ChatCompletionSystemMessageParam(
            role="system", content=prompts.SYSTEM_PROMPT_SUGGEST_A_QUESTION
        ),
        ChatCompletionUserMessageParam(
            role="user", content=f"Data Dictionary:\n{json.dumps(dict_data)}"
        ),
    ]
    async with AsyncLLMClient() as client:
        completion: QuestionListGeneration = await client.chat.completions.create(
            response_model=QuestionListGeneration,
            model=ALTERNATIVE_LLM_SMALL,
            messages=messages,
        )

    available_columns = dict_data["columns"]
    validated_questions: list[ValidatedQuestion] = []

    for question in completion.questions:
        validated_question = _validate_question_feasibility(question, available_columns)
        if validated_question is not None:
            validated_questions.append(validated_question)

    return validated_questions


def find_imports(module: ModuleType) -> list[str]:
    """
    Get top-level third-party imports from a Python module.

    Args:
        module: Python module object to analyze

    Returns:
        list of third-party package names

    Example:
        >>> import my_module
        >>> imports = find_third_party_imports(my_module)
        >>> print(imports)  # ['pandas', 'numpy', 'requests']
    """
    try:
        # Get the source code of the module
        source = inspect.getsource(module)
        tree = ast.parse(source)

        stdlib_modules = set(sys.stdlib_module_names)
        third_party = set()

        # Only look at top-level imports
        for node in tree.body:
            if isinstance(node, ast.Import):
                for name in node.names:
                    module_name = name.name.split(".")[0]
                    if module_name not in stdlib_modules:
                        third_party.add(module_name)

            elif isinstance(node, ast.ImportFrom):
                if node.module is None:
                    continue
                module_name = node.module.split(".")[0]
                if module_name not in stdlib_modules:
                    third_party.add(module_name)

        return sorted(third_party)
    except Exception:
        return []


def get_tools() -> list[Tool]:
    try:
        # find all functions defined in the tools module
        tool_functions = [func for func in dir(tools) if callable(getattr(tools, func))]

        # find the function signatures and doc strings
        tools_list = []
        for func_name in tool_functions:
            func = getattr(tools, func_name)
            signature = inspect.signature(func)
            docstring = inspect.getdoc(func)
            tools_list.append(
                Tool(
                    name=func_name,
                    signature=str(signature),
                    docstring=docstring,
                    function=func,
                )
            )
        return tools_list
    except Exception:
        return []


async def _generate_run_charts_python_code(
    request: RunChartsRequest,
    validation_error: InvalidGeneratedCode | None = None,
) -> str:
    df = request.dataset.to_df().to_pandas()
    question = request.question
    dataframe_metadata = {
        "shape": {"rows": int(df.shape[0]), "columns": int(df.shape[1])},
        "statistics": df.describe(include="all").to_dict(),
        "dtypes": df.dtypes.astype(str).to_dict(),
    }
    messages: list[ChatCompletionMessageParam] = [
        ChatCompletionSystemMessageParam(
            role="system",
            content=prompts.SYSTEM_PROMPT_PLOTLY_CHART,
        ),
        ChatCompletionUserMessageParam(role="user", content=f"Question: {question}"),
        ChatCompletionUserMessageParam(
            role="user", content=f"Data Metadata:\n{dataframe_metadata}"
        ),
        ChatCompletionUserMessageParam(
            role="user", content=f"Data top 25 rows:\n{df.head(25).to_string()}"
        ),
    ]
    if validation_error:
        msg = type(validation_error).__name__ + f": {str(validation_error)}"
        messages.extend(
            [
                ChatCompletionUserMessageParam(
                    role="user",
                    content=f"Previous attempt failed with error: {msg}",
                ),
                ChatCompletionUserMessageParam(
                    role="user",
                    content=f"Failed code: {validation_error.code}",
                ),
                ChatCompletionUserMessageParam(
                    role="user",
                    content="Please generate new code that avoids this error.",
                ),
            ]
        )

    # Get response based on model mode
    async with AsyncLLMClient() as client:
        response: CodeGeneration = await client.chat.completions.create(
            response_model=CodeGeneration,
            model=ALTERNATIVE_LLM_BIG,
            temperature=0,
            messages=messages,
        )
    return response.code


async def _generate_run_analysis_python_code(
    request: RunAnalysisRequest,
    analyst_db: AnalystDB,
    validation_error: InvalidGeneratedCode | None = None,
    attempt: int = 0,
) -> str:
    """
    Generate Python analysis code based on JSON data and question.

    Parameters:
    - request: RunAnalysisRequest containing data and question
    - validation_errors: Past validation errors to include in prompt

    Returns:
    - Generated code
    """
    # Convert dictionary data structure to list of columns for all datasets
    logger.info("Starting code gen")

    all_columns = []
    all_descriptions = []
    all_data_types = []

    dictionaries = [
        await analyst_db.get_data_dictionary(name) for name in request.dataset_names
    ]
    for dictionary in dictionaries:
        if dictionary is None:
            continue
        for entry in dictionary.column_descriptions:
            all_columns.append(f"{dictionary.name}.{entry.column}")
            all_descriptions.append(entry.description)
            all_data_types.append(entry.data_type)

    # Create dictionary format for prompt
    dictionary_data = {
        "columns": all_columns,
        "descriptions": all_descriptions,
        "data_types": all_data_types,
    }

    # Get sample data and shape info for all datasets
    all_samples = []
    all_shapes = []

    logger.debug(f"datasets: {request.dataset_names}")
    for dataset_name in request.dataset_names:
        try:
            dataset = (await analyst_db.get_cleansed_dataset(dataset_name)).to_df()
        except Exception:
            dataset = (await analyst_db.get_dataset(dataset_name)).to_df()
        all_shapes.append(
            f"{dataset_name}: {dataset.shape[0]} rows x {dataset.shape[1]} columns"
        )
        # Limit sample to 10 rows
        sample_df = dataset.head(10)
        all_samples.append(f"{dataset_name}:\n{sample_df}")

    shape_info = "\n".join(all_shapes)
    sample_data = "\n\n".join(all_samples)
    logger.debug("Assembling messages")
    # Create messages for OpenAI
    messages: list[ChatCompletionMessageParam] = [
        ChatCompletionSystemMessageParam(
            role="system", content=prompts.SYSTEM_PROMPT_PYTHON_ANALYST
        ),
        ChatCompletionUserMessageParam(
            role="user", content=f"Business Question: {request.question}"
        ),
        ChatCompletionUserMessageParam(
            role="user", content=f"Data Shapes:\n{shape_info}"
        ),
        ChatCompletionUserMessageParam(
            role="user", content=f"Sample Data:\n{sample_data}"
        ),
        ChatCompletionUserMessageParam(
            role="user",
            content=f"Data Dictionary:\n{json.dumps(dictionary_data)}",
        ),
    ]

    tools_list = get_tools()
    if len(tools_list) > 0:
        messages.append(
            ChatCompletionUserMessageParam(
                role="user",
                content="If it helps the analysis, you can optionally use following functions:\n"
                + "\n".join([str(t) for t in tools_list]),
            )
        )

    logger.debug(f"total_characters: {len(''.join([str(msg) for msg in messages]))}")
    # Add error context if available
    if validation_error:
        msg = type(validation_error).__name__ + f": {str(validation_error)}"
        messages.extend(
            [
                ChatCompletionUserMessageParam(
                    role="user",
                    content=f"Previous attempt failed with error: {msg}",
                ),
                ChatCompletionUserMessageParam(
                    role="user",
                    content=f"Failed code: {validation_error.code}",
                ),
                ChatCompletionUserMessageParam(
                    role="user",
                    content="Please generate new code that avoids this error.",
                ),
            ]
        )
        if attempt > 2:
            messages.append(
                ChatCompletionUserMessageParam(
                    role="user",
                    content="Convert the dataframe to pandas!",
                )
            )
    logger.info("Running Code Gen")
    logger.debug(messages)
    async with AsyncLLMClient() as client:
        completion: CodeGeneration = await client.chat.completions.create(
            response_model=CodeGeneration,
            model=ALTERNATIVE_LLM_BIG,
            temperature=0.1,
            messages=messages,
            max_retries=10,
        )
    logger.info("Code Gen complete")
    return completion.code


async def cleanse_dataframe(dataset: AnalystDataset) -> CleansedDataset:
    """Clean and standardize multiple pandas DataFrames in parallel.

    Args:
        datasets: List of AnalystDataset objects to clean
    Returns:
        List of CleansedDataset objects containing cleaned data and reports
    Raises:
        ValueError: If a dataset is empty
    """

    if dataset.to_df().is_empty():
        raise ValueError(f"Dataset {dataset.name} is empty")

    df = dataset.to_df()
    sample_df = df.sample(min(100, len(df)))

    results = []
    for col in df.columns:
        results.append(process_column(df, col, sample_df))

    # Create new DataFrame from processed columns
    new_columns = {}
    reports = []

    for new_name, series, report in results:
        new_columns[new_name] = series
        reports.append(report)

    cleaned_df = pl.DataFrame(new_columns)
    add_summary_statistics(cleaned_df, reports)

    return CleansedDataset(
        dataset=AnalystDataset(
            name=dataset.name,
            data=cleaned_df,
        ),
        cleaning_report=reports,
    )


@log_api_call
async def rephrase_message(messages: ChatRequest) -> str:
    """Process chat messages history and return a new question

    Args:
        messages: list of message dictionaries with 'role' and 'content' fields

    Returns:
        Dict[str, str]: Dictionary containing response content
    """
    # Convert messages to string format for prompt
    messages_str = "\n".join(
        [f"{msg['role']}: {msg['content']}" for msg in messages.messages]
    )

    prompt_messages: list[ChatCompletionMessageParam] = [
        ChatCompletionSystemMessageParam(
            content=prompts.SYSTEM_PROMPT_REPHRASE_MESSAGE,
            role="system",
        ),
        ChatCompletionUserMessageParam(
            content=f"Message History:\n{messages_str}",
            role="user",
        ),
    ]
    async with AsyncLLMClient() as client:
        completion: EnhancedQuestionGeneration = await client.chat.completions.create(
            response_model=EnhancedQuestionGeneration,
            model=ALTERNATIVE_LLM_BIG,
            messages=prompt_messages,
        )

    return completion.enhanced_user_message


@reflect_code_generation_errors(max_attempts=7)
async def _run_charts(
    request: RunChartsRequest,
    exception_history: list[InvalidGeneratedCode] | None = None,
) -> RunChartsResult:
    """Generate and validate chart code with retry logic"""
    # Create messages for OpenAI
    start_time = datetime.now()

    if not request.dataset:
        raise ValueError(VALUE_ERROR_MESSAGE)

    df = request.dataset.to_df().to_pandas()
    if exception_history is None:
        exception_history = []

    code = await _generate_run_charts_python_code(
        request, next(iter(exception_history[::-1]), None)
    )
    try:
        result = execute_python(
            modules={
                "pd": pd,
                "np": np,
                "go": go,
                "pl": pl,
                "scipy": scipy,
            },
            functions={
                "make_subplots": make_subplots,
            },
            expected_function="create_charts",
            code=code,
            input_data=df,
            output_type=ChartGenerationExecutionResult,
            allowed_modules={
                "pandas",
                "numpy",
                "plotly",
                "scipy",
                "datetime",
                "polars",
            },
        )
    except InvalidGeneratedCode:
        raise
    except Exception as e:
        raise InvalidGeneratedCode(code=code, exception=e)

    duration = datetime.now() - start_time

    return RunChartsResult(
        status="success",
        code=code,
        fig1_json=result.fig1.to_json(),
        fig2_json=result.fig2.to_json(),
        metadata=RunAnalysisResultMetadata(
            duration=duration.total_seconds(),
            attempts=len(exception_history) + 1,
        ),
    )


@log_api_call
async def run_charts(request: RunChartsRequest) -> RunChartsResult:
    """Execute analysis workflow on datasets."""
    try:
        chart_result = await _run_charts(request)
        return chart_result
    except ValidationError:
        return RunChartsResult(
            status="error", metadata=RunAnalysisResultMetadata(duration=0, attempts=1)
        )
    except MaxReflectionAttempts as e:
        return RunChartsResult(
            status="error",
            metadata=RunAnalysisResultMetadata(
                duration=e.duration,
                attempts=len(e.exception_history) if e.exception_history else 0,
                exception=AnalysisError.from_max_reflection_exception(e),
            ),
        )


@log_api_call
async def get_business_analysis(
    request: GetBusinessAnalysisRequest,
) -> GetBusinessAnalysisResult:
    """
    Generate business analysis based on data and question.

    Parameters:
    - request: BusinessAnalysisRequest containing data and question

    Returns:
    - Dictionary containing analysis components
    """
    try:
        # Convert JSON data to DataFrame for analysis
        start = datetime.now()

        df = request.dataset.to_df().to_pandas()

        # Get first 1000 rows as CSV with quoted values for context
        df_csv = df.head(750).to_csv(index=False, quoting=1)

        # Create messages for OpenAI
        messages: list[ChatCompletionMessageParam] = [
            ChatCompletionSystemMessageParam(
                role="system", content=prompts.SYSTEM_PROMPT_BUSINESS_ANALYSIS
            ),
            ChatCompletionUserMessageParam(
                role="user",
                content=f"Business Question: {request.question}",
            ),
            ChatCompletionUserMessageParam(
                role="user", content=f"Analyzed Data:\n{df_csv}"
            ),
            ChatCompletionUserMessageParam(
                role="user",
                content=f"Data Dictionary:\n{request.dictionary.model_dump_json()}",
            ),
        ]
        async with AsyncLLMClient() as client:
            completion: BusinessAnalysisGeneration = (
                await client.chat.completions.create(
                    response_model=BusinessAnalysisGeneration,
                    model=ALTERNATIVE_LLM_BIG,
                    temperature=0.1,
                    messages=messages,
                )
            )
        duration = (datetime.now() - start).total_seconds()
        # Ensure all response fields are present
        metadata = GetBusinessAnalysisMetadata(
            duration=duration,
            question=request.question,
            rows_analyzed=len(df),
            columns_analyzed=len(df.columns),
        )
        return GetBusinessAnalysisResult(
            status="success",
            **completion.model_dump(),
            metadata=metadata,
        )

    except Exception as e:
        msg = type(e).__name__ + f": {str(e)}"
        logger.error(f"Error in get_business_analysis: {msg}")
        return GetBusinessAnalysisResult(
            status="error",
            metadata=GetBusinessAnalysisMetadata(exception_str=msg),
            additional_insights="",
            follow_up_questions=[],
            bottom_line="",
        )


@reflect_code_generation_errors(max_attempts=7)
async def _run_analysis(
    request: RunAnalysisRequest,
    analyst_db: AnalystDB,
    exception_history: list[InvalidGeneratedCode] | None = None,
) -> RunAnalysisResult:
    start_time = datetime.now()

    if not request.dataset_names:
        raise ValueError(VALUE_ERROR_MESSAGE)

    if exception_history is None:
        exception_history = []
    logger.info(f"Running analysis (attempt {len(exception_history)})")
    code = await _generate_run_analysis_python_code(
        request,
        analyst_db,
        next(iter(exception_history[::-1]), None),
        attempt=len(exception_history),
    )
    logger.info("Code generated, preparing execution")
    dataframes: dict[str, pl.DataFrame] = {}

    for dataset_name in request.dataset_names:
        try:
            dataset = (
                await analyst_db.get_cleansed_dataset(dataset_name, max_rows=None)
            ).to_df()
        except Exception:
            dataset = (
                await analyst_db.get_dataset(dataset_name, max_rows=None)
            ).to_df()
        dataframes[dataset_name] = dataset
    functions = {}
    tool_functions = get_tools()
    for tool in tool_functions:
        functions[tool.name] = tool.function
    try:
        logger.info("Executing")
        result = execute_python(
            modules={
                "pd": pd,
                "np": np,
                "sm": sm,
                "pl": pl,
                "scipy": scipy,
                "sklearn": sklearn,
            },
            functions=functions,
            expected_function="analyze_data",
            code=code,
            input_data=dataframes,
            output_type=AnalystDataset,
            allowed_modules={
                "pandas",
                "numpy",
                "scipy",
                "sklearn",
                "statsmodels",
                "datetime",
                "polars",
                *find_imports(tools),
            },
        )
    except InvalidGeneratedCode:
        raise
    except Exception as e:
        raise InvalidGeneratedCode(code=code, exception=e)
    logger.info("Execution done")
    duration = datetime.now() - start_time
    return RunAnalysisResult(
        status="success",
        code=code,
        dataset=result,
        metadata=RunAnalysisResultMetadata(
            duration=duration.total_seconds(),
            attempts=len(exception_history) + 1,
            datasets_analyzed=len(dataframes),
            total_rows_analyzed=sum(
                len(df) for df in dataframes.values() if not df.is_empty()
            ),
            total_columns_analyzed=sum(
                len(df.columns) for df in dataframes.values() if not df.is_empty()
            ),
        ),
    )


@log_api_call
async def run_analysis(
    request: RunAnalysisRequest,
    analyst_db: AnalystDB,
) -> RunAnalysisResult:
    """Execute analysis workflow on datasets."""
    logger.debug("Entering run_analysis")
    log_memory()
    try:
        return await _run_analysis(request, analyst_db=analyst_db)
    except MaxReflectionAttempts as e:
        return RunAnalysisResult(
            status="error",
            metadata=RunAnalysisResultMetadata(
                duration=e.duration,
                attempts=len(e.exception_history) if e.exception_history else 0,
                exception=AnalysisError.from_max_reflection_exception(e),
            ),
        )
    except ValueError as e:
        return RunAnalysisResult(
            status="error",
            metadata=RunAnalysisResultMetadata(
                duration=0,
                attempts=1,
                exception=AnalysisError.from_value_error(e),
            ),
        )


async def _generate_intelligent_followup_questions(
    original_question: str, 
    failed_query: str, 
    dictionaries: list,
    analyst_db: AnalystDB
) -> list[str]:
    """
    Generate intelligent follow-up questions based on the failed query and available data schema.
    These questions should be more likely to return results.
    """
    # Extract key information from the original question and failed query
    question_keywords = original_question.lower()
    query_upper = failed_query.upper()
    
    # Build context about available data
    schema_context = []
    for dictionary in dictionaries:
        if dictionary and dictionary.column_descriptions:
            table_name = dictionary.name
            columns = [col.column for col in dictionary.column_descriptions]
            schema_context.append(f"Table {table_name}: {', '.join(columns)}")
    
    # Create a prompt for generating better follow-up questions
    followup_prompt = f"""
Based on a failed query that returned 0 results, suggest 3 specific follow-up questions that are more likely to return data.

CONTEXT:
- Original user question: "{original_question}"
- Failed SQL query: {failed_query}
- Available data schema: {chr(10).join(schema_context)}

REQUIREMENTS:
- Questions should be more general/broader than the original
- Questions should use the actual column names from the schema
- Questions should be actionable and likely to return results
- Focus on exploring the data to understand what's available
- Don't ask generic questions like "what data is available" - be specific

Generate 3 follow-up questions that would help the user understand why their original query failed and suggest alternative approaches that might work.
"""

    try:
        # Generate follow-up questions using LLM
        messages: list[ChatCompletionMessageParam] = [
            ChatCompletionSystemMessageParam(
                role="system",
                content="You are a data analyst helping users refine their questions when queries return no results. Generate specific, actionable follow-up questions."
            ),
            ChatCompletionUserMessageParam(
                role="user", 
                content=followup_prompt
            )
        ]

        from pydantic import BaseModel
        
        class FollowupQuestionGeneration(BaseModel):
            questions: list[str]

        async with AsyncLLMClient() as client:
            completion = await client.chat.completions.create(
                response_model=FollowupQuestionGeneration,
                model=ALTERNATIVE_LLM_BIG,
                temperature=0.3,
                messages=messages,
            )

        return completion.questions if completion.questions else [
            "Let's try a broader search with fewer filters",
            "Can we explore what player positions are available in the data?",
            "What contract statuses exist in the database?"
        ]
        
    except Exception as e:
        logger.warning(f"Failed to generate intelligent follow-up questions: {e}")
        # Fallback to some general but better questions
        fallback_questions = []
        
        if "defense" in question_keywords or "position" in question_keywords:
            fallback_questions.extend([
                "What player positions are available in the data?",
                "Can we see all defensemen regardless of contract status?",
                "What are the different ways positions are recorded in the database?"
            ])
        elif "contract" in question_keywords or "free agent" in question_keywords:
            fallback_questions.extend([
                "What contract statuses are available in the data?",
                "Can we see all free agents regardless of position?",
                "What players have contracts expiring soon?"
            ])
        elif "team" in question_keywords:
            fallback_questions.extend([
                "What teams are represented in the database?",
                "Can we see player distribution across teams?",
                "What team-related data is available?"
            ])
        else:
            fallback_questions = [
                "Let's try the same query with broader search criteria",
                "Can we explore the available data with fewer filters?",
                "What would a simpler version of this question look like?"
            ]
            
        return fallback_questions[:3]

async def _validate_column_names_in_query(query: str, dictionaries: list, table_names: list[str]) -> list[str]:
    """
    Validate that column names referenced in the SQL query actually exist in the data dictionaries.
    
    Returns:
    - List of validation errors (empty if all columns are valid)
    """
    import re
    
    validation_errors = []
    
    # Create a mapping of table names to their columns
    table_columns = {}
    for dictionary in dictionaries:
        if dictionary and dictionary.column_descriptions:
            table_name = dictionary.name
            columns = {col.column.lower() for col in dictionary.column_descriptions}
            table_columns[table_name.lower()] = columns
            
            # Also handle schema.table format
            if '.' in table_name:
                schema, table = table_name.split('.', 1)
                table_columns[table.lower()] = columns
    
    # Extract column references from the query
    # Look for patterns like: table_alias.column_name or just column_name
    column_patterns = [
        r'\b([a-zA-Z_]\w*\.[a-zA-Z_]\w*)\b',  # table.column
        r'SELECT\s+.*?(\w+)(?:\s+AS\s+\w+)?(?:\s*,|\s+FROM)',  # columns in SELECT
        r'WHERE\s+.*?(\w+)\s*[=<>]',  # columns in WHERE
        r'ORDER\s+BY\s+.*?(\w+)',  # columns in ORDER BY
        r'GROUP\s+BY\s+.*?(\w+)',  # columns in GROUP BY
    ]
    
    referenced_columns = set()
    for pattern in column_patterns:
        matches = re.finditer(pattern, query, re.IGNORECASE | re.MULTILINE | re.DOTALL)
        for match in matches:
            referenced_columns.add(match.group(1).lower())
    
    # Check if referenced columns exist in any of the tables
    for col_ref in referenced_columns:
        if '.' in col_ref:
            # Handle table.column format
            table_part, col_part = col_ref.split('.', 1)
            if table_part in table_columns:
                if col_part not in table_columns[table_part]:
                    validation_errors.append(f"Column '{col_part}' does not exist in table '{table_part}'. Available columns: {sorted(table_columns[table_part])}")
        else:
            # Check if column exists in any table
            found = False
            for table_name, columns in table_columns.items():
                if col_ref in columns:
                    found = True
                    break
            if not found and col_ref not in ['count', 'sum', 'avg', 'max', 'min', 'top']:  # Ignore SQL functions
                validation_errors.append(f"Column '{col_ref}' not found in any available table")
    
    return validation_errors

async def _explore_and_validate_schema(
    request: RunDatabaseAnalysisRequest,
    analyst_db: AnalystDB
) -> dict:
    """
    Explore table schemas and relationships before generating complex queries.
    
    Returns:
        Dictionary containing exploration results and validation info
    """
    db_operator = get_external_database()
    
    exploration_results = {}
    schema_relationships = []
    
    try:
        # Explore each table's schema and sample values
        for table_name in request.dataset_names:
            if hasattr(db_operator, 'explore_table_schema'):
                exploration = await db_operator.explore_table_schema(table_name, sample_size=500)
                exploration_results[table_name] = exploration
                logger.info(f"Explored table {table_name}: {exploration.row_count} rows, {len(exploration.column_samples)} columns")
        
        # Validate relationships between tables
        if len(request.dataset_names) > 1 and hasattr(db_operator, 'validate_schema_relationships'):
            schema_relationships = await db_operator.validate_schema_relationships(request.dataset_names)
            logger.info(f"Found {len(schema_relationships)} valid table relationships")
            
    except Exception as e:
        logger.warning(f"Schema exploration failed: {str(e)}")
    
    return {
        "explorations": exploration_results,
        "relationships": schema_relationships
    }

async def _create_enhanced_schema_context(
    exploration_results: dict,
    dictionaries: list,
    request: RunDatabaseAnalysisRequest
) -> str:
    """
    Create enhanced schema context with sample values and relationship information.
    """
    context_parts = []
    
    # Add column validation section
    column_info = []
    for dictionary in dictionaries:
        if dictionary and dictionary.column_descriptions:
            table_name = dictionary.name
            columns = [col.column for col in dictionary.column_descriptions]
            column_info.append(f"Table {table_name} has columns: {', '.join(columns)}")
    
    context_parts.append(f"""
CRITICAL COLUMN VALIDATION:
The following are the EXACT column names available in each table:
{chr(10).join(column_info)}

IMPORTANT: Only use these exact column names in your query. Do not invent or assume column names.
If you need similar functionality, use the closest matching column name from the list above.
""")

    # Add sample values context
    explorations = exploration_results.get("explorations", {})
    if explorations:
        context_parts.append("\nSAMPLE VALUES FOR KEY COLUMNS:")
        for table_name, exploration in explorations.items():
            context_parts.append(f"\nTable: {table_name}")
            for col_sample in exploration.column_samples:
                if col_sample.sample_values and len(col_sample.sample_values) > 0:
                    values_str = ", ".join(col_sample.sample_values[:5])  # Show top 5
                    context_parts.append(f"  {col_sample.column_name}: {values_str}")

    # Add relationship information
    relationships = exploration_results.get("relationships", [])
    if relationships:
        context_parts.append("\nVALID TABLE RELATIONSHIPS:")
        for rel in relationships:
            match_pct = rel.match_percentage
            context_parts.append(f"  {rel.left_table}.{rel.left_column} = {rel.right_table}.{rel.right_column} ({match_pct:.1f}% match)")

    # Add hockey terminology guidance
    db_operator = get_external_database()
    if hasattr(db_operator, 'create_hockey_terminology_mappings'):
        mappings = db_operator.create_hockey_terminology_mappings()
        context_parts.append(f"""
HOCKEY TERMINOLOGY MAPPINGS:
When filtering by common hockey terms, use these variations for better results:
- Position "Defense": Try {mappings.get('defense', [])}
- Contract Status "UFA": Try {mappings.get('ufa', [])}
- Contract Status "RFA": Try {mappings.get('rfa', [])}

Use flexible WHERE clauses with OR conditions to include multiple variations.
""")

    return "\n".join(context_parts)

async def _generate_database_analysis_code(
    request: RunDatabaseAnalysisRequest,
    analyst_db: AnalystDB,
    validation_error: InvalidGeneratedCode | None = None,
) -> str:
    """
    Generate SQL Server SQL analysis code with enhanced schema exploration and validation.

    Parameters:
    - request: DatabaseAnalysisRequest containing data samples and question

    Returns:
    - Generated SQL code string with comprehensive validation
    """

    # Phase 1: Explore schema and relationships
    logger.info("Exploring table schemas and relationships...")
    exploration_results = await _explore_and_validate_schema(request, analyst_db)

    # Convert dictionary data structure to list of columns for all tables
    dictionaries = [
        await analyst_db.get_data_dictionary(name) for name in request.dataset_names
    ]
    all_tables_info = [d.model_dump(mode="json") for d in dictionaries if d is not None]

    # Get sample data for all tables
    all_samples = []
    for table in request.dataset_names:
        df = (await analyst_db.get_dataset(table)).to_df().to_pandas()
        sample_str = f"Table: {table}\n{df.head(10).to_string()}"
        all_samples.append(sample_str)
        
    # Create enhanced schema context with exploration results
    schema_context = await _create_enhanced_schema_context(
        exploration_results, dictionaries, request
    )

    # Create messages for OpenAI with enhanced context
    messages: list[ChatCompletionMessageParam] = [
        get_external_database().get_system_prompt(),
        ChatCompletionUserMessageParam(
            content=f"Business Question: {request.question}",
            role="user",
        ),
        ChatCompletionUserMessageParam(
            content=schema_context, role="user"
        ),
        ChatCompletionUserMessageParam(
            content=f"Sample Data:\n{chr(10).join(all_samples)}", role="user"
        ),
        ChatCompletionUserMessageParam(
            content=f"Data Dictionary:\n{json.dumps(all_tables_info)}", role="user"
        ),
    ]
    if validation_error:
        msg = type(validation_error).__name__ + f": {str(validation_error)}"
        messages.extend(
            [
                ChatCompletionUserMessageParam(
                    role="user",
                    content=f"Previous attempt failed with error: {msg}",
                ),
                ChatCompletionUserMessageParam(
                    role="user",
                    content=f"Failed code: {validation_error.code}",
                ),
                ChatCompletionUserMessageParam(
                    role="user",
                    content="Please generate new code that avoids this error. Pay special attention to column names and ensure they exist in the data dictionary.",
                ),
            ]
        )

    # Get response from OpenAI
    async with AsyncLLMClient() as client:
        completion = await client.chat.completions.create(
            response_model=DatabaseAnalysisCodeGeneration,
            model=ALTERNATIVE_LLM_BIG,
            temperature=0.1,
            messages=messages,
        )

    generated_query = completion.code
    
    # Phase 2: Enhanced query validation and diagnostic preparation
    validation_errors = await _validate_column_names_in_query(generated_query, dictionaries, request.dataset_names)
    if validation_errors:
        error_msg = "Column validation failed: " + "; ".join(validation_errors)
        logger.warning(f"Generated query has column validation issues: {error_msg}")
        # Store validation info for potential fallback
    
    return generated_query


async def _diagnose_query_failure(
    failed_query: str,
    request: RunDatabaseAnalysisRequest,
    analyst_db: AnalystDB,
    error_message: str
) -> "QueryDiagnostic":
    """
    Diagnose why a query failed and suggest fixes.
    
    Args:
        failed_query: The SQL query that failed
        request: Original request for context
        analyst_db: Database instance
        error_message: Error message from the failed query
        
    Returns:
        QueryDiagnostic with analysis and suggestions
    """
    from utils.schema import QueryDiagnostic
    
    db_operator = get_external_database()
    
    diagnostic = QueryDiagnostic(
        original_query=failed_query,
        step_results={},
        problematic_filters=[],
        suggested_fixes=[],
        alternative_values={}
    )
    
    try:
        # Parse the query to understand its structure
        query_upper = failed_query.upper()
        
        # Extract WHERE clause conditions
        where_conditions = _extract_where_conditions(failed_query)
        
        # Test each filter condition individually
        base_tables = _extract_tables_from_query(failed_query)
        
        if base_tables:
            # Start with a simple count from the main table
            main_table = base_tables[0]
            
            # Test table accessibility
            try:
                test_query = f"SELECT TOP 1 * FROM {main_table}"
                test_result = db_operator.execute_query(test_query, timeout=30)
                if test_result:
                    diagnostic.step_results["base_table_accessible"] = 1
                else:
                    diagnostic.step_results["base_table_accessible"] = 0
                    diagnostic.problematic_filters.append(f"Cannot access table {main_table}")
            except Exception as e:
                diagnostic.step_results["base_table_accessible"] = 0
                diagnostic.problematic_filters.append(f"Table access error: {str(e)}")
            
            # Test individual WHERE conditions
            for condition in where_conditions:
                try:
                    test_query = f"SELECT COUNT(*) as count FROM {main_table} WHERE {condition}"
                    result = db_operator.execute_query(test_query, timeout=30)
                    if result:
                        count = result[0]["count"]
                        diagnostic.step_results[f"filter_{condition[:50]}"] = count
                        if count == 0:
                            diagnostic.problematic_filters.append(condition)
                            
                            # Try to find alternative values for this condition
                            alternatives = await _find_alternative_values(condition, main_table, db_operator)
                            if alternatives:
                                diagnostic.alternative_values[condition] = alternatives
                                
                except Exception as e:
                    diagnostic.step_results[f"filter_{condition[:50]}"] = -1
                    diagnostic.problematic_filters.append(f"{condition}: {str(e)}")
        
        # Generate suggestions based on findings
        diagnostic.suggested_fixes = _generate_fix_suggestions(diagnostic, request.question)
        
    except Exception as e:
        logger.error(f"Query diagnosis failed: {str(e)}")
        diagnostic.suggested_fixes = ["Try simplifying the query with fewer filters"]
    
    return diagnostic


def _extract_where_conditions(query: str) -> list[str]:
    """Extract individual WHERE conditions from a SQL query"""
    import re
    
    # Find the WHERE clause
    where_match = re.search(r'WHERE\s+(.*?)(?:\s+ORDER\s+BY|\s+GROUP\s+BY|$)', query, re.IGNORECASE | re.DOTALL)
    if not where_match:
        return []
    
    where_clause = where_match.group(1).strip()
    
    # Split on AND (simple approach - could be enhanced for nested conditions)
    conditions = [cond.strip() for cond in re.split(r'\s+AND\s+', where_clause, flags=re.IGNORECASE)]
    
    return conditions


def _extract_tables_from_query(query: str) -> list[str]:
    """Extract table names from a SQL query"""
    import re
    
    # Find FROM clause
    from_match = re.search(r'FROM\s+(.*?)(?:\s+WHERE|\s+ORDER\s+BY|\s+GROUP\s+BY|$)', query, re.IGNORECASE | re.DOTALL)
    if not from_match:
        return []
    
    from_clause = from_match.group(1).strip()
    
    # Extract first table (main table)
    # Handle joins by splitting on INNER JOIN, LEFT JOIN, etc.
    main_table = re.split(r'\s+(?:INNER|LEFT|RIGHT|OUTER)\s+JOIN\s+', from_clause, flags=re.IGNORECASE)[0].strip()
    
    # Remove alias if present
    main_table = re.split(r'\s+(?:AS\s+)?\w+$', main_table, flags=re.IGNORECASE)[0].strip()
    
    return [main_table]


async def _find_alternative_values(condition: str, table: str, db_operator) -> list[str]:
    """Find alternative values for a failed filter condition"""
    import re
    
    alternatives = []
    
    try:
        # Extract column name from condition (simple patterns)
        column_match = re.search(r'(\w+)\s*[=<>]|(\w+)\s+(?:LIKE|IN)', condition, re.IGNORECASE)
        if column_match:
            column = column_match.group(1) or column_match.group(2)
            
            # Get top distinct values for this column
            distinct_query = f"SELECT TOP 10 DISTINCT {column} as value FROM {table} WHERE {column} IS NOT NULL"
            result = db_operator.execute_query(distinct_query, timeout=30)
            
            if result:
                alternatives = [str(row["value"]) for row in result if row["value"]]
                
    except Exception as e:
        logger.warning(f"Could not find alternatives for condition {condition}: {str(e)}")
    
    return alternatives


def _generate_fix_suggestions(diagnostic: "QueryDiagnostic", original_question: str) -> list[str]:
    """Generate fix suggestions based on diagnostic results"""
    suggestions = []
    
    if not diagnostic.step_results.get("base_table_accessible", 1):
        suggestions.append("Check table name and schema - the main table may not be accessible")
        return suggestions
    
    if diagnostic.problematic_filters:
        suggestions.append(f"Found {len(diagnostic.problematic_filters)} restrictive filters")
        
        for condition in diagnostic.problematic_filters[:3]:  # Show top 3
            if condition in diagnostic.alternative_values:
                alts = diagnostic.alternative_values[condition][:3]
                suggestions.append(f"For '{condition}', try these values: {', '.join(alts)}")
            else:
                suggestions.append(f"Consider removing or relaxing filter: {condition}")
    
    # Add general suggestions based on the question
    question_lower = original_question.lower()
    if "defense" in question_lower:
        suggestions.append("Try using broader position filters: Position LIKE '%D%' OR Position = 'Defense'")
    
    if "free agent" in question_lower:
        suggestions.append("Try multiple contract status values: ContractStatus IN ('UFA', 'RFA', 'Free Agent')")
    
    return suggestions


@reflect_code_generation_errors(max_attempts=7)
async def _run_database_analysis(
    request: RunDatabaseAnalysisRequest,
    analyst_db: AnalystDB,
    exception_history: list[InvalidGeneratedCode] | None = None,
) -> RunDatabaseAnalysisResult:
    start_time = datetime.now()
    if not request.dataset_names:
        raise ValueError(VALUE_ERROR_MESSAGE)

    if exception_history is None:
        exception_history = []

    sql_code = await _generate_database_analysis_code(
        request, analyst_db, next(iter(exception_history[::-1]), None)
    )
    try:
        results = get_external_database().execute_query(query=sql_code)
        results = cast(list[dict[str, Any]], results)
        duration = datetime.now() - start_time

        # Handle empty results gracefully - this is valid information, not an error
        if not results:
            logger.info(
                f"Query executed successfully but returned 0 rows. "
                f"This is valid information - the query may be too restrictive or there may be no matching data."
            )
            # Return an empty dataset - this is a valid result
            results = []

    except InvalidGeneratedCode:
        raise
    except Exception as e:
        raise InvalidGeneratedCode(code=sql_code, exception=e)
    return RunDatabaseAnalysisResult(
        status="success",
        code=sql_code,
        dataset=AnalystDataset(
            data=results,
        ),
        metadata=RunDatabaseAnalysisResultMetadata(
            duration=duration.total_seconds(),
            attempts=len(exception_history),
            datasets_analyzed=len(request.dataset_names),
            # total_columns_analyzed=sum(len(ds.columns) for ds in request.datasets),
        ),
    )


@log_api_call
async def run_database_analysis(
    request: RunDatabaseAnalysisRequest, analyst_db: AnalystDB
) -> RunDatabaseAnalysisResult:
    """Execute analysis workflow on datasets."""
    try:
        return await _run_database_analysis(request, analyst_db)
    except MaxReflectionAttempts as e:
        return RunDatabaseAnalysisResult(
            status="error",
            metadata=RunDatabaseAnalysisResultMetadata(
                duration=e.duration,
                attempts=len(e.exception_history) if e.exception_history else 0,
                exception=AnalysisError.from_max_reflection_exception(e),
            ),
        )
    except ValueError as e:
        return RunDatabaseAnalysisResult(
            status="error",
            metadata=RunDatabaseAnalysisResultMetadata(
                duration=0,
                attempts=1,
                exception=AnalysisError.from_value_error(e),
            ),
        )


# Type definitions
@dataclass
class AnalysisGenerationError:
    message: str
    original_error: BaseException | None = None


async def execute_business_analysis_and_charts(
    analysis_result: RunAnalysisResult | RunDatabaseAnalysisResult,
    enhanced_message: str,
    enable_chart_generation: bool = True,
    enable_business_insights: bool = True,
) -> tuple[
    RunChartsResult | BaseException | None,
    GetBusinessAnalysisResult | BaseException | None,
]:
    analysis_result.dataset = cast(AnalystDataset, analysis_result.dataset)
    # Prepare both requests
    chart_request = RunChartsRequest(
        dataset=analysis_result.dataset,
        question=enhanced_message,
    )

    business_request = GetBusinessAnalysisRequest(
        dataset=analysis_result.dataset,
        dictionary=DataDictionary.from_analyst_df(analysis_result.dataset.to_df()),
        question=enhanced_message,
    )

    if enable_chart_generation and enable_business_insights:
        # Run both analyses concurrently
        result = await asyncio.gather(
            run_charts(chart_request),
            get_business_analysis(business_request),
            return_exceptions=True,
        )

        return (result[0], result[1])
    elif enable_chart_generation:
        charts_result = await run_charts(chart_request)
        return charts_result, None
    else:
        business_result = await get_business_analysis(business_request)
        return None, business_result


async def run_complete_analysis(
    chat_request: ChatRequest,
    data_source: DataSourceType,
    datasets_names: list[str],
    analyst_db: AnalystDB,
    chat_id: str,
    message_id: str,
    enable_chart_generation: bool = True,
    enable_business_insights: bool = True,
) -> AsyncGenerator[Component | AnalysisGenerationError, None]:
    user_message = await analyst_db.get_chat_message(message_id=message_id)
    if user_message is None or user_message.role != "user":
        yield AnalysisGenerationError("Message not found")

        return
    # Get enhanced message
    try:
        logger.info("Getting rephrased question...")
        enhanced_message = await rephrase_message(chat_request)
        logger.info("Getting rephrased question done")

        yield enhanced_message

    except ValidationError:
        user_message.error = "LLM Error, please retry"
        user_message.in_progress = False
        await analyst_db.update_chat_message(
            message_id=message_id,
            message=user_message,
        )
        yield AnalysisGenerationError(user_message.error)

        return

    assistant_message = AnalystChatMessage(
        role="assistant",
        content=enhanced_message,
        components=[EnhancedQuestionGeneration(enhanced_user_message=enhanced_message)],
    )

    user_message.in_progress = False
    await analyst_db.update_chat_message(
        message_id=message_id,
        message=user_message,
    )
    await analyst_db.add_chat_message(chat_id=chat_id, message=assistant_message)
    # Run main analysis
    logger.info("Start main analysis")
    try:
        is_database = data_source == DataSourceType.DATABASE
        logger.info("Getting analysis result...")
        log_memory()

        if is_database:
            analysis_result: (
                RunAnalysisResult | RunDatabaseAnalysisResult
            ) = await run_database_analysis(
                RunDatabaseAnalysisRequest(
                    dataset_names=datasets_names,
                    question=enhanced_message,
                ),
                analyst_db,
            )
        else:
            analysis_result = await run_analysis(
                RunAnalysisRequest(
                    dataset_names=datasets_names,
                    question=enhanced_message,
                ),
                analyst_db,
            )

        log_memory()
        logger.info("Getting analysis result done")

        if isinstance(analysis_result, BaseException):
            error_message = f"Error running initial analysis. Try rephrasing: {str(analysis_result)}"
            assistant_message.in_progress = False
            assistant_message.error = error_message
            await analyst_db.update_chat_message(
                message_id=assistant_message.id, message=assistant_message
            )

            yield AnalysisGenerationError(error_message)

            return

        yield analysis_result

        assistant_message.components.append(analysis_result)
        await analyst_db.update_chat_message(
            message_id=assistant_message.id, message=assistant_message
        )

    except Exception as e:
        error_message = f"Error running initial analysis. Try rephrasing: {str(e)}"
        assistant_message.in_progress = False
        assistant_message.error = error_message
        await analyst_db.update_chat_message(
            message_id=assistant_message.id, message=assistant_message
        )

        yield AnalysisGenerationError(error_message)

        return

    # Check if we have empty results
    has_empty_results = (
        analysis_result 
        and analysis_result.dataset 
        and hasattr(analysis_result.dataset, 'data') 
        and hasattr(analysis_result.dataset.data, 'df')
        and len(analysis_result.dataset.data.df) == 0
    )
    
    if has_empty_results:
        # Add a note about empty results but don't treat as error
        logger.info("Query returned 0 rows. Skipping chart and insights generation.")
        # The analysis_result already contains the query and empty dataset
        # which will be displayed to the user
        
        # Enhanced zero results handling with diagnostics
        try:
            # Get dictionaries for intelligent question generation
            dictionaries = []
            for dataset_name in request.dataset_names:
                dictionary = await analyst_db.get_data_dictionary(dataset_name)
                if dictionary:
                    dictionaries.append(dictionary)
            
            # Run diagnostic analysis on the failed query
            diagnostic = None
            if analysis_result and analysis_result.code:
                try:
                    diagnostic = await _diagnose_query_failure(
                        analysis_result.code,
                        request,
                        analyst_db,
                        "Query returned 0 results"
                    )
                    logger.info(f"Query diagnostic completed. Found {len(diagnostic.problematic_filters)} problematic filters")
                except Exception as diag_e:
                    logger.warning(f"Query diagnostic failed: {str(diag_e)}")
            
            # Generate intelligent follow-up questions with diagnostic insights
            intelligent_followup_questions = await _generate_intelligent_followup_questions(
                enhanced_message,  # original user question
                analysis_result.code if analysis_result else "",  # failed query
                dictionaries,
                analyst_db
            )
            
            # Add diagnostic-based suggestions if available
            if diagnostic and diagnostic.suggested_fixes:
                # Enhance the additional insights with diagnostic findings
                diagnostic_insights = "\n".join([
                    "Query Analysis Results:",
                    f"• {len(diagnostic.problematic_filters)} filters may be too restrictive",
                    "• " + "\n• ".join(diagnostic.suggested_fixes[:3])  # Top 3 suggestions
                ])
                
                # Add diagnostic insights to follow-up questions if they're actionable
                for fix in diagnostic.suggested_fixes[:2]:  # Add top 2 as questions
                    if "try" in fix.lower():
                        question = fix.replace("try", "Can we try").replace("Try", "Can we try")
                        if question not in intelligent_followup_questions:
                            intelligent_followup_questions.append(question)
            
        except Exception as e:
            logger.warning(f"Enhanced zero results analysis failed: {e}")
            intelligent_followup_questions = [
                "Let's try the same query with broader search criteria",
                "Can we explore the available data with fewer filters?", 
                "What would a simpler version of this question look like?"
            ]
        
        # Add a business result explaining the zero results with intelligent follow-up questions
        empty_result_message = GetBusinessAnalysisResult(
            status="success",
            bottom_line="The query returned 0 results. This may indicate that the search criteria are too restrictive or there is no data matching the specified conditions.",
            additional_insights="Consider:\n• Using broader search criteria\n• Checking if the data exists with simpler filters\n• Verifying column values match the actual data\n• Using LIKE patterns instead of exact matches",
            follow_up_questions=intelligent_followup_questions,
            metadata=GetBusinessAnalysisMetadata(
                duration=0,
                attempts=1,
                rows_analyzed=0,
                columns_analyzed=0,
            )
        )
        
        assistant_message.components.append(empty_result_message)
        await analyst_db.update_chat_message(
            message_id=assistant_message.id, message=assistant_message
        )
        yield empty_result_message
    
    # Only proceed with additional analysis if we have valid initial results with data
    if not (
        analysis_result
        and analysis_result.dataset
        and not has_empty_results  # Skip if empty
        and (enable_chart_generation or enable_business_insights)
    ):
        assistant_message.in_progress = False
        await analyst_db.update_chat_message(
            message_id=assistant_message.id, message=assistant_message
        )
        return

    # Run concurrent analyses
    try:
        charts_result, business_result = await execute_business_analysis_and_charts(
            analysis_result,
            enhanced_message,
            enable_business_insights=enable_business_insights,
            enable_chart_generation=enable_chart_generation,
        )

        # Handle chart results
        if isinstance(charts_result, BaseException):
            error_message = "Error generating charts"
            assistant_message.error = error_message
            await analyst_db.update_chat_message(
                message_id=assistant_message.id, message=assistant_message
            )

            yield AnalysisGenerationError(error_message)

        elif charts_result is not None:
            assistant_message.components.append(charts_result)
            await analyst_db.update_chat_message(
                message_id=assistant_message.id, message=assistant_message
            )

            yield charts_result

        # Handle business analysis results
        if isinstance(business_result, BaseException):
            error_message = "Error generating business insights"
            assistant_message.error = error_message
            await analyst_db.update_chat_message(
                message_id=assistant_message.id, message=assistant_message
            )

            yield AnalysisGenerationError(error_message)

        elif business_result is not None:
            assistant_message.components.append(business_result)
            assistant_message.in_progress = False

            await analyst_db.update_chat_message(
                message_id=assistant_message.id, message=assistant_message
            )

            yield business_result

    except Exception as e:
        error_message = f"Error setting up additional analysis: {str(e)}"
        assistant_message.in_progress = False
        assistant_message.error = error_message
        await analyst_db.update_chat_message(
            message_id=assistant_message.id, message=assistant_message
        )

        yield AnalysisGenerationError(error_message)


async def process_data_and_update_state(
    new_dataset_names: list[str],
    analyst_db: AnalystDB,
    data_source: str | DataSourceType,
) -> AsyncGenerator[str, None]:
    """Process datasets and yield progress updates asynchronously."""
    # Start processing and yield initial message
    logger.info("Starting data processing")
    log_memory()
    yield "Starting data processing"

    # Handle data cleansing based on the source
    # Convert string data_source to DataSourceType if needed
    data_source_type = (
        data_source
        if isinstance(data_source, DataSourceType)
        else DataSourceType(data_source)
    )
    if data_source_type != DataSourceType.DATABASE:
        try:
            logger.info("Cleansing datasets")
            yield "Cleansing datasets"
            for analysis_dataset_name in new_dataset_names:
                analysis_dataset = await analyst_db.get_dataset(
                    analysis_dataset_name, max_rows=None
                )
                cleansed_dataset = await cleanse_dataframe(analysis_dataset)
                await analyst_db.register_dataset(
                    cleansed_dataset, data_source=DataSourceType.GENERATED
                )
                yield f"Cleansed dataset: {analysis_dataset_name}"
                del cleansed_dataset
                del analysis_dataset
                log_memory()

            logger.info("Cleansing datasets complete")
            yield "Cleansing datasets complete"
            log_memory()
        except Exception:
            logger.error("Data processing failed", exc_info=True)
            yield "Data processing failed"
            raise
    else:
        pass

    # Generate data dictionaries
    logger.info("Data processing successful, generating dictionaries")
    yield "Data processing successful, generating dictionaries"
    log_memory()
    try:
        for analysis_dataset_name in new_dataset_names:
            try:
                existing_dictionary = await analyst_db.get_data_dictionary(
                    analysis_dataset_name
                )
                logger.info(
                    f"Found existing dictionary for dataset: {analysis_dataset_name}"
                )
                if existing_dictionary is not None:
                    continue

            except Exception:
                pass
            logger.info(f"Creating dictionary for dataset: {analysis_dataset_name}")
            analysis_dataset = await analyst_db.get_dataset(analysis_dataset_name)
            new_dictionary = await get_dictionary(analysis_dataset)
            logger.info(new_dictionary.to_application_df())
            del analysis_dataset
            await analyst_db.register_data_dictionary(new_dictionary)
            logger.info(f"Registered dictionary for dataset: {analysis_dataset_name}")
            yield f"Registered data dictionary: {analysis_dataset_name}"
            log_memory()
            continue
    except Exception:
        logger.error("Failed to generate data dictionaries", exc_info=True)
        yield "Failed to generate data dictionaries"
        raise
    log_memory()
    # Final completion message
    yield "Processing complete"
