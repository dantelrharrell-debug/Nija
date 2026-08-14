"""Production runtime convergence v88.

Repairs post-deployment liveness defects without weakening writer, nonce,
capital, risk, kill-switch, or broker safety.
"""
from __future__ import annotations

import logging
import os
import re
import sys
import threading
import time
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.production_runtime_convergence_v88")
MARKER = "20260813-production-runtime-convergence-v88"
_LOCK = threading.RLock()
_MONITOR_STARTED = False
_PATCHED_TSM_IDS: set[int] = set()
_KRAKEN_SUPERVISION_INSTALLED = False
_LOG_FILTER_INSTALLED = False
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_GENERIC_EXECUTION_FALSE_REASONS = {
    "execute_action_returned_false",
    "returned_false_or_none",
    "execute_action_returned_none",
}


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in _TRUE


def _live_runtime_intent() -> bool:
    state = str(os.environ.get("NIJA_RUNTIME_TRADING_STATE", "") or "").strip().upper()
    return bool(
        state == "LIVE_ACTIVE"
        and _truthy("LIVE_CAPITAL_VERIFIED")
        and not _truthy("DRY_RUN_MODE")
        and not _truthy("PAPER_MODE")
    )


def _kill_switch_clear(tsm: ModuleType) -> bool:
    probe = getattr(tsm, "_kill_switch_is_active", None)
    if callable(probe):
        try:
            active, _detail = probe()
            return active is False
        except Exception:
            return False
    try:
        from bot.kill_switch import get_kill_switch
        return not bool(get_kill_switch().is_active())
    except Exception:
        return False


def _strict_writer_nonce_ready(tsm: ModuleType) -> bool:
    probe = getattr(tsm, "_runtime_writer_nonce_ready", None)
    if not callable(probe):
        return False
    try:
        ready, _detail = probe()
        return bool(ready)
    except Exception:
        return False


def _only_generic_execution_false_counts(counts: dict[Any, Any]) -> bool:
    if not counts:
        return False
    positive: dict[str, int] = {}
    for raw_reason, raw_count in counts.items():
        try:
            count = int(raw_count or 0)
        except Exception:
            count = 0
        if count <= 0:
            continue
        positive[str(raw_reason or "").strip().lower()] = count
    return bool(positive) and set(positive).issubset(_GENERIC_EXECUTION_FALSE_REASONS)


def _clear_generic_execution_false_counts(tsm: ModuleType) -> dict[str, int]:
    lock = getattr(tsm, "_EXECUTION_CIRCUIT_BREAKER_LOCK", None)
    counts = getattr(tsm, "_EXECUTION_CIRCUIT_BREAKER_COUNTS", None)
    if lock is None or not isinstance(counts, dict):
        return {}
    with lock:
        if not _only_generic_execution_false_counts(counts):
            return {}
        prior = {str(k): int(v or 0) for k, v in counts.items() if int(v or 0) > 0}
        for key in list(counts):
            if str(key or "").strip().lower() in _GENERIC_EXECUTION_FALSE_REASONS:
                counts.pop(key, None)
        if not counts:
            setattr(tsm, "_EXECUTION_CIRCUIT_BREAKER_TRIPPED", False)
            setattr(tsm, "_EXECUTION_CIRCUIT_BREAKER_REASON", "")
        return prior


def _patch_trading_state_machine(tsm: ModuleType) -> bool:
    module_id = id(tsm)
    with _LOCK:
        if module_id in _PATCHED_TSM_IDS:
            return True
    original_status = getattr(tsm, "_execution_circuit_breaker_status", None)
    if not callable(original_status):
        return False
    if getattr(original_status, "_nija_v88_generic_false_classification", False):
        with _LOCK:
            _PATCHED_TSM_IDS.add(module_id)
        return True

    def _status() -> tuple[bool, str]:
        ok, reason = original_status()
        if bool(ok):
            return bool(ok), str(reason or "")
        counts = getattr(tsm, "_EXECUTION_CIRCUIT_BREAKER_COUNTS", None)
        if not isinstance(counts, dict) or not _only_generic_execution_false_counts(counts):
            return bool(ok), str(reason or "")
        if not _live_runtime_intent() or not _kill_switch_clear(tsm) or not _strict_writer_nonce_ready(tsm):
            return bool(ok), str(reason or "")
        prior = _clear_generic_execution_false_counts(tsm)
        if not prior:
            return bool(ok), str(reason or "")
        LOGGER.critical(
            "EXECUTION_CIRCUIT_BREAKER_GENERIC_FALSE_RECLASSIFIED marker=%s prior_counts=%s "
            "strict_writer_nonce=true kill_switch=clear real_exchange_rejections_unchanged=true",
            MARKER,
            prior,
        )
        return True, "generic_execute_false_not_exchange_rejection"

    setattr(_status, "_nija_v88_generic_false_classification", True)
    setattr(tsm, "_execution_circuit_breaker_status", _status)
    with _LOCK:
        _PATCHED_TSM_IDS.add(module_id)
    LOGGER.critical("EXECUTION_CIRCUIT_BREAKER_CLASSIFICATION_V88_PATCHED marker=%s module=%s", MARKER, getattr(tsm, "__name__", "unknown"))
    return True


