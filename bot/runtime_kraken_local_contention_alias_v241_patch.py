"""Protect every live KrakenBroker alias from local read-lock health mutation (v241).

v237 patched ``bot.broker_manager.KrakenBroker`` but production still showed direct
``_balance_fetch_errors`` increments after KRAKEN_READ_LOCK_V212_BUSY.  That proves at
least one live class/method binding was outside the v237 class identity.

v241 discovers both canonical and legacy broker_manager module aliases, patches every
unique KrakenBroker class identity, and detects the local contention *per call* by
comparing v234's monotonic busy counter before/after the balance call.  This avoids the
v237 failure mode where a pre-existing STARVING flag could be ambiguous.

The current read remains fail-closed.  Only direct health mutations made during a call
that generated a new v234 local-lock busy observation are restored to their exact
pre-call values.  Genuine exchange/auth/nonce/HTTP/order failures are untouched.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.runtime_kraken_local_contention_alias_v241")
MARKER = "20260826-kraken-local-contention-alias-v241"
_FLAG = "NIJA_KRAKEN_LOCAL_CONTENTION_ALIAS_V241_READY"
_PATCH_ATTR = "_nija_kraken_local_contention_alias_v241"
_MODULES = ("bot.broker_manager", "broker_manager")


def _busy_count() -> int:
    try:
        return max(0, int(str(os.environ.get("NIJA_KRAKEN_READ_LOCK_V234_BUSY_COUNT", "0") or "0")))
    except Exception:
        return 0


def _snapshot(self: Any) -> dict[str, Any]:
    names = (
        "_balance_fetch_errors",
        "_is_available",
        "exit_only_mode",
        "kraken_health",
        "_consecutive_errors",
        "consecutive_errors",
    )
    return {name: getattr(self, name) for name in names if hasattr(self, name)}


def _restore(self: Any, before: dict[str, Any]) -> None:
    for name, value in before.items():
        try:
            setattr(self, name, value)
        except Exception:
            pass


def _patch_class(cls: type) -> bool:
    current = getattr(cls, "get_account_balance", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def get_account_balance_v241(self: Any, *args: Any, **kwargs: Any):
        before = _snapshot(self)
        busy_before = _busy_count()
        result = current(self, *args, **kwargs)
        busy_after = _busy_count()
        if busy_after > busy_before:
            mutated = {
                name: (before[name], getattr(self, name, None))
                for name in before
                if getattr(self, name, None) != before[name]
            }
            _restore(self, before)
            LOGGER.critical(
                "KRAKEN_LOCAL_CONTENTION_V241_HEALTH_RESTORED marker=%s account=%s "
                "busy_before=%d busy_after=%d mutated_fields=%s current_read_fail_closed=true "
                "exact_precall_health_restored=true balance_result_unchanged=true local_contention_not_exchange_failure=true "
                "genuine_exchange_auth_nonce_http_order_failures_unchanged=true execution_authority_unchanged=true "
                "forced_trade=false safety_gates_bypassed=false",
                MARKER,
                str(getattr(self, "account_identifier", getattr(self, "account_id", "unknown"))),
                busy_before,
                busy_after,
                ",".join(sorted(mutated)) or "none",
            )
        return result

    setattr(get_account_balance_v241, _PATCH_ATTR, True)
    setattr(get_account_balance_v241, "__wrapped__", current)
    cls.get_account_balance = get_account_balance_v241
    return True


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
            if module_name == "bot.broker_manager":
                canonical_manager_found = True
    patched = sum(1 for cls in classes.values() if _patch_class(cls))
    return bool(
        classes and canonical_manager_found and patched == len(classes)
    ), patched, tuple(sorted(set(modules)))


def install() -> bool:
    try:
        v237 = importlib.import_module("bot.runtime_kraken_local_contention_health_v237_patch")
        install_v237 = getattr(v237, "install", None)
        upstream = bool(callable(install_v237) and install_v237())
        aliases, patched_classes, modules = _patch_aliases()
        ready = bool(upstream and aliases)
    except Exception as exc:
        LOGGER.error(
            "KRAKEN_LOCAL_CONTENTION_V241_INSTALL_ERROR marker=%s error=%s:%s trading_fail_closed=true",
            MARKER, type(exc).__name__, exc,
        )
        ready, patched_classes, modules = False, 0, ()
    os.environ[_FLAG] = "1" if ready else "0"
    if ready:
        LOGGER.critical(
            "KRAKEN_LOCAL_CONTENTION_V241_READY marker=%s ready=true patched_classes=%d modules=%s "
            "v237_required=true per_call_v234_busy_delta=true current_read_fail_closed=true "
            "exact_precall_health_only=true genuine_exchange_errors_unchanged=true execution_authority_unchanged=true "
            "nonce_policy_unchanged=true forced_trade=false safety_gates_bypassed=false",
            MARKER, patched_classes, ",".join(modules),
        )
    return ready


def install_import_hook() -> bool:
    return install()


__all__ = ["MARKER", "install", "install_import_hook", "_patch_aliases"]
