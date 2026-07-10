"""Fail-closed venue readiness and late OKX binding repair.

This patch fixes three runtime contracts without granting execution authority:

* Explicitly disconnected platform brokers cannot contribute capital snapshots.
* Broker-independent scans never fall back to a disconnected caller broker.
* The existing OKX order-callshape bridge is rebound when concrete broker/router
  classes load after its original monitor window.

The patch does not create credentials, mark brokers connected, bypass writer
  authority, or weaken risk/order admission.
"""

from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from types import ModuleType, SimpleNamespace
from typing import Any, Optional

logger = logging.getLogger("nija.venue_readiness_execution_repair")
_MARKER = "20260710ae"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_INSTALL_LOCK = threading.RLock()
_INSTALLED = False
_MONITOR_STARTED = False
_CAPITAL_WRAP_ATTR = "_nija_venue_readiness_capital_v20260710ae"
_CORE_WRAP_ATTR = "_nija_venue_readiness_core_v20260710ae"
_PATCHED_MABM: set[str] = set()
_PATCHED_CORE: set[str] = set()
_LAST_EXCLUDED_LOG: dict[str, float] = {}


def _truthy(name: str, default: str = "") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in _TRUE


def _normalise_broker_name(value: Any) -> str:
    raw = getattr(value, "value", value)
    text = str(raw or "").strip().lower()
    compact = text.replace("_", "").replace("-", "").replace(" ", "")
    for key in ("okx", "coinbase", "kraken", "alpaca", "binance"):
        if key in compact:
            return key
    return text


def _broker_name(broker: Any, fallback: Any = "") -> str:
    if broker is not None:
        for attr in ("broker_type", "name", "broker_name", "exchange", "exchange_name", "NAME"):
            try:
                name = _normalise_broker_name(getattr(broker, attr, None))
                if name:
                    return name
            except Exception:
                pass
        try:
            name = _normalise_broker_name(type(broker).__name__)
            if name:
                return name
        except Exception:
            pass
    return _normalise_broker_name(fallback) or "unknown"


def _explicit_connection_state(broker: Any) -> tuple[Optional[bool], str]:
    """Return explicit connection truth when the adapter exposes it.

    Any explicit false state wins. This prevents stale balance payloads from
    resurrecting a disconnected venue.
    """
    if broker is None:
        return False, "broker_missing"

    observed: list[tuple[str, bool]] = []
    for attr in ("connected", "is_connected"):
        try:
            if not hasattr(broker, attr):
                continue
            value = getattr(broker, attr)
            if callable(value):
                value = value()
            if value is None:
                continue
            observed.append((attr, bool(value)))
        except Exception:
            observed.append((attr, False))

    if observed:
        false_names = [name for name, value in observed if not value]
        if false_names:
            return False, "explicit_false:" + ",".join(false_names)
        return True, "explicit_true:" + ",".join(name for name, _ in observed)

    for attr in ("connection_state", "_connection_state", "status"):
        try:
            value = getattr(broker, attr, None)
            raw = getattr(value, "value", value)
            text = str(raw or "").strip().lower()
            if not text:
                continue
            if text in {"connected", "ready", "active", "online"}:
                return True, f"{attr}:{text}"
            if text in {"disconnected", "failed", "offline", "closed", "not_started"}:
                return False, f"{attr}:{text}"
        except Exception:
            continue

    return None, "connection_state_absent"


def _broker_execution_ready(broker: Any) -> bool:
    state, _reason = _explicit_connection_state(broker)
    if state is not None:
        return bool(state)

    # Only adapters with no explicit connection field may use readiness methods.
    for attr in ("is_ready_for_trading", "is_available", "is_ready_for_capital"):
        try:
            fn = getattr(broker, attr, None)
            if callable(fn) and bool(fn()):
                return True
        except Exception:
            continue
    return False


