"""Fail-closed guard for disconnected broker execution paths.

This startup patch repairs broker-independent routing that previously admitted a
broker even when its explicit ``connected`` flag was false.  It also protects
Coinbase position readers from dereferencing a missing API client.

The guard does not enable a broker, fabricate balance, grant execution
authority, or bypass any risk/Redis gate.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from functools import wraps
from types import ModuleType, SimpleNamespace
from typing import Any

logger = logging.getLogger("nija.disconnected_broker_execution_guard")
_MARKER = "20260710z"
_STARTED = False
_START_LOCK = threading.Lock()
_PATCHED_EXECUTION: set[int] = set()
_PATCHED_BROKER_CLASSES: set[int] = set()
_PATCHED_CORE_CLASSES: set[int] = set()
_LAST_LOG: dict[tuple[int, str], float] = {}

_EXECUTION_MODULE_NAMES = (
    "bot.broker_independent_live_execution_patch",
    "broker_independent_live_execution_patch",
)
_BROKER_MODULE_NAMES = ("bot.broker_manager", "broker_manager")
_CORE_MODULE_NAMES = ("bot.nija_core_loop", "nija_core_loop")
_POSITION_METHODS = ("get_positions", "get_open_positions", "fetch_positions")


def _broker_name(broker: Any) -> str:
    if broker is None:
        return "unknown"
    for attr in ("broker_type", "name", "broker_name", "exchange", "exchange_name", "id"):
        try:
            value = getattr(broker, attr, None)
            value = getattr(value, "value", value)
            text = str(value or "").strip().lower()
            for key in ("coinbase", "kraken", "okx", "alpaca", "binance"):
                if key in text:
                    return key
        except Exception:
            pass
    text = type(broker).__name__.lower()
    for key in ("coinbase", "kraken", "okx", "alpaca", "binance"):
        if key in text:
            return key
    return "unknown"


def _read_surface(broker: Any, name: str) -> tuple[bool, bool]:
    """Return (surface_present, truth_value) without propagating adapter errors."""
    try:
        if not hasattr(broker, name):
            return False, False
        value = getattr(broker, name)
        if callable(value):
            value = value()
        if value is None:
            return True, False
        return True, bool(value)
    except Exception:
        return True, False


def _connection_state(broker: Any) -> tuple[bool, str]:
    if broker is None:
        return False, "broker_missing"

    broker_name = _broker_name(broker)
    positive = False
    explicit_seen = False

    # Explicit connection state is authoritative.  Any explicit false surface
    # prevents the legacy "assume connected" fallback.
    for name in ("connected", "is_connected", "_connected", "_is_connected"):
        present, value = _read_surface(broker, name)
        if present:
            explicit_seen = True
            if not value:
                return False, f"{name}=false"
            positive = True

    for name in ("is_ready_for_trading", "is_ready_for_capital", "is_available", "_is_available", "available"):
        present, value = _read_surface(broker, name)
        if present:
            explicit_seen = True
            positive = positive or value

    # The concrete Coinbase broker cannot authenticate or read positions without
    # an API client.  Do not treat a class shell as an executable venue.
    if broker_name == "coinbase":
        client_surfaces = []
        for name in ("client", "api_client", "_client", "_api_client", "rest_client"):
            try:
                if hasattr(broker, name):
                    client_surfaces.append(getattr(broker, name, None))
            except Exception:
                client_surfaces.append(None)
        if client_surfaces and not any(client is not None for client in client_surfaces):
            return False, "client_missing"

    if positive:
        return True, "explicit_ready"
    if explicit_seen:
        return False, "no_ready_surface_true"

    # Preserve compatibility for legacy broker adapters that expose no status
    # surface at all.  Their normal balance/order gates remain authoritative.
    return True, "legacy_no_status_surface"


def _log_skip(broker: Any, surface: str, reason: str) -> None:
    now = time.monotonic()
    key = (id(broker), surface)
    if now - _LAST_LOG.get(key, 0.0) < 60.0:
        return
    _LAST_LOG[key] = now
    logger.warning(
        "BROKER_EXECUTION_DISCONNECTED_SKIPPED marker=%s broker=%s surface=%s reason=%s connected=%s client_present=%s",
        _MARKER,
        _broker_name(broker),
        surface,
        reason,
        getattr(broker, "connected", None),
        any(
            getattr(broker, attr, None) is not None
            for attr in ("client", "api_client", "_client", "_api_client", "rest_client")
            if hasattr(broker, attr)
        ),
    )


def _empty_scan_result(core_class: type) -> Any:
    core_module = sys.modules.get(getattr(core_class, "__module__", ""))
    result_cls = getattr(core_module, "CoreLoopResult", None) if isinstance(core_module, ModuleType) else None
    try:
        result = result_cls() if callable(result_cls) else SimpleNamespace()
    except Exception:
        result = SimpleNamespace()
    for name, value in (
        ("entries_taken", 0),
        ("entries_blocked", 0),
        ("symbols_scored", 0),
        ("exits_taken", 0),
        ("errors", []),
        ("next_interval", 150),
    ):
        try:
            setattr(result, name, value)
        except Exception:
            pass
    return result


def _patch_core_outer_guards() -> int:
    patched = 0
    for core_name in _CORE_MODULE_NAMES:
        core_module = sys.modules.get(core_name)
        core_class = getattr(core_module, "NijaCoreLoop", None) if isinstance(core_module, ModuleType) else None
        if not isinstance(core_class, type) or id(core_class) in _PATCHED_CORE_CLASSES:
            continue
        current = getattr(core_class, "run_scan_phase", None)
        if not callable(current):
            continue
        if getattr(current, "_nija_disconnected_broker_outer_guard", False):
            _PATCHED_CORE_CLASSES.add(id(core_class))
            continue

        @wraps(current)
        def guarded_run_scan_phase(
            self: Any,
            broker: Any,
            balance: float,
            symbols: list[str],
            open_positions_count: int = 0,
            user_mode: bool = False,
            _original=current,
            _core_class=core_class,
        ) -> Any:
            ready, reason = _connection_state(broker)
            if not ready:
                _log_skip(broker, "run_scan_phase", reason)
                return _empty_scan_result(_core_class)
            return _original(self, broker, balance, symbols, open_positions_count, user_mode)

        setattr(guarded_run_scan_phase, "_nija_disconnected_broker_outer_guard", _MARKER)
        setattr(core_class, "run_scan_phase", guarded_run_scan_phase)
        _PATCHED_CORE_CLASSES.add(id(core_class))
        patched += 1
        logger.critical(
            "BROKER_EXECUTION_DISCONNECTED_CORE_GUARD_PATCHED marker=%s module=%s class=%s",
            _MARKER,
            core_name,
            core_class.__name__,
        )
    return patched


def _patch_execution_module(module: ModuleType) -> bool:
    module_id = id(module)
    if module_id in _PATCHED_EXECUTION:
        return False

    original_ready = module.__dict__.get("_broker_is_connected_or_ready")
    original_balance = module.__dict__.get("_broker_entry_balance")
    original_positions = module.__dict__.get("_broker_position_count")
    if not callable(original_ready):
        return False

    def ready_guard(broker: Any) -> bool:
        ready, reason = _connection_state(broker)
        if not ready:
            _log_skip(broker, "candidate_filter", reason)
        return ready

    def balance_guard(name: str, broker: Any, fallback: float) -> float:
        ready, reason = _connection_state(broker)
        if not ready:
            _log_skip(broker, "entry_balance", reason)
            return 0.0
        if callable(original_balance):
            return float(original_balance(name, broker, fallback) or 0.0)
        return 0.0

    def position_guard(broker: Any, fallback: int = 0) -> int:
        ready, reason = _connection_state(broker)
        if not ready:
            _log_skip(broker, "position_count", reason)
            return 0
        if callable(original_positions):
            return int(original_positions(broker, fallback) or 0)
        return max(0, int(fallback or 0))

    setattr(ready_guard, "_nija_disconnected_broker_guard", _MARKER)
    setattr(balance_guard, "_nija_disconnected_broker_guard", _MARKER)
    setattr(position_guard, "_nija_disconnected_broker_guard", _MARKER)
    module.__dict__["_broker_is_connected_or_ready"] = ready_guard
    module.__dict__["_broker_entry_balance"] = balance_guard
    module.__dict__["_broker_position_count"] = position_guard

    _patch_core_outer_guards()

    _PATCHED_EXECUTION.add(module_id)
    logger.critical(
        "BROKER_EXECUTION_DISCONNECTED_GUARD_PATCHED marker=%s module=%s aggregate_balance_reuse=false",
        _MARKER,
        module.__name__,
    )
    return True


def _coinbase_disconnected(instance: Any) -> tuple[bool, str]:
    if _broker_name(instance) != "coinbase":
        return False, "not_coinbase"
    ready, reason = _connection_state(instance)
    return (not ready), reason


def _patch_broker_class(cls: type) -> bool:
    class_id = id(cls)
    if class_id in _PATCHED_BROKER_CLASSES:
        return False
    changed = False
    for method_name in _POSITION_METHODS:
        original = getattr(cls, method_name, None)
        if not callable(original) or getattr(original, "_nija_disconnected_position_guard", False):
            continue

        @wraps(original)
        def position_reader(self: Any, *args: Any, _original=original, _surface=method_name, **kwargs: Any) -> Any:
            disconnected, reason = _coinbase_disconnected(self)
            if disconnected:
                _log_skip(self, _surface, reason)
                return []
            return _original(self, *args, **kwargs)

        setattr(position_reader, "_nija_disconnected_position_guard", _MARKER)
        setattr(cls, method_name, position_reader)
        changed = True

    if changed:
        _PATCHED_BROKER_CLASSES.add(class_id)
        logger.critical(
            "COINBASE_DISCONNECTED_POSITION_GUARD_PATCHED marker=%s class=%s",
            _MARKER,
            cls.__name__,
        )
    return changed


def _patch_broker_module(module: ModuleType) -> bool:
    changed = False
    for name in ("CoinbaseBroker", "CoinbaseAdvancedTradeBroker"):
        cls = getattr(module, name, None)
        if isinstance(cls, type):
            changed = _patch_broker_class(cls) or changed
    return changed


def apply_once() -> int:
    patched = _patch_core_outer_guards()
    for name in _EXECUTION_MODULE_NAMES:
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            try:
                patched += int(_patch_execution_module(module))
            except Exception as exc:
                logger.warning(
                    "BROKER_EXECUTION_DISCONNECTED_GUARD_FAILED marker=%s module=%s err=%s",
                    _MARKER,
                    name,
                    exc,
                )
    for name in _BROKER_MODULE_NAMES:
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            try:
                patched += int(_patch_broker_module(module))
            except Exception as exc:
                logger.warning(
                    "COINBASE_DISCONNECTED_POSITION_GUARD_FAILED marker=%s module=%s err=%s",
                    _MARKER,
                    name,
                    exc,
                )
    return patched


def _monitor() -> None:
    deadline = time.monotonic() + 900.0
    last_log = 0.0
    while time.monotonic() < deadline:
        patched = apply_once()
        now = time.monotonic()
        if patched or now - last_log >= 30.0:
            logger.info(
                "BROKER_EXECUTION_DISCONNECTED_GUARD_HEARTBEAT marker=%s patched_now=%d execution_modules=%d broker_classes=%d core_classes=%d",
                _MARKER,
                patched,
                len(_PATCHED_EXECUTION),
                len(_PATCHED_BROKER_CLASSES),
                len(_PATCHED_CORE_CLASSES),
            )
            last_log = now
        time.sleep(0.01 if not _PATCHED_EXECUTION else 2.0)


def install_import_hook() -> None:
    global _STARTED
    apply_once()
    if _STARTED:
        return
    with _START_LOCK:
        if _STARTED:
            return
        _STARTED = True
        thread = threading.Thread(
            target=_monitor,
            name="disconnected-broker-execution-guard",
            daemon=True,
        )
        thread.start()
        logger.warning(
            "BROKER_EXECUTION_DISCONNECTED_GUARD_INSTALLED marker=%s thread_alive=%s authority_bypass=false risk_bypass=false",
            _MARKER,
            thread.is_alive(),
        )


def install() -> None:
    install_import_hook()
