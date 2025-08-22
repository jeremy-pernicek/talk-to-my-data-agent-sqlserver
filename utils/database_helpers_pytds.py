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
Enhanced with pushdown capabilities for large dataset analysis
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Generator

try:
    import polars as pl
except ImportError:
    pl = None  # type: ignore

try:
    import pytds
except ImportError:
    pytds = None  # type: ignore

from .code_execution import InvalidGeneratedCode
from .database_helpers import DatabaseOperator, retry_on_transient_error
from .prompts import SYSTEM_PROMPT_SQLSERVER

if TYPE_CHECKING:
    from .credentials import SQLServerCredentials

logger = logging.getLogger(__name__)


@dataclass
class PushdownConfig:
    """Configuration for SQL Server pushdown optimization"""

    # Memory limits
    max_result_memory_mb: int = 500
    streaming_chunk_size: int = 10000

    # Query optimization  
    auto_add_top_limit: int = 10000  # Reduced from 50000 to prevent timeouts
    enable_tablesample: bool = True
    tablesample_rows: int = 5000  # Reduced from 10000

    # Performance monitoring
    log_query_performance: bool = True
    warn_on_large_results: bool = True
    large_result_threshold: int = 100000

    def should_optimize_query(self, query: str) -> bool:
        """Determine if a query should be optimized for large datasets"""
        query_upper = query.upper()

        # Don't optimize if already optimized
        if "TOP" in query_upper or "LIMIT" in query_upper:
            return False

        # Optimize if it's a broad SELECT
        if "SELECT *" in query_upper:
            return True

        # Optimize if no aggregations that would naturally limit results
        if not any(
            agg in query_upper
            for agg in ["COUNT(", "SUM(", "AVG(", "MAX(", "MIN(", "GROUP BY"]
        ):
            return True

        return False


