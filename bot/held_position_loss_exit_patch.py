"""Adopt held exchange positions into loss-protection exit evaluation.

This patch targets the exact live-log problem where exchange-held positions were
visible but not fully managed by the runtime exit stack:

    ADOPTED_HELD_POSITION ... ledger=False tracker=False profit_exit=False runtime=False
    COINBASE_STARTUP_POSITION_SYNC positions=1 symbols=ADA-USD

It does not bypass broker, authority, or exchange checks. It only scans already
held broker positions, computes loss when cost basis/PnL is available, and asks
the broker to submit a normal sell/close order when the position breaches the
configured loss threshold.
"""

from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any, Iterable, Mapping, MutableMapping, Optional

logger = logging.getLogger("nija.held_position_loss_exit_patch")
_PATCHED_ATTR = "__nija_held_position_loss_exit_patch__"
_MONITOR_STARTED = False
_INSTALL_LOCK = threading.Lock()
_CASH = {"USD", "USDT", "USDC", "DAI", "EUR", "GBP"}


def _truthy(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on", "y", "enabled"}


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default) or default)
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        if isinstance(value, str):
            value = value.replace("$", "").replace(",", "").replace("%", "").strip()
            if not value:
                return default
        return float(value)
    except Exception:
        return default


def _broker_name(broker: Any) -> str:
    for attr in ("name", "broker_name", "exchange", "exchange_name", "broker_type"):
        try:
            value = getattr(broker, attr, None)
            raw = getattr(value, "value", value)
            if raw:
                return str(raw).strip().lower()
        except Exception:
            pass
    cls = type(broker).__name__.lower()
    for name in ("kraken", "coinbase", "okx", "binance", "alpaca"):
        if name in cls:
            return name
    return "unknown"


def _base(symbol: str) -> str:
    text = str(symbol or "").upper().replace("/", "-").replace("_", "-").replace(":", "-")
    if "-" in text:
        return text.split("-", 1)[0]
    for quote in ("USDT", "USDC", "USD", "EUR", "GBP"):
        if text.endswith(quote) and len(text) > len(quote):
            return text[: -len(quote)]
    return text


def _symbol_from_asset(asset: str) -> str:
    asset = str(asset or "").upper().strip()
    if not asset or asset in _CASH:
        return ""
    if "-" in asset or "/" in asset:
        return asset.replace("/", "-").upper()
    return f"{asset}-USD"


def _sequence(payload: Any) -> list[Any]:
    if payload is None:
        return []
    if isinstance(payload, Mapping):
        for key in ("positions", "open_positions", "holdings", "assets", "balances", "crypto", "crypto_balances"):
            value = payload.get(key)
            if isinstance(value, list):
                return list(value)
            if isinstance(value, Mapping):
                return [dict(v, asset=k, symbol=_symbol_from_asset(str(k))) if isinstance(v, Mapping) else {"asset": k, "quantity": v, "symbol": _symbol_from_asset(str(k))} for k, v in value.items()]
        rows = []
        for key, value in payload.items():
            if isinstance(value, Mapping):
                item = dict(value)
                item.setdefault("asset", key)
                item.setdefault("symbol", _symbol_from_asset(str(key)))
                rows.append(item)
        return rows
    if isinstance(payload, list):
        return list(payload)
    return []


def _extract_positions(broker: Any) -> list[Any]:
    payloads: list[Any] = []
    for method_name in ("get_open_positions", "get_positions", "get_spot_positions", "get_spot_holdings", "get_holdings", "fetch_positions", "get_account_balance", "get_portfolio_breakdown", "get_balances"):
        try:
            method = getattr(broker, method_name, None)
            if callable(method):
                try:
                    payload = method(verbose=False)
                except TypeError:
                    payload = method()
                payloads.extend(_sequence(payload))
        except Exception as exc:
            logger.debug("HELD_POSITION_EXIT_PROBE_SKIP method=%s err=%s", method_name, exc)
    for attr in ("open_positions", "positions", "_positions", "_open_positions", "holdings", "balances", "_last_raw_balances", "last_raw_balances", "_portfolio_breakdown", "portfolio_breakdown"):
        try:
            payloads.extend(_sequence(getattr(broker, attr, None)))
        except Exception:
            pass
    return payloads


