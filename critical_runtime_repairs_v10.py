"""Stabilize live broker connection ownership and runtime release convergence.

This repair is intentionally fail-closed. It does not bypass writer authority,
risk sizing, exchange minimums, or release-manifest checks. It makes the
canonical Coinbase/OKX connect wrappers terminal, keeps the zero-signal state
repair attached when later patches replace Phase 3, and republishes release
readiness only when the existing audits pass.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any, Callable

logger = logging.getLogger("nija.critical_runtime_repairs_v10")
_MARKER = "20260720-critical-runtime-repairs-v10"
_LOCK = threading.RLock()
_LOCAL = threading.local()
_STARTED = False

_COINBASE_OWNER_ATTR = "_nija_coinbase_terminal_owner_v10"
_OKX_OWNER_ATTR = "_nija_okx_terminal_owner_v10"

_COINBASE_COMPAT_ATTRS = (
    _COINBASE_OWNER_ATTR,
    "_nija_coinbase_connect_recursion_terminal_v2",
    "_nija_coinbase_connection_funding_v3",
    "_nija_coinbase_connection_convergence_v2",
    "_nija_coinbase_authenticated_connect_v1",
    "_nija_coinbase_failfast_20260713b",
    "_nija_runtime_convergence_auth_e",
    "_nija_final_auth_safe",
    "_nija_runtime_convergence_auth_safe_v2",
    "_nija_auth_recovery_20260711n",
    "_nija_auth_v2",
)

_OKX_COMPAT_ATTRS = (
    _OKX_OWNER_ATTR,
    "_nija_final_okx_endpoint_e",
    "_nija_okx_connect_canonical_20260713b",
    "_nija_endpoint_instance_repair_v2",
    "_nija_runtime_convergence_auth_e",
    "_nija_final_auth_safe",
    "_nija_runtime_convergence_auth_safe_v2",
    "_nija_auth_recovery_20260711n",
    "_nija_auth_v2",
)


def _unwrap(func: Any, max_depth: int = 256) -> tuple[Any, int, bool]:
    current = func
    seen: set[int] = set()
    depth = 0
    while callable(current):
        ident = id(current)
        if ident in seen:
            return current, depth, True
        seen.add(ident)
        wrapped = getattr(current, "__wrapped__", None)
        if not callable(wrapped):
            return current, depth, False
        current = wrapped
        depth += 1
        if depth >= max_depth:
            return current, depth, True
    return current, depth, False


def _set_attrs(func: Callable[..., Any], attrs: tuple[str, ...]) -> None:
    for attr in attrs:
        try:
            setattr(func, attr, True)
        except Exception:
            pass


def _normalise_coinbase() -> bool:
    for module_name, function_name in (
        ("bot.coinbase_funding_readiness_repair_patch", "recover_coinbase_environment"),
        ("bot.coinbase_connection_convergence_patch", "normalize_environment"),
        ("broker_auth_recovery_patch", "normalize_coinbase_environment"),
    ):
        try:
            module = importlib.import_module(module_name)
            function = getattr(module, function_name, None)
            if callable(function):
                return bool(function())
        except Exception:
            continue
    return False


def _coinbase_probe(broker: Any) -> tuple[bool, str]:
    for module_name, function_name in (
        ("coinbase_connect_recursion_terminal_guard", "_private_probe"),
        ("coinbase_authenticated_connect_recovery_patch", "_authenticated_probe"),
    ):
        try:
            module = importlib.import_module(module_name)
            function = getattr(module, function_name, None)
            if callable(function):
                result = function(broker)
                if isinstance(result, tuple) and len(result) >= 2:
                    return bool(result[0]), str(result[1])
        except Exception:
            continue
    return False, "private_account_probe_unavailable"


def _publish_coinbase_failure(detail: str) -> None:
    os.environ["NIJA_COINBASE_CONNECTED"] = "0"
    os.environ["NIJA_COINBASE_TRADING_READY"] = "0"
    os.environ["NIJA_COINBASE_ACTIVATED"] = "0"
    os.environ["NIJA_COINBASE_ACTIVATION_STATE"] = "authentication_failed"
    os.environ["NIJA_COINBASE_FUNDING_STATUS"] = "auth_unavailable"
    logger.error("COINBASE_TERMINAL_CONNECT_FAILED marker=%s detail=%s", _MARKER, detail[:400])


def _publish_coinbase_success(broker: Any, source: str) -> None:
    try:
        setattr(broker, "connected", True)
    except Exception:
        pass
    spendable = 0.0
    try:
        helper = importlib.import_module("bot.coinbase_funding_readiness_repair_patch")
        measure = getattr(helper, "_measure_spendable", None)
        publish = getattr(helper, "_publish_ready", None)
        if callable(measure):
            spendable = max(0.0, float(measure(broker) or 0.0))
        if callable(publish):
            publish(spendable)
    except Exception:
        logger.debug("COINBASE_TERMINAL_FUNDING_PUBLISH_FAILED marker=%s", _MARKER, exc_info=True)
    os.environ["NIJA_COINBASE_CONNECTED"] = "1"
    os.environ["NIJA_COINBASE_BALANCE_OBSERVED"] = "1"
    os.environ["NIJA_COINBASE_SPENDABLE_QUOTE"] = f"{spendable:.8f}"
    os.environ["NIJA_COINBASE_FUNDING_STATUS"] = "funded" if spendable > 0 else "observed_zero"
    os.environ["NIJA_COINBASE_TRADING_READY"] = "1" if spendable > 0 else "0"
    os.environ["NIJA_COINBASE_ACTIVATED"] = "1"
    os.environ["NIJA_COINBASE_ACTIVATION_STATE"] = "ready" if spendable > 0 else "connected_unfunded"
    logger.critical(
        "COINBASE_TERMINAL_CONNECT_RECOVERED marker=%s source=%s spendable=$%.2f",
        _MARKER,
        source,
        spendable,
    )


def _patch_coinbase_class(cls: type) -> bool:
    current = getattr(cls, "connect", None)
    if not callable(current):
        return False
    if bool(getattr(current, _COINBASE_OWNER_ATTR, False)):
        _set_attrs(current, _COINBASE_COMPAT_ATTRS)
        return True

    base, depth, cycle = _unwrap(current)

    def connect(self: Any, *args: Any, **kwargs: Any) -> Any:
        active = getattr(_LOCAL, "coinbase_active", set())
        identity = id(self)
        if identity in active:
            authenticated, detail = _coinbase_probe(self)
            if authenticated:
                _publish_coinbase_success(self, "reentry_probe:" + detail)
                return True
            _publish_coinbase_failure("same_thread_reentry:" + detail)
            return False

        if not _normalise_coinbase():
            _publish_coinbase_failure("invalid_credential_shape")
            try:
                setattr(self, "connected", False)
            except Exception:
                pass
            return False

        active = set(active)
        active.add(identity)
        _LOCAL.coinbase_active = active
        try:
            target = base if callable(base) and not cycle else current
            try:
                result = target(self, *args, **kwargs)
            except RecursionError as exc:
                authenticated, detail = _coinbase_probe(self)
                if authenticated:
                    _publish_coinbase_success(self, "recursion_probe:" + detail)
                    return True
                _publish_coinbase_failure(f"RecursionError:{exc}:{detail}")
                return False

            if bool(result) or bool(getattr(self, "connected", False)):
                authenticated, detail = _coinbase_probe(self)
                if authenticated:
                    _publish_coinbase_success(self, detail)
                else:
                    _publish_coinbase_failure("connect_true_private_probe_failed:" + detail)
                    try:
                        setattr(self, "connected", False)
                    except Exception:
                        pass
                    return False
                return result if result is not None else True

            authenticated, detail = _coinbase_probe(self)
            if authenticated:
                _publish_coinbase_success(self, detail)
                return True
            _publish_coinbase_failure(detail)
            return result
        finally:
            remaining = set(getattr(_LOCAL, "coinbase_active", set()))
            remaining.discard(identity)
            _LOCAL.coinbase_active = remaining

    connect.__name__ = "connect"
    connect.__qualname__ = getattr(current, "__qualname__", f"{cls.__name__}.connect")
    connect.__doc__ = getattr(current, "__doc__", None)
    _set_attrs(connect, _COINBASE_COMPAT_ATTRS)
    if callable(base) and not cycle:
        connect.__wrapped__ = base  # type: ignore[attr-defined]
    cls.connect = connect
    logger.critical(
        "COINBASE_TERMINAL_OWNER_INSTALLED marker=%s module=%s class=%s collapsed_layers=%d cycle=%s",
        _MARKER,
        cls.__module__,
        cls.__name__,
        depth,
        str(cycle).lower(),
    )
    return True


def _apply_okx_url(instance: Any) -> str:
    url = str(os.environ.get("OKX_BASE_URL", "https://us.okx.com") or "https://us.okx.com").strip().rstrip("/")
    os.environ["OKX_BASE_URL"] = url
    for attr in ("base_url", "api_base_url", "endpoint", "api_url", "rest_url"):
        try:
            if hasattr(instance, attr):
                setattr(instance, attr, url)
        except Exception:
            pass
    return url


def _patch_okx_class(cls: type) -> bool:
    current = getattr(cls, "connect", None)
    if not callable(current):
        return False
    if bool(getattr(current, _OKX_OWNER_ATTR, False)):
        _set_attrs(current, _OKX_COMPAT_ATTRS)
        return True

    _base, depth, cycle = _unwrap(current)

    def connect(self: Any, *args: Any, **kwargs: Any) -> Any:
        active = getattr(_LOCAL, "okx_active", set())
        identity = id(self)
        if identity in active:
            try:
                setattr(self, "connected", False)
            except Exception:
                pass
            os.environ["NIJA_OKX_CONNECTED"] = "0"
            os.environ["NIJA_OKX_FUNDING_STATUS"] = "connect_recursion_blocked"
            logger.error("OKX_TERMINAL_CONNECT_REENTRY_BLOCKED marker=%s class=%s", _MARKER, cls.__name__)
            return False
        active = set(active)
        active.add(identity)
        _LOCAL.okx_active = active
        try:
            _apply_okx_url(self)
            try:
                result = current(self, *args, **kwargs)
            except RecursionError as exc:
                try:
                    setattr(self, "connected", False)
                except Exception:
                    pass
                os.environ["NIJA_OKX_CONNECTED"] = "0"
                os.environ["NIJA_OKX_FUNDING_STATUS"] = "connect_recursion_blocked"
                logger.error("OKX_TERMINAL_CONNECT_RECURSION_BLOCKED marker=%s error=%s", _MARKER, str(exc)[:200])
                return False
            _apply_okx_url(self)
            return result
        finally:
            remaining = set(getattr(_LOCAL, "okx_active", set()))
            remaining.discard(identity)
            _LOCAL.okx_active = remaining

    connect.__name__ = "connect"
    connect.__qualname__ = getattr(current, "__qualname__", f"{cls.__name__}.connect")
    connect.__doc__ = getattr(current, "__doc__", None)
    _set_attrs(connect, _OKX_COMPAT_ATTRS)
    if not cycle:
        connect.__wrapped__ = current  # type: ignore[attr-defined]
    cls.connect = connect
    logger.critical(
        "OKX_TERMINAL_OWNER_INSTALLED marker=%s module=%s class=%s preserved_layers=%d cycle=%s endpoint=%s",
        _MARKER,
        cls.__module__,
        cls.__name__,
        depth,
        str(cycle).lower(),
        os.environ.get("OKX_BASE_URL", "https://us.okx.com"),
    )
    return True


def _patch_broker_modules() -> bool:
    patched = False
    names = (
        "bot.broker_manager", "broker_manager",
        "bot.broker_integration", "broker_integration",
        "bot.multi_account_broker_manager", "multi_account_broker_manager",
    )
    seen_classes: set[int] = set()
    for name in names:
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            continue
        for value in vars(module).values():
            if not isinstance(value, type) or id(value) in seen_classes:
                continue
            seen_classes.add(id(value))
            lowered = value.__name__.lower()
            if "coinbase" in lowered:
                patched = _patch_coinbase_class(value) or patched
            elif "okx" in lowered:
                patched = _patch_okx_class(value) or patched
    return patched


def _repair_zero_signal_state() -> bool:
    repaired = False
    try:
        patch = importlib.import_module("bot.zero_signal_streak_state_repair_patch")
    except Exception:
        return False
    installer = getattr(patch, "_install_on_core_loop", None)
    if not callable(installer):
        return False
    for name in ("bot.nija_core_loop", "nija_core_loop"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            try:
                repaired = bool(installer(module)) or repaired
            except Exception:
                logger.exception("ZERO_SIGNAL_STATE_V10_REPAIR_FAILED marker=%s module=%s", _MARKER, name)
    return repaired


def _republish_release_if_ready() -> bool:
    try:
        identity = importlib.import_module("runtime_module_identity_convergence_patch")
        quiescence = importlib.import_module("runtime_convergence_quiescence_patch")
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        identity_ready, _ = identity.audit()
        quiescence_ready, _ = quiescence.audit()
        ready, details = manifest._audit()
        final_ready = bool(identity_ready and quiescence_ready and ready)
        manifest._publish(final_ready, details)
        return final_ready
    except Exception:
        logger.debug("RUNTIME_RELEASE_V10_REPUBLISH_DEFERRED marker=%s", _MARKER, exc_info=True)
        return False


def _apply() -> tuple[bool, bool, bool]:
    brokers = _patch_broker_modules()
    zero_signal = _repair_zero_signal_state()
    release = _republish_release_if_ready()
    return brokers, zero_signal, release


def _monitor() -> None:
    last: tuple[bool, bool, bool] | None = None
    while True:
        try:
            state = _apply()
            if state != last:
                last = state
                logger.warning(
                    "CRITICAL_RUNTIME_REPAIRS_V10_STATE marker=%s brokers=%s zero_signal=%s release_ready=%s",
                    _MARKER,
                    state[0],
                    state[1],
                    state[2],
                )
        except Exception:
            logger.exception("CRITICAL_RUNTIME_REPAIRS_V10_RETRY marker=%s", _MARKER)
        time.sleep(max(0.25, float(os.environ.get("NIJA_CRITICAL_V10_MONITOR_S", "1.0") or 1.0)))


def install() -> bool:
    global _STARTED
    with _LOCK:
        prior = importlib.import_module("critical_runtime_repairs_v9")
        prior_install = getattr(prior, "install", None)
        if not callable(prior_install) or not prior_install():
            raise RuntimeError("critical_runtime_repairs_v9_not_ready")
        _apply()
        if not _STARTED:
            _STARTED = True
            threading.Thread(target=_monitor, name="CriticalRuntimeRepairsV10", daemon=True).start()
        os.environ["NIJA_CRITICAL_RUNTIME_REPAIRS_V10_READY"] = "1"
        logger.critical(
            "CRITICAL_RUNTIME_REPAIRS_V10_READY marker=%s coinbase_terminal_owner=true okx_terminal_owner=true zero_signal_persistent=true release_fail_closed_preserved=true",
            _MARKER,
        )
        return True


__all__ = [
    "install",
    "_unwrap",
    "_patch_coinbase_class",
    "_patch_okx_class",
    "_patch_broker_modules",
    "_repair_zero_signal_state",
    "_republish_release_if_ready",
]