class SQLServerOperatorPytds(DatabaseOperator["SQLServerCredentials"]):
    """SQL Server database operator using pytds for pure Python implementation"""

    def __init__(
        self,
        credentials: "SQLServerCredentials",
        default_timeout: int = 600,
        pushdown_config: PushdownConfig | None = None,
    ) -> None:
        """Initialize SQL Server operator with pytds

        Args:
            credentials: SQL Server connection credentials
            default_timeout: Default query timeout in seconds
            pushdown_config: Configuration for pushdown optimization
        """
        if pytds is None:
            raise ImportError(
                "pytds is required for SQL Server operations but is not installed"
            )
        if pl is None:
            raise ImportError(
                "polars is required for SQL Server operations but is not installed"
            )

        self._credentials = credentials
        self.default_timeout = default_timeout
        self.pushdown_config = pushdown_config or PushdownConfig()
        
        # Performance tracking for query optimization learning
        self._query_performance_cache = {}
        self._connection_pool_stats = {"total_connections": 0, "failed_connections": 0}
        
        logger.info(
            "Initialized SQLServerOperatorPytds for DataRobot Codespace environment with pushdown capabilities"
        )

    @contextmanager
    def create_connection(self) -> Generator[Any, None, None]:
        """Create a connection to SQL Server using pytds"""
        if not self._credentials.is_configured():
            raise ValueError("SQL Server credentials not properly configured")

        try:
            # Create connection with pytds - use extended timeouts for complex queries
            connection_timeout = max(self._credentials.connection_timeout or 30, 120)
            login_timeout = max(self._credentials.connection_timeout or 30, 60)
            
            logger.info(f"Connecting to SQL Server with extended timeouts: connection={connection_timeout}s, login={login_timeout}s")
            
            # Note: pytds handles encryption automatically for SQL Server 2017+
            # The JDBC encrypt=true;trustServerCertificate=true is handled internally
            connection = pytds.connect(
                server=self._credentials.host,
                port=self._credentials.port,
                user=self._credentials.user,
                password=self._credentials.password,
                database=self._credentials.database,
                timeout=connection_timeout,  # Extended timeout for query execution
                login_timeout=login_timeout,  # Extended timeout for connection establishment
                as_dict=True,  # Return rows as dictionaries
                autocommit=True,  # Enable autocommit to prevent transaction issues
            )

            logger.info(
                f"Successfully connected to SQL Server at {self._credentials.host}"
            )

            try:
                yield connection
            finally:
                connection.close()

        except Exception as e:
            logger.error(f"Failed to connect to SQL Server: {str(e)}")
            # Don't wrap connection errors
            raise

    @retry_on_transient_error(max_attempts=2, initial_delay=0.5)
    def _execute_query_with_retry(
        self, cursor: pytds.Cursor, query: str
    ) -> tuple[list[str], list[Any]]:
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

        logger.info(
            f"Query executed in {execution_time:.3f}s, fetched {len(rows)} rows in {fetch_time:.3f}s"
        )

        return columns, rows

    def optimize_query_for_large_datasets(
        self, query: str, max_rows: int | None = None
    ) -> str:
        """Optimize a query for large datasets by adding appropriate limits and optimizations

        Args:
            query: Original SQL query
            max_rows: Maximum number of rows to return (default: no limit)

        Returns:
            Optimized query string
        """
        query = query.strip()
        query_upper = query.upper()

        # Check if query already has a TOP clause
        has_top = "SELECT TOP" in query_upper
        has_limit = "LIMIT" in query_upper

        if max_rows and not has_top and not has_limit:
            # Add TOP clause for row limiting
            if query_upper.startswith("SELECT"):
                # Insert TOP after SELECT
                select_pos = query_upper.find("SELECT")
                if select_pos != -1:
                    insert_pos = select_pos + 6  # len('SELECT')
                    query = query[:insert_pos] + f" TOP {max_rows}" + query[insert_pos:]
                    logger.debug(
                        f"Added TOP {max_rows} clause to query for optimization"
                    )

        # CRITICAL OPTIMIZATION: Force WHERE clause for TTMD_Deposit_History if missing
        # This table has millions of rows and causes 50+ second queries without filters
        if "TTMD_DEPOSIT_HISTORY" in query_upper and "WHERE" not in query_upper:
            logger.warning("TTMD_Deposit_History query missing WHERE clause - adding date filter for performance")
            
            # Find the right place to insert WHERE clause
            if "GROUP BY" in query_upper:
                # Insert WHERE before GROUP BY
                group_pos = query.upper().find("GROUP BY")
                query = (query[:group_pos] + 
                        "\nWHERE [As Of Date] >= DATEADD(month, -3, GETDATE()) -- Auto-added for performance\n" +
                        query[group_pos:])
            elif "ORDER BY" in query_upper:
                # Insert WHERE before ORDER BY
                order_pos = query.upper().find("ORDER BY")
                query = (query[:order_pos] + 
                        "\nWHERE [As Of Date] >= DATEADD(month, -3, GETDATE()) -- Auto-added for performance\n" +
                        query[order_pos:])
            else:
                # Add at the end before any OPTION clause
                if "OPTION" in query_upper:
                    option_pos = query.upper().find("OPTION")
                    query = (query[:option_pos] + 
                            "\nWHERE [As Of Date] >= DATEADD(month, -3, GETDATE()) -- Auto-added for performance\n" +
                            query[option_pos:])
                else:
                    query += "\nWHERE [As Of Date] >= DATEADD(month, -3, GETDATE()) -- Auto-added for performance"

        # Apply transparent SQL Server optimizations
        optimized_query = self._add_transparent_query_hints(query)

        return optimized_query

    def _add_transparent_query_hints(self, query: str) -> str:
        """Add SQL Server query hints that don't change semantics but improve performance
        
        Args:
            query: Original SQL query
            
        Returns:
            Query with performance hints added
        """
        query = query.strip()
        query_upper = query.upper()
        
        # Add OPTION clauses for performance
        hints = []
        
        # Detect if FORMAT() is being used for date operations (slow!)
        if "FORMAT(" in query_upper:
            logger.warning("Query uses FORMAT() function which is slow on large datasets. Consider using CONVERT() instead.")
        
        # For queries without TOP, add FAST hint to get first results quickly
        if "TOP" not in query_upper and "OPTION" not in query_upper:
            # Check if it's an aggregation query or detailed query
            if any(agg in query_upper for agg in ["GROUP BY", "COUNT(", "SUM(", "AVG("]):
                # For aggregation queries, don't use FAST hint as it can make them slower
                # Instead use HASH GROUP for better aggregation performance
                hints.append("HASH GROUP")
                hints.append("MAXDOP 4")  # Use parallel processing for aggregations
            else:
                hints.append("FAST 1000")  # Get first 1000 detail results quickly
        
        # Add query optimization hints for large table scans
        if "FROM" in query_upper and "WHERE" not in query_upper:
            # Full table scan detected - add memory optimization
            hints.append("HASH GROUP")  # Use hash aggregation for large scans
            hints.append("MAXDOP 4")  # Enable parallel processing
            logger.warning("Query performs full table scan without WHERE clause - performance may be slow")
        
        # For date-based aggregations, ensure proper hints
        if "GROUP BY" in query_upper and any(date_func in query_upper for date_func in ["YEAR(", "MONTH(", "CONVERT(", "FORMAT("]):
            if "HASH GROUP" not in hints:
                hints.append("HASH GROUP")
            if "MAXDOP" not in " ".join(hints):
                hints.append("MAXDOP 4")
        
        # Apply hints if any were identified
        if hints and not query_upper.endswith(";"):
            option_clause = f" OPTION ({', '.join(hints)})"
            query = query + option_clause
            logger.debug(f"Added SQL Server hints: {option_clause}")
        
        return query

    def _track_query_performance(self, query: str, execution_time: float, row_count: int) -> None:
        """Track query performance metrics for optimization learning
        
        Args:
            query: The executed query
            execution_time: Time taken to execute the query
            row_count: Number of rows returned
        """
        # Create a simple hash of the query pattern for tracking
        query_pattern = self._extract_query_pattern(query)
        
        if query_pattern not in self._query_performance_cache:
            self._query_performance_cache[query_pattern] = {
                "avg_time": execution_time,
                "min_time": execution_time,
                "max_time": execution_time,
                "avg_rows": row_count,
                "execution_count": 1
            }
        else:
            stats = self._query_performance_cache[query_pattern]
            stats["execution_count"] += 1
            stats["avg_time"] = (stats["avg_time"] * (stats["execution_count"] - 1) + execution_time) / stats["execution_count"]
            stats["avg_rows"] = (stats["avg_rows"] * (stats["execution_count"] - 1) + row_count) / stats["execution_count"]
            stats["min_time"] = min(stats["min_time"], execution_time)
            stats["max_time"] = max(stats["max_time"], execution_time)
        
        # Log performance insights
        if execution_time > 30:  # Slow query
            logger.warning(f"Slow query detected: {execution_time:.2f}s for pattern {query_pattern}")
        elif execution_time > 10:
            logger.info(f"Medium query time: {execution_time:.2f}s for pattern {query_pattern}")

    def _extract_query_pattern(self, query: str) -> str:
        """Extract a pattern from the query for performance tracking
        
        Args:
            query: SQL query
            
        Returns:
            Simplified query pattern string
        """
        query_upper = query.upper()
        
        # Extract basic pattern
        pattern_parts = []
        
        if "SELECT" in query_upper:
            pattern_parts.append("SELECT")
            
        if "COUNT(" in query_upper:
            pattern_parts.append("COUNT")
        if "SUM(" in query_upper:
            pattern_parts.append("SUM")
        if "AVG(" in query_upper:
            pattern_parts.append("AVG")
        if "GROUP BY" in query_upper:
            pattern_parts.append("GROUP_BY")
        if "ORDER BY" in query_upper:
            pattern_parts.append("ORDER_BY")
        if "WHERE" in query_upper:
            pattern_parts.append("WHERE")
        if "JOIN" in query_upper:
            pattern_parts.append("JOIN")
        if "TOP" in query_upper:
            pattern_parts.append("TOP")
            
        return "_".join(pattern_parts) if pattern_parts else "UNKNOWN"

    def get_performance_insights(self) -> dict[str, Any]:
        """Get performance insights that can inform query optimization
        
        Returns:
            Dictionary with performance insights
        """
        if not self._query_performance_cache:
            return {"insights": "No performance data available yet"}
        
        insights = {
            "total_query_patterns": len(self._query_performance_cache),
            "slow_patterns": [],
            "fast_patterns": [],
            "recommendations": []
        }
        
        for pattern, stats in self._query_performance_cache.items():
            if stats["avg_time"] > 20:
                insights["slow_patterns"].append({
                    "pattern": pattern,
                    "avg_time": round(stats["avg_time"], 2),
                    "avg_rows": round(stats["avg_rows"], 0),
                    "executions": stats["execution_count"]
                })
            elif stats["avg_time"] < 3:
                insights["fast_patterns"].append({
                    "pattern": pattern,
                    "avg_time": round(stats["avg_time"], 2),
                    "avg_rows": round(stats["avg_rows"], 0),
                    "executions": stats["execution_count"]
                })
        
        # Generate recommendations based on patterns
        if insights["slow_patterns"]:
            insights["recommendations"].append(
                "Consider adding WHERE clauses to limit result sets for better performance"
            )
        
        for slow_pattern in insights["slow_patterns"]:
            if "GROUP_BY" not in slow_pattern["pattern"] and slow_pattern["avg_rows"] > 10000:
                insights["recommendations"].append(
                    f"Pattern {slow_pattern['pattern']} might benefit from aggregation or TOP clause"
                )
        
        return insights

    def execute_query_with_optimization(
        self, query: str, timeout: int | None = None, max_rows: int | None = None
    ) -> list[dict[str, Any]]:
        """Execute a query with automatic optimization for large datasets

        Args:
            query: SQL query to execute
            timeout: Query timeout in seconds
            max_rows: Maximum number of rows to return for optimization

        Returns:
            List of dictionaries containing query results
        """
        # Optimize the query if max_rows is specified
        if max_rows:
            optimized_query = self.optimize_query_for_large_datasets(query, max_rows)
            logger.info(f"Executing optimized query with max_rows={max_rows}")
        else:
            optimized_query = query

        return self.execute_query(optimized_query, timeout)

    def execute_query(
        self, query: str, timeout: int | None = None
    ) -> list[dict[str, Any]]:
        """Execute a SQL Server query with automatic pushdown optimizations

        Args:
            query: SQL query to execute
            timeout: Query timeout in seconds (not supported by pytds)

        Returns:
            List of dictionaries containing query results
        """
        timeout = timeout if timeout is not None else self.default_timeout

        # Apply pushdown optimizations if configured
        optimized_query = query
        if self.pushdown_config.should_optimize_query(query):
            optimized_query = self.optimize_query_for_large_datasets(
                query, self.pushdown_config.auto_add_top_limit
            )
            logger.info("Applied pushdown optimization to query")

        cursor = None

        # Track query performance for learning
        query_start_time = time.time()
        
        try:
            with self.create_connection() as conn:
                # Create cursor (as_dict is already set on connection)
                cursor = conn.cursor()

                try:
                    # Execute query (pytds doesn't support per-query timeout)
                    if timeout != self.default_timeout:
                        logger.warning(
                            "pytds does not support per-query timeout, using connection timeout"
                        )

                    columns, rows = self._execute_query_with_retry(
                        cursor, optimized_query
                    )
                    
                    # Track performance metrics
                    execution_time = time.time() - query_start_time
                    self._track_query_performance(query, execution_time, len(rows))

                    # Check for large result sets and warn if configured
                    if (
                        self.pushdown_config.warn_on_large_results
                        and len(rows) > self.pushdown_config.large_result_threshold
                    ):
                        logger.warning(
                            f"Large result set returned: {len(rows)} rows. "
                            f"Consider adding more specific WHERE clauses or using streaming methods."
                        )

                    # Convert to list of dictionaries
                    if cursor.description and rows:
                        # With as_dict=True on connection, rows should be dictionaries
                        if self.pushdown_config.log_query_performance:
                            logger.info(f"Query returned {len(rows)} rows successfully in {execution_time:.2f}s")
                        return rows
                    else:
                        return []

                finally:
                    if cursor:
                        cursor.close()

        except Exception as e:
            error_str = str(e).lower()
            logger.error(f"Query execution failed: {str(e)}")
            logger.error(f"Original query was: {query[:1500]}...")
            if optimized_query != query:
                logger.error(f"Optimized query was: {optimized_query[:1500]}...")
            
            # Handle timeout errors with specific guidance
            if "timed out" in error_str or "timeout" in error_str:
                # Try a simplified query approach for timeouts
                logger.warning("Query timeout detected. Attempting fallback with simpler query...")
                try:
                    fallback_result = self._execute_timeout_fallback(query)
                    if fallback_result:
                        return fallback_result
                except Exception as fallback_error:
                    logger.error(f"Fallback query also failed: {str(fallback_error)}")
                
                raise InvalidGeneratedCode(
                    f"Query timeout: The query is too complex or the dataset is too large. "
                    f"Consider adding more specific WHERE clauses, using smaller date ranges, "
                    f"or limiting the number of rows with TOP clause. Original error: {str(e)}"
                ) from e
            else:
                raise InvalidGeneratedCode(f"Failed to execute SQL query: {str(e)}") from e

    def _execute_timeout_fallback(self, original_query: str) -> list[dict[str, Any]] | None:
        """Execute a simplified version of the query when timeout occurs
        
        Args:
            original_query: The original query that timed out
            
        Returns:
            Simplified query results or None if fallback fails
        """
        try:
            # Create a much more aggressive optimization for timeout scenarios
            query_upper = original_query.upper()
            
            # If it's a complex aggregation, try a much smaller sample
            if any(agg in query_upper for agg in ["GROUP BY", "COUNT(", "SUM(", "AVG("]):
                # Replace any existing TOP with a very small limit
                if "TOP" in query_upper:
                    # Remove existing TOP clause and add our own
                    import re
                    fallback_query = re.sub(r'\bTOP\s+\d+\b', 'TOP 1000', original_query, flags=re.IGNORECASE)
                else:
                    # Add TOP 1000 to the query
                    fallback_query = self.optimize_query_for_large_datasets(original_query, 1000)
                
                logger.info("Attempting timeout fallback with TOP 1000 limit")
                
                with self.create_connection() as conn:
                    cursor = conn.cursor()
                    try:
                        columns, rows = self._execute_query_with_retry(cursor, fallback_query)
                        if rows:
                            logger.info(f"Timeout fallback succeeded: returned {len(rows)} rows")
                            return rows
                    finally:
                        cursor.close()
            
            return None
            
        except Exception as e:
            logger.error(f"Timeout fallback failed: {str(e)}")
            return None

    def execute_query_streaming(
        self, query: str, timeout: int | None = None, chunk_size: int = 10000
    ) -> Generator[list[dict[str, Any]], None, None]:
        """Execute a query and yield results in chunks for memory efficiency

        Args:
            query: SQL query to execute
            timeout: Query timeout in seconds
            chunk_size: Number of rows to fetch per chunk

        Yields:
            Lists of dictionaries containing query results in chunks
        """
        timeout = timeout if timeout is not None else self.default_timeout
        cursor = None

        try:
            with self.create_connection() as conn:
                cursor = conn.cursor()

                try:
                    if timeout != self.default_timeout:
                        logger.warning(
                            "pytds does not support per-query timeout, using connection timeout"
                        )

                    # Execute query
                    start_time = time.time()
                    cursor.execute(query)
                    execution_time = time.time() - start_time

                    logger.info(
                        f"Query executed in {execution_time:.3f}s, starting streaming fetch"
                    )

                    # Stream results in chunks
                    chunk_count = 0
                    total_rows = 0

                    while True:
                        # Fetch chunk
                        chunk_start = time.time()
                        rows = cursor.fetchmany(chunk_size)
                        chunk_time = time.time() - chunk_start

                        if not rows:
                            break

                        chunk_count += 1
                        total_rows += len(rows)

                        logger.debug(
                            f"Fetched chunk {chunk_count}: {len(rows)} rows in {chunk_time:.3f}s"
                        )

                        # Yield chunk as list of dictionaries
                        # With as_dict=True, rows should already be dictionaries
                        yield rows

                    logger.info(
                        f"Streaming complete: {total_rows} total rows in {chunk_count} chunks"
                    )

                finally:
                    if cursor:
                        cursor.close()

        except Exception as e:
            logger.error(f"Streaming query execution failed: {str(e)}")
            logger.error(f"Query was: {query[:1500]}...")
            raise InvalidGeneratedCode(
                f"Failed to execute streaming SQL query: {str(e)}"
            ) from e

    def execute_large_query_safe(
        self, query: str, timeout: int | None = None, max_memory_mb: int = 500
    ) -> list[dict[str, Any]] | str:
        """Execute a query with memory safeguards for large result sets

        Args:
            query: SQL query to execute
            timeout: Query timeout in seconds
            max_memory_mb: Maximum memory to use for results (approximate)

        Returns:
            Query results or error message if too large
        """
        try:
            # Estimate if query might return large results
            if self._might_return_large_results(query):
                logger.info(
                    "Query might return large results, using memory-safe execution"
                )
                return self._execute_with_memory_check(query, timeout, max_memory_mb)
            else:
                # Use normal execution for smaller queries
                return self.execute_query(query, timeout)

        except Exception as e:
            error_msg = f"Large query execution failed: {str(e)}"
            logger.error(error_msg)
            return error_msg

    def _might_return_large_results(self, query: str) -> bool:
        """Heuristic to determine if a query might return large results"""
        query_upper = query.upper()

        # Check for indicators of potentially large results
        large_result_indicators = [
            "SELECT *" in query_upper,
            "TOP" not in query_upper and "LIMIT" not in query_upper,
            "COUNT(" not in query_upper,  # Aggregations are usually small
            "GROUP BY" not in query_upper,  # Grouped results are usually smaller
        ]

        # If multiple indicators are present, assume large results
        return sum(large_result_indicators) >= 2

    def _execute_with_memory_check(
        self, query: str, timeout: int | None, max_memory_mb: int
    ) -> list[dict[str, Any]] | str:
        """Execute query with memory monitoring"""
        import os

        import psutil

        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB

        results = []
        total_size_estimate = 0

        try:
            for chunk in self.execute_query_streaming(query, timeout, chunk_size=1000):
                # Add chunk to results
                results.extend(chunk)

                # Estimate memory usage (rough approximation)
                chunk_size_estimate = len(str(chunk).encode("utf-8"))
                total_size_estimate += chunk_size_estimate

                # Check if we're approaching memory limit
                current_memory = process.memory_info().rss / 1024 / 1024
                memory_used = current_memory - initial_memory

                if memory_used > max_memory_mb:
                    warning_msg = (
                        f"Query results exceeded memory limit ({max_memory_mb}MB). "
                        f"Returned {len(results)} rows. Consider adding LIMIT or more specific WHERE clauses."
                    )
                    logger.warning(warning_msg)
                    return warning_msg

            logger.info(
                f"Large query completed: {len(results)} rows, ~{total_size_estimate / 1024 / 1024:.1f}MB"
            )
            return results

        except Exception as e:
            return f"Memory-safe execution failed: {str(e)}"

    def get_table_as_dataframe(self, query: str, timeout: int | None = None) -> Any:
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

            # Handle large datasets by using pandas as intermediate step
            # This avoids Polars schema inference issues with inconsistent data types
            try:
                # First try direct Polars creation with extended schema inference
                return pl.DataFrame(results, infer_schema_length=10000)
            except Exception as polars_error:
                logger.warning(
                    f"Direct Polars creation failed: {str(polars_error)}, falling back to pandas conversion"
                )

                # Fallback: convert through pandas to handle schema inconsistencies
                import pandas as pd

                # Convert to pandas DataFrame first (more forgiving with mixed types)
                pandas_df = pd.DataFrame(results)

                # Convert pandas DataFrame to Polars
                return pl.from_pandas(pandas_df)

        except Exception as e:
            error_msg = f"Failed to get table as dataframe: {str(e)}"
            logger.error(error_msg)
            return error_msg

    def list_tables(self, schema: str | None = None) -> list[str]:
        """List all tables and views in the database or schema(s)

        Args:
            schema: Schema name to filter tables and views (optional)

        Returns:
            List of table and view names, prefixed with schema if multiple schemas
        """
        # Get schemas to query
        if schema:
            schemas = [schema]
        else:
            schemas = self._credentials.get_schemas_list()
        
        # Build schema filter
        if len(schemas) == 1:
            schema_filter = f"TABLE_SCHEMA = '{schemas[0]}'"
        else:
            schema_list = "', '".join(schemas)
            schema_filter = f"TABLE_SCHEMA IN ('{schema_list}')"

        query = f"""
        SELECT 
            CASE 
                WHEN TABLE_SCHEMA != 'dbo' OR {len(schemas)} > 1
                THEN TABLE_SCHEMA + '.' + TABLE_NAME
                ELSE TABLE_NAME
            END AS TABLE_NAME,
            TABLE_TYPE,
            TABLE_SCHEMA
        FROM INFORMATION_SCHEMA.TABLES 
        WHERE TABLE_TYPE IN ('BASE TABLE', 'VIEW') 
        AND {schema_filter}
        ORDER BY TABLE_SCHEMA, TABLE_TYPE, TABLE_NAME
        """

        try:
            results = self.execute_query(query)
            # Log what types of objects we found
            tables = [
                row["TABLE_NAME"]
                for row in results
                if row["TABLE_TYPE"] == "BASE TABLE"
            ]
            views = [
                row["TABLE_NAME"] for row in results if row["TABLE_TYPE"] == "VIEW"
            ]

            schemas_str = "', '".join(schemas)
            logger.info(
                f"Found {len(tables)} tables and {len(views)} views in schema(s) '{schemas_str}'"
            )
            if tables:
                logger.debug(f"Tables: {', '.join(tables)}")
            if views:
                logger.debug(f"Views: {', '.join(views)}")

            # Return all objects (tables + views)
            return [row["TABLE_NAME"] for row in results]
        except Exception as e:
            logger.error(f"Failed to list tables and views: {str(e)}")
            return []

    def get_table_schema(self, table_name: str, schema: str | None = None) -> str:
        """Get the schema information for a table or view

        Args:
            table_name: Name of the table or view (can be schema-qualified like 'hr.employees')
            schema: Schema name (optional if table_name is schema-qualified)

        Returns:
            String representation of table/view schema
        """
        # Handle schema-qualified table names
        if '.' in table_name and not schema:
            parts = table_name.split('.', 1)
            schema = parts[0]
            table_name = parts[1]
        else:
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
                return f"Table or view {schema}.{table_name} not found"

            # Format schema information
            schema_info = [f"Schema for {schema}.{table_name}:"]
            for col in results:
                col_type = col["DATA_TYPE"]
                if col["CHARACTER_MAXIMUM_LENGTH"]:
                    col_type += f"({col['CHARACTER_MAXIMUM_LENGTH']})"
                nullable = "NULL" if col["IS_NULLABLE"] == "YES" else "NOT NULL"
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
                    # First, get table size information for better diagnostics
                    try:
                        count_query = (
                            f"SELECT COUNT(*) as row_count FROM {qualified_table}"
                        )
                        count_result = self.execute_query(count_query, timeout)
                        total_rows = count_result[0]["row_count"] if count_result else 0
                        logger.info(
                            f"Loading table {table}: {total_rows} total rows, sampling {sample_size} rows"
                        )
                    except Exception:
                        logger.info(
                            f"Loading table {table}: unable to get row count, sampling {sample_size} rows"
                        )

                    df = self.get_table_as_dataframe(query, timeout)

                    if isinstance(df, str):
                        logger.error(f"Failed to fetch data from {table}: {df}")
                        # For large tables, suggest trying with smaller sample size
                        if sample_size > 1000:
                            logger.info(
                                f"Tip: For large tables like {table}, try reducing sample_size below 1000"
                            )
                        continue

                    if df.is_empty():
                        logger.warning(f"Table {table} is empty")
                        continue

                    # Convert Polars DataFrame to pandas for compatibility
                    pandas_df = df.to_pandas()

                    # Log dataframe information for diagnostics
                    logger.info(
                        f"Table {table}: loaded {len(pandas_df)} rows, {len(pandas_df.columns)} columns"
                    )

                    # Check for potential data quality issues
                    if pandas_df.isnull().any().any():
                        null_cols = pandas_df.columns[pandas_df.isnull().any()].tolist()
                        logger.warning(
                            f"Table {table} contains null values in columns: {null_cols}"
                        )

                    # Create dataset object
                    from utils.analyst_db import DataSourceType
                    from utils.schema import AnalystDataset

                    dataset = AnalystDataset(name=table, data=pandas_df)

                    # Register with analyst DB
                    if analyst_db:
                        await analyst_db.register_dataset(
                            dataset, DataSourceType.DATABASE
                        )

                    names.append(table)
                    logger.info(f"Successfully loaded and registered table: {table}")

                except Exception as e:
                    logger.error(f"Error loading table {table}: {str(e)}")
                    logger.error(f"Query attempted: {query}")

                    # Provide helpful error messages based on error type
                    error_str = str(e).lower()
                    if "schema" in error_str or "type" in error_str:
                        logger.error(
                            f"Schema issue detected for table {table}. This may be due to mixed data types in columns."
                        )
                        logger.error(
                            "Try using a smaller sample_size or check for data consistency in the table."
                        )
                    elif "timeout" in error_str:
                        logger.error(
                            f"Timeout loading table {table}. Try increasing timeout or reducing sample_size."
                        )
                    elif "memory" in error_str:
                        logger.error(
                            f"Memory issue loading table {table}. Try reducing sample_size significantly."
                        )

                    continue

            return names

        except Exception as e:
            logger.error(f"Error fetching SQL Server data: {str(e)}")
            return []

    def get_object_type(
        self, object_name: str, schema: str | None = None
    ) -> str | None:
        """Get the type of a database object (TABLE or VIEW)

        Args:
            object_name: Name of the object
            schema: Schema name

        Returns:
            'BASE TABLE', 'VIEW', or None if not found
        """
        schema = schema or self._credentials.db_schema

        query = f"""
        SELECT TABLE_TYPE
        FROM INFORMATION_SCHEMA.TABLES 
        WHERE TABLE_NAME = '{object_name}' 
        AND TABLE_SCHEMA = '{schema}'
        """

        try:
            results = self.execute_query(query)
            if results:
                return results[0]["TABLE_TYPE"]
            return None
        except Exception as e:
            logger.error(f"Failed to get object type for {object_name}: {str(e)}")
            return None

    def list_tables_with_types(self, schema: str | None = None) -> list[dict[str, str]]:
        """List all tables and views with their types

        Args:
            schema: Schema name to filter objects

        Returns:
            List of dictionaries with 'name' and 'type' keys
        """
        schema = schema or self._credentials.db_schema

        query = f"""
        SELECT TABLE_NAME, TABLE_TYPE
        FROM INFORMATION_SCHEMA.TABLES 
        WHERE TABLE_TYPE IN ('BASE TABLE', 'VIEW') 
        AND TABLE_SCHEMA = '{schema}'
        ORDER BY TABLE_TYPE, TABLE_NAME
        """

        try:
            results = self.execute_query(query)
            return [
                {
                    "name": row["TABLE_NAME"],
                    "type": "table" if row["TABLE_TYPE"] == "BASE TABLE" else "view",
                }
                for row in results
            ]
        except Exception as e:
            logger.error(f"Failed to list tables and views with types: {str(e)}")
            return []

    def list_views_only(self, schema: str | None = None) -> list[str]:
        """List only views in the database or schema

        Args:
            schema: Schema name to filter views

        Returns:
            List of view names
        """
        schema = schema or self._credentials.db_schema

        query = f"""
        SELECT TABLE_NAME 
        FROM INFORMATION_SCHEMA.TABLES 
        WHERE TABLE_TYPE = 'VIEW' 
        AND TABLE_SCHEMA = '{schema}'
        ORDER BY TABLE_NAME
        """

        try:
            results = self.execute_query(query)
            view_names = [row["TABLE_NAME"] for row in results]
            logger.info(f"Found {len(view_names)} views in schema '{schema}'")
            return view_names
        except Exception as e:
            logger.error(f"Failed to list views: {str(e)}")
            return []

    def list_tables_only(self, schema: str | None = None) -> list[str]:
        """List only base tables in the database or schema

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
            table_names = [row["TABLE_NAME"] for row in results]
            logger.info(f"Found {len(table_names)} tables in schema '{schema}'")
            return table_names
        except Exception as e:
            logger.error(f"Failed to list tables: {str(e)}")
            return []
