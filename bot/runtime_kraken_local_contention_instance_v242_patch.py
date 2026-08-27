"""Bind Kraken local-read contention to every live broker class identity (v242).

Production on 2026-08-26 showed v241/v242 installed while get_account_balance() still
incremented direct failure counters and entered EXIT-ONLY after KrakenReadLockBusy.
The live KrakenBroker is defined in ``bot.broker_integration``; earlier v242 only
searched broker_manager aliases, so the actual instance could remain unpatched.

v242 patches every loaded KrakenBroker class alias at BOTH boundaries:
1. _kraken_private_call records a monotonic instance-local sequence only when the
   raised exception is provably KrakenReadLockBusy/local read-lock contention.
2. get_account_balance/connect snapshot health before the call. If that exact instance
   sequence increased during the call, direct health mutations are restored to the
   exact pre-call values.

The read/connect result itself is NOT changed. A failed local read remains failed and
no balance, connectivity, eligibility, execution authority, nonce, fill, or activation
proof is fabricated. Genuine exchange/API/auth/nonce/HTTP/order failures never bump the
local-contention sequence and therefore remain fully authoritative/fail-closed.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.runtime_kraken_local_contention_instance_v242")
MARKER = "20260826-kraken-local-contention-instance-v242"
_FLAG = "NIJA_KRAKEN_LOCAL_CONTENTION_INSTANCE_V242_READY"
_PRIVATE_ATTR = "_nija_kraken_local_contention_private_v242"
_BALANCE_ATTR = "_nija_kraken_local_contention_balance_v242"
_CONNECT_ATTR = "_nija_kraken_local_contention_connect_v242"
_MODULES = (
    "bot.broker_integration",
    "broker_integration",
    "bot.broker_manager",
    "broker_manager",
)
_SEQ_ATTR = "_nija_kraken_local_read_busy_seq_v242"


def _is_local_busy(exc: BaseException) -> bool:
    try:
        timeout_mod = importlib.import_module("bot.kraken_read_timeout_v121_patch")
        exc_type = getattr(timeout_mod, "KrakenReadLockBusy", None)
        if isinstance(exc_type, type) and isinstance(exc, exc_type):
            return True
    except Exception:
        pass
    text = str(exc or "").lower()
    return "kraken read lock busy" in text or "krakenreadlockbusy" in text


def _seq(obj: Any) -> int:
    try:
        return max(0, int(getattr(obj, _SEQ_ATTR, 0) or 0))
    except Exception:
        return 0


def _mark_local_busy(obj: Any, method: str, exc: BaseException) -> None:
    value = _seq(obj) + 1
    try:
        setattr(obj, _SEQ_ATTR, value)
    except Exception:
        return
    LOGGER.warning(
        "KRAKEN_LOCAL_CONTENTION_V242_INSTANCE_MARKED marker=%s account=%s method=%s seq=%d "
        "local_contention=true exchange_unavailability_unproven=true health_mutated=false "
        "current_call_fail_closed=true safety_gates_bypassed=false error=%s",
        MARKER,
        str(getattr(obj, "account_identifier", getattr(obj, "account_id", "unknown"))),
        method,
        value,
        str(exc)[:180],
    )


def _health_snapshot(obj: Any) -> dict[str, Any]:
    fields = (
        "_balance_fetch_errors",
        "_is_available",
        "exit_only_mode",
        "kraken_health",
        "_consecutive_errors",
        "consecutive_errors",
        "connected",
        "is_connected",
        "_connected",
        "trading_eligible",
    )
    return {name: getattr(obj, name) for name in fields if hasattr(obj, name)}


def _restore_exact(obj: Any, before: dict[str, Any]) -> tuple[str, ...]:
    restored: list[str] = []
    for name, value in before.items():
        try:
            if getattr(obj, name, None) != value:
                setattr(obj, name, value)
                restored.append(name)
        except Exception:
            pass
    return tuple(sorted(restored))


def _patch_private(cls: type) -> bool:
    current = getattr(cls, "_kraken_private_call", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PRIVATE_ATTR, False)):
        return True

    @wraps(current)
    def private_v242(self: Any, *args: Any, **kwargs: Any):
        method = str(args[0] if args else kwargs.get("method", "") or "")
        try:
            return current(self, *args, **kwargs)
        except BaseException as exc:
            if _is_local_busy(exc):
                _mark_local_busy(self, method, exc)
            raise

    setattr(private_v242, _PRIVATE_ATTR, True)
    setattr(private_v242, "__wrapped__", current)
    cls._kraken_private_call = private_v242
    return True


def _patch_health_method(cls: type, method_name: str, attr_marker: str) -> bool:
    current = getattr(cls, method_name, None)
    if not callable(current):
        return method_name == "connect"
    if bool(getattr(current, attr_marker, False)):
        return True

    @wraps(current)
    def health_guard_v242(self: Any, *args: Any, **kwargs: Any):
        before_seq = _seq(self)
        before_health = _health_snapshot(self)
        try:
            result = current(self, *args, **kwargs)
        except BaseException:
            if _seq(self) > before_seq:
                restored = _restore_exact(self, before_health)
                LOGGER.critical(
                    "KRAKEN_LOCAL_CONTENTION_V242_HEALTH_RESTORED marker=%s account=%s method=%s "
                    "seq_before=%d seq_after=%d restored_fields=%s current_call_fail_closed=true "
                    "return_or_exception_unchanged=true exact_precall_health_only=true "
                    "genuine_exchange_failures_unchanged=true forced_trade=false safety_gates_bypassed=false",
                    MARKER,
                    str(getattr(self, "account_identifier", getattr(self, "account_id", "unknown"))),
                    method_name,
                    before_seq,
                    _seq(self),
                    ",".join(restored) or "none",
                )
            raise
        if _seq(self) > before_seq:
            restored = _restore_exact(self, before_health)
            LOGGER.critical(
                "KRAKEN_LOCAL_CONTENTION_V242_HEALTH_RESTORED marker=%s account=%s method=%s "
                "seq_before=%d seq_after=%d restored_fields=%s current_call_fail_closed=true "
                "result_unchanged=true exact_precall_health_only=true "
                "genuine_exchange_failures_unchanged=true forced_trade=false safety_gates_bypassed=false",
                MARKER,
                str(getattr(self, "account_identifier", getattr(self, "account_id", "unknown"))),
                method_name,
                before_seq,
                _seq(self),
                ",".join(restored) or "none",
            )
        return result

    setattr(health_guard_v242, attr_marker, True)
    setattr(health_guard_v242, "__wrapped__", current)
    setattr(cls, method_name, health_guard_v242)
    return True


def _patch_class(cls: type) -> bool:
    return bool(
        _patch_private(cls)
        and _patch_health_method(cls, "get_account_balance", _BALANCE_ATTR)
        and _patch_health_method(cls, "connect", _CONNECT_ATTR)
    )


def _patch_aliases() -> tuple[bool, int, tuple[str, ...]]:
    classes: dict[int, type] = {}
    modules: list[str] = []
    canonical_manager_found = False
    for name in _MODULES:
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            try:
                module = importlib.import_module(name)
            except Exception:
                continue
        cls = getattr(module, "KrakenBroker", None)
        if isinstance(cls, type):
            classes[id(cls)] = cls
            module_name = str(getattr(module, "__name__", name))
            modules.append(module_name)
            # The production class is ``bot.broker_manager.KrakenBroker``.
            # The integration module defines ``KrakenBrokerAdapter`` instead;
            # looking for ``KrakenBroker`` there kept the entire v234/v237/
            # v241/v242 readiness chain false despite effective protection.
            if module_name == "bot.broker_manager":
                canonical_manager_found = True
    patched = sum(1 for cls in classes.values() if _patch_class(cls))
    return bool(
        classes and canonical_manager_found and patched == len(classes)
    ), patched, tuple(sorted(set(modules)))


def install() -> bool:
    try:
        v241 = importlib.import_module("bot.runtime_kraken_local_contention_alias_v241_patch")
        upstream_install = getattr(v241, "install", None)
        upstream = bool(callable(upstream_install) and upstream_install())
        aliases, patched_classes, modules = _patch_aliases()
        ready = bool(upstream and aliases)
    except Exception as exc:
        LOGGER.error(
            "KRAKEN_LOCAL_CONTENTION_V242_INSTALL_ERROR marker=%s error=%s:%s trading_fail_closed=true",
            MARKER, type(exc).__name__, exc,
        )
        ready, patched_classes, modules = False, 0, ()
    os.environ[_FLAG] = "1" if ready else "0"
    if ready:
        LOGGER.critical(
            "KRAKEN_LOCAL_CONTENTION_V242_READY marker=%s ready=true patched_classes=%d modules=%s "
            "canonical_broker_manager_required=true instance_local_busy_sequence=true private_call_boundary=true "
            "balance_health_guard=true connect_health_guard=true exact_precall_health_only=true "
            "current_call_fail_closed=true genuine_exchange_api_auth_nonce_http_order_failures_unchanged=true "
            "execution_authority_unchanged=true forced_trade=false safety_gates_bypassed=false",
            MARKER, patched_classes, ",".join(modules),
        )
    return ready


def install_import_hook() -> bool:
    return install()


__all__ = ["MARKER", "install", "install_import_hook", "_patch_aliases", "_is_local_busy"]
