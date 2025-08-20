#!/usr/bin/env python3
"""
SQL Server Connection Test Script
Tests various connection methods to diagnose connectivity issues
"""

import socket
import sys
import os
from pathlib import Path

# Add vendor directory to path for pytds
sys.path.insert(0, str(Path(__file__).parent / "utils" / "vendor"))

def test_tcp_connection(host, port, timeout=5):
    """Test basic TCP connectivity"""
    print(f"\n1. Testing TCP connection to {host}:{port}...")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        
        if result == 0:
            print(f"   ✓ TCP connection successful - port {port} is open")
            return True
        else:
            print(f"   ✗ TCP connection failed - port {port} is closed or filtered")
            return False
    except socket.gaierror:
        print(f"   ✗ Hostname resolution failed for {host}")
        return False
    except Exception as e:
        print(f"   ✗ TCP connection error: {e}")
        return False

def test_pytds_connection(host, port, user, password, database, timeout=10):
    """Test pytds connection"""
    print(f"\n2. Testing pytds connection...")
    try:
        import pytds
        
        print(f"   Connecting with pytds to {host}:{port}")
        print(f"   Database: {database}, User: {user}")
        
        conn = pytds.connect(
            server=host,
            port=port,
            user=user,
            password=password,
            database=database,
            timeout=timeout,
            login_timeout=timeout
        )
        
        cursor = conn.cursor()
        cursor.execute("SELECT @@VERSION")
        version = cursor.fetchone()[0]
        print(f"   ✓ pytds connection successful!")
        print(f"   SQL Server Version: {version[:50]}...")
        
        cursor.close()
        conn.close()
        return True
        
    except ImportError:
        print("   ✗ pytds not installed")
        return False
    except Exception as e:
        print(f"   ✗ pytds connection failed: {e}")
        return False

def test_telnet_banner(host, port, timeout=5):
    """Try to get SQL Server TDS pre-login response"""
    print(f"\n3. Testing SQL Server TDS protocol response...")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, port))
        
        # Send a minimal TDS pre-login packet
        # This is just to see if we get any response
        prelogin = bytes([
            0x12, 0x01, 0x00, 0x2F, 0x00, 0x00, 0x01, 0x00,
            0x00, 0x00, 0x1A, 0x00, 0x06, 0x01, 0x00, 0x20,
            0x00, 0x01, 0x02, 0x00, 0x21, 0x00, 0x01, 0x03,
            0x00, 0x22, 0x00, 0x04, 0x04, 0x00, 0x26, 0x00,
            0x01, 0xFF, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00
        ])
        
        sock.send(prelogin)
        response = sock.recv(1024)
        sock.close()
        
        if response:
            print(f"   ✓ SQL Server TDS response received ({len(response)} bytes)")
            return True
        else:
            print(f"   ✗ No TDS response received")
            return False
            
    except socket.timeout:
        print(f"   ✗ Connection timed out - firewall may be blocking")
        return False
    except ConnectionRefusedError:
        print(f"   ✗ Connection refused - SQL Server may not be running or not listening on this port")
        return False
    except Exception as e:
        print(f"   ✗ TDS test error: {e}")
        return False

def main():
    print("="*60)
    print("SQL Server Connection Diagnostic Tool")
    print("="*60)
    
    # Read configuration from environment or use defaults
    host = os.getenv("AZURE_SQL_HOST", "172.208.108.22")
    port = int(os.getenv("AZURE_SQL_PORT", "1433"))
    user = os.getenv("AZURE_SQL_USER", "ayeager")
    password = os.getenv("AZURE_SQL_PASSWORD", "DataRobot123!")
    database = os.getenv("AZURE_SQL_DATABASE", "HAD")
    
    print(f"\nConfiguration:")
    print(f"  Host: {host}")
    print(f"  Port: {port}")
    print(f"  Database: {database}")
    print(f"  User: {user}")
    print(f"  Password: {'*' * len(password)}")
    
    # Run tests
    tcp_ok = test_tcp_connection(host, port)
    
    if tcp_ok:
        tds_ok = test_telnet_banner(host, port)
        pytds_ok = test_pytds_connection(host, port, user, password, database)
    else:
        print("\n⚠ Skipping further tests since TCP connection failed")
        print("\nPossible issues:")
        print("  1. SQL Server is not accessible from this network")
        print("  2. Firewall is blocking port 1433")
        print("  3. SQL Server is not configured for TCP/IP connections")
        print("  4. SQL Server is using a different port")
        
    print("\n" + "="*60)
    print("Diagnostic Summary:")
    if tcp_ok:
        print("  ✓ Network connectivity is working")
        if 'tds_ok' in locals() and tds_ok:
            print("  ✓ SQL Server is responding to TDS protocol")
        if 'pytds_ok' in locals() and pytds_ok:
            print("  ✓ Authentication and database access working")
        else:
            print("  ✗ Authentication or database access failed")
    else:
        print("  ✗ Cannot reach SQL Server - check network/firewall")
    print("="*60)

if __name__ == "__main__":
    main()