def _price(broker: Any, symbol: str, fallback: float = 0.0) -> float:
    for method_name in ("get_last_price", "get_current_price", "get_market_price", "get_ticker_price", "get_price"):
        try:
            method = getattr(broker, method_name, None)
            if callable(method):
                value = method(symbol)
                if isinstance(value, Mapping):
                    for key in ("price", "last", "last_price", "mark", "close"):
                        px = _safe_float(value.get(key), 0.0)
                        if px > 0:
                            return px
                px = _safe_float(value, 0.0)
                if px > 0:
                    return px
        except Exception:
            pass
    return fallback


def _normalize(raw: Any, broker: Any) -> Optional[dict[str, Any]]:
    if not isinstance(raw, Mapping):
        raw = getattr(raw, "__dict__", None)
    if not isinstance(raw, Mapping):
        return None
    symbol = str(raw.get("symbol") or raw.get("pair") or raw.get("market") or raw.get("instrument") or "").upper().replace("/", "-")
    asset = str(raw.get("asset") or raw.get("currency") or _base(symbol) or "").upper()
    if not symbol:
        symbol = _symbol_from_asset(asset)
    if not asset:
        asset = _base(symbol)
    if not symbol or not asset or asset in _CASH:
        return None
    qty = 0.0
    for key in ("qty", "quantity", "amount", "size", "units", "balance", "total", "available", "free"):
        qty = _safe_float(raw.get(key), 0.0)
        if qty > 0:
            break
    if qty <= 0:
        return None
    current = 0.0
    for key in ("current_price", "mark_price", "last_price", "price"):
        current = _safe_float(raw.get(key), 0.0)
        if current > 0:
            break
    value = 0.0
    for key in ("market_value_usd", "value_usd", "usd_value", "notional", "market_value", "value", "size_usd"):
        value = _safe_float(raw.get(key), 0.0)
        if value > 0:
            break
    if current <= 0 and value > 0:
        current = value / qty
    if current <= 0:
        current = _price(broker, symbol, 0.0)
    if value <= 0 and current > 0:
        value = current * qty
    entry = 0.0
    for key in ("entry_price", "avg_entry_price", "average_price", "cost_basis_price", "cost_basis"):
        entry = _safe_float(raw.get(key), 0.0)
        if entry > 0:
            break
    pnl = 0.0
    pnl_known = False
    for key in ("unrealized_pnl", "unrealized_pnl_usd", "pnl", "profit_loss", "gain_loss"):
        if key in raw:
            pnl = _safe_float(raw.get(key), 0.0)
            pnl_known = True
            break
    pnl_pct = None
    for key in ("unrealized_pnl_pct", "pnl_pct", "profit_loss_pct", "gain_loss_pct"):
        if key in raw:
            pnl_pct = _safe_float(raw.get(key), 0.0)
            if abs(pnl_pct) > 1.0:
                pnl_pct = pnl_pct / 100.0
            pnl_known = True
            break
    if entry > 0 and current > 0:
        pnl = (current - entry) * qty
        pnl_pct = (current - entry) / entry
        pnl_known = True
    return {
        "symbol": symbol,
        "asset": asset,
        "qty": qty,
        "quantity": qty,
        "current_price": current,
        "entry_price": entry,
        "market_value_usd": value,
        "pnl_usd": pnl,
        "pnl_pct": pnl_pct,
        "pnl_known": pnl_known,
        "broker": _broker_name(broker),
        "source": str(raw.get("source") or raw.get("position_source") or "exchange_held"),
    }


