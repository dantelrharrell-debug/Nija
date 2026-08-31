"""Capital recycling + just-in-time exit authority v330.

Purpose
-------
Prevent live capital from becoming stranded in long-held positions when the
account no longer has enough free buying power to continue NIJA's normal 24/7
operation.

v330 does four things, without weakening fill/order/risk truth:

1. Makes the corrected universal exit stack mandatory (v67 fill reconciliation,
   v68 all-in break-even/net-profit floor, v74 adaptive profit trailing, v323
   tracker/quantity proof convergence).
2. Adds a just-in-time, account-local quantity proof for exits when the global
   v285 snapshot is missing/stale. Kraken first reuses a genuine recent v312
   authenticated Balance observation. Other venues use a bounded, single-flight
   broker position refresh in a daemon worker. A tracker row is actionable only
   when its quantity matches a genuine recent JIT proof.
3. Adds capital-recycling exits. When proven free buying power is below the
   venue reserve, a verified holding may exit as soon as it reaches the same
   fee/spread/slippage-adjusted break-even computed by v68. When capital is not
   constrained, the normal net-profit target gradually decays toward true
   break-even after a configurable hold age, so funds are not tied up forever.
4. Adds a live-entry reserve gate at the v69 expectancy boundary. A new entry is
   blocked if proven free buying power is already at/below the venue reserve, or
   if a known planned notional would consume that reserve.

This patch never fabricates a position, cost basis, balance, price, order, fill,
profit, or readiness state. It does not extend the v285 snapshot TTL. Stop-loss,
critical-margin and liquidation-prevention exits remain unchanged. "Break-even"
means estimated all-in break-even; adverse market movement/slippage can still
produce a realized loss.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import math
import os
import threading
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.runtime_capital_recycling_exit_v330")
MARKER = "20260831-runtime-capital-recycling-exit-v330"
RELEASE_ID = "20260831-runtime-convergence-v330"
_READY_FLAG = "NIJA_RUNTIME_CAPITAL_RECYCLING_EXIT_V330_READY"
_EXIT_PATCH_ATTR = "_nija_capital_recycling_exit_v330"
_PROOF_PATCH_ATTR = "_nija_jit_exit_proof_v330"
_ENTRY_PATCH_ATTR = "_nija_capital_reserve_entry_v330"
_INSTALL_FLAG = "_NIJA_RUNTIME_CAPITAL_RECYCLING_EXIT_V330"
_LOCK = threading.RLock()
_JIT_LOCK = threading.RLock()
_JIT_INFLIGHT: set[int] = set()
_JIT_ROWS: dict[int, tuple[float, dict[str, float], str]] = {}


def _f(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return result if math.isfinite(result) else default


def _norm(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _symbol(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-").replace("_", "-")


def _broker_label(broker: Any) -> str:
    for attr in ("broker_name", "exchange_name", "exchange", "name"):
        text = _norm(getattr(broker, attr, None))
        for known in ("kraken", "coinbase", "okx", "alpaca"):
            if known in text:
                return known
    broker_type = getattr(broker, "broker_type", None)
    text = _norm(getattr(broker_type, "value", broker_type))
    for known in ("kraken", "coinbase", "okx", "alpaca"):
        if known in text:
            return known
    text = _norm(type(broker).__name__)
    for known in ("kraken", "coinbase", "okx", "alpaca"):
        if known in text:
            return known
    return "unknown"


def _reserve_usd(broker: Any) -> float:
    venue = _broker_label(broker)
    defaults = {
        "kraken": 30.75,   # $28.75 current safe verification notional + headroom
        "coinbase": 14.50, # $12.50 minimum verification notional + headroom
        "okx": 14.50,
        "alpaca": 12.00,
        "unknown": 15.00,
    }
    venue_key = f"NIJA_CAPITAL_RECYCLE_{venue.upper()}_RESERVE_USD"
    return max(
        0.0,
        _f(
            os.environ.get(venue_key),
            _f(os.environ.get("NIJA_CAPITAL_RECYCLE_RESERVE_USD"), defaults.get(venue, 15.0)),
        ),
    )


def _balance_from_payload(payload: Any) -> float | None:
    if payload is None:
        return None
    if isinstance(payload, Mapping):
        for key in (
            "available_usd", "available", "cash", "buying_power", "spendable",
            "free", "free_cash", "available_balance", "usd_available", "balance",
        ):
            if key in payload:
                value = _f(payload.get(key), -1.0)
                if value >= 0.0:
                    return value
        return None
    value = _f(payload, -1.0)
    return value if value >= 0.0 else None


def _cached_free_balance(broker: Any) -> tuple[float | None, str]:
    for attr in (
        "_last_known_balance", "last_known_balance", "cached_balance",
        "_cached_balance", "available_balance", "buying_power", "cash",
    ):
        value = _balance_from_payload(getattr(broker, attr, None))
        if value is not None:
            return value, f"broker_attr:{attr}"

    try:
        from bot.balance_service import BalanceService
        label = _broker_label(broker)
        value = _f(BalanceService.get(label), -1.0)
        if value >= 0.0:
            return value, "balance_service"
    except Exception:
        pass
    return None, "unproven"


def _row_quantity(row: Mapping[str, Any]) -> float:
    for key in ("quantity", "qty", "amount", "size", "units", "balance"):
        if row.get(key) is not None:
            return abs(_f(row.get(key)))
    return 0.0


def _rows_to_quantities(rows: Any) -> dict[str, float]:
    if isinstance(rows, Mapping):
        iterable = []
        for key, value in rows.items():
            if isinstance(value, Mapping):
                row = dict(value)
                row.setdefault("symbol", key)
                iterable.append(row)
        rows = iterable
    if not isinstance(rows, (list, tuple, set, frozenset)):
        return {}
    output: dict[str, float] = {}
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        sym = _symbol(raw.get("symbol") or raw.get("pair") or raw.get("asset"))
        qty = _row_quantity(raw)
        if sym and qty > 0.0:
            output[sym] = output.get(sym, 0.0) + qty
    return output


def _kraken_recent_balance_quantities(broker: Any) -> tuple[dict[str, float], str]:
    if _broker_label(broker) != "kraken":
        return {}, "not_kraken"
    try:
        v312 = importlib.import_module("bot.runtime_kraken_balance_epoch_handoff_v312_patch")
        getter = getattr(v312, "_fresh_observation", None)
        builder = getattr(v312, "_rows_from_observation", None)
        if not callable(getter) or not callable(builder):
            return {}, "v312_helpers_missing"
        observation = getter(broker, not_before=0.0)
        if not isinstance(observation, Mapping):
            return {}, "v312_recent_balance_missing"
        rows = builder(broker, observation)
        quantities = _rows_to_quantities(rows)
        if quantities:
            return quantities, "v312_authenticated_balance"
    except Exception as exc:
        return {}, f"v312_error:{type(exc).__name__}"
    return {}, "v312_no_positions"


def _start_jit_refresh(broker: Any) -> None:
    key = id(broker)
    with _JIT_LOCK:
        if key in _JIT_INFLIGHT:
            return
        _JIT_INFLIGHT.add(key)

    def worker() -> None:
        source = "broker_get_positions"
        try:
            getter = getattr(broker, "get_positions", None)
            if not callable(getter):
                return
            rows = getter()
            quantities = _rows_to_quantities(rows)
            if quantities:
                with _JIT_LOCK:
                    _JIT_ROWS[key] = (time.monotonic(), quantities, source)
                LOGGER.critical(
                    "CAPITAL_RECYCLE_V330_JIT_POSITION_PROOF marker=%s venue=%s symbols=%s "
                    "genuine_broker_read=true tracker_mutation=false snapshot_ttl_extended=false "
                    "position_fabricated=false safety_gates_bypassed=false",
                    MARKER, _broker_label(broker), sorted(quantities),
                )
        except Exception as exc:
            LOGGER.warning(
                "CAPITAL_RECYCLE_V330_JIT_POSITION_DEFERRED marker=%s venue=%s error=%s:%s "
                "exit_not_submitted=true fail_closed=true",
                MARKER, _broker_label(broker), type(exc).__name__, exc,
            )
        finally:
            with _JIT_LOCK:
                _JIT_INFLIGHT.discard(key)

    threading.Thread(
        target=worker,
        name=f"ExitJIT-{_broker_label(broker)}-{key}",
        daemon=True,
    ).start()


def _jit_quantity(broker: Any, symbol: str) -> tuple[bool, float, str, float]:
    target = _symbol(symbol)
    if not target:
        return False, 0.0, "invalid_symbol", float("inf")

    kraken_rows, source = _kraken_recent_balance_quantities(broker)
    if target in kraken_rows and kraken_rows[target] > 0.0:
        return True, kraken_rows[target], source, 0.0

    key = id(broker)
    ttl = max(3.0, min(30.0, _f(os.environ.get("NIJA_EXIT_JIT_PROOF_TTL_S"), 15.0)))
    with _JIT_LOCK:
        cached = _JIT_ROWS.get(key)
    if cached is not None:
        at, quantities, cached_source = cached
        age = max(0.0, time.monotonic() - at)
        if age <= ttl and target in quantities and quantities[target] > 0.0:
            return True, quantities[target], cached_source, age

    _start_jit_refresh(broker)
    return False, 0.0, "jit_refresh_scheduled", float("inf")


def _quantity_matches(left: float, right: float) -> bool:
    tolerance = max(1e-10, abs(right) * 1e-6)
    return abs(left - right) <= tolerance


def _patch_v323_proof() -> bool:
    v323 = importlib.import_module("bot.runtime_universal_exit_tracker_convergence_v323_patch")
    current = getattr(v323, "_position_exit_proof", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PROOF_PATCH_ATTR, False)):
        return True

    @wraps(current)
    def jit_position_exit_proof(universal: ModuleType, broker: Any, pos: Mapping[str, Any]):
        safe, reason, details = current(universal, broker, pos)
        if safe:
            return safe, reason, details
        if reason not in {
            "authoritative_snapshot_missing",
            "authoritative_snapshot_stale",
            "authoritative_snapshot_invalid",
        }:
            return safe, reason, details

        symbol = universal.auto_exit._sym(pos.get("symbol"))
        tracker_qty = universal.auto_exit._quantity(dict(pos))
        ok, auth_qty, source, age = _jit_quantity(broker, symbol)
        if not ok:
            merged = dict(details or {})
            merged.update({"jit_source": source, "jit_age_s": age})
            return False, f"{reason}+{source}", merged
        if not _quantity_matches(tracker_qty, auth_qty):
            return False, "jit_authoritative_quantity_mismatch", {
                "tracker_quantity": tracker_qty,
                "authoritative_quantity": auth_qty,
                "jit_source": source,
                "jit_age_s": age,
            }

        LOGGER.critical(
            "CAPITAL_RECYCLE_V330_EXIT_PROOF_RECOVERED marker=%s venue=%s account=%s symbol=%s "
            "tracker_qty=%.12f authoritative_qty=%.12f source=%s age_s=%.3f "
            "cost_basis_verified=true stale_v285_not_promoted=true position_fabricated=false "
            "fill_confirmation_required=true safety_gates_bypassed=false",
            MARKER,
            universal.auto_exit._broker_label(broker),
            universal._account_label(broker),
            symbol,
            tracker_qty,
            auth_qty,
            source,
            age,
        )
        return True, "verified_jit_authoritative_position", {
            "tracker_quantity": tracker_qty,
            "authoritative_quantity": auth_qty,
            "jit_source": source,
            "jit_age_s": age,
        }

    setattr(jit_position_exit_proof, _PROOF_PATCH_ATTR, True)
    setattr(jit_position_exit_proof, "__wrapped__", current)
    v323._position_exit_proof = jit_position_exit_proof
    return True


def _held_minutes(pos: Mapping[str, Any]) -> float:
    raw = (
        pos.get("first_entry_time") or pos.get("entry_time") or pos.get("opened_at")
        or pos.get("created_at") or pos.get("entry_timestamp")
    )
    if raw is None:
        return 0.0
    try:
        if isinstance(raw, (int, float)):
            stamp = float(raw)
            if stamp > 1e12:
                stamp /= 1000.0
            return max(0.0, (time.time() - stamp) / 60.0)
        if isinstance(raw, datetime):
            dt = raw
        else:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 60.0)
    except Exception:
        return 0.0


def _meets(market: float, target: float, short: bool) -> bool:
    return market <= target if short else market >= target


def _recycle_target(v68: ModuleType, universal: ModuleType, broker: Any, pos: Mapping[str, Any]) -> tuple[float, str, dict[str, Any]]:
    break_even, net_target, details = v68._floors(universal, broker, pos)
    if break_even <= 0.0 or net_target <= 0.0:
        return 0.0, "unproven_floor", details

    free_balance, balance_source = _cached_free_balance(broker)
    reserve = _reserve_usd(broker)
    starved = free_balance is not None and free_balance + 1e-9 < reserve
    held = _held_minutes(pos)
    decay_start = max(1.0, _f(os.environ.get("NIJA_CAPITAL_RECYCLE_DECAY_START_MIN"), 60.0))
    full_decay = max(decay_start + 1.0, _f(os.environ.get("NIJA_CAPITAL_RECYCLE_FULL_DECAY_MIN"), 180.0))
    short = bool(details.get("short"))

    details = dict(details or {})
    details.update({
        "free_balance": free_balance,
        "balance_source": balance_source,
        "reserve_usd": reserve,
        "capital_starved": starved,
        "held_minutes": held,
        "decay_start_min": decay_start,
        "full_decay_min": full_decay,
    })

    if starved:
        return break_even, "capital_recycle_break_even", details
    if held < decay_start:
        return 0.0, "normal_profit_window", details

    progress = min(1.0, max(0.0, (held - decay_start) / (full_decay - decay_start)))
    if short:
        target = net_target + (break_even - net_target) * progress
    else:
        target = net_target - (net_target - break_even) * progress
    return target, "aged_profit_target_decay", details


def _patch_universal_trigger() -> bool:
    universal = importlib.import_module("bot.universal_broker_exit_supervisor_patch")
    v68 = importlib.import_module("bot.universal_net_profit_exit_floor_v68_patch")
    v323 = importlib.import_module("bot.runtime_universal_exit_tracker_convergence_v323_patch")
    current = getattr(universal, "_trigger", None)
    if not callable(current):
        return False
    if bool(getattr(current, _EXIT_PATCH_ATTR, False)):
        return True

    @wraps(current)
    def capital_recycle_trigger(broker: Any, pos: dict[str, Any], market: float):
        hit, reason, target = current(broker, pos, market)
        if hit:
            return hit, reason, target

        safe, proof_reason, proof_details = v323._position_exit_proof(universal, broker, pos)
        if not safe:
            return False, "", 0.0

        recycle_target, recycle_reason, details = _recycle_target(v68, universal, broker, pos)
        if recycle_target <= 0.0:
            return False, "", 0.0
        short = bool(details.get("short"))
        if not _meets(float(market), float(recycle_target), short):
            return False, "", 0.0

        LOGGER.critical(
            "CAPITAL_RECYCLE_V330_EXIT_TRIGGER marker=%s venue=%s account=%s symbol=%s reason=%s "
            "market=%.8f target=%.8f break_even=%.8f normal_net_target=%.8f held_min=%.1f "
            "free_balance=%s reserve_usd=%.2f capital_starved=%s balance_source=%s proof=%s "
            "estimated_all_in_break_even=true stop_loss_unchanged=true fill_confirmation_required=true "
            "forced_loss_exit=false safety_gates_bypassed=false",
            MARKER,
            universal.auto_exit._broker_label(broker),
            universal._account_label(broker),
            universal.auto_exit._sym(pos.get("symbol")),
            recycle_reason,
            float(market),
            float(recycle_target),
            float(details.get("break_even", 0.0)),
            float(details.get("net_target", 0.0)),
            float(details.get("held_minutes", 0.0)),
            "unproven" if details.get("free_balance") is None else f"{float(details.get('free_balance')):.2f}",
            float(details.get("reserve_usd", 0.0)),
            str(bool(details.get("capital_starved"))).lower(),
            details.get("balance_source", "unproven"),
            proof_reason,
        )
        return True, recycle_reason, recycle_target

    setattr(capital_recycle_trigger, _EXIT_PATCH_ATTR, True)
    setattr(capital_recycle_trigger, "__wrapped__", current)
    universal._trigger = capital_recycle_trigger
    return True


def _planned_notional(result: Mapping[str, Any]) -> float | None:
    for key in (
        "size_usd", "trade_size_usd", "position_size_usd", "notional_usd",
        "amount_usd", "order_size_usd", "requested_notional_usd",
    ):
        value = _f(result.get(key), -1.0)
        if value > 0.0:
            return value
    metadata = result.get("metadata")
    if isinstance(metadata, Mapping):
        for key in (
            "size_usd", "trade_size_usd", "position_size_usd", "notional_usd",
            "amount_usd", "order_size_usd", "requested_notional_usd",
        ):
            value = _f(metadata.get(key), -1.0)
            if value > 0.0:
                return value
    return None


def _patch_entry_reserve() -> bool:
    v69 = importlib.import_module("bot.live_entry_expectancy_authority_v69_patch")
    current = getattr(v69, "_validate_live_entry", None)
    if not callable(current):
        return False
    if bool(getattr(current, _ENTRY_PATCH_ATTR, False)):
        return True

    @wraps(current)
    def validate_with_capital_reserve(strategy: Any, df: Any, symbol: str, result: Mapping[str, Any]):
        ok, reason, details = current(strategy, df, symbol, result)
        if not ok:
            return ok, reason, details
        action = _norm(result.get("action"))
        if action not in {"enter_long", "enter_short", "buy", "short"}:
            return ok, reason, details

        broker = getattr(strategy, "broker_client", None) or getattr(strategy, "broker", None)
        if broker is None:
            return ok, reason, details
        free_balance, source = _cached_free_balance(broker)
        if free_balance is None:
            # Do not fabricate balance. Downstream canonical capital authorization
            # remains authoritative when no cache-backed free balance is proven.
            return ok, reason, details

        reserve = _reserve_usd(broker)
        planned = _planned_notional(result)
        remaining = free_balance if planned is None else free_balance - planned
        merged = dict(details or {})
        merged.update({
            "free_balance": free_balance,
            "capital_reserve_usd": reserve,
            "planned_notional_usd": planned,
            "post_entry_free_balance": remaining,
            "capital_balance_source": source,
        })
        if free_balance + 1e-9 <= reserve:
            return False, "capital_reserve_already_constrained", merged
        if planned is not None and remaining + 1e-9 < reserve:
            return False, "entry_would_consume_capital_reserve", merged
        return ok, reason, merged

    setattr(validate_with_capital_reserve, _ENTRY_PATCH_ATTR, True)
    setattr(validate_with_capital_reserve, "__wrapped__", current)
    v69._validate_live_entry = validate_with_capital_reserve
    return True


def _install_base_exit_stack() -> bool:
    requirements = (
        ("bot.universal_exit_fill_reconciliation_v67_patch", None),
        ("bot.universal_net_profit_exit_floor_v68_patch", None),
        ("bot.adaptive_profit_exit_v74_patch", None),
        ("bot.runtime_universal_exit_tracker_convergence_v323_patch", "NIJA_RUNTIME_UNIVERSAL_EXIT_TRACKER_CONVERGENCE_V323_READY"),
    )
    for module_name, ready_env in requirements:
        module = importlib.import_module(module_name)
        installer = getattr(module, "install_import_hook", None) or getattr(module, "install", None)
        if not callable(installer) or installer() is False:
            return False
        if ready_env and os.environ.get(ready_env) != "1":
            return False
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_capital_recycling_exit_v330"] = _READY_FLAG
        return True
    except Exception:
        return False


def install_import_hook() -> bool:
    with _LOCK:
        if getattr(builtins, _INSTALL_FLAG, False) and os.environ.get(_READY_FLAG) == "1":
            return True
        try:
            base_ready = _install_base_exit_stack()
            proof_ready = _patch_v323_proof() if base_ready else False
            exit_ready = _patch_universal_trigger() if proof_ready else False
            entry_ready = _patch_entry_reserve() if exit_ready else False
            manifest_ready = _register_manifest()
            ready = bool(base_ready and proof_ready and exit_ready and entry_ready and manifest_ready)
        except Exception as exc:
            ready = False
            LOGGER.exception(
                "RUNTIME_CAPITAL_RECYCLING_EXIT_V330_INSTALL_FAILED marker=%s error=%s:%s "
                "trading_fail_closed=true forced_exit=false safety_gates_bypassed=false",
                MARKER, type(exc).__name__, exc,
            )

        os.environ[_READY_FLAG] = "1" if ready else "0"
        setattr(builtins, _INSTALL_FLAG, ready)
        log = LOGGER.critical if ready else LOGGER.error
        log(
            "RUNTIME_CAPITAL_RECYCLING_EXIT_V330_%s marker=%s ready=%s "
            "all_account_exit_stack_required=true jit_exit_position_proof=true "
            "kraken_authenticated_balance_reuse=true global_snapshot_ttl_unchanged=true "
            "capital_starvation_break_even_harvest=true aged_profit_target_decay=true "
            "entry_free_cash_reserve=true long_short_spot_compatible=true "
            "cost_basis_required=true quantity_match_required=true fill_confirmation_required=true "
            "stop_loss_preserved=true trailing_stop_preserved=true trailing_profit_preserved=true "
            "minimum_order_unchanged=true writer_nonce_risk_killswitch_gates_unchanged=true "
            "forced_loss_exit=false safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY",
            MARKER,
            str(ready).lower(),
        )
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER", "RELEASE_ID", "install", "install_import_hook",
    "_reserve_usd", "_cached_free_balance", "_jit_quantity", "_recycle_target",
]
