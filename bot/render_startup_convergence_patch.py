"""Fail-closed Render startup authority and capital convergence repair.

This module repairs two startup-state problems without granting trading authority:

* Runtime authority is derived state, not an operator setting.  A stale Render
  environment value such as ``NIJA_RUNTIME_EXECUTION_AUTHORITY=true`` is reset
  to ``0`` until the current process owns a writer fencing token and lease
  generation.
* After writer lineage exists, a bounded monitor converges the canonical
  MultiAccountBrokerManager through its locked prebootstrap when startup import
  churn has delayed initialization, then re-runs its normal capital watchdog
  refresh. It never creates a second manager and never bypasses capital,
  heartbeat, writer-lock, kill-switch, broker, or state-machine gates.

The platform contract treats Kraken as the required primary broker and Coinbase
as an optional isolated broker, so runtime convergence defaults to one valid
broker.  Operators may still configure a stricter value explicitly.
"""

from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from collections.abc import Mapping
from typing import Any, Optional, Tuple

logger = logging.getLogger("nija.render_startup_convergence")

_MARKER = "20260710r"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_FALSE = {"0", "false", "no", "off", "disabled", "n", ""}
_STARTED = False
_START_LOCK = threading.Lock()


def _truthy_value(value: Any) -> bool:
    return str(value or "").strip().lower() in _TRUE


def _truthy_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return _truthy_value(raw)


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)) or default)
    except (TypeError, ValueError):
        return default


def _int_env(name: str, default: int) -> int:
    try:
        return int(float(os.environ.get(name, str(default)) or default))
    except (TypeError, ValueError):
        return default


def _live_mode() -> bool:
    return (
        _truthy_env("LIVE_CAPITAL_VERIFIED")
        and not _truthy_env("DRY_RUN_MODE")
        and not _truthy_env("PAPER_MODE")
    )


def _writer_lineage() -> Tuple[bool, str]:
    token = str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "")).strip()
    generation = str(os.environ.get("NIJA_WRITER_LEASE_GENERATION", "")).strip()
    lease = _truthy_env("NIJA_WRITER_LEASE_ACQUIRED") or bool(token)
    if not token:
        return False, "fencing_token_missing"
    if not generation:
        return False, "lease_generation_missing"
    if not lease:
        return False, "lease_not_acquired"
    return True, f"lineage_ready generation={generation}"


