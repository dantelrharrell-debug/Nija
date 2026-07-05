from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.broker_independent_live_execution_patch")

_MARKER = "BROKER_INDEPENDENT_LIVE_EXECUTION_PATCHED marker=20260705a"
_TRUTHY = {"1", "true", "yes", "enabled", "on", "y"}
_FALSEY = {"0", "false", "no", "disabled", "off", "n"}
_WRAP_ATTR = "_nija_broker_independent_live_execution_v20260705a"
_IMPORT_LOCK = threading.Lock()
_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_PATCHED = False
_MONITOR_STARTED = False
_REENTRANT = threading.local()


def _truthy_value(value: Any) -> bool:
    return str(value or "").strip().lower() in _TRUTHY


def _falsey_value(value: Any) -> bool:
    return str(value or "").strip().lower() in _FALSEY


def _truthy(name: str, default: str = "") -> bool:
    return _truthy_value(os.environ.get(name, default))


def _csv_env(name: str, default: str = "") -> list[str]:
    raw = os.environ.get(name, default) or ""
    return [_normalise_broker_name(item) for item in raw.split(",") if item.strip()]


def _normalise_broker_name(value: Any) -> str:
    raw = getattr(value, "value", value)
    text = str(raw or "").strip().lower()
    if not text:
        return ""
    for key in ("okx", "coinbase", "kraken", "alpaca", "binance"):
        if key in text:
            return key
    return text


def _broker_key_from_obj(obj: Any) -> str:
    if obj is None:
        return "unknown"
    for attr in ("broker_type", "name", "broker_name", "exchange", "exchange_name", "id"):
        try:
            key = _normalise_broker_name(getattr(obj, attr, None))
            if key:
                return key
        except Exception:
            pass
    try:
        cls_name = type(obj).__name__.lower()
        for key in ("okx", "coinbase", "kraken", "alpaca", "binance"):
            if key in cls_name:
                return key
    except Exception:
        pass
    return "unknown"


def _apply_defaults() -> None:
    """Default live execution to independent broker passes.

    This intentionally does not merge broker capital.  Each broker is scanned and
    sized from its own broker object/balance path.  A low Kraken free-quote
    balance therefore cannot suppress Coinbase or OKX execution.
    """
    os.environ.setdefault("NIJA_BROKER_INDEPENDENT_LIVE_EXECUTION", "true")
    os.environ.setdefault("NIJA_INDEPENDENT_BROKER_TRADING", "true")
    os.environ.setdefault("NIJA_INDEPENDENT_USER_TRADING", "true")
    os.environ.setdefault("NIJA_COPY_TRADE_ENABLED", "false")
    os.environ.setdefault("NIJA_MASTER_SIGNAL_ONLY", "true")
    os.environ.setdefault("NIJA_BROKER_SCOPED_POSITION_CAP", "true")
    os.environ.setdefault("NIJA_BROKER_SCOPED_ZERO_SIGNAL_STREAK", "true")
    os.environ.setdefault("NIJA_ALLOWED_EXECUTION_BROKERS", "okx,coinbase,kraken")
    os.environ.setdefault("NIJA_ENTRY_BROKER_PRIORITY", "okx,coinbase,kraken")
    os.environ.setdefault("NIJA_BROKER_PRIORITY", "okx,coinbase,kraken")
    # User explicitly requested OKX live routing with Coinbase and Kraken.
    # These flags also satisfy execution_route_integrity_patch._okx_execution_enabled().
    os.environ.setdefault("NIJA_OKX_EXECUTION_ENABLED", "true")
    os.environ.setdefault("NIJA_OKX_LIVE_TRADING_ENABLED", "true")
    os.environ.setdefault("OKX_LIVE_TRADING_ENABLED", "true")


def _broker_enabled(name: str) -> bool:
    key = _normalise_broker_name(name)
    if not key or key == "unknown":
        return False
    disabled = set(_csv_env("NIJA_DISABLED_BROKERS", ""))
    if key in disabled:
        return False
    allowed = _csv_env("NIJA_ALLOWED_EXECUTION_BROKERS", "okx,coinbase,kraken")
    return not allowed or key in allowed


