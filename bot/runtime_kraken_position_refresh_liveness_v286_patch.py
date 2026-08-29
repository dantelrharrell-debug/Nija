"""Kraken authoritative position refresh liveness and read-admission repair v286.

Production deployment d4f9e91f on 2026-08-29 proved that v285 correctly
fail-closed stale/missing Kraken position proof while Coinbase and OKX were
current. The remaining Kraken-specific liveness gap has two causes:

* Kraken private monitoring rate-limit sleep occurs inside the process-wide API
  lock. A MICRO_CAP monitoring interval can therefore hold that global lock for
  tens of seconds while platform and user Balance readers fail their bounded
  lock-admission window.
* KrakenBroker.get_positions() is a strategy-oriented view: it may return an
  empty list after local read contention, API errors, missing prices, dust
  filtering, or unsupported-pair filtering. That list cannot be treated as an
  authoritative proof that the account has no holdings.

v286 moves the existing read-only Kraken rate wait in front of the global lock,
without shortening the configured rate interval. It also gives startup position
reconciliation a dedicated authoritative Balance snapshot proxy. Positive
broker balances are enumerated even when price discovery is unavailable; the
existing cost-basis/protective-exit adoption path must still verify each holding
before coverage can become ready.

The authoritative Balance call is single-flight and bounded to callers. A late
result is reused rather than duplicated. Local read contention, API errors,
invalid payloads and timeouts raise/fail closed and can never become a synthetic
empty position snapshot. When a previously missing/stale Kraken proof genuinely
recovers, v286 requests the existing canonical capital refresh path so the
separate 3/3 capital publication can converge from real broker data.

No connectivity, position, cost basis, balance, capital, writer, nonce,
execution, order, fill, or exit-protection truth is fabricated. Mutating Kraken
calls retain their existing serialization and timeout behavior. All existing
risk, kill-switch, ECEL, minimum-notional, writer, nonce, capital, order and fill
gates remain authoritative.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from collections.abc import Mapping
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_kraken_position_refresh_liveness_v286")
MARKER = "20260829-kraken-position-refresh-liveness-v286"
RELEASE_ID = "20260829-runtime-convergence-v286"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_POSITION_REFRESH_LIVENESS_V286_READY"
_PATCH_ATTR = "_nija_kraken_position_refresh_liveness_v286"
_LOCK = threading.RLock()
_INSTANCE_GATE_LOCK = threading.RLock()
_AUTH_LOCK = threading.RLock()
_CAPITAL_WAKE_LOCK = threading.Lock()
_MONITOR_STOP = threading.Event()
_MONITOR_THREAD: threading.Thread | None = None
_MONITOR_RESTARTS = 0
_AUTH_FLIGHTS: dict[int, dict[str, Any]] = {}
_LAST_PROOF_READY: dict[int, bool] = {}
_LAST_CAPITAL_WAKE_AT = 0.0
_LAST_STATE_SIGNATURE = ""


def _float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return default if number != number else number
    except Exception:
        return default


def _label(value: Any) -> str:
    raw = getattr(value, "value", value)
    text = str(raw or "").strip().lower()
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text


def _connected(broker: Any) -> bool:
    if broker is None:
        return False
    try:
        value = getattr(broker, "connected", False)
        return bool(value() if callable(value) else value)
    except Exception:
        return False


def _is_kraken_broker(broker: Any) -> bool:
    if broker is None:
        return False
    if _label(getattr(broker, "broker_type", "")) == "kraken":
        return True
    return type(broker).__name__.lower() == "krakenbroker"


def _auth_wait_s() -> float:
    try:
        value = float(os.environ.get("NIJA_KRAKEN_AUTHORITATIVE_POSITION_WAIT_S", "5") or 5.0)
    except (TypeError, ValueError):
        value = 5.0
    return max(1.0, min(15.0, value))


def _monitor_interval_s() -> float:
    try:
        value = float(os.environ.get("NIJA_KRAKEN_POSITION_LIVENESS_POLL_S", "5") or 5.0)
    except (TypeError, ValueError):
        value = 5.0
    return max(2.0, min(30.0, value))


def _capital_wake_debounce_s() -> float:
    try:
        value = float(os.environ.get("NIJA_KRAKEN_POSITION_CAPITAL_WAKE_DEBOUNCE_S", "20") or 20.0)
    except (TypeError, ValueError):
        value = 20.0
    return max(5.0, min(120.0, value))


def _busy_seq(broker: Any) -> int:
    try:
        return max(0, int(getattr(broker, "_nija_kraken_local_read_busy_seq_v242", 0) or 0))
    except Exception:
        return 0


def _chain_has_exact(callable_obj: Any, expected_name: str | None = None) -> bool:
    seen: set[int] = set()
    current = callable_obj
    for _ in range(64):
        if not callable(current) or id(current) in seen:
            return False
        seen.add(id(current))
        owner = getattr(current, "__globals__", {}) or {}
        if bool(getattr(current, _PATCH_ATTR, False)) and owner.get("MARKER") == MARKER:
            if expected_name is None or str(getattr(current, "__name__", "")) == expected_name:
                return True
        current = getattr(current, "__wrapped__", None)
    return False


def _broker_module() -> Any:
    return importlib.import_module("bot.broker_manager")


def _mutating_methods() -> set[str]:
    try:
        values = getattr(_broker_module(), "_KRAKEN_NONCE_MUTATING_METHODS", set())
        return {str(value) for value in set(values or ())}
    except Exception:
        return {"AddOrder", "AddOrderBatch", "CancelOrder", "CancelOrderBatch", "CancelAll", "CancelAllOrdersAfter", "EditOrder"}


def _category_from_call(broker: Any, method: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    category = kwargs.get("category")
    if category is None and len(args) >= 3:
        category = args[2]
    if category is not None:
        return category
    try:
        module = _broker_module()
        resolver = getattr(module, "get_category_for_method", None)
        if callable(resolver):
            return resolver(method)
        enum_cls = getattr(module, "KrakenAPICategory", None)
        return getattr(enum_cls, "MONITORING", None)
    except Exception:
        return None


def _read_rate_delay(broker: Any, method: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> tuple[float, str]:
    if method in _mutating_methods():
        return 0.0, "mutating_unchanged"
    category = _category_from_call(broker, method, args, kwargs)
    profile = getattr(broker, "_kraken_rate_profile", None)
    mode = getattr(broker, "_kraken_rate_mode", None)
    try:
        module = _broker_module()
        calculator = getattr(module, "calculate_min_interval", None)
        enum_cls = getattr(module, "KrakenAPICategory", None)
        if category is not None and profile and callable(calculator):
            minimum = max(0.0, float(calculator(category, mode) or 0.0))
            if enum_cls is not None and isinstance(category, enum_cls):
                key = str(getattr(category, "value", category))
            else:
                key = str(category)
            last_map = getattr(broker, "_last_call_by_category", {})
            last = _float(last_map.get(key, 0.0) if isinstance(last_map, Mapping) else 0.0)
            remaining = minimum - max(0.0, time.time() - last)
            return max(0.0, remaining), key
    except Exception:
        pass
    minimum = max(0.0, _float(getattr(broker, "_min_call_interval", 0.0)))
    last = _float(getattr(broker, "_last_api_call_time", 0.0))
    remaining = minimum - max(0.0, time.time() - last)
    return max(0.0, remaining), "global"


def _instance_rate_gate(broker: Any) -> threading.Lock:
    gate = getattr(broker, "_nija_kraken_read_rate_gate_v286", None)
    if gate is not None and callable(getattr(gate, "acquire", None)):
        return gate
    with _INSTANCE_GATE_LOCK:
        gate = getattr(broker, "_nija_kraken_read_rate_gate_v286", None)
        if gate is None or not callable(getattr(gate, "acquire", None)):
            gate = threading.Lock()
            try:
                setattr(broker, "_nija_kraken_read_rate_gate_v286", gate)
            except Exception:
                pass
        return gate


def _patch_private_read_prewait() -> bool:
    try:
        module = _broker_module()
        cls = getattr(module, "KrakenBroker", None)
    except Exception:
        return False
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "_kraken_private_call", None)
    if not callable(current):
        return False
    if _chain_has_exact(current, "private_v286"):
        return True
    original = current

    @wraps(original)
    def private_v286(self: Any, *args: Any, **kwargs: Any):
        method = str(args[0] if args else kwargs.get("method", "") or "")
        if method in _mutating_methods():
            return original(self, *args, **kwargs)
        gate = _instance_rate_gate(self)
        with gate:
            delay_s, category = _read_rate_delay(self, method, args, kwargs)
            if delay_s > 0.001:
                LOGGER.info(
                    "KRAKEN_READ_PREWAIT_V286 marker=%s account=%s method=%s category=%s delay_s=%.3f global_api_lock_held=false configured_rate_interval_preserved=true mutating_calls_unchanged=true",
                    MARKER,
                    str(getattr(self, "account_identifier", "unknown")),
                    method or "unknown",
                    category,
                    delay_s,
                )
                time.sleep(delay_s)
            return original(self, *args, **kwargs)

    private_v286.__name__ = "private_v286"
    setattr(private_v286, _PATCH_ATTR, True)
    setattr(private_v286, "__wrapped__", original)
    cls._kraken_private_call = private_v286
    return True


def _normalise_asset(broker: Any, asset: Any) -> str:
    normaliser = getattr(broker, "_normalize_kraken_asset_code", None)
    if callable(normaliser):
        try:
            return str(normaliser(asset) or "").strip().upper()
        except Exception:
            pass
    token = str(asset or "").strip().upper().split(".", 1)[0]
    if len(token) > 3 and token[:1] in {"X", "Z"}:
        token = token[1:]
    return {"XBT": "BTC", "XDG": "DOGE"}.get(token, token)


def _cached_price(broker: Any, symbol: str) -> float:
    cache = getattr(broker, "_price_cache", None)
    if not isinstance(cache, Mapping):
        return 0.0
    row = cache.get(symbol)
    if isinstance(row, Mapping):
        return max(0.0, _float(row.get("price")))
    return max(0.0, _float(row))


def _build_authoritative_rows(broker: Any, result: Mapping[str, Any]) -> list[dict[str, Any]]:
    fiat = {"USD", "USDT", "USDC", "EUR", "GBP", "CAD", "AUD", "JPY"}
    try:
        fiat.update(str(value).upper() for value in set(getattr(broker, "_FIAT_ASSETS", set()) or ()))
    except Exception:
        pass
    rows: list[dict[str, Any]] = []
    for raw_asset, raw_quantity in result.items():
        quantity = _float(raw_quantity)
        if quantity <= 0.0:
            continue
        asset = _normalise_asset(broker, raw_asset)
        if not asset or asset in fiat:
            continue
        symbol = f"{asset}-USD"
        supports = getattr(broker, "supports_symbol", None)
        try:
            tradable = bool(supports(symbol)) if callable(supports) else True
        except Exception:
            tradable = False
        price = _cached_price(broker, symbol)
        rows.append({
            "symbol": symbol,
            "quantity": quantity,
            "currency": asset,
            "current_price": price,
            "size_usd": quantity * price if price > 0.0 else 0.0,
            "authoritative_balance": True,
            "tradable": tradable,
            "pricing_verified": price > 0.0,
            "raw_asset": str(raw_asset or ""),
        })
    rows.sort(key=lambda row: str(row.get("symbol", "")))
    return rows


def _v285() -> Any:
    return importlib.import_module("bot.runtime_authoritative_position_coverage_v285_patch")


def _record_snapshot_failure(broker: Any, reason: str) -> None:
    try:
        recorder = getattr(_v285(), "_record_snapshot_failure", None)
        if callable(recorder):
            recorder(broker, reason)
    except Exception:
        pass


def _record_snapshot_success(broker: Any, rows: list[dict[str, Any]]) -> None:
    v285 = _v285()
    recorder = getattr(v285, "_record_snapshot_success", None)
    if not callable(recorder) or not bool(recorder(broker, rows)):
        raise RuntimeError("v285_authoritative_snapshot_record_failed")
    generation = int(getattr(broker, "_nija_authoritative_position_snapshot_generation_v285", 0) or 0)
    try:
        setattr(broker, "_nija_authoritative_position_raw_rows_v286", tuple(dict(row) for row in rows))
        setattr(broker, "_nija_authoritative_position_raw_generation_v286", generation)
    except Exception:
        pass


def _fetch_authoritative_rows_sync(broker: Any) -> list[dict[str, Any]]:
    if broker is None or not _connected(broker):
        raise RuntimeError("kraken_broker_not_connected")
    private_call = getattr(broker, "_kraken_private_call", None)
    if not callable(private_call):
        raise RuntimeError("kraken_private_call_unavailable")
    before_seq = _busy_seq(broker)
    category = _category_from_call(broker, "Balance", ("Balance",), {})
    try:
        response = private_call("Balance", category=category)
    except BaseException as exc:
        _record_snapshot_failure(broker, f"{type(exc).__name__}:{exc}")
        raise
    after_seq = _busy_seq(broker)
    if after_seq > before_seq:
        reason = f"local_read_contention_during_authoritative_position_fetch:{before_seq}->{after_seq}"
        _record_snapshot_failure(broker, reason)
        raise RuntimeError(reason)
    if not isinstance(response, Mapping):
        reason = f"invalid_kraken_balance_payload:{type(response).__name__}"
        _record_snapshot_failure(broker, reason)
        raise RuntimeError(reason)
    errors = response.get("error")
    if errors:
        reason = "kraken_balance_error:" + ",".join(str(value) for value in list(errors))
        _record_snapshot_failure(broker, reason)
        raise RuntimeError(reason)
    result = response.get("result")
    if not isinstance(result, Mapping):
        reason = f"kraken_balance_result_missing:{type(result).__name__}"
        _record_snapshot_failure(broker, reason)
        raise RuntimeError(reason)
    rows = _build_authoritative_rows(broker, result)
    _record_snapshot_success(broker, rows)
    LOGGER.critical(
        "KRAKEN_AUTHORITATIVE_BALANCE_V286_FETCHED marker=%s account=%s held_assets=%d authoritative_balance=true price_required_for_enumeration=false dust_hidden=false unsupported_hidden=false synthetic_empty=false",
        MARKER,
        str(getattr(broker, "account_identifier", "unknown")),
        len(rows),
    )
    return rows


def _finish_auth_flight(flight: dict[str, Any], broker: Any) -> None:
    try:
        flight["result"] = _fetch_authoritative_rows_sync(broker)
    except BaseException as exc:
        flight["error"] = exc
    finally:
        flight["finished_at"] = time.monotonic()
        flight["event"].set()


def _authoritative_positions(broker: Any) -> list[dict[str, Any]]:
    key = id(broker)
    with _AUTH_LOCK:
        flight = _AUTH_FLIGHTS.get(key)
        if flight is None:
            flight = {
                "event": threading.Event(),
                "result": None,
                "error": None,
                "started_at": time.monotonic(),
                "finished_at": 0.0,
            }
            _AUTH_FLIGHTS[key] = flight
            thread = threading.Thread(
                target=_finish_auth_flight,
                args=(flight, broker),
                name=f"kraken-authoritative-position-v286-{getattr(broker, 'account_identifier', key)}",
                daemon=True,
            )
            flight["thread"] = thread
            thread.start()
            started = True
        else:
            started = False
    wait_s = _auth_wait_s()
    if not flight["event"].wait(wait_s):
        age = max(0.0, time.monotonic() - _float(flight.get("started_at")))
        raise TimeoutError(
            f"Kraken authoritative position Balance pending after {wait_s:.1f}s age={age:.1f}s single_flight_reused={str(not started).lower()}"
        )
    error = flight.get("error")
    result = flight.get("result")
    with _AUTH_LOCK:
        if _AUTH_FLIGHTS.get(key) is flight:
            _AUTH_FLIGHTS.pop(key, None)
    if error is not None:
        raise error
    if not isinstance(result, list):
        raise RuntimeError("authoritative_position_flight_invalid_result")
    return [dict(row) for row in result]


class _KrakenAuthoritativeProxy:
    __slots__ = ("_broker",)

    def __init__(self, broker: Any) -> None:
        object.__setattr__(self, "_broker", broker)

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_broker"), name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_broker":
            object.__setattr__(self, name, value)
            return
        setattr(object.__getattribute__(self, "_broker"), name, value)

    def get_positions(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return _authoritative_positions(object.__getattribute__(self, "_broker"))


def _strong_proof(broker: Any) -> tuple[bool, str]:
    try:
        fn = getattr(_v285(), "_strong_broker_proof", None)
        if callable(fn):
            ready, reason = fn(broker)
            return bool(ready), str(reason or "")
    except Exception as exc:
        return False, f"v285_proof_error:{type(exc).__name__}:{exc}"
    return False, "v285_strong_proof_unavailable"


def _capital_wake_worker(source: str) -> None:
    try:
        v32 = importlib.import_module("bot.runtime_execution_convergence_v32")
        request = getattr(v32, "_request_runtime_reconciliation", None)
        refreshed = bool(request("kraken_position_coverage_recovered_v286")) if callable(request) else False
        LOGGER.critical(
            "KRAKEN_POSITION_V286_CAPITAL_WAKE marker=%s source=%s refresh_requested=%s canonical_refresh_only=true capital_ready_granted=false synthetic_balance=false",
            MARKER,
            source,
            str(refreshed).lower(),
        )
    except Exception as exc:
        LOGGER.warning(
            "KRAKEN_POSITION_V286_CAPITAL_WAKE_FAILED marker=%s source=%s error=%s:%s capital_remains_fail_closed=true",
            MARKER,
            source,
            type(exc).__name__,
            exc,
        )
    finally:
        _CAPITAL_WAKE_LOCK.release()


def _schedule_capital_wake(source: str) -> bool:
    global _LAST_CAPITAL_WAKE_AT
    now = time.monotonic()
    with _LOCK:
        if now - _LAST_CAPITAL_WAKE_AT < _capital_wake_debounce_s():
            return False
        if not _CAPITAL_WAKE_LOCK.acquire(blocking=False):
            return False
        _LAST_CAPITAL_WAKE_AT = now
    try:
        threading.Thread(
            target=_capital_wake_worker,
            args=(source,),
            name="KrakenPositionV286CapitalWake",
            daemon=True,
        ).start()
        return True
    except BaseException:
        _CAPITAL_WAKE_LOCK.release()
        raise


def _patch_startup_adopter() -> bool:
    try:
        sync = importlib.import_module("bot.startup_position_sync")
    except Exception:
        return False
    current = getattr(sync, "_adopt_broker_positions", None)
    if not callable(current):
        return False
    if _chain_has_exact(current, "adopt_v286"):
        return True
    original = current

    @wraps(original)
    def adopt_v286(broker: Any, broker_name: str, eps: Any) -> int:
        real = getattr(broker, "_broker", broker)
        if not _is_kraken_broker(real):
            return int(original(broker, broker_name, eps) or 0)
        before_ready, _before_reason = _strong_proof(real)
        proxy = _KrakenAuthoritativeProxy(real)
        try:
            result = int(original(proxy, broker_name, eps) or 0)
        except BaseException as exc:
            _record_snapshot_failure(real, f"{type(exc).__name__}:{exc}")
            raise
        after_ready, after_reason = _strong_proof(real)
        with _LOCK:
            prior = _LAST_PROOF_READY.get(id(real), before_ready)
            _LAST_PROOF_READY[id(real)] = after_ready
        if after_ready and not prior:
            _schedule_capital_wake(str(broker_name or getattr(real, "account_identifier", "kraken")))
            LOGGER.critical(
                "KRAKEN_POSITION_V286_PROOF_RECOVERED marker=%s account=%s reason=%s capital_refresh_wakeup=true synthetic_position=false synthetic_capital=false",
                MARKER,
                str(broker_name or getattr(real, "account_identifier", "kraken")),
                after_reason,
            )
        return result

    adopt_v286.__name__ = "adopt_v286"
    setattr(adopt_v286, _PATCH_ATTR, True)
    setattr(adopt_v286, "__wrapped__", original)
    sync._adopt_broker_positions = adopt_v286
    return True


def _patch_v281_kraken_audit() -> bool:
    try:
        v281 = importlib.import_module("bot.runtime_all_account_position_exit_coverage_v281_patch")
    except Exception:
        return False
    current = getattr(v281, "_account_audit", None)
    if not callable(current):
        return False
    if _chain_has_exact(current, "account_audit_v286"):
        return True
    original = current

    @wraps(original)
    def account_audit_v286(account: str, broker: Any, structural_exit_ready: bool):
        reasons, positions = original(account, broker, structural_exit_ready)
        reasons = list(reasons or [])
        positions = [dict(row) for row in tuple(positions or ()) if isinstance(row, Mapping)]
        if broker is None or not _is_kraken_broker(broker):
            return list(dict.fromkeys(reasons)), positions
        try:
            generation = int(getattr(broker, "_nija_authoritative_position_snapshot_generation_v285", 0) or 0)
            raw_generation = int(getattr(broker, "_nija_authoritative_position_raw_generation_v286", -1) or -1)
            raw_rows = tuple(getattr(broker, "_nija_authoritative_position_raw_rows_v286", ()) or ())
        except Exception:
            generation, raw_generation, raw_rows = 0, -1, ()
        if generation <= 0 or raw_generation != generation:
            return list(dict.fromkeys(reasons)), positions
        raw_by_symbol = {
            str(row.get("symbol", "")).strip().upper(): row
            for row in raw_rows
            if isinstance(row, Mapping) and str(row.get("symbol", "")).strip()
        }
        for symbol, raw in sorted(raw_by_symbol.items()):
            if raw.get("tradable") is False:
                reasons.append(f"held_position_untradable:{symbol}")
        for row in positions:
            symbol = str(row.get("symbol", "")).strip().upper()
            raw = raw_by_symbol.get(symbol)
            if raw is None:
                continue
            row["broker_position_tradable"] = bool(raw.get("tradable", False))
            row["broker_position_pricing_cached"] = bool(raw.get("pricing_verified", False))
            if raw.get("tradable") is False:
                row["protective_exit_verified"] = False
                row["exit_protections_attached"] = ()
        return list(dict.fromkeys(reasons)), positions

    account_audit_v286.__name__ = "account_audit_v286"
    setattr(account_audit_v286, _PATCH_ATTR, True)
    setattr(account_audit_v286, "__wrapped__", original)
    v281._account_audit = account_audit_v286
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_kraken_position_refresh_liveness_v286"] = _READY_FLAG
        return True
    except Exception:
        return False


def _reassert_dependencies() -> bool:
    try:
        v182 = importlib.import_module("bot.runtime_position_fetch_proof_v182_patch")
        exact_v98 = getattr(v182, "_reassert_v98_adopter", None)
        if callable(exact_v98):
            ok, _detail = exact_v98()
            if not ok:
                return False
        dispatch = getattr(v182, "_reassert_v108_dispatch_hook", None)
        if callable(dispatch):
            ok, _detail = dispatch()
            if not ok:
                return False
    except Exception:
        return False
    try:
        v285 = _v285()
        patch_loaded = getattr(v285, "_patch_loaded", None)
        if callable(patch_loaded) and not bool(patch_loaded()):
            return False
    except Exception:
        return False
    return True


def _patch_all() -> bool:
    dependencies = _reassert_dependencies()
    private_ok = _patch_private_read_prewait()
    adopter_ok = _patch_startup_adopter()
    audit_ok = _patch_v281_kraken_audit()
    return bool(dependencies and private_ok and adopter_ok and audit_ok)


def _emit_state(result: Mapping[str, Any]) -> None:
    global _LAST_STATE_SIGNATURE
    pending_raw = result.get("pending", {}) if isinstance(result, Mapping) else {}
    pending = dict(pending_raw) if isinstance(pending_raw, Mapping) else {}
    kraken_pending = {
        str(account): tuple(str(reason) for reason in tuple(reasons or ()))
        for account, reasons in pending.items()
        if "kraken" in str(account).lower()
    }
    with _AUTH_LOCK:
        flight_count = len(_AUTH_FLIGHTS)
    signature = repr((bool(result.get("ready")), tuple(sorted(kraken_pending.items())), flight_count, _MONITOR_RESTARTS))
    with _LOCK:
        if signature == _LAST_STATE_SIGNATURE:
            return
        _LAST_STATE_SIGNATURE = signature
    log = LOGGER.critical if not kraken_pending else LOGGER.warning
    log(
        "KRAKEN_POSITION_REFRESH_LIVENESS_V286_STATE marker=%s all_account_ready=%s kraken_pending=%s authoritative_flights=%d monitor_restarts=%d read_rate_wait_outside_global_lock=true authoritative_balance_proxy=true synthetic_empty=false capital_wakeup_on_real_recovery=true safety_gates_bypassed=false",
        MARKER,
        str(bool(result.get("ready"))).lower(),
        kraken_pending,
        flight_count,
        _MONITOR_RESTARTS,
    )


def reconcile_once() -> dict[str, Any]:
    _patch_all()
    try:
        v285 = _v285()
        reconcile = getattr(v285, "reconcile_once", None)
        result = reconcile() if callable(reconcile) else {}
    except Exception as exc:
        result = {"ready": False, "pending": {"__v286__": (f"v285_reconcile_error:{type(exc).__name__}:{exc}",)}}
    if not isinstance(result, Mapping):
        result = {"ready": False, "pending": {"__v286__": ("v285_invalid_result",)}}
    output = dict(result)
    _emit_state(output)
    return output


def _monitor() -> None:
    while not _MONITOR_STOP.wait(_monitor_interval_s()):
        try:
            reconcile_once()
        except BaseException as exc:
            LOGGER.error(
                "KRAKEN_POSITION_REFRESH_LIVENESS_V286_MONITOR_ERROR marker=%s error=%s:%s fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )


def _ensure_monitor() -> bool:
    global _MONITOR_THREAD, _MONITOR_RESTARTS
    with _LOCK:
        thread = _MONITOR_THREAD
        if thread is not None and thread.is_alive():
            return True
        if _MONITOR_STOP.is_set():
            _MONITOR_STOP.clear()
        _MONITOR_RESTARTS += 1
        thread = threading.Thread(
            target=_monitor,
            name="KrakenPositionRefreshLivenessV286",
            daemon=True,
        )
        _MONITOR_THREAD = thread
        thread.start()
        LOGGER.critical(
            "KRAKEN_POSITION_REFRESH_LIVENESS_V286_MONITOR_STARTED marker=%s restart_count=%d boolean_latch_not_liveness=true",
            MARKER,
            _MONITOR_RESTARTS,
        )
        return True


def install() -> bool:
    manifest_ok = _register_manifest()
    patched = _patch_all()
    monitor_ok = _ensure_monitor()
    ready = bool(manifest_ok and patched and monitor_ok)
    os.environ[_READY_FLAG] = "1" if ready else "0"
    if ready:
        try:
            reconcile_once()
        except Exception:
            pass
    log = LOGGER.critical if ready else LOGGER.error
    log(
        "RUNTIME_KRAKEN_POSITION_REFRESH_LIVENESS_V286_%s marker=%s ready=%s read_rate_wait_outside_global_lock=true mutating_rate_semantics_unchanged=true authoritative_balance_single_flight=true all_positive_holdings_enumerated=true price_not_required_for_enumeration=true local_contention_cannot_be_empty_snapshot=true api_error_cannot_be_empty_snapshot=true v285_freshness_unchanged=true capital_expected_brokers_unchanged=true forced_trade=false forced_activation=false writer_nonce_risk_capital_killswitch_order_fill_gates_unchanged=true safety_gates_bypassed=false",
        "READY" if ready else "NOT_READY",
        MARKER,
        str(ready).lower(),
    )
    return ready


def install_import_hook() -> bool:
    return install()


def stop() -> None:
    _MONITOR_STOP.set()


__all__ = [
    "MARKER", "RELEASE_ID", "install", "install_import_hook", "stop", "reconcile_once",
    "_read_rate_delay", "_patch_private_read_prewait", "_build_authoritative_rows",
    "_authoritative_positions", "_KrakenAuthoritativeProxy", "_patch_startup_adopter",
    "_patch_v281_kraken_audit", "_ensure_monitor",
]
