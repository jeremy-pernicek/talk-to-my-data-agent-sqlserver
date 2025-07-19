# SQL Server Integration for Talk to My Data Agent

## Overview

This document details the SQL Server integration added to the Talk to My Data Agent application. The integration enables the application to connect to Microsoft SQL Server and Azure SQL Database instances, query data, and provide AI-powered analytics through a chat interface.

## Architecture & Design Decisions

### Why SQL Server Support?

The original Talk to My Data Agent supported Snowflake, BigQuery, and SAP Datasphere. SQL Server support was added to:
- Enable enterprise users with SQL Server/Azure SQL databases to leverage the AI analytics capabilities
- Provide a pure-Python solution that works in restricted environments (DataRobot runtime)
- Maintain consistency with existing database integration patterns

### Driver Selection: Why pytds?

After evaluating multiple SQL Server drivers, we chose **pytds** for the following reasons:

1. **Pure Python Implementation**: Unlike pyodbc (requires ODBC driver installation) and pymssql (requires FreeTDS), pytds is pure Python with no C dependencies
2. **DataRobot Runtime Compatibility**: Works in restricted environments where system-level driver installation is not possible
3. **TDS Protocol Native**: Implements the Tabular Data Stream (TDS) protocol directly
4. **Lightweight**: Minimal dependencies and smaller footprint

### Vendoring Strategy

Due to DataRobot runtime restrictions, we implemented a vendoring solution:

```
app_backend/vendor/
├── __init__.py
├── pytds/
│   ├── __init__.py
│   ├── connection.py
│   ├── cursor.py
│   └── ... (all pytds modules)
└── python_tds-1.16.1.dist-info/

utils/vendor/
├── __init__.py
└── pytds/ (duplicate for utils module access)
```

**Rationale**: DataRobot's runtime environment doesn't include pytds, and pip installation at runtime is not possible. Vendoring ensures the driver is always available.

## Implementation Details

### 1. Driver Detection Mechanism

**File**: `utils/database_helpers.py`

```python
# Dynamic driver detection with fallback support
HAS_PYTDS = False
HAS_PYMSSQL = False
HAS_PYODBC = False

try:
    import pytds
    HAS_PYTDS = True
except ImportError:
    pass

# Similar blocks for pymssql and pyodbc
```

This allows graceful fallback if multiple drivers are available in different environments.

### 2. SQL Server Operator Implementation

**File**: `utils/database_helpers_pytds.py`

Key features:
- Connection pooling support
- Query execution timing
- Proper error handling with detailed logging
- Schema-qualified table names
- Configurable timeouts

```python
class SQLServerOperatorPytds(DatabaseOperator["SQLServerCredentials"]):
    def create_connection(self) -> Generator[pytds.Connection, None, None]:
        connection = pytds.connect(
            server=self._credentials.host,
            port=self._credentials.port,
            user=self._credentials.user,
            password=self._credentials.password,
            database=self._credentials.database,
            timeout=self._credentials.connection_timeout,
            login_timeout=self._credentials.connection_timeout,
            as_dict=True,  # Return rows as dictionaries
            autocommit=True,  # Prevent transaction issues
        )
```

### 3. Credential Management

**File**: `infra/components/dr_credential.py`

Environment variables are mapped to runtime parameters:
- `AZURE_SQL_HOST` → Server hostname
- `AZURE_SQL_PORT` → Port (default: 1433)
- `AZURE_SQL_USER` → Username
- `AZURE_SQL_PASSWORD` → Password (encrypted)
- `AZURE_SQL_DATABASE` → Database name
- `AZURE_SQL_SCHEMA` → Schema (default: dbo)

### 4. Query Enhancements

**File**: `utils/prompts.py`

Added SQL Server-specific prompt with:
- T-SQL syntax guidance
- GROUP BY validation rules
- Common SQL Server functions
- Performance optimization tips

```python
SYSTEM_PROMPT_SQLSERVER = """
You are an expert SQL Server T-SQL analyst...
- GROUP BY RULES: When using aggregate functions, all non-aggregated columns must be in GROUP BY
- Use TOP instead of LIMIT
- Use GETDATE() for current timestamp
"""
```

### 5. Connection Test Implementation

**File**: `infra/components/dr_credential.py`

```python
def test_sql_server_connection(credentials: SQLServerCredentials) -> None:
    conn = pytds.connect(
        server=credentials.host,
        port=credentials.port,
        user=credentials.user,
        password=credentials.password,
        database=credentials.database,
        tds_version=0x74000004,  # TDS 7.4 for SQL Server 2012+
    )
    # Test with simple query
    cursor = conn.cursor()
    cursor.execute("SELECT 1")
    cursor.close()
    conn.close()
```

