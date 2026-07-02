"""Runtime fixes for live entry visibility, quote filtering, pair quarantine, and held-position adoption.

This module is intentionally defensive: it patches the live core loop only when
those classes are imported and leaves trade admission logic unchanged except for
skipping pairs that cannot be funded by the broker's available quote balance,
quarantining venue-unknown pairs, and forcing exchange-held positions to be
adopted into the runtime/exit stack before the first live scan.
"""

from __future__ import annotations

import builtins
import logging
import os
import re
import time
from functools import wraps
from typing import Any, Iterable, Mapping, MutableMapping, Optional, Sequence

logger = logging.getLogger("nija.live_entry_runtime_fixes")
_PATCHED_ATTR = "__nija_live_entry_runtime_fixes__"
_ADOPTION_ATTR = "__nija_exchange_held_positions_adopted__"
_UNKNOWN_PAIRS: set[tuple[str, str]] = set()

_STABLE_QUOTES = ("USDT", "USDC", "USD", "EUR", "GBP", "BTC", "ETH")
_CASH_ASSETS = {"USD", "USDT", "USDC", "DAI", "EUR", "GBP"}
_BALANCE_ATTRS = (
    "balance_cache",
    "_balance_cache",
    "balances",
    "_balances",
    "last_balance",
    "_last_balance",
    "last_balance_snapshot",
    "_last_balance_snapshot",
    "_last_known_balance_payload",
    "_last_raw_balances",
    "raw_balances",
    "_raw_balances",
)
_POSITION_ATTRS = (
    "open_positions",
    "positions",
    "_positions",
    "_open_positions",
    "tracked_positions",
    "_tracked_positions",
)
_POSITION_METHODS = (
    "get_open_positions",
    "get_positions",
    "get_spot_positions",
    "get_spot_holdings",
    "get_holdings",
    "fetch_open_positions",
    "fetch_positions",
)
_LEDGER_METHODS = (
    "upsert_open_position",
    "record_open_position",
    "add_open_position",
    "insert_open_position",
    "save_open_position",
)
_TRACKER_METHODS = (
    "adopt_position",
    "track_position",
    "add_position",
    "update_position",
    "register_position",
)
_PROFIT_METHODS = (
    "register_position",
    "adopt_position",
    "track_position",
    "add_position",
)


