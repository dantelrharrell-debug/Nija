"""Account-local Kraken connection and profit/break-even exit convergence.

This runtime layer fixes three structural problems:

1. A live trading thread was treated as proof that its broker was still privately
   authenticated.  The exit supervisor could therefore hand off while the exact
   platform/user Kraken adapter was disconnected or stale.
2. The legacy automatic exit worker was process-global and bound to whichever
   execution engine/broker happened to start first.  Multi-account user positions
   could be monitored through the wrong adapter or not monitored at all.
3. Entry-only gates (cash buying power, throttling, allocation and short-capability
   checks) could block a legitimate sell-to-close/reduce-only exit.

The patch keeps writer authority, Kraken private authentication, ECEL validation,
exchange minimums and broker acknowledgements fail-closed.  Profit is not
promised: normal exits prefer net profit, then fee-adjusted break-even, while
configured stop-loss and critical margin reduction may still realise a loss.
"""

from __future__ import annotations

import builtins
import logging
import os
import sys
import threading
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
from types import ModuleType
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional, Tuple

logger = logging.getLogger("nija.kraken_all_account_exit")
_MARKER = "20260713-kraken-all-account-exit-v1"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_IMPORT_LOCK = threading.RLock()
_ORIGINAL_IMPORT = None
_PATCHED: set[tuple[str, int]] = set()
_PRIVATE_HEALTH: Dict[int, Tuple[float, bool, str]] = {}
_PAIR_CACHE: Dict[Tuple[int, str], Tuple[float, Optional[str]]] = {}
_EXIT_STATE: Dict[Tuple[str, str], Dict[str, Any]] = {}
_ACTIVE_EXITS: set[Tuple[str, str]] = set()
_EXIT_LOCK = threading.RLock()
_PIPELINE_LOCK = threading.RLock()
_EXIT_SCOPE: ContextVar[bool] = ContextVar("nija_account_exit_scope", default=False)


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in _TRUE


