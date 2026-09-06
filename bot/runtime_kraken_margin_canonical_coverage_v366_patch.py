"""Kraken margin OpenPositions canonical protective-coverage convergence v366.

Production evidence on 2026-09-04 proved a live Kraken 2x ETH margin long that
never reached NIJA's canonical protective-coverage report.  The gap is
structural rather than accidental:

* the canonical Kraken position snapshot is Balance-owned (v286) and therefore
  spot-only, so a leveraged position is invisible to it;
* v281/v285 build canonical coverage rows exclusively from the account-local
  spot tracker, so no margin row can ever appear there;
* v364 only reads ``OpenPositions`` immediately before a Kraken SELL;
* v365 only augments the Kraken exit scanner's candidate rows.

Consequently a Kraken account could report canonical position coverage READY on
a successful Balance call while broker-visible margin exposure remained
unreconciled and unrepresented.

v366 closes exactly that boundary.  Authenticated Kraken ``OpenPositions`` rows
become a first-class *margin position-state* input of the recurring canonical
coverage cycle (``v281.evaluate``):

* genuine open LONG margin rows are published into canonical coverage with
  ``source=kraken_open_positions``/``margin_position=true`` so the existing
  stop-loss / take-profit / trailing-stop / trailing-take-profit / auto-exit
  infrastructure can see them before any exit is requested;
* an unresolved ``OpenPositions`` read keeps that Kraken account pending with
  ``kraken_open_positions_fetch_unproven`` — a successful Balance call can no
  longer erase a failed margin proof;
* spot Balance/tracker ownership is untouched: margin rows are never inserted
  into spot holdings and the spot tracker is never mutated;
* protective SELL quantities are capped at broker-authoritative remaining
  units, and a margin row that disappears before submission fails closed.

``OpenPositions`` is position-state evidence only.  It never becomes a fill, an
acknowledgement, execution readiness, activation, or capital truth, and no
existing safety gate is weakened.
"""
from __future__ import annotations

import importlib
import logging
import math
import os
import threading
import time
from collections.abc import Mapping
from functools import wraps
from typing import Any, Dict, Tuple

LOGGER = logging.getLogger("nija.runtime_kraken_margin_canonical_coverage_v366")
MARKER = "20260904-runtime-kraken-margin-canonical-coverage-v366"
RELEASE_ID = "20260904-runtime-convergence-v366"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_MARGIN_CANONICAL_COVERAGE_V366_READY"
_PATCH_ATTR = "_nija_v366_kraken_margin_canonical_coverage"
_UNPROVEN_REASON = "kraken_open_positions_fetch_unproven"
_SOURCE = "kraken_open_positions"
_EPS = 1e-12

_LOCK = threading.RLock()
_CACHE: Dict[str, Dict[str, Any]] = {}
_LAST_VISIBLE: Dict[str, Dict[str, float]] = {}

_KNOWN_ALIASES = {
    "XETHZUSD": "ETH-USD",
    "XXBTZUSD": "BTC-USD",
    "XBTUSD": "BTC-USD",
    "XXRPZUSD": "XRP-USD",
    "XETCZUSD": "ETC-USD",
    "XLTCZUSD": "LTC-USD",
    "XXLMZUSD": "XLM-USD",
    "XMLNZUSD": "MLN-USD",
    "XDGUSD": "DOGE-USD",
}


def _float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError, OverflowError):
        return default


