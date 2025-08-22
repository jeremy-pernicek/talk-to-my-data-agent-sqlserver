#!/usr/bin/env python3
"""
Detailed SQL Server Connection Test
Compares different connection methods to understand why JDBC works but pytds doesn't
"""

import socket
import sys
import os
import subprocess
from pathlib import Path

# Add vendor directory to path for pytds
sys.path.insert(0, str(Path(__file__).parent / "utils" / "vendor"))

def test_jdbc_with_jaydebeapi():
    """Test using JDBC driver through Python (requires jaydebeapi)"""
    print("\n1. Testing JDBC connection (if jaydebeapi available)...")
    try:
        import jaydebeapi
        
        # JDBC connection string that works
        jdbc_url = "jdbc:sqlserver://172.208.108.22;encrypt=true;trustServerCertificate=true;database=HAD"
        jdbc_driver = "com.microsoft.sqlserver.jdbc.SQLServerDriver"
        
        # This would need the JDBC driver JAR file
        print(f"   JDBC URL: {jdbc_url}")
        print("   Note: Would need SQL Server JDBC driver JAR")
        return False
        
    except ImportError:
        print("   jaydebeapi not installed - skipping JDBC test")
        return False

def test_pyodbc():
    """Test using pyodbc (if available)"""
    print("\n2. Testing pyodbc connection...")
    try:
        import pyodbc
        
        # Connection string mimicking JDBC settings
        conn_str = (
            "DRIVER={ODBC Driver 17 for SQL Server};"
            "SERVER=172.208.108.22,1433;"
            "DATABASE=HAD;"
            "UID=ayeager;"
            "PWD=DataRobot123!;"
            "Encrypt=yes;"
            "TrustServerCertificate=yes;"
        )
        
        print(f"   Connection string: {conn_str[:50]}...")
        
        try:
            conn = pyodbc.connect(conn_str, timeout=10)
            cursor = conn.cursor()
            cursor.execute("SELECT @@VERSION")
            version = cursor.fetchone()[0]
            print(f"   ✓ pyodbc connection successful!")
            print(f"   SQL Server Version: {version[:50]}...")
            conn.close()
            return True
        except Exception as e:
            print(f"   ✗ pyodbc connection failed: {e}")
            
            # Try alternative driver names
            for driver in ["ODBC Driver 18 for SQL Server", "SQL Server"]:
                conn_str_alt = conn_str.replace("ODBC Driver 17 for SQL Server", driver)
                try:
                    print(f"   Trying driver: {driver}")
                    conn = pyodbc.connect(conn_str_alt, timeout=10)
                    print(f"   ✓ Connected with {driver}")
                    conn.close()
                    return True
                except:
                    continue
                    
            return False
            
    except ImportError:
        print("   pyodbc not installed")
        return False

def test_pytds_with_different_options():
    """Test pytds with various connection options"""
    print("\n3. Testing pytds with different configurations...")
    
    try:
        import pytds
        
        host = "172.208.108.22"
        port = 1433
        user = "ayeager"
        password = "DataRobot123!"
        database = "HAD"
        
        # Test configurations matching JDBC behavior
        test_configs = [
            {
                "name": "Basic connection",
                "params": {
                    "server": host,
                    "port": port,
                    "user": user,
                    "password": password,
                    "database": database,
                }
            },
            {
                "name": "With TDS 7.2 (SQL Server 2008)",
                "params": {
                    "server": host,
                    "port": port,
                    "user": user,
                    "password": password,
                    "database": database,
                    "tds_version": 0x72000000,
                }
            },
            {
                "name": "With TDS 7.3 (SQL Server 2012)",
                "params": {
                    "server": host,
                    "port": port,
                    "user": user,
                    "password": password,
                    "database": database,
                    "tds_version": 0x73000000,
                }
            },
            {
                "name": "With TDS 7.4 (SQL Server 2014+)",
                "params": {
                    "server": host,
                    "port": port,
                    "user": user,
                    "password": password,
                    "database": database,
                    "tds_version": 0x74000000,
                }
            },
            {
                "name": "With encryption disabled",
                "params": {
                    "server": host,
                    "port": port,
                    "user": user,
                    "password": password,
                    "database": database,
                    "encryption_level": 0,  # No encryption
                }
            },
            {
                "name": "With longer timeouts",
                "params": {
                    "server": host,
                    "port": port,
                    "user": user,
                    "password": password,
                    "database": database,
                    "timeout": 60,
                    "login_timeout": 60,
                }
            },
        ]
        
        for config in test_configs:
            print(f"\n   Testing: {config['name']}")
            try:
                conn = pytds.connect(**config["params"])
                cursor = conn.cursor()
                cursor.execute("SELECT @@VERSION")
                version = cursor.fetchone()[0]
                print(f"   ✓ SUCCESS with {config['name']}")
                print(f"   SQL Server Version: {version[:50]}...")
                conn.close()
                return True
            except Exception as e:
                print(f"   ✗ Failed: {str(e)[:100]}")
                continue
                
        return False
        
    except ImportError:
        print("   pytds not installed")
        return False

