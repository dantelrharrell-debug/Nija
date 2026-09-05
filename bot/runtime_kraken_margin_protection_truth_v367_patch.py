"""Kraken margin protection truth and execution-proof recovery v367.

v366 made authenticated Kraken ``OpenPositions`` visible to canonical coverage, but
production evidence exposed two remaining gaps:

* margin coverage called configured stop/take-profit components "verified" merely
  because an entry price/cost basis existed, even when Kraken reported no open
  protective orders;
* the margin row was visible to the account-local exit scanner, but that scanner
  was not guaranteed to run continuously for a funded account whose ordinary
  trading thread was already alive;
* a real Kraken margin position could survive a redeploy while the canonical
  execution marker was missing, leaving general execution fail-closed even though
  the opening order can be re-proven through authenticated QueryOrders.

v367 hardens those boundaries. It never treats configuration as exchange proof.
A margin position is protected only by either a broker-visible stop covering the
remaining quantity or a live dedicated margin monitor whose trusted close path
currently re-proves hard exit authority. The monitor feeds only authenticated
Kraken margin rows through the existing v365/v364/v337 exit stack and derives a
software stop from the existing NIJA hard-loss policy. Exact opening order ids
from OpenPositions may be reconciled read-only through QueryOrders and then fed
through v328/v346; ACKs, positions, market prices, and remembered notional are
never promoted to execution proof.
"""
from __future__ import annotations

import importlib
import logging
import math
import os
import threading
import time
from collections.abc import Mapping
from contextvars import ContextVar
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_kraken_margin_protection_truth_v367")
MARKER = "20260904-runtime-kraken-margin-protection-truth-v367"
RELEASE_ID = "20260904-runtime-convergence-v367"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_MARGIN_PROTECTION_TRUTH_V367_READY"
_PATCH_ATTR = "_nija_v367_kraken_margin_protection_truth"
_MARGIN_ONLY = ContextVar("nija_v367_margin_only_exit_scan", default=False)
_LOCK = threading.RLock()
_THREAD: threading.Thread | None = None
_STOP = threading.Event()
_LAST_PULSE = 0.0
_NATIVE_CACHE: dict[str, tuple[float, bool, dict[str, dict[str, Any]], str]] = {}
_AUTH_CACHE: tuple[float, bool, str] = (0.0, False, "unproven")
_EPS = 1e-12
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in _TRUE


def _f(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError, OverflowError):
        return default


def _v366():
    return importlib.import_module("bot.runtime_kraken_margin_canonical_coverage_v366_patch")


def _kraken_exit():
    return importlib.import_module("bot.kraken_all_account_exit_runtime_patch")


def _private_call(broker: Any):
    try:
        return getattr(_v366(), "_private_call")(broker)
    except Exception:
        return None


def _poll_s() -> float:
    try:
        value = float(os.environ.get("NIJA_KRAKEN_MARGIN_PROTECTIVE_MONITOR_POLL_S", "5") or 5.0)
    except (TypeError, ValueError):
        value = 5.0
    return max(2.0, min(30.0, value))


def _native_ttl_s() -> float:
    try:
        value = float(os.environ.get("NIJA_KRAKEN_MARGIN_OPENORDERS_TTL_S", "5") or 5.0)
    except (TypeError, ValueError):
        value = 5.0
    return max(1.0, min(30.0, value))


def _account_brokers() -> list[tuple[str, Any]]:
    try:
        v281 = importlib.import_module("bot.runtime_all_account_position_exit_coverage_v281_patch")
        manager = v281._canonical_manager()
        expected = v281._expected_accounts(manager)
    except Exception:
        return []
    rows: list[tuple[str, Any]] = []
    for account, broker in dict(expected or {}).items():
        if broker is None:
            continue
        try:
            connected = getattr(broker, "connected", False)
            connected = bool(connected() if callable(connected) else connected)
        except Exception:
            connected = False
        if not connected:
            continue
        try:
            if not _v366().is_kraken_account(account, broker):
                continue
        except Exception:
            continue
        rows.append((str(account), broker))
    return rows