def _loss_breached(pos: Mapping[str, Any]) -> tuple[bool, str]:
    if not bool(pos.get("pnl_known")):
        if _truthy("NIJA_EXIT_HELD_UNKNOWN_COST_BASIS", False):
            return True, "unknown_cost_basis_forced_by_env"
        return False, "pnl_unknown"
    max_loss_pct = -abs(_float_env("NIJA_HELD_POSITION_MAX_LOSS_PCT", 0.005))
    max_loss_usd = -abs(_float_env("NIJA_HELD_POSITION_MAX_LOSS_USD", 0.25))
    pnl_pct = pos.get("pnl_pct")
    pnl_usd = _safe_float(pos.get("pnl_usd"), 0.0)
    if pnl_pct is not None and _safe_float(pnl_pct, 0.0) <= max_loss_pct:
        return True, f"pnl_pct={_safe_float(pnl_pct):.4f} <= {max_loss_pct:.4f}"
    if pnl_usd <= max_loss_usd:
        return True, f"pnl_usd={pnl_usd:.2f} <= {max_loss_usd:.2f}"
    return False, f"not_negative_enough pnl_pct={pnl_pct} pnl_usd={pnl_usd:.2f}"


def _submit_exit(broker: Any, pos: Mapping[str, Any]) -> tuple[bool, str]:
    symbol = str(pos.get("symbol") or "")
    qty = _safe_float(pos.get("qty") or pos.get("quantity"), 0.0)
    if not symbol or qty <= 0:
        return False, "missing_symbol_or_qty"
    dry = _truthy("NIJA_HELD_POSITION_EXIT_DRY_RUN", False)
    if dry:
        return False, "dry_run_enabled"
    attempts = (
        ("close_position", (symbol,), {"quantity": qty}),
        ("exit_position", (symbol,), {"quantity": qty}),
        ("sell_position", (symbol,), {"quantity": qty}),
        ("market_sell", (symbol, qty), {}),
        ("sell", (symbol, qty), {}),
        ("place_market_order", (symbol, "sell", qty), {}),
        ("submit_market_order", (symbol, "sell", qty), {}),
        ("create_market_order", (symbol, "sell", qty), {}),
        ("place_order", (), {"symbol": symbol, "side": "sell", "quantity": qty, "order_type": "market"}),
        ("submit_order", (), {"symbol": symbol, "side": "sell", "quantity": qty, "order_type": "market"}),
        ("create_order", (), {"symbol": symbol, "side": "sell", "quantity": qty, "order_type": "market"}),
    )
    errors = []
    for method_name, args, kwargs in attempts:
        method = getattr(broker, method_name, None)
        if not callable(method):
            continue
        try:
            result = method(*args, **kwargs)
            logger.critical("HELD_POSITION_EXIT_ORDER_SUBMITTED broker=%s symbol=%s qty=%s method=%s result=%s", _broker_name(broker), symbol, qty, method_name, str(result)[:300])
            print(f"[NIJA-PRINT] HELD_POSITION_EXIT_ORDER_SUBMITTED | broker={_broker_name(broker)} symbol={symbol} qty={qty} method={method_name}", flush=True)
            return True, method_name
        except TypeError as exc:
            errors.append(f"{method_name}:type:{exc}")
            # Try common alternate positional order.
            try:
                result = method(symbol=symbol, side="sell", size=qty, type="market")
                logger.critical("HELD_POSITION_EXIT_ORDER_SUBMITTED broker=%s symbol=%s qty=%s method=%s_alt result=%s", _broker_name(broker), symbol, qty, method_name, str(result)[:300])
                print(f"[NIJA-PRINT] HELD_POSITION_EXIT_ORDER_SUBMITTED | broker={_broker_name(broker)} symbol={symbol} qty={qty} method={method_name}_alt", flush=True)
                return True, f"{method_name}_alt"
            except Exception as exc2:
                errors.append(f"{method_name}:alt:{exc2}")
        except Exception as exc:
            errors.append(f"{method_name}:{exc}")
    return False, "; ".join(errors[-5:]) or "no_supported_exit_method"


