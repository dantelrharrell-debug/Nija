"""Confirmed-fill settlement and heartbeat duplicate-entry guard (v415).

Production evidence on 2026-09-12 showed a confirmed Coinbase BTC fill being
recorded in PositionTracker and then removed as an "orphan" roughly two seconds
later because an immediately-following broker snapshot had not caught up yet.
The heartbeat scheduler could then retry while exposure still existed at the
exchange.

v415 is deliberately narrow and fail-closed:

* freshly confirmed execution positions receive a short, bounded settlement
  grace before broker-sync orphan cleanup may remove them;
* even after the grace expires, a confirmed execution position must be absent
  from more than one consecutive authoritative snapshot before deletion;
* the heartbeat BUY submit path checks every canonical stop surface immediately
  before submission: the KillSwitch object, emergency-stop files, runtime
  trading-state environment, and the trading-state-machine singleton;
* the heartbeat BUY submit path also requires an authoritative position read and
  blocks when the same symbol is already held;
* when the broker exposes an open-order API, an existing BUY for the heartbeat
  symbol also blocks another heartbeat BUY.

The patch does not change strategy thresholds, position sizing, drawdown limits,
stop-loss/take-profit logic, writer/nonce authority, or ordinary non-heartbeat
order dispatch.  Explicit exits continue to remove tracker positions
immediately via PositionTracker.track_exit().
"""
from __future__ import annotations

import functools
import importlib
import logging
import os
import re
import threading
import time
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

LOGGER = logging.getLogger("nija.runtime_confirmed_fill_settlement_v415")
MARKER = "20260913-runtime-confirmed-fill-settlement-v415"
_READY_FLAG = "NIJA_RUNTIME_CONFIRMED_FILL_SETTLEMENT_V415_READY"
_SYNC_PATCH_ATTR = "_nija_confirmed_fill_settlement_v415_sync"
_HEARTBEAT_PATCH_ATTR = "_nija_confirmed_fill_settlement_v415_heartbeat"
_LOCK = threading.RLock()


def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _settlement_grace_seconds() -> float:
    return _env_float(
        "NIJA_CONFIRMED_FILL_SETTLEMENT_GRACE_SECONDS",
        default=15.0,
        minimum=2.0,
        maximum=120.0,
    )


def _required_orphan_misses() -> int:
    return _env_int(
        "NIJA_CONFIRMED_FILL_ORPHAN_MISSES_REQUIRED",
        default=2,
        minimum=2,
        maximum=5,
    )


def _float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value or 0.0)
        return default if number != number else number
    except Exception:
        return default


def _value(obj: Any, *names: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        for name in names:
            if name in obj:
                return obj.get(name)
        return default
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def _canonical_symbol(value: Any) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""
    compact = re.sub(r"[^A-Z0-9]", "", text)
    aliases = {
        "BTCUSD": "BTC-USD",
        "XBTUSD": "BTC-USD",
        "XXBTZUSD": "BTC-USD",
        "ETHUSD": "ETH-USD",
        "XETHZUSD": "ETH-USD",
        "SOLUSD": "SOL-USD",
        "XRPUSD": "XRP-USD",
    }
    if compact in aliases:
        return aliases[compact]
    text = text.replace("/", "-").replace("_", "-").replace(":", "-")
    text = re.sub(r"-+", "-", text).strip("-")
    return text


def _position_symbol(position: Any) -> str:
    return _canonical_symbol(
        _value(position, "symbol", "product_id", "pair", "market", "instrument", default="")
    )


def _position_quantity(position: Any) -> float:
    return abs(
        _float(
            _value(position, "quantity", "qty", "volume", "size", "amount", "base_size", default=0.0)
        )
    )


def _position_age_seconds(position: Mapping[str, Any], now_epoch: float | None = None) -> float:
    raw = position.get("last_entry_time") or position.get("first_entry_time")
    if not raw:
        return float("inf")
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            # Render uses UTC; legacy PositionTracker timestamps are naive.
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.fromtimestamp(now_epoch if now_epoch is not None else time.time(), tz=timezone.utc)
        return max(0.0, (now - dt.astimezone(timezone.utc)).total_seconds())
    except Exception:
        return float("inf")


def _confirmed_execution_position(position: Any) -> bool:
    if not isinstance(position, Mapping):
        return False
    if position.get("cost_basis_verified") is not True:
        return False
    position_source = str(position.get("position_source") or "").strip().lower()
    entry_source = str(position.get("entry_price_source") or "").strip().lower()
    strategy = str(position.get("strategy") or "").strip().upper()
    return bool(
        entry_source == "execution"
        or position_source in {"nija_strategy", "strategy_execution", "execution"}
        or strategy == "HEARTBEAT_TRADE"
    )


def _iter_rows(payload: Any, container_keys: tuple[str, ...]) -> tuple[bool, list[Any], str]:
    if payload is None:
        return False, [], "payload_none"
    if isinstance(payload, Mapping):
        for key in container_keys:
            rows = payload.get(key)
            if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes, bytearray)):
                return True, list(rows), f"mapping:{key}"
        # Some adapters return {symbol: position_dict}.
        if payload and all(isinstance(value, Mapping) for value in payload.values()):
            return True, list(payload.values()), "mapping_values"
        if not payload:
            return True, [], "mapping_empty"
        return False, [], "mapping_shape_unknown"
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        return True, list(payload), "sequence"
    return False, [], f"unsupported_payload:{type(payload).__name__}"