def _rate_limited_exclusion_log(scope: str, excluded: list[str], trigger: str = "") -> None:
    if not excluded:
        return
    key = f"{scope}:{','.join(sorted(excluded))}:{trigger}"
    now = time.monotonic()
    if now - _LAST_EXCLUDED_LOG.get(key, 0.0) < 10.0:
        return
    _LAST_EXCLUDED_LOG[key] = now
    logger.warning(
        "VENUE_READINESS_EXCLUDED marker=%s scope=%s trigger=%s brokers=%s",
        _MARKER,
        scope,
        trigger or "unknown",
        ",".join(sorted(excluded)),
    )


def _patch_mabm_module(module: ModuleType) -> bool:
    cls = getattr(module, "MultiAccountBrokerManager", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "refresh_capital_authority", None)
    if not callable(current):
        return False
    if getattr(current, _CAPITAL_WRAP_ATTR, False):
        _PATCHED_MABM.add(getattr(module, "__name__", "<unknown>"))
        return True

    original = current

    def _filtered_refresh(self: Any, *args: Any, **kwargs: Any) -> Any:
        broker_map = getattr(self, "_platform_brokers", None)
        if not isinstance(broker_map, dict) or not broker_map:
            return original(self, *args, **kwargs)

        lock = getattr(self, "_nija_venue_readiness_filter_lock", None)
        if lock is None:
            lock = threading.RLock()
            try:
                setattr(self, "_nija_venue_readiness_filter_lock", lock)
            except Exception:
                pass

        trigger = str(kwargs.get("trigger", args[0] if args else "manual"))
        with lock:
            live_map = getattr(self, "_platform_brokers", broker_map)
            if not isinstance(live_map, dict):
                return original(self, *args, **kwargs)

            filtered: dict[Any, Any] = {}
            excluded: list[str] = []
            for raw_key, broker in live_map.items():
                if _broker_execution_ready(broker):
                    filtered[raw_key] = broker
                else:
                    excluded.append(_broker_name(broker, raw_key))

            if not excluded:
                return original(self, *args, **kwargs)

            _rate_limited_exclusion_log("capital_refresh", excluded, trigger)
            original_map = live_map
            self._platform_brokers = filtered
            try:
                result = original(self, *args, **kwargs)
            finally:
                # Restore only when nobody replaced the filtered map while the
                # original refresh was running.
                if getattr(self, "_platform_brokers", None) is filtered:
                    self._platform_brokers = original_map
            return result

    setattr(_filtered_refresh, _CAPITAL_WRAP_ATTR, True)
    setattr(_filtered_refresh, "__wrapped__", original)
    setattr(cls, "refresh_capital_authority", _filtered_refresh)
    name = getattr(module, "__name__", "<unknown>")
    _PATCHED_MABM.add(name)
    logger.warning(
        "VENUE_READINESS_CAPITAL_REFRESH_PATCHED marker=%s module=%s",
        _MARKER,
        name,
    )
    return True


def _empty_core_result(core_module: ModuleType) -> Any:
    result_cls = getattr(core_module, "CoreLoopResult", None)
    try:
        result = result_cls() if callable(result_cls) else SimpleNamespace()
    except Exception:
        result = SimpleNamespace()
    for key, value in (
        ("entries_taken", 0),
        ("entries_blocked", 0),
        ("symbols_scored", 0),
        ("exits_taken", 0),
        ("errors", []),
        ("next_interval", 150),
    ):
        try:
            setattr(result, key, value)
        except Exception:
            pass
    return result


def _ready_candidates(independent: ModuleType, apex: Any, explicit_broker: Any) -> list[tuple[str, Any]]:
    collect = getattr(independent, "_collect_candidate_brokers", None)
    if not callable(collect):
        return []
    try:
        candidates = dict(collect(apex, explicit_broker) or {})
    except Exception:
        return []

    priority_fn = getattr(independent, "_csv_env", None)
    try:
        priority = list(priority_fn("NIJA_BROKER_PRIORITY", "okx,coinbase,kraken")) if callable(priority_fn) else ["okx", "coinbase", "kraken"]
    except Exception:
        priority = ["okx", "coinbase", "kraken"]
    names = [name for name in priority if name in candidates] + sorted(set(candidates) - set(priority))
    return [
        (name, candidates[name])
        for name in names
        if _broker_execution_ready(candidates[name])
    ]


