#!/usr/bin/env python3
"""
Deploy Talk-to-My-Data without SQL Server connectivity test
Use this when SQL Server is not accessible from deployment environment
but will be accessible from the runtime environment
"""

import os
import sys
import subprocess

def main():
    if len(sys.argv) < 2:
        print("Usage: python deploy_without_test.py <stack_name>")
        sys.exit(1)
    
    stack_name = sys.argv[1]
    
    print("="*60)
    print(f"Deploying {stack_name} WITHOUT SQL Server connectivity test")
    print("="*60)
    
    # Set environment variable to skip database test
    os.environ["SKIP_DATABASE_TEST"] = "true"
    
    # Load existing environment variables from .env
    if os.path.exists(".env"):
        with open(".env", "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    if "=" in line:
                        key, value = line.split("=", 1)
                        os.environ[key.strip()] = value.strip()
    
    print("\nEnvironment configured:")
    print(f"  AZURE_SQL_HOST: {os.getenv('AZURE_SQL_HOST', 'not set')}")
    print(f"  AZURE_SQL_DATABASE: {os.getenv('AZURE_SQL_DATABASE', 'not set')}")
    print(f"  SKIP_DATABASE_TEST: {os.getenv('SKIP_DATABASE_TEST', 'not set')}")
    
    # Run quickstart with test disabled
    print(f"\nRunning deployment for stack: {stack_name}")
    result = subprocess.run([sys.executable, "quickstart.py", stack_name])
    
    if result.returncode == 0:
        print("\n✓ Deployment completed successfully!")
        print("\nIMPORTANT: SQL Server connectivity was NOT tested during deployment.")
        print("Make sure SQL Server is accessible from the runtime environment.")
    else:
        print("\n✗ Deployment failed")
        sys.exit(1)

if __name__ == "__main__":
    main()