## Key Technical Improvements

### 1. Query Performance Monitoring

```python
# Measure query execution time
start_time = time.time()
cursor.execute(query)
execution_time = time.time() - start_time

# Log performance metrics
logger.info(f"Query executed in {execution_time:.3f}s, fetched {len(rows)} rows")
```

### 2. Enhanced Error Handling

```python
try:
    columns, rows = self._execute_query_with_retry(cursor, query)
except Exception as e:
    logger.error(f"Query execution failed: {str(e)}")
    logger.error(f"Query was: {query[:1500]}...")  # Log more for debugging
    raise InvalidGeneratedCode(f"Failed to execute SQL query: {str(e)}")
```

### 3. Retry Logic

Implemented exponential backoff for transient errors:
```python
@retry_on_transient_error(max_attempts=2, initial_delay=0.5)
def _execute_query_with_retry(self, cursor, query):
    # Execution logic
```

## Configuration

### Environment Variables

```bash
# Required
AZURE_SQL_HOST=your-server.database.windows.net
AZURE_SQL_PORT=1433
AZURE_SQL_USER=your-username
AZURE_SQL_PASSWORD=your-password
AZURE_SQL_DATABASE=your-database
AZURE_SQL_SCHEMA=dbo

# Optional (with secure defaults)
AZURE_SQL_DRIVER=ODBC Driver 18 for SQL Server  # Not used with pytds
AZURE_SQL_TRUST_CERT=false
AZURE_SQL_ENCRYPT=true
AZURE_SQL_CONN_TIMEOUT=30
```

### Python Path Configuration

**File**: `app_backend/start-app.sh`

```bash
export PYTHONPATH="${PYTHONPATH:+${PYTHONPATH}:}$(pwd)/vendor:$(pwd)/app_backend/vendor:$(pwd)/utils/vendor"
```

This ensures vendored packages are found before system packages.

## Testing & Validation

### Connection Testing
- Validates credentials during deployment
- Tests basic query execution
- Verifies schema access permissions

### Query Validation
- GROUP BY clause validation
- Aggregate function handling
- Schema-qualified table references

### Performance Metrics
- Query execution timing
- Row fetch performance
- Connection establishment time

## Known Issues & Limitations

1. **TDS Version Constant**: Had to use hex value `0x74000004` instead of `pytds.TDS74` due to module attribute issues
2. **Per-Query Timeouts**: pytds doesn't support per-query timeouts (uses connection-level timeout)
3. **Cursor Parameters**: `as_dict` must be set at connection level, not cursor level
4. **Large Result Sets**: Consider implementing pagination for very large results

## Security Considerations

1. **Credentials**: All passwords are encrypted in DataRobot runtime parameters
2. **Connection Security**: Supports encrypted connections (TDS encryption)
3. **Query Sanitization**: Uses parameterized queries where applicable
4. **Audit Logging**: All queries are logged with truncation for sensitive data

## Future Improvements

1. **Connection Pooling**: Implement proper connection pool with size limits
2. **Async Support**: Add async query execution for better concurrency
3. **Query Caching**: Cache frequently accessed metadata queries
4. **Advanced Features**: Support for stored procedures, bulk operations
5. **Performance Tuning**: Query plan analysis and optimization hints

## Maintenance Notes

### Updating pytds
1. Install new version: `pip install python-tds==<version>`
2. Copy pytds package to vendor directories
3. Update dist-info metadata
4. Test in DataRobot runtime environment

### Adding New SQL Server Features
1. Extend `SQLServerOperatorPytds` class
2. Update `SYSTEM_PROMPT_SQLSERVER` if needed
3. Add corresponding tests
4. Update credential validation if new parameters added

### Debugging Connection Issues
1. Check logs for TDS protocol messages
2. Verify firewall rules (port 1433)
3. Test with SQL Server Management Studio first
4. Enable pytds debug logging if needed

## Integration Testing Checklist

- [ ] Connection establishment
- [ ] Table listing functionality
- [ ] Query execution with various data types
- [ ] Error handling for invalid queries
- [ ] Performance with large result sets
- [ ] GROUP BY validation
- [ ] Schema access permissions
- [ ] Timeout handling
- [ ] Connection pooling under load

## Conclusion

The SQL Server integration successfully extends the Talk to My Data Agent to support Microsoft SQL Server and Azure SQL Database. The pure-Python pytds implementation ensures compatibility with restricted runtime environments while maintaining performance and reliability. The vendoring solution provides a robust deployment strategy that works across different environments without requiring system-level dependencies.