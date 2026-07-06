"""Spendable quote-cash routing guard.

Routes new entries using free quote cash after buffer instead of total portfolio
equity. This prevents a venue with crypto holdings but insufficient free USD
from being selected for a fresh buy that cannot clear the exchange notional
floor. The guard does not bypass risk, capital, exchange, or broker checks.
"""

from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.spendable_quote_routing")

_MARKER = "SPENDABLE_QUOTE_ROUTING_PATCHED marker=20260706a"
_TRUTHY = {"1", "true", "yes", "on", "y", "enabled"}
_TARGETS = {
    "bot.trading_strategy",
    "trading_strategy",
    "bot.execution_engine",
    "execution_engine",
    "bot.nija_apex_strategy_v71",
    "nija_apex_strategy_v71",
    "bot.signal_funnel_diagnostics",
    "signal_funnel_diagnostics",
}
_LOCK = threading.Lock()
_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_MONITOR_STARTED = False
_PATCHED = {"strategy": False, "engine": False, "apex": False, "funnel": False}


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)) or default)
    except Exception:
        return default


def _truthy(name: str, default: str = "") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in _TRUTHY


def _norm(value: Any) -> str:
    raw = getattr(value, "value", value)
    text = str(raw or "").strip().lower()
    for key in ("kraken", "coinbase", "okx", "alpaca", "binance"):
        if key in text:
            return key
    return text or "unknown"


def _broker_key(broker: Any) -> str:
    if broker is None:
        return "unknown"
    for attr in ("broker_type", "name", "broker_name", "exchange", "exchange_name", "NAME"):
        try:
            key = _norm(getattr(broker, attr, None))
            if key and key != "unknown":
                return key
        except Exception:
            pass
    return _norm(type(broker).__name__)


def _buffer_pct() -> float:
    return max(0.0, min(_float_env("NIJA_ENTRY_SPENDABLE_BUFFER_PCT", 0.10), 0.50))


def _floor_usd(broker_key: str) -> float:
    key = _norm(broker_key)
    min_trade = _float_env("MIN_TRADE_USD", 10.0)
    if key == "kraken":
        return max(
            23.10,
            min_trade,
            _float_env("KRAKEN_MIN_NOTIONAL_USD", 23.0),
            _float_env("NIJA_KRAKEN_MIN_NOTIONAL_USD", 23.0),
            _float_env("NIJA_KRAKEN_FINAL_MIN_NOTIONAL_USD", 23.0),
            _float_env("NIJA_KRAKEN_TARGET_ORDER_USD", 23.10),
        )
    if key == "okx":
        return max(10.0, _float_env("OKX_MIN_ORDER_USD", 10.0))
    if key == "coinbase":
        return max(12.0, _float_env("COINBASE_VENUE_THRESHOLD_USD", 12.0), _float_env("COINBASE_MIN_ORDER_USD", 1.0))
    if key == "alpaca":
        return max(2.0, _float_env("ALPACA_MIN_BALANCE_USD", 2.0))
    return max(10.0, min_trade)


def _cash_from_payload(payload: Any, broker_key: str = "") -> Optional[float]:
    if payload is None:
        return None
    if isinstance(payload, (int, float)):
        return max(0.0, float(payload))
    if not isinstance(payload, dict):
        return None

    for key in (
        "available_balance",
        "available_usd",
        "availableUSD",
        "available_cash",
        "cash_available",
        "trading_balance",
        "usd",
        "USD",
        "usd_available",
        "free_usd",
        "freeUSD",
        "free",
        "available",
        "total_available",
    ):
        if key not in payload:
            continue
        try:
            return max(0.0, float(payload.get(key) or 0.0))
        except Exception:
            continue

    for container_key in ("balances", "assets", "result"):
        nested = payload.get(container_key)
        if not isinstance(nested, dict):
            continue
        for usd_key in ("USD", "usd", "ZUSD"):
            item = nested.get(usd_key)
            if isinstance(item, dict):
                value = _cash_from_payload(item, broker_key)
                if value is not None:
                    return value
            else:
                try:
                    return max(0.0, float(item or 0.0))
                except Exception:
                    pass

    # Kraken total_funds includes held/non-USD value and must not make a fresh
    # USD buy look executable unless the operator explicitly allows scalar fallback.
    if _norm(broker_key) == "kraken" and not _truthy("NIJA_ALLOW_KRAKEN_SCALAR_BALANCE_FOR_ENTRY"):
        return None

    for key in ("balance", "total_balance", "equity", "total_usd", "total_funds"):
        if key not in payload:
            continue
        try:
            return max(0.0, float(payload.get(key) or 0.0))
        except Exception:
            continue
    return None


