"""Kraken margin protective-scan visibility v365.

Production on 2026-09-04 proved that the canonical Kraken spot/Balance position
snapshot can correctly report no spot positions while Kraken still has a live
leveraged ETH long in authenticated ``OpenPositions``.  v364 safely reconciles
that broker margin state immediately before a SELL, but the account-local Kraken
exit scanner builds its candidate rows from the spot tracker / ``get_positions``
path first.  A broker-open margin position can therefore remain invisible before
an exit is even evaluated.

v365 changes only that candidate-read boundary.  It augments
``kraken_all_account_exit_runtime_patch._position_rows`` with authenticated
Kraken ``OpenPositions`` long rows that contain positive broker quantity and
positive broker cost.  Multiple Kraken position ids for the same pair are
aggregated into one authoritative scanner row so stop-loss/take-profit evaluation
covers the full remaining margin quantity rather than only the first leg.  It
does not mutate the spot tracker, does not create an execution fill, does not
grant execution readiness, and does not submit an order.  v364 remains the
terminal margin-ledger reconciliation and authoritative remaining-quantity cap
before any SELL.
"""
from __future__ import annotations

import importlib
import logging
import math
import os
from functools import wraps
from typing import Any, Iterable, Mapping, MutableMapping

LOGGER = logging.getLogger("nija.runtime_kraken_margin_protective_scan_v365")
MARKER = "20260904-runtime-kraken-margin-protective-scan-v365"
RELEASE_ID = "20260904-runtime-convergence-v365"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_MARGIN_PROTECTIVE_SCAN_V365_READY"
_PATCH_ATTR = "_nija_v365_kraken_margin_protective_scan"
_EPS = 1e-12


def _f(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError, OverflowError):
        return default


def _canonical_symbol(value: Any) -> str:
    try:
        v364 = importlib.import_module("bot.runtime_kraken_openpositions_margin_reconciliation_v364_patch")
        fn = getattr(v364, "_canonical_symbol", None)
        if callable(fn):
            return str(fn(value) or "").strip().upper()
    except Exception:
        pass
    raw = str(value or "").strip().upper().replace("/", "-").replace("_", "-")
    known = {"XETHZUSD": "ETH-USD", "XXBTZUSD": "BTC-USD", "XXRPZUSD": "XRP-USD"}
    return known.get(raw.replace("-", ""), raw)


def _openposition_rows(broker: Any) -> tuple[list[MutableMapping[str, Any]], str]:
    """Return one aggregate long-margin row per canonical Kraken pair.

    Kraken can represent one user-visible margin position as several independent
    ``OpenPositions`` ids.  The protective scanner must evaluate the sum of all
    remaining legs for a pair; yielding the ids individually and later de-duping
    by symbol protects only the first leg.
    """
    call = getattr(broker, "_kraken_api_call", None)
    if not callable(call):
        return [], "private_api_unavailable"
    try:
        payload = call("OpenPositions", {"docalcs": "true"})
    except Exception as exc:
        return [], f"openpositions_exception:{type(exc).__name__}"
    if not isinstance(payload, Mapping):
        return [], "invalid_payload"
    errors = payload.get("error") or []
    if isinstance(errors, str):
        errors = [errors]
    if errors:
        return [], "openpositions_rejected:" + ",".join(str(item) for item in errors)
    result = payload.get("result") or {}
    if not isinstance(result, Mapping):
        return [], "invalid_result"

    aggregates: dict[str, MutableMapping[str, Any]] = {}
    for position_id, raw in result.items():
        if not isinstance(raw, Mapping):
            continue
        side = str(raw.get("type") or "").strip().lower()
        if side != "buy":
            # v365 is intentionally long-only. Short authority remains v325/v326.
            continue
        symbol = _canonical_symbol(raw.get("pair"))
        vol = max(0.0, _f(raw.get("vol")))
        closed = max(0.0, _f(raw.get("vol_closed")))
        remaining = max(0.0, vol - closed)
        cost = max(0.0, _f(raw.get("cost")))
        if not symbol or vol <= _EPS or remaining <= _EPS or cost <= _EPS:
            continue

        remaining_cost = cost * min(1.0, remaining / vol)
        if remaining_cost <= _EPS:
            continue

        row = aggregates.get(symbol)
        if row is None:
            row = {
                "symbol": symbol,
                "quantity": 0.0,
                "qty": 0.0,
                "side": "long",
                "cost_basis_usd": 0.0,
                "cost_basis_verified": True,
                "auto_exit_blocked": False,
                "position_ids": [],
                "kraken_margin_openpositions": True,
                "broker_position_state_only": True,
                "confirmed_fill_proof": False,
            }
            aggregates[symbol] = row

        row["quantity"] = _f(row.get("quantity")) + remaining
        row["qty"] = _f(row.get("qty")) + remaining
        row["cost_basis_usd"] = _f(row.get("cost_basis_usd")) + remaining_cost
        ids = row.get("position_ids")
        if isinstance(ids, list):
            ids.append(str(position_id))

        leverage = max(0.0, _f(raw.get("leverage")))
        if leverage > 0.0:
            row["leverage"] = max(_f(row.get("leverage"), 0.0), leverage)

        opentm = _f(raw.get("opentm"))
        prior_open = _f(row.get("kraken_open_time_epoch"))
        if opentm > 0.0 and (prior_open <= 0.0 or opentm < prior_open):
            row["kraken_open_time_epoch"] = opentm

    rows: list[MutableMapping[str, Any]] = []
    for symbol in sorted(aggregates):
        row = aggregates[symbol]
        quantity = max(0.0, _f(row.get("quantity")))
        cost_basis = max(0.0, _f(row.get("cost_basis_usd")))
        if quantity <= _EPS or cost_basis <= _EPS:
            continue
        entry = cost_basis / quantity
        if entry <= _EPS:
            continue
        ids = tuple(sorted(str(value) for value in row.get("position_ids", []) if str(value)))
        row["position_ids"] = ids
        row["position_id"] = ",".join(ids)
        row["entry_price"] = entry
        row["avg_entry_price"] = entry
        rows.append(row)

    return rows, "ok"


