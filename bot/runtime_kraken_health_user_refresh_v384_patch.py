"""Kraken exact-health and registered-user refresh convergence v384.

Production after the v383 restart exposed two wrapper-order defects:

1. v367 software margin protection can be re-wrapped after v368.  The new outer
   v367 coverage wrapper then evaluates hard-exit authority before v368 has put
   the exact broker into scope, so a stale global dispatch-health bit can
   temporarily demote a genuinely healthy Kraken software monitor.
2. v366 can stop unwrapping too early when a registered-user proxy exposes a
   delegated ``_kraken_api_call`` method.  OpenPositions is then attempted on the
   proxy instead of the concrete Kraken adapter and the account is reported as
   disconnected/unproven even though credential/balance handoff succeeded.

v384 fixes only those object-boundary problems.  It never promotes global broker
health, never treats authenticated reads as execution health, never fabricates
positions or fills, and never relaxes writer/nonce/risk/kill-switch/order/fill
checks.  Native v380 orders remain reduce-only and require OpenOrders proof.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from contextvars import ContextVar
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_kraken_health_user_refresh_v384")
MARKER = "20260906-kraken-health-user-refresh-v384"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_HEALTH_USER_REFRESH_V384_READY"
_PATCH_ATTR = "_nija_kraken_health_user_refresh_v384"
_PROXY_ATTRS = ("_broker", "_real_broker", "_target", "broker")
_PROXY_MAX_DEPTH = 6
_LOCK = threading.RLock()
_BROKER_SCOPE: ContextVar[Any] = ContextVar("nija_v384_exact_kraken_broker", default=None)


def _v366():
    return importlib.import_module("bot.runtime_kraken_margin_canonical_coverage_v366_patch")


def _v367():
    return importlib.import_module("bot.runtime_kraken_margin_protection_truth_v367_patch")


def _proxy_candidate(value: Any) -> bool:
    if value is None:
        return False
    if callable(getattr(value, "_kraken_api_call", None)) or callable(getattr(value, "_kraken_private_call", None)):
        return True
    if "kraken" in type(value).__name__.lower():
        return True
    for attr in _PROXY_ATTRS:
        try:
            nested = getattr(value, attr, None)
        except Exception:
            nested = None
        if nested is not None and nested is not value:
            return True
    return False


def _deepest_known_proxy(broker: Any) -> Any:
    """Resolve known NIJA broker wrappers before trusting delegated methods.

    A wrapper-level ``_kraken_api_call`` is not itself proof that the wrapper is
    the authoritative adapter.  Known proxy links are followed first.  Cycles or
    excessive depth fail closed by returning ``None``.
    """
    current = broker
    seen: set[int] = set()
    for _depth in range(_PROXY_MAX_DEPTH):
        if current is None:
            return None
        ident = id(current)
        if ident in seen:
            return None
        seen.add(ident)

        nxt = None
        for attr in _PROXY_ATTRS:
            try:
                candidate = getattr(current, attr, None)
            except Exception:
                candidate = None
            if candidate is current or id(candidate) in seen if candidate is not None else False:
                continue
            if _proxy_candidate(candidate):
                nxt = candidate
                break
        if nxt is None:
            return current
        current = nxt

    for attr in _PROXY_ATTRS:
        try:
            candidate = getattr(current, attr, None)
        except Exception:
            candidate = None
        if candidate is not None and candidate is not current and _proxy_candidate(candidate):
            return None
    return current


def _patch_v366_unwrap() -> bool:
    v366 = _v366()
    current = getattr(v366, "_unwrap", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def unwrap_v384(broker: Any):
        target = _deepest_known_proxy(broker)
        if target is None:
            return None
        return target

    setattr(unwrap_v384, _PATCH_ATTR, True)
    setattr(unwrap_v384, "__wrapped__", current)
    v366._unwrap = unwrap_v384
    return True


def _exact_scoped_authority(broker: Any) -> tuple[bool, str]:
    if broker is None:
        return False, "exact_broker_missing"
    try:
        v337 = importlib.import_module("bot.runtime_protective_exit_authority_bridge_v337_patch")
        v339 = importlib.import_module("bot.runtime_protective_exit_broker_health_v339_patch")
        probe = getattr(v337, "_hard_exit_authority_proof", None)
        broker_var = getattr(v339, "_BROKER", None)
        if not callable(probe) or broker_var is None:
            return False, "exact_broker_authority_surface_unavailable"
        token = broker_var.set(broker)
        try:
            ok, reason, _snapshot = probe()
        finally:
            broker_var.reset(token)
        return bool(ok), str(reason or "unproven")
    except Exception as exc:
        return False, f"exact_broker_authority_exception:{type(exc).__name__}"


def _patch_v367_software_status() -> bool:
    v367 = _v367()
    current = getattr(v367, "_software_protection_status", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def software_status_v384():
        broker = _BROKER_SCOPE.get()
        if broker is None:
            return current()
        if not bool(getattr(v367, "_monitor_alive", lambda: False)()):
            return False, "margin_monitor_not_alive"
        if not bool(getattr(v367, "_margin_scan_wiring_ready", lambda: False)()):
            return False, "margin_scan_wiring_unproven"
        ok, reason = _exact_scoped_authority(broker)
        if not ok:
            return False, f"hard_exit_authority_unproven:{reason}"
        return True, "dedicated_margin_monitor_and_exact_broker_hard_exit_authority_ready_v384"

    setattr(software_status_v384, _PATCH_ATTR, True)
    setattr(software_status_v384, "__wrapped__", current)
    v367._software_protection_status = software_status_v384
    return True


def _ensure_coverage_scope() -> bool:
    """Keep exact broker scope outermost across later v367/v368 reassertions."""
    v366 = _v366()
    v367 = _v367()
    current = getattr(v366, "margin_coverage_rows", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def coverage_scope_v384(account: str, broker: Any):
        token = _BROKER_SCOPE.set(broker)
        try:
            return current(account, broker)
        finally:
            _BROKER_SCOPE.reset(token)

    setattr(coverage_scope_v384, _PATCH_ATTR, True)
    # Also mark this as satisfying v367's coverage wrapper contract.  The v367
    # processing layer already exists underneath; this prevents later reasserts
    # from inserting a new v367 layer outside exact-broker scope.
    patch_attr = str(getattr(v367, "_PATCH_ATTR", "") or "")
    if patch_attr:
        setattr(coverage_scope_v384, patch_attr, True)
    setattr(coverage_scope_v384, "__wrapped__", current)
    v366.margin_coverage_rows = coverage_scope_v384
    return True


def _patch_v367_reassert() -> bool:
    """Make future v367 reassertions preserve v384 as the outer coverage scope."""
    v367 = _v367()
    current = getattr(v367, "_patch_v366_coverage", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def patch_coverage_v384():
        ok = bool(current())
        return bool(ok and _ensure_coverage_scope())

    setattr(patch_coverage_v384, _PATCH_ATTR, True)
    setattr(patch_coverage_v384, "__wrapped__", current)
    v367._patch_v366_coverage = patch_coverage_v384
    return True


def _clear_transient_caches() -> None:
    try:
        v367 = _v367()
        v367._AUTH_CACHE = (0.0, False, "v384_reproof")
        native = getattr(v367, "_NATIVE_CACHE", None)
        if isinstance(native, dict):
            native.clear()
    except Exception:
        pass
    try:
        cache = getattr(_v366(), "_CACHE", None)
        if isinstance(cache, dict):
            # Only discard read cache; authoritative broker reads will refill it.
            cache.clear()
    except Exception:
        pass


def _wake_audit() -> None:
    try:
        v281 = importlib.import_module("bot.runtime_all_account_position_exit_coverage_v281_patch")
        audit = getattr(v281, "audit_once", None)
        if callable(audit):
            audit()
    except Exception:
        LOGGER.debug("v384 audit wake deferred", exc_info=True)


def install_import_hook() -> bool:
    with _LOCK:
        try:
            unwrap_ready = _patch_v366_unwrap()
            status_ready = _patch_v367_software_status()
            reassert_ready = _patch_v367_reassert()
            scope_ready = _ensure_coverage_scope()
            ready = bool(unwrap_ready and status_ready and reassert_ready and scope_ready)
        except Exception as exc:
            ready = False
            LOGGER.exception(
                "RUNTIME_KRAKEN_HEALTH_USER_REFRESH_V384_INSTALL_FAILED marker=%s error=%s:%s "
                "trading_fail_closed=true global_health_unchanged=true safety_gates_bypassed=false",
                MARKER, type(exc).__name__, exc,
            )
        os.environ[_READY_FLAG] = "1" if ready else "0"
        log = LOGGER.critical if ready else LOGGER.error
        log(
            "RUNTIME_KRAKEN_HEALTH_USER_REFRESH_V384_%s marker=%s ready=%s "
            "deep_proxy_private_reads=true exact_broker_coverage_scope=true v367_reassert_guard=true "
            "global_dispatch_health_not_promoted=true authenticated_read_not_execution_health=true "
            "writer_nonce_risk_killswitch_terminal_gates_unchanged=true safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY", MARKER, str(ready).lower(),
        )
        if ready:
            _clear_transient_caches()
            _wake_audit()
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER", "install", "install_import_hook", "_deepest_known_proxy",
    "_patch_v366_unwrap", "_ensure_coverage_scope",
]