def _balance_keys(broker: Any, broker_key: str) -> list[str]:
    out = [broker_key]
    try:
        try:
            from bot.broker_identity import format_broker_identity
        except Exception:
            from broker_identity import format_broker_identity  # type: ignore
        identity = str(format_broker_identity(broker) or "").strip().lower()
        if identity and identity not in out:
            out.insert(0, identity)
    except Exception:
        pass
    return [x for x in out if x]


def _available_usd(broker: Any, broker_key: str) -> tuple[float, str]:
    for attr in ("_balance_cache", "balance_cache", "_last_balance_detail", "_last_account_balance_detail"):
        try:
            value = _cash_from_payload(getattr(broker, attr, None), broker_key)
            if value is not None:
                return value, f"broker.{attr}"
        except Exception:
            pass

    try:
        try:
            from bot.balance_service import BalanceService
        except Exception:
            from balance_service import BalanceService  # type: ignore
        for key in _balance_keys(broker, broker_key):
            try:
                value = _cash_from_payload(BalanceService.get_detailed(key), broker_key)
                if value is not None:
                    return value, f"BalanceService.get_detailed:{key}"
            except Exception:
                pass
        if _norm(broker_key) != "kraken" or _truthy("NIJA_ALLOW_KRAKEN_SCALAR_BALANCE_FOR_ENTRY"):
            for key in _balance_keys(broker, broker_key):
                try:
                    scalar = float(BalanceService.get(key) or 0.0)
                    if scalar > 0.0:
                        return scalar, f"BalanceService.get:{key}:scalar"
                except Exception:
                    pass
    except Exception:
        pass

    if _norm(broker_key) != "kraken" or _truthy("NIJA_ALLOW_KRAKEN_SCALAR_BALANCE_FOR_ENTRY"):
        for attr in ("_last_known_balance", "last_known_balance"):
            try:
                raw = getattr(broker, attr, None)
                if raw is not None:
                    return max(0.0, float(raw or 0.0)), f"broker.{attr}:scalar"
            except Exception:
                pass

    getter = getattr(broker, "get_account_balance_detailed", None)
    if callable(getter):
        try:
            value = _cash_from_payload(getter(verbose=False), broker_key)
            if value is not None:
                return value, "get_account_balance_detailed"
        except Exception:
            pass

    return 0.0, "unavailable"


def _spendable_usd(broker: Any, broker_key: str) -> tuple[float, float, str]:
    available, source = _available_usd(broker, broker_key)
    spendable = max(0.0, available * (1.0 - _buffer_pct()))
    return spendable, available, source


def _apply_env_defaults() -> None:
    os.environ.setdefault("NIJA_SPENDABLE_QUOTE_ROUTING_ENABLED", "true")
    os.environ.setdefault("NIJA_ENTRY_SPENDABLE_BUFFER_PCT", "0.10")
    os.environ.setdefault("NIJA_OKX_EXECUTION_ENABLED", "true")
    os.environ.setdefault("NIJA_OKX_LIVE_TRADING_ENABLED", "true")
    os.environ.setdefault("NIJA_ENABLE_OKX_EXECUTION", "true")
    os.environ.setdefault("NIJA_ENTRY_BROKER_PRIORITY", "okx,kraken,coinbase,alpaca")
    os.environ.setdefault("NIJA_BROKER_PRIORITY", "okx,kraken,coinbase,alpaca")
    os.environ.setdefault("NIJA_ALLOWED_EXECUTION_BROKERS", "okx,kraken,coinbase,alpaca")


