#!/usr/bin/env python3
"""
Mock API Server for Dashboard Demo
===================================

This provides mock data to demonstrate the dashboard with various failure states.
"""

from http.server import HTTPServer, SimpleHTTPRequestHandler
import json
import time
from urllib.parse import urlparse

class MockAPIHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed_path = urlparse(self.path)
        
        # Mock critical status endpoint
        if parsed_path.path == '/api/founder/critical-status':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            # Return mock data with failures
            data = {
                "adoption": {
                    "status": "failed",
                    "recent_failures": 3,
                    "total_failures": 15,
                    "last_failure": "2026-02-17T20:45:00.000Z",
                    "failures": [
                        {
                            "type": "broker_auth",
                            "user_id": "user_123",
                            "error": "Invalid API key - authentication failed",
                            "timestamp_iso": "2026-02-17T20:45:00.000Z"
                        },
                        {
                            "type": "trading_activation",
                            "user_id": "user_456",
                            "error": "Insufficient balance to activate trading",
                            "timestamp_iso": "2026-02-17T20:40:00.000Z"
                        },
                        {
                            "type": "registration",
                            "user_id": "user_789",
                            "error": "Email validation failed",
                            "timestamp_iso": "2026-02-17T20:35:00.000Z"
                        }
                    ]
                },
                "broker_health": {
                    "status": "failed",
                    "failed_brokers": ["coinbase"],
                    "degraded_brokers": ["kraken"],
                    "recent_failures": 5,
                    "total_failures": 20,
                    "broker_status": {
                        "coinbase": {
                            "status": "failed",
                            "last_check": time.time(),
                            "error_count": 8,
                            "last_error": "Connection timeout after 30 seconds"
                        },
                        "kraken": {
                            "status": "degraded",
                            "last_check": time.time(),
                            "error_count": 2,
                            "last_error": "Slow response time (>5s)"
                        },
                        "binance": {
                            "status": "healthy",
                            "last_check": time.time(),
                            "error_count": 0,
                            "last_error": None
                        }
                    },
                    "failures": []
                },
                "trading_threads": {
                    "status": "halted",
                    "halted_threads": ["coinbase"],
                    "halted_count": 1,
                    "recent_failures": 2,
                    "thread_status": {
                        "coinbase": {
                            "status": "halted",
                            "last_heartbeat": time.time() - 120,
                            "thread_id": 12345,
                            "error_count": 3
                        },
                        "kraken": {
                            "status": "running",
                            "last_heartbeat": time.time(),
                            "thread_id": 12346,
                            "error_count": 0
                        },
                        "binance": {
                            "status": "running",
                            "last_heartbeat": time.time(),
                            "thread_id": 12347,
                            "error_count": 0
                        }
                    }
                },
                "timestamp": "2026-02-17T20:50:00.000Z"
            }
            
            self.wfile.write(json.dumps(data).encode())
            return
        
        # Serve files normally
        return SimpleHTTPRequestHandler.do_GET(self)

if __name__ == '__main__':
    port = 8888
    server = HTTPServer(('localhost', port), MockAPIHandler)
    print(f'🚀 Mock API server running on http://localhost:{port}')
    print(f'📊 View dashboard at: http://localhost:{port}/NIJA_PRODUCTION_OBSERVABILITY_DASHBOARD.html')
    print('\nPress Ctrl+C to stop')
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n\n🛑 Server stopped')
