"""Heartbeat position-cap result bridge v303.

Production generation 5020 on 2026-08-30 proved that v273's venue-failover
policy could not observe a genuine position-cap rejection produced by the
pipeline execution worker.  v273 records the hardening rejection in
thread-local state and requires the current thread to be ``HeartbeatTrade``.
The canonical pipeline correctly propagates the startup-probe ContextVar into
its execution worker, but the worker is a different thread and thread-local
writes do not return to the caller.  The unchanged pipeline result therefore
returned ``POSITION_CAP_EXCEEDED`` to the HeartbeatTrade caller while v273 saw
no cap block and did not quarantine/fail over the venue.

v303 bridges only that already-returned rejection result on the HeartbeatTrade
caller.  It wraps the ``submit_market_order_via_pipeline`` symbol used by the
trading-strategy module, leaves the result object untouched, and when all of the
following are true records the same rejection into v273's existing caller-local
slot: the strategy is exactly HEARTBEAT_TRADE, the side is an entry BUY, v273's
existing trusted startup-probe verifier succeeds, and the returned error is an
explicit position-cap denial.  v273 then performs its existing canonical-ready
venue quarantine/retry logic.

The position cap itself is never bypassed or reclassified.  A rejected order is
never treated as submitted, filled, or as execution proof.  Ordinary orders,
account limits, writer/nonce authority, risk, capital, kill switch, broker
health, minimum notional, acknowledgement/fill confirmation, activation, and
all exchange semantics are unchanged.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
from collections.abc import Mapping
from functools import wraps
from types import ModuleType
from typing import Any, Callable

LOGGER = logging.getLogger("nija.runtime_heartbeat_position_cap_result_bridge_v303")
MARKER = "20260830-heartbeat-position-cap-result-bridge-v303"
RELEASE_ID = "20260830-runtime-convergence-v303"
_READY_FLAG = "NIJA_RUNTIME_HEARTBEAT_POSITION_CAP_RESULT_BRIDGE_V303_READY"
_PATCH_ATTR = "_nija_heartbeat_position_cap_result_bridge_v303"
_ALLOWED_STRATEGY = "HEARTBEAT_TRADE"
_ALLOWED_ENTRY_SIDES = {"BUY", "ENTER", "OPEN"}


def _v273() -> Any:
    return importlib.import_module("bot.runtime_heartbeat_position_cap_failover_v273_patch")


def _cap_rejection_detail(result: Any) -> str:
    if not isinstance(result, Mapping):
        return ""
    status = str(result.get("status", "") or "").strip().lower()
    detail = str(result.get("error", "") or result.get("message", "") or "").strip()
    upper = detail.upper()
    if status not in {"error", "rejected", "failed", "unfilled"}:
        return ""
    if "POSITION_CAP_EXCEEDED" not in upper and "POSITION CAP REACHED" not in upper:
        return ""
    return detail


def _trusted_startup_probe() -> tuple[bool, str]:
    try:
        verifier = getattr(_v273(), "_trusted_heartbeat_probe", None)
        if not callable(verifier):
            return False, "v273_trusted_probe_unavailable"
        ok, detail = verifier()
        return bool(ok), str(detail or "")
    except Exception as exc:
        return False, f"v273_trusted_probe_error:{type(exc).__name__}:{exc}"


def _record_cap_block(detail: str, *, symbol: str, side: str) -> bool:
    try:
        setter = getattr(_v273(), "_set_cap_block", None)
        if not callable(setter):
            return False
        setter(detail, symbol=symbol, side=side)
        return True
    except Exception:
        return False


def _wrap_submit(current: Callable[..., Any]) -> Callable[..., Any]:
    if bool(getattr(current, _PATCH_ATTR, False)):
        return current

    @wraps(current)
    def submit_v303(*args: Any, **kwargs: Any) -> Any:
        result = current(*args, **kwargs)
        try:
            strategy = str(kwargs.get("strategy", "") or "").strip().upper()
            side = str(kwargs.get("side", "") or "").strip().upper()
            if strategy != _ALLOWED_STRATEGY or side not in _ALLOWED_ENTRY_SIDES:
                return result

            detail = _cap_rejection_detail(result)
            if not detail:
                return result

            trusted, probe_reason = _trusted_startup_probe()
            if not trusted or str(probe_reason or "").strip().upper() != _ALLOWED_STRATEGY:
                LOGGER.warning(
                    "HEARTBEAT_POSITION_CAP_V303_BRIDGE_REJECTED marker=%s reason=%s "
                    "pipeline_result_unchanged=true position_cap_unchanged=true trading_fail_closed=true",
                    MARKER,
                    probe_reason or "startup_probe_not_verified",
                )
                return result

            symbol = str(kwargs.get("symbol", "") or "")
            if not _record_cap_block(detail, symbol=symbol, side=side):
                LOGGER.error(
                    "HEARTBEAT_POSITION_CAP_V303_BRIDGE_FAILED marker=%s symbol=%s "
                    "pipeline_result_unchanged=true position_cap_unchanged=true trading_fail_closed=true",
                    MARKER,
                    symbol,
                )
                return result

            LOGGER.critical(
                "HEARTBEAT_POSITION_CAP_V303_RESULT_BRIDGED marker=%s symbol=%s side=%s detail=%s "
                "caller_thread_signal=true pipeline_result_unchanged=true order_submitted=false fill=false "
                "position_cap_unchanged=true canonical_v273_failover_only=true execution_proof_fabricated=false "
                "writer_nonce_risk_capital_killswitch_broker_health_min_notional_order_ack_fill_gates_unchanged=true "
                "safety_gates_bypassed=false",
                MARKER,
                symbol,
                side,
                detail,
            )
        except Exception as exc:
            LOGGER.warning(
                "HEARTBEAT_POSITION_CAP_V303_BRIDGE_EXCEPTION marker=%s error=%s:%s "
                "pipeline_result_unchanged=true position_cap_unchanged=true trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
        return result

    setattr(submit_v303, _PATCH_ATTR, True)
    setattr(submit_v303, "__wrapped__", current)
    return submit_v303


def _patch_strategy_module(module: ModuleType) -> bool:
    current = getattr(module, "submit_market_order_via_pipeline", None)
    if not callable(current):
        return False
    wrapped = _wrap_submit(current)
    setattr(module, "submit_market_order_via_pipeline", wrapped)
    return bool(getattr(getattr(module, "submit_market_order_via_pipeline", None), _PATCH_ATTR, False))


def _patch_loaded_strategy_surfaces() -> tuple[bool, tuple[str, ...]]:
    try:
        importlib.import_module("bot.trading_strategy")
    except Exception as exc:
        LOGGER.warning(
            "HEARTBEAT_POSITION_CAP_V303_STRATEGY_IMPORT_DEFERRED marker=%s error=%s:%s",
            MARKER,
            type(exc).__name__,
            exc,
        )

    patched: list[str] = []
    for name in ("bot.trading_strategy", "trading_strategy"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and _patch_strategy_module(module):
            patched.append(name)
    return bool(patched), tuple(sorted(set(patched)))


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_heartbeat_position_cap_result_bridge_v303"] = _READY_FLAG
        return True
    except Exception:
        return False


def reconcile_once() -> dict[str, Any]:
    patched, surfaces = _patch_loaded_strategy_surfaces()
    return {
        "ready": bool(patched),
        "strategy_surfaces": surfaces,
        "v273_bridge_target": callable(getattr(_v273(), "_set_cap_block", None)),
    }


def install() -> bool:
    manifest_ok = _register_manifest()
    try:
        state = reconcile_once()
    except Exception as exc:
        state = {"ready": False, "strategy_surfaces": (), "v273_bridge_target": False, "error": f"{type(exc).__name__}:{exc}"}

    ready = bool(manifest_ok and state.get("ready") and state.get("v273_bridge_target"))
    os.environ[_READY_FLAG] = "1" if ready else "0"
    log = LOGGER.critical if ready else LOGGER.error
    log(
        "RUNTIME_HEARTBEAT_POSITION_CAP_RESULT_BRIDGE_V303_%s marker=%s ready=%s surfaces=%s "
        "caller_result_observation=true v273_bridge_target=%s trusted_startup_probe_only=true "
        "position_cap_unchanged=true pipeline_result_unchanged=true ordinary_orders_unchanged=true "
        "execution_proof_fabricated=false forced_trade=false forced_activation=false "
        "writer_nonce_risk_capital_killswitch_broker_health_min_notional_order_ack_fill_gates_unchanged=true "
        "safety_gates_bypassed=false",
        "READY" if ready else "NOT_READY",
        MARKER,
        str(ready).lower(),
        ",".join(state.get("strategy_surfaces", ()) or ()) or "none",
        str(bool(state.get("v273_bridge_target"))).lower(),
    )
    return ready


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "reconcile_once",
    "_cap_rejection_detail",
    "_wrap_submit",
    "_patch_strategy_module",
    "_patch_loaded_strategy_surfaces",
]