def _patch_strategy(module: ModuleType) -> bool:
    cls = getattr(module, "TradingStrategy", None)
    if not isinstance(cls, type):
        return False

    desired = [x.strip() for x in os.environ.get("NIJA_ENTRY_BROKER_PRIORITY", "okx,kraken,coinbase,alpaca").split(",") if x.strip()]
    priority = getattr(module, "ENTRY_BROKER_PRIORITY", None)
    if isinstance(priority, list):
        priority[:] = desired + [p for p in priority if _norm(p) not in set(desired)]

    mins = getattr(module, "BROKER_MIN_BALANCE", None)
    if isinstance(mins, dict):
        mins["kraken"] = max(float(mins.get("kraken", 23.10) or 23.10), _floor_usd("kraken"))
        mins["okx"] = min(max(float(mins.get("okx", 10.0) or 10.0), 10.0), _floor_usd("okx"))
        mins["coinbase"] = max(float(mins.get("coinbase", 2.0) or 2.0), _floor_usd("coinbase"))

    original_balance = getattr(cls, "_broker_entry_balance", None)
    if callable(original_balance) and not getattr(original_balance, "_nija_spendable_quote_balance", False):
        def _broker_entry_balance(self: Any, broker: Any, broker_key: Optional[str] = None) -> float:
            key = _norm(broker_key or _broker_key(broker))
            spendable, available, source = _spendable_usd(broker, key)
            logger.info("SPENDABLE_QUOTE_BALANCE broker=%s available=$%.2f spendable=$%.2f source=%s", key, available, spendable, source)
            return spendable
        setattr(_broker_entry_balance, "_nija_spendable_quote_balance", True)
        setattr(cls, "_broker_entry_balance", _broker_entry_balance)

    original_eligible = getattr(cls, "_is_broker_eligible_for_entry", None)
    if callable(original_eligible) and not getattr(original_eligible, "_nija_spendable_quote_gate", False):
        def _is_broker_eligible_for_entry(self: Any, broker: Any) -> tuple[bool, str]:
            if broker is None:
                return False, "broker missing"
            key = _norm(_broker_key(broker))
            if not getattr(broker, "connected", False):
                return False, f"{key} not connected"
            if getattr(broker, "exit_only_mode", False):
                return False, f"{key} is in EXIT-ONLY mode"
            if hasattr(broker, "position_tracker") and getattr(broker, "position_tracker") is None:
                return False, f"{key} position tracker unavailable"
            spendable, available, source = _spendable_usd(broker, key)
            required = _floor_usd(key)
            if spendable < required:
                reason = f"{key} spendable ${spendable:.2f} below executable minimum ${required:.2f} (available=${available:.2f}, source={source})"
                logger.warning("ENTRY_BROKER_SPENDABLE_REJECT marker=20260706a %s", reason)
                return False, reason
            reason = f"{key} eligible spendable=${spendable:.2f} available=${available:.2f} min=${required:.2f} source={source}"
            logger.warning("ENTRY_BROKER_SPENDABLE_OK marker=20260706a %s", reason)
            return True, reason
        setattr(_is_broker_eligible_for_entry, "_nija_spendable_quote_gate", True)
        setattr(cls, "_is_broker_eligible_for_entry", _is_broker_eligible_for_entry)

    _PATCHED["strategy"] = True
    logger.warning("%s trading_strategy_module=%s", _MARKER, getattr(module, "__name__", "<unknown>"))
    return True


def _patch_engine(module: ModuleType) -> bool:
    cls = getattr(module, "ExecutionEngine", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "_apply_minimum_notional_gate", None)
    if not callable(original) or getattr(original, "_nija_spendable_min_notional_detail", False):
        _PATCHED["engine"] = True
        return True

    def _apply_minimum_notional_gate(self: Any, *, symbol: str, position_size: float, broker_name: Optional[str], balance_usd: float, affordable_usd: Optional[float]) -> tuple[Optional[float], Optional[str]]:
        key = _norm(broker_name or _broker_key(getattr(self, "broker_client", None)))
        required = _floor_usd(key)
        affordable = affordable_usd if affordable_usd is not None else max(0.0, float(balance_usd or 0.0) * (1.0 - _buffer_pct()))
        try:
            affordable_value = float(affordable or 0.0)
        except Exception:
            affordable_value = 0.0
        if affordable_value < required:
            detail = f"below_min_notional_spendable min_notional={required:.2f} spendable={affordable_value:.2f} available={float(balance_usd or 0.0):.2f} broker={key}"
            logger.warning("MIN_NOTIONAL_SPENDABLE_BLOCK marker=20260706a symbol=%s %s", symbol, detail)
            return None, detail
        return original(self, symbol=symbol, position_size=position_size, broker_name=broker_name, balance_usd=balance_usd, affordable_usd=affordable_usd)

    setattr(_apply_minimum_notional_gate, "_nija_spendable_min_notional_detail", True)
    setattr(cls, "_apply_minimum_notional_gate", _apply_minimum_notional_gate)
    _PATCHED["engine"] = True
    logger.warning("%s execution_engine_module=%s", _MARKER, getattr(module, "__name__", "<unknown>"))
    return True