def _attach_runtime(core_loop: Any, pos: Mapping[str, Any]) -> bool:
    attached = False
    for owner in (core_loop, getattr(core_loop, "apex", None)):
        if owner is None:
            continue
        for attr in ("open_positions", "positions", "_open_positions", "tracked_positions", "_tracked_positions"):
            try:
                container = getattr(owner, attr, None)
                key = f"{pos.get('broker')}:{pos.get('symbol')}:exchange_held"
                if isinstance(container, MutableMapping):
                    container.setdefault(key, dict(pos, id=key, position_source="exchange_held", exit_managed=True))
                    attached = True
                elif isinstance(container, list):
                    if key not in {str((x or {}).get("id")) for x in container if isinstance(x, Mapping)}:
                        container.append(dict(pos, id=key, position_source="exchange_held", exit_managed=True))
                        attached = True
            except Exception:
                pass
    return attached


def _candidate_brokers(core_loop: Any, current_broker: Any = None) -> list[Any]:
    brokers: list[Any] = []
    if current_broker is not None:
        brokers.append(current_broker)
    for owner in (core_loop, getattr(core_loop, "apex", None), getattr(getattr(core_loop, "apex", None), "mabm", None), getattr(getattr(core_loop, "apex", None), "broker_manager", None)):
        if owner is None:
            continue
        for attr in ("platform_brokers", "user_brokers", "brokers", "_brokers", "broker_clients", "connected_brokers"):
            try:
                value = getattr(owner, attr, None)
                if isinstance(value, Mapping):
                    for broker in value.values():
                        if broker is not None and broker not in brokers:
                            brokers.append(broker)
                elif isinstance(value, (list, tuple, set)):
                    for broker in value:
                        if broker is not None and broker not in brokers:
                            brokers.append(broker)
            except Exception:
                pass
        for attr in ("broker", "broker_client", "primary_broker", "kraken_broker", "coinbase_broker", "okx_broker"):
            try:
                broker = getattr(owner, attr, None)
                if broker is not None and broker not in brokers:
                    brokers.append(broker)
            except Exception:
                pass
    return brokers


def _evaluate_held_position_exits(core_loop: Any, current_broker: Any = None) -> None:
    if not _truthy("NIJA_HELD_POSITION_LOSS_EXIT_ENABLED", True):
        return
    seen = getattr(core_loop, "__nija_held_position_exit_seen__", None)
    if not isinstance(seen, set):
        seen = set()
        setattr(core_loop, "__nija_held_position_exit_seen__", seen)
    cooldown = _float_env("NIJA_HELD_POSITION_EXIT_COOLDOWN_S", 20.0)
    now = time.time()
    last = _safe_float(getattr(core_loop, "__nija_held_position_exit_last_ts__", 0.0), 0.0)
    if cooldown > 0 and now - last < cooldown:
        return
    setattr(core_loop, "__nija_held_position_exit_last_ts__", now)
    for broker in _candidate_brokers(core_loop, current_broker):
        broker_name = _broker_name(broker)
        raw_positions = _extract_positions(broker)
        normalized = [p for p in (_normalize(raw, broker) for raw in raw_positions) if p]
        if normalized:
            logger.critical("HELD_POSITION_EXIT_SCAN broker=%s raw=%d normalized=%d", broker_name, len(raw_positions), len(normalized))
        for pos in normalized:
            key = f"{broker_name}:{pos.get('symbol')}:{pos.get('qty')}"
            _attach_runtime(core_loop, pos)
            breached, reason = _loss_breached(pos)
            logger.critical(
                "HELD_POSITION_EXIT_EVALUATED broker=%s symbol=%s qty=%s value=$%.2f pnl_usd=%.2f pnl_pct=%s breached=%s reason=%s",
                broker_name,
                pos.get("symbol"),
                pos.get("qty"),
                _safe_float(pos.get("market_value_usd"), 0.0),
                _safe_float(pos.get("pnl_usd"), 0.0),
                pos.get("pnl_pct"),
                breached,
                reason,
            )
            if not breached:
                continue
            if key in seen:
                continue
            ok, detail = _submit_exit(broker, pos)
            if ok:
                seen.add(key)
                logger.critical("HELD_POSITION_EXIT_TRIGGERED broker=%s symbol=%s qty=%s reason=%s detail=%s", broker_name, pos.get("symbol"), pos.get("qty"), reason, detail)
            else:
                logger.critical("HELD_POSITION_EXIT_BLOCKED broker=%s symbol=%s qty=%s reason=%s detail=%s", broker_name, pos.get("symbol"), pos.get("qty"), reason, detail)