def normalize_derived_runtime_state() -> dict[str, str]:
    """Canonicalize derived authority flags without granting authority.

    When writer lineage is absent, stale deployment-environment authority is
    reset to the fail-closed state.  When lineage already exists, recognized
    boolean spellings are only canonicalized to ``1``/``0``.
    """

    os.environ.setdefault("NIJA_RUNTIME_AUTHORITY_CONVERGENCE_MIN_BROKERS", "1")

    lineage_ready, _ = _writer_lineage()
    raw_auth = str(os.environ.get("NIJA_RUNTIME_EXECUTION_AUTHORITY", "")).strip().lower()
    raw_state = str(os.environ.get("NIJA_RUNTIME_TRADING_STATE", "")).strip().upper()
    changes: dict[str, str] = {}

    if not lineage_ready:
        if raw_auth != "0":
            changes["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = f"{raw_auth or 'missing'}->0"
        os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"

        if raw_state != "OFF":
            changes["NIJA_RUNTIME_TRADING_STATE"] = f"{raw_state or 'missing'}->OFF"
        os.environ["NIJA_RUNTIME_TRADING_STATE"] = "OFF"

        # Guard: never clear NIJA_WRITER_LEASE_ACQUIRED if the canonical
        # EntrypointWriterAuthority singleton actively holds the Redis lock.
        # The singleton is the sole authority over that flag; clearing it here
        # when lineage appears stale (e.g. a transient gap between lock
        # acquisition and fencing-token publication) breaks the heartbeat and
        # causes an unnecessary re-election.  Only reset the flag when the
        # singleton itself does not hold authority.
        _singleton_acquired = False
        try:
            _ewa_mod = (
                sys.modules.get("bot.entrypoint_writer_authority")
                or sys.modules.get("entrypoint_writer_authority")
            )
            if _ewa_mod is not None:
                _get_singleton = getattr(_ewa_mod, "get_entrypoint_writer_authority", None)
                if callable(_get_singleton):
                    _singleton = _get_singleton()
                    _singleton_acquired = bool(
                        _singleton is not None
                        and getattr(_singleton, "acquired", False)
                    )
        except Exception:
            pass

        if not _singleton_acquired:
            if str(os.environ.get("NIJA_WRITER_LEASE_ACQUIRED", "")).strip() != "0":
                changes["NIJA_WRITER_LEASE_ACQUIRED"] = "reset->0"
            os.environ["NIJA_WRITER_LEASE_ACQUIRED"] = "0"
        else:
            logger.debug(
                "RENDER_STARTUP_LEASE_RESET_SKIPPED marker=%s "
                "reason=singleton_holds_lock lineage_reason=%s",
                _MARKER,
                _,
            )
    else:
        if raw_auth in _TRUE:
            os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "1"
            if raw_auth != "1":
                changes["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = f"{raw_auth}->1"
        elif raw_auth in _FALSE:
            os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"
            if raw_auth != "0":
                changes["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = f"{raw_auth or 'missing'}->0"
        else:
            os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"
            changes["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = f"invalid:{raw_auth}->0"

        os.environ.setdefault("NIJA_RUNTIME_TRADING_STATE", "OFF")

    if changes:
        logger.warning(
            "RENDER_STARTUP_DERIVED_STATE_NORMALIZED marker=%s changes=%s",
            _MARKER,
            ",".join(f"{key}:{value}" for key, value in sorted(changes.items())),
        )
    return changes


def _manager_module() -> Optional[Any]:
    """Return an already-imported MABM module without taking bootstrap ownership."""

    return sys.modules.get("bot.multi_account_broker_manager") or sys.modules.get(
        "multi_account_broker_manager"
    )


def _result_summary(result: Any) -> str:
    if isinstance(result, Mapping):
        total = result.get("total_capital", result.get("real_capital", 0.0))
        valid = result.get("valid_brokers", result.get("broker_count", 0))
        ready = result.get("ready", False)
        return f"ready={bool(ready)} total={total} valid_brokers={valid}"
    return f"type={type(result).__name__}"


def _canonical_prebootstrap_manager() -> Tuple[Optional[Any], str]:
    """Run the existing locked canonical prebootstrap after writer verification."""

    module = None
    for name in (
        "nija_canonical_broker_prebootstrap_v22",
        "bot.canonical_broker_prebootstrap_v22",
    ):
        candidate = sys.modules.get(name)
        if candidate is not None:
            module = candidate
            break

    if module is None:
        for name in (
            "nija_canonical_broker_startup_convergence_v24_prebot",
            "nija_canonical_broker_startup_convergence_v24",
        ):
            startup_guard = sys.modules.get(name)
            loader = getattr(startup_guard, "_load_v22_module", None)
            if callable(loader):
                try:
                    module = loader()
                except Exception as exc:
                    logger.error(
                        "RENDER_STARTUP_CANONICAL_PREBOOTSTRAP_LOAD_FAILED "
                        "marker=%s err=%s:%s",
                        _MARKER,
                        type(exc).__name__,
                        exc,
                    )
                    return None, (
                        "canonical_prebootstrap_load_failed:"
                        f"{type(exc).__name__}"
                    )
                break

    if module is None:
        return None, "canonical_prebootstrap_module_not_loaded"

    prepare = getattr(module, "prepare_canonical_broker_runtime", None)
    if not callable(prepare):
        return None, "canonical_prebootstrap_prepare_missing"

    try:
        manager = prepare()
    except Exception as exc:
        logger.critical(
            "RENDER_STARTUP_CANONICAL_PREBOOTSTRAP_FAILED marker=%s err=%s:%s "
            "trading_remains_fail_closed=true",
            _MARKER,
            type(exc).__name__,
            exc,
            exc_info=True,
        )
        return None, f"canonical_prebootstrap_failed:{type(exc).__name__}"

    if not bool(getattr(manager, "_fsm_initialized", False)):
        return None, "canonical_prebootstrap_returned_uninitialized"

    logger.critical(
        "RENDER_STARTUP_CANONICAL_PREBOOTSTRAP_READY marker=%s generation=%s",
        _MARKER,
        os.environ.get("NIJA_WRITER_LEASE_GENERATION", "unknown"),
    )
    return manager, "canonical_prebootstrap_ready"


def _attempt_recovery_once() -> Tuple[bool, str]:
    """Run one safe convergence attempt.

    Returns ``(done, reason)``.  ``done`` means the monitor can stop because the
    service is not in live mode or runtime authority has converged.
    """

    normalize_derived_runtime_state()

    if not _live_mode():
        return True, "not_live_mode"

    state = str(os.environ.get("NIJA_RUNTIME_TRADING_STATE", "")).strip().upper()
    if state == "LIVE_ACTIVE" and _truthy_env("NIJA_RUNTIME_EXECUTION_AUTHORITY"):
        return True, "already_live_active"

    lineage_ready, lineage_reason = _writer_lineage()
    if not lineage_ready:
        return False, lineage_reason

    module = _manager_module()
    if module is None:
        return False, "broker_manager_module_not_loaded"

    getter = getattr(module, "get_broker_manager", None)
    if not callable(getter):
        return False, "broker_manager_getter_missing"

    try:
        manager = getter()
    except Exception as exc:
        return False, f"broker_manager_unavailable:{type(exc).__name__}"

    if not bool(getattr(manager, "_fsm_initialized", False)):
        manager, prebootstrap_reason = _canonical_prebootstrap_manager()
        if manager is None:
            return False, prebootstrap_reason

    has_sources = getattr(manager, "has_registered_sources", None)
    if not callable(has_sources) or not bool(has_sources()):
        return False, "no_registered_platform_source"

    attempted = getattr(manager, "has_attempted_connections", None)
    if not callable(attempted) or not bool(attempted()):
        return False, "broker_registration_not_finalized"

    watchdog_start = getattr(manager, "_start_capital_watchdog", None)
    if callable(watchdog_start):
        watchdog_start()

    refresh = getattr(manager, "refresh_capital_authority", None)
    if not callable(refresh):
        return False, "capital_refresh_unavailable"

    try:
        trigger = str(getattr(manager, "WATCHDOG_REFRESH_TRIGGER", "watchdog") or "watchdog")
        result = refresh(trigger=trigger)
    except Exception as exc:
        logger.warning(
            "RENDER_STARTUP_CAPITAL_REFRESH_FAILED marker=%s err=%s",
            _MARKER,
            exc,
        )
        return False, f"capital_refresh_failed:{type(exc).__name__}"

    converged = False
    try:
        convergence = importlib.import_module("bot.runtime_authority_convergence_repair_patch")
        converge = getattr(convergence, "converge_runtime_authority", None)
        if callable(converge):
            converged = bool(converge("render_post_lock_recovery"))
    except Exception as exc:
        logger.warning(
            "RENDER_STARTUP_CONVERGENCE_CALL_FAILED marker=%s err=%s",
            _MARKER,
            exc,
        )

    state = str(os.environ.get("NIJA_RUNTIME_TRADING_STATE", "")).strip().upper()
    authority = _truthy_env("NIJA_RUNTIME_EXECUTION_AUTHORITY")
    logger.warning(
        "RENDER_STARTUP_CAPITAL_REFRESH marker=%s result=%s converged=%s state=%s authority=%s",
        _MARKER,
        _result_summary(result),
        converged,
        state or "missing",
        authority,
    )
    if state == "LIVE_ACTIVE" and authority:
        return True, "converged_live_active"
    return False, "capital_refreshed_waiting_for_remaining_gates"


def _monitor() -> None:
    interval = max(1.0, _float_env("NIJA_RENDER_STARTUP_RECOVERY_INTERVAL_S", 5.0))
    max_attempts = max(1, _int_env("NIJA_RENDER_STARTUP_RECOVERY_MAX_ATTEMPTS", 60))
    initial_delay = max(0.0, _float_env("NIJA_RENDER_STARTUP_RECOVERY_INITIAL_DELAY_S", 2.0))
    log_every = max(1, _int_env("NIJA_RENDER_STARTUP_RECOVERY_LOG_EVERY", 3))
    maintenance_interval = max(
        10.0, _float_env("NIJA_RENDER_STARTUP_MAINTENANCE_INTERVAL_S", 30.0)
    )

    if initial_delay:
        time.sleep(initial_delay)

    last_reason = ""
    for attempt in range(1, max_attempts + 1):
        try:
            done, reason = _attempt_recovery_once()
        except Exception as exc:  # pragma: no cover - final defensive boundary
            done = False
            reason = f"unexpected:{type(exc).__name__}"
            logger.exception(
                "RENDER_STARTUP_RECOVERY_ERROR marker=%s attempt=%d/%d",
                _MARKER,
                attempt,
                max_attempts,
            )

        if done:
            logger.warning(
                "RENDER_STARTUP_RECOVERY_COMPLETE marker=%s attempt=%d/%d reason=%s",
                _MARKER,
                attempt,
                max_attempts,
                reason,
            )
            break

        if reason != last_reason or attempt == 1 or attempt % log_every == 0:
            logger.warning(
                "RENDER_STARTUP_RECOVERY_WAITING marker=%s attempt=%d/%d reason=%s",
                _MARKER,
                attempt,
                max_attempts,
                reason,
            )
            last_reason = reason

        time.sleep(interval)
    else:
        logger.error(
            "RENDER_STARTUP_RECOVERY_EXHAUSTED marker=%s attempts=%d last_reason=%s "
            "trading_remains_fail_closed=true",
            _MARKER,
            max_attempts,
            last_reason or "unknown",
        )
        return

    # ── Maintenance loop ──────────────────────────────────────────────────────
    # After initial convergence, keep running at a slower cadence.  If the
    # capital snapshot becomes stale (e.g. Kraken reconnects, balance changes),
    # _attempt_recovery_once() will trigger a refresh and re-publish authority.
    maintenance_attempt = 0
    while True:
        time.sleep(maintenance_interval)
        maintenance_attempt += 1
        try:
            _done, _reason = _attempt_recovery_once()
        except Exception as _exc:  # pragma: no cover
            logger.warning(
                "RENDER_STARTUP_MAINTENANCE_ERROR marker=%s attempt=%d err=%s",
                _MARKER,
                maintenance_attempt,
                _exc,
            )
            continue
        if not _done:
            logger.warning(
                "RENDER_STARTUP_MAINTENANCE_RECOVERY marker=%s attempt=%d reason=%s",
                _MARKER,
                maintenance_attempt,
                _reason,
            )


def install_import_hook() -> None:
    """Install normalization and the bounded recovery monitor exactly once."""

    global _STARTED
    with _START_LOCK:
        if _STARTED:
            return
        _STARTED = True

    normalize_derived_runtime_state()
    if not _truthy_env("NIJA_RENDER_STARTUP_RECOVERY_ENABLED", True):
        logger.warning("RENDER_STARTUP_RECOVERY_DISABLED marker=%s", _MARKER)
        return

    thread = threading.Thread(
        target=_monitor,
        name="render-startup-convergence",
        daemon=True,
    )
    thread.start()
    logger.warning(
        "RENDER_STARTUP_RECOVERY_INSTALLED marker=%s thread_alive=%s min_brokers=%s",
        _MARKER,
        thread.is_alive(),
        os.environ.get("NIJA_RUNTIME_AUTHORITY_CONVERGENCE_MIN_BROKERS", "1"),
    )


__all__ = [
    "install_import_hook",
    "normalize_derived_runtime_state",
    "_attempt_recovery_once",
    "_canonical_prebootstrap_manager",
]