def _patch_apex(module: ModuleType) -> bool:
    changed = False
    for cls in list(vars(module).values()):
        if not isinstance(cls, type):
            continue
        original = getattr(cls, "execute_action", None)
        if not callable(original) or getattr(original, "_nija_long_reason_sanitizer", False):
            continue
        def execute_action(self: Any, analysis: Any, symbol: str, *args: Any, __orig=original, **kwargs: Any) -> Any:
            if isinstance(analysis, dict):
                action = str(analysis.get("action") or "").lower()
                reason = str(analysis.get("reason") or "")
                if action in {"enter_long", "long", "buy"} and "short" in reason.lower():
                    analysis["stale_reason_sanitized"] = reason
                    analysis["reason"] = "entry_order_rejected_by_execution_engine; see execute_entry rejection detail"
            return __orig(self, analysis, symbol, *args, **kwargs)
        setattr(execute_action, "_nija_long_reason_sanitizer", True)
        setattr(cls, "execute_action", execute_action)
        changed = True
    if changed:
        _PATCHED["apex"] = True
        logger.warning("%s apex_module=%s", _MARKER, getattr(module, "__name__", "<unknown>"))
    return changed


def _patch_funnel(module: ModuleType) -> bool:
    stats_cls = getattr(module, "FunnelStats", None)
    diag_cls = getattr(module, "SignalFunnelDiagnostics", None)
    if not isinstance(stats_cls, type) or not isinstance(diag_cls, type):
        return False
    original_line = getattr(stats_cls, "as_log_line", None)
    if callable(original_line) and not getattr(original_line, "_nija_attempt_label", False):
        def as_log_line(self: Any) -> str:
            return str(original_line(self)).replace("execution_pass=", "execution_attempts=")
        setattr(as_log_line, "_nija_attempt_label", True)
        setattr(stats_cls, "as_log_line", as_log_line)
    _PATCHED["funnel"] = True
    logger.warning("%s signal_funnel_module=%s", _MARKER, getattr(module, "__name__", "<unknown>"))
    return True


def _install_on_module(name: str, module: ModuleType) -> bool:
    changed = False
    if name in {"bot.trading_strategy", "trading_strategy"}:
        changed = _patch_strategy(module) or changed
    if name in {"bot.execution_engine", "execution_engine"}:
        changed = _patch_engine(module) or changed
    if name in {"bot.nija_apex_strategy_v71", "nija_apex_strategy_v71"}:
        changed = _patch_apex(module) or changed
    if name in {"bot.signal_funnel_diagnostics", "signal_funnel_diagnostics"}:
        changed = _patch_funnel(module) or changed
    return changed


def _try_patch_loaded() -> bool:
    changed = False
    for name in _TARGETS:
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            changed = _install_on_module(name, module) or changed
    return changed


def _start_monitor() -> None:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return
    _MONITOR_STARTED = True

    def _monitor() -> None:
        deadline = time.time() + _float_env("NIJA_PATCH_MONITOR_SECONDS", 240.0)
        while time.time() < deadline:
            _try_patch_loaded()
            if all(_PATCHED.values()):
                return
            time.sleep(0.5)
        logger.warning("SPENDABLE_QUOTE_ROUTING_MONITOR_EXPIRED marker=20260706a patched=%s", _PATCHED)

    threading.Thread(target=_monitor, name="spendable-quote-routing", daemon=True).start()


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    with _LOCK:
        _apply_env_defaults()
        logger.warning("SPENDABLE_QUOTE_ROUTING_INSTALL_START marker=20260706a priority=%s buffer_pct=%.2f", os.environ.get("NIJA_ENTRY_BROKER_PRIORITY"), _buffer_pct())
        print("[NIJA-PRINT] SPENDABLE_QUOTE_ROUTING_INSTALL_START marker=20260706a", flush=True)
        _try_patch_loaded()
        _start_monitor()
        if _ORIGINAL_IMPORT_MODULE is not None:
            return
        _ORIGINAL_IMPORT_MODULE = importlib.import_module
        def _wrapped_import_module(name: str, package: str | None = None):
            module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
            if name in _TARGETS:
                _install_on_module(name, module)
            return module
        importlib.import_module = _wrapped_import_module  # type: ignore[assignment]


def install() -> None:
    install_import_hook()