def _authoritative_position_exposure(broker: Any, symbol: str) -> tuple[bool, bool, str]:
    getter = getattr(broker, "get_positions", None)
    if not callable(getter):
        return False, False, "positions_api_missing"
    try:
        payload = getter()
    except Exception as exc:
        return False, False, f"positions_read_failed:{type(exc).__name__}:{exc}"
    parsed, rows, shape = _iter_rows(payload, ("positions", "data", "items"))
    if not parsed:
        return False, False, f"positions_{shape}"
    target = _canonical_symbol(symbol)
    for row in rows:
        if _position_symbol(row) == target and _position_quantity(row) > 1e-12:
            return True, True, f"position_present:{target}"
    return True, False, f"position_absent:{target}:{shape}"


def _open_heartbeat_buy(broker: Any, symbol: str) -> tuple[bool, bool, str]:
    getter = getattr(broker, "get_open_orders", None)
    if not callable(getter):
        # Position proof is mandatory; open-order proof is opportunistic because
        # not every broker adapter implements this endpoint.
        return True, False, "open_orders_api_unavailable"
    try:
        payload = getter()
    except Exception as exc:
        return False, False, f"open_orders_read_failed:{type(exc).__name__}:{exc}"
    parsed, rows, shape = _iter_rows(payload, ("orders", "open_orders", "data", "items"))
    if not parsed:
        return False, False, f"open_orders_{shape}"
    target = _canonical_symbol(symbol)
    for row in rows:
        row_symbol = _canonical_symbol(
            _value(row, "symbol", "product_id", "pair", "market", "instrument", default="")
        )
        side = str(_value(row, "side", "order_side", default="") or "").strip().lower()
        status = str(_value(row, "status", "state", default="open") or "open").strip().lower()
        terminal = status in {"filled", "closed", "cancelled", "canceled", "rejected", "failed", "expired"}
        if row_symbol == target and side == "buy" and not terminal:
            return True, True, f"open_buy_present:{target}:{status}"
    return True, False, f"open_buy_absent:{target}:{shape}"


def _runtime_state() -> str:
    env_state = str(os.environ.get("NIJA_RUNTIME_TRADING_STATE", "") or "").strip().upper()
    if env_state:
        return env_state
    try:
        module = importlib.import_module("bot.trading_state_machine")
        getter = getattr(module, "get_trading_state_machine", None)
        machine = getter() if callable(getter) else getattr(module, "trading_state_machine", None)
        if machine is not None:
            current = getattr(machine, "get_current_state", lambda: None)()
            return str(getattr(current, "value", current) or "").strip().upper()
    except Exception:
        pass
    return ""


def _emergency_stop_files() -> list[str]:
    candidates = {
        "/app/EMERGENCY_STOP",
        os.path.abspath("EMERGENCY_STOP"),
    }
    try:
        module = importlib.import_module("bot.kill_switch")
        getter = getattr(module, "get_kill_switch", None)
        switch = getter() if callable(getter) else None
        kill_file = getattr(switch, "_kill_file", None)
        if kill_file:
            candidates.add(os.path.abspath(str(kill_file)))
    except Exception:
        pass
    return sorted(path for path in candidates if path and os.path.exists(path))


def _entry_stop_clear() -> tuple[bool, str]:
    reasons: list[str] = []
    state = _runtime_state()
    if state == "EMERGENCY_STOP":
        reasons.append("runtime_state_emergency_stop")

    active_files = _emergency_stop_files()
    if active_files:
        reasons.append("emergency_stop_file:" + ",".join(active_files))

    try:
        module = importlib.import_module("bot.kill_switch")
        getter = getattr(module, "get_kill_switch", None)
        if not callable(getter):
            reasons.append("kill_switch_getter_missing")
        else:
            switch = getter()
            if switch is None:
                reasons.append("kill_switch_missing")
            elif bool(switch.is_active()):
                reasons.append("kill_switch_active")
    except Exception as exc:
        reasons.append(f"kill_switch_probe_failed:{type(exc).__name__}:{exc}")

    if reasons:
        return False, "|".join(reasons)
    return True, "all_stop_surfaces_clear"