def _patch_independent_module(module: ModuleType) -> bool:
    if not hasattr(module, "_collect_candidate_brokers"):
        return False
    setattr(module, "_broker_is_connected_or_ready", _broker_execution_ready)
    setattr(module, "_NIJA_VENUE_READINESS_HELPER_MARKER", _MARKER)
    return True


def _patch_core_module(core_module: ModuleType, independent: ModuleType) -> bool:
    cls = getattr(core_module, "NijaCoreLoop", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "run_scan_phase", None)
    if not callable(current):
        return False
    if getattr(current, _CORE_WRAP_ATTR, False):
        _PATCHED_CORE.add(getattr(core_module, "__name__", "<unknown>"))
        return True

    # Wait until the independent wrapper is present. Otherwise it may replace
    # this guard later and reintroduce the disconnected-caller fallback.
    independent_wrap_attr = str(getattr(independent, "_WRAP_ATTR", "") or "")
    if independent_wrap_attr and not getattr(current, independent_wrap_attr, False):
        return False

    original = current

    def _guarded_scan(
        self: Any,
        broker: Any,
        balance: float,
        symbols: list[str],
        open_positions_count: int = 0,
        user_mode: bool = False,
    ) -> Any:
        if _broker_execution_ready(broker):
            return original(self, broker, balance, symbols, open_positions_count, user_mode)

        apex = getattr(self, "apex", None)
        ready = _ready_candidates(independent, apex, broker)
        if not ready:
            name = _broker_name(broker)
            _rate_limited_exclusion_log("scan_dispatch", [name], "no_connected_venue")
            logger.warning(
                "BROKER_INDEPENDENT_SCAN_SKIPPED marker=%s broker=%s reason=not_connected",
                _MARKER,
                name,
            )
            return _empty_core_result(core_module)

        selected_name, selected_broker = ready[0]
        balance_fn = getattr(independent, "_broker_entry_balance", None)
        position_fn = getattr(independent, "_broker_position_count", None)
        try:
            selected_balance = float(balance_fn(selected_name, selected_broker, 0.0)) if callable(balance_fn) else 0.0
        except Exception:
            selected_balance = 0.0
        try:
            selected_open = int(position_fn(selected_broker, 0)) if callable(position_fn) else 0
        except Exception:
            selected_open = 0

        logger.warning(
            "BROKER_INDEPENDENT_SCAN_REROUTED marker=%s from=%s to=%s "
            "reason=caller_not_connected balance=%.2f",
            _MARKER,
            _broker_name(broker),
            selected_name,
            selected_balance,
        )
        return original(
            self,
            selected_broker,
            selected_balance,
            symbols,
            selected_open,
            user_mode,
        )

    setattr(_guarded_scan, _CORE_WRAP_ATTR, True)
    setattr(_guarded_scan, "__wrapped__", original)
    setattr(cls, "run_scan_phase", _guarded_scan)
    name = getattr(core_module, "__name__", "<unknown>")
    _PATCHED_CORE.add(name)
    logger.warning(
        "VENUE_READINESS_CORE_SCAN_PATCHED marker=%s module=%s",
        _MARKER,
        name,
    )
    return True


def _get_module(*names: str) -> Optional[ModuleType]:
    for name in names:
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            return module
    return None