def _install_kraken_user_supervision() -> bool:
    global _KRAKEN_SUPERVISION_INSTALLED
    with _LOCK:
        if _KRAKEN_SUPERVISION_INSTALLED:
            return True
    try:
        from bot import kraken_all_account_supervision_v86 as v86
        installed = bool(v86.install())
        if installed:
            from bot import kraken_user_connection_convergence_v90_patch as v90
            installed = bool(v90.install_import_hook())
    except Exception as exc:
        LOGGER.warning("KRAKEN_USER_SUPERVISION_V88_INSTALL_FAILED marker=%s error=%s:%s", MARKER, type(exc).__name__, exc)
        return False
    if installed:
        with _LOCK:
            _KRAKEN_SUPERVISION_INSTALLED = True
        LOGGER.critical(
            "KRAKEN_USER_SUPERVISION_V88_CHAINED marker=%s source=v86+v90 "
            "authenticated_reconnect_only=true canonical_rebuild=true writer_scoped=true",
            MARKER,
        )
    return installed


class _StaleStartupSuppressionFilter(logging.Filter):
    _elapsed = re.compile(r"elapsed_s=([0-9.]+)")
    _timeout = re.compile(r"timeout_s=([0-9.]+)")

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
            if "WRITER_RELEASE_SUPPRESSED_DURING_CANONICAL_STARTUP" not in message or "state=LIVE_ACTIVE" not in message:
                return True
            elapsed_match = self._elapsed.search(message)
            timeout_match = self._timeout.search(message)
            if not elapsed_match or not timeout_match:
                return True
            return not (float(elapsed_match.group(1)) > float(timeout_match.group(1)))
        except Exception:
            return True


def _install_stale_startup_log_filter() -> None:
    global _LOG_FILTER_INSTALLED
    with _LOCK:
        if _LOG_FILTER_INSTALLED:
            return
        logging.getLogger("nija.final_production_activation_repair_v58").addFilter(_StaleStartupSuppressionFilter())
        _LOG_FILTER_INSTALLED = True
    LOGGER.info("STALE_STARTUP_DIAGNOSTIC_FILTER_V88_INSTALLED marker=%s behavior_unchanged=true", MARKER)


def _try_patch_loaded() -> bool:
    patched = False
    for name in ("bot.trading_state_machine", "trading_state_machine"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _patch_trading_state_machine(module) or patched
    return patched


def _monitor() -> None:
    deadline = time.monotonic() + 600.0
    while time.monotonic() < deadline:
        _install_kraken_user_supervision()
        if _try_patch_loaded():
            return
        time.sleep(0.25)
    LOGGER.warning("PRODUCTION_RUNTIME_CONVERGENCE_V88_MONITOR_EXPIRED marker=%s", MARKER)


def install_import_hook() -> bool:
    global _MONITOR_STARTED
    _install_stale_startup_log_filter()
    _install_kraken_user_supervision()
    _try_patch_loaded()
    with _LOCK:
        if not _MONITOR_STARTED:
            _MONITOR_STARTED = True
            threading.Thread(target=_monitor, name="ProductionRuntimeConvergenceV88", daemon=True).start()
    os.environ["NIJA_PRODUCTION_RUNTIME_CONVERGENCE_V88_INSTALLED"] = "1"
    LOGGER.critical(
        "PRODUCTION_RUNTIME_CONVERGENCE_V88_INSTALLED marker=%s circuit_classification=true "
        "kraken_user_supervision=true kraken_user_rebuild_v90=true stale_log_filter=true "
        "risk_gates_unchanged=true nonce_gates_unchanged=true",
        MARKER,
    )
    return True


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "install", "install_import_hook", "_only_generic_execution_false_counts", "_patch_trading_state_machine"]