def _f(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return default if parsed != parsed else parsed
    except Exception:
        return default


def _identity(broker: Any, fallback: str = "") -> str:
    for value in (
        fallback,
        getattr(broker, "account_identifier", None),
        getattr(broker, "account_id", None),
        getattr(broker, "user_id", None),
    ):
        text = str(value or "").strip().lower()
        if text and text not in {"none", "kraken"}:
            return text
    return "platform:kraken"


def _is_kraken(broker: Any) -> bool:
    if broker is None:
        return False
    values = (
        type(broker).__name__,
        getattr(broker, "NAME", ""),
        getattr(getattr(broker, "broker_type", None), "value", getattr(broker, "broker_type", "")),
    )
    return any("kraken" in str(value or "").lower() for value in values)


def _connected(broker: Any) -> bool:
    try:
        value = getattr(broker, "connected", False)
        return bool(value() if callable(value) else value)
    except Exception:
        return False


def _private_probe_ttl() -> float:
    return max(5.0, _f(os.environ.get("NIJA_KRAKEN_PRIVATE_PROBE_TTL_S"), 20.0))


def _private_ready(broker: Any, identity: str = "", *, force: bool = False) -> Tuple[bool, str]:
    """Verify private Kraken account access for the exact adapter."""
    if broker is None:
        return False, "broker_missing"
    if not _is_kraken(broker):
        return _connected(broker), "non_kraken_connected" if _connected(broker) else "disconnected"
    if not _connected(broker):
        return False, "connected_flag_false"

    key = id(broker)
    now = time.time()
    cached = _PRIVATE_HEALTH.get(key)
    if not force and cached and now - cached[0] < _private_probe_ttl():
        return cached[1], cached[2]

    account = _identity(broker, identity)
    try:
        private_call = getattr(broker, "_kraken_api_call", None)
        if callable(private_call):
            payload = private_call("TradeBalance", {"asset": "ZUSD"})
            errors = payload.get("error") or [] if isinstance(payload, dict) else ["invalid_payload"]
            result = payload.get("result") if isinstance(payload, dict) else None
            if isinstance(errors, str):
                errors = [errors]
            if errors:
                reason = "private_api_error:" + ",".join(str(item) for item in errors)
                _PRIVATE_HEALTH[key] = (now, False, reason)
                logger.warning(
                    "KRAKEN_ACCOUNT_PRIVATE_PROBE_FAILED marker=%s account=%s reason=%s",
                    _MARKER, account, reason,
                )
                return False, reason
            if not isinstance(result, Mapping):
                reason = "trade_balance_result_missing"
                _PRIVATE_HEALTH[key] = (now, False, reason)
                return False, reason
            _PRIVATE_HEALTH[key] = (now, True, "trade_balance_ok")
            logger.info(
                "KRAKEN_ACCOUNT_PRIVATE_READY marker=%s account=%s equity=%s free_margin=%s",
                _MARKER, account, result.get("e", result.get("eb")), result.get("mf", result.get("tb")),
            )
            return True, "trade_balance_ok"

        getter = getattr(broker, "get_account_balance", None)
        if callable(getter):
            value = getter()
            if _f(value if not isinstance(value, Mapping) else value.get("total_funds", value.get("balance")), -1.0) >= 0:
                _PRIVATE_HEALTH[key] = (now, True, "balance_ok")
                return True, "balance_ok"
    except Exception as exc:
        reason = f"private_probe_exception:{exc}"
        _PRIVATE_HEALTH[key] = (now, False, reason)
        logger.warning(
            "KRAKEN_ACCOUNT_PRIVATE_PROBE_FAILED marker=%s account=%s reason=%s",
            _MARKER, account, reason,
        )
        return False, reason

    _PRIVATE_HEALTH[key] = (now, False, "private_probe_unavailable")
    return False, "private_probe_unavailable"


def _force_reconnect(broker: Any, identity: str) -> bool:
    if broker is None:
        return False
    account = _identity(broker, identity)
    ready, _ = _private_ready(broker, account)
    if ready:
        return True
    try:
        for attr in ("connected", "_connected"):
            if hasattr(broker, attr):
                try:
                    setattr(broker, attr, False)
                except Exception:
                    pass
        connector = getattr(broker, "connect", None)
        if not callable(connector):
            return False
        result = connector()
        _PRIVATE_HEALTH.pop(id(broker), None)
        ready, reason = _private_ready(broker, account, force=True)
        logger.warning(
            "KRAKEN_ACCOUNT_RECONNECT_RESULT marker=%s account=%s connect_result=%s private_ready=%s reason=%s",
            _MARKER, account, result, ready, reason,
        )
        return ready
    except Exception as exc:
        logger.warning(
            "KRAKEN_ACCOUNT_RECONNECT_FAILED marker=%s account=%s error=%s",
            _MARKER, account, exc,
        )
        return False


def _normalise_symbol(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-").replace("_", "-")


def _base_asset(symbol: str) -> str:
    text = _normalise_symbol(symbol)
    if "-" in text:
        base = text.split("-", 1)[0]
    elif text.endswith("USDT"):
        base = text[:-4]
    elif text.endswith("USDC"):
        base = text[:-4]
    elif text.endswith("USD") or text.endswith("EUR"):
        base = text[:-3]
    else:
        base = text
    aliases = {"XXBT": "XBT", "BTC": "XBT", "XETH": "ETH"}
    return aliases.get(base, base)


def _public_call(broker: Any, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    custom = getattr(broker, "_kraken_public_api_call", None)
    if callable(custom):
        result = custom(method, params or {})
        return result if isinstance(result, dict) else {}
    api = getattr(broker, "api", None)
    query_public = getattr(api, "query_public", None)
    if callable(query_public):
        result = query_public(method, params or {})
        return result if isinstance(result, dict) else {}
    query_public = getattr(broker, "query_public", None)
    if callable(query_public):
        result = query_public(method, params or {})
        return result if isinstance(result, dict) else {}
    return {}


def _resolve_pair(broker: Any, symbol: str) -> Optional[str]:
    canonical = _normalise_symbol(symbol)
    key = (id(broker), canonical)
    now = time.time()
    cached = _PAIR_CACHE.get(key)
    if cached and now - cached[0] < 1800.0:
        return cached[1]

    base = _base_asset(canonical)
    if not base:
        _PAIR_CACHE[key] = (now, None)
        return None

    candidates = []
    if "-" in canonical:
        candidates.append(canonical.replace("-", ""))
    candidates.extend(f"{base}{quote}" for quote in ("USD", "USDT", "USDC", "EUR"))
    candidates = list(dict.fromkeys(candidates))

    for candidate in candidates:
        try:
            payload = _public_call(broker, "AssetPairs", {"pair": candidate})
            errors = payload.get("error") or [] if isinstance(payload, dict) else ["invalid"]
            result = payload.get("result", {}) if isinstance(payload, dict) else {}
            if not errors and isinstance(result, Mapping) and result:
                row = next(iter(result.values()))
                altname = str(row.get("altname") or candidate) if isinstance(row, Mapping) else candidate
                _PAIR_CACHE[key] = (now, altname)
                logger.info(
                    "KRAKEN_EXIT_PAIR_RESOLVED marker=%s symbol=%s pair=%s",
                    _MARKER, canonical, altname,
                )
                return altname
        except Exception:
            continue

    _PAIR_CACHE[key] = (now, None)
    logger.warning(
        "KRAKEN_EXIT_PAIR_UNRESOLVED marker=%s symbol=%s candidates=%s",
        _MARKER, canonical, candidates,
    )
    return None


def _ticker_price(broker: Any, pair: str) -> float:
    for method_name in ("get_current_price", "get_price", "fetch_price"):
        method = getattr(broker, method_name, None)
        if callable(method):
            try:
                value = _f(method(pair))
                if value > 0:
                    return value
            except Exception:
                pass
    try:
        payload = _public_call(broker, "Ticker", {"pair": pair})
        result = payload.get("result", {}) if isinstance(payload, dict) else {}
        if isinstance(result, Mapping) and result:
            row = next(iter(result.values()))
            if isinstance(row, Mapping):
                close = row.get("c")
                if isinstance(close, (list, tuple)) and close:
                    return _f(close[0])
                for key in ("last", "price", "close"):
                    value = _f(row.get(key))
                    if value > 0:
                        return value
    except Exception:
        pass
    return 0.0


def _position_rows(broker: Any) -> Iterable[MutableMapping[str, Any]]:
    tracker = getattr(broker, "position_tracker", None)
    yielded: set[str] = set()
    if tracker is not None:
        try:
            for symbol in tracker.get_all_positions() or []:
                row = tracker.get_position(symbol)
                if isinstance(row, MutableMapping):
                    payload = dict(row)
                    payload.setdefault("symbol", symbol)
                    yielded.add(_normalise_symbol(symbol))
                    yield payload
        except Exception:
            pass
    getter = getattr(broker, "get_positions", None)
    if callable(getter):
        try:
            rows = getter() or []
            if isinstance(rows, Mapping):
                rows = list(rows.values())
            for row in rows if isinstance(rows, (list, tuple, set)) else []:
                if not isinstance(row, Mapping):
                    continue
                symbol = _normalise_symbol(row.get("symbol"))
                if not symbol or symbol in yielded:
                    continue
                yield dict(row)
        except Exception:
            pass


def _entry_price(position: Mapping[str, Any]) -> float:
    for key in (
        "entry_price", "avg_entry_price", "average_price", "cost_basis_price",
        "average_filled_price", "avg_fill_price", "avg_price", "purchase_price",
    ):
        value = _f(position.get(key))
        if value > 0:
            return value
    quantity = abs(_f(position.get("quantity", position.get("qty", position.get("size")))))
    total_cost = _f(position.get("size_usd", position.get("cost_basis_usd", position.get("total_cost"))))
    return total_cost / quantity if quantity > 0 and total_cost > 0 else 0.0


def _quantity(position: Mapping[str, Any]) -> float:
    for key in ("quantity", "qty", "amount", "size", "units"):
        value = abs(_f(position.get(key)))
        if value > 0:
            return value
    return 0.0


def _held_minutes(position: Mapping[str, Any]) -> float:
    raw = position.get("first_entry_time") or position.get("entry_time") or position.get("opened_at")
    if raw is None:
        return 0.0
    try:
        if isinstance(raw, datetime):
            dt = raw
        else:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 60.0)
    except Exception:
        return 0.0


def _margin_extra_buffer(account: str, symbol: str) -> float:
    try:
        from bot.margin_position_ledger import get_margin_position_ledger
        row = get_margin_position_ledger().get_record(
            broker="kraken", account_id=account, subaccount_id="",
            symbol=_normalise_symbol(symbol), asset_class="crypto",
        )
        if row and int(_f(row.get("leverage"), 1.0)) > 1:
            return max(0.0, _f(os.environ.get("NIJA_KRAKEN_MARGIN_EXIT_EXTRA_BUFFER_PCT"), 0.002))
    except Exception:
        pass
    return 0.0


def _exit_thresholds(account: str, symbol: str, entry: float) -> Tuple[float, float]:
    round_trip = max(0.001, _f(os.environ.get("NIJA_KRAKEN_EXIT_ROUND_TRIP_COST_PCT"), 0.008))
    round_trip += _margin_extra_buffer(account, symbol)
    net_target = max(0.001, _f(os.environ.get("NIJA_KRAKEN_EXIT_NET_PROFIT_TARGET_PCT"), 0.004))
    return entry * (1.0 + round_trip), entry * (1.0 + round_trip + net_target)


def _exit_reason(position: Mapping[str, Any], price: float, account: str, symbol: str) -> Tuple[Optional[str], float, float]:
    entry = _entry_price(position)
    if entry <= 0 or price <= 0:
        return None, 0.0, 0.0
    side = str(position.get("side") or "long").strip().lower()
    short = side in {"short", "sell"}
    breakeven, target = _exit_thresholds(account, symbol, entry)
    if short:
        round_trip = max(0.001, (breakeven / entry) - 1.0)
        net_target = max(0.001, (target / entry) - (breakeven / entry))
        breakeven = entry * (1.0 - round_trip)
        target = entry * (1.0 - round_trip - net_target)

    stop = _f(position.get("stop_loss"))
    if stop > 0 and ((not short and price <= stop) or (short and price >= stop)):
        return "emergency_stop_loss", breakeven, target

    for key in ("take_profit_1", "take_profit_2", "take_profit_3", "take_profit"):
        tp = _f(position.get(key))
        if tp > 0 and ((not short and price >= tp) or (short and price <= tp)):
            return key, breakeven, target

    state_key = (account, symbol)
    state = _EXIT_STATE.setdefault(state_key, {"high": price, "low": price, "armed": False})
    state["high"] = max(_f(state.get("high"), price), price)
    state["low"] = min(_f(state.get("low"), price), price)
    profit_hit = price >= target if not short else price <= target
    if profit_hit:
        state["armed"] = True
        return "net_profit_target", breakeven, target

    held = _held_minutes(position)
    break_even_hold = max(5.0, _f(os.environ.get("NIJA_KRAKEN_BREAK_EVEN_MAX_HOLD_MINUTES"), 60.0))
    at_breakeven = price >= breakeven if not short else price <= breakeven
    if _truthy("NIJA_KRAKEN_BREAK_EVEN_EXIT_ENABLED", "true") and held >= break_even_hold and at_breakeven:
        return "fee_adjusted_break_even", breakeven, target

    trail = max(0.001, _f(os.environ.get("NIJA_KRAKEN_PROFIT_LOCK_TRAIL_PCT"), 0.0035))
    if state.get("armed") and at_breakeven:
        retraced = price <= state["high"] * (1.0 - trail) if not short else price >= state["low"] * (1.0 + trail)
        if retraced:
            return "profit_lock_break_even", breakeven, target
    return None, breakeven, target


def _submit_exit(broker: Any, account: str, pair: str, quantity: float, reason: str) -> Mapping[str, Any]:
    try:
        from bot.pipeline_order_submitter import submit_market_order_via_pipeline
        with _EXIT_LOCK:
            result = submit_market_order_via_pipeline(
                broker=broker,
                symbol=pair,
                side="sell",
                quantity=quantity,
                size_type="base",
                strategy=f"KrakenAccountExit:{reason}",
            )
        return result if isinstance(result, Mapping) else {"status": "error", "error": str(result)}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def _scan_account_exits(trader: Any, identity: str, broker: Any) -> int:
    if not _truthy("NIJA_KRAKEN_ALL_ACCOUNT_EXIT_ENABLED", "true") or not _is_kraken(broker):
        return 0
    account = _identity(broker, identity)
    ready, reason = _private_ready(broker, account)
    if not ready:
        logger.warning(
            "KRAKEN_ACCOUNT_EXIT_SCAN_BLOCKED marker=%s account=%s reason=%s",
            _MARKER, account, reason,
        )
        return 0

    closed = 0
    for position in list(_position_rows(broker)):
        symbol = _normalise_symbol(position.get("symbol"))
        quantity = _quantity(position)
        entry = _entry_price(position)
        if not symbol or quantity <= 0:
            continue
        pair = _resolve_pair(broker, symbol)
        if not pair:
            continue
        price = _ticker_price(broker, pair)
        if price <= 0:
            logger.warning(
                "KRAKEN_ACCOUNT_EXIT_PRICE_MISSING marker=%s account=%s symbol=%s pair=%s",
                _MARKER, account, symbol, pair,
            )
            continue
        reason, breakeven, target = _exit_reason(position, price, account, symbol)
        logger.info(
            "KRAKEN_ACCOUNT_EXIT_EVALUATED marker=%s account=%s symbol=%s pair=%s qty=%.8f "
            "entry=$%.8f market=$%.8f breakeven=$%.8f profit_target=$%.8f decision=%s",
            _MARKER, account, symbol, pair, quantity, entry, price, breakeven, target, reason or "hold",
        )
        if not reason:
            continue

        active_key = (account, symbol)
        with _EXIT_LOCK:
            if active_key in _ACTIVE_EXITS:
                continue
            _ACTIVE_EXITS.add(active_key)
        try:
            logger.critical(
                "KRAKEN_ACCOUNT_EXIT_TRIGGER marker=%s account=%s symbol=%s pair=%s reason=%s "
                "market=$%.8f breakeven=$%.8f profit_target=$%.8f",
                _MARKER, account, symbol, pair, reason, price, breakeven, target,
            )
            result = _submit_exit(broker, account, pair, quantity, reason)
            status = str(result.get("status") or "").lower()
            success = status in {"filled", "closed", "done", "complete", "completed", "success", "accepted"} or bool(result.get("order_id"))
            if not success:
                logger.error(
                    "KRAKEN_ACCOUNT_EXIT_ORDER_FAILED marker=%s account=%s symbol=%s reason=%s error=%s",
                    _MARKER, account, symbol, reason, result.get("error", result),
                )
                continue
            tracker = getattr(broker, "position_tracker", None)
            if tracker is not None and callable(getattr(tracker, "track_exit", None)):
                try:
                    tracker.track_exit(symbol)
                except Exception:
                    pass
            _EXIT_STATE.pop(active_key, None)
            closed += 1
            logger.critical(
                "KRAKEN_ACCOUNT_EXIT_ORDER_ACK marker=%s account=%s symbol=%s reason=%s "
                "order_id=%s filled_price=%s",
                _MARKER, account, symbol, reason, result.get("order_id"), result.get("filled_price"),
            )
        finally:
            with _EXIT_LOCK:
                _ACTIVE_EXITS.discard(active_key)
    return closed


def _patch_recovery_module(module: ModuleType) -> bool:
    changed = False
    original_connect = getattr(module, "_connect", None)
    if callable(original_connect) and not getattr(original_connect, "_nija_private_ready_v1", False):
        @wraps(original_connect)
        def connect(broker: Any, identity: str) -> bool:
            if _private_ready(broker, identity)[0]:
                return True
            result = original_connect(broker, identity)
            return bool(result and _private_ready(broker, identity, force=True)[0]) or _force_reconnect(broker, identity)
        connect._nija_private_ready_v1 = True  # type: ignore[attr-defined]
        module._connect = connect
        changed = True

    original_alive = getattr(module, "_normal_thread_alive", None)
    if callable(original_alive) and not getattr(original_alive, "_nija_private_ready_v1", False):
        @wraps(original_alive)
        def normal_thread_alive(trader: Any, scope: str, user_id: Optional[str], broker_type: Any, broker: Any) -> bool:
            alive = bool(original_alive(trader, scope, user_id, broker_type, broker))
            if not alive:
                return False
            name = str(getattr(broker_type, "value", broker_type) or "kraken").lower()
            identity = f"platform:{name}" if scope == "platform" else f"user:{user_id}:{name}"
            ready, reason = _private_ready(broker, identity)
            if not ready:
                logger.warning(
                    "KRAKEN_THREAD_HANDOFF_REJECTED marker=%s account=%s reason=%s thread_alive=true",
                    _MARKER, identity, reason,
                )
                return False
            return True
        normal_thread_alive._nija_private_ready_v1 = True  # type: ignore[attr-defined]
        module._normal_thread_alive = normal_thread_alive
        changed = True

    original_manage = getattr(module, "_adopt_and_manage", None)
    if callable(original_manage) and not getattr(original_manage, "_nija_account_exit_scan_v1", False):
        @wraps(original_manage)
        def adopt_and_manage(trader: Any, identity: str, broker: Any):
            result = original_manage(trader, identity, broker)
            try:
                _scan_account_exits(trader, identity, broker)
            except Exception:
                logger.exception(
                    "KRAKEN_ACCOUNT_EXIT_SCAN_FAILED marker=%s account=%s",
                    _MARKER, identity,
                )
            return result
        adopt_and_manage._nija_account_exit_scan_v1 = True  # type: ignore[attr-defined]
        module._adopt_and_manage = adopt_and_manage
        changed = True

    original_retry = getattr(module, "_retry_all_accounts", None)
    if callable(original_retry) and not getattr(original_retry, "_nija_account_matrix_v1", False):
        @wraps(original_retry)
        def retry_all_accounts(trader: Any):
            result = original_retry(trader)
            rows = []
            iterator = getattr(module, "_iter_accounts", None)
            if callable(iterator):
                for identity, scope, user_id, broker_type, broker in list(iterator(trader)):
                    if not _is_kraken(broker):
                        continue
                    ready, reason = _private_ready(broker, identity)
                    rows.append(f"{identity}={'ready' if ready else 'down'}:{reason}")
            logger.critical(
                "KRAKEN_ALL_ACCOUNT_CONNECTION_MATRIX marker=%s accounts=%s",
                _MARKER, rows,
            )
            return result
        retry_all_accounts._nija_account_matrix_v1 = True  # type: ignore[attr-defined]
        module._retry_all_accounts = retry_all_accounts
        changed = True
    return changed


def _is_exit_request(request: Any) -> bool:
    intent = str(getattr(request, "intent_type", "") or "").strip().lower()
    effect = str(getattr(request, "position_effect", "") or "").strip().lower()
    metadata = dict(getattr(request, "metadata", {}) or {})
    return intent in {"exit", "reduce"} or effect in {"close", "reduce"} or metadata.get("closing_position") is True


def _patch_execution_pipeline(module: ModuleType) -> bool:
    cls = getattr(module, "ExecutionPipeline", None)
    if not isinstance(cls, type):
        return False
    changed = False

    original_caps = getattr(cls, "_gate_broker_capabilities", None)
    if callable(original_caps) and not getattr(original_caps, "_nija_exit_capability_v1", False):
        @wraps(original_caps)
        def gate_broker_capabilities(self: Any, request: Any, t_start: float):
            if _is_exit_request(request):
                logger.info(
                    "ACCOUNT_EXIT_CAPABILITY_CLOSE_ALLOWED marker=%s account=%s symbol=%s side=%s",
                    _MARKER, getattr(request, "account_id", "default"), getattr(request, "symbol", ""), getattr(request, "side", ""),
                )
                return None
            return original_caps(self, request, t_start)
        gate_broker_capabilities._nija_exit_capability_v1 = True  # type: ignore[attr-defined]
        cls._gate_broker_capabilities = gate_broker_capabilities
        changed = True

    original_execute = getattr(cls, "execute", None)
    if callable(original_execute) and not getattr(original_execute, "_nija_exit_entry_gate_split_v1", False):
        @wraps(original_execute)
        def execute(self: Any, request: Any):
            with _PIPELINE_LOCK:
                if not _is_exit_request(request):
                    return original_execute(self, request)
                token = _EXIT_SCOPE.set(True)
                names = (
                    "_pre_trade_risk_engine", "_allocation_clamp", "_execution_observer",
                    "_throttler", "_downstream_guard",
                )
                saved = {name: getattr(self, name, None) for name in names}
                try:
                    for name in names:
                        setattr(self, name, None)
                    logger.critical(
                        "ACCOUNT_EXIT_ENTRY_ONLY_GATES_BYPASSED marker=%s account=%s symbol=%s "
                        "writer_and_broker_gates_preserved=true",
                        _MARKER, getattr(request, "account_id", "default"), getattr(request, "symbol", ""),
                    )
                    return original_execute(self, request)
                finally:
                    for name, value in saved.items():
                        setattr(self, name, value)
                    _EXIT_SCOPE.reset(token)
        execute._nija_exit_entry_gate_split_v1 = True  # type: ignore[attr-defined]
        cls.execute = execute
        changed = True
    return changed


def _patch_auto_exit_module(module: ModuleType) -> bool:
    starter = getattr(module, "_start_monitor", None)
    if not callable(starter) or getattr(starter, "_nija_account_local_disabled_v1", False):
        return False

    def start_monitor(engine: Any) -> None:
        logger.warning(
            "GLOBAL_SINGLETON_AUTO_EXIT_DISABLED marker=%s reason=account_local_kraken_supervisor_active",
            _MARKER,
        )
        return None

    start_monitor._nija_account_local_disabled_v1 = True  # type: ignore[attr-defined]
    start_monitor.__wrapped__ = starter  # type: ignore[attr-defined]
    module._start_monitor = start_monitor
    return True


def _patch_module(module: ModuleType) -> bool:
    key = (str(getattr(module, "__name__", "")), id(module))
    if key in _PATCHED:
        return True
    name = str(getattr(module, "__name__", ""))
    changed = False
    if name.endswith("account_exit_management_recovery_patch"):
        changed = _patch_recovery_module(module) or changed
    if name.endswith("execution_pipeline"):
        changed = _patch_execution_pipeline(module) or changed
    if name.endswith("auto_exit_sl_tp_runtime_patch"):
        changed = _patch_auto_exit_module(module) or changed
    if changed:
        _PATCHED.add(key)
    return changed


def _patch_loaded() -> None:
    for module in tuple(sys.modules.values()):
        if isinstance(module, ModuleType):
            try:
                _patch_module(module)
            except Exception:
                continue


def _set_defaults() -> None:
    defaults = {
        "NIJA_KRAKEN_ALL_ACCOUNT_EXIT_ENABLED": "true",
        "NIJA_ACCOUNT_EXIT_MANAGEMENT_RECOVERY_ENABLED": "true",
        "NIJA_ACCOUNT_EXIT_MANAGEMENT_INTERVAL_S": "10",
        "NIJA_KRAKEN_PRIVATE_PROBE_TTL_S": "20",
        "NIJA_KRAKEN_EXIT_ROUND_TRIP_COST_PCT": "0.008",
        "NIJA_KRAKEN_MARGIN_EXIT_EXTRA_BUFFER_PCT": "0.002",
        "NIJA_KRAKEN_EXIT_NET_PROFIT_TARGET_PCT": "0.004",
        "NIJA_KRAKEN_BREAK_EVEN_EXIT_ENABLED": "true",
        "NIJA_KRAKEN_BREAK_EVEN_MAX_HOLD_MINUTES": "60",
        "NIJA_KRAKEN_PROFIT_LOCK_TRAIL_PCT": "0.0035",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT
    _set_defaults()
    _patch_loaded()
    with _IMPORT_LOCK:
        if _ORIGINAL_IMPORT is not None:
            return
        _ORIGINAL_IMPORT = builtins.__import__
        local = threading.local()

        def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
            module = _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)  # type: ignore[misc]
            if getattr(local, "active", False):
                return module
            local.active = True
            try:
                _patch_loaded()
            finally:
                local.active = False
            return module

        builtins.__import__ = guarded_import  # type: ignore[assignment]
    _patch_loaded()
    logger.critical(
        "KRAKEN_ALL_ACCOUNT_EXIT_RUNTIME_INSTALLED marker=%s interval_s=%s "
        "profit_target_net=%s break_even_hold_min=%s",
        _MARKER,
        os.environ.get("NIJA_ACCOUNT_EXIT_MANAGEMENT_INTERVAL_S"),
        os.environ.get("NIJA_KRAKEN_EXIT_NET_PROFIT_TARGET_PCT"),
        os.environ.get("NIJA_KRAKEN_BREAK_EVEN_MAX_HOLD_MINUTES"),
    )


__all__ = [
    "install_import_hook", "_private_ready", "_resolve_pair", "_exit_reason",
    "_scan_account_exits", "_patch_execution_pipeline", "_patch_recovery_module",
]
