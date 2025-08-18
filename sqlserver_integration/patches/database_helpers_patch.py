"""
SQL Server Integration Patch for database_helpers.py
This file contains the modifications needed to add SQL Server support to database_helpers.py
"""

# Add these imports at the beginning of the file (after existing imports)
ADDITIONAL_IMPORTS = """
import logging
import time
from typing import Callable

# Get a temporary logger for import diagnostics
_import_logger = logging.getLogger("DatabaseHelper.imports")

# Try to import SQL Server drivers
# DataRobot runtime may have different drivers available
HAS_PYTDS = False
HAS_PYMSSQL = False
HAS_PYODBC = False
SQL_DRIVER_ERROR = None

try:
    import pytds
    HAS_PYTDS = True
    _import_logger.info("pytds driver is available")
except ImportError as e:
    SQL_DRIVER_ERROR = f"pytds not available: {str(e)}"
    _import_logger.warning(SQL_DRIVER_ERROR)
    
    # Log diagnostic information
    import os
    import sys
    
    _import_logger.warning(f"Python path: {sys.path}")
    _import_logger.warning(f"Current working directory: {os.getcwd()}")
    _import_logger.warning(f"Script location: {__file__}")
    _import_logger.warning(f"PYTHONPATH env: {os.environ.get('PYTHONPATH', 'Not set')}")
    
    pytds = None  # type: ignore

try:
    import pymssql
    HAS_PYMSSQL = True
    _import_logger.info("pymssql driver is available")
except ImportError:
    _import_logger.warning("pymssql not available")
    pymssql = None  # type: ignore

try:
    import pyodbc
    HAS_PYODBC = True
    _import_logger.info("pyodbc driver is available")
except ImportError:
    _import_logger.warning("pyodbc not available")
    pyodbc = None  # type: ignore
"""

# Add SQLServerCredentials to the import from utils.credentials
CREDENTIALS_IMPORT_ADDITION = "SQLServerCredentials,"

# Add SYSTEM_PROMPT_SQLSERVER to the import from utils.prompts
PROMPTS_IMPORT_ADDITION = "SYSTEM_PROMPT_SQLSERVER,"

# Add this retry decorator function after the imports section
RETRY_DECORATOR = """
def retry_on_transient_error(
    max_attempts: int = 3, initial_delay: float = 1.0
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    \"\"\"Decorator to retry operations on transient errors
    
    Args:
        max_attempts: Maximum number of retry attempts
        initial_delay: Initial delay between retries in seconds
    \"\"\"

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception = None
            delay = initial_delay
            
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    error_msg = str(e).lower()
                    
                    # Check if it's a transient error
                    transient_keywords = [
                        "timeout",
                        "connection",
                        "network",
                        "temporarily",
                        "deadlock",
                        "busy",
                    ]
                    
                    if any(keyword in error_msg for keyword in transient_keywords):
                        if attempt < max_attempts - 1:
                            logger = get_logger()
                            logger.warning(
                                f"Transient error on attempt {attempt + 1}/{max_attempts}: {e}. "
                                f"Retrying in {delay} seconds..."
                            )
                            time.sleep(delay)
                            delay *= 2  # Exponential backoff
                            continue
                    
                    # Not a transient error or last attempt
                    raise
            
            # This should never be reached, but just in case
            if last_exception:
                raise last_exception
            raise RuntimeError("Unexpected retry loop exit")
        
        return wrapper
    
    return decorator
"""

# Add SQL Server operator registration in the get_db_datasource function
# This should be added as an elif block after the SAP Datasphere block
SQL_SERVER_REGISTRATION = """
    elif app_infra.database == "sqlserver":
        try:
            credentials = SQLServerCredentials()
            if credentials.is_configured():
                # Log available SQL drivers
                logger.info(
                    f"SQL Server drivers available - pytds: {HAS_PYTDS}, pymssql: {HAS_PYMSSQL}, pyodbc: {HAS_PYODBC}"
                )
                
                # Try to import the pytds implementation
                try:
                    from .database_helpers_pytds import SQLServerOperatorPytds
                    
                    logger.info(
                        "Using pytds driver for SQL Server connection from database_helpers_pytds module"
                    )
                    return SQLServerOperatorPytds(credentials)
                except ImportError as e:
                    logger.warning(f"Could not import database_helpers_pytds: {e}")
                    
                    # Fallback: Check which SQL Server driver is available
                    if HAS_PYTDS:
                        logger.error("pytds is available but database_helpers_pytds module not found")
                        raise ImportError(
                            "SQL Server support files missing. Please ensure database_helpers_pytds.py is present."
                        )
                    elif HAS_PYMSSQL:
                        raise NotImplementedError(
                            "pymssql driver detected but not yet implemented. Please use pytds."
                        )
                    elif HAS_PYODBC:
                        raise NotImplementedError(
                            "pyodbc driver detected but not yet implemented. Please use pytds."
                        )
                    else:
                        if SQL_DRIVER_ERROR:
                            raise ImportError(
                                f"No SQL Server driver available. {SQL_DRIVER_ERROR}"
                            )
                        else:
                            raise ImportError(
                                "No SQL Server driver available. Please install pytds: pip install python-tds"
                            )
            else:
                logger.warning(
                    "SQL Server credentials not properly configured, falling back to no database"
                )
        except (ValidationError, ValueError) as e:
            logger.warning(
                f"SQL Server configuration error: {e}, falling back to no database"
            )
        except ImportError as e:
            logger.error(f"SQL Server import error: {e}, falling back to no database")
        return NoDatabaseOperator(NoDatabaseCredentials())
"""

# Instructions for applying the patch
PATCH_INSTRUCTIONS = """
To apply this patch to database_helpers.py:

1. Add the ADDITIONAL_IMPORTS block after the existing imports
2. Add SQLServerCredentials to the credentials import line
3. Add SYSTEM_PROMPT_SQLSERVER to the prompts import line
4. Add the RETRY_DECORATOR function after the imports section
5. Add the SQL_SERVER_REGISTRATION block in get_db_datasource() after the SAP block

The patch is designed to be modular and non-invasive to the existing code.
"""