"""Proof-based pre-activation readiness and activation liveness repair.

This patch resolves a circular startup latch: the canonical readiness table could
remain false until LIVE_ACTIVE, while LIVE_ACTIVE itself required that table to
already be true. Every readiness key is reconstructed from current process facts
and is marked ready only when its own safety proof passes. Activation continues
through TradingStateMachine.commit_activation(); no force transition is used.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.preactivation_readiness_convergence_v16")
_MARKER = "20260723-preactivation-readiness-v16"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_KEYS = (
    "broker_connected",
    "balance_hydrated",
    "authority_ready",
    "capital_ready",
    "risk_ready",
    "strategy_ready",
    "execution_ready",
    "nonce_ready",
    "bootstrap_ready",
)
_LOCK = threading.RLock()
_STARTED = False
_LAST_SIGNATURE = ""


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in _TRUE


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value not in (None, "") else default)
    except Exception:
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value if value not in (None, "") else default))
    except Exception:
        return default


def _live_mode() -> bool:
    return _truthy("LIVE_CAPITAL_VERIFIED") and not _truthy("DRY_RUN_MODE") and not _truthy("PAPER_MODE")


def _capital_snapshot() -> dict[str, Any]:
    result: dict[str, Any] = {
        "hydrated": False,
        "stale": True,
        "real": 0.0,
        "registered": 0,
    }
    try:
        try:
            module = importlib.import_module("bot.capital_authority")
        except Exception:
            module = importlib.import_module("capital_authority")
        authority = module.get_capital_authority()
        result["hydrated"] = bool(getattr(authority, "is_hydrated", False))
        result["real"] = max(
            _float(getattr(authority, "total_capital", 0.0)),
            _float(getattr(authority, "real_capital", 0.0)),
            _float(getattr(authority, "available_capital", 0.0)),
        )
        for method_name in ("get_real_capital", "get_total_capital", "get_usable_capital"):
            method = getattr(authority, method_name, None)
            if callable(method):
                try:
                    result["real"] = max(result["real"], _float(method()))
                except Exception:
                    pass
        result["registered"] = max(
            _int(getattr(authority, "registered_broker_count", 0)),
            _int(getattr(authority, "valid_broker_count", 0)),
        )
        values = getattr(authority, "broker_values", None) or getattr(authority, "values", None) or {}
        if isinstance(values, dict):
            result["registered"] = max(
                result["registered"],
                sum(1 for value in values.values() if _float(value) > 0.0),
            )
        stale = getattr(authority, "is_stale", None)
        result["stale"] = bool(stale()) if callable(stale) else bool(getattr(authority, "stale", False))
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}:{exc}"
    return result


def _strategy_published() -> bool:
    for module_name in ("__main__", "bot", "bot.bot", "bot.trading_strategy", "trading_strategy"):
        module = sys.modules.get(module_name)
        if not isinstance(module, ModuleType):
            continue
        for attr in ("TRADING_STRATEGY", "strategy", "trading_strategy", "_published_strategy"):
            value = getattr(module, attr, None)
            if value is not None and type(value).__name__ == "TradingStrategy":
                return True
    return False


def _execution_pipeline_ready() -> bool:
    try:
        module = sys.modules.get("bot.execution_pipeline") or importlib.import_module("bot.execution_pipeline")
        pipeline = getattr(module, "ExecutionPipeline", None)
        execute = getattr(pipeline, "execute", None) if isinstance(pipeline, type) else None
        return bool(
            callable(execute)
            and _truthy("NIJA_PRE_DISPATCH_RISK_SIZING_READY")
            and _truthy("NIJA_PRE_DISPATCH_RISK_SIZING_FAIL_CLOSED")
        )
    except Exception:
        return False


def _kill_switch_clear() -> tuple[bool, str]:
    try:
        try:
            module = importlib.import_module("bot.kill_switch")
        except Exception:
            module = importlib.import_module("kill_switch")
        active = bool(module.get_kill_switch().is_active())
        return (not active), ("kill_switch_active" if active else "")
    except Exception as exc:
        return False, f"kill_switch_probe_failed:{exc}"


def _heartbeat_ready() -> tuple[bool, str]:
    if os.environ.get("NIJA_WRITER_HEARTBEAT_ACTIVE", "").strip() != "1":
        return False, "writer_heartbeat_inactive"
    alive = _float(os.environ.get("NIJA_WRITER_HEARTBEAT_ALIVE_TS"), 0.0)
    if alive <= 0.0:
        return False, "writer_heartbeat_alive_ts_missing"
    max_age = max(5.0, _float(os.environ.get("NIJA_PREACTIVATION_HEARTBEAT_MAX_AGE_S"), 90.0))
    age = max(0.0, time.time() - alive)
    if age > max_age:
        return False, f"writer_heartbeat_stale:{age:.1f}>{max_age:.1f}"
    return True, f"writer_heartbeat_fresh:{age:.1f}s"


def _strict_authority_ready() -> tuple[bool, str]:
    token = os.environ.get("NIJA_WRITER_FENCING_TOKEN", "").strip()
    generation = os.environ.get("NIJA_WRITER_LEASE_GENERATION", "").strip()
    if not token or not generation:
        return False, f"writer_identity_missing:token={bool(token)} generation={generation or 'missing'}"
    heartbeat_ok, heartbeat_detail = _heartbeat_ready()
    if not heartbeat_ok:
        return False, heartbeat_detail
    try:
        try:
            module = importlib.import_module("bot.trading_state_machine")
        except Exception:
            module = importlib.import_module("trading_state_machine")
        probe = getattr(module, "_runtime_writer_nonce_ready", None)
        if not callable(probe):
            return False, "runtime_writer_nonce_probe_missing"
        ready, detail = probe()
        if not bool(ready):
            return False, str(detail or "runtime_writer_nonce_not_ready")
        return True, str(detail or "strict_writer_nonce_ready")
    except Exception as exc:
        return False, f"runtime_writer_nonce_probe_failed:{exc}"


def _bootstrap_ready() -> tuple[bool, list[str]]:
    required = {
        "module_identity": _truthy("NIJA_RUNTIME_MODULE_IDENTITY_READY"),
        "scan_wrapper_depth": _truthy("NIJA_SCAN_WRAPPER_DEPTH_READY"),
        "zero_signal_state": _truthy("NIJA_ZERO_SIGNAL_STREAK_STATE_READY"),
        "pre_dispatch_risk": _truthy("NIJA_PRE_DISPATCH_RISK_SIZING_READY"),
    }
    missing = [name for name, ready in required.items() if not ready]
    return not missing, missing


def _collect_proofs() -> tuple[dict[str, bool], dict[str, Any]]:
    capital = _capital_snapshot()
    strict_ok, strict_detail = _strict_authority_ready()
    kill_ok, kill_detail = _kill_switch_clear()
    bootstrap_ok, bootstrap_missing = _bootstrap_ready()
    strategy = _strategy_published()
    execution = _execution_pipeline_ready()
    hydrated = bool(capital.get("hydrated")) and not bool(capital.get("stale"))
    funded = _float(capital.get("real")) > 0.0
    registered = _int(capital.get("registered")) > 0
    risk = bool(
        _truthy("NIJA_PRE_DISPATCH_RISK_SIZING_READY")
        and _truthy("NIJA_PRE_DISPATCH_RISK_SIZING_FAIL_CLOSED")
        and _truthy("NIJA_DOWNSTREAM_RISK_GOVERNOR_V2_INSTALLED")
    )
    authority = bool(strict_ok and kill_ok)
    proofs = {
        "broker_connected": bool(hydrated and funded and registered),
        "balance_hydrated": hydrated,
        "authority_ready": authority,
        "capital_ready": bool(_live_mode() and hydrated and funded),
        "risk_ready": risk,
        "strategy_ready": strategy,
        "execution_ready": bool(execution and risk),
        "nonce_ready": strict_ok,
        "bootstrap_ready": bootstrap_ok,
    }
    details = {
        "capital": capital,
        "strict_authority": strict_detail,
        "kill_switch": kill_detail or "clear",
        "bootstrap_missing": bootstrap_missing,
        "live_mode": _live_mode(),
    }
    return proofs, details


def _mark_proven_readiness(proofs: dict[str, bool]) -> tuple[bool, list[str]]:
    pending = [key for key in _KEYS if not bool(proofs.get(key))]
    if pending:
        return False, pending
    try:
        try:
            table = importlib.import_module("bot.readiness_table")
        except Exception:
            table = importlib.import_module("readiness_table")
        before = list(table.pending())
        for key in _KEYS:
            table.mark_ready(key)
        after = list(table.pending())
        os.environ["NIJA_PREACTIVATION_READINESS_V16_READY"] = "1" if not after else "0"
        logger.critical(
            "PREACTIVATION_READINESS_V16_RECONSTRUCTED marker=%s before=%s after=%s proofs=%s",
            _MARKER,
            before,
            after,
            proofs,
        )
        return not after, after
    except Exception as exc:
        os.environ["NIJA_PREACTIVATION_READINESS_V16_READY"] = "0"
        return False, [f"readiness_table_error:{exc}"]


def _rearm_unsafe_timeout(sm: Any) -> None:
    """Prevent the legacy timeout force-path; normal commit gates remain authoritative."""
    if _truthy("NIJA_ALLOW_PENDING_CONFIRMATION_FORCE_TIMEOUT", "false"):
        return
    try:
        with getattr(sm, "_lock", threading.RLock()):
            state = sm.get_current_state()
            state_value = str(getattr(state, "value", state) or "")
            if state_value == "LIVE_PENDING_CONFIRMATION":
                sm._pending_confirmation_since = time.monotonic()
    except Exception:
        pass


def _attempt_activation() -> tuple[bool, dict[str, Any]]:
    proofs, details = _collect_proofs()
    ready, pending = _mark_proven_readiness(proofs)
    details["proofs"] = proofs
    details["pending"] = pending
    if not ready:
        return False, details
    try:
        try:
            monitor = importlib.import_module("bot.activation_pending_commit_monitor_patch")
        except Exception:
            monitor = importlib.import_module("activation_pending_commit_monitor_patch")
        sm = monitor._state_machine()
        if sm is None:
            details["activation"] = "state_machine_unavailable"
            return False, details
        state = monitor._current_state_value(sm)
        details["state_before"] = state
        if state == "LIVE_ACTIVE":
            return True, details
        if state not in {"OFF", "LIVE_PENDING_CONFIRMATION"}:
            details["activation"] = f"state_not_armable:{state}"
            return False, details
        accepted, meta = monitor._capital_ready_snapshot()
        if not accepted:
            details["activation"] = f"capital_snapshot_not_accepted:{meta}"
            return False, details
        _rearm_unsafe_timeout(sm)
        committed = bool(monitor._commit_once(sm, meta))
        state_after = monitor._current_state_value(sm)
        details["state_after"] = state_after
        details["activation"] = "committed" if committed else "normal_commit_rejected"
        return bool(committed and state_after == "LIVE_ACTIVE"), details
    except Exception as exc:
        details["activation"] = f"activation_attempt_failed:{type(exc).__name__}:{exc}"
        return False, details


def _cycle() -> tuple[bool, dict[str, Any]]:
    try:
        v15 = importlib.import_module("runtime_convergence_v15_patch")
        installer = getattr(v15, "install", None)
        if callable(installer):
            installer()
    except Exception:
        pass
    if not _live_mode():
        return False, {"live_mode": False}
    return _attempt_activation()


def _monitor() -> None:
    global _LAST_SIGNATURE
    interval = max(0.5, _float(os.environ.get("NIJA_PREACTIVATION_V16_INTERVAL_S"), 2.0))
    while True:
        try:
            active, details = _cycle()
            signature = repr((active, details))
            if signature != _LAST_SIGNATURE:
                _LAST_SIGNATURE = signature
                blockers = details.get("pending") or details.get("activation") or "none"
                logger.log(
                    logging.INFO if active else logging.WARNING,
                    "PREACTIVATION_READINESS_V16_STATE marker=%s active=%s blockers=%s details=%s persistent=true force_transition=false",
                    _MARKER,
                    str(active).lower(),
                    blockers,
                    details,
                )
        except Exception:
            logger.exception("PREACTIVATION_READINESS_V16_RETRY marker=%s", _MARKER)
        time.sleep(interval)


def install() -> bool:
    global _STARTED
    with _LOCK:
        if _STARTED:
            return True
        _STARTED = True
        os.environ["NIJA_PREACTIVATION_READINESS_V16_INSTALLED"] = "1"
        thread = threading.Thread(target=_monitor, name="PreActivationReadinessV16", daemon=True)
        thread.start()
        logger.critical(
            "PREACTIVATION_READINESS_V16_INSTALLED marker=%s persistent=true proof_based=true normal_commit_only=true thread_alive=%s",
            _MARKER,
            thread.is_alive(),
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "install",
    "install_import_hook",
    "_collect_proofs",
    "_mark_proven_readiness",
    "_attempt_activation",
    "_cycle",
    "_rearm_unsafe_timeout",
]
