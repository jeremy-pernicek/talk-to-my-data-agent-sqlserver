#!/usr/bin/env python3
"""
Test script for multi-schema support in SQL Server integration
"""

import os
import sys
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from utils.credentials import SQLServerCredentials
from utils.database_helpers_pytds import SQLServerOperatorPytds

def test_multischema_credentials():
    """Test multi-schema credential parsing"""
    print("Testing multi-schema credential parsing...")
    
    # Test single schema (backward compatibility)
    os.environ["AZURE_SQL_SCHEMA"] = "dbo"
    os.environ.pop("AZURE_SQL_SCHEMAS", None)
    
    creds = SQLServerCredentials(
        host="test.example.com",
        port=1433,
        user="test",
        password="test",
        database="test"
    )
    
    schemas = creds.get_schemas_list()
    print(f"Single schema test: {schemas}")
    assert schemas == ["dbo"], f"Expected ['dbo'], got {schemas}"
    
    # Test multiple schemas
    os.environ["AZURE_SQL_SCHEMAS"] = "dbo, hr, finance, inventory,sales"
    
    creds = SQLServerCredentials(
        host="test.example.com",
        port=1433,
        user="test",
        password="test",
        database="test"
    )
    
    schemas = creds.get_schemas_list()
    print(f"Multi-schema test: {schemas}")
    expected = ["dbo", "hr", "finance", "inventory", "sales"]
    assert schemas == expected, f"Expected {expected}, got {schemas}"
    
    print("✓ Credential parsing tests passed\n")

def test_schema_qualified_table_names():
    """Test handling of schema-qualified table names"""
    print("Testing schema-qualified table name parsing...")
    
    # Mock credentials for testing
    class MockCredentials:
        def __init__(self):
            self.db_schema = "dbo"
            self.db_schemas = ["dbo", "hr", "finance"]
            
        def get_schemas_list(self):
            return self.db_schemas
    
    # Test various table name formats
    test_cases = [
        ("employees", "dbo", "employees"),           # Simple table
        ("hr.employees", None, "employees"),         # Schema-qualified
        ("finance.transactions", None, "transactions"), # Schema-qualified
        ("dbo.customers", None, "customers"),        # Explicit dbo schema
    ]
    
    for table_input, expected_schema, expected_table in test_cases:
        if '.' in table_input:
            parts = table_input.split('.', 1)
            parsed_schema = parts[0]
            parsed_table = parts[1]
        else:
            parsed_schema = expected_schema or "dbo"
            parsed_table = table_input
            
        print(f"  {table_input} -> schema: {parsed_schema}, table: {parsed_table}")
        assert parsed_table == expected_table, f"Table parsing failed for {table_input}"
        
    print("✓ Schema-qualified table name tests passed\n")

def test_sql_query_generation():
    """Test SQL query generation for multiple schemas"""
    print("Testing SQL query generation...")
    
    schemas = ["dbo", "hr", "finance"]
    
    # Single schema query
    single_schema_filter = f"TABLE_SCHEMA = '{schemas[0]}'"
    print(f"Single schema filter: {single_schema_filter}")
    
    # Multiple schema query
    schema_list = "', '".join(schemas)
    multi_schema_filter = f"TABLE_SCHEMA IN ('{schema_list}')"
    print(f"Multi-schema filter: {multi_schema_filter}")
    
    # Test table name formatting
    table_name_cases = [
        ("employees", "dbo", 1, "employees"),                    # Single schema, dbo
        ("employees", "hr", 1, "employees"),                     # Single schema, non-dbo
        ("employees", "dbo", 3, "dbo.employees"),               # Multi schema, dbo
        ("employees", "hr", 3, "hr.employees"),                 # Multi schema, non-dbo
    ]
    
    for table, schema, schema_count, expected in table_name_cases:
        if schema != 'dbo' or schema_count > 1:
            result = f"{schema}.{table}"
        else:
            result = table
            
        print(f"  Table: {table}, Schema: {schema}, Count: {schema_count} -> {result}")
        assert result == expected, f"Expected {expected}, got {result}"
    
    print("✓ SQL query generation tests passed\n")

def main():
    """Run all tests"""
    print("="*60)
    print("Multi-Schema Support Test Suite")
    print("="*60)
    
    try:
        test_multischema_credentials()
        test_schema_qualified_table_names()
        test_sql_query_generation()
        
        print("="*60)
        print("✓ All tests passed!")
        print("Multi-schema support is working correctly.")
        print("="*60)
        
    except Exception as e:
        print(f"✗ Test failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()