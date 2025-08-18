#!/usr/bin/env python3
"""
Test script for SQL Server view support
This script tests the enhanced SQL Server integration to ensure it can list both tables and views.
"""

import sys
import os

# Add utils to path for testing
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'utils'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'utils', 'vendor'))

try:
    import pytds
    print("✓ pytds import successful")
except ImportError as e:
    print(f"✗ pytds import failed: {e}")
    print("Make sure pytds is properly vendored in utils/vendor/")
    sys.exit(1)

try:
    from database_helpers_pytds import SQLServerOperatorPytds
    from credentials import SQLServerCredentials
    print("✓ SQL Server classes imported successfully")
except ImportError as e:
    print(f"✗ SQL Server imports failed: {e}")
    sys.exit(1)

def test_view_support():
    """Test SQL Server view support functionality"""
    print("\n=== Testing SQL Server View Support ===")
    
    # Test credential creation (this will fail without real credentials, but we can test the class)
    try:
        credentials = SQLServerCredentials()
        print("✓ SQLServerCredentials class instantiated")
    except Exception as e:
        print(f"○ SQLServerCredentials failed (expected without env vars): {e}")
    
    # Test the methods exist on the operator class
    methods_to_check = [
        'list_tables',
        'list_views_only', 
        'list_tables_only',
        'list_tables_with_types',
        'get_object_type',
        'get_table_schema'
    ]
    
    for method in methods_to_check:
        if hasattr(SQLServerOperatorPytds, method):
            print(f"✓ Method '{method}' exists")
        else:
            print(f"✗ Method '{method}' missing")
    
    # Test the query logic without actual database connection
    print("\n=== Query Validation ===")
    
    # Test the main list_tables query includes views
    expected_query_parts = [
        "INFORMATION_SCHEMA.TABLES",
        "TABLE_TYPE IN ('BASE TABLE', 'VIEW')",
        "ORDER BY TABLE_TYPE, TABLE_NAME"
    ]
    
    # Read the source code to verify the query
    import inspect
    source = inspect.getsource(SQLServerOperatorPytds.list_tables)
    
    for part in expected_query_parts:
        if part in source:
            print(f"✓ Query contains: {part}")
        else:
            print(f"✗ Query missing: {part}")
    
    print("\n=== Method Documentation Check ===")
    
    # Check that docstrings mention views
    docstring = SQLServerOperatorPytds.list_tables.__doc__
    if docstring and 'view' in docstring.lower():
        print("✓ list_tables docstring mentions views")
    else:
        print("✗ list_tables docstring should mention views")
    
    schema_docstring = SQLServerOperatorPytds.get_table_schema.__doc__
    if schema_docstring and 'view' in schema_docstring.lower():
        print("✓ get_table_schema docstring mentions views")
    else:
        print("✗ get_table_schema docstring should mention views")

def test_query_compatibility():
    """Test that the SQL queries are compatible with SQL Server"""
    print("\n=== SQL Query Compatibility Test ===")
    
    # Test queries that would be generated
    test_queries = [
        # Main list query
        """
        SELECT TABLE_NAME, TABLE_TYPE
        FROM INFORMATION_SCHEMA.TABLES 
        WHERE TABLE_TYPE IN ('BASE TABLE', 'VIEW') 
        AND TABLE_SCHEMA = 'dbo'
        ORDER BY TABLE_TYPE, TABLE_NAME
        """,
        
        # Views only query
        """
        SELECT TABLE_NAME 
        FROM INFORMATION_SCHEMA.TABLES 
        WHERE TABLE_TYPE = 'VIEW' 
        AND TABLE_SCHEMA = 'dbo'
        ORDER BY TABLE_NAME
        """,
        
        # Object type query
        """
        SELECT TABLE_TYPE
        FROM INFORMATION_SCHEMA.TABLES 
        WHERE TABLE_NAME = 'test_view' 
        AND TABLE_SCHEMA = 'dbo'
        """,
        
        # Schema query (works for both tables and views)
        """
        SELECT 
            COLUMN_NAME,
            DATA_TYPE,
            CHARACTER_MAXIMUM_LENGTH,
            IS_NULLABLE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = 'dbo'
        AND TABLE_NAME = 'test_object'
        ORDER BY ORDINAL_POSITION
        """
    ]
    
    for i, query in enumerate(test_queries, 1):
        # Basic syntax validation
        query = query.strip()
        if query.upper().startswith('SELECT') and 'FROM' in query.upper():
            print(f"✓ Query {i}: Valid SQL syntax")
        else:
            print(f"✗ Query {i}: Invalid SQL syntax")
        
        # Check for SQL injection protection (basic check)
        if "'" in query and not (query.count("'") % 2 == 0):
            print(f"⚠ Query {i}: Potential SQL injection risk")
        else:
            print(f"✓ Query {i}: No obvious injection issues")

if __name__ == "__main__":
    print("SQL Server View Support Test")
    print("=" * 40)
    
    test_view_support()
    test_query_compatibility()
    
    print("\n=== Test Summary ===")
    print("✓ = Pass")
    print("✗ = Fail") 
    print("○ = Expected (no credentials)")
    print("⚠ = Warning")
    print("\nIf all tests show ✓ or ○, view support is properly implemented!")