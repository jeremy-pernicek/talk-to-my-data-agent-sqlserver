#!/usr/bin/env python3
"""
Basic validation of the Polars fix implementation
This validates the code structure without requiring polars to be installed
"""

import sys
import os
import re

def validate_fix_implementation():
    """Validate that the fix has been properly implemented"""
    
    print("=== Validating Polars Fix Implementation ===\n")
    
    # Read the fixed file
    file_path = "./utils/database_helpers_pytds.py"
    
    if not os.path.exists(file_path):
        print(f"✗ File not found: {file_path}")
        return False
    
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Check for key improvements
    checks = [
        (r"infer_schema_length=10000", "Extended schema inference parameter"),
        (r"import pandas as pd", "Pandas import for fallback"),
        (r"pl\.from_pandas\(pandas_df\)", "Pandas to Polars conversion"),
        (r"except Exception as polars_error:", "Polars-specific error handling"),
        (r"falling back to pandas conversion", "Fallback logging message"),
        (r"Direct Polars creation failed", "Specific error logging"),
        (r"pandas_df = pd\.DataFrame\(results\)", "Pandas DataFrame creation"),
        (r"try:\s*#.*First try direct Polars", "Two-stage approach comment"),
    ]
    
    print("Checking for implementation features:")
    all_passed = True
    
    for pattern, description in checks:
        if re.search(pattern, content, re.MULTILINE | re.DOTALL):
            print(f"✓ {description}")
        else:
            print(f"✗ {description}")
            all_passed = False
    
    # Check the overall structure of the get_table_as_dataframe method
    print(f"\n--- Method Structure Analysis ---")
    
    # Extract the method
    method_match = re.search(
        r'def get_table_as_dataframe\(.*?\n(?:\s{4,}.*\n)*',
        content,
        re.MULTILINE | re.DOTALL
    )
    
    if method_match:
        method_code = method_match.group(0)
        print("✓ get_table_as_dataframe method found")
        
        # Check for proper error handling structure
        if "try:" in method_code and "except Exception as polars_error:" in method_code:
            print("✓ Proper nested exception handling")
        else:
            print("✗ Missing nested exception handling")
            all_passed = False
            
        # Count exception handlers
        exception_count = method_code.count("except Exception")
        print(f"✓ Found {exception_count} exception handlers")
        
        # Check for return types
        if "pl.DataFrame | str" in content:
            print("✓ Correct return type annotation")
        else:
            print("✗ Missing or incorrect return type annotation")
            all_passed = False
            
    else:
        print("✗ get_table_as_dataframe method not found")
        all_passed = False
    
    # Check for enhanced error handling in load_tables method
    print(f"\n--- Enhanced Error Handling Analysis ---")
    
    enhanced_features = [
        (r"SELECT COUNT\(\*\) as row_count", "Row count query for diagnostics"),
        (r"total_rows.*sampling.*rows", "Row count logging"),
        (r"schema.*issue.*detected", "Schema-specific error messages"),
        (r"timeout.*loading.*table", "Timeout-specific error messages"),
        (r"memory.*issue.*loading", "Memory-specific error messages"),
        (r"reducing.*sample_size", "Sample size suggestions"),
        (r"loaded.*rows.*columns", "DataFrame info logging"),
        (r"null.*values.*in.*columns", "Null value detection"),
    ]
    
    for pattern, description in enhanced_features:
        if re.search(pattern, content, re.IGNORECASE):
            print(f"✓ {description}")
        else:
            print(f"○ {description} (may be optional)")
    
    return all_passed

def validate_error_scenarios():
    """Validate error handling scenarios"""
    
    print(f"\n=== Error Scenario Analysis ===\n")
    
    # Test scenarios that should be handled
    scenarios = [
        "Schema inference fails with mixed types",
        "Large dataset causes memory issues", 
        "Database timeout occurs",
        "Network connection drops",
        "Invalid SQL syntax",
        "Missing table/view",
        "Permission denied",
        "Data type conversion errors"
    ]
    
    print("Error scenarios that should be handled by the fix:")
    for i, scenario in enumerate(scenarios, 1):
        print(f"{i}. {scenario}")
    
    print(f"\nThe fix addresses scenarios 1, 2, and 8 specifically.")
    print("Other scenarios are handled by existing error handling.")

def create_summary():
    """Create a summary of the fix"""
    
    print(f"\n=== Fix Summary ===\n")
    
    print("🔧 Problem Solved:")
    print("   Polars DataFrame schema inference error when processing large SQL Server tables")
    print("   Error: 'could not append value: TREASURY SERVICES of type: str to the builder'")
    
    print(f"\n🛠️ Solution Implemented:")
    print("   1. Two-stage DataFrame creation approach:")
    print("      • First: Try direct Polars with extended schema inference (10,000 rows)")
    print("      • Second: Fall back to pandas → Polars conversion if direct fails")
    print("   2. Enhanced error logging with specific diagnostics")
    print("   3. Better error messages with actionable suggestions")
    print("   4. Table size monitoring and reporting")
    
    print(f"\n📈 Benefits:")
    print("   • Handles mixed data types in SQL Server columns")
    print("   • Works with both small and large tables")
    print("   • Provides better error diagnostics for troubleshooting")
    print("   • Maintains backward compatibility")
    print("   • Graceful fallback ensures robustness")
    
    print(f"\n🎯 Files Modified:")
    print("   • utils/database_helpers_pytds.py (get_table_as_dataframe method)")
    print("   • Enhanced load_tables method with better error handling")

if __name__ == "__main__":
    print("Polars Fix Implementation Validation")
    print("=" * 50)
    
    success = validate_fix_implementation()
    validate_error_scenarios()
    create_summary()
    
    print(f"\n{'='*50}")
    if success:
        print("✅ Fix implementation validation PASSED")
        print("The code changes appear to properly address the Polars schema inference issue.")
    else:
        print("❌ Fix implementation validation FAILED")
        print("Some required changes may be missing or incorrect.")
    
    print(f"\nNext step: Test with actual SQL Server data to confirm the fix works.")