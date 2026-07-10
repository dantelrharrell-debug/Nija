"""Minimal Render liveness endpoint available before NIJA broker startup.

The endpoint intentionally reports process liveness, not trading readiness. Writer
authority, broker hydration, and LIVE_ACTIVE remain enforced by the normal NIJA
runtime gates.
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


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
        if self.path not in {"/", "/health", "/healthz", "/status"}:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        payload = json.dumps(
            {
                "status": "alive",
                "state": os.environ.get("NIJA_RUNTIME_TRADING_STATE", "OFF"),
                "writer_authority": os.environ.get(
                    "NIJA_RUNTIME_EXECUTION_AUTHORITY", "0"
                ),
                "uptime_seconds": round(time.time() - _STARTED_AT, 3),
                "commit": os.environ.get("GIT_COMMIT_SHORT", "unknown"),
            },
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            self.send_response(200)
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
    print(f"RENDER_EARLY_LIVENESS_READY port={port}", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