def _heartbeat_block_result(reason: str) -> dict[str, Any]:
    return {
        "status": "error",
        "error": f"HEARTBEAT_V415_ENTRY_BLOCKED:{reason}",
        "submitted": False,
        "filled": False,
    }


def _patch_position_tracker() -> bool:
    module = importlib.import_module("bot.position_tracker")
    tracker_cls = getattr(module, "PositionTracker", None)
    if tracker_cls is None:
        return False
    original = getattr(tracker_cls, "sync_with_broker", None)
    if not callable(original):
        return False
    if bool(getattr(original, _SYNC_PATCH_ATTR, False)):
        return True

    @functools.wraps(original)
    def sync_with_broker_v415(self: Any, broker_positions: Any) -> int:
        if broker_positions is None:
            LOGGER.critical(
                "CONFIRMED_FILL_V415_ORPHAN_SYNC_DEFERRED marker=%s reason=broker_snapshot_none positions_preserved=true fail_closed=true",
                MARKER,
            )
            return 0
        try:
            parsed, rows, shape = _iter_rows(broker_positions, ("positions", "data", "items"))
            if not parsed:
                LOGGER.critical(
                    "CONFIRMED_FILL_V415_ORPHAN_SYNC_DEFERRED marker=%s reason=broker_snapshot_unparseable shape=%s positions_preserved=true fail_closed=true",
                    MARKER, shape,
                )
                return 0
            broker_symbols = {
                _position_symbol(row)
                for row in rows
                if _position_symbol(row)
            }
            now_epoch = time.time()
            grace_s = _settlement_grace_seconds()
            required_misses = _required_orphan_misses()
            with self.lock:
                tracked_symbols = set(self.positions.keys())
                missing = tracked_symbols - broker_symbols
                counts = getattr(self, "_nija_v415_orphan_miss_counts", None)
                if not isinstance(counts, dict):
                    counts = {}
                    setattr(self, "_nija_v415_orphan_miss_counts", counts)
                for symbol in tracked_symbols & broker_symbols:
                    counts.pop(symbol, None)
                if not missing:
                    return 0

                removable: list[str] = []
                preserved: list[tuple[str, float, int, str]] = []
                for symbol in sorted(missing):
                    position = self.positions.get(symbol) or {}
                    if not _confirmed_execution_position(position):
                        removable.append(symbol)
                        counts.pop(symbol, None)
                        continue
                    misses = int(counts.get(symbol, 0) or 0) + 1
                    counts[symbol] = misses
                    age_s = _position_age_seconds(position, now_epoch=now_epoch)
                    if age_s < grace_s:
                        preserved.append((symbol, age_s, misses, "settlement_grace"))
                        continue
                    if misses < required_misses:
                        preserved.append((symbol, age_s, misses, "consecutive_miss_confirmation"))
                        continue
                    removable.append(symbol)
                    counts.pop(symbol, None)

                if preserved:
                    LOGGER.warning(
                        "CONFIRMED_FILL_V415_ORPHAN_PRESERVED marker=%s entries=%s grace_s=%.3f required_misses=%d broker_shape=%s safety_gates_bypassed=false",
                        MARKER,
                        ";".join(
                            f"{symbol}:age={age:.3f}:misses={misses}:reason={reason}"
                            for symbol, age, misses, reason in preserved
                        ),
                        grace_s,
                        required_misses,
                        shape,
                    )
                if not removable:
                    return 0
                for symbol in removable:
                    self.positions.pop(symbol, None)
                self._save_positions()
                LOGGER.info(
                    "CONFIRMED_FILL_V415_ORPHAN_REMOVED marker=%s count=%d symbols=%s repeated_absence_required=true explicit_exit_unchanged=true",
                    MARKER, len(removable), ",".join(sorted(removable)),
                )
                return len(removable)
        except Exception as exc:
            LOGGER.exception(
                "CONFIRMED_FILL_V415_ORPHAN_SYNC_ERROR marker=%s error=%s:%s positions_preserved=true fail_closed=true",
                MARKER, type(exc).__name__, exc,
            )
            return 0

    setattr(sync_with_broker_v415, _SYNC_PATCH_ATTR, True)
    setattr(sync_with_broker_v415, "__wrapped__", original)
    tracker_cls.sync_with_broker = sync_with_broker_v415
    return True


