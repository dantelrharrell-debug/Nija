"""Registered-platform capital completeness guard v270.

Production on 2026-08-29 showed three platform brokers registered while Kraken
was disconnected, but the capital stack could still report the most recent
publication as accepted and MultiAccountBrokerManager.refresh_capital_authority()
contains a fallback that treats positive non-Kraken capital as ready when Kraken
is disconnected.  That can let current connectivity shrink the effective
completeness denominator below the registered platform topology.

v270 preserves the configured platform topology as the capital denominator.  It
never fabricates connectivity, balances, freshness, publication status, nonce,
execution authority, order/fill proof, or activation.  It only raises the
CapitalAuthority expected-broker floor to the registered platform count, refuses
a READY refresh result while any registered platform broker is disconnected or
while the current result has fewer contributing brokers, and prevents startup
lock release under the same incomplete condition.  Protective exits are not
changed.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from functools import wraps
from typing import Any, Mapping

LOGGER = logging.getLogger("nija.runtime_registered_platform_capital_completeness_v270")
MARKER = "20260828-registered-platform-capital-completeness-v270"
RELEASE_ID = "20260828-runtime-convergence-v270"
_READY_FLAG = "NIJA_RUNTIME_REGISTERED_PLATFORM_CAPITAL_COMPLETENESS_V270_READY"
_REFRESH_PATCH_ATTR = "_nija_registered_platform_capital_completeness_v270_refresh"
_FINALIZE_PATCH_ATTR = "_nija_registered_platform_capital_completeness_v270_finalize"
_LOCK = threading.RLock()


def _platform_mapping(manager: Any) -> dict[Any, Any]:
    raw = getattr(manager, "platform_brokers", None)
    if callable(raw):
        try:
            raw = raw()
        except Exception:
            raw = None
    if not isinstance(raw, Mapping):
        raw = getattr(manager, "_platform_brokers", None)
    if not isinstance(raw, Mapping):
        return {}
    return {key: broker for key, broker in raw.items() if broker is not None}


def _platform_counts(manager: Any) -> tuple[int, int]:
    mapping = _platform_mapping(manager)
    registered = len(mapping)
    connected = 0
    for broker in mapping.values():
        try:
            if bool(getattr(broker, "connected", False)):
                connected += 1
        except Exception:
            pass
    return registered, connected


def _authority() -> Any:
    try:
        module = importlib.import_module("bot.capital_authority")
        getter = getattr(module, "get_capital_authority", None)
        return getter() if callable(getter) else None
    except Exception:
        return None


def _raise_expected_floor(manager: Any) -> tuple[int, int, int]:
    registered, connected = _platform_counts(manager)
    authority = _authority()
    expected_before = 0
    if authority is not None:
        try:
            expected_before = int(getattr(authority, "expected_brokers", 0) or 0)
        except Exception:
            expected_before = 0
        if registered > expected_before:
            setter = getattr(authority, "set_expected_brokers", None)
            if callable(setter):
                setter(registered)
    return registered, connected, max(expected_before, registered)


def _result_valid_brokers(result: Any) -> int:
    if not isinstance(result, Mapping):
        return 0
    try:
        return max(0, int(float(result.get("valid_brokers", 0) or 0)))
    except (TypeError, ValueError):
        return 0


def _current_publication_accepted_and_fresh(authority: Any) -> bool:
    if authority is None:
        return False
    status_getter = getattr(authority, "get_snapshot_publication_status", None)
    if callable(status_getter):
        try:
            status = status_getter()
            if not bool(getattr(status, "accepted", False)):
                return False
            if bool(getattr(status, "stale", False)):
                return False
        except Exception:
            return False
    stale = getattr(authority, "is_stale", None)
    if callable(stale):
        try:
            if bool(stale()):
                return False
        except Exception:
            return False
    complete = getattr(authority, "is_brokers_complete", None)
    if callable(complete):
        try:
            if not bool(complete()):
                return False
        except Exception:
            return False
    return True


def _fail_closed_result(manager: Any, result: Any, *, registered: int, connected: int) -> Any:
    valid = _result_valid_brokers(result)
    if not isinstance(result, Mapping):
        return result
    if registered <= 0:
        return result
    if connected >= registered and valid >= registered:
        return result

    state_lock = getattr(manager, "_capital_state_lock", None) or _LOCK
    try:
        with state_lock:
            setattr(manager, "_capital_ready", False)
            setattr(manager, "_trading_halted_due_to_capital", True)
    except Exception:
        setattr(manager, "_capital_ready", False)
        setattr(manager, "_trading_halted_due_to_capital", True)

    corrected = dict(result)
    corrected["ready"] = 0.0
    corrected["pending"] = 1.0
    corrected["registered_platform_brokers"] = float(registered)
    corrected["connected_platform_brokers"] = float(connected)
    corrected["registered_platform_complete"] = 0.0
    LOGGER.critical(
        "REGISTERED_PLATFORM_CAPITAL_V270_FAIL_CLOSED marker=%s "
        "registered=%d connected=%d valid_brokers=%d original_ready=%s "
        "capital_mutated=false freshness_extended=false publication_expiry_extended=false "
        "execution_authority_unchanged=true forced_trade=false forced_activation=false "
        "safety_gates_bypassed=false",
        MARKER,
        registered,
        connected,
        valid,
        result.get("ready"),
    )
    return corrected


def _patch_refresh() -> bool:
    try:
        module = importlib.import_module("bot.multi_account_broker_manager")
        cls = getattr(module, "MultiAccountBrokerManager", None)
    except Exception:
        return False
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "refresh_capital_authority", None)
    if not callable(current):
        return False
    if bool(getattr(current, _REFRESH_PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def refresh_v270(self: Any, *args: Any, **kwargs: Any) -> Any:
        registered, connected, expected = _raise_expected_floor(self)
        result = original(self, *args, **kwargs)
        corrected = _fail_closed_result(
            self,
            result,
            registered=registered,
            connected=connected,
        )
        if isinstance(corrected, Mapping) and float(corrected.get("ready", 0.0) or 0.0) > 0.0:
            LOGGER.info(
                "REGISTERED_PLATFORM_CAPITAL_V270_COMPLETE marker=%s registered=%d "
                "connected=%d valid_brokers=%d expected_floor=%d",
                MARKER,
                registered,
                connected,
                _result_valid_brokers(corrected),
                expected,
            )
        return corrected

    setattr(refresh_v270, _REFRESH_PATCH_ATTR, True)
    setattr(refresh_v270, "__wrapped__", original)
    cls.refresh_capital_authority = refresh_v270
    return True


def _patch_finalize() -> bool:
    try:
        module = importlib.import_module("bot.multi_account_broker_manager")
        cls = getattr(module, "MultiAccountBrokerManager", None)
    except Exception:
        return False
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "finalize_bootstrap_ready", None)
    if not callable(current):
        return False
    if bool(getattr(current, _FINALIZE_PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def finalize_v270(self: Any, *args: Any, **kwargs: Any) -> Any:
        registered, connected, expected = _raise_expected_floor(self)
        authority = _authority()
        complete = bool(
            registered > 0
            and connected >= registered
            and _current_publication_accepted_and_fresh(authority)
        )
        if not complete:
            LOGGER.critical(
                "REGISTERED_PLATFORM_CAPITAL_V270_STARTUP_LOCK_HELD marker=%s "
                "registered=%d connected=%d expected_floor=%d publication_current=false "
                "startup_lock_released=false trading_fail_closed=true "
                "execution_authority_unchanged=true forced_activation=false "
                "safety_gates_bypassed=false",
                MARKER,
                registered,
                connected,
                expected,
            )
            return False
        return original(self, *args, **kwargs)

    setattr(finalize_v270, _FINALIZE_PATCH_ATTR, True)
    setattr(finalize_v270, "__wrapped__", original)
    cls.finalize_bootstrap_ready = finalize_v270
    return True


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        installers = getattr(manifest, "_INSTALLERS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_registered_platform_capital_completeness_v270"] = _READY_FLAG
        own = (
            "bot.runtime_registered_platform_capital_completeness_v270_patch",
            "install_import_hook",
        )
        if isinstance(installers, tuple) and own not in installers:
            manifest._INSTALLERS = tuple(installers) + (own,)
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        refresh_ok = _patch_refresh()
        finalize_ok = _patch_finalize()
        manifest_ok = _patch_release_manifest()
        try:
            module = importlib.import_module("bot.multi_account_broker_manager")
            getter = getattr(module, "get_broker_manager", None)
            manager = getter() if callable(getter) else None
        except Exception:
            manager = None
        registered = connected = expected = 0
        if manager is not None:
            registered, connected, expected = _raise_expected_floor(manager)
            if registered > 0 and connected < registered:
                try:
                    lock = getattr(manager, "_capital_state_lock", None) or _LOCK
                    with lock:
                        setattr(manager, "_capital_ready", False)
                        setattr(manager, "_trading_halted_due_to_capital", True)
                except Exception:
                    pass
        ready = bool(refresh_ok and finalize_ok and manifest_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "RUNTIME_REGISTERED_PLATFORM_CAPITAL_COMPLETENESS_V270_FAILED marker=%s "
                "refresh_patch=%s finalize_patch=%s manifest=%s trading_fail_closed=true",
                MARKER,
                str(refresh_ok).lower(),
                str(finalize_ok).lower(),
                str(manifest_ok).lower(),
            )
            return False
        LOGGER.critical(
            "RUNTIME_REGISTERED_PLATFORM_CAPITAL_COMPLETENESS_V270 marker=%s ready=true "
            "registered=%d connected=%d expected_floor=%d registered_denominator_preserved=true "
            "startup_lock_incomplete_blocked=true stale_snapshot_not_promoted=true "
            "user_brokers_excluded=true capital_thresholds_not_lowered=true "
            "freshness_extended=false publication_expiry_extended=false "
            "execution_authority_unchanged=true forced_trade=false forced_activation=false "
            "safety_gates_bypassed=false",
            MARKER,
            registered,
            connected,
            expected,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_platform_mapping",
    "_platform_counts",
    "_raise_expected_floor",
    "_result_valid_brokers",
    "_current_publication_accepted_and_fresh",
    "_fail_closed_result",
    "_patch_refresh",
    "_patch_finalize",
    "_patch_release_manifest",
]
