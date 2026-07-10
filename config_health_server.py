#!/usr/bin/env python3
"""Config-aware health server for NIJA.

When Render's early liveness server already owns ``PORT``, this process performs a
safe handoff instead of crashing with ``EADDRINUSE``. Trading remains fail-closed;
this module never grants writer authority or changes runtime trading state.
"""

from __future__ import annotations

import errno
import json
import logging
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

_TRUTHY = {"1", "true", "yes", "on", "enabled"}
_KRAKEN_KEY_NAMES = (
    "KRAKEN_PLATFORM_API_KEY",
    "KRAKEN_API_KEY",
    "KRAKEN_MASTER_API_KEY",
    "KRAKEN_MASTER_KEY",
    "KRAKEN_PLATFORM_KEY",
)
_KRAKEN_SECRET_NAMES = (
    "KRAKEN_PLATFORM_API_SECRET",
    "KRAKEN_API_SECRET",
    "KRAKEN_PRIVATE_KEY",
    "KRAKEN_SECRET_KEY",
    "KRAKEN_MASTER_API_SECRET",
    "KRAKEN_MASTER_SECRET",
    "KRAKEN_PLATFORM_SECRET",
)


def _is_truthy(value: object) -> bool:
    return str(value or "").strip().lower() in _TRUTHY


def _first_present(names: tuple[str, ...]) -> str:
    for name in names:
        if str(os.getenv(name, "") or "").strip():
            return name
    return ""


def _pid_alive(raw_pid: str) -> bool:
    try:
        pid = int(str(raw_pid or "").strip())
        if pid <= 0:
            return False
        os.kill(pid, 0)
        return True
    except (TypeError, ValueError, ProcessLookupError, PermissionError):
        return False


def _get_system_status() -> dict[str, object]:
    """Determine configuration status without exposing secret values."""

    from bot.redis_env import get_redis_resolution_diagnostics, get_redis_url

    if os.path.exists("EMERGENCY_STOP"):
        return {
            "status": "error",
            "state": "emergency_stopped",
            "message": "Emergency stop is active",
            "action_required": "Remove EMERGENCY_STOP file to resume",
        }

    critical_files = ["bot.py", "config_health_server.py"]
    missing_files = [path for path in critical_files if not os.path.exists(path)]
    if missing_files:
        return {
            "status": "error",
            "state": "corrupted_deployment",
            "message": "Critical files missing",
            "missing_files": missing_files,
            "action_required": "Redeploy from clean image",
        }

    strict_lease = str(os.getenv("NIJA_STRICT_REDIS_LEASE", "1")).strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    unsafe_bypass = _is_truthy(os.getenv("NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK", "0"))
    dry_run = _is_truthy(os.getenv("DRY_RUN_MODE", "false"))
    paper_mode = _is_truthy(os.getenv("PAPER_MODE", "false"))
    redis_required = (not dry_run) and (not paper_mode) and strict_lease and not unsafe_bypass

    resolved_redis = get_redis_url()
    redis_diag = get_redis_resolution_diagnostics()
    valid_redis = str(resolved_redis or "").strip().startswith(("redis://", "rediss://"))
    railway_internal = ".railway.internal" in str(resolved_redis or "")
    tls_mismatch = bool(redis_diag.get("tls_mismatch"))

    if redis_required and (not valid_redis or railway_internal or tls_mismatch):
        return {
            "status": "blocked",
            "state": "awaiting_configuration",
            "message": "Distributed writer lock requires a reachable Redis URL",
            "config_status": "missing_redis_for_writer_lock",
            "redis_diagnostics": redis_diag,
            "required": {"NIJA_REDIS_URL": "Redis URL (redis:// or rediss://)"},
            "action_required": "Configure Redis and redeploy",
        }

    key_source = _first_present(_KRAKEN_KEY_NAMES)
    secret_source = _first_present(_KRAKEN_SECRET_NAMES)
    if key_source and secret_source:
        return {
            "status": "ready",
            "state": "configured",
            "message": "Configuration is complete",
            "config_status": "credentials_configured",
            "credentials": {
                "kraken_platform": "configured",
                "key_source": key_source,
                "secret_source": secret_source,
            },
        }

    return {
        "status": "blocked",
        "state": "awaiting_configuration",
        "message": "Kraken platform credentials are missing",
        "config_status": "missing_credentials",
        "required": {
            "KRAKEN_PLATFORM_API_KEY": "Kraken API key (required)",
            "KRAKEN_PLATFORM_API_SECRET": "Kraken API secret (required)",
        },
        "action_required": "Set both Kraken platform secrets and restart",
    }


class ConfigHealthHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
        if self.path not in {"/", "/health", "/healthz", "/status"}:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        status_info = _get_system_status()
        http_status = {
            "ready": 200,
            "blocked": 503,
            "error": 500,
        }.get(str(status_info.get("status", "error")), 500)
        payload = json.dumps(status_info, separators=(",", ":")).encode("utf-8")

        try:
            self.send_response(http_status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            return

    def log_message(self, fmt: str, *args: object) -> None:
        logger.debug("%s - %s", self.client_address[0], fmt % args)


def start_health_server(port: int | None = None) -> None:
    """Start the config server or hand off to Render's existing liveness server."""

    if port is None:
        try:
            port = int(os.getenv("PORT", "8080") or "8080")
        except ValueError:
            port = 8080

    try:
        server = ThreadingHTTPServer(("0.0.0.0", port), ConfigHealthHandler)
    except OSError as exc:
        early_pid = os.getenv("NIJA_RENDER_LIVENESS_PID", "")
        if exc.errno == errno.EADDRINUSE and _pid_alive(early_pid):
            logger.warning(
                "CONFIG_HEALTH_HANDOFF existing_render_liveness=true port=%s pid=%s "
                "trading_remains_fail_closed=true",
                port,
                early_pid,
            )
            while _pid_alive(early_pid):
                time.sleep(5)
            logger.error("Render liveness process exited while configuration remained blocked")
            raise SystemExit(1)
        logger.error("Health server failed to start: %s", exc)
        raise SystemExit(1) from exc

    server.daemon_threads = True
    logger.info("🌐 Config-aware health server listening on port %s", port)
    logger.info("   Health endpoints: /health, /healthz, /status")
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()


if __name__ == "__main__":
    start_health_server()