def _normalise_open_orders(payload: Any) -> tuple[bool, dict[str, dict[str, Any]], str]:
    if not isinstance(payload, Mapping):
        return False, {}, "invalid_openorders_payload"
    errors = payload.get("error") or []
    if isinstance(errors, str):
        errors = [errors]
    if errors:
        return False, {}, "openorders_rejected:" + ",".join(str(item) for item in errors)
    result = payload.get("result") or {}
    if not isinstance(result, Mapping):
        return False, {}, "invalid_openorders_result"
    opened = result.get("open", result)
    if not isinstance(opened, Mapping):
        return False, {}, "invalid_openorders_open"
    by_symbol: dict[str, dict[str, Any]] = {}
    for order_id, raw in opened.items():
        if not isinstance(raw, Mapping):
            continue
        status = str(raw.get("status") or "open").strip().lower()
        if status not in {"open", "pending", "new", "accepted"}:
            continue
        descr = raw.get("descr") if isinstance(raw.get("descr"), Mapping) else {}
        side = str(descr.get("type") or raw.get("type") or "").strip().lower()
        if side != "sell":
            continue
        pair = descr.get("pair") or raw.get("pair")
        symbol = _v366().canonical_symbol(pair)
        if not symbol:
            continue
        order_type = str(descr.get("ordertype") or raw.get("ordertype") or "").strip().lower()
        volume = max(0.0, _f(raw.get("vol", raw.get("volume"))))
        executed = max(0.0, _f(raw.get("vol_exec", raw.get("filled_volume"))))
        remaining = max(0.0, volume - executed)
        if remaining <= _EPS:
            continue
        row = by_symbol.setdefault(
            symbol,
            {"stop_qty": 0.0, "take_profit_qty": 0.0, "stop_order_ids": [], "take_profit_order_ids": []},
        )
        if "stop" in order_type:
            row["stop_qty"] += remaining
            row["stop_order_ids"].append(str(order_id))
        if "take" in order_type and "profit" in order_type:
            row["take_profit_qty"] += remaining
            row["take_profit_order_ids"].append(str(order_id))
    for row in by_symbol.values():
        row["stop_order_ids"] = tuple(sorted(row["stop_order_ids"]))
        row["take_profit_order_ids"] = tuple(sorted(row["take_profit_order_ids"]))
    return True, by_symbol, "ok"


def _native_protection(account: str, broker: Any) -> tuple[bool, dict[str, dict[str, Any]], str]:
    now = time.monotonic()
    cached = _NATIVE_CACHE.get(str(account))
    if cached and now - cached[0] <= _native_ttl_s():
        return cached[1], {k: dict(v) for k, v in cached[2].items()}, cached[3]
    call = _private_call(broker)
    if not callable(call):
        return False, {}, "kraken_private_api_unavailable"
    try:
        payload = call("OpenOrders", {"trades": "false"})
    except Exception as exc:
        reason = f"openorders_exception:{type(exc).__name__}"
        _NATIVE_CACHE[str(account)] = (now, False, {}, reason)
        return False, {}, reason
    ok, rows, reason = _normalise_open_orders(payload)
    _NATIVE_CACHE[str(account)] = (now, ok, {k: dict(v) for k, v in rows.items()}, reason)
    return ok, rows, reason


def _hard_exit_authority() -> tuple[bool, str]:
    global _AUTH_CACHE
    now = time.monotonic()
    if now - _AUTH_CACHE[0] <= 2.0:
        return _AUTH_CACHE[1], _AUTH_CACHE[2]
    try:
        v337 = importlib.import_module("bot.runtime_protective_exit_authority_bridge_v337_patch")
        probe = getattr(v337, "_hard_exit_authority_proof", None)
        if not callable(probe):
            result = (False, "v337_hard_exit_probe_unavailable")
        else:
            ok, reason, _snapshot = probe()
            result = (bool(ok), str(reason or "unproven"))
    except Exception as exc:
        result = (False, f"hard_exit_authority_exception:{type(exc).__name__}")
    _AUTH_CACHE = (now, result[0], result[1])
    return result


def _monitor_alive() -> bool:
    thread = _THREAD
    return bool(
        thread is not None
        and callable(getattr(thread, "is_alive", None))
        and thread.is_alive()
        and _truthy(os.environ.get("NIJA_KRAKEN_MARGIN_PROTECTIVE_MONITOR_ENABLED", "true"))
    )


def _margin_scan_wiring_ready() -> bool:
    try:
        rows_fn = getattr(_kraken_exit(), "_position_rows", None)
        if not callable(rows_fn):
            return False
        seen: set[int] = set()
        current = rows_fn
        v365_seen = False
        v367_seen = False
        for _ in range(32):
            if not callable(current) or id(current) in seen:
                break
            seen.add(id(current))
            v365_seen = v365_seen or bool(getattr(current, "_nija_v365_kraken_margin_protective_scan", False))
            v367_seen = v367_seen or bool(getattr(current, _PATCH_ATTR, False))
            current = getattr(current, "__wrapped__", None)
        return bool(v365_seen and v367_seen)
    except Exception:
        return False