def _truthy(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on", "y", "enabled"}


def _broker_name(broker: Any, fallback: str = "unknown") -> str:
    for attr in ("name", "broker_name", "exchange", "exchange_name", "broker_type"):
        try:
            value = getattr(broker, attr, None)
            if value is None:
                continue
            raw = getattr(value, "value", value)
            if str(raw).strip():
                return str(raw).strip().lower()
        except Exception:
            continue
    try:
        cls_name = type(broker).__name__.lower()
        for key in ("kraken", "coinbase", "okx", "binance", "alpaca"):
            if key in cls_name:
                return key
    except Exception:
        pass
    return fallback


def _quote_asset(symbol: Any) -> str:
    raw = str(symbol or "").upper().strip()
    if not raw:
        return ""
    normalized = raw.replace("/", "-").replace("_", "-").replace(":", "-")
    if "-" in normalized:
        tail = normalized.rsplit("-", 1)[-1]
        return re.sub(r"[^A-Z0-9]", "", tail)
    compact = re.sub(r"[^A-Z0-9]", "", normalized)
    for quote in sorted(_STABLE_QUOTES, key=len, reverse=True):
        if compact.endswith(quote) and len(compact) > len(quote):
            return quote
    return ""


def _base_asset(symbol: Any) -> str:
    raw = str(symbol or "").upper().strip().replace("/", "-").replace("_", "-").replace(":", "-")
    if not raw:
        return ""
    if "-" in raw:
        return re.sub(r"[^A-Z0-9]", "", raw.split("-", 1)[0])
    compact = re.sub(r"[^A-Z0-9]", "", raw)
    for quote in sorted(_STABLE_QUOTES, key=len, reverse=True):
        if compact.endswith(quote) and len(compact) > len(quote):
            return compact[: -len(quote)]
    return compact


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        if isinstance(value, str):
            value = value.replace("$", "").replace(",", "").strip()
            if value == "":
                return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _flatten_balances(payload: Any, out: MutableMapping[str, float]) -> None:
    if payload is None:
        return
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            key_text = str(key).strip().lower()
            try:
                if isinstance(value, Mapping):
                    # Coinbase/OKX often nest available/total values under each currency.
                    for sub_key in ("available", "free", "balance", "total", "amount", "value"):
                        if sub_key in value:
                            out[key_text] = max(out.get(key_text, 0.0), float(value.get(sub_key) or 0.0))
                            break
                    _flatten_balances(value, out)
                elif isinstance(value, (int, float, str)):
                    numeric = float(value or 0.0)
                    out[key_text] = max(out.get(key_text, 0.0), numeric)
            except (TypeError, ValueError):
                continue
    elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        for item in payload:
            _flatten_balances(item, out)


def _quote_balances_from_broker(broker: Any) -> dict[str, float]:
    balances: dict[str, float] = {}
    for attr in _BALANCE_ATTRS:
        try:
            _flatten_balances(getattr(broker, attr, None), balances)
        except Exception:
            continue
    # Common scalar attributes used by bootstrap/capital hydration.
    scalar_attrs = {
        "usd": ("usd", "available_usd", "usd_balance", "_usd_balance"),
        "usdt": ("usdt", "available_usdt", "usdt_balance", "_usdt_balance"),
        "usdc": ("usdc", "available_usdc", "usdc_balance", "_usdc_balance"),
    }
    for quote, attrs in scalar_attrs.items():
        for attr in attrs:
            try:
                value = getattr(broker, attr, None)
                if value is not None:
                    balances[quote] = max(balances.get(quote, 0.0), float(value or 0.0))
            except (TypeError, ValueError):
                continue
    return balances


def _position_sequence_from_payload(payload: Any) -> list[Any]:
    if payload is None:
        return []
    if isinstance(payload, Mapping):
        # Containers commonly expose {symbol: position} or {"positions": [...]}.
        for key in ("positions", "open_positions", "holdings", "assets", "balances"):
            value = payload.get(key)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
                return list(value)
        seq: list[Any] = []
        for key, value in payload.items():
            if isinstance(value, Mapping):
                item = dict(value)
                item.setdefault("symbol", key)
                item.setdefault("asset", key)
                seq.append(item)
        return seq
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        return list(payload)
    return []


def _extract_position_payloads(broker: Any) -> list[Any]:
    payloads: list[Any] = []
    for method_name in _POSITION_METHODS:
        try:
            method = getattr(broker, method_name, None)
            if callable(method):
                payload = method()
                payloads.extend(_position_sequence_from_payload(payload))
        except Exception as exc:
            logger.debug("[ADOPTION] broker.%s() skipped: %s", method_name, exc)
    for attr in _POSITION_ATTRS:
        try:
            payloads.extend(_position_sequence_from_payload(getattr(broker, attr, None)))
        except Exception:
            continue
    return payloads


def _price_for_symbol(broker: Any, symbol: str, fallback: float = 0.0) -> float:
    for method_name in ("get_last_price", "get_current_price", "get_market_price", "get_ticker_price", "get_price"):
        try:
            method = getattr(broker, method_name, None)
            if callable(method):
                value = method(symbol)
                if isinstance(value, Mapping):
                    for key in ("price", "last", "last_price", "mark", "close"):
                        price = _coerce_float(value.get(key), 0.0)
                        if price > 0:
                            return price
                price = _coerce_float(value, 0.0)
                if price > 0:
                    return price
        except Exception:
            continue
    return fallback


def _normalize_position(raw: Any, broker: Any, broker_name: str, account_id: str) -> Optional[dict[str, Any]]:
    if not isinstance(raw, Mapping):
        raw = getattr(raw, "__dict__", None)
    if not isinstance(raw, Mapping):
        return None

    symbol = str(raw.get("symbol") or raw.get("pair") or raw.get("market") or raw.get("instrument") or "").upper()
    asset = str(raw.get("asset") or raw.get("currency") or _base_asset(symbol) or "").upper()
    if not symbol and asset:
        symbol = f"{asset}-USD"
    if not asset:
        asset = _base_asset(symbol)
    if not asset or asset in _CASH_ASSETS:
        return None

    qty = 0.0
    for key in ("qty", "quantity", "amount", "size", "units", "balance", "total", "available", "free"):
        qty = _coerce_float(raw.get(key), 0.0)
        if abs(qty) > 0:
            break
    if qty <= 0:
        return None

    mark_price = 0.0
    for key in ("mark_price", "current_price", "last_price", "price", "entry_price", "avg_entry_price", "average_price"):
        mark_price = _coerce_float(raw.get(key), 0.0)
        if mark_price > 0:
            break
    market_value = 0.0
    for key in ("market_value_usd", "value_usd", "usd_value", "notional", "market_value", "value"):
        market_value = _coerce_float(raw.get(key), 0.0)
        if market_value > 0:
            break
    if mark_price <= 0 and market_value > 0 and qty > 0:
        mark_price = market_value / qty
    if mark_price <= 0:
        mark_price = _price_for_symbol(broker, symbol, 0.0)
    if market_value <= 0 and mark_price > 0:
        market_value = qty * mark_price

    min_value = _coerce_float(os.environ.get("NIJA_ADOPT_MIN_POSITION_USD", "1.0"), 1.0)
    if market_value > 0 and market_value < min_value:
        return None

    entry_price = 0.0
    for key in ("entry_price", "avg_entry_price", "average_price", "cost_basis_price"):
        entry_price = _coerce_float(raw.get(key), 0.0)
        if entry_price > 0:
            break
    entry_price_source = "broker_cost_basis" if entry_price > 0 else "estimated_from_adoption_mark"
    if entry_price <= 0:
        entry_price = mark_price

    return {
        "id": f"{account_id}:{broker_name}:{symbol}:long:exchange_held",
        "symbol": symbol,
        "asset": asset,
        "side": str(raw.get("side") or "long").lower(),
        "quantity": qty,
        "qty": qty,
        "entry_price": entry_price,
        "current_price": mark_price,
        "mark_price": mark_price,
        "market_value_usd": market_value,
        "broker": broker_name,
        "account_id": account_id,
        "status": "open",
        "position_source": "exchange_held",
        "entry_price_source": entry_price_source,
        "adopted": True,
        "adopted_at": time.time(),
        "exit_profile": "ADOPTED_HELD_PROFIT_PROTECT" if entry_price_source == "estimated_from_adoption_mark" else "STANDARD",
        "min_net_profit_pct": 0.50,
        "min_hold_time_s": 120,
        "giveback_pct": 0.30,
    }


def _call_first_supported(target: Any, methods: tuple[str, ...], position: Mapping[str, Any]) -> bool:
    if target is None:
        return False
    for method_name in methods:
        try:
            method = getattr(target, method_name, None)
            if callable(method):
                method(dict(position))
                return True
        except TypeError:
            try:
                method(**dict(position))
                return True
            except Exception:
                continue
        except Exception as exc:
            logger.debug("[ADOPTION] %s.%s skipped: %s", type(target).__name__, method_name, exc)
    return False


def _known_position_targets(core_loop: Any) -> list[Any]:
    apex = getattr(core_loop, "apex", None)
    names = (
        "trade_ledger",
        "ledger",
        "position_tracker",
        "positions",
        "profit_harvest_layer",
        "profit_harvest",
        "execution_exit_manager",
        "exit_manager",
        "execution_exit_config",
    )
    targets: list[Any] = []
    for owner in (core_loop, apex):
        if owner is None:
            continue
        for name in names:
            try:
                target = getattr(owner, name, None)
                if target is not None and target not in targets:
                    targets.append(target)
            except Exception:
                continue
    return targets


def _append_to_runtime_open_positions(core_loop: Any, position: Mapping[str, Any]) -> bool:
    attached = False
    apex = getattr(core_loop, "apex", None)
    for owner in (core_loop, apex):
        if owner is None:
            continue
        for attr in ("open_positions", "positions", "_open_positions", "tracked_positions"):
            try:
                container = getattr(owner, attr, None)
                if isinstance(container, MutableMapping):
                    key = str(position.get("id") or position.get("symbol"))
                    if key not in container:
                        container[key] = dict(position)
                        attached = True
                elif isinstance(container, list):
                    key = str(position.get("id") or position.get("symbol"))
                    existing = {
                        str((item or {}).get("id") or (item or {}).get("symbol"))
                        for item in container
                        if isinstance(item, Mapping)
                    }
                    if key not in existing:
                        container.append(dict(position))
                        attached = True
            except Exception:
                continue
    return attached


def _adopt_exchange_held_positions(core_loop: Any, broker: Any, open_positions_count: int = 0) -> int:
    if broker is None:
        return int(open_positions_count or 0)
    if not _truthy("NIJA_ADOPT_HELD_POSITIONS", True):
        return int(open_positions_count or 0)

    broker_name = _broker_name(broker)
    account_id = str(
        getattr(broker, "account_id", None)
        or getattr(broker, "user_id", None)
        or getattr(broker, "account_name", None)
        or getattr(broker, "label", None)
        or f"runtime:{broker_name}"
    )
    key = f"{account_id}:{broker_name}"
    adopted_map = getattr(core_loop, _ADOPTION_ATTR, None)
    if not isinstance(adopted_map, set):
        adopted_map = set()
        setattr(core_loop, _ADOPTION_ATTR, adopted_map)
    if key in adopted_map:
        return max(int(open_positions_count or 0), int(getattr(core_loop, "_adopted_held_position_count", 0) or 0))

    raw_positions = _extract_position_payloads(broker)
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_positions:
        pos = _normalize_position(raw, broker, broker_name, account_id)
        if not pos:
            continue
        pos_key = str(pos.get("id") or f"{account_id}:{broker_name}:{pos.get('symbol')}")
        if pos_key in seen:
            continue
        seen.add(pos_key)
        normalized.append(pos)

    targets = _known_position_targets(core_loop)
    adopted = 0
    for pos in normalized:
        ledger_ok = False
        tracker_ok = False
        profit_ok = False
        for target in targets:
            target_name = type(target).__name__.lower()
            if "ledger" in target_name:
                ledger_ok = _call_first_supported(target, _LEDGER_METHODS, pos) or ledger_ok
            elif "tracker" in target_name or "position" in target_name:
                tracker_ok = _call_first_supported(target, _TRACKER_METHODS, pos) or tracker_ok
            elif "profit" in target_name or "exit" in target_name:
                profit_ok = _call_first_supported(target, _PROFIT_METHODS, pos) or profit_ok
        runtime_ok = _append_to_runtime_open_positions(core_loop, pos)
        adopted += 1
        logger.critical(
            "ADOPTED_HELD_POSITION account=%s broker=%s symbol=%s qty=%s value=$%.2f source=exchange_held ledger=%s tracker=%s profit_exit=%s runtime=%s entry_price_source=%s",
            account_id,
            broker_name,
            pos.get("symbol"),
            pos.get("qty"),
            float(pos.get("market_value_usd") or 0.0),
            ledger_ok,
            tracker_ok,
            profit_ok,
            runtime_ok,
            pos.get("entry_price_source"),
        )

    adopted_map.add(key)
    previous = int(getattr(core_loop, "_adopted_held_position_count", 0) or 0)
    setattr(core_loop, "_adopted_held_position_count", previous + adopted)
    logger.critical(
        "ADOPTION_SUMMARY account=%s broker=%s raw=%d adopted=%d previous_open=%s effective_open=%s",
        account_id,
        broker_name,
        len(raw_positions),
        adopted,
        open_positions_count,
        max(int(open_positions_count or 0), previous + adopted),
    )
    return max(int(open_positions_count or 0), previous + adopted)


def _should_skip_for_quote(broker_name: str, symbol: str, quote: str, balances: Mapping[str, float]) -> tuple[bool, str]:
    if not quote or not balances:
        return False, ""
    quote_key = quote.lower()
    quote_available = float(balances.get(quote_key, 0.0) or 0.0)
    # Only enforce the strict mismatch guard on OKX. Other brokers can expose
    # their buying power through generic USD/trading_balance fields while still
    # accepting USD pairs; over-filtering those venues would suppress trades.
    if broker_name == "okx" and quote in {"USDT", "USDC"} and quote_available <= 0.0:
        usd_available = float(balances.get("usd", 0.0) or balances.get("available_usd", 0.0) or 0.0)
        if usd_available > 0.0:
            return True, f"okx_quote_mismatch:{quote}_balance=0 usd_available={usd_available:.2f}"
    return False, ""


def _filter_symbols_for_quote_balance(broker: Any, symbols: Iterable[Any]) -> list[Any]:
    symbols_list = list(symbols or [])
    broker_name = _broker_name(broker)
    balances = _quote_balances_from_broker(broker)
    kept: list[Any] = []
    skipped_quote = 0
    skipped_unknown = 0
    for symbol in symbols_list:
        sym_text = str(symbol)
        quote = _quote_asset(sym_text)
        if (broker_name, sym_text.upper()) in _UNKNOWN_PAIRS:
            skipped_unknown += 1
            logger.info("PAIR_SKIPPED_UNKNOWN broker=%s pair=%s reason=session_quarantine", broker_name, sym_text)
            continue
        skip, reason = _should_skip_for_quote(broker_name, sym_text, quote, balances)
        if skip:
            skipped_quote += 1
            logger.info(
                "PAIR_SKIPPED_QUOTE_MISMATCH broker=%s pair=%s quote=%s reason=%s balances=%s",
                broker_name,
                sym_text,
                quote,
                reason,
                {k: round(v, 8) for k, v in balances.items() if k in {"usd", "usdt", "usdc", "available_usd"}},
            )
            continue
        kept.append(symbol)
    if skipped_quote or skipped_unknown:
        logger.warning(
            "SYMBOL_FILTER_SUMMARY broker=%s input=%d kept=%d skipped_quote=%d skipped_unknown=%d",
            broker_name,
            len(symbols_list),
            len(kept),
            skipped_quote,
            skipped_unknown,
        )
    return kept


def _mark_unknown_pair(broker: Any, symbol: Any, error: Any) -> None:
    msg = str(error or "")
    if "Unknown asset pair" not in msg and "EQuery:Unknown asset pair" not in msg:
        return
    broker_name = _broker_name(broker)
    sym_text = str(symbol or "").upper()
    if not sym_text:
        return
    _UNKNOWN_PAIRS.add((broker_name, sym_text))
    logger.warning("PAIR_QUARANTINED_UNKNOWN broker=%s pair=%s error=%s", broker_name, sym_text, msg[:240])


def _wrap_run_scan_phase(cls: type) -> None:
    original = getattr(cls, "run_scan_phase", None)
    if not callable(original) or getattr(original, _PATCHED_ATTR, False):
        return

    @wraps(original)
    def _wrapped(self: Any, broker: Any = None, balance: float = 0.0, symbols: Optional[list[str]] = None, *args: Any, **kwargs: Any):
        broker_obj = broker if broker is not None else getattr(getattr(self, "apex", None), "broker_client", None)
        broker_name = _broker_name(broker_obj)
        symbols_count = len(symbols or []) if symbols is not None else 0
        cycle_id = f"runtime-{int(time.time() * 1000)}"
        original_open = kwargs.get("open_positions_count", args[0] if args else 0)
        effective_open = _adopt_exchange_held_positions(self, broker_obj, int(original_open or 0))
        if effective_open != original_open:
            if "open_positions_count" in kwargs or not args:
                kwargs["open_positions_count"] = effective_open
            else:
                args = (effective_open,) + tuple(args[1:])
        logger.info(
            "SCAN_CYCLE_START cycle_id=%s broker=%s symbols=%d balance=%.2f open_positions=%s adopted_effective_open=%s user_mode=%s",
            cycle_id,
            broker_name,
            symbols_count,
            float(balance or 0.0),
            original_open,
            effective_open,
            kwargs.get("user_mode", args[1] if len(args) > 1 else False),
        )
        result = original(self, broker, balance, symbols, *args, **kwargs)
        logger.info(
            "SCAN_CYCLE_END cycle_id=%s broker=%s symbols_scored=%s entries_taken=%s entries_blocked=%s exits_taken=%s next_interval=%s errors=%s",
            cycle_id,
            broker_name,
            getattr(result, "symbols_scored", None),
            getattr(result, "entries_taken", None),
            getattr(result, "entries_blocked", None),
            getattr(result, "exits_taken", None),
            getattr(result, "next_interval", None),
            getattr(result, "errors", None),
        )
        return result

    setattr(_wrapped, _PATCHED_ATTR, True)
    setattr(cls, "run_scan_phase", _wrapped)
    logger.warning("LIVE_ENTRY_FIXES_RUN_SCAN_WIRED class=%s", cls.__name__)


def _wrap_phase3(cls: type) -> None:
    original = getattr(cls, "_phase3_scan_and_enter", None)
    if not callable(original) or getattr(original, _PATCHED_ATTR, False):
        return

    @wraps(original)
    def _wrapped(self: Any, broker: Any, snapshot: Any, symbols: list[str], available_slots: int, *args: Any, **kwargs: Any):
        filtered_symbols = _filter_symbols_for_quote_balance(broker, symbols)
        logger.info(
            "ENTRY_SCAN_START broker=%s cycle_id=%s symbols_in=%d symbols_after_filter=%d available_slots=%d balance=%.2f",
            _broker_name(broker),
            getattr(snapshot, "cycle_id", "n/a"),
            len(symbols or []),
            len(filtered_symbols),
            int(available_slots or 0),
            float(getattr(snapshot, "balance", 0.0) or 0.0),
        )
        return original(self, broker, snapshot, filtered_symbols, available_slots, *args, **kwargs)

    setattr(_wrapped, _PATCHED_ATTR, True)
    setattr(cls, "_phase3_scan_and_enter", _wrapped)
    logger.warning("LIVE_ENTRY_FIXES_PHASE3_WIRED class=%s", cls.__name__)


def _wrap_fetch_df(cls: type) -> None:
    original = getattr(cls, "_fetch_df", None)
    if not callable(original) or getattr(original, _PATCHED_ATTR, False):
        return

    @wraps(original)
    def _wrapped(self: Any, broker: Any, symbol: Any, *args: Any, **kwargs: Any):
        try:
            return original(self, broker, symbol, *args, **kwargs)
        except Exception as exc:
            _mark_unknown_pair(broker, symbol, exc)
            raise

    setattr(_wrapped, _PATCHED_ATTR, True)
    setattr(cls, "_fetch_df", _wrapped)
    logger.warning("LIVE_ENTRY_FIXES_FETCH_DF_WIRED class=%s", cls.__name__)


def _wrap_execute_action(cls: type) -> None:
    original = getattr(cls, "execute_action", None)
    if not callable(original) or getattr(original, _PATCHED_ATTR, False):
        return

    @wraps(original)
    def _wrapped(self: Any, analysis: Any, symbol: str, *args: Any, **kwargs: Any):
        action = analysis.get("action") if isinstance(analysis, Mapping) else None
        size = analysis.get("position_size") if isinstance(analysis, Mapping) else None
        price = analysis.get("entry_price") if isinstance(analysis, Mapping) else None
        logger.info(
            "ORDER_SUBMIT_ATTEMPT broker=%s pair=%s action=%s usd_size=%s entry_price=%s",
            _broker_name(getattr(self, "broker_client", None)),
            symbol,
            action,
            size,
            price,
        )
        result = original(self, analysis, symbol, *args, **kwargs)
        logger.info(
            "ORDER_SUBMIT_RESULT broker=%s pair=%s action=%s success=%s",
            _broker_name(getattr(self, "broker_client", None)),
            symbol,
            action,
            bool(result),
        )
        return result

    setattr(_wrapped, _PATCHED_ATTR, True)
    setattr(cls, "execute_action", _wrapped)
    logger.warning("LIVE_ENTRY_FIXES_EXECUTE_WIRED class=%s", cls.__name__)


def _patch_module(module: Any) -> bool:
    if module is None:
        return False
    patched = False
    try:
        core_cls = getattr(module, "NijaCoreLoop", None)
        if isinstance(core_cls, type):
            _wrap_run_scan_phase(core_cls)
            _wrap_phase3(core_cls)
            _wrap_fetch_df(core_cls)
            patched = True
    except Exception as exc:
        logger.warning("Live entry core-loop patch failed for %s: %s", getattr(module, "__name__", module), exc)
    try:
        apex_cls = getattr(module, "NIJAApexStrategyV71", None)
        if isinstance(apex_cls, type):
            _wrap_execute_action(apex_cls)
            patched = True
    except Exception as exc:
        logger.warning("Live entry apex patch failed for %s: %s", getattr(module, "__name__", module), exc)
    return patched


def install_import_hook() -> None:
    if not _truthy("NIJA_LIVE_ENTRY_RUNTIME_FIXES", True):
        logger.warning("LIVE_ENTRY_FIXES_DISABLED env=NIJA_LIVE_ENTRY_RUNTIME_FIXES")
        return

    import sys

    for name, module in list(sys.modules.items()):
        if name.endswith(("nija_core_loop", "nija_apex_strategy_v71")):
            _patch_module(module)

    if getattr(builtins, "_NIJA_LIVE_ENTRY_RUNTIME_FIXES_HOOK_INSTALLED", False):
        return

    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        targets = ("nija_core_loop", "nija_apex_strategy_v71")
        try:
            if name.endswith(targets):
                _patch_module(module)
            # When importing from a package with fromlist, Python returns the package;
            # patch submodules if they are already loaded.
            for loaded_name, loaded_module in list(sys.modules.items()):
                if loaded_name.endswith(targets):
                    _patch_module(loaded_module)
        except Exception as exc:
            logger.warning("Live entry runtime fixes import hook failed for %s: %s", name, exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_LIVE_ENTRY_RUNTIME_FIXES_HOOK_INSTALLED", True)
    logger.warning("LIVE_ENTRY_FIXES_INSTALL_COMPLETE")
