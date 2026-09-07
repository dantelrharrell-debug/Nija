"""Kraken BTNL emergency-exit identity convergence v395.

The Kraken account exit scanner uses a standard exchange pair for public pricing.
For US retail leveraged positions, private execution belongs to the Bitnomial
venue identity (for example ``ETHUSD:BTNL``). Passing the public pair into the
exit submitter can drop margin identity and make a protective SELL look like a
1x non-reduce-only spot order.

v395 keeps those identities separate:
* public/reference pricing may use the standard pair;
* immediately before an account exit, authenticated OpenPositions must prove a
  matching open long BTNL margin identity;
* when proven, the existing fill-confirmed protective exit wrapper is invoked
  with that exact BTNL symbol and no more than broker-open remaining units;
* get_current_price strips ``:BTNL`` only for the read-only price query on the
  exact Kraken adapter class, while the PipelineRequest/private order symbol
  remains unchanged;
* ambiguous/mixed BTNL exposure fails closed and never falls back to spot.

No fill, order acknowledgement, position, leverage, or readiness is fabricated.
No BUY/new-exposure path is modified.
"""
from __future__ import annotations

import importlib
import logging
import math
import os
from collections.abc import Mapping
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_kraken_btnl_exit_identity_v395")
MARKER = "20260907-kraken-btnl-exit-identity-v395"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_BTNL_EXIT_IDENTITY_V395_READY"
_PATCH_ATTR = "_nija_btnl_exit_identity_v395"
_PRICE_PATCH_ATTR = "_nija_btnl_reference_price_v395"
_V265_SENTINEL = "_nija_protective_exit_submit_v265"
_EPS = 1e-12


