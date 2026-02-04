#!/usr/bin/env python3
"""
Test the health check HTTP endpoints.

This script starts a test server and makes HTTP requests to verify
the endpoints work correctly.
"""

import sys
import os
import time
import json
import subprocess
import signal
import requests
from threading import Thread

# Configuration
PORT = 8888
BASE_URL = f"http://localhost:{PORT}"


def start_test_server():
    """Start a simple test server with health endpoints"""
    from http.server import BaseHTTPRequestHandler, HTTPServer
    
    # Add bot directory to path for imports
    bot_path = os.path.join(os.path.dirname(__file__), 'bot')
    if bot_path not in sys.path:
        sys.path.insert(0, bot_path)
    
    from health_check import get_health_manager
    
    health_manager = get_health_manager()
    
    # Set up some test state
    health_manager.mark_configuration_valid()
    health_manager.update_exchange_status(connected=2, expected=2)
    
    class TestHealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                if self.path in ("/health", "/healthz"):
                    status = health_manager.get_liveness_status()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(status).encode())
                
                elif self.path in ("/ready", "/readiness"):
                    status, http_code = health_manager.get_readiness_status()
                    self.send_response(http_code)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(status).encode())
                
                elif self.path in ("/status", "/"):
                    status = health_manager.get_detailed_status()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(status).encode())
                
                else:
                    self.send_response(404)
                    self.end_headers()
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        
        def log_message(self, format, *args):
            # Silence HTTP server logging
            pass
    
    server = HTTPServer(("0.0.0.0", PORT), TestHealthHandler)
    server.serve_forever()


def test_liveness_endpoint():
    """Test /healthz endpoint"""
    print("=" * 70)
    print("TEST 1: Liveness Endpoint (/healthz)")
    print("=" * 70)
    
    response = requests.get(f"{BASE_URL}/healthz", timeout=5)
    
    print(f"Status Code: {response.status_code}")
    print(f"Response:")
    print(json.dumps(response.json(), indent=2))
    
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data = response.json()
    assert data['status'] == 'alive', "Status should be 'alive'"
    
    print("✅ Liveness endpoint working correctly")
    print()


def test_readiness_endpoint():
    """Test /ready endpoint"""
    print("=" * 70)
    print("TEST 2: Readiness Endpoint (/ready)")
    print("=" * 70)
    
    response = requests.get(f"{BASE_URL}/ready", timeout=5)
    
    print(f"Status Code: {response.status_code}")
    print(f"Response:")
    print(json.dumps(response.json(), indent=2))
    
    # Should be ready since we configured it in the test server
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data = response.json()
    assert data['ready'] == True, "Should be ready"
    assert data['status'] == 'ready', "Status should be 'ready'"
    
    print("✅ Readiness endpoint working correctly")
    print()


def test_status_endpoint():
    """Test /status endpoint"""
    print("=" * 70)
    print("TEST 3: Status Endpoint (/status)")
    print("=" * 70)
    
    response = requests.get(f"{BASE_URL}/status", timeout=5)
    
    print(f"Status Code: {response.status_code}")
    print(f"Response:")
    print(json.dumps(response.json(), indent=2))
    
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data = response.json()
    assert 'liveness' in data, "Should include liveness info"
    assert 'readiness' in data, "Should include readiness info"
    assert 'operational_state' in data, "Should include operational state"
    
    print("✅ Status endpoint working correctly")
    print()


def test_404_response():
    """Test 404 for unknown endpoints"""
    print("=" * 70)
    print("TEST 4: 404 for Unknown Endpoints")
    print("=" * 70)
    
    response = requests.get(f"{BASE_URL}/unknown", timeout=5)
    
    print(f"Status Code: {response.status_code}")
    
    assert response.status_code == 404, f"Expected 404, got {response.status_code}"
    
    print("✅ Unknown endpoints return 404")
    print()


def main():
    """Run all HTTP endpoint tests"""
    print("\n")
    print("╔" + "=" * 68 + "╗")
    print("║" + " " * 12 + "HEALTH CHECK HTTP ENDPOINT TESTS" + " " * 22 + "║")
    print("╚" + "=" * 68 + "╝")
    print()
    
    # Start test server in background thread
    print(f"Starting test server on port {PORT}...")
    server_thread = Thread(target=start_test_server, daemon=True)
    server_thread.start()
    
    # Wait for server to start
    time.sleep(1)
    
    try:
        test_liveness_endpoint()
        test_readiness_endpoint()
        test_status_endpoint()
        test_404_response()
        
        print("=" * 70)
        print("✅ ALL HTTP ENDPOINT TESTS PASSED")
        print("=" * 70)
        print()
        print("Health check HTTP endpoints are working correctly:")
        print("  ✅ /healthz returns liveness status")
        print("  ✅ /ready returns readiness status")
        print("  ✅ /status returns detailed operational status")
        print("  ✅ Unknown endpoints return 404")
        print()
        
        return 0
        
    except AssertionError as e:
        print()
        print("=" * 70)
        print("❌ TEST FAILED")
        print("=" * 70)
        print(f"Error: {e}")
        print()
        return 1
    except Exception as e:
        print()
        print("=" * 70)
        print("❌ UNEXPECTED ERROR")
        print("=" * 70)
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        print()
        return 1


if __name__ == '__main__':
    sys.exit(main())