def _patch_core_loop(cls: type) -> bool:
    if getattr(cls, _PATCHED_ATTR, False):
        return True
    original_scan = getattr(cls, "run_scan_phase", None)
    if callable(original_scan):
        @wraps(original_scan)
        def _wrapped_scan(self: Any, broker: Any = None, *args: Any, **kwargs: Any):
            broker_obj = broker if broker is not None else getattr(getattr(self, "apex", None), "broker_client", None)
            try:
                _evaluate_held_position_exits(self, broker_obj)
            except Exception as exc:
                logger.warning("HELD_POSITION_EXIT_SCAN_FAILED before_scan err=%s", exc)
            result = original_scan(self, broker, *args, **kwargs)
            try:
                _evaluate_held_position_exits(self, broker_obj)
            except Exception as exc:
                logger.warning("HELD_POSITION_EXIT_SCAN_FAILED after_scan err=%s", exc)
            return result
        setattr(cls, "run_scan_phase", _wrapped_scan)
    setattr(cls, _PATCHED_ATTR, True)
    logger.warning("HELD_POSITION_LOSS_EXIT_PATCHED class=%s", cls.__name__)
    print(f"[NIJA-PRINT] HELD_POSITION_LOSS_EXIT_PATCHED | class={cls.__name__}", flush=True)
    return True


def _patch_loaded() -> bool:
    patched = False
    for name, module in list(sys.modules.items()):
        if not isinstance(module, ModuleType):
            continue
        cls = getattr(module, "NijaCoreLoop", None)
        if isinstance(cls, type):
            patched = _patch_core_loop(cls) or patched
    return patched


def _start_monitor() -> None:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return
    _MONITOR_STARTED = True

    def _monitor() -> None:
        deadline = time.time() + _float_env("NIJA_PATCH_MONITOR_SECONDS", 300.0)
        while time.time() < deadline:
            if _patch_loaded():
                break
            time.sleep(0.25)
        logger.warning("HELD_POSITION_LOSS_EXIT_MONITOR_COMPLETE")

    threading.Thread(target=_monitor, name="held-position-loss-exit-monitor", daemon=True).start()
    logger.warning("HELD_POSITION_LOSS_EXIT_MONITOR_STARTED")


def install_import_hook() -> None:
    with _INSTALL_LOCK:
        os.environ.setdefault("NIJA_HELD_POSITION_LOSS_EXIT_ENABLED", "true")
        os.environ.setdefault("NIJA_HELD_POSITION_MAX_LOSS_PCT", "0.005")
        os.environ.setdefault("NIJA_HELD_POSITION_MAX_LOSS_USD", "0.25")
        os.environ.setdefault("NIJA_HELD_POSITION_EXIT_DRY_RUN", "false")
        os.environ.setdefault("NIJA_EXIT_HELD_UNKNOWN_COST_BASIS", "false")
        _patch_loaded()
        _start_monitor()
