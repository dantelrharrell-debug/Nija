"""Broker-aware position liveness and exact-close contract convergence (v342).

This repair addresses two production regressions without weakening execution safety:

1. v117 applied one 12-second position-fetch budget to every broker.  Coinbase
   routinely completed after that deadline and Kraken can intentionally pre-wait
   private reads for rate-limit fairness.  v342 keeps bounded single-flight reads,
   late-generation rejection, and fail-closed readiness, but gives each broker a
   budget aligned with its observed/API pacing characteristics.
2. ECEL could turn a trusted reduce-only close quantity into a larger synthetic
   quantity while trying to satisfy minimum notional.  v342 makes verified unit-
   sized closes quantity-authoritative: the compiler may round DOWN to the venue
   grid, but may never increase the held quantity.  If the entire verified holding
   is below a genuine venue minimum, the close is rejected as explicit dust rather
   than manufacturing a larger sell.

Kraken contract metadata remains authoritative.  When AssetPairs supplies an
explicit positive costmin below NIJA's legacy $10 fallback, v342 adopts that exact
pair-specific value.  Missing/invalid costmin never lowers an existing rule.

No readiness, capital, position, order acknowledgement, fill, or profit is
fabricated.  Writer, nonce, risk, kill-switch, balance, exchange-constraint and
fill-confirmation gates remain unchanged.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from decimal import Decimal
from functools import wraps
from typing import Any, Callable

LOGGER = logging.getLogger("nija.runtime_execution_convergence_v342")
MARKER = "20260901-runtime-execution-convergence-v342"
RELEASE_ID = "20260901-runtime-convergence-v342"
_READY_FLAG = "NIJA_RUNTIME_EXECUTION_CONVERGENCE_V342_READY"
_POSITION_ATTR = "_nija_position_fetch_broker_budget_v342"
_ECEL_ATTR = "_nija_exact_close_contract_v342"
_SCHEMA_ATTR = "_nija_kraken_pair_costmin_v342"

_LOCK = threading.RLock()
_FLIGHTS: dict[int, dict[str, Any]] = {}
_GENERATIONS: dict[int, int] = {}

_DEFAULT_TIMEOUT = {
    "coinbase": 45.0,
    "kraken": 90.0,
    "okx": 25.0,
    "alpaca": 25.0,
}
_DEFAULT_STALE = {
    "coinbase": 60.0,
    "kraken": 120.0,
    "okx": 40.0,
    "alpaca": 40.0,
}


def _env_float(name: str, default: float, low: float, high: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


def _timeout_s(broker: str) -> float:
    key = str(broker or "").strip().lower()
    default = _DEFAULT_TIMEOUT.get(key, 45.0)
    return _env_float(f"NIJA_POSITION_FETCH_TIMEOUT_{key.upper()}_S", default, 1.0, 180.0)


def _stale_after_s(broker: str) -> float:
    key = str(broker or "").strip().lower()
    timeout = _timeout_s(key)
    default = _DEFAULT_STALE.get(key, max(timeout + 15.0, timeout * 1.5))
    configured = _env_float(
        f"NIJA_POSITION_FETCH_STALE_{key.upper()}_S",
        default,
        timeout + 1.0,
        300.0,
    )
    return max(timeout + 1.0, configured)


def _unwrap_position_method(method: Callable[..., Any]) -> Callable[..., Any]:
    current = method
    seen: set[int] = set()
    while callable(current) and id(current) not in seen:
        seen.add(id(current))
        if (
            getattr(current, "_nija_position_fetch_generation_v117", False)
            or getattr(current, "_nija_position_sync_core_handoff_v95", False)
            or getattr(current, _POSITION_ATTR, False)
        ):
            wrapped = getattr(current, "__wrapped__", None)
            if callable(wrapped):
                current = wrapped
                continue
        break
    return current


def _finish_flight(
    flight: dict[str, Any],
    raw: Callable[..., Any],
    self: Any,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> None:
    try:
        flight["result"] = raw(self, *args, **kwargs)
    except BaseException as exc:  # preserve original broker exception exactly
        flight["error"] = exc
    finally:
        flight["finished_at"] = time.monotonic()
        flight["event"].set()


def _broker_bounded_generation(method: Callable[..., Any], broker: str) -> Callable[..., Any]:
    raw = _unwrap_position_method(method)
    broker_key = str(broker or "unknown").strip().lower()

    @wraps(method)
    def get_positions_v342(self: Any, *args: Any, **kwargs: Any):
        key = id(self)
        now = time.monotonic()
        timeout = _timeout_s(broker_key)
        stale_after = _stale_after_s(broker_key)
        with _LOCK:
            flight = _FLIGHTS.get(key)
            started_new = False
            if flight is not None and not flight["event"].is_set():
                age = max(0.0, now - float(flight.get("started_at", now)))
                if age >= stale_after:
                    flight["superseded"] = True
                    LOGGER.critical(
                        "POSITION_FETCH_V342_GENERATION_SUPERSEDED marker=%s broker=%s generation=%s age_s=%.2f stale_after_s=%.2f late_result_discarded=true synthetic_success=false",
                        MARKER, broker_key, flight.get("generation"), age, stale_after,
                    )
                    flight = None
            elif flight is not None and flight["event"].is_set():
                _FLIGHTS.pop(key, None)
                flight = None

            if flight is None:
                generation = int(_GENERATIONS.get(key, 0)) + 1
                _GENERATIONS[key] = generation
                flight = {
                    "event": threading.Event(),
                    "result": None,
                    "error": None,
                    "started_at": time.monotonic(),
                    "finished_at": 0.0,
                    "generation": generation,
                    "superseded": False,
                    "broker": broker_key,
                }
                _FLIGHTS[key] = flight
                thread = threading.Thread(
                    target=_finish_flight,
                    args=(flight, raw, self, args, dict(kwargs)),
                    name=f"position-fetch-v342-{broker_key}-g{generation}",
                    daemon=True,
                )
                flight["thread"] = thread
                thread.start()
                started_new = True

        if not flight["event"].wait(timeout=timeout):
            age = max(0.0, time.monotonic() - float(flight.get("started_at", 0.0) or 0.0))
            LOGGER.warning(
                "POSITION_FETCH_V342_TIMEOUT marker=%s broker=%s generation=%s timeout_s=%.2f age_s=%.2f single_flight_reused=%s synthetic_empty_snapshot=false trading_fail_closed=true",
                MARKER, broker_key, flight.get("generation"), timeout, age,
                str(not started_new).lower(),
            )
            raise TimeoutError(
                f"position snapshot timed out for {broker_key} after {timeout:.2f}s generation={flight.get('generation')}"
            )

        with _LOCK:
            current = _FLIGHTS.get(key)
            authoritative = current is flight and not bool(flight.get("superseded"))
            if authoritative:
                _FLIGHTS.pop(key, None)

        if not authoritative:
            LOGGER.warning(
                "POSITION_FETCH_V342_STALE_RESULT_DISCARDED marker=%s broker=%s generation=%s current_generation=%s synthetic_success=false",
                MARKER, broker_key, flight.get("generation"),
                current.get("generation") if isinstance(current, dict) else "none",
            )
            raise TimeoutError(
                f"stale position snapshot generation discarded for {broker_key} generation={flight.get('generation')}"
            )

        error = flight.get("error")
        if error is not None:
            raise error
        return flight.get("result")

    setattr(get_positions_v342, _POSITION_ATTR, True)
    # Mark the reconciled wrapper as satisfying v117 so later install reassertions
    # do not place the old global-budget wrapper back on top.
    setattr(get_positions_v342, "_nija_position_fetch_generation_v117", True)
    setattr(get_positions_v342, "__wrapped__", raw)
    return get_positions_v342


def _patch_position_budgets() -> bool:
    try:
        from bot import broker_manager as module
    except Exception:
        return False

    ready = True
    found = False
    for class_name in ("CoinbaseBroker", "KrakenBroker", "OKXBroker", "AlpacaBroker"):
        cls = getattr(module, class_name, None)
        if not isinstance(cls, type):
            continue
        method = getattr(cls, "get_positions", None)
        if not callable(method):
            continue
        found = True
        broker = class_name.replace("Broker", "").lower()
        if not getattr(method, _POSITION_ATTR, False):
            setattr(cls, "get_positions", _broker_bounded_generation(method, broker))
        installed = getattr(getattr(cls, "get_positions", None), _POSITION_ATTR, False)
        ready = ready and bool(installed)
        if installed:
            LOGGER.critical(
                "POSITION_FETCH_V342_BROKER_BUDGET marker=%s broker=%s timeout_s=%.2f stale_after_s=%.2f single_flight=true late_generation_discard=true synthetic_success=false",
                MARKER, broker, _timeout_s(broker), _stale_after_s(broker),
            )
    return bool(found and ready)


def _patch_kraken_pair_costmin() -> bool:
    try:
        from bot import ecel_execution_compiler as module
    except Exception:
        return False
    cls = getattr(module, "ContractSchemaMap", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "_refresh_kraken", None)
    if not callable(current):
        return False
    if getattr(current, _SCHEMA_ATTR, False):
        return True

    @wraps(current)
    def _refresh_kraken_v342(self: Any) -> int:
        updated = int(current(self) or 0)
        try:
            payload = self._fetch_json("https://api.kraken.com/0/public/AssetPairs")
            result = payload.get("result") if isinstance(payload, dict) else None
            if not isinstance(result, dict):
                return updated
            corrected = 0
            for info in result.values():
                if not isinstance(info, dict):
                    continue
                if "costmin" not in info:
                    continue
                try:
                    explicit_costmin = float(str(info.get("costmin")))
                except Exception:
                    continue
                if explicit_costmin <= 0.0:
                    continue
                symbol_src = str(info.get("wsname") or info.get("altname") or "")
                if not symbol_src:
                    continue
                symbol = self._norm_symbol(symbol_src)
                existing = self.get_rule("kraken", symbol)
                if existing is None:
                    continue
                if explicit_costmin >= float(existing.min_notional_usd):
                    continue
                rule = module.ContractRule(
                    broker=existing.broker,
                    symbol=existing.symbol,
                    base_asset=existing.base_asset,
                    quote_asset=existing.quote_asset,
                    min_notional_usd=explicit_costmin,
                    min_base_size=existing.min_base_size,
                    base_step_size=existing.base_step_size,
                    price_step_size=existing.price_step_size,
                    base_precision=existing.base_precision,
                    price_precision=existing.price_precision,
                    max_base_size=existing.max_base_size,
                )
                self.upsert_rule(rule)
                corrected += 1
            if corrected:
                LOGGER.critical(
                    "KRAKEN_PAIR_COSTMIN_V342_ADOPTED marker=%s corrected_pairs=%d explicit_assetpairs_only=true missing_costmin_not_lowered=true safety_gates_bypassed=false",
                    MARKER, corrected,
                )
        except Exception as exc:
            LOGGER.warning(
                "KRAKEN_PAIR_COSTMIN_V342_REFRESH_DEFERRED marker=%s error=%s:%s existing_rules_preserved=true trading_fail_closed=true",
                MARKER, type(exc).__name__, exc,
            )
        return updated

    setattr(_refresh_kraken_v342, _SCHEMA_ATTR, True)
    setattr(_refresh_kraken_v342, "__wrapped__", current)
    setattr(cls, "_refresh_kraken", _refresh_kraken_v342)
    return True


def _trusted_exact_close(req: Any) -> bool:
    side = str(getattr(req, "side", "") or "").strip().lower()
    if side != "sell":
        return False
    if str(getattr(req, "sizing_mode", "") or "").strip().lower() != "units":
        return False
    try:
        units = float(getattr(req, "desired_units", 0.0) or 0.0)
    except Exception:
        return False
    if units <= 0.0:
        return False
    if bool(getattr(req, "reduce_only", False)):
        return True
    intent = str(getattr(req, "intent_type", "") or "").strip().lower()
    return intent in {"close", "exit", "reduce", "close_only", "protective_exit"}


def _patch_ecel_exact_close() -> bool:
    try:
        from bot import ecel_execution_compiler as module
    except Exception:
        return False
    cls = getattr(module, "ECELExecutionCompiler", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "compile", None)
    if not callable(current):
        return False
    if getattr(current, _ECEL_ATTR, False):
        return True

    @wraps(current)
    def compile_v342(self: Any, req: Any):
        if not _trusted_exact_close(req):
            return current(self, req)

        broker = str(getattr(req, "broker", "coinbase") or "coinbase").strip().lower()
        side = "sell"
        symbol = self._normalize_symbol(str(getattr(req, "symbol", "") or ""), broker)
        order_type = str(getattr(req, "order_type", "MARKET") or "MARKET").strip().upper()
        if order_type not in {"MARKET", "LIMIT"}:
            return current(self, req)
        try:
            price_hint = float(getattr(req, "price_hint_usd", 0.0) or 0.0)
            requested_units = float(getattr(req, "desired_units", 0.0) or 0.0)
        except Exception:
            return current(self, req)
        if price_hint <= 0.0 or requested_units <= 0.0:
            return current(self, req)

        self.schema.refresh_if_due(target_broker=broker)
        rule = self.schema.get_rule(broker, symbol)
        if rule is None:
            return self._reject("NO_CONTRACT_RULE", broker, symbol, side, None, attempted_broker=broker)

        compiled_price = self.precision.compile_price(price_hint, side, rule)
        compiled_base = self.precision.compile_base_size(requested_units, rule)
        # Quantity-authoritative invariant: never increase a close above the
        # verified units supplied by the caller.
        if compiled_base > requested_units + 1e-12:
            return self._reject(
                "CLOSE_QUANTITY_INFLATION_BLOCKED", broker, symbol, side, rule,
                requested_units=requested_units, compiled_units=compiled_base,
            )
        if compiled_base <= 0.0 or compiled_base < float(rule.min_base_size):
            return self._reject(
                "CLOSE_BELOW_MIN_BASE_DUST", broker, symbol, side, rule,
                requested_units=requested_units, compiled_units=compiled_base,
                min_base_size=rule.min_base_size,
            )

        compiled_notional = float(Decimal(str(compiled_base)) * Decimal(str(compiled_price)))
        if compiled_notional + 1e-12 < float(rule.min_notional_usd):
            return self._reject(
                "CLOSE_BELOW_MIN_NOTIONAL_DUST", broker, symbol, side, rule,
                requested_units=requested_units, compiled_units=compiled_base,
                compiled_notional=compiled_notional,
                min_notional=rule.min_notional_usd,
            )

        compiled_order = module.CompiledOrder(
            symbol=symbol,
            side=side,
            qty=Decimal(str(compiled_base)),
            price=Decimal(str(compiled_price)),
            valid=True,
            reason=None,
        )
        LOGGER.critical(
            "EXACT_CLOSE_CONTRACT_V342_ACCEPTED marker=%s broker=%s symbol=%s requested_units=%.12f compiled_units=%.12f notional=%.8f quantity_inflated=false pair_min_notional=%.8f safety_gates_bypassed=false",
            MARKER, broker, symbol, requested_units, compiled_base, compiled_notional,
            float(rule.min_notional_usd),
        )
        return module.CompileResult(
            accepted=True,
            reason="ACCEPTED",
            broker=broker,
            symbol=symbol,
            side=side,
            compiled_notional_usd=compiled_notional,
            compiled_base_size=compiled_base,
            compiled_price_usd=compiled_price,
            reservation_id=None,
            rule=rule,
            compiled_order=compiled_order,
            diagnostics={
                "requested_units": requested_units,
                "compiled_units": compiled_base,
                "quantity_inflated": 0.0,
            },
        )

    setattr(compile_v342, _ECEL_ATTR, True)
    setattr(compile_v342, "__wrapped__", current)
    setattr(cls, "compile", compile_v342)
    return True


def install() -> bool:
    position_ready = _patch_position_budgets()
    schema_ready = _patch_kraken_pair_costmin()
    ecel_ready = _patch_ecel_exact_close()
    ready = bool(position_ready and schema_ready and ecel_ready)
    os.environ[_READY_FLAG] = "1" if ready else "0"
    LOGGER.critical(
        "RUNTIME_EXECUTION_CONVERGENCE_V342 marker=%s ready=%s broker_specific_position_budgets=%s kraken_pair_costmin=%s exact_close_quantity_authority=%s stale_position_success_fabricated=false close_quantity_inflated=false readiness_fabricated=false execution_proof_fabricated=false forced_trade=false forced_activation=false safety_gates_bypassed=false",
        MARKER, str(ready).lower(), str(position_ready).lower(),
        str(schema_ready).lower(), str(ecel_ready).lower(),
    )
    return ready


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER", "RELEASE_ID", "install", "install_import_hook",
    "_timeout_s", "_stale_after_s", "_broker_bounded_generation",
    "_trusted_exact_close", "_patch_position_budgets",
    "_patch_kraken_pair_costmin", "_patch_ecel_exact_close",
]