def _f(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except Exception:
        return default


def _compact_head(value: Any) -> str:
    raw = str(value or "").strip().upper()
    if not raw:
        return ""
    head = raw.split(":", 1)[0]
    return head.replace("/", "").replace("-", "").replace("_", "")


def _btnl_identity(value: Any) -> str:
    raw = str(value or "").strip().upper()
    if not raw or ":" not in raw:
        return ""
    head, suffix = raw.split(":", 1)
    if suffix != "BTNL":
        return ""
    compact = _compact_head(head)
    return f"{compact}:BTNL" if compact else ""


def _private_openpositions(broker: Any) -> tuple[bool, Mapping[str, Any], str]:
    try:
        v366 = importlib.import_module("bot.runtime_kraken_margin_canonical_coverage_v366_patch")
        getter = getattr(v366, "_private_call", None)
        api_call = getter(broker) if callable(getter) else None
    except Exception as exc:
        return False, {}, f"private_call_resolve:{type(exc).__name__}"
    if not callable(api_call):
        return False, {}, "kraken_private_api_unavailable"
    try:
        payload = api_call("OpenPositions", {"docalcs": "true"})
    except Exception as exc:
        return False, {}, f"openpositions_exception:{type(exc).__name__}"
    if not isinstance(payload, Mapping):
        return False, {}, "invalid_openpositions_payload"
    errors = payload.get("error") or []
    if isinstance(errors, str):
        errors = [errors]
    if errors:
        return False, {}, "openpositions_rejected:" + ",".join(str(x) for x in errors)
    rows = payload.get("result") or {}
    if not isinstance(rows, Mapping):
        return False, {}, "invalid_openpositions_result"
    return True, rows, "ok"


def _discover_btnl_long(broker: Any, public_pair: str) -> dict[str, Any]:
    ok, rows, reason = _private_openpositions(broker)
    if not ok:
        return {"ok": False, "found": False, "reason": reason}

    target = _compact_head(public_pair)
    groups: dict[str, dict[str, Any]] = {}
    opposite = False
    for position_id, raw in rows.items():
        if not isinstance(raw, Mapping):
            continue
        identity = _btnl_identity(raw.get("pair"))
        if not identity or _compact_head(identity) != target:
            continue
        volume = max(0.0, _f(raw.get("vol")))
        closed = max(0.0, _f(raw.get("vol_closed")))
        remaining = max(0.0, volume - closed)
        if remaining <= _EPS:
            continue
        side = str(raw.get("type") or "").strip().lower()
        if side != "buy":
            opposite = True
            continue
        group = groups.setdefault(
            identity,
            {"remaining_units": 0.0, "position_ids": [], "leverage_values": []},
        )
        group["remaining_units"] += remaining
        group["position_ids"].append(str(position_id))
        cost = max(0.0, _f(raw.get("cost")))
        margin = max(0.0, _f(raw.get("margin")))
        if cost > _EPS and margin > _EPS:
            inferred = int(round(cost / margin))
            if 2 <= inferred <= 3:
                group["leverage_values"].append(inferred)

    if opposite:
        return {
            "ok": False,
            "found": bool(groups),
            "reason": "mixed_direction_btnl_openpositions",
            "ambiguous": True,
        }
    if not groups:
        return {"ok": True, "found": False, "reason": "no_matching_btnl_long"}
    if len(groups) != 1:
        return {
            "ok": False,
            "found": True,
            "reason": "multiple_btnl_execution_identities",
            "ambiguous": True,
            "identities": tuple(sorted(groups)),
        }

    identity, group = next(iter(groups.items()))
    remaining = max(0.0, _f(group.get("remaining_units")))
    if remaining <= _EPS:
        return {"ok": True, "found": False, "reason": "matching_btnl_long_closed"}
    leverage_values = list(group.get("leverage_values") or ())
    return {
        "ok": True,
        "found": True,
        "reason": "authenticated_openpositions_btnl_long",
        "symbol": identity,
        "remaining_units": remaining,
        "position_ids": tuple(group.get("position_ids") or ()),
        "leverage": max(leverage_values) if leverage_values else None,
        "broker_position_state_only": True,
        "confirmed_fill_proof": False,
    }


def _known_btnl_margin_intent(account: str, public_pair: str) -> bool:
    compact = _compact_head(public_pair)
    if not compact:
        return False
    candidate = f"{compact}:BTNL"
    try:
        ledger_module = importlib.import_module("bot.margin_position_ledger")
        ledger = ledger_module.get_margin_position_ledger()
    except Exception:
        return False

    account_candidates = [str(account or "").strip().lower()]
    if account_candidates[0] == "platform:kraken":
        account_candidates.append("platform")
    for account_id in dict.fromkeys(x for x in account_candidates if x):
        try:
            row = ledger.get_record(
                broker="kraken",
                account_id=account_id,
                subaccount_id="",
                symbol=candidate,
                asset_class="crypto",
            ) or {}
        except Exception:
            continue
        lifecycle = str(row.get("lifecycle_status") or "").strip().lower()
        leverage = int(max(1.0, _f(row.get("leverage"), 1.0)))
        if leverage > 1 and lifecycle in {"pending_open", "open", "reducing"}:
            return True
    return False


def _patch_reference_price_class(broker: Any) -> bool:
    cls = type(broker)
    current = getattr(cls, "get_current_price", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PRICE_PATCH_ATTR, False)):
        return True

    @wraps(current)
    def get_current_price_v395(self: Any, symbol: str, *args: Any, **kwargs: Any):
        raw = str(symbol or "").strip()
        lookup = raw[:-5] if raw.upper().endswith(":BTNL") else raw
        if lookup != raw:
            LOGGER.info(
                "KRAKEN_BTNL_REFERENCE_PRICE_V395 marker=%s execution_symbol=%s lookup_symbol=%s "
                "read_only_translation=true private_order_symbol_unchanged=true safety_gates_bypassed=false",
                MARKER, raw, lookup,
            )
        return current(self, lookup, *args, **kwargs)

    setattr(get_current_price_v395, _PRICE_PATCH_ATTR, True)
    setattr(get_current_price_v395, "__wrapped__", current)
    cls.get_current_price = get_current_price_v395
    return True


def _ensure_v265(module: Any) -> bool:
    current = getattr(module, "_submit_exit", None)
    if callable(current) and bool(getattr(current, _V265_SENTINEL, False)):
        return True
    try:
        v265 = importlib.import_module("bot.runtime_protective_exit_authority_v265_patch")
        patcher = getattr(v265, "_patch_kraken_exit_submit", None)
        if callable(patcher):
            patcher(module)
    except Exception:
        return False
    current = getattr(module, "_submit_exit", None)
    return bool(callable(current) and getattr(current, _V265_SENTINEL, False))