def _broker_is_connected_or_ready(broker: Any) -> bool:
    if broker is None:
        return False
    for attr in ("is_ready_for_trading", "is_ready_for_capital", "is_available"):
        try:
            fn = getattr(broker, attr, None)
            if callable(fn) and bool(fn()):
                return True
        except Exception:
            pass
    for attr in ("connected", "_is_available", "available", "is_connected"):
        try:
            value = getattr(broker, attr, None)
            if callable(value):
                value = value()
            if bool(value):
                return True
        except Exception:
            pass
    # Some patched broker adapters do not expose connected but do expose balance
    # and candle/order methods.  Keep them eligible; the broker call will fail
    # independently if that venue is actually offline.
    return True


def _collect_candidate_brokers(apex: Any, explicit_broker: Any = None) -> dict[str, Any]:
    candidates: dict[str, Any] = {}

    def add(raw_key: Any, broker: Any) -> None:
        if broker is None:
            return
        key = _broker_key_from_obj(broker)
        if key == "unknown":
            key = _normalise_broker_name(raw_key)
        if key and key != "unknown" and _broker_enabled(key):
            candidates[key] = broker

    add("explicit", explicit_broker)
    for attr in ("broker_client", "broker", "active_broker"):
        add(attr, getattr(apex, attr, None))

    for container_attr in ("broker_manager", "multi_account_manager", "multi_account_broker_manager"):
        manager = getattr(apex, container_attr, None)
        if manager is None:
            continue
        for mapping_attr in ("platform_brokers", "brokers", "GLOBAL_PLATFORM_BROKERS"):
            try:
                mapping = getattr(manager, mapping_attr, {}) or {}
                if isinstance(mapping, dict):
                    for raw_key, broker in mapping.items():
                        add(raw_key, broker)
            except Exception:
                continue
        for attr in ("active_broker", "broker", "broker_client"):
            add(attr, getattr(manager, attr, None))

    # Last resort: read global platform broker registry from broker_manager.
    for module_name in ("bot.broker_manager", "broker_manager"):
        bm = sys.modules.get(module_name)
        if bm is None:
            continue
        try:
            registry = getattr(bm, "_PLATFORM_BROKER_INSTANCES", {}) or {}
            if isinstance(registry, dict):
                for raw_key, broker in registry.items():
                    add(raw_key, broker)
        except Exception:
            pass
        try:
            registry = getattr(bm, "GLOBAL_PLATFORM_BROKERS", {}) or {}
            if isinstance(registry, dict):
                for raw_key, broker in registry.items():
                    add(raw_key, broker)
        except Exception:
            pass

    return candidates


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return default


def _mapping_cash_value(mapping: dict[Any, Any]) -> float:
    cash_keys = (
        "usd", "usdt", "usdc", "zusd", "zUSD", "USD", "USDT", "USDC",
        "available_usd", "available_usdt", "available_usdc",
        "usd_available", "usdt_available", "usdc_available",
        "cash", "free_cash", "quote_cash", "free_quote", "trading_balance",
    )
    total = 0.0
    for key in cash_keys:
        if key in mapping:
            total += max(0.0, _safe_float(mapping.get(key), 0.0))
    if total > 0.0:
        return total
    for nested in mapping.values():
        if isinstance(nested, dict):
            total += _mapping_cash_value(nested)
    return total