def canonical_symbol(value: Any) -> str:
    """Normalise a Kraken pair, including legacy aliases such as ``XETHZUSD``."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        v364 = importlib.import_module("bot.runtime_kraken_openpositions_margin_reconciliation_v364_patch")
        fn = getattr(v364, "_canonical_symbol", None)
        if callable(fn):
            candidate = str(fn(raw) or "").strip().upper()
            if candidate:
                raw = candidate
    except Exception:
        pass
    compact = raw.upper().replace("/", "-").replace("_", "-")
    if "-" in compact:
        return compact
    alias = _KNOWN_ALIASES.get(compact)
    if alias:
        return alias
    for quote in ("ZUSD", "USDT", "USDC", "USD"):
        if compact.endswith(quote) and len(compact) > len(quote):
            base = compact[: -len(quote)]
            if base.startswith("X") and len(base) > 3:
                base = base[1:]
            quote_symbol = "USD" if quote == "ZUSD" else quote
            return f"{base}-{quote_symbol}"
    return compact


def _cache_ttl_s() -> float:
    try:
        value = float(os.environ.get("NIJA_KRAKEN_MARGIN_OPENPOSITIONS_TTL_S", "10") or 10.0)
    except (TypeError, ValueError):
        value = 10.0
    return max(0.0, min(60.0, value))


def _account_key(account: Any, broker: Any) -> str:
    text = str(account or "").strip().lower()
    if text:
        return text
    identity = getattr(broker, "account_identifier", "") or getattr(broker, "account_id", "")
    return str(identity or f"broker:{id(broker)}").strip().lower()


def _unwrap(broker: Any) -> Any:
    """Resolve the concrete broker behind known read-only authoritative proxies."""
    current = broker
    for _ in range(6):
        if current is None:
            return None
        if callable(getattr(current, "_kraken_api_call", None)) or callable(
            getattr(current, "_kraken_private_call", None)
        ):
            return current
        nxt = None
        for attr in ("_broker", "_real_broker", "_target", "broker"):
            candidate = getattr(current, attr, None)
            if candidate is not None and candidate is not current:
                nxt = candidate
                break
        if nxt is None:
            return current
        current = nxt
    return current


def _private_call(broker: Any):
    target = _unwrap(broker)
    for attr in ("_kraken_api_call", "_kraken_private_call"):
        call = getattr(target, attr, None)
        if callable(call):
            return call
    return None


def is_kraken_account(account: Any, broker: Any) -> bool:
    """True when the account is a Kraken account that can hold margin exposure."""
    text = str(account or "").strip().lower()
    if text.endswith(":kraken") or text == "kraken":
        return True
    broker_type = getattr(broker, "broker_type", None)
    label = str(getattr(broker_type, "value", broker_type) or "").strip().lower()
    if label.endswith("kraken"):
        return True
    return "kraken" in type(broker).__name__.strip().lower()


def normalise_open_positions(payload: Any) -> Dict[str, Any]:
    """Aggregate authenticated ``OpenPositions`` rows into canonical margin truth.

    Returns ``{"ok": bool, "reason": str, "positions": {symbol: row}}``.  The
    result is broker position-state evidence only; it is never fill proof.
    """
    if not isinstance(payload, Mapping):
        return {"ok": False, "reason": "invalid_openpositions_payload", "positions": {}}
    errors = payload.get("error") or []
    if isinstance(errors, str):
        errors = [errors]
    if errors:
        detail = ",".join(str(item) for item in errors)
        return {"ok": False, "reason": f"openpositions_rejected:{detail}", "positions": {}}
    result = payload.get("result")
    if result is None:
        result = {}
    if not isinstance(result, Mapping):
        return {"ok": False, "reason": "invalid_openpositions_result", "positions": {}}

    aggregated: Dict[str, Dict[str, Any]] = {}
    for position_id, raw in result.items():
        if not isinstance(raw, Mapping):
            continue
        side = str(raw.get("type") or "").strip().lower()
        if side != "buy":
            # v366 is intentionally long-only; short authority remains v325/v326.
            continue
        symbol = canonical_symbol(raw.get("pair"))
        volume = max(0.0, _float(raw.get("vol")))
        closed = max(0.0, _float(raw.get("vol_closed")))
        remaining = max(0.0, volume - closed)
        if not symbol or volume <= _EPS or remaining <= _EPS:
            continue
        cost = max(0.0, _float(raw.get("cost")))
        value = max(0.0, _float(raw.get("value")))
        remaining_ratio = min(1.0, remaining / volume)
        remaining_cost = cost * remaining_ratio
        row = aggregated.setdefault(
            symbol,
            {
                "symbol": symbol,
                "quantity": 0.0,
                "remaining_units": 0.0,
                "cost_basis_usd": 0.0,
                "notional_usd": 0.0,
                "position_ids": [],
                "leverage": None,
            },
        )
        row["quantity"] += remaining
        row["remaining_units"] += remaining
        row["cost_basis_usd"] += remaining_cost
        row["notional_usd"] += value if value > 0 else remaining_cost
        row["position_ids"].append(str(position_id))
        margin = max(0.0, _float(raw.get("margin")))
        if margin > _EPS and cost > _EPS:
            inferred = int(round(cost / margin))
            if 2 <= inferred <= 5:
                previous = row.get("leverage")
                row["leverage"] = inferred if previous is None else max(int(previous), inferred)

    positions: Dict[str, Dict[str, Any]] = {}
    for symbol, row in aggregated.items():
        quantity = _float(row.get("quantity"))
        cost_basis = _float(row.get("cost_basis_usd"))
        if quantity <= _EPS or cost_basis <= _EPS:
            # Without broker-proven cost there is no honest entry basis; the row
            # is retained as exposure but never given a synthesised entry price.
            entry_price = 0.0
        else:
            entry_price = cost_basis / quantity
        row["entry_price"] = entry_price
        row["avg_entry_price"] = entry_price
        row["side"] = "long"
        row["source"] = _SOURCE
        row["margin_position"] = True
        row["broker_position_state_only"] = True
        row["confirmed_fill_proof"] = False
        row["position_ids"] = tuple(sorted(row["position_ids"]))
        positions[symbol] = row
    return {"ok": True, "reason": "ok", "positions": positions}


def fetch_margin_positions(broker: Any, *, account: Any = "", force: bool = False) -> Tuple[bool, Dict[str, Dict[str, Any]], str]:
    """Fetch authenticated Kraken margin positions for ``broker``.

    Successful reads are cached for a short TTL so the recurring coverage cycle
    does not hammer the authenticated endpoint.  Failures are never cached and
    never downgraded into an empty (i.e. "no exposure") result.
    """
    key = _account_key(account, broker)
    ttl = _cache_ttl_s()
    now = time.monotonic()
    if not force and ttl > 0:
        with _LOCK:
            cached = _CACHE.get(key)
            if cached and (now - _float(cached.get("at"))) <= ttl:
                return True, {symbol: dict(row) for symbol, row in cached["positions"].items()}, "cached"

    call = _private_call(broker)
    if call is None:
        reason = "kraken_private_api_unavailable"
        _log_fetch_failed(key, reason)
        return False, {}, reason
    try:
        payload = call("OpenPositions", {"docalcs": "true"})
    except Exception as exc:
        reason = f"openpositions_exception:{type(exc).__name__}"
        _log_fetch_failed(key, reason)
        return False, {}, reason

    truth = normalise_open_positions(payload)
    if not truth.get("ok"):
        reason = str(truth.get("reason") or "openpositions_unproven")
        _log_fetch_failed(key, reason)
        return False, {}, reason

    positions = {symbol: dict(row) for symbol, row in (truth.get("positions") or {}).items()}
    with _LOCK:
        _CACHE[key] = {"at": now, "positions": {symbol: dict(row) for symbol, row in positions.items()}}
    _reconcile_closed(key, positions)
    LOGGER.info(
        "KRAKEN_MARGIN_OPENPOSITIONS_FETCH_SUCCESS marker=%s account=%s open_positions=%d symbols=%s "
        "source=%s broker_position_state_only=true fill_fabricated=false spot_tracker_mutated=false "
        "safety_gates_bypassed=false",
        MARKER, key, len(positions), ",".join(sorted(positions)) or "none", _SOURCE,
    )
    return True, positions, "ok"


def _log_fetch_failed(account: str, reason: str) -> None:
    LOGGER.error(
        "KRAKEN_MARGIN_OPENPOSITIONS_FETCH_FAILED marker=%s account=%s reason=%s "
        "coverage_reason=%s fail_closed=true margin_position_fabricated=false "
        "spot_tracker_mutated=false safety_gates_bypassed=false",
        MARKER, account, reason, _UNPROVEN_REASON,
    )


def _reconcile_closed(account: str, positions: Mapping[str, Mapping[str, Any]]) -> None:
    """Log broker-evidenced disappearance of previously visible margin rows."""
    with _LOCK:
        previous = dict(_LAST_VISIBLE.get(account) or {})
        _LAST_VISIBLE[account] = {
            symbol: _float(row.get("quantity")) for symbol, row in positions.items()
        }
    for symbol, quantity in sorted(previous.items()):
        current = _float((positions.get(symbol) or {}).get("quantity"))
        if current > _EPS and current < quantity - max(1e-12, abs(quantity) * 1e-9):
            LOGGER.info(
                "KRAKEN_MARGIN_POSITION_PARTIAL_CLOSE_RECONCILED marker=%s account=%s symbol=%s "
                "previous_quantity=%.12f quantity=%.12f source=%s side=long "
                "protective_exit_required=true fill_fabricated=false spot_tracker_mutated=false "
                "safety_gates_bypassed=false",
                MARKER, account, symbol, quantity, current, _SOURCE,
            )
        elif current <= _EPS:
            LOGGER.critical(
                "KRAKEN_MARGIN_POSITION_CLOSED_RECONCILED marker=%s account=%s symbol=%s "
                "previous_quantity=%.12f quantity=0 source=%s side=long "
                "broker_evidence=openpositions_absent protective_exit_required=false "
                "fill_fabricated=false spot_tracker_mutated=false safety_gates_bypassed=false",
                MARKER, account, symbol, quantity, _SOURCE,
            )


def last_visible_quantity(account: Any, symbol: Any, broker: Any = None) -> float:
    key = _account_key(account, broker)
    with _LOCK:
        return _float((_LAST_VISIBLE.get(key) or {}).get(canonical_symbol(symbol)))


def authoritative_remaining_units(broker: Any, symbol: Any, *, account: Any = "") -> Tuple[bool, float, str]:
    """Return broker-authoritative remaining base units for a Kraken margin long."""
    ok, positions, reason = fetch_margin_positions(broker, account=account, force=True)
    if not ok:
        return False, 0.0, reason
    row = positions.get(canonical_symbol(symbol))
    if not row:
        return True, 0.0, "no_open_margin_position"
    return True, max(0.0, _float(row.get("quantity"))), "ok"


def cap_protective_exit_quantity(
    broker: Any,
    symbol: Any,
    requested: Any,
    *,
    account: Any = "",
    spot_quantity: Any = 0.0,
) -> Dict[str, Any]:
    """Cap a protective SELL at authoritative remaining margin + spot holdings.

    The quantity is never increased.  When a previously visible margin row can
    no longer be proven the request fails closed instead of sending a stale SELL.
    """
    key = _account_key(account, broker)
    canonical = canonical_symbol(symbol)
    requested_units = max(0.0, _float(requested))
    spot_units = max(0.0, _float(spot_quantity))
    previously_visible = last_visible_quantity(key, canonical) > _EPS

    ok, positions, reason = fetch_margin_positions(broker, account=key, force=True)
    if not ok:
        if previously_visible:
            return {
                "ok": False,
                "quantity": 0.0,
                "reason": _UNPROVEN_REASON,
                "detail": reason,
                "fail_closed": True,
            }
        return {"ok": True, "quantity": requested_units, "reason": "no_known_margin_position", "detail": reason}

    margin_units = max(0.0, _float((positions.get(canonical) or {}).get("quantity")))
    if margin_units <= _EPS:
        if previously_visible and spot_units <= _EPS:
            LOGGER.error(
                "KRAKEN_MARGIN_POSITION_EXIT_BLOCKED marker=%s account=%s symbol=%s reason=%s "
                "broker_open_row_absent=true stale_sell_prevented=true fail_closed=true "
                "fill_fabricated=false spot_tracker_mutated=false safety_gates_bypassed=false",
                MARKER, key, canonical, "margin_position_absent_before_submission",
            )
            return {
                "ok": False,
                "quantity": 0.0,
                "reason": "margin_position_absent_before_submission",
                "fail_closed": True,
            }
        return {"ok": True, "quantity": requested_units, "reason": "no_open_margin_position"}

    authoritative = margin_units + spot_units
    quantity = min(requested_units, authoritative)
    if quantity < requested_units:
        LOGGER.critical(
            "KRAKEN_MARGIN_POSITION_QUANTITY_CAPPED marker=%s account=%s symbol=%s requested=%.12f "
            "authoritative_remaining=%.12f spot_quantity=%.12f submitted=%.12f source=%s side=long "
            "oversell_prevented=true fill_fabricated=false spot_tracker_mutated=false "
            "safety_gates_bypassed=false",
            MARKER, key, canonical, requested_units, margin_units, spot_units, quantity, _SOURCE,
        )
    return {
        "ok": True,
        "quantity": quantity,
        "reason": "capped" if quantity < requested_units else "within_authoritative_remaining",
        "authoritative_remaining_units": margin_units,
    }


def _spot_quantity(broker: Any, symbol: str) -> float:
    tracker = getattr(_unwrap(broker), "position_tracker", None)
    getter = getattr(tracker, "get_position", None)
    if not callable(getter):
        return 0.0
    try:
        row = getter(symbol)
    except Exception:
        return 0.0
    if not isinstance(row, Mapping):
        return 0.0
    for field in ("quantity", "qty", "amount", "size", "units"):
        if row.get(field) is not None:
            return max(0.0, _float(row.get(field)))
    return 0.0


def margin_coverage_rows(account: Any, broker: Any) -> Tuple[list, list]:
    """Return canonical coverage rows and pending reasons for one Kraken account."""
    key = _account_key(account, broker)
    ok, positions, reason = fetch_margin_positions(broker, account=key)
    if not ok:
        return [], [f"{_UNPROVEN_REASON}:{reason}"]

    venue = key.rsplit(":", 1)[-1] if ":" in key else "kraken"
    rows = []
    for symbol in sorted(positions):
        position = positions[symbol]
        quantity = max(0.0, _float(position.get("quantity")))
        entry_price = max(0.0, _float(position.get("entry_price")))
        cost_basis = max(0.0, _float(position.get("cost_basis_usd")))
        if quantity <= _EPS:
            continue
        verified = entry_price > 0.0 and cost_basis > 0.0
        row = {
            "account": key,
            "broker": venue,
            "symbol": symbol,
            "quantity": quantity,
            "entry_price": entry_price,
            "cost_basis_usd": cost_basis,
            "cost_basis_verified": verified,
            "auto_exit_blocked": False,
            "side": "long",
            "margin_position": True,
            "source": _SOURCE,
            "position_ids": tuple(position.get("position_ids") or ()),
            "leverage": position.get("leverage"),
            "authoritative_snapshot_adopted": True,
            "authoritative_snapshot_current": True,
            "spot_holding": False,
            "protective_exit_required": True,
            "protective_exit_verified": False,
            "broker_position_state_only": True,
            "confirmed_fill_proof": False,
            # OpenPositions proves exposure identity/cost only. Protection is
            # certified later by v367/v371 from authenticated native orders or
            # the live account-local software monitor.
            "exit_protections_attached": (),
        }
        rows.append(row)
        LOGGER.critical(
            "KRAKEN_MARGIN_POSITION_VISIBLE marker=%s account=%s broker=%s symbol=%s position_id=%s "
            "quantity=%.12f entry_price=%.8f cost_basis_usd=%.8f leverage=%s side=long source=%s "
            "margin_position=true protective_exit_required=true protective_exit_verified=%s "
            "safety_gates_bypassed=false fill_fabricated=false spot_tracker_mutated=false",
            MARKER, key, venue, symbol, ",".join(row["position_ids"]) or "unknown",
            quantity, entry_price, cost_basis, row["leverage"], _SOURCE, "false",
        )
        LOGGER.critical(
            "KRAKEN_MARGIN_POSITION_PROTECTIVE_COVERAGE marker=%s account=%s symbol=%s quantity=%.12f "
            "entry_price=%.8f side=long source=%s margin_position=true protective_exit_required=true "
            "protective_exit_verified=%s canonical_coverage=false safety_gates_bypassed=false "
            "fill_fabricated=false spot_tracker_mutated=false",
            MARKER, key, symbol, quantity, entry_price, _SOURCE, "false",
        )
    reasons = [
        f"margin_position_cost_basis_unverified:{row['symbol']}"
        for row in rows if not row["cost_basis_verified"]
    ]
    # Exposure visibility is not protection proof. A later verifier must remove
    # this reason only after all required protection legs are proven.
    reasons.extend(
        f"kraken_margin_protective_exit_unverified:{row['symbol']}" for row in rows
    )
    return rows, reasons


def augment_coverage(manager: Any, result: Mapping[str, Any]) -> Dict[str, Any]:
    """Merge Kraken margin exposure into one canonical v281 coverage result."""
    if not isinstance(result, Mapping):
        return dict(result) if isinstance(result, dict) else {}
    merged = dict(result)
    expected = merged.get("expected_accounts", ()) or ()
    if not expected:
        return merged

    brokers: Dict[str, Any] = {}
    try:
        v281 = importlib.import_module("bot.runtime_all_account_position_exit_coverage_v281_patch")
        resolver = getattr(v281, "_expected_accounts", None)
        if callable(resolver):
            resolved = resolver(manager)
            if isinstance(resolved, Mapping):
                brokers = dict(resolved)
    except Exception as exc:
        LOGGER.error(
            "KRAKEN_MARGIN_CANONICAL_COVERAGE_V366_ACCOUNT_RESOLUTION_FAILED marker=%s error=%s:%s fail_closed=true",
            MARKER, type(exc).__name__, exc,
        )
        return merged

    pending = {str(key): tuple(value) for key, value in dict(merged.get("pending", {}) or {}).items()}
    positions = [dict(row) for row in tuple(merged.get("positions", ()) or ()) if isinstance(row, Mapping)]

    for account, broker in brokers.items():
        if broker is None or not is_kraken_account(account, broker):
            continue
        rows, reasons = margin_coverage_rows(account, broker)
        positions.extend(rows)
        if reasons:
            key = str(account)
            pending[key] = tuple(dict.fromkeys(list(pending.get(key, ())) + list(reasons)))

    merged["pending"] = pending
    merged["positions"] = tuple(positions)
    merged["ready"] = bool(expected) and bool(merged.get("structural_exit_ready")) and not pending
    return merged


def _patch_evaluate() -> bool:
    module = importlib.import_module("bot.runtime_all_account_position_exit_coverage_v281_patch")
    current = getattr(module, "evaluate", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def evaluate_v366(manager: Any = None, **kwargs: Any) -> Dict[str, Any]:
        result = original(manager, **kwargs)
        try:
            return augment_coverage(manager, result)
        except Exception as exc:
            LOGGER.exception(
                "KRAKEN_MARGIN_CANONICAL_COVERAGE_V366_AUGMENT_ERROR marker=%s error=%s:%s fail_closed=true",
                MARKER, type(exc).__name__, exc,
            )
            merged = dict(result) if isinstance(result, Mapping) else {}
            pending = dict(merged.get("pending", {}) or {})
            pending["__kraken_margin_coverage__"] = (f"{_UNPROVEN_REASON}:augment_error",)
            merged["pending"] = pending
            merged["ready"] = False
            return merged

    setattr(evaluate_v366, _PATCH_ATTR, True)
    setattr(evaluate_v366, "__wrapped__", original)
    module.evaluate = evaluate_v366
    return True


def _patch_exit_submission() -> bool:
    """Cap Kraken protective exits at broker-authoritative remaining quantity."""
    try:
        module = importlib.import_module("bot.kraken_all_account_exit_runtime_patch")
    except Exception:
        return False
    current = getattr(module, "_submit_exit", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def submit_exit_v366(broker: Any, account: Any, pair: Any, quantity: Any, reason: Any):
        symbol = canonical_symbol(pair)
        decision = cap_protective_exit_quantity(
            broker, symbol, quantity, account=account, spot_quantity=_spot_quantity(broker, symbol),
        )
        if not decision.get("ok"):
            return {
                "status": "error",
                "error": f"Kraken margin protective exit fail-closed: {decision.get('reason')}",
                "symbol": symbol,
                "account_id": _account_key(account, broker),
                "margin": True,
            }
        return original(broker, account, pair, max(0.0, _float(decision.get("quantity"))), reason)

    setattr(submit_exit_v366, _PATCH_ATTR, True)
    setattr(submit_exit_v366, "__wrapped__", original)
    module._submit_exit = submit_exit_v366
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_kraken_margin_canonical_coverage_v366"] = _READY_FLAG
        return True
    except Exception:
        return False


def install_import_hook() -> bool:
    evaluate_patched = exit_patched = manifest = False
    try:
        evaluate_patched = _patch_evaluate()
        exit_patched = _patch_exit_submission()
        manifest = _register_manifest()
    except Exception as exc:
        LOGGER.exception(
            "RUNTIME_KRAKEN_MARGIN_CANONICAL_COVERAGE_V366_INSTALL_ERROR marker=%s error=%s:%s fail_closed=true",
            MARKER, type(exc).__name__, exc,
        )
    ready = bool(evaluate_patched and exit_patched and manifest)
    os.environ[_READY_FLAG] = "1" if ready else "0"
    (LOGGER.critical if ready else LOGGER.error)(
        "RUNTIME_KRAKEN_MARGIN_CANONICAL_COVERAGE_V366_%s marker=%s ready=%s "
        "openpositions_first_class_margin_input=true canonical_protective_coverage_merged=true "
        "kraken_open_positions_fetch_unproven_blocks_ready=true spot_margin_separation_preserved=true "
        "spot_tracker_mutated=false margin_exit_quantity_capped_to_broker_remaining=true "
        "stale_sell_fail_closed=true openpositions_not_fill_proof=true execution_ready_unchanged=true "
        "forced_trade=false forced_activation=false kill_switch_unchanged=true rejection_history_unchanged=true "
        "writer_nonce_risk_capital_position_sync_ecel_broker_health_minimum_order_ack_fill_gates_unchanged=true "
        "safety_gates_bypassed=false",
        "READY" if ready else "NOT_READY", MARKER, str(ready).lower(),
    )
    return ready


def install() -> bool:
    return install_import_hook()


def _reset_state_for_tests() -> None:
    with _LOCK:
        _CACHE.clear()
        _LAST_VISIBLE.clear()


__all__ = [
    "MARKER", "RELEASE_ID", "install", "install_import_hook", "canonical_symbol",
    "normalise_open_positions", "fetch_margin_positions", "margin_coverage_rows",
    "augment_coverage", "authoritative_remaining_units", "cap_protective_exit_quantity",
    "is_kraken_account", "last_visible_quantity",
]
