"""Kraken startup reconciliation phase handoff v306.

Production generation 5024 on 2026-08-30 proved a same-account scheduling
starvation after v304/v305.  A genuine v286 Balance observation can enumerate a
held Kraken asset and start v288 authenticated TradesHistory cost-basis recovery.
While that history worker is still rate-paced on the same credential, another
startup reconciliation pass can create a new v286 Balance owner.  The later
Balance is authoritative-priority work too, so it can take the next exclusive
monitoring turn before v304's older-history page.  Repeating that cycle prevents
the quantity+cost-basis phase from ever committing even though every individual
private call is healthy.

v306 establishes an explicit phase handoff.  While the exact broker object has a
genuine unfinished v288 bulk-history flight, v286 does not launch a redundant
new Balance owner.  If the existing v285/v286 Balance snapshot is still inside
its original freshness limit and its raw-generation matches, v306 returns a
defensive copy of those already-authenticated rows so startup reconciliation can
continue polling the in-flight cost-basis phase without refreshing position
freshness.  If that snapshot is missing or stale, the caller remains fail-closed
until history finishes; no stale rows are promoted.  Once the history flight
finishes/errors, or a bounded phase-deferral budget expires, normal v286 Balance
behavior resumes unchanged.

The 90-second position freshness policy is unchanged.  Kraken rate intervals,
priority/FIFO exclusivity, credential serialization, transport timeouts, nonce
ordering, cost-basis rules, position quantities, capital publication, writer,
risk, kill switch, position cap, minimum notional, order acknowledgement/fill
confirmation and exit rules are unchanged.  No current-price fallback, synthetic
cost basis, synthetic position, execution proof, forced activation or forced
trade is introduced.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from functools import wraps
from typing import Any, Callable, Mapping

LOGGER = logging.getLogger("nija.runtime_kraken_startup_phase_handoff_v306")
MARKER = "20260830-kraken-startup-phase-handoff-v306"
RELEASE_ID = "20260830-runtime-convergence-v306"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_STARTUP_PHASE_HANDOFF_V306_READY"
_PATCH_ATTR = "_nija_kraken_startup_phase_handoff_v306"
_LOG_LOCK = threading.RLock()
_LAST_LOG_AT: dict[tuple[int, str], float] = {}


def _float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return default if parsed != parsed else parsed
    except Exception:
        return default


def _real_broker(broker: Any) -> Any:
    return getattr(broker, "_broker", broker)


def _v285() -> Any:
    return importlib.import_module("bot.runtime_authoritative_position_coverage_v285_patch")


def _v286() -> Any:
    return importlib.import_module("bot.runtime_kraken_position_refresh_liveness_v286_patch")


def _v288() -> Any:
    return importlib.import_module("bot.runtime_kraken_cost_basis_bulk_v288_patch")


def _max_phase_defer_s() -> float:
    """Bound phase handoff without changing any broker or snapshot timeout."""
    try:
        value = float(os.environ.get("NIJA_KRAKEN_STARTUP_PHASE_HANDOFF_MAX_S", "360") or 360.0)
    except (TypeError, ValueError):
        value = 360.0
    return max(60.0, min(600.0, value))


def _snapshot_max_age_s() -> float:
    try:
        helper = getattr(_v285(), "_snapshot_max_age_s", None)
        if callable(helper):
            return max(1.0, float(helper() or 0.0))
    except Exception:
        pass
    return 90.0


def _bulk_flight_state(broker: Any) -> dict[str, Any]:
    """Inspect only the exact v288 broker-scoped flight; never create/retire it."""
    real = _real_broker(broker)
    try:
        module = _v288()
        lock = getattr(module, "_FLIGHT_LOCK", None)
        flights = getattr(module, "_BULK_FLIGHTS", None)
        if lock is None or not isinstance(flights, dict):
            return {"active": False, "expired": False, "age_s": 0.0, "symbols": ()}
        with lock:
            flight = flights.get(id(real))
            if not isinstance(flight, dict):
                return {"active": False, "expired": False, "age_s": 0.0, "symbols": ()}
            event = flight.get("event")
            if event is None or not callable(getattr(event, "is_set", None)):
                return {"active": False, "expired": False, "age_s": 0.0, "symbols": ()}
            started_at = _float(flight.get("started_at"))
            age_s = max(0.0, time.monotonic() - started_at) if started_at > 0.0 else 0.0
            symbols = tuple(str(value or "").strip().upper() for value in tuple(flight.get("symbols", ()) or ()) if str(value or "").strip())
            if bool(event.is_set()) or flight.get("error") is not None:
                return {"active": False, "expired": False, "age_s": age_s, "symbols": symbols}
            maximum = _max_phase_defer_s()
            if age_s >= maximum:
                return {"active": False, "expired": True, "age_s": age_s, "symbols": symbols}
            return {"active": True, "expired": False, "age_s": age_s, "symbols": symbols}
    except Exception as exc:
        return {
            "active": False,
            "expired": False,
            "age_s": 0.0,
            "symbols": (),
            "inspection_error": f"{type(exc).__name__}:{exc}",
        }


def _current_authoritative_rows(broker: Any) -> tuple[bool, list[dict[str, Any]], float, float, str]:
    """Return current v286 rows without changing timestamp/generation/fetch flags."""
    real = _real_broker(broker)
    maximum = _snapshot_max_age_s()
    try:
        fetch_ok = bool(getattr(real, "_nija_authoritative_position_snapshot_fetch_ok_v285", False))
        generation = int(getattr(real, "_nija_authoritative_position_snapshot_generation_v285", 0) or 0)
        raw_generation = int(getattr(real, "_nija_authoritative_position_raw_generation_v286", -1) or -1)
        recorded = _float(getattr(real, "_nija_authoritative_position_snapshot_at_monotonic_v285", 0.0))
        raw_rows = tuple(getattr(real, "_nija_authoritative_position_raw_rows_v286", ()) or ())
    except Exception as exc:
        return False, [], float("inf"), maximum, f"snapshot_inspection_error:{type(exc).__name__}:{exc}"

    age_s = max(0.0, time.monotonic() - recorded) if recorded > 0.0 else float("inf")
    if not fetch_ok:
        return False, [], age_s, maximum, "snapshot_fetch_not_ready"
    if generation <= 0 or raw_generation != generation:
        return False, [], age_s, maximum, "raw_generation_mismatch"
    if age_s >= maximum:
        return False, [], age_s, maximum, "snapshot_stale"

    rows: list[dict[str, Any]] = []
    for row in raw_rows:
        if not isinstance(row, Mapping):
            return False, [], age_s, maximum, "invalid_raw_row"
        rows.append(dict(row))
    if not rows:
        # A v288 history flight necessarily represents at least one held symbol;
        # do not reinterpret an empty raw cache as an authoritative empty account.
        return False, [], age_s, maximum, "raw_rows_empty"
    return True, rows, age_s, maximum, "current_balance_snapshot"


def _should_log(broker: Any, kind: str, every_s: float = 5.0) -> bool:
    key = (id(_real_broker(broker)), str(kind))
    now = time.monotonic()
    with _LOG_LOCK:
        prior = _LAST_LOG_AT.get(key, 0.0)
        if now - prior < every_s:
            return False
        _LAST_LOG_AT[key] = now
        return True


def _wrap_authoritative_positions(current: Callable[[Any], Any]) -> Callable[[Any], Any]:
    if bool(getattr(current, _PATCH_ATTR, False)):
        return current

    @wraps(current)
    def authoritative_positions_v306(broker: Any):
        flight = _bulk_flight_state(broker)
        if bool(flight.get("expired")):
            if _should_log(broker, "expired", 30.0):
                LOGGER.warning(
                    "KRAKEN_STARTUP_PHASE_V306_DEFER_EXPIRED marker=%s account=%s history_age_s=%.1f symbols=%s "
                    "normal_balance_resume=true phase_budget_bounded=true snapshot_ttl_unchanged=true "
                    "history_flight_mutated=false trading_fail_closed=true safety_gates_bypassed=false",
                    MARKER,
                    str(getattr(_real_broker(broker), "account_identifier", "unknown") or "unknown"),
                    _float(flight.get("age_s")),
                    ",".join(tuple(flight.get("symbols", ()) or ())) or "none",
                )
            return current(broker)

        if not bool(flight.get("active")):
            return current(broker)

        current_ok, rows, snapshot_age, max_age, snapshot_reason = _current_authoritative_rows(broker)
        account = str(getattr(_real_broker(broker), "account_identifier", "unknown") or "unknown")
        symbols = ",".join(tuple(flight.get("symbols", ()) or ())) or "none"
        history_age = _float(flight.get("age_s"))

        if current_ok:
            if _should_log(broker, "reuse"):
                LOGGER.critical(
                    "KRAKEN_STARTUP_PHASE_V306_BALANCE_DEFERRED marker=%s account=%s history_age_s=%.1f symbols=%s "
                    "current_snapshot_reused=true snapshot_age_s=%.1f max_age_s=%.1f "
                    "redundant_balance_started=false authenticated_rows_only=true defensive_copy=true "
                    "snapshot_timestamp_unchanged=true snapshot_generation_unchanged=true freshness_extended=false "
                    "rate_interval_unchanged=true credential_lock_unchanged=true transport_timeout_unchanged=true "
                    "position_success_fabricated=false cost_basis_fabricated=false execution_proof_fabricated=false "
                    "safety_gates_bypassed=false",
                    MARKER,
                    account,
                    history_age,
                    symbols,
                    snapshot_age,
                    max_age,
                )
            return [dict(row) for row in rows]

        if _should_log(broker, "fail_closed"):
            LOGGER.warning(
                "KRAKEN_STARTUP_PHASE_V306_BALANCE_DEFERRED marker=%s account=%s history_age_s=%.1f symbols=%s "
                "current_snapshot_reused=false snapshot_reason=%s snapshot_age_s=%.1f max_age_s=%.1f "
                "redundant_balance_started=false history_flight_active=true trading_fail_closed=true "
                "snapshot_timestamp_unchanged=true snapshot_generation_unchanged=true freshness_extended=false "
                "rate_interval_unchanged=true credential_lock_unchanged=true transport_timeout_unchanged=true "
                "position_success_fabricated=false cost_basis_fabricated=false execution_proof_fabricated=false "
                "safety_gates_bypassed=false",
                MARKER,
                account,
                history_age,
                symbols,
                snapshot_reason,
                snapshot_age,
                max_age,
            )
        raise TimeoutError(
            "Kraken startup cost-basis history still in progress; redundant Balance deferred "
            f"age={history_age:.1f}s snapshot={snapshot_reason}"
        )

    setattr(authoritative_positions_v306, _PATCH_ATTR, True)
    setattr(authoritative_positions_v306, "__wrapped__", current)
    return authoritative_positions_v306


def _patch_v286_authoritative_positions() -> bool:
    try:
        module = _v286()
    except Exception:
        return False
    current = getattr(module, "_authoritative_positions", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True
    module._authoritative_positions = _wrap_authoritative_positions(current)
    return bool(getattr(getattr(module, "_authoritative_positions", None), _PATCH_ATTR, False))


def _v288_flight_surface_ready() -> bool:
    try:
        module = _v288()
        return isinstance(getattr(module, "_BULK_FLIGHTS", None), dict) and getattr(module, "_FLIGHT_LOCK", None) is not None
    except Exception:
        return False


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_kraken_startup_phase_handoff_v306"] = _READY_FLAG
        return True
    except Exception:
        return False


def reconcile_once() -> dict[str, Any]:
    patch_ready = _patch_v286_authoritative_positions()
    flight_ready = _v288_flight_surface_ready()
    return {
        "ready": bool(patch_ready and flight_ready),
        "authoritative_positions_patch": bool(patch_ready),
        "v288_flight_surface": bool(flight_ready),
    }


def install() -> bool:
    manifest_ok = _register_manifest()
    try:
        state = reconcile_once()
    except Exception as exc:
        state = {
            "ready": False,
            "authoritative_positions_patch": False,
            "v288_flight_surface": False,
            "error": f"{type(exc).__name__}:{exc}",
        }
    ready = bool(manifest_ok and state.get("ready"))
    os.environ[_READY_FLAG] = "1" if ready else "0"
    log = LOGGER.critical if ready else LOGGER.error
    log(
        "RUNTIME_KRAKEN_STARTUP_PHASE_HANDOFF_V306_%s marker=%s ready=%s "
        "authoritative_positions_patch=%s v288_flight_surface=%s "
        "same_broker_history_phase_blocks_redundant_balance=true current_snapshot_reuse_requires_original_ttl=true "
        "stale_snapshot_promoted=false history_flight_mutated=false phase_defer_bounded=true "
        "snapshot_ttl_unchanged=true snapshot_timestamp_unchanged=true snapshot_generation_unchanged=true "
        "rate_interval_unchanged=true monitoring_priority_unchanged=true credential_lock_unchanged=true "
        "transport_timeout_unchanged=true synthetic_position=false synthetic_cost_basis=false current_price_fallback=false "
        "forced_trade=false forced_activation=false "
        "writer_nonce_capital_risk_killswitch_broker_health_position_cap_min_notional_order_ack_fill_gates_unchanged=true "
        "execution_proof_fabricated=false safety_gates_bypassed=false",
        "READY" if ready else "NOT_READY",
        MARKER,
        str(ready).lower(),
        str(bool(state.get("authoritative_positions_patch"))).lower(),
        str(bool(state.get("v288_flight_surface"))).lower(),
    )
    return ready


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "reconcile_once",
    "_bulk_flight_state",
    "_current_authoritative_rows",
    "_wrap_authoritative_positions",
    "_patch_v286_authoritative_positions",
]