def _broker_entry_balance(name: str, broker: Any, fallback: float) -> float:
    """Return broker-local entry capital, preferring free quote cash.

    This avoids the observed Kraken issue where total portfolio equity was
    healthy but free USD/USDT was below the order floor.  Coinbase and OKX are
    evaluated from their own broker object instead of the aggregate CA balance.
    """
    for attr in ("balance_cache", "_balance_cache", "last_balance_payload", "_last_balance_payload", "raw_balances", "_raw_balances"):
        try:
            payload = getattr(broker, attr, None)
            if isinstance(payload, dict):
                cash = _mapping_cash_value(payload)
                if cash > 0.0:
                    return cash
        except Exception:
            pass

    for method_name in ("get_available_cash", "get_available_quote_cash", "get_cash_balance", "get_usd_balance"):
        method = getattr(broker, method_name, None)
        if not callable(method):
            continue
        for args in (("USD",), tuple()):
            try:
                value = method(*args)
                if isinstance(value, dict):
                    cash = _mapping_cash_value(value)
                    if cash > 0.0:
                        return cash
                cash = _safe_float(value, 0.0)
                if cash > 0.0:
                    return cash
            except TypeError:
                continue
            except Exception:
                break

    for method_name in ("get_balance", "get_account_balance", "fetch_balance"):
        method = getattr(broker, method_name, None)
        if not callable(method):
            continue
        try:
            value = method()
            if isinstance(value, dict):
                cash = _mapping_cash_value(value)
                if cash > 0.0:
                    return cash
                for key in ("total_balance", "balance", "equity", "total_usd", "total", "total_funds"):
                    if key in value and _safe_float(value.get(key), 0.0) > 0.0:
                        return _safe_float(value.get(key), 0.0)
            scalar = _safe_float(value, 0.0)
            if scalar > 0.0:
                return scalar
        except Exception as exc:
            logger.debug("%s balance method %s failed: %s", name, method_name, exc)

    for attr in ("available_usd", "usd", "cash", "trading_balance", "_last_known_balance", "last_known_balance", "cached_balance", "last_balance"):
        try:
            value = getattr(broker, attr, None)
            if isinstance(value, dict):
                cash = _mapping_cash_value(value)
                if cash > 0.0:
                    return cash
            scalar = _safe_float(value, 0.0)
            if scalar > 0.0:
                return scalar
        except Exception:
            pass

    return max(0.0, _safe_float(fallback, 0.0))


def _broker_position_count(broker: Any, fallback: int = 0) -> int:
    if not _truthy("NIJA_BROKER_SCOPED_POSITION_CAP", "true"):
        return max(0, int(fallback or 0))
    for attr in ("open_positions", "positions", "cached_positions", "_open_positions"):
        try:
            value = getattr(broker, attr, None)
            if isinstance(value, dict):
                return len([v for v in value.values() if v])
            if isinstance(value, (list, tuple, set)):
                return len(value)
        except Exception:
            pass
    for method_name in ("get_open_positions", "get_positions"):
        method = getattr(broker, method_name, None)
        if not callable(method):
            continue
        try:
            value = method()
            if isinstance(value, dict):
                return len([v for v in value.values() if v])
            if isinstance(value, (list, tuple, set)):
                return len(value)
        except Exception:
            pass
    return 0


def _set_apex_broker_context(apex: Any, name: str, broker: Any) -> dict[str, Any]:
    old: dict[str, Any] = {"env_selected": os.environ.get("NIJA_SELECTED_EXECUTION_BROKER")}
    for attr in ("broker_client", "broker", "active_broker", "_nija_selected_execution_broker", "_nija_execution_route_broker"):
        try:
            old[attr] = getattr(apex, attr, None)
        except Exception:
            pass
    for attr in ("broker_client", "broker", "active_broker"):
        try:
            setattr(apex, attr, broker)
        except Exception:
            pass
    for attr in ("_nija_selected_execution_broker", "_nija_execution_route_broker"):
        try:
            setattr(apex, attr, name)
        except Exception:
            pass
    os.environ["NIJA_SELECTED_EXECUTION_BROKER"] = name
    os.environ["NIJA_PRIMARY_EXECUTION_BROKER"] = name
    try:
        manager = getattr(apex, "broker_manager", None)
        if manager is not None:
            old["manager_active_broker"] = getattr(manager, "active_broker", None)
            manager.active_broker = broker
    except Exception:
        pass
    return old


def _restore_apex_broker_context(apex: Any, old: dict[str, Any]) -> None:
    for attr in ("broker_client", "broker", "active_broker", "_nija_selected_execution_broker", "_nija_execution_route_broker"):
        if attr in old:
            try:
                setattr(apex, attr, old[attr])
            except Exception:
                pass
    if old.get("env_selected") is None:
        os.environ.pop("NIJA_SELECTED_EXECUTION_BROKER", None)
    else:
        os.environ["NIJA_SELECTED_EXECUTION_BROKER"] = str(old.get("env_selected") or "")
    try:
        manager = getattr(apex, "broker_manager", None)
        if manager is not None and "manager_active_broker" in old:
            manager.active_broker = old["manager_active_broker"]
    except Exception:
        pass


def _result_like(module: ModuleType, base: Any, **updates: Any) -> Any:
    cls = getattr(module, "CoreLoopResult", None)
    if callable(cls):
        result = cls()
    else:
        result = base
    for key, value in updates.items():
        try:
            setattr(result, key, value)
        except Exception:
            pass
    return result


