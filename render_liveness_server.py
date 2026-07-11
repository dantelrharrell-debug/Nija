"""Minimal Render liveness and NIJA trading-readiness endpoints.

``/healthz`` intentionally reports process liveness so Render can complete a
zero-downtime deployment while broker startup converges. ``/readyz`` is stricter:
it returns HTTP 200 only after LIVE_ACTIVE writer authority is present and every
operator-required venue (Coinbase and OKX in production) is trading-ready.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_STARTED_AT = time.time()
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(name: str, default: str = "") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in _TRUE


def _readiness() -> tuple[bool, dict[str, object]]:
    state = str(os.environ.get("NIJA_RUNTIME_TRADING_STATE", "OFF") or "OFF")
    writer_raw = str(os.environ.get("NIJA_RUNTIME_EXECUTION_AUTHORITY", "0") or "0")
    writer_ready = writer_raw.strip().lower() in _TRUE
    strict = _truthy("NIJA_REQUIRE_SECONDARY_VENUES_READY", "false")
    required_ready = _truthy("NIJA_REQUIRED_VENUES_READY", "false") if strict else True
    ready = state == "LIVE_ACTIVE" and writer_ready and required_ready
    details: dict[str, object] = {
        "status": "ready" if ready else "not_ready",
        "state": state,
        "writer_authority": writer_raw,
        "strict_secondary_venues": strict,
        "required_venues_ready": required_ready,
        "required_venues": os.environ.get("NIJA_REQUIRED_LIVE_VENUES", "coinbase,okx"),
        "required_venues_missing": os.environ.get("NIJA_REQUIRED_VENUES_MISSING", ""),
        "coinbase_activation_state": os.environ.get("NIJA_COINBASE_ACTIVATION_STATE", "unknown"),
        "coinbase_connected": os.environ.get("NIJA_COINBASE_CONNECTED", "0"),
        "coinbase_trading_ready": os.environ.get("NIJA_COINBASE_TRADING_READY", "0"),
        "okx_activation_state": os.environ.get("NIJA_OKX_ACTIVATION_STATE", "unknown"),
        "okx_connected": os.environ.get("NIJA_OKX_CONNECTED", "0"),
        "okx_trading_ready": os.environ.get("NIJA_OKX_TRADING_READY", "0"),
        "uptime_seconds": round(time.time() - _STARTED_AT, 3),
        "commit": os.environ.get("GIT_COMMIT_SHORT", "unknown"),
    }
    return ready, details


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
        if self.path not in {"/", "/health", "/healthz", "/status", "/readyz"}:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        ready, details = _readiness()
        if self.path == "/readyz":
            payload_obj = details
            status_code = 200 if ready else 503
        else:
            payload_obj = dict(details)
            payload_obj["status"] = "alive"
            payload_obj["trading_ready"] = ready
            status_code = 200

        payload = json.dumps(payload_obj, separators=(",", ":")).encode("utf-8")
        try:
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            return

    def log_message(self, fmt: str, *args: object) -> None:
        return


def main() -> int:
    try:
        port = int(os.environ.get("PORT", "5000") or "5000")
    except ValueError:
        port = 5000

    server = ThreadingHTTPServer(("0.0.0.0", port), _Handler)
    server.daemon_threads = True
    server.allow_reuse_address = True

    stop = threading.Event()

    def _shutdown(signum: int, frame: object) -> None:
        del signum, frame
        if not stop.is_set():
            stop.set()
            threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    print(f"RENDER_EARLY_LIVENESS_READY port={port} readiness_path=/readyz", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
