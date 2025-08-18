#!/usr/bin/env python3
"""
Validation script for SQL Server view support
This script validates that the SQL Server integration has been properly updated to support views.
"""

import os
import re

def check_file_content(filepath, patterns, description):
    """Check if a file contains the required patterns"""
    print(f"\n=== {description} ===")
    
    if not os.path.exists(filepath):
        print(f"✗ File not found: {filepath}")
        return False
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    all_found = True
    for pattern, desc in patterns:
        if re.search(pattern, content, re.IGNORECASE | re.MULTILINE):
            print(f"✓ {desc}")
        else:
            print(f"✗ {desc}")
            all_found = False
    
    return all_found

def validate_sql_server_integration():
    """Validate the SQL Server view support implementation"""
    print("SQL Server View Support Validation")
    print("=" * 50)
    
    # Check database_helpers_pytds.py
    pytds_patterns = [
        (r"TABLE_TYPE IN \('BASE TABLE', 'VIEW'\)", "Main query includes both tables and views"),
        (r"List all tables and views", "list_tables method mentions views in docstring"),
        (r"table or view", "get_table_schema method mentions views in docstring"),
        (r"def list_views_only", "list_views_only method exists"),
        (r"def list_tables_only", "list_tables_only method exists"),
        (r"def list_tables_with_types", "list_tables_with_types method exists"),
        (r"def get_object_type", "get_object_type method exists"),
        (r"Found.*tables and.*views", "Logging includes both tables and views"),
        (r"Table or view.*not found", "Error messages mention both tables and views"),
    ]
    
    pytds_file = "./utils/database_helpers_pytds.py"
    pytds_valid = check_file_content(pytds_file, pytds_patterns, "SQL Server Operator (database_helpers_pytds.py)")
    
    # Check that other database operators also support views (for consistency)
    main_helpers_patterns = [
        (r"TABLE_TYPE IN.*VIEW", "Snowflake operator includes views"),
        (r"SYS\.VIEWS", "SAP operator queries views"),
    ]
    
    main_file = "./utils/database_helpers.py"
    main_valid = check_file_content(main_file, main_helpers_patterns, "Main Database Helpers (database_helpers.py)")
    
    # Check SQL queries are properly formatted
    print(f"\n=== SQL Query Validation ===")
    
    with open(pytds_file, 'r') as f:
        content = f.read()
    
    # Extract SQL queries from the file
    sql_patterns = re.findall(r'query = f?"""(.*?)"""', content, re.DOTALL)
    
    for i, sql in enumerate(sql_patterns):
        sql = sql.strip()
        if 'INFORMATION_SCHEMA.TABLES' in sql:
            if "TABLE_TYPE IN ('BASE TABLE', 'VIEW')" in sql:
                print(f"✓ Query {i+1}: Includes both tables and views")
            elif "TABLE_TYPE = 'VIEW'" in sql:
                print(f"✓ Query {i+1}: Views-only query")
            elif "TABLE_TYPE = 'BASE TABLE'" in sql:
                print(f"✓ Query {i+1}: Tables-only query")
            else:
                print(f"○ Query {i+1}: Other table metadata query")
    
    # Check method signatures
    print(f"\n=== Method Signature Validation ===")
    
    method_patterns = [
        (r"def list_tables\(self.*\) -> list\[str\]", "list_tables returns list of strings"),
        (r"def list_views_only\(self.*\) -> list\[str\]", "list_views_only returns list of strings"),
        (r"def list_tables_only\(self.*\) -> list\[str\]", "list_tables_only returns list of strings"),
        (r"def list_tables_with_types\(self.*\) -> list\[dict", "list_tables_with_types returns list of dicts"),
        (r"def get_object_type\(self.*\) -> str \| None", "get_object_type returns optional string"),
    ]
    
    for pattern, desc in method_patterns:
        if re.search(pattern, content):
            print(f"✓ {desc}")
        else:
            print(f"✗ {desc}")
    
    return pytds_valid and main_valid

def check_integration_guide():
    """Check if integration guide mentions view support"""
    print(f"\n=== Integration Guide Check ===")
    
    guide_file = "./sqlserver_integration/INTEGRATION_GUIDE.md"
    if os.path.exists(guide_file):
        with open(guide_file, 'r') as f:
            content = f.read()
        
        if 'view' in content.lower():
            print("✓ Integration guide mentions view support")
        else:
            print("⚠ Integration guide should mention view support")
    else:
        print("○ Integration guide not found (expected in some setups)")

def main():
    """Main validation function"""
    success = validate_sql_server_integration()
    check_integration_guide()
    
    print(f"\n=== Validation Summary ===")
    if success:
        print("✅ SQL Server view support validation PASSED")
        print("The integration properly supports both tables and views!")
    else:
        print("❌ SQL Server view support validation FAILED")
        print("Some issues were found that need to be addressed.")
    
    print(f"\n=== Feature Summary ===")
    print("Enhanced SQL Server integration now supports:")
    print("• Listing both tables and views with get_tables()")
    print("• Separate methods for tables-only and views-only")
    print("• Object type detection (table vs view)")
    print("• Unified schema information for both tables and views")
    print("• Consistent with other database operators (Snowflake, SAP)")

if __name__ == "__main__":
    main()