def _patch_core_loop_module(module: ModuleType) -> bool:
    global _PATCHED
    cls = getattr(module, "NijaCoreLoop", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "run_scan_phase", None)
    if not callable(original):
        return False
    if getattr(original, _WRAP_ATTR, False):
        _PATCHED = True
        return True

    def _independent_run_scan_phase(
        self: Any,
        broker: Any,
        balance: float,
        symbols: list[str],
        open_positions_count: int = 0,
        user_mode: bool = False,
    ) -> Any:
        if getattr(_REENTRANT, "active", False) or not _truthy("NIJA_BROKER_INDEPENDENT_LIVE_EXECUTION", "true"):
            return original(self, broker, balance, symbols, open_positions_count, user_mode)

        apex = getattr(self, "apex", None)
        candidates = _collect_candidate_brokers(apex, broker)
        priority = _csv_env("NIJA_BROKER_PRIORITY", "okx,coinbase,kraken")
        names = [name for name in priority if name in candidates] + sorted(set(candidates) - set(priority))
        selected = [(name, candidates[name]) for name in names if _broker_enabled(name) and _broker_is_connected_or_ready(candidates[name])]

        if len(selected) <= 1:
            return original(self, broker, balance, symbols, open_positions_count, user_mode)

        logger.critical(
            "BROKER_INDEPENDENT_SCAN_START marker=20260705a brokers=%s symbols=%d caller_balance=%.2f user_mode=%s",
            ",".join(name for name, _ in selected),
            len(symbols or []),
            _safe_float(balance),
            user_mode,
        )
        print(
            f"[NIJA-PRINT] BROKER_INDEPENDENT_SCAN_START marker=20260705a brokers={','.join(name for name, _ in selected)} symbols={len(symbols or [])}",
            flush=True,
        )

        totals = {"entries_taken": 0, "entries_blocked": 0, "symbols_scored": 0, "exits_taken": 0, "errors": []}
        next_interval = None
        first_result = None
        broker_streaks = getattr(self, "_nija_broker_zero_signal_streaks", None)
        if not isinstance(broker_streaks, dict):
            broker_streaks = {}
            try:
                setattr(self, "_nija_broker_zero_signal_streaks", broker_streaks)
            except Exception:
                pass

        previous_global_streak = int(getattr(self, "_zero_signal_streak", 0) or 0)
        _REENTRANT.active = True
        try:
            for name, broker_obj in selected:
                broker_balance = _broker_entry_balance(name, broker_obj, balance)
                broker_open = _broker_position_count(broker_obj, 0)
                if _truthy("NIJA_BROKER_SCOPED_ZERO_SIGNAL_STREAK", "true"):
                    try:
                        setattr(self, "_zero_signal_streak", int(broker_streaks.get(name, 0) or 0))
                    except Exception:
                        pass
                old_context = _set_apex_broker_context(apex, name, broker_obj) if apex is not None else {}
                try:
                    logger.critical(
                        "BROKER_INDEPENDENT_SCAN_BROKER_START marker=20260705a broker=%s balance=%.2f open_positions=%d symbols=%d",
                        name,
                        broker_balance,
                        broker_open,
                        len(symbols or []),
                    )
                    result = original(self, broker_obj, broker_balance, symbols, broker_open, user_mode)
                    first_result = first_result or result
                    entries = int(getattr(result, "entries_taken", 0) or 0)
                    blocked = int(getattr(result, "entries_blocked", 0) or 0)
                    scored = int(getattr(result, "symbols_scored", 0) or 0)
                    exits = int(getattr(result, "exits_taken", 0) or 0)
                    totals["entries_taken"] += entries
                    totals["entries_blocked"] += blocked
                    totals["symbols_scored"] += scored
                    totals["exits_taken"] += exits
                    try:
                        totals["errors"].extend(list(getattr(result, "errors", []) or []))
                    except Exception:
                        pass
                    ni = getattr(result, "next_interval", None)
                    if ni is not None:
                        next_interval = ni if next_interval is None else min(next_interval, ni)
                    broker_streaks[name] = int(getattr(self, "_zero_signal_streak", 0) or 0)
                    logger.critical(
                        "BROKER_INDEPENDENT_SCAN_BROKER_END marker=20260705a broker=%s entries=%d blocked=%d scored=%d broker_streak=%s",
                        name,
                        entries,
                        blocked,
                        scored,
                        broker_streaks.get(name),
                    )
                except Exception as exc:
                    totals["entries_blocked"] += 1
                    totals["errors"].append(f"{name}:{exc}")
                    logger.exception("BROKER_INDEPENDENT_SCAN_BROKER_EXCEPTION marker=20260705a broker=%s error=%s", name, exc)
                finally:
                    if apex is not None:
                        _restore_apex_broker_context(apex, old_context)
        finally:
            _REENTRANT.active = False
            try:
                # Preserve the worst per-broker starvation streak for diagnostics
                # without letting one broker's state suppress another broker pass.
                setattr(self, "_zero_signal_streak", max([previous_global_streak] + [int(v or 0) for v in broker_streaks.values()]))
            except Exception:
                pass

        logger.critical(
            "BROKER_INDEPENDENT_SCAN_END marker=20260705a brokers=%s entries=%d blocked=%d scored=%d",
            ",".join(name for name, _ in selected),
            totals["entries_taken"],
            totals["entries_blocked"],
            totals["symbols_scored"],
        )
        print(
            f"[NIJA-PRINT] BROKER_INDEPENDENT_SCAN_END marker=20260705a entries={totals['entries_taken']} blocked={totals['entries_blocked']} scored={totals['symbols_scored']}",
            flush=True,
        )
        return _result_like(
            module,
            first_result,
            entries_taken=totals["entries_taken"],
            entries_blocked=totals["entries_blocked"],
            symbols_scored=totals["symbols_scored"],
            exits_taken=totals["exits_taken"],
            errors=totals["errors"],
            next_interval=next_interval if next_interval is not None else 150,
        )

    setattr(_independent_run_scan_phase, _WRAP_ATTR, True)
    setattr(cls, "run_scan_phase", _independent_run_scan_phase)
    _PATCHED = True
    logger.warning("%s core_loop_module=%s", _MARKER, getattr(module, "__name__", "<unknown>"))
    print("[NIJA-PRINT] BROKER_INDEPENDENT_LIVE_EXECUTION_PATCHED marker=20260705a", flush=True)
    return True


