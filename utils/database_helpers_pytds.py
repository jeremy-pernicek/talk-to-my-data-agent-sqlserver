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

"""
SQL Server operator using pytds for DataRobot Codespaces compatibility
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from functools import lru_cache
from typing import Any, Generator, TYPE_CHECKING

import polars as pl

import pytds

from .database_helpers import DatabaseOperator, retry_on_transient_error
from .prompts import SYSTEM_PROMPT_SQLSERVER
from .code_execution import InvalidGeneratedCode

if TYPE_CHECKING:
    from .credentials import SQLServerCredentials

logger = logging.getLogger(__name__)


class SQLServerOperatorPytds(DatabaseOperator["SQLServerCredentials"]):
    """SQL Server database operator using pytds for pure Python implementation"""
    
    def __init__(self, credentials: "SQLServerCredentials", default_timeout: int = 300) -> None:
        """Initialize SQL Server operator with pytds
        
        Args:
            credentials: SQL Server connection credentials
            default_timeout: Default query timeout in seconds
        """
        self._credentials = credentials
        self.default_timeout = default_timeout
        logger.info("Initialized SQLServerOperatorPytds for DataRobot Codespace environment")
    
    @contextmanager
    def create_connection(self) -> Generator[pytds.Connection, None, None]:
        """Create a connection to SQL Server using pytds"""
        if not self._credentials.is_configured():
            raise ValueError("SQL Server credentials not properly configured")
        
        try:
            # Create connection with pytds
            connection = pytds.connect(
                server=self._credentials.host,
                port=self._credentials.port,
                user=self._credentials.user,
                password=self._credentials.password,
                database=self._credentials.database,
                timeout=self._credentials.connection_timeout,
                login_timeout=self._credentials.connection_timeout,
                as_dict=True,  # Return rows as dictionaries
                autocommit=True  # Enable autocommit to prevent transaction issues
            )
            
            logger.info(f"Successfully connected to SQL Server at {self._credentials.host}")
            
            try:
                yield connection
            finally:
                connection.close()
                
        except Exception as e:
            logger.error(f"Failed to connect to SQL Server: {str(e)}")
            # Don't wrap connection errors
            raise
    
    @retry_on_transient_error(max_attempts=2, initial_delay=0.5)
    def _execute_query_with_retry(self, cursor: pytds.Cursor, query: str) -> tuple[list[str], list[Any]]:
        """Execute query with retry logic"""
        import time
        
        logger.debug(f"Executing query: {query[:1000]}...")  # Log first 1000 chars
        
        # Measure query execution time
        start_time = time.time()
        cursor.execute(query)
        execution_time = time.time() - start_time
        
        # Get column names
        columns = [col[0] for col in cursor.description] if cursor.description else []
        
        # Fetch all rows
        rows = cursor.fetchall()
        fetch_time = time.time() - start_time - execution_time
        
        logger.info(f"Query executed in {execution_time:.3f}s, fetched {len(rows)} rows in {fetch_time:.3f}s")
        
        return columns, rows
    
    def execute_query(
        self, query: str, timeout: int | None = None
    ) -> list[dict[str, Any]]:
        """Execute a SQL Server query
        
        Args:
            query: SQL query to execute
            timeout: Query timeout in seconds (not supported by pytds)
            
        Returns:
            List of dictionaries containing query results
        """
        timeout = timeout if timeout is not None else self.default_timeout
        cursor = None
        
        try:
            with self.create_connection() as conn:
                # Create cursor (as_dict is already set on connection)
                cursor = conn.cursor()
                
                try:
                    # Execute query (pytds doesn't support per-query timeout)
                    if timeout != self.default_timeout:
                        logger.warning("pytds does not support per-query timeout, using connection timeout")
                    
                    columns, rows = self._execute_query_with_retry(cursor, query)
                    
                    # Convert to list of dictionaries
                    if cursor.description and rows:
                        # With as_dict=True on connection, rows should be dictionaries
                        return rows
                    else:
                        return []
                        
                finally:
                    if cursor:
                        cursor.close()
                        
        except Exception as e:
            logger.error(f"Query execution failed: {str(e)}")
            logger.error(f"Query was: {query[:1500]}...")  # Log more of the query for debugging
            raise InvalidGeneratedCode(
                f"Failed to execute SQL query: {str(e)}"
            ) from e
    
    def get_table_as_dataframe(
        self, query: str, timeout: int | None = None
    ) -> pl.DataFrame | str:
        """Execute query and return results as Polars DataFrame
        
        Args:
            query: SQL query to execute
            timeout: Query timeout in seconds
            
        Returns:
            Polars DataFrame or error message string
        """
        try:
            # Execute query and get results
            results = self.execute_query(query, timeout)
            
            if not results:
                return pl.DataFrame()
            
            # Convert directly to Polars DataFrame
            return pl.DataFrame(results)
            
        except Exception as e:
            error_msg = f"Failed to get table as dataframe: {str(e)}"
            logger.error(error_msg)
            return error_msg
    
    def list_tables(self, schema: str | None = None) -> list[str]:
        """List all tables in the database or schema
        
        Args:
            schema: Schema name to filter tables
            
        Returns:
            List of table names
        """
        schema = schema or self._credentials.db_schema
        
        query = f"""
        SELECT TABLE_NAME 
        FROM INFORMATION_SCHEMA.TABLES 
        WHERE TABLE_TYPE = 'BASE TABLE' 
        AND TABLE_SCHEMA = '{schema}'
        ORDER BY TABLE_NAME
        """
        
        try:
            results = self.execute_query(query)
            return [row['TABLE_NAME'] for row in results]
        except Exception as e:
            logger.error(f"Failed to list tables: {str(e)}")
            return []
    
    def get_table_schema(self, table_name: str, schema: str | None = None) -> str:
        """Get the schema information for a table
        
        Args:
            table_name: Name of the table
            schema: Schema name
            
        Returns:
            String representation of table schema
        """
        schema = schema or self._credentials.db_schema
        
        query = f"""
        SELECT 
            COLUMN_NAME,
            DATA_TYPE,
            CHARACTER_MAXIMUM_LENGTH,
            IS_NULLABLE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = '{schema}'
        AND TABLE_NAME = '{table_name}'
        ORDER BY ORDINAL_POSITION
        """
        
        try:
            results = self.execute_query(query)
            
            if not results:
                return f"Table {schema}.{table_name} not found"
            
            # Format schema information
            schema_info = [f"Schema for {schema}.{table_name}:"]
            for col in results:
                col_type = col['DATA_TYPE']
                if col['CHARACTER_MAXIMUM_LENGTH']:
                    col_type += f"({col['CHARACTER_MAXIMUM_LENGTH']})"
                nullable = "NULL" if col['IS_NULLABLE'] == 'YES' else "NOT NULL"
                schema_info.append(f"  - {col['COLUMN_NAME']}: {col_type} {nullable}")
            
            return "\n".join(schema_info)
            
        except Exception as e:
            return f"Failed to get table schema: {str(e)}"
    
    def sample_table_data(self, table_name: str, limit: int = 5) -> str:
        """Get a sample of data from a table
        
        Args:
            table_name: Name of the table to sample
            limit: Number of rows to return
            
        Returns:
            String representation of sample data
        """
        # Use schema-qualified table name
        qualified_table = f"[{self._credentials.db_schema}].[{table_name}]"
        
        query = f"SELECT TOP {limit} * FROM {qualified_table}"
        
        try:
            df = self.get_table_as_dataframe(query)
            
            if isinstance(df, str):
                return df  # Error message
            
            if df.is_empty():
                return f"No data found in table {qualified_table}"
            
            # Convert to string representation
            return f"Sample data from {qualified_table} (first {limit} rows):\n{df}"
            
        except Exception as e:
            return f"Failed to sample table data: {str(e)}"
    
    def get_system_prompt(self) -> Any:
        """Get the system prompt for SQL Server T-SQL code generation"""
        from openai.types.chat import ChatCompletionSystemMessageParam
        
        return ChatCompletionSystemMessageParam(
            role="system",
            content=SYSTEM_PROMPT_SQLSERVER.format(
                database=self._credentials.database,
                schema=self._credentials.db_schema,
            ),
        )
    
    def get_tables(self, timeout: int | None = None) -> list[str]:
        """Get list of available tables in the database
        
        Args:
            timeout: Query timeout in seconds (not used by pytds)
            
        Returns:
            List of table names
        """
        return self.list_tables()
    
    async def get_data(
        self,
        *table_names: str,
        analyst_db: Any,
        sample_size: int = 5000,
        timeout: int | None = None,
    ) -> list[str]:
        """Load selected tables from SQL Server as pandas DataFrames
        
        Args:
            table_names: List of table names to fetch
            analyst_db: AnalystDB instance to register datasets
            sample_size: Number of rows to sample from each table
            timeout: Query timeout in seconds
            
        Returns:
            List of successfully loaded table names
        """
        if not table_names:
            return []
        
        names = []
        try:
            for table in table_names:
                # Use schema-qualified table name
                qualified_table = f"[{self._credentials.db_schema}].[{table}]"
                query = f"SELECT TOP {sample_size} * FROM {qualified_table}"
                
                try:
                    df = self.get_table_as_dataframe(query, timeout)
                    
                    if isinstance(df, str):
                        logger.error(f"Failed to fetch data from {table}: {df}")
                        continue
                    
                    if df.is_empty():
                        logger.warning(f"Table {table} is empty")
                        continue
                    
                    # Convert Polars DataFrame to pandas for compatibility
                    import pandas as pd
                    pandas_df = df.to_pandas()
                    
                    # Create dataset object
                    from utils.schema import AnalystDataset
                    from utils.analyst_db import DataSourceType
                    dataset = AnalystDataset(name=table, data=pandas_df)
                    
                    # Register with analyst DB
                    if analyst_db:
                        await analyst_db.register_dataset(
                            dataset, DataSourceType.DATABASE
                        )
                    
                    names.append(table)
                    logger.info(f"Successfully loaded table: {table}")
                    
                except Exception as e:
                    logger.error(f"Error loading table {table}: {str(e)}")
                    continue
            
            return names
            
        except Exception as e:
            logger.error(f"Error fetching SQL Server data: {str(e)}")
            return []