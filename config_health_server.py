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
    stream=sys.stdout,
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

        def _is_truthy(value):
            return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}

        def _is_railway_internal_url(raw):
            return ".railway.internal" in str(raw or "")

        def _has_public_redis_fallback():
            if os.getenv("RAILWAY_TCP_PROXY_DOMAIN") and os.getenv("RAILWAY_TCP_PROXY_PORT"):
                return True

            redis_public_url = os.getenv("REDIS_PUBLIC_URL", "")
            if redis_public_url and not _is_railway_internal_url(redis_public_url):
                return True

            redis_host = os.getenv("REDIS_HOST") or os.getenv("REDISHOST") or ""
            redis_port = os.getenv("REDIS_PORT") or os.getenv("REDISPORT") or ""
            if redis_host and redis_port and ".railway.internal" not in redis_host:
                return True

            return False
        
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
        
        # Check whether strict writer lock requires Redis at startup.
        # In live mode this must be configured correctly before boot can continue.
        strict_lease = not str(os.getenv("NIJA_STRICT_REDIS_LEASE", "1")).strip().lower() in {
            "0", "false", "no", "off"
        }
        unsafe_bypass = _is_truthy(os.getenv("NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK", "0"))
        dry_run = _is_truthy(os.getenv("DRY_RUN_MODE", "false"))
        paper_mode = _is_truthy(os.getenv("PAPER_MODE", "false"))
        live_mode = (not dry_run) and (not paper_mode)
        redis_required = live_mode and strict_lease and (not unsafe_bypass)

        resolved_redis = (
            os.getenv("NIJA_REDIS_URL")
            or os.getenv("REDIS_URL")
            or os.getenv("REDIS_PRIVATE_URL")
            or os.getenv("REDIS_PUBLIC_URL")
            or ""
        )
        has_component_redis = bool(
            (os.getenv("RAILWAY_TCP_PROXY_DOMAIN") and os.getenv("RAILWAY_TCP_PROXY_PORT"))
            or ((os.getenv("REDIS_HOST") or os.getenv("REDISHOST")) and (os.getenv("REDIS_PORT") or os.getenv("REDISPORT")))
        )
        has_any_redis = bool(str(resolved_redis).strip()) or has_component_redis
        internal_only_redis = bool(str(resolved_redis).strip()) and _is_railway_internal_url(resolved_redis) and not _has_public_redis_fallback()

        if redis_required and (not has_any_redis or internal_only_redis):
            if internal_only_redis:
                message = "Redis URL uses Railway internal hostname without public proxy fallback"
                action = "Set NIJA_REDIS_URL to Railway public proxy URL and redeploy"
                required = {
                    "NIJA_REDIS_URL": "Railway public proxy URL (rediss://default:PASSWORD@maglev.proxy.rlwy.net:PORT/0)",
                    "ALTERNATIVE": "Set RAILWAY_TCP_PROXY_DOMAIN + RAILWAY_TCP_PROXY_PORT + REDIS_PASSWORD"
                }
            else:
                message = "Distributed writer lock requires Redis configuration in live mode"
                action = "Configure Redis connection and redeploy"
                required = {
                    "NIJA_REDIS_URL": "Redis URL (preferred)",
                    "ALTERNATIVE": "Set RAILWAY_TCP_PROXY_DOMAIN + RAILWAY_TCP_PROXY_PORT + REDIS_PASSWORD"
                }

            return {
                "status": "blocked",
                "state": "awaiting_configuration",
                "message": message,
                "config_status": "missing_redis_for_writer_lock",
                "required": required,
                "action_required": action
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
