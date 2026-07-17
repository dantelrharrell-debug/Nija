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
_MARKER = "20260717a"
_LOCK = threading.RLock()
_INSTALLED = False
_THREAD: threading.Thread | None = None
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _state_path() -> Path:
    raw = os.environ.get(
        "NIJA_RENDER_READINESS_STATE_FILE",
        "/tmp/nija_render_readiness.json",
    )
    return Path(str(raw or "/tmp/nija_render_readiness.json")).expanduser()


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in _TRUE


def _normalised_policy() -> str:
    explicit = str(os.environ.get("NIJA_SECONDARY_VENUE_POLICY", "") or "").strip().lower()
    if explicit in {"broker_local", "global_all_required", "optional"}:
        return explicit
    return "broker_local" if _truthy(os.environ.get("NIJA_REQUIRE_SECONDARY_VENUES_READY")) else "optional"


def _required_missing() -> str:
    return str(os.environ.get("NIJA_REQUIRED_VENUES_MISSING", "") or "").strip().strip(",")


def _required_ready(missing: str) -> str:
    # Missing required venues always means the required-venue set itself is not
    # ready, even when broker-local policy permits another healthy venue to trade.
    if missing:
        return "0"
    return "1" if _truthy(os.environ.get("NIJA_REQUIRED_VENUES_READY", "0")) else "0"


def _global_ready() -> str:
    for name in ("NIJA_GLOBAL_TRADING_READY", "NIJA_MULTI_BROKER_TRADING_READY"):
        if name in os.environ:
            return "1" if _truthy(os.environ.get(name)) else "0"
    active = str(os.environ.get("NIJA_ACTIVE_LIVE_VENUES", "") or "").strip().strip(",")
    return "1" if active else "0"


def _observed_balance_fields(prefix: str) -> tuple[str, str, str]:
    observed = "1" if _truthy(os.environ.get(f"NIJA_{prefix}_BALANCE_OBSERVED", "0")) else "0"
    funding_status = str(
        os.environ.get(f"NIJA_{prefix}_FUNDING_STATUS", "unobserved") or "unobserved"
    ).strip().lower()
    spendable = str(os.environ.get(f"NIJA_{prefix}_SPENDABLE_QUOTE", "") or "").strip()
    if observed != "1":
        # Do not publish a synthetic zero before the broker has authenticated and
        # completed a real balance probe. Zero is a valid observed balance and must
        # remain distinguishable from an unknown startup state.
        spendable = "unobserved"
        if funding_status in {"", "unknown", "observed_zero", "funded"}:
            funding_status = "unobserved"
    elif not spendable:
        spendable = "0"
    return observed, funding_status, spendable


def _payload() -> dict[str, Any]:
    missing = _required_missing()
    global_ready = _global_ready()
    cb_observed, cb_funding, cb_spendable = _observed_balance_fields("COINBASE")
    okx_observed, okx_funding, okx_spendable = _observed_balance_fields("OKX")
    return {
        "timestamp": time.time(),
        "pid": os.getpid(),
        "state": os.environ.get("NIJA_RUNTIME_TRADING_STATE", "OFF"),
        "writer_authority": os.environ.get("NIJA_RUNTIME_EXECUTION_AUTHORITY", "0"),
        "strict_secondary_venues": os.environ.get(
            "NIJA_REQUIRE_SECONDARY_VENUES_READY", "false"
        ),
        "secondary_venue_policy": _normalised_policy(),
        "required_venues_ready": _required_ready(missing),
        "global_trading_ready": global_ready,
        "multi_broker_trading_ready": global_ready,
        "required_venues": os.environ.get(
            "NIJA_REQUIRED_LIVE_VENUES", "coinbase,okx"
        ),
        "required_venues_missing": missing,
        "active_live_venues": os.environ.get("NIJA_ACTIVE_LIVE_VENUES", ""),
        "degraded_live_venues": os.environ.get("NIJA_DEGRADED_LIVE_VENUES", ""),
        "coinbase_activation_state": os.environ.get(
            "NIJA_COINBASE_ACTIVATION_STATE", "unknown"
        ),
        "coinbase_connected": os.environ.get("NIJA_COINBASE_CONNECTED", "0"),
        "coinbase_trading_ready": os.environ.get(
            "NIJA_COINBASE_TRADING_READY", "0"
        ),
        "coinbase_balance_observed": cb_observed,
        "coinbase_funding_status": cb_funding,
        "coinbase_spendable_quote": cb_spendable,
        "okx_activation_state": os.environ.get(
            "NIJA_OKX_ACTIVATION_STATE", "unknown"
        ),
        "okx_connected": os.environ.get("NIJA_OKX_CONNECTED", "0"),
        "okx_trading_ready": os.environ.get("NIJA_OKX_TRADING_READY", "0"),
        "okx_balance_observed": okx_observed,
        "okx_funding_status": okx_funding,
        "okx_spendable_quote": okx_spendable,
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
            "RENDER_READINESS_STATE_BRIDGE_INSTALLED marker=%s path=%s policy=%s",
            _MARKER,
            _state_path(),
            _normalised_policy(),
        )
        print(
            f"[NIJA-PRINT] RENDER_READINESS_STATE_BRIDGE_INSTALLED marker={_MARKER} "
            f"path={_state_path()} policy={_normalised_policy()}",
            flush=True,
        )


__all__ = ["install", "publish_once", "_payload", "_observed_balance_fields"]