def _software_protection_status() -> tuple[bool, str]:
    if not _monitor_alive():
        return False, "margin_monitor_not_alive"
    if not _margin_scan_wiring_ready():
        return False, "margin_scan_wiring_unproven"
    authority, reason = _hard_exit_authority()
    if not authority:
        return False, f"hard_exit_authority_unproven:{reason}"
    return True, "dedicated_margin_monitor_and_hard_exit_authority_ready"


def _effective_stop_loss_pct(row: Mapping[str, Any]) -> float:
    hard = max(0.0, _f(os.environ.get("NIJA_HARD_STOP_LOSS_PCT"), 0.015))
    cost = max(0.0, _f(row.get("cost_basis_usd")))
    max_loss = max(0.0, _f(os.environ.get("NIJA_MAX_POSITION_LOSS_USD"), 2.0))
    candidates = [value for value in (hard,) if value > 0.0]
    if max_loss > 0.0 and cost > _EPS:
        candidates.append(max_loss / cost)
    if not candidates:
        return 0.0
    return max(0.001, min(0.25, min(candidates)))


def _patch_v365_margin_rows() -> bool:
    v365 = importlib.import_module("bot.runtime_kraken_margin_protective_scan_v365_patch")
    current = getattr(v365, "_openposition_rows", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def rows_v367(broker: Any):
        rows, reason = current(broker)
        if reason != "ok":
            return rows, reason
        hardened = []
        for raw in list(rows or []):
            row = dict(raw)
            if row.get("kraken_margin_openpositions") is True:
                entry = max(0.0, _f(row.get("entry_price")))
                pct = _effective_stop_loss_pct(row)
                if entry > 0.0 and pct > 0.0 and _f(row.get("stop_loss")) <= 0.0:
                    row["stop_loss"] = entry * (1.0 - pct)
                    row["risk_stop_loss_pct"] = pct
                    row["risk_stop_loss_source"] = "existing_nija_hard_loss_policy"
                    row["software_stop_loss_derived"] = True
            hardened.append(row)
        return hardened, reason

    setattr(rows_v367, _PATCH_ATTR, True)
    setattr(rows_v367, "__wrapped__", current)
    v365._openposition_rows = rows_v367
    return True


def _patch_margin_only_filter() -> bool:
    module = _kraken_exit()
    current = getattr(module, "_position_rows", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def position_rows_v367(broker: Any):
        for row in current(broker):
            if _MARGIN_ONLY.get() and not bool(
                isinstance(row, Mapping)
                and (row.get("kraken_margin_openpositions") is True or row.get("margin_position") is True)
            ):
                continue
            yield row

    setattr(position_rows_v367, _PATCH_ATTR, True)
    setattr(position_rows_v367, "__wrapped__", current)
    module._position_rows = position_rows_v367
    return True


def _patch_v366_coverage() -> bool:
    v366 = _v366()
    current = getattr(v366, "margin_coverage_rows", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def coverage_v367(account: str, broker: Any):
        rows, reasons = current(account, broker)
        rows = [dict(row) for row in list(rows or [])]
        reasons = list(reasons or [])
        native_ok, native_by_symbol, native_reason = _native_protection(str(account), broker)
        software_ok, software_reason = _software_protection_status()

        for row in rows:
            if row.get("margin_position") is not True:
                continue
            symbol = v366.canonical_symbol(row.get("symbol"))
            quantity = max(0.0, _f(row.get("quantity")))
            native = native_by_symbol.get(symbol, {}) if native_ok else {}
            stop_qty = max(0.0, _f(native.get("stop_qty")))
            take_qty = max(0.0, _f(native.get("take_profit_qty")))
            native_stop = bool(quantity > _EPS and stop_qty + max(_EPS, quantity * 0.005) >= quantity)
            native_tp = bool(quantity > _EPS and take_qty + max(_EPS, quantity * 0.005) >= quantity)
            verified = bool(native_stop or software_ok)

            if native_stop and software_ok:
                mode = "native_exchange_stop+software_margin_monitor"
            elif native_stop:
                mode = "native_exchange_stop"
            elif software_ok:
                mode = "software_margin_monitor"
            else:
                mode = "unverified"

            attached: list[str] = []
            if native_stop:
                attached.append("native_stop_loss")
            if native_tp:
                attached.append("native_take_profit")
            if software_ok:
                attached.append("kraken_margin_software_exit_monitor")

            row["native_openorders_verified"] = bool(native_ok)
            row["native_openorders_reason"] = native_reason
            row["native_stop_loss_verified"] = native_stop
            row["native_take_profit_verified"] = native_tp
            row["native_stop_loss_quantity"] = stop_qty
            row["native_take_profit_quantity"] = take_qty
            row["native_stop_order_ids"] = tuple(native.get("stop_order_ids", ()))
            row["native_take_profit_order_ids"] = tuple(native.get("take_profit_order_ids", ()))
            row["software_exit_monitor_verified"] = bool(software_ok)
            row["software_exit_monitor_reason"] = software_reason
            row["protective_exit_mode"] = mode
            row["protective_exit_verified"] = verified
            row["exit_protections_attached"] = tuple(attached)

            if not verified:
                reasons.append(f"kraken_margin_protective_exit_unverified:{symbol}")

            LOGGER.critical(
                "KRAKEN_MARGIN_PROTECTION_TRUTH_V367 marker=%s account=%s symbol=%s quantity=%.12f "
                "native_openorders_verified=%s native_stop_loss_verified=%s native_take_profit_verified=%s "
                "software_exit_monitor_verified=%s protective_exit_verified=%s mode=%s "
                "configuration_not_exchange_proof=true safety_gates_bypassed=false",
                MARKER, account, symbol, quantity,
                str(bool(native_ok)).lower(), str(native_stop).lower(), str(native_tp).lower(),
                str(bool(software_ok)).lower(), str(verified).lower(), mode,
            )

        return rows, list(dict.fromkeys(str(reason) for reason in reasons if str(reason)))

    setattr(coverage_v367, _PATCH_ATTR, True)
    setattr(coverage_v367, "__wrapped__", current)
    v366.margin_coverage_rows = coverage_v367
    return True


def _openposition_opening_orders(broker: Any) -> list[dict[str, Any]]:
    call = _private_call(broker)
    if not callable(call):
        return []
    try:
        payload = call("OpenPositions", {"docalcs": "true"})
    except Exception:
        return []
    if not isinstance(payload, Mapping) or (payload.get("error") or []):
        return []
    result = payload.get("result") or {}
    if not isinstance(result, Mapping):
        return []
    out: list[dict[str, Any]] = []
    max_age = max(
        300.0,
        _f(os.environ.get("NIJA_KRAKEN_MARGIN_EXECUTION_PROOF_MAX_AGE_S"), 7 * 24 * 3600.0),
    )
    now = time.time()
    for position_id, raw in result.items():
        if not isinstance(raw, Mapping):
            continue
        vol = max(0.0, _f(raw.get("vol")))
        closed = max(0.0, _f(raw.get("vol_closed")))
        if vol <= _EPS or vol - closed <= _EPS:
            continue
        opened = max(0.0, _f(raw.get("opentm")))
        if opened > 0.0 and now - opened > max_age:
            continue
        order_id = str(raw.get("ordertxid") or "").strip()
        if not order_id:
            continue
        out.append(
            {
                "position_id": str(position_id),
                "order_id": order_id,
                "symbol": _v366().canonical_symbol(raw.get("pair")),
                "side": str(raw.get("type") or "buy").strip().lower(),
            }
        )
    return out


def _execution_marker_ready() -> tuple[bool, str]:
    try:
        v231 = importlib.import_module("bot.runtime_authority_nonce_truth_convergence_v231_patch")
        probe = getattr(v231, "_execution_marker_proof", None)
        if not callable(probe):
            return False, "execution_marker_probe_unavailable"
        ready, detail = probe()
        return bool(ready), str(detail or "")
    except Exception as exc:
        return False, f"execution_marker_probe_exception:{type(exc).__name__}"


def recover_execution_proof_once() -> int:
    ready, _detail = _execution_marker_ready()
    if ready:
        return 0
    v328 = importlib.import_module("bot.runtime_confirmed_fill_profitability_v328_patch")
    normalize = getattr(v328, "_normalize_dict_fill", None)
    if not callable(normalize):
        return 0

    for account, broker in _account_brokers():
        call = _private_call(broker)
        if not callable(call):
            continue
        for opening in _openposition_opening_orders(broker):
            order_id = opening["order_id"]
            try:
                payload = call("QueryOrders", {"txid": order_id, "trades": "true"})
            except Exception:
                continue
            if not isinstance(payload, Mapping) or (payload.get("error") or []):
                continue
            result = payload.get("result") or {}
            if not isinstance(result, Mapping):
                continue
            row = result.get(order_id)
            if not isinstance(row, Mapping):
                continue
            status = str(row.get("status") or "").strip().lower()
            if status not in {"closed", "filled", "complete", "completed", "executed"}:
                continue
            vol_exec = max(0.0, _f(row.get("vol_exec")))
            cost = max(0.0, _f(row.get("cost")))
            if vol_exec <= _EPS or cost <= _EPS:
                continue
            price = max(0.0, _f(row.get("price")))
            if price <= _EPS:
                price = cost / vol_exec
            descr = row.get("descr") if isinstance(row.get("descr"), Mapping) else {}
            symbol = _v366().canonical_symbol(descr.get("pair") or opening.get("symbol"))
            side = str(descr.get("type") or opening.get("side") or "buy").strip().lower()
            if not symbol or side not in {"buy", "sell"}:
                continue
            proof = {
                "order_id": order_id,
                "status": "closed",
                "filled_price": price,
                "filled_quantity": vol_exec,
                "authenticated_kraken_queryorders": True,
                "opening_position_id": opening.get("position_id"),
            }
            try:
                normalize(proof, symbol=symbol, side=side)
            except Exception as exc:
                LOGGER.info(
                    "KRAKEN_MARGIN_EXECUTION_PROOF_V367_DEFERRED marker=%s account=%s order_id=%s "
                    "reason=%s:%s fail_closed=true",
                    MARKER, account, order_id, type(exc).__name__, exc,
                )
                continue

            LOGGER.critical(
                "KRAKEN_MARGIN_EXECUTION_PROOF_V367_RECOVERED marker=%s account=%s order_id=%s "
                "symbol=%s side=%s fill_price=%.10f filled_quantity=%.12f "
                "authenticated_open_position_order=true exact_queryorders_match=true "
                "ack_not_fill=true market_price_promoted=false requested_notional_promoted=false "
                "execution_proof_fabricated=false safety_gates_bypassed=false",
                MARKER, account, order_id, symbol, side, price, vol_exec,
            )
            try:
                v346 = importlib.import_module("bot.runtime_execution_position_readiness_v346_patch")
                wake = getattr(v346, "_wake_activation_after_proof", None)
                if callable(wake):
                    wake()
                sync = getattr(v346, "_wake_position_sync", None)
                if callable(sync):
                    sync()
            except Exception:
                pass
            return 1
    return 0


def _scan_margin_positions_once() -> int:
    closed = 0
    module = _kraken_exit()
    scan = getattr(module, "_scan_account_exits", None)
    if not callable(scan):
        return 0
    token = _MARGIN_ONLY.set(True)
    try:
        for account, broker in _account_brokers():
            try:
                closed += int(scan(None, account, broker) or 0)
            except Exception as exc:
                LOGGER.warning(
                    "KRAKEN_MARGIN_PROTECTIVE_MONITOR_V367_SCAN_FAILED marker=%s account=%s error=%s:%s",
                    MARKER, account, type(exc).__name__, exc,
                )
    finally:
        _MARGIN_ONLY.reset(token)
    return closed


def _wake_coverage() -> None:
    try:
        v281 = importlib.import_module("bot.runtime_all_account_position_exit_coverage_v281_patch")
        audit = getattr(v281, "audit_once", None)
        if callable(audit):
            audit()
    except Exception:
        pass


def _monitor_loop() -> None:
    global _LAST_PULSE
    LOGGER.critical(
        "KRAKEN_MARGIN_PROTECTIVE_MONITOR_V367_STARTED marker=%s poll_s=%.2f "
        "margin_only=true v365_visibility_required=true v364_terminal_quantity_cap_required=true "
        "existing_exit_pipeline_only=true forced_exit=false safety_gates_bypassed=false",
        MARKER, _poll_s(),
    )
    last_coverage = 0.0
    while not _STOP.wait(_poll_s()):
        _LAST_PULSE = time.monotonic()
        try:
            recover_execution_proof_once()
        except Exception:
            LOGGER.debug("v367 execution-proof recovery pulse failed", exc_info=True)
        try:
            closed = _scan_margin_positions_once()
            if closed:
                LOGGER.critical(
                    "KRAKEN_MARGIN_PROTECTIVE_MONITOR_V367_EXIT_CONFIRMED marker=%s closed=%d",
                    MARKER, closed,
                )
        except Exception:
            LOGGER.exception("KRAKEN_MARGIN_PROTECTIVE_MONITOR_V367_PULSE_FAILED marker=%s", MARKER)
        now = time.monotonic()
        if now - last_coverage >= max(5.0, _poll_s()):
            last_coverage = now
            _wake_coverage()


def _start_monitor() -> bool:
    global _THREAD, _LAST_PULSE
    if not _truthy(os.environ.get("NIJA_KRAKEN_MARGIN_PROTECTIVE_MONITOR_ENABLED", "true")):
        return False
    with _LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return True
        _STOP.clear()
        _LAST_PULSE = time.monotonic()
        _THREAD = threading.Thread(
            target=_monitor_loop,
            name="KrakenMarginProtectiveMonitorV367",
            daemon=True,
        )
        _THREAD.start()
    return bool(_THREAD.is_alive())


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_kraken_margin_protection_truth_v367"] = _READY_FLAG
        return True
    except Exception:
        return False


def install_import_hook() -> bool:
    os.environ.setdefault("NIJA_KRAKEN_MARGIN_PROTECTIVE_MONITOR_ENABLED", "true")
    os.environ.setdefault("NIJA_KRAKEN_MARGIN_PROTECTIVE_MONITOR_POLL_S", "5")
    os.environ.setdefault("NIJA_KRAKEN_MARGIN_OPENORDERS_TTL_S", "5")
    os.environ.setdefault("NIJA_KRAKEN_MARGIN_EXECUTION_PROOF_MAX_AGE_S", str(7 * 24 * 3600))

    with _LOCK:
        try:
            if os.environ.get("NIJA_RUNTIME_KRAKEN_MARGIN_CANONICAL_COVERAGE_V366_READY") != "1":
                raise RuntimeError("v366_not_ready")
            row_patch = _patch_v365_margin_rows()
            filter_patch = _patch_margin_only_filter()
            coverage_patch = _patch_v366_coverage()
            manifest = _register_manifest()
            monitor = _start_monitor()
            ready = bool(row_patch and filter_patch and coverage_patch and manifest and monitor)
        except Exception as exc:
            ready = False
            LOGGER.exception(
                "RUNTIME_KRAKEN_MARGIN_PROTECTION_TRUTH_V367_INSTALL_FAILED marker=%s error=%s:%s "
                "trading_fail_closed=true safety_gates_bypassed=false",
                MARKER, type(exc).__name__, exc,
            )

        os.environ[_READY_FLAG] = "1" if ready else "0"
        log = LOGGER.critical if ready else LOGGER.error
        log(
            "RUNTIME_KRAKEN_MARGIN_PROTECTION_TRUTH_V367_%s marker=%s ready=%s "
            "configured_protection_not_exchange_proof=true native_openorders_verified_separately=true "
            "dedicated_margin_monitor=%s margin_only_scan=true software_stop_from_existing_risk_policy=true "
            "queryorders_execution_proof_recovery=true exact_order_match_required=true "
            "ack_not_fill=true openpositions_not_fill=true market_price_not_fill=true "
            "v364_terminal_quantity_cap_preserved=true forced_trade=false forced_activation=false "
            "writer_nonce_risk_capital_killswitch_ecel_broker_health_minimum_order_ack_fill_gates_unchanged=true "
            "safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY", MARKER, str(ready).lower(), str(monitor).lower(),
        )
        if ready:
            try:
                recover_execution_proof_once()
            except Exception:
                LOGGER.debug("v367 immediate execution-proof recovery deferred", exc_info=True)
            _wake_coverage()
        return ready


def install() -> bool:
    return install_import_hook()


def _reset_state_for_tests() -> None:
    global _THREAD, _LAST_PULSE, _AUTH_CACHE
    _STOP.set()
    thread = _THREAD
    if thread is not None and thread.is_alive():
        thread.join(timeout=0.05)
    _THREAD = None
    _LAST_PULSE = 0.0
    _NATIVE_CACHE.clear()
    _AUTH_CACHE = (0.0, False, "unproven")
    _STOP.clear()


__all__ = [
    "MARKER", "RELEASE_ID", "install", "install_import_hook",
    "recover_execution_proof_once", "_normalise_open_orders",
    "_effective_stop_loss_pct", "_software_protection_status",
    "_reset_state_for_tests",
]
