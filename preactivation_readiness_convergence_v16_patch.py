"""Proof-based pre-activation readiness and activation liveness repair.

This patch resolves a circular startup latch: the canonical readiness table could
remain false until LIVE_ACTIVE, while LIVE_ACTIVE itself required that table to
already be true. Every readiness key is reconstructed from current process facts
and is marked ready only when its own safety proof passes. Activation continues
through TradingStateMachine.commit_activation(); no force transition is used.

v109 also consumes the short-lived CapitalCSMv2 handoff proof published by
capital_readiness_handoff_v34. The handoff is used only to bridge object-
publication lag after CSM-v2 has accepted a fresh positive live snapshot. It is
never accepted after its TTL expires and never overrides fresher authoritative
CapitalAuthority truth.
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
_STRATEGY_PUBLICATION_MONITOR_STARTED = False
_LAST_STRATEGY_PUBLISHED = False


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


def _fresh_capital_handoff() -> dict[str, Any] | None:
    """Return a fresh CSM-v2 accepted-snapshot proof, otherwise None."""
    if not _truthy("NIJA_CAPITAL_READINESS_HANDOFF_V34"):
        return None
    accepted_at = _float(os.environ.get("NIJA_CAPITAL_HANDOFF_ACCEPTED_TS"), 0.0)
    real = _float(os.environ.get("NIJA_CAPITAL_HANDOFF_REAL"), 0.0)
    registered = _int(os.environ.get("NIJA_CAPITAL_HANDOFF_BROKER_COUNT"), 0)
    ttl = max(1.0, _float(os.environ.get("NIJA_CAPITAL_HANDOFF_TTL_S"), 90.0))
    age = max(0.0, time.time() - accepted_at) if accepted_at > 0 else float("inf")
    if accepted_at <= 0.0 or real <= 0.0 or registered <= 0 or age > ttl:
        return None
    return {
        "hydrated": True,
        "stale": False,
        "real": real,
        "registered": registered,
        "source": "csm_v2_handoff_v109",
        "handoff_age_s": age,
        "handoff_ttl_s": ttl,
    }


def _ensure_strategy_publication_monitor() -> tuple[bool, str]:
    global _STRATEGY_PUBLICATION_MONITOR_STARTED
    if _STRATEGY_PUBLICATION_MONITOR_STARTED:
        return True, "already_started"
    try:
        try:
            module = importlib.import_module("bot.strategy_publication_patch")
        except Exception:
            module = importlib.import_module("strategy_publication_patch")
        start = getattr(module, "start_monitor", None)
        if not callable(start):
            return False, "start_monitor_unavailable"
        started = bool(start())
        if started:
            _STRATEGY_PUBLICATION_MONITOR_STARTED = True
            return True, "started"
        return False, "start_monitor_returned_false"
    except Exception as exc:
        return False, f"start_monitor_failed:{type(exc).__name__}:{exc}"


def _capital_snapshot() -> dict[str, Any]:
    result: dict[str, Any] = {
        "hydrated": False,
        "stale": True,
        "real": 0.0,
        "registered": 0,
        "source": "capital_authority",
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

    authoritative_ready = bool(result.get("hydrated")) and not bool(result.get("stale")) and _float(result.get("real")) > 0.0 and _int(result.get("registered")) > 0
    if authoritative_ready:
        return result

    handoff = _fresh_capital_handoff()
    if handoff is not None:
        logger.warning(
            "PREACTIVATION_CAPITAL_V109_HANDOFF_USED marker=%s authority_hydrated=%s authority_real=%.2f authority_registered=%d handoff_real=%.2f handoff_registered=%d age_s=%.3f ttl_s=%.1f",
            _MARKER,
            bool(result.get("hydrated")),
            _float(result.get("real")),
            _int(result.get("registered")),
            _float(handoff.get("real")),
            _int(handoff.get("registered")),
            _float(handoff.get("handoff_age_s")),
            _float(handoff.get("handoff_ttl_s")),
        )
        if "error" in result:
            handoff["authority_error"] = result["error"]
        return handoff
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
        return bool(callable(execute) and _truthy("NIJA_PRE_DISPATCH_RISK_SIZING_READY") and _truthy("NIJA_PRE_DISPATCH_RISK_SIZING_FAIL_CLOSED"))
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
    state_value = "UNAVAILABLE"
    try:
        try:
            module = importlib.import_module("bot.bootstrap_state_machine")
        except Exception:
            module = importlib.import_module("bootstrap_state_machine")
        fsm = module.get_bootstrap_fsm()
        state = getattr(fsm, "state", None)
        state_value = str(getattr(state, "value", state) or "UNKNOWN").strip().upper()
    except Exception:
        state_value = "UNAVAILABLE"
    required = {
        "bootstrap_supervised": state_value == "RUNNING_SUPERVISED",
        "module_identity": _truthy("NIJA_RUNTIME_MODULE_IDENTITY_READY"),
        "scan_wrapper_depth": _truthy("NIJA_SCAN_WRAPPER_DEPTH_READY"),
        "zero_signal_state": _truthy("NIJA_ZERO_SIGNAL_STREAK_STATE_READY"),
        "pre_dispatch_risk": _truthy("NIJA_PRE_DISPATCH_RISK_SIZING_READY"),
    }
    missing = [name for name, ready in required.items() if not ready]
    if state_value != "RUNNING_SUPERVISED":
        missing.append(f"bootstrap_state:{state_value}")
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
    risk = bool(_truthy("NIJA_PRE_DISPATCH_RISK_SIZING_READY") and _truthy("NIJA_PRE_DISPATCH_RISK_SIZING_FAIL_CLOSED") and _truthy("NIJA_DOWNSTREAM_RISK_GOVERNOR_V2_INSTALLED"))
    authority = bool(strict_ok and kill_ok)
    proofs = {
        "broker_connected": bool(hydrated and funded and registered),
        "balance_hydrated": hydrated,
        "authority_ready": authority,
        "capital_ready": bool(_live_mode() and hydrated and funded),
        "risk_ready": risk,
        "strategy_ready": strategy,
        "execution_ready": bool(execution and risk and authority),
        "nonce_ready": strict_ok,
        "bootstrap_ready": bootstrap_ok,
    }
    details = {
        "capital": capital,
        "strict_authority": strict_detail,
        "kill_switch": kill_detail or "clear",
        "bootstrap_missing": bootstrap_missing,
        "live_mode": _live_mode(),
        "execution_pipeline_wired": execution,
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
        if not after:
            os.environ["NIJA_AUTHORITY_READY"] = "1" if bool(proofs.get("authority_ready")) else "0"
            os.environ["NIJA_NONCE_READY"] = "1" if bool(proofs.get("nonce_ready")) else "0"
            os.environ["NIJA_RUNTIME_NONCE_READY"] = os.environ["NIJA_NONCE_READY"]
            logger.critical("PREACTIVATION_READY authority_ready=%s nonce_ready=%s writer_authority=confirmed blockers_cleared=true", bool(proofs.get("authority_ready")), bool(proofs.get("nonce_ready")))
        logger.critical("PREACTIVATION_READINESS_V16_RECONSTRUCTED marker=%s before=%s after=%s proofs=%s", _MARKER, before, after, proofs)
        return not after, after
    except Exception as exc:
        os.environ["NIJA_PREACTIVATION_READINESS_V16_READY"] = "0"
        return False, [f"readiness_table_error:{exc}"]


def _rearm_unsafe_timeout(sm: Any) -> None:
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


def _retry_activation_after_publication() -> tuple[bool, dict[str, Any]]:
    max_attempts = max(1, _int(os.environ.get("NIJA_POST_PUBLICATION_ACTIVATION_MAX_ATTEMPTS"), 3))
    delay_s = max(0.0, _float(os.environ.get("NIJA_POST_PUBLICATION_ACTIVATION_INITIAL_DELAY_S"), 0.25))
    max_delay_s = max(delay_s, _float(os.environ.get("NIJA_POST_PUBLICATION_ACTIVATION_MAX_DELAY_S"), 1.5))
    backoff = max(1.0, _float(os.environ.get("NIJA_POST_PUBLICATION_ACTIVATION_BACKOFF"), 2.0))
    last_details: dict[str, Any] = {"activation": "post_publication_retry_not_attempted"}
    for attempt in range(1, max_attempts + 1):
        active, details = _attempt_activation()
        last_details = details
        blockers = details.get("pending") or details.get("activation") or "none"
        logger.warning("POST_PUBLICATION_ACTIVATION_RETRY attempt=%d/%d active=%s delay_s=%.2f blockers=%s", attempt, max_attempts, str(active).lower(), delay_s if attempt < max_attempts else 0.0, blockers)
        if active:
            logger.critical("POST_PUBLICATION_ACTIVATION_RETRY_SUCCESS attempts=%d state=%s", attempt, details.get("state_after") or details.get("state_before") or "unknown")
            details["post_publication_retry_attempts"] = attempt
            return True, details
        if attempt < max_attempts:
            time.sleep(delay_s)
            delay_s = min(max_delay_s, delay_s * backoff if delay_s > 0.0 else max_delay_s)
    logger.warning("POST_PUBLICATION_ACTIVATION_RETRY_EXHAUSTED attempts=%d blockers=%s", max_attempts, last_details.get("pending") or last_details.get("activation") or "unknown")
    last_details["post_publication_retry_attempts"] = max_attempts
    return False, last_details


def _attempt_activation() -> tuple[bool, dict[str, Any]]:
    proofs, details = _collect_proofs()
    ready, pending = _mark_proven_readiness(proofs)
    details["proofs"] = proofs
    details["pending"] = pending
    monitor_started, monitor_detail = _ensure_strategy_publication_monitor()
    details["strategy_publication_monitor"] = {"started": monitor_started, "detail": monitor_detail}
    try:
        try:
            module = importlib.import_module("bot.trading_state_machine")
        except Exception:
            module = importlib.import_module("trading_state_machine")
        sm = module.get_trading_state_machine()
        _rearm_unsafe_timeout(sm)
        before = sm.get_current_state()
        details["state_before"] = str(getattr(before, "value", before))
        if not ready:
            return False, details
        active = bool(sm.commit_activation())
        after = sm.get_current_state()
        details["state_after"] = str(getattr(after, "value", after))
        return active, details
    except Exception as exc:
        details["activation"] = f"{type(exc).__name__}:{exc}"
        return False, details


def _monitor() -> None:
    global _LAST_SIGNATURE, _LAST_STRATEGY_PUBLISHED
    interval = max(0.25, _float(os.environ.get("NIJA_PREACTIVATION_READINESS_POLL_S"), 1.0))
    while True:
        try:
            active, details = _attempt_activation()
            proofs = details.get("proofs", {})
            strategy_published = bool(proofs.get("strategy_ready"))
            signature = repr((active, details.get("pending"), proofs, details.get("state_before"), details.get("state_after")))
            if signature != _LAST_SIGNATURE:
                _LAST_SIGNATURE = signature
                logger.warning("PREACTIVATION_READINESS_V16_STATE marker=%s active=%s blockers=%s details=%s persistent=true force_transition=false", _MARKER, str(active).lower(), details.get("pending", []), details)
            if strategy_published and not _LAST_STRATEGY_PUBLISHED and not active:
                _retry_activation_after_publication()
            _LAST_STRATEGY_PUBLISHED = strategy_published
        except Exception as exc:
            logger.warning("PREACTIVATION_READINESS_V16_MONITOR_ERROR marker=%s error=%s:%s", _MARKER, type(exc).__name__, exc)
        time.sleep(interval)


def install() -> bool:
    global _STARTED
    with _LOCK:
        if _STARTED:
            return True
        thread = threading.Thread(target=_monitor, name="preactivation-readiness-v16", daemon=True)
        thread.start()
        _STARTED = thread.is_alive()
    if not _STARTED:
        return False
    os.environ["NIJA_PREACTIVATION_READINESS_V16_INSTALLED"] = "1"
    logger.warning("PREACTIVATION_READINESS_V16_INSTALLED marker=%s proof_based=true force_transition=false capital_handoff_v109=true", _MARKER)
    return True


install_import_hook = install

__all__ = ["install", "install_import_hook", "_capital_snapshot", "_fresh_capital_handoff", "_collect_proofs"]
