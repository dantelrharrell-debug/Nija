from __future__ import annotations

import builtins
import logging
import sys
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.broker_health_exit_continuity")
_MARKER = "20260716-broker-health-exit-v1"
_PATCHED = "_nija_broker_health_exit_continuity_v1"
_ORIGINAL_IMPORT: Optional[Callable[..., Any]] = None
_TARGETS = {
    "bot.broker_failure_manager",
    "broker_failure_manager",
    "bot.independent_broker_trader",
    "independent_broker_trader",
}

_TERMINAL_TOKENS = (
    "authentication",
    "auth failed",
    "invalid api key",
    "invalid key",
    "permission denied",
    "insufficient permission",
    "account suspended",
    "account disabled",
    "signature invalid",
    "eapi:invalid key",
)

_TRANSIENT_TOKENS = (
    "timeout",
    "temporarily unavailable",
    "rate limit",
    "too many requests",
    "network",
    "connection reset",
    "connection aborted",
    "ohlc",
    "market data",
    "data timeout",
    "volume",
    "product",
    "symbol",
    "balance_check_failed",
    "platform not connected",
    "nonce",
)


def _text(value: Any) -> str:
    return str(value or "").strip().lower()


def _is_terminal(reason: Any) -> bool:
    text = _text(reason)
    if not text:
        return False
    return any(token in text for token in _TERMINAL_TOKENS)


def _is_transient(reason: Any) -> bool:
    text = _text(reason)
    return any(token in text for token in _TRANSIENT_TOKENS)


def _patch_failure_manager(module: ModuleType) -> bool:
    cls = getattr(module, "BrokerFailureManager", None)
    if cls is None or getattr(cls, _PATCHED, False):
        return False

    original_record_error = getattr(cls, "record_error", None)
    original_record_success = getattr(cls, "record_success", None)
    original_is_dead = getattr(cls, "is_dead", None)
    if not all(callable(fn) for fn in (original_record_error, original_record_success, original_is_dead)):
        return False

    def record_error(self, broker_name: str, reason: str = "", *args, **kwargs):
        # Symbol, OHLC, timeout, nonce, connection-lag and balance-read failures
        # must degrade a broker, not globally disable entry and exit execution.
        if _is_transient(reason) and not _is_terminal(reason):
            try:
                state = self._get_or_create(broker_name)
                with self._lock:
                    state.total_errors += 1
                    state.last_error_reason = str(reason or "")[:200]
                    # Keep one warning worth of history without allowing a
                    # transient series to cross the global dead threshold.
                    state.consecutive_errors = min(state.consecutive_errors + 1, 1)
                    if state.is_dead:
                        state.is_dead = False
                        state.dead_since = None
                        state.retry_attempts = 0
                logger.warning(
                    "BROKER_TRANSIENT_FAILURE_DEGRADED marker=%s broker=%s reason=%s action=keep_live",
                    _MARKER,
                    broker_name,
                    str(reason or "")[:160],
                )
                return False
            except Exception:
                return original_record_error(self, broker_name, reason, *args, **kwargs)
        return original_record_error(self, broker_name, reason, *args, **kwargs)

    def record_success(self, broker_name: str, *args, **kwargs):
        revived = original_record_success(self, broker_name, *args, **kwargs)
        logger.info(
            "BROKER_PRIVATE_READ_SUCCESS marker=%s broker=%s revived=%s",
            _MARKER,
            broker_name,
            bool(revived),
        )
        return revived

    def is_dead(self, broker_name: str, *args, **kwargs):
        dead = bool(original_is_dead(self, broker_name, *args, **kwargs))
        if not dead:
            return False
        try:
            state = self._states.get(broker_name)
            reason = getattr(state, "last_error_reason", "") if state is not None else ""
            if not _is_terminal(reason):
                logger.critical(
                    "BROKER_NONTERMINAL_DEAD_STATE_BYPASSED marker=%s broker=%s reason=%s exits_preserved=true",
                    _MARKER,
                    broker_name,
                    str(reason or "")[:160],
                )
                return False
        except Exception:
            pass
        return True

    setattr(record_error, _PATCHED, True)
    setattr(record_success, _PATCHED, True)
    setattr(is_dead, _PATCHED, True)
    cls.record_error = record_error
    cls.record_success = record_success
    cls.is_dead = is_dead
    setattr(cls, _PATCHED, True)
    logger.critical("BROKER_FAILURE_CLASSIFICATION_PATCHED marker=%s", _MARKER)
    return True


def _patch_independent_trader(module: ModuleType) -> bool:
    cls = getattr(module, "IndependentBrokerTrader", None)
    if cls is None or getattr(cls, _PATCHED, False):
        return False

    original_get_balance = getattr(cls, "_get_broker_balance", None)
    if callable(original_get_balance) and not getattr(original_get_balance, _PATCHED, False):
        def _get_broker_balance(self, broker, broker_type, broker_name, *args, **kwargs):
            balance = original_get_balance(self, broker, broker_type, broker_name, *args, **kwargs)
            # A successful authenticated balance read is proof the venue is not
            # globally dead. Reset both aliases because this class currently
            # stores the singleton under two attributes.
            for attr in ("failure_manager", "broker_failure_manager"):
                manager = getattr(self, attr, None)
                if manager is not None:
                    try:
                        manager.record_success(broker_name)
                    except Exception:
                        pass
            return balance

        setattr(_get_broker_balance, _PATCHED, True)
        cls._get_broker_balance = _get_broker_balance

    setattr(cls, _PATCHED, True)
    logger.critical(
        "INDEPENDENT_TRADER_PRIVATE_READ_REVIVAL_PATCHED marker=%s exits_preserved=true",
        _MARKER,
    )
    return True


def _try_patch_loaded() -> None:
    for name in tuple(_TARGETS):
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            continue
        if name.endswith("broker_failure_manager"):
            _patch_failure_manager(module)
        elif name.endswith("independent_broker_trader"):
            _patch_independent_trader(module)


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT
    _try_patch_loaded()
    if getattr(builtins, "_NIJA_BROKER_HEALTH_EXIT_CONTINUITY_HOOK", False):
        return
    _ORIGINAL_IMPORT = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)  # type: ignore[misc]
        try:
            if name in _TARGETS or name.endswith(("broker_failure_manager", "independent_broker_trader")):
                _try_patch_loaded()
        except Exception as exc:
            logger.warning(
                "BROKER_HEALTH_EXIT_CONTINUITY_IMPORT_PATCH_FAILED marker=%s name=%s error=%s",
                _MARKER,
                name,
                exc,
            )
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_BROKER_HEALTH_EXIT_CONTINUITY_HOOK", True)
    logger.critical("BROKER_HEALTH_EXIT_CONTINUITY_INSTALLED marker=%s", _MARKER)


def install() -> None:
    install_import_hook()
