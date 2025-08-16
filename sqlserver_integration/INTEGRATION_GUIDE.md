# SQL Server Integration Guide for Talk to My Data Agent

## Overview

This guide provides step-by-step instructions for adding SQL Server support to the Talk to My Data Agent application. The integration is designed to be modular and can be applied to future versions of the main repository.

## Integration Components

The SQL Server integration consists of the following components:

### 1. Core Files
- `utils/database_helpers_pytds.py` - SQL Server operator implementation using pytds
- `utils/vendor/pytds/` - Vendored pytds library for pure Python support
- `app_backend/vendor/pytds/` - Duplicate vendor for app_backend access

### 2. Modified Files
- `utils/database_helpers.py` - Added SQL Server driver detection and operator registration
- `utils/credentials.py` - Added SQLServerCredentials class
- `utils/prompts.py` - Added SYSTEM_PROMPT_SQLSERVER
- `utils/schema.py` - Added "sqlserver" to DatabaseConnectionType
- `infra/settings_database.py` - Updated comment to include "sqlserver"
- `infra/components/dr_credential.py` - Added SQL Server credential handling

## Step-by-Step Integration Process

### Step 1: Copy Vendor Directories
```bash
# Copy pytds vendor to utils
cp -r sqlserver_integration/vendor/pytds talk-to-my-data-agent/utils/vendor/

# Copy pytds vendor to app_backend
cp -r sqlserver_integration/vendor/pytds talk-to-my-data-agent/app_backend/vendor/

# Ensure __init__.py exists in vendor directories
touch talk-to-my-data-agent/utils/vendor/__init__.py
touch talk-to-my-data-agent/app_backend/vendor/__init__.py
```

### Step 2: Copy SQL Server Operator
```bash
cp sqlserver_integration/database_helpers_pytds.py talk-to-my-data-agent/utils/
```

### Step 3: Update database_helpers.py

Add the following imports at the beginning:
```python
import logging
import time
from typing import Callable

# SQL Server driver detection
_import_logger = logging.getLogger("DatabaseHelper.imports")
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
    pytds = None  # type: ignore

# Similar blocks for pymssql and pyodbc...
```

Add to credentials import:
```python
from utils.credentials import (
    # ... existing imports ...
    SQLServerCredentials,
)
```

Add to prompts import:
```python
from utils.prompts import (
    # ... existing imports ...
    SYSTEM_PROMPT_SQLSERVER,
)
```

Add the retry decorator after logger initialization:
```python
def retry_on_transient_error(
    max_attempts: int = 3, initial_delay: float = 1.0
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    # ... (see patches/database_helpers_patch.py for full implementation)
```

Add SQL Server registration in `get_database_operator()` after SAP block:
```python
elif app_infra.database == "sqlserver":
    try:
        credentials = SQLServerCredentials()
        if credentials.is_configured():
            # Try to import the pytds implementation
            try:
                from .database_helpers_pytds import SQLServerOperatorPytds
                return SQLServerOperatorPytds(credentials)
            except ImportError as e:
                # Handle import errors...
    # ... error handling ...
```

### Step 4: Update credentials.py

Add import:
```python
from pydantic import AliasChoices, AliasPath, Field, field_validator
```

Add SQLServerCredentials class before NoDatabaseCredentials:
```python
class SQLServerCredentials(DRCredentials):
    """SQL Server Connection credentials."""
    
    host: str = Field(
        validation_alias=AliasChoices(
            AliasPath("MLOPS_RUNTIME_PARAM_AZURE_SQL_HOST"),
            "AZURE_SQL_HOST",
        ),
    )
    port: int = Field(
        default=1433,
        validation_alias=AliasChoices(
            AliasPath("MLOPS_RUNTIME_PARAM_AZURE_SQL_PORT"),
            "AZURE_SQL_PORT",
        ),
    )
    # ... (see full implementation in the actual file)
    
    def is_configured(self) -> bool:
        return bool(
            self.host and self.port and self.user 
            and self.password and self.database and self.db_schema
        )
```

### Step 5: Update schema.py

Change DatabaseConnectionType:
```python
DatabaseConnectionType = Literal["snowflake", "bigquery", "sap", "sqlserver", "no_database"]
```

### Step 6: Update prompts.py

Add SYSTEM_PROMPT_SQLSERVER at the end of the file:
```python
SYSTEM_PROMPT_SQLSERVER = """
ROLE:
Your job is to write a Microsoft SQL Server (T-SQL) query...
# ... (see full prompt in prompts.py)
"""
```

### Step 7: Update infra/components/dr_credential.py

Add SQLServerCredentials to imports:
```python
from utils.credentials import (
    # ... existing imports ...
    SQLServerCredentials,
)
```

