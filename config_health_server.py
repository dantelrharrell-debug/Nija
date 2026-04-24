#!/usr/bin/env python3
"""
Config-aware health server for NIJA
Starts before config validation and reports configuration status.

This allows orchestration platforms to:
- Health check the container even without config
- Differentiate between "waiting for config" vs "crashed"
- Avoid restart loops when credentials are missing
"""

import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ConfigHealthHandler(BaseHTTPRequestHandler):
    """HTTP handler that reports config readiness status
    
    Returns three distinct states to prevent restart loops and provide clear signals:
    
    1. BLOCKED (503) - Missing config, waiting for credentials
       Railway behavior: Container stays running, health check fails
       Human action: Add credentials via environment variables
    
    2. READY (200) - Config complete, bot operational
       Railway behavior: Container healthy, service available
       Human action: None needed
    
    3. ERROR (500) - Hard error detected (e.g., file corruption, system failure)
       Railway behavior: Container unhealthy, may need intervention
       Human action: Check logs, investigate error, may need redeploy
    """
    
    def do_GET(self):
        try:
            if self.path in ("/", "/health", "/healthz", "/status"):
                status_info = self._get_system_status()
                
                # Determine HTTP status code based on state
                http_status = {
                    "ready": 200,
                    "blocked": 503,  # Service Unavailable - will be available when config added
                    "error": 500     # Internal Server Error - hard failure
                }.get(status_info["status"], 500)
                
                self.send_response(http_status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(status_info, indent=2).encode())
            else:
                self.send_response(404)
                self.end_headers()
        except Exception as e:
            logger.error(f"Health check error: {e}")
            try:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                error_response = {
                    "status": "error",
                    "message": f"Health check handler error: {str(e)}",
                    "state": "hard_error"
                }
                self.wfile.write(json.dumps(error_response).encode())
            except Exception:
                pass
    
    def _get_system_status(self):
        """Determine system status: blocked, ready, or error"""
        
        # Check for hard error indicators
        if os.path.exists("EMERGENCY_STOP"):
            return {
                "status": "error",
                "state": "emergency_stopped",
                "message": "Emergency stop is active",
                "action_required": "Remove EMERGENCY_STOP file to resume"
            }
        
        # Check if critical files are missing/corrupted
        critical_files = ["bot.py", "config_health_server.py"]
        missing_files = [f for f in critical_files if not os.path.exists(f)]
        if missing_files:
            return {
                "status": "error",
                "state": "corrupted_deployment",
                "message": "Critical files missing",
                "missing_files": missing_files,
                "action_required": "Redeploy from clean image"
            }
        
        # Check if Kraken credentials are configured
        has_kraken = bool(
            os.getenv("KRAKEN_PLATFORM_API_KEY") and 
            os.getenv("KRAKEN_PLATFORM_API_SECRET")
        )
        
        if has_kraken:
            # Config ready - bot can start
            return {
                "status": "ready",
                "state": "configured",
                "message": "Configuration is complete, bot is ready to trade",
                "config_status": "credentials_configured",
                "credentials": {
                    "kraken_platform": "configured"
                }
            }
        else:
            # Waiting for config - not an error, just blocked
            return {
                "status": "blocked",
                "state": "awaiting_configuration",
                "message": "Waiting for configuration",
                "config_status": "missing_credentials",
                "required": {
                    "KRAKEN_PLATFORM_API_KEY": "Kraken API key (required)",
                    "KRAKEN_PLATFORM_API_SECRET": "Kraken API secret (required)"
                },
                "action_required": "Set environment variables and restart deployment"
            }
    
    def log_message(self, format, *args):
        # Log health checks at debug level only
        logger.debug("%s - %s" % (self.client_address[0], format % args))


def start_health_server(port=None):
    """Start the config-aware health server"""
    if port is None:
        port_env = os.getenv("PORT", "")
        default_port = 8080
        try:
            port = int(port_env) if port_env else default_port
        except Exception:
            port = default_port
    
    try:
        server = HTTPServer(("0.0.0.0", port), ConfigHealthHandler)
        logger.info(f"🌐 Config-aware health server listening on port {port}")
        logger.info(f"   Health endpoints: /health, /healthz, /status")
        logger.info(f"   Status: Reports 'blocked' (503) when config missing, 'ready' (200) when configured")
        server.serve_forever()
    except Exception as e:
        logger.error(f"Health server failed to start: {e}")
        sys.exit(1)


if __name__ == "__main__":
    start_health_server()
