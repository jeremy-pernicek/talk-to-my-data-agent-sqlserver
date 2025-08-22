#!/usr/bin/env python3
"""
Test raw socket connection to SQL Server
This tests the most basic TCP connection without any SQL protocol
"""

import socket
import struct
import time

def test_basic_tcp():
    """Test basic TCP connection"""
    host = "172.208.108.22"
    port = 1433
    
    print(f"Testing basic TCP connection to {host}:{port}")
    print("-" * 50)
    
    for timeout in [1, 5, 10, 30]:
        print(f"\nAttempting connection with {timeout}s timeout...")
        try:
            start = time.time()
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            
            result = sock.connect_ex((host, port))
            elapsed = time.time() - start
            
            if result == 0:
                print(f"  ✓ Connected successfully in {elapsed:.2f}s")
                
                # Try to send a TDS prelogin packet
                print("  Sending TDS prelogin packet...")
                prelogin = bytes([
                    0x12, 0x01, 0x00, 0x2F, 0x00, 0x00, 0x01, 0x00,
                    0x00, 0x00, 0x1A, 0x00, 0x06, 0x01, 0x00, 0x20,
                    0x00, 0x01, 0x02, 0x00, 0x21, 0x00, 0x01, 0x03,
                    0x00, 0x22, 0x00, 0x04, 0x04, 0x00, 0x26, 0x00,
                    0x01, 0xFF, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
                    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00
                ])
                
                sock.send(prelogin)
                sock.settimeout(5)
                response = sock.recv(4096)
                
                if response:
                    print(f"  ✓ Received TDS response ({len(response)} bytes)")
                    # Check if it's a valid TDS response
                    if len(response) > 8:
                        packet_type = response[0]
                        if packet_type == 0x04:
                            print("  ✓ Valid TDS PRELOGIN response received")
                        else:
                            print(f"  ? Unexpected packet type: {packet_type:#x}")
                
                sock.close()
                return True
            else:
                print(f"  ✗ Connection failed with error code {result} after {elapsed:.2f}s")
                sock.close()
                
        except socket.timeout:
            print(f"  ✗ Connection timed out after {timeout}s")
        except socket.gaierror as e:
            print(f"  ✗ DNS resolution failed: {e}")
            break
        except Exception as e:
            print(f"  ✗ Error: {e}")
    
    return False

def test_with_socket_options():
    """Test with different socket options"""
    host = "172.208.108.22"
    port = 1433
    
    print(f"\n\nTesting with different socket options")
    print("-" * 50)
    
    socket_options = [
        ("Default", {}),
        ("TCP_NODELAY", {socket.TCP_NODELAY: 1}),
        ("SO_KEEPALIVE", {socket.SO_KEEPALIVE: 1}),
        ("Combined", {socket.TCP_NODELAY: 1, socket.SO_KEEPALIVE: 1}),
    ]
    
    for name, options in socket_options:
        print(f"\nTesting with {name}...")
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10)
            
            # Set socket options
            for opt, val in options.items():
                sock.setsockopt(socket.SOL_SOCKET, opt, val)
            
            start = time.time()
            result = sock.connect_ex((host, port))
            elapsed = time.time() - start
            
            if result == 0:
                print(f"  ✓ Connected with {name} in {elapsed:.2f}s")
                sock.close()
            else:
                print(f"  ✗ Failed with {name} after {elapsed:.2f}s")
                sock.close()
                
        except Exception as e:
            print(f"  ✗ Error with {name}: {e}")

def check_dns():
    """Check DNS resolution"""
    host = "172.208.108.22"
    
    print(f"\n\nChecking DNS/IP resolution")
    print("-" * 50)
    
    try:
        # This is an IP, so resolution should be instant
        import socket as s
        result = s.gethostbyaddr(host)
        print(f"  Reverse DNS: {result[0]}")
    except:
        print(f"  No reverse DNS for {host} (this is normal for IP addresses)")
    
    # Check if we can resolve the IP
    try:
        addr_info = socket.getaddrinfo(host, 1433, socket.AF_INET, socket.SOCK_STREAM)
        print(f"  Address info: {addr_info[0]}")
    except Exception as e:
        print(f"  ✗ getaddrinfo failed: {e}")

if __name__ == "__main__":
    print("="*60)
    print("Raw Socket Connection Test for SQL Server")
    print("="*60)
    
    check_dns()
    
    if test_basic_tcp():
        print("\n✓ Basic TCP connection works!")
        test_with_socket_options()
    else:
        print("\n✗ Basic TCP connection failed")
        print("\nThis suggests a network-level issue:")
        print("  1. Firewall blocking the connection")
        print("  2. SQL Server not listening on this IP/port")
        print("  3. Network routing issue")
        print("  4. SQL Server only accepting connections from specific IPs")