def _patch_heartbeat_submit() -> bool:
    module = importlib.import_module("bot.trading_strategy")
    original = getattr(module, "submit_market_order_via_pipeline", None)
    if not callable(original):
        return False
    if bool(getattr(original, _HEARTBEAT_PATCH_ATTR, False)):
        return True

    @functools.wraps(original)
    def guarded_submit(*args: Any, **kwargs: Any) -> Any:
        broker = kwargs.get("broker")
        symbol = kwargs.get("symbol")
        side = kwargs.get("side")
        strategy = kwargs.get("strategy")
        if broker is None and args:
            broker = args[0]
        if symbol is None and len(args) > 1:
            symbol = args[1]
        if side is None and len(args) > 2:
            side = args[2]
        strategy_text = str(strategy or "").strip().upper()
        side_text = str(side or "").strip().lower()
        if strategy_text != "HEARTBEAT_TRADE" or side_text != "buy":
            return original(*args, **kwargs)

        clear, stop_detail = _entry_stop_clear()
        if not clear:
            LOGGER.critical(
                "HEARTBEAT_V415_ENTRY_BLOCKED marker=%s reason=stop_surface_not_clear detail=%s symbol=%s order_submitted=false fail_closed=true safety_gates_bypassed=false",
                MARKER, stop_detail, _canonical_symbol(symbol),
            )
            return _heartbeat_block_result("stop_surface_not_clear")

        positions_ok, has_exposure, position_detail = _authoritative_position_exposure(broker, str(symbol or ""))
        if not positions_ok:
            LOGGER.critical(
                "HEARTBEAT_V415_ENTRY_BLOCKED marker=%s reason=authoritative_position_proof_unavailable detail=%s symbol=%s order_submitted=false fail_closed=true safety_gates_bypassed=false",
                MARKER, position_detail, _canonical_symbol(symbol),
            )
            return _heartbeat_block_result("authoritative_position_proof_unavailable")
        if has_exposure:
            LOGGER.critical(
                "HEARTBEAT_V415_ENTRY_BLOCKED marker=%s reason=existing_position detail=%s symbol=%s order_submitted=false duplicate_entry_prevented=true safety_gates_bypassed=false",
                MARKER, position_detail, _canonical_symbol(symbol),
            )
            return _heartbeat_block_result("existing_position")

        orders_ok, has_open_buy, order_detail = _open_heartbeat_buy(broker, str(symbol or ""))
        if not orders_ok:
            LOGGER.critical(
                "HEARTBEAT_V415_ENTRY_BLOCKED marker=%s reason=open_order_proof_failed detail=%s symbol=%s order_submitted=false fail_closed=true safety_gates_bypassed=false",
                MARKER, order_detail, _canonical_symbol(symbol),
            )
            return _heartbeat_block_result("open_order_proof_failed")
        if has_open_buy:
            LOGGER.critical(
                "HEARTBEAT_V415_ENTRY_BLOCKED marker=%s reason=existing_open_buy detail=%s symbol=%s order_submitted=false duplicate_entry_prevented=true safety_gates_bypassed=false",
                MARKER, order_detail, _canonical_symbol(symbol),
            )
            return _heartbeat_block_result("existing_open_buy")

        return original(*args, **kwargs)

    setattr(guarded_submit, _HEARTBEAT_PATCH_ATTR, True)
    setattr(guarded_submit, "__wrapped__", original)
    module.submit_market_order_via_pipeline = guarded_submit
    return True


def install() -> bool:
    with _LOCK:
        try:
            tracker_ready = _patch_position_tracker()
            heartbeat_ready = _patch_heartbeat_submit()
            ready = bool(tracker_ready and heartbeat_ready)
            os.environ[_READY_FLAG] = "1" if ready else "0"
            LOGGER.critical(
                "RUNTIME_CONFIRMED_FILL_SETTLEMENT_V415_%s marker=%s tracker_guard=%s heartbeat_guard=%s settlement_grace_s=%.3f orphan_misses_required=%d all_stop_surfaces_required=true ordinary_strategy_dispatch_unchanged=true thresholds_unchanged=true sizing_unchanged=true orders_submitted=false orders_cancelled=false forced_activation=false safety_gates_bypassed=false",
                "READY" if ready else "PENDING",
                MARKER,
                str(tracker_ready).lower(),
                str(heartbeat_ready).lower(),
                _settlement_grace_seconds(),
                _required_orphan_misses(),
            )
            return ready
        except Exception as exc:
            os.environ[_READY_FLAG] = "0"
            LOGGER.exception(
                "RUNTIME_CONFIRMED_FILL_SETTLEMENT_V415_INSTALL_ERROR marker=%s error=%s:%s trading_fail_closed=true",
                MARKER, type(exc).__name__, exc,
            )
            return False


install_import_hook = install

__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_authoritative_position_exposure",
    "_open_heartbeat_buy",
    "_confirmed_execution_position",
    "_position_age_seconds",
    "_entry_stop_clear",
    "_patch_position_tracker",
    "_patch_heartbeat_submit",
]