def _install_on_module(name: str, module: ModuleType) -> bool:
    if name in {"bot.nija_core_loop", "nija_core_loop"}:
        return _patch_core_loop_module(module)
    return False


def _try_patch_loaded() -> bool:
    patched = False
    for name in ("bot.nija_core_loop", "nija_core_loop"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _install_on_module(name, module) or patched
    return patched


def _start_monitor() -> None:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return
    _MONITOR_STARTED = True

    def _monitor() -> None:
        deadline = time.time() + float(os.environ.get("NIJA_BROKER_INDEPENDENT_PATCH_MONITOR_SECONDS", "240") or "240")
        while time.time() < deadline:
            if _try_patch_loaded() or _PATCHED:
                return
            time.sleep(1.0)
        logger.warning("BROKER_INDEPENDENT_MONITOR_EXPIRED marker=20260705a patched=%s", _PATCHED)

    threading.Thread(target=_monitor, name="broker-independent-live-execution-monitor", daemon=True).start()
    logger.warning("BROKER_INDEPENDENT_MONITOR_STARTED marker=20260705a")


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    with _IMPORT_LOCK:
        _apply_defaults()
        logger.warning(
            "%s install_start=True independent=%s allowed=%s priority=%s",
            _MARKER,
            os.environ.get("NIJA_BROKER_INDEPENDENT_LIVE_EXECUTION"),
            _csv_env("NIJA_ALLOWED_EXECUTION_BROKERS", "okx,coinbase,kraken"),
            _csv_env("NIJA_BROKER_PRIORITY", "okx,coinbase,kraken"),
        )
        _try_patch_loaded()
        _start_monitor()
        if _ORIGINAL_IMPORT_MODULE is not None:
            return
        _ORIGINAL_IMPORT_MODULE = importlib.import_module

        def _wrapped_import_module(name: str, package: str | None = None):
            module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
            if name in {"bot.nija_core_loop", "nija_core_loop"}:
                _install_on_module(name, module)
            return module

        importlib.import_module = _wrapped_import_module  # type: ignore[assignment]


def install() -> None:
    install_import_hook()