def _patch_exit_submit() -> bool:
    module = importlib.import_module("bot.kraken_all_account_exit_runtime_patch")
    if not _ensure_v265(module):
        return False
    current = getattr(module, "_submit_exit", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def submit_exit_v395(
        broker: Any,
        account: str,
        pair: str,
        quantity: float,
        reason: str,
    ):
        requested = max(0.0, _f(quantity))
        if requested <= _EPS:
            return {"status": "error", "error": "btnl_exit_no_requested_quantity"}

        truth = _discover_btnl_long(broker, pair)
        if not truth.get("ok"):
            known_margin = _known_btnl_margin_intent(account, pair)
            LOGGER.error(
                "KRAKEN_BTNL_EXIT_V395_PROOF_FAILED marker=%s account=%s public_pair=%s reason=%s "
                "known_margin_intent=%s fail_closed=%s spot_fallback_allowed=%s new_exposure=false",
                MARKER, account, pair, truth.get("reason"),
                str(known_margin).lower(), str(known_margin).lower(), str(not known_margin).lower(),
            )
            if known_margin or truth.get("ambiguous"):
                return {
                    "status": "error",
                    "error": f"btnl_exit_identity_unproven:{truth.get('reason')}",
                    "margin": True,
                    "symbol": pair,
                }
            return current(broker, account, pair, requested, reason)

        if not truth.get("found"):
            return current(broker, account, pair, requested, reason)

        execution_symbol = str(truth.get("symbol") or "").strip()
        remaining = max(0.0, _f(truth.get("remaining_units")))
        if not execution_symbol.endswith(":BTNL") or remaining <= _EPS:
            return {
                "status": "error",
                "error": "btnl_exit_invalid_authoritative_position",
                "margin": True,
                "symbol": pair,
            }

        if not _patch_reference_price_class(broker):
            return {
                "status": "error",
                "error": "btnl_exit_reference_price_bridge_unavailable",
                "margin": True,
                "symbol": execution_symbol,
            }

        safe_quantity = min(requested, remaining)
        LOGGER.critical(
            "KRAKEN_BTNL_EXIT_V395_ROUTED marker=%s account=%s public_pair=%s execution_symbol=%s "
            "requested=%.12f broker_remaining=%.12f submitted=%.12f leverage=%s "
            "authenticated_openpositions=true sell_only=true exit_intent_preserved=true "
            "reduce_only_derived_from_authoritative_margin=true no_spot_fallback=true new_exposure=false "
            "ack_not_fill=true safety_gates_bypassed=false",
            MARKER, account, pair, execution_symbol, requested, remaining, safe_quantity,
            truth.get("leverage"),
        )
        return current(broker, account, execution_symbol, safe_quantity, reason)

    setattr(submit_exit_v395, _PATCH_ATTR, True)
    setattr(submit_exit_v395, _V265_SENTINEL, True)
    setattr(submit_exit_v395, "__wrapped__", current)
    module._submit_exit = submit_exit_v395
    return True


def install_import_hook() -> bool:
    patched = False
    try:
        patched = _patch_exit_submit()
    except Exception as exc:
        LOGGER.exception(
            "RUNTIME_KRAKEN_BTNL_EXIT_IDENTITY_V395_INSTALL_ERROR marker=%s error=%s:%s "
            "fail_closed=true new_exposure=false safety_gates_bypassed=false",
            MARKER, type(exc).__name__, exc,
        )
    os.environ[_READY_FLAG] = "1" if patched else "0"
    (LOGGER.critical if patched else LOGGER.error)(
        "RUNTIME_KRAKEN_BTNL_EXIT_IDENTITY_V395_%s marker=%s ready=%s "
        "authenticated_openpositions_before_btnl_route=true public_price_execution_identity_split=true "
        "v265_fill_confirmation_preserved=true margin_quantity_capped=true mixed_direction_fail_closed=true "
        "spot_fallback_blocked_for_known_or_ambiguous_margin=true sell_only=true new_exposure=false "
        "writer_nonce_risk_ecel_broker_health_fill_gates_unchanged=true safety_gates_bypassed=false",
        "READY" if patched else "NOT_READY", MARKER, str(patched).lower(),
    )
    return patched


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER", "install", "install_import_hook", "_discover_btnl_long",
    "_patch_reference_price_class", "_patch_exit_submit", "_btnl_identity",
]