def test_pymssql():
    """Test using pymssql (alternative to pytds)"""
    print("\n4. Testing pymssql connection...")
    try:
        import pymssql
        
        try:
            conn = pymssql.connect(
                server="172.208.108.22",
                port=1433,
                user="ayeager",
                password="DataRobot123!",
                database="HAD",
                login_timeout=30,
                timeout=30,
                tds_version="7.0",  # Try older TDS version
            )
            cursor = conn.cursor()
            cursor.execute("SELECT @@VERSION")
            version = cursor.fetchone()[0]
            print(f"   ✓ pymssql connection successful!")
            print(f"   SQL Server Version: {version[:50]}...")
            conn.close()
            return True
        except Exception as e:
            print(f"   ✗ pymssql connection failed: {e}")
            return False
            
    except ImportError:
        print("   pymssql not installed - you can install with: pip install pymssql")
        return False

def check_network_routes():
    """Check network routing to SQL Server"""
    print("\n5. Checking network routes and connectivity...")
    
    host = "172.208.108.22"
    
    # Test ping (might be blocked)
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "2", host],
            capture_output=True,
            text=True,
            timeout=3
        )
        if result.returncode == 0:
            print(f"   ✓ Ping successful to {host}")
        else:
            print(f"   ✗ Ping failed to {host} (might be blocked by firewall)")
    except:
        print(f"   ✗ Could not ping {host}")
    
    # Test traceroute
    try:
        print(f"\n   Traceroute to {host} (first 5 hops):")
        result = subprocess.run(
            ["traceroute", "-m", "5", "-w", "1", host],
            capture_output=True,
            text=True,
            timeout=10
        )
        for line in result.stdout.split('\n')[1:6]:
            if line.strip():
                print(f"     {line}")
    except:
        print("   Could not run traceroute")
    
    # Check local network interfaces
    try:
        import netifaces
        print("\n   Local network interfaces:")
        for iface in netifaces.interfaces():
            addrs = netifaces.ifaddresses(iface)
            if netifaces.AF_INET in addrs:
                for addr in addrs[netifaces.AF_INET]:
                    if addr['addr'] != '127.0.0.1':
                        print(f"     {iface}: {addr['addr']}")
    except ImportError:
        pass

def test_telnet():
    """Test using telnet command"""
    print("\n6. Testing with telnet command...")
    try:
        result = subprocess.run(
            ["timeout", "5", "telnet", "172.208.108.22", "1433"],
            capture_output=True,
            text=True,
        )
        if "Connected" in result.stdout or "Escape character" in result.stdout:
            print("   ✓ Telnet can connect to SQL Server port")
            return True
        else:
            print("   ✗ Telnet cannot connect")
            return False
    except:
        print("   telnet command not available")
        return False

def main():
    print("="*70)
    print("SQL Server Connection Diagnostic Tool - Detailed Analysis")
    print("="*70)
    
    print("\nEnvironment Configuration:")
    print(f"  Host: 172.208.108.22")
    print(f"  Port: 1433")
    print(f"  Database: HAD")
    print(f"  User: ayeager")
    print(f"  Working JDBC: jdbc:sqlserver://172.208.108.22;encrypt=true;trustServerCertificate=true;database=HAD")
    
    # Run all tests
    results = {
        "JDBC": test_jdbc_with_jaydebeapi(),
        "pyodbc": test_pyodbc(),
        "pytds": test_pytds_with_different_options(),
        "pymssql": test_pymssql(),
        "telnet": test_telnet(),
    }
    
    check_network_routes()
    
    print("\n" + "="*70)
    print("Summary:")
    print("="*70)
    
    for method, success in results.items():
        status = "✓ SUCCESS" if success else "✗ FAILED"
        print(f"  {method:10} : {status}")
    
    if results["pyodbc"] and not results["pytds"]:
        print("\n⚠ pyodbc works but pytds doesn't - consider using pyodbc instead")
    elif results["pymssql"] and not results["pytds"]:
        print("\n⚠ pymssql works but pytds doesn't - consider using pymssql instead")
    
    print("\nRecommendations:")
    if not results["pytds"]:
        print("  1. Try installing pymssql: pip install pymssql")
        print("  2. Or install pyodbc with SQL Server ODBC driver")
        print("  3. Or use SKIP_DATABASE_TEST=true during deployment")
    
    print("="*70)

if __name__ == "__main__":
    main()