def _patch_position_rows() -> bool:
    module = importlib.import_module("bot.kraken_all_account_exit_runtime_patch")
    current = getattr(module, "_position_rows", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def position_rows_v365(broker: Any) -> Iterable[MutableMapping[str, Any]]:
        yielded: set[str] = set()
        try:
            for row in original(broker):
                if not isinstance(row, Mapping):
                    continue
                payload = dict(row)
                symbol = _canonical_symbol(payload.get("symbol"))
                if symbol:
                    yielded.add(symbol)
                yield payload
        except Exception as exc:
            LOGGER.warning(
                "KRAKEN_MARGIN_PROTECTIVE_SCAN_V365_BASE_ROWS_ERROR marker=%s error=%s:%s",
                MARKER, type(exc).__name__, exc,
            )

        rows, reason = _openposition_rows(broker)
        if reason != "ok":
            LOGGER.warning(
                "KRAKEN_MARGIN_PROTECTIVE_SCAN_V365_OPENPOSITIONS_UNAVAILABLE marker=%s reason=%s "
                "spot_rows_preserved=true margin_position_fabricated=false fail_closed=true",
                MARKER, reason,
            )
            return
        for row in rows:
            symbol = _canonical_symbol(row.get("symbol"))
            if not symbol or symbol in yielded:
                continue
            yielded.add(symbol)
            LOGGER.critical(
                "KRAKEN_MARGIN_PROTECTIVE_SCAN_V365_POSITION_VISIBLE marker=%s symbol=%s "
                "quantity=%.12f entry=%.8f position_ids=%s broker_position_state_only=true "
                "confirmed_fill_proof=false tracker_mutation=false order_submitted=false",
                MARKER, symbol, _f(row.get("quantity")), _f(row.get("entry_price")),
                row.get("position_ids", ()),
            )
            yield row

    setattr(position_rows_v365, _PATCH_ATTR, True)
    setattr(position_rows_v365, "__wrapped__", original)
    module._position_rows = position_rows_v365
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_kraken_margin_protective_scan_v365"] = _READY_FLAG
        return True
    except Exception:
        return False


def install_import_hook() -> bool:
    patched = manifest = False
    try:
        patched = _patch_position_rows()
        manifest = _register_manifest()
    except Exception as exc:
        LOGGER.exception(
            "RUNTIME_KRAKEN_MARGIN_PROTECTIVE_SCAN_V365_INSTALL_ERROR marker=%s error=%s:%s fail_closed=true",
            MARKER, type(exc).__name__, exc,
        )
    ready = bool(patched and manifest)
    os.environ[_READY_FLAG] = "1" if ready else "0"
    (LOGGER.critical if ready else LOGGER.error)(
        "RUNTIME_KRAKEN_MARGIN_PROTECTIVE_SCAN_V365_%s marker=%s ready=%s "
        "openpositions_long_visibility=true openpositions_same_pair_aggregation=true "
        "spot_tracker_mutation=false ack_not_fill=true execution_ready_unchanged=true "
        "v364_terminal_quantity_cap_required=true short_authority_unchanged=true "
        "forced_trade=false forced_activation=false kill_switch_unchanged=true "
        "rejection_history_unchanged=true "
        "writer_nonce_risk_capital_position_sync_ecel_broker_health_minimum_order_ack_fill_gates_unchanged=true "
        "safety_gates_bypassed=false",
        "READY" if ready else "NOT_READY", MARKER, str(ready).lower(),
    )
    return ready


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "RELEASE_ID", "install", "install_import_hook", "_openposition_rows", "_patch_position_rows"]
