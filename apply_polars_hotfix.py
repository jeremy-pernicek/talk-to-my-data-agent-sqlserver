#!/usr/bin/env python3
"""
Hotfix script to apply the Polars schema inference fix to a running deployment
Run this in the deployed environment to fix the TTMD_Deposit_History loading issue
"""

import os
import sys

# The fix to apply
FIXED_GET_TABLE_AS_DATAFRAME = '''    def get_table_as_dataframe(
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

            # Handle large datasets by using pandas as intermediate step
            # This avoids Polars schema inference issues with inconsistent data types
            try:
                # First try direct Polars creation with extended schema inference
                return pl.DataFrame(results, infer_schema_length=10000)
            except Exception as polars_error:
                logger.warning(f"Direct Polars creation failed: {str(polars_error)}, falling back to pandas conversion")
                
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
'''


def find_file_to_patch():
    """Find the database_helpers_pytds.py file in the deployment"""
    possible_paths = [
        "/opt/code/utils/database_helpers_pytds.py",
        "./utils/database_helpers_pytds.py",
        "utils/database_helpers_pytds.py",
        "/app/utils/database_helpers_pytds.py",
    ]

    for path in possible_paths:
        if os.path.exists(path):
            return path

    # Try to find it
    import subprocess

    try:
        result = subprocess.run(
            ["find", "/", "-name", "database_helpers_pytds.py", "2>/dev/null"],
            capture_output=True,
            text=True,
            shell=True,
        )
        if result.stdout:
            return result.stdout.strip().split("\n")[0]
    except Exception:
        pass

    return None


def apply_hotfix(file_path):
    """Apply the hotfix to the file"""
    print(f"Reading file: {file_path}")

    with open(file_path, "r") as f:
        content = f.read()

    # Check if already fixed
    if "infer_schema_length=10000" in content:
        print("✅ File already contains the fix!")
        return True

    # Find the method to replace
    import re

    # Pattern to match the get_table_as_dataframe method
    pattern = r"(    def get_table_as_dataframe\([^)]+\)[^:]+:[^}]+?return error_msg)"

    # Check if we can find the method
    if not re.search(pattern, content, re.DOTALL):
        print("❌ Could not find get_table_as_dataframe method to patch")
        print("Trying alternative patch method...")

        # Try to find just the problem line
        if "return pl.DataFrame(results)" in content:
            print("Found the problematic line")
            # Replace the simple DataFrame creation with our enhanced version
            content = content.replace(
                "return pl.DataFrame(results)",
                """# Handle large datasets by using pandas as intermediate step
            # This avoids Polars schema inference issues with inconsistent data types
            try:
                # First try direct Polars creation with extended schema inference
                return pl.DataFrame(results, infer_schema_length=10000)
            except Exception as polars_error:
                logger.warning(f"Direct Polars creation failed: {str(polars_error)}, falling back to pandas conversion")
                
                # Fallback: convert through pandas to handle schema inconsistencies
                import pandas as pd
                
                # Convert to pandas DataFrame first (more forgiving with mixed types)
                pandas_df = pd.DataFrame(results)
                
                # Convert pandas DataFrame to Polars
                return pl.from_pandas(pandas_df)""",
            )

            # Write the patched content
            print(f"Writing patched file: {file_path}")
            with open(file_path, "w") as f:
                f.write(content)

            print("✅ Hotfix applied successfully!")
            return True
    else:
        # Replace the entire method
        content = re.sub(
            pattern, FIXED_GET_TABLE_AS_DATAFRAME.strip(), content, flags=re.DOTALL
        )

        # Write the patched content
        print(f"Writing patched file: {file_path}")
        with open(file_path, "w") as f:
            f.write(content)

        print("✅ Hotfix applied successfully!")
        return True

    return False


def verify_fix(file_path):
    """Verify the fix was applied"""
    with open(file_path, "r") as f:
        content = f.read()

    checks = [
        "infer_schema_length=10000",
        "pandas_df = pd.DataFrame(results)",
        "pl.from_pandas(pandas_df)",
    ]

    print("\n=== Verification ===")
    all_good = True
    for check in checks:
        if check in content:
            print(f"✅ Found: {check}")
        else:
            print(f"❌ Missing: {check}")
            all_good = False

    return all_good


def main():
    """Main function to apply the hotfix"""
    print("Polars Schema Inference Hotfix Script")
    print("=" * 50)

    # Find the file to patch
    file_path = find_file_to_patch()

    if not file_path:
        print("❌ Could not find database_helpers_pytds.py file")
        print("Please specify the path manually or check the deployment")
        return False

    print(f"✅ Found file at: {file_path}")

    # Create backup
    backup_path = file_path + ".backup"
    if not os.path.exists(backup_path):
        import shutil

        shutil.copy2(file_path, backup_path)
        print(f"✅ Created backup at: {backup_path}")

    # Apply the hotfix
    if apply_hotfix(file_path):
        # Verify the fix
        if verify_fix(file_path):
            print("\n" + "=" * 50)
            print("🎉 HOTFIX APPLIED SUCCESSFULLY!")
            print("The TTMD_Deposit_History table should now load correctly.")
            print("You may need to restart the application or reload the page.")
            return True

    print("\n" + "=" * 50)
    print("❌ Failed to apply hotfix")
    print("Please check the file manually or redeploy with the fixed code")
    return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
