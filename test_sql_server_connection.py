#!/usr/bin/env python3
"""
Test SQL Server connection and table listing
Run this to diagnose SQL Server integration issues
"""

import logging
import sys

# Setup logging
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Add utils to path
sys.path.insert(0, "utils")
sys.path.insert(0, "utils/vendor")


def test_app_infra():
    """Test app infrastructure configuration"""
    print("=== Testing App Infrastructure ===")

    try:
        from utils.database_helpers import load_app_infra

        app_infra = load_app_infra()
        print(f"✓ App infra loaded: {app_infra}")
        print(f"✓ Database type: {app_infra.database}")
        print(f"✓ LLM type: {app_infra.llm}")
        return app_infra
    except Exception as e:
        print(f"✗ Failed to load app infra: {e}")
        return None


def test_sql_server_credentials():
    """Test SQL Server credentials"""
    print("\n=== Testing SQL Server Credentials ===")

    try:
        from utils.credentials import SQLServerCredentials

        # Try to create credentials
        credentials = SQLServerCredentials()
        print("✓ SQLServerCredentials created")

        # Check if configured
        is_configured = credentials.is_configured()
        print(f"✓ Is configured: {is_configured}")

        if is_configured:
            print(f"✓ Host: {credentials.host}")
            print(f"✓ Port: {credentials.port}")
            print(f"✓ Database: {credentials.database}")
            print(f"✓ Schema: {credentials.db_schema}")
            print(f"✓ User: {credentials.user}")
            print(
                f"✓ Password: {'*' * len(credentials.password) if credentials.password else 'Not set'}"
            )
        else:
            print("✗ SQL Server credentials not configured")
            print("Required environment variables:")
            print("  AZURE_SQL_HOST")
            print("  AZURE_SQL_PORT")
            print("  AZURE_SQL_USER")
            print("  AZURE_SQL_PASSWORD")
            print("  AZURE_SQL_DATABASE")
            print("  AZURE_SQL_SCHEMA")

        return credentials if is_configured else None

    except Exception as e:
        print(f"✗ Failed to create SQL Server credentials: {e}")
        return None


def test_database_operator():
    """Test database operator creation"""
    print("\n=== Testing Database Operator ===")

    try:
        from utils.database_helpers import get_database_operator, load_app_infra

        app_infra = load_app_infra()
        operator = get_database_operator(app_infra)

        print(f"✓ Database operator created: {type(operator).__name__}")

        # Check if it's the SQL Server operator
        if "SQLServer" in type(operator).__name__:
            print("✓ SQL Server operator successfully created")
            return operator
        else:
            print(f"✗ Expected SQL Server operator, got: {type(operator).__name__}")
            return None

    except Exception as e:
        print(f"✗ Failed to create database operator: {e}")
        import traceback

        traceback.print_exc()
        return None


def test_sql_server_connection(operator):
    """Test SQL Server connection and table listing"""
    print("\n=== Testing SQL Server Connection ===")

    try:
        # Test table listing
        tables = operator.list_tables()
        print(f"✓ Successfully listed tables: {len(tables)} found")

        if tables:
            print("✓ Tables found:")
            for i, table in enumerate(tables[:10]):  # Show first 10
                print(f"  {i + 1}. {table}")
            if len(tables) > 10:
                print(f"  ... and {len(tables) - 10} more")
        else:
            print("⚠ No tables found - check schema permissions")

        return tables

    except Exception as e:
        print(f"✗ Failed to list tables: {e}")
        import traceback

        traceback.print_exc()
        return None


def test_external_database():
    """Test the external database function used by the app"""
    print("\n=== Testing External Database Function ===")

    try:
        from utils.database_helpers import get_external_database

        ext_db = get_external_database()
        print(f"✓ External database created: {type(ext_db).__name__}")

        # Try to list tables
        if hasattr(ext_db, "list_tables"):
            tables = ext_db.list_tables()
            print(f"✓ External database listed {len(tables)} tables")
            return tables
        else:
            print("✗ External database doesn't have list_tables method")
            return None

    except Exception as e:
        print(f"✗ Failed to get external database: {e}")
        import traceback

        traceback.print_exc()
        return None


def main():
    """Main diagnostic function"""
    print("SQL Server Connection Diagnostic Tool")
    print("=" * 50)

    # Test 1: App Infrastructure
    app_infra = test_app_infra()
    if not app_infra or app_infra.database != "sqlserver":
        print("\n❌ App infrastructure not configured for SQL Server")
        print("✅ Solution: Ensure app_infra.json contains:")
        print('   {"llm": "azure_openai", "database": "sqlserver"}')
        return

    # Test 2: Credentials
    credentials = test_sql_server_credentials()
    if not credentials:
        print("\n❌ SQL Server credentials not configured")
        print("✅ Solution: Set environment variables in .env file")
        return

    # Test 3: Database Operator
    operator = test_database_operator()
    if not operator:
        print("\n❌ Failed to create SQL Server operator")
        return

    # Test 4: Connection and Tables
    tables = test_sql_server_connection(operator)
    if tables is None:
        print("\n❌ Failed to connect to SQL Server or list tables")
        return

    # Test 5: External Database
    test_external_database()

    print("\n" + "=" * 50)
    if tables and len(tables) > 0:
        print("🎉 SUCCESS: SQL Server connection working!")
        print(f"   Found {len(tables)} tables in the database")
        print("   Tables should now be visible in the application")
    else:
        print("⚠️  SQL Server connected but no tables found")
        print("   Check schema permissions and table existence")


if __name__ == "__main__":
    main()