def _bind_okx_bridge_once() -> bool:
    targets = [
        module
        for module in (
            _get_module("bot.broker_manager", "broker_manager"),
            _get_module("bot.broker_integration", "broker_integration"),
            _get_module("bot.multi_broker_execution_router", "multi_broker_execution_router"),
        )
        if module is not None
    ]
    if not targets:
        return False

    bridge = _get_module(
        "bot.okx_final_order_submission_bridge_patch",
        "okx_final_order_submission_bridge_patch",
    )
    if bridge is None:
        try:
            bridge = importlib.import_module("bot.okx_final_order_submission_bridge_patch")
        except Exception as exc:
            logger.debug("OKX bridge import pending marker=%s err=%s", _MARKER, exc)
            return False

    patch_module = getattr(bridge, "_patch_module", None)
    if not callable(patch_module):
        return False

    patched_any = False
    for target in targets:
        try:
            patched_any = bool(patch_module(target)) or patched_any
        except Exception as exc:
            logger.warning(
                "OKX_LATE_BIND_TARGET_FAILED marker=%s module=%s err=%s",
                _MARKER,
                getattr(target, "__name__", "<unknown>"),
                exc,
            )

    router_ready = bool(getattr(bridge, "_ROUTER_PATCHED", False))
    classes = sorted(getattr(bridge, "_PATCHED_ORDER_CLASSES", set()) or set())
    if patched_any or router_ready or classes:
        logger.warning(
            "OKX_LATE_BIND_COMPLETE marker=%s router_patched=%s order_classes=%s",
            _MARKER,
            router_ready,
            classes,
        )
    return router_ready or bool(classes)


def _patch_loaded() -> tuple[bool, bool, bool]:
    mabm_patched = False
    for name in ("bot.multi_account_broker_manager", "multi_account_broker_manager"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            mabm_patched = _patch_mabm_module(module) or mabm_patched

    independent = _get_module(
        "bot.broker_independent_live_execution_patch",
        "broker_independent_live_execution_patch",
    )
    core_patched = False
    if independent is not None:
        _patch_independent_module(independent)
        for name in ("bot.nija_core_loop", "nija_core_loop"):
            core = sys.modules.get(name)
            if isinstance(core, ModuleType):
                core_patched = _patch_core_module(core, independent) or core_patched

    okx_bound = _bind_okx_bridge_once()
    return mabm_patched, core_patched, okx_bound


def _monitor() -> None:
    last_state: tuple[bool, bool, bool] = (False, False, False)
    while True:
        try:
            state = _patch_loaded()
            if state != last_state:
                logger.warning(
                    "VENUE_READINESS_REPAIR_STATE marker=%s capital=%s scan=%s okx=%s",
                    _MARKER,
                    state[0],
                    state[1],
                    state[2],
                )
                last_state = state
            # Continue indefinitely at low frequency. Hot reloads and late class
            # imports must not reopen the disconnected venue path.
            time.sleep(1.0 if not all(state) else 5.0)
        except Exception:
            logger.exception("VENUE_READINESS_REPAIR_MONITOR_ERROR marker=%s", _MARKER)
            time.sleep(2.0)


def install() -> None:
    global _INSTALLED, _MONITOR_STARTED
    with _INSTALL_LOCK:
        if _INSTALLED:
            _patch_loaded()
            return
        _INSTALLED = True
        _patch_loaded()
        if not _MONITOR_STARTED:
            _MONITOR_STARTED = True
            thread = threading.Thread(
                target=_monitor,
                name="venue-readiness-execution-repair",
                daemon=True,
            )
            thread.start()
        logger.warning(
            "VENUE_READINESS_EXECUTION_REPAIR_INSTALLED marker=%s monitor_alive=%s",
            _MARKER,
            True,
        )
        print(
            f"[NIJA-PRINT] VENUE_READINESS_EXECUTION_REPAIR_INSTALLED marker={_MARKER}",
            flush=True,
        )


__all__ = [
    "install",
    "_broker_execution_ready",
    "_patch_mabm_module",
    "_patch_independent_module",
    "_patch_core_module",
    "_bind_okx_bridge_once",
]