Add SQL Server runtime parameters in construct_runtime_parameter_values():
```python
elif isinstance(credentials, SQLServerCredentials):
    rtps = [
        {
            "key": "db_credential",
            "type": "basic_credential",
            "value": {
                "user": credentials.user,
                "password": credentials.password,
            },
        },
        # ... (see full implementation)
    ]
```

Add SQL Server in get_database_credentials():
```python
elif database == "sqlserver":
    credentials = SQLServerCredentials()
    if test_credentials:
        # Test connection with pytds
        # ... (see full implementation)
    return credentials
```

Update type hints to include SQLServerCredentials.

### Step 8: Update infra/settings_database.py

Update comment:
```python
# Valid values are: "snowflake", "bigquery", "sap", "sqlserver" or "no_database"
```

## Environment Variables

The SQL Server integration requires these environment variables:

```bash
# Required
AZURE_SQL_HOST=your-server.database.windows.net
AZURE_SQL_PORT=1433
AZURE_SQL_USER=your-username
AZURE_SQL_PASSWORD=your-password
AZURE_SQL_DATABASE=your-database
AZURE_SQL_SCHEMA=dbo

# Optional
AZURE_SQL_DRIVER=ODBC Driver 18 for SQL Server
AZURE_SQL_TRUST_CERT=false
AZURE_SQL_ENCRYPT=true
AZURE_SQL_CONN_TIMEOUT=30

# In settings
DATABASE_CONNECTION_TYPE=sqlserver
```

## Testing the Integration

1. Set environment variables in `.env`
2. Run `source set_env.sh` (or `set_env.bat` on Windows)
3. Test database connection:
   ```python
   from utils.database_helpers import get_database_operator
   from utils.schema import AppInfra
   
   app_infra = AppInfra(llm="azure_openai", database="sqlserver")
   operator = get_database_operator(app_infra)
   tables = operator.get_tables()
   print(f"Connected! Found {len(tables)} tables")
   ```

## Updating pytds

If you need to update the pytds version:

1. Install new version:
   ```bash
   pip install python-tds==<new_version>
   ```

2. Copy to vendor directories:
   ```bash
   cp -r <site-packages>/pytds sqlserver_integration/vendor/
   cp -r <site-packages>/pytds talk-to-my-data-agent/utils/vendor/
   cp -r <site-packages>/pytds talk-to-my-data-agent/app_backend/vendor/
   ```

3. Test the integration

## Troubleshooting

### Import Errors
- Check PYTHONPATH includes vendor directories
- Verify pytds is properly vendored in both utils and app_backend

### Connection Errors
- Verify SQL Server allows remote connections
- Check firewall rules for port 1433
- Test with SQL Server Management Studio first
- Enable pytds debug logging if needed

### Query Errors
- Remember GROUP BY rules: all non-aggregated columns must be in GROUP BY
- Use TOP instead of LIMIT
- Use square brackets for identifiers with spaces
- Use GETDATE() for current timestamp

## View Support

The SQL Server integration provides full support for both database tables and views:

### Features
- **Unified Listing**: `get_tables()` returns both tables and views
- **Type Detection**: Methods to distinguish between tables and views
- **Schema Information**: `get_table_schema()` works for both tables and views
- **Query Support**: Views can be queried exactly like tables

### Additional Methods
The integration includes specialized methods for working with views:

```python
# List only views
views = operator.list_views_only()

# List only tables  
tables = operator.list_tables_only()

# List with type information
objects = operator.list_tables_with_types()
# Returns: [{"name": "MyTable", "type": "table"}, {"name": "MyView", "type": "view"}]

# Check object type
object_type = operator.get_object_type("MyView")  # Returns "VIEW"
```

### Implementation Details
- Uses `INFORMATION_SCHEMA.TABLES` with `TABLE_TYPE IN ('BASE TABLE', 'VIEW')`
- Consistent with Snowflake, BigQuery, and SAP Datasphere implementations
- Proper logging distinguishes between tables and views for debugging
- T-SQL prompt includes view-specific guidance

### Testing View Support
```python
# Test that views are included
all_objects = operator.get_tables()
views_only = operator.list_views_only()
tables_only = operator.list_tables_only()

# Verify counts match
assert len(all_objects) == len(views_only) + len(tables_only)

# Test view querying
view_schema = operator.get_table_schema("MyView")
query_result = operator.execute_query("SELECT TOP 5 * FROM MyView")
```

## Future Maintenance

When merging updates from the main repository:

1. Pull latest from main repository
2. Apply this integration guide step by step
3. Test all database connections
4. Verify SQL Server specific features work correctly

The modular design ensures the SQL Server integration can be cleanly applied to future versions without major conflicts.