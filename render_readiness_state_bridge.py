"""Publish NIJA trading readiness for the separate Render liveness process.

The early HTTP server is launched as a sibling process before writer acquisition.
Process environments are not shared, so later runtime state must be communicated
through an atomic file rather than stale inherited environment variables.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("nija.render_readiness_bridge")
_MARKER = "20260711b"
_LOCK = threading.RLock()
_INSTALLED = False
_THREAD: threading.Thread | None = None


def _state_path() -> Path:
    raw = os.environ.get(
        "NIJA_RENDER_READINESS_STATE_FILE",
        "/tmp/nija_render_readiness.json",
    )
    return Path(str(raw or "/tmp/nija_render_readiness.json")).expanduser()


def _payload() -> dict[str, Any]:
    return {
        "timestamp": time.time(),
        "pid": os.getpid(),
        "state": os.environ.get("NIJA_RUNTIME_TRADING_STATE", "OFF"),
        "writer_authority": os.environ.get("NIJA_RUNTIME_EXECUTION_AUTHORITY", "0"),
        "strict_secondary_venues": os.environ.get(
            "NIJA_REQUIRE_SECONDARY_VENUES_READY", "false"
        ),
        "required_venues_ready": os.environ.get("NIJA_REQUIRED_VENUES_READY", "0"),
        "required_venues": os.environ.get(
            "NIJA_REQUIRED_LIVE_VENUES", "coinbase,okx"
        ),
        "required_venues_missing": os.environ.get(
            "NIJA_REQUIRED_VENUES_MISSING", "coinbase,okx"
        ),
        "coinbase_activation_state": os.environ.get(
            "NIJA_COINBASE_ACTIVATION_STATE", "unknown"
        ),
        "coinbase_connected": os.environ.get("NIJA_COINBASE_CONNECTED", "0"),
        "coinbase_trading_ready": os.environ.get(
            "NIJA_COINBASE_TRADING_READY", "0"
        ),
        "coinbase_spendable_quote": os.environ.get(
            "NIJA_COINBASE_SPENDABLE_QUOTE", "0"
        ),
        "okx_activation_state": os.environ.get(
            "NIJA_OKX_ACTIVATION_STATE", "unknown"
        ),
        "okx_connected": os.environ.get("NIJA_OKX_CONNECTED", "0"),
        "okx_trading_ready": os.environ.get("NIJA_OKX_TRADING_READY", "0"),
        "okx_spendable_quote": os.environ.get("NIJA_OKX_SPENDABLE_QUOTE", "0"),
        "commit": os.environ.get(
            "GIT_COMMIT_SHORT",
            os.environ.get("RENDER_GIT_COMMIT", "unknown")[:12],
        ),
    }


def publish_once() -> dict[str, Any]:
    payload = _payload()
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            if os.path.exists(temporary):
                os.unlink(temporary)
        except OSError:
            pass
    return payload


def _loop() -> None:
    while True:
        try:
            publish_once()
        except Exception:
            logger.exception("RENDER_READINESS_STATE_PUBLISH_FAILED marker=%s", _MARKER)
        try:
            interval = max(
                0.5,
                float(os.environ.get("NIJA_RENDER_READINESS_PUBLISH_S", "1") or "1"),
            )
        except (TypeError, ValueError):
            interval = 1.0
        time.sleep(interval)


def install() -> None:
    global _INSTALLED, _THREAD
    with _LOCK:
        if _INSTALLED:
            publish_once()
            return
        _INSTALLED = True
        publish_once()
        _THREAD = threading.Thread(
            target=_loop,
            name="render-readiness-state-bridge",
            daemon=True,
        )
        _THREAD.start()
        os.environ["NIJA_RENDER_READINESS_BRIDGE_INSTALLED"] = "1"
        logger.warning(
            "RENDER_READINESS_STATE_BRIDGE_INSTALLED marker=%s path=%s",
            _MARKER,
            _state_path(),
        )
        print(
            f"[NIJA-PRINT] RENDER_READINESS_STATE_BRIDGE_INSTALLED marker={_MARKER} "
            f"path={_state_path()}",
            flush=True,
        )


__all__ = ["install", "publish_once"]
