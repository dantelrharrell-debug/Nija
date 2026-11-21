"""Authenticated Kraken protective-exit readback against independent ledger lots.

Only the existing nonce-owning broker may be used. This is a read-only v452
single-field producer, not an order placement, repair, or activation hook.
The trusted composition root must independently approve account pins, provider
IDs, and a complete current ledger-position reader.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import time
from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Any

from bot.kraken_authenticated_balance_provider import _amount, _snapshot_digest
from bot.kraken_authenticated_identity_v480 import make_kraken_account_identity_provider
from bot.kraken_authenticated_open_order_reconciliation_v482 import (
    _ORDER_ID, _broker_orders, _canonical_pair, _decimal, _id,
)
from bot.pretrade_attestation_validation_v452 import evidence_expiry_failure
from scripts.nija_kraken_readonly_history_collector_v441 import _broker_account_scope

STOP_TYPES = frozenset({"stop-loss", "stop-loss-limit", "trailing-stop", "trailing-stop-limit"})
PROFIT_TYPES = frozenset({"take-profit", "take-profit-limit"})
MAX_AGE = 60.0


class KrakenProtectionDenied(ValueError):
    """Fixed non-sensitive refusal code."""


def _flat_readers(broker, account_scope, approved_api_key_sha256, monitoring_category):
    def guard_flat_transport(read: Callable, api: Any) -> None:
        """Recheck the exact existing owner without any private read or mutation."""
        key = getattr(api, "key", None)
        if (not callable(read) or getattr(broker, "connected", False) is not True
                or _broker_account_scope(broker) != account_scope
                or getattr(broker, "api", None) is not api
                or getattr(broker, "_kraken_private_call", None) != read
                or getattr(broker, "_gateway_url", "")
                or getattr(broker, "_gateway_only_mode", False)
                or not isinstance(key, str) or not key
                or not hmac.compare_digest(hashlib.sha256(key.encode()).hexdigest(),
                                           approved_api_key_sha256.lower())):
            raise KrakenProtectionDenied("flat_exposure_transport_unverified")

    def flat_exposure(read: Callable, api: Any, expected_usd: Decimal | None = None) -> str:
        """Read complete supported-wallet exposure through the same pinned client."""
        results = {}
        for endpoint in ("BalanceEx", "OpenPositions"):
            guard_flat_transport(read, api)
            reply = read(endpoint, {}, category=monitoring_category)
            guard_flat_transport(read, api)
            if (not isinstance(reply, Mapping) or set(reply) != {"error", "result"}
                    or reply.get("error") != [] or not isinstance(reply.get("result"), Mapping)):
                raise KrakenProtectionDenied("flat_exposure_response_unverified")
            results[endpoint] = json.loads(json.dumps(reply["result"], allow_nan=False))
        if results["OpenPositions"]:
            raise KrakenProtectionDenied("flat_margin_exposure_present")
        balances = results["BalanceEx"]
        digest = _snapshot_digest(balances)  # Exact fields, finite amounts and paired credit fields.
        aliases = {"ZUSD": "USD", "USD": "USD", "XXBT": "BTC", "XBT": "BTC", "BTC": "BTC",
                   "XETH": "ETH", "ETH": "ETH"}
        seen = set()
        for asset, values in balances.items():
            canonical = aliases.get(asset)
            if canonical is None or canonical in seen:
                raise KrakenProtectionDenied("flat_asset_unsupported_or_ambiguous")
            seen.add(canonical)
            if any(_amount(value) != 0 for field, value in values.items()
                   if canonical != "USD" or field != "balance"):
                raise KrakenProtectionDenied("flat_balance_or_encumbrance_present")
        if expected_usd is not None:
            # Require an explicit USD row even for a proposed zero opening balance.
            cash = balances.get("ZUSD", balances.get("USD"))
            if cash is None or _amount(cash["balance"]) != expected_usd:
                raise KrakenProtectionDenied("opening_cash_mismatch")
        return digest

    return guard_flat_transport, flat_exposure


def rehearse_cash_only_baseline(
    broker: Any, *, account_scope: str, approved_api_key_sha256: str,
    approved_iban_sha256: str, reviewed_provider_id: str, monitoring_category: Any,
    identity_method: str = "response_echo", clock: Callable[[], float] = time.time,
    expected_usd: str | None = None,
) -> dict:
    """Check current default-wallet exposure without certifying origin, P&L or orders.

    An exposed account still needs the independent lot and protective-order path.
    No historic attribution, pending row, provider registration or order is changed.
    """
    if account_scope != "platform:kraken":
        raise KrakenProtectionDenied("reviewed_platform_scope_required")
    identity = make_kraken_account_identity_provider(
        broker, account_scope=account_scope, approved_api_key_sha256=approved_api_key_sha256,
        approved_iban_sha256=approved_iban_sha256, reviewed_provider_id=reviewed_provider_id,
        monitoring_category=monitoring_category, identity_method=identity_method, clock=clock,
    )
    guard, exposure = _flat_readers(broker, account_scope, approved_api_key_sha256,
                                    monitoring_category)
    try:
        if expected_usd is not None and not isinstance(expected_usd, str):
            raise KrakenProtectionDenied("opening_cash_requires_decimal_text")
        opening_cash = None if expected_usd is None else _amount(expected_usd)
        start = clock()
        api, read = broker.api, broker._kraken_private_call
        if identity().get("verified") is not True:
            raise KrakenProtectionDenied("broker_identity_unverified")
        observations = []
        for _ in range(2):
            guard(read, api)
            if _broker_orders(broker, monitoring_category=monitoring_category):
                raise KrakenProtectionDenied("flat_open_order_inventory_not_empty")
            observations.append(exposure(read, api, opening_cash))
        if identity().get("verified") is not True:
            raise KrakenProtectionDenied("broker_identity_changed")
        guard(read, api)
        if observations[0] != observations[1] or not 0 <= clock() - start <= MAX_AGE:
            raise KrakenProtectionDenied("readback_changed_or_stale")
        return {"supplied_usd_matched": opening_cash is not None,
                "default_wallet_cash_only_observed": True, "authorizes_orders": False,
                "collector_install_allowed": False, "historical_attribution_verified": False}
    except KrakenProtectionDenied:
        raise
    except Exception:
        raise KrakenProtectionDenied("cash_only_rehearsal_unavailable") from None


def make_kraken_protective_exit_provider(
    broker: Any, *, account_scope: str,
    approved_api_key_sha256: str, approved_iban_sha256: str,
    reviewed_provider_id: str, reviewed_ledger_provider_id: str,
    independent_positions: Callable[[], Mapping[str, Any]],
    monitoring_category: Any, clock: Callable[[], float] = time.time,
    identity_method: str = "response_echo",
) -> Callable[[], Mapping[str, Any]]:
    """Verify both exchange-side stop and take-profit orders for every ledger lot.

    The ledger reader must certify its own complete fills/positions snapshot.
    A flat account additionally needs complete reconciled intent/pending state,
    repeated empty exchange orders and independently read spot/margin exposure.
    Empty local tables alone never qualify. The flat branch supports only the
    reviewed USD/BTC/ETH default wallet, with no noncash balance, hold or credit.
    """
    if (account_scope != "platform:kraken"
            or not isinstance(reviewed_provider_id, str) or not reviewed_provider_id
            or not isinstance(reviewed_ledger_provider_id, str)
            or not reviewed_ledger_provider_id
            or reviewed_provider_id == reviewed_ledger_provider_id
            or not callable(independent_positions) or not callable(clock)
            or monitoring_category is None):
        raise KrakenProtectionDenied("reviewed_bindings_required")
    identity = make_kraken_account_identity_provider(
        broker, account_scope=account_scope,
        approved_api_key_sha256=approved_api_key_sha256,
        approved_iban_sha256=approved_iban_sha256,
        reviewed_provider_id=reviewed_provider_id,
        monitoring_category=monitoring_category, clock=clock, identity_method=identity_method,
    )

    guard_flat_transport, flat_exposure = _flat_readers(
        broker, account_scope, approved_api_key_sha256, monitoring_category
    )

    def ledger_snapshot() -> tuple:
        try:
            snap = independent_positions()
            now = clock()
        except Exception:
            raise KrakenProtectionDenied("independent_ledger_read_failed") from None
        if not isinstance(snap, Mapping):
            raise KrakenProtectionDenied("independent_ledger_invalid")
        stamp = snap.get("observed_at_epoch")
        if (snap.get("account") != account_scope
                or snap.get("provider_id") != reviewed_ledger_provider_id
                or snap.get("source") != "independent_ledger"
                or snap.get("snapshot_complete") is not True
                or snap.get("fills_reconciled") is not True
                or snap.get("positions_reconciled") is not True
                or not isinstance(snap.get("snapshot_id"), str)
                or not snap["snapshot_id"]
                or isinstance(stamp, bool) or not isinstance(stamp, (int, float))
                or not math.isfinite(stamp) or not 0 <= now - stamp <= MAX_AGE):
            raise KrakenProtectionDenied("independent_ledger_unverified")
        positions = snap.get("positions")
        if not isinstance(positions, Mapping) or len(positions) > 100:
            raise KrakenProtectionDenied("complete_positions_required")
        flat_source = None
        if not positions:
            provenance = snap.get("provenance")
            if (any(snap.get(field) is not True for field in (
                    "verified", "read_only", "scope_verified", "pending_closes_reconciled",
                    "outstanding_intents_reconciled"))
                    or snap.get("authorizes_orders") is not False
                    or not _id(snap.get("evidence_id")) or not _id(snap["snapshot_id"])
                    or not isinstance(snap.get("orders"), Mapping) or snap["orders"]
                    or type(snap.get("unresolved_submission_count")) is not int
                    or snap["unresolved_submission_count"] != 0
                    or not isinstance(provenance, Mapping)
                    or any(provenance.get(field) is not True for field in (
                        "account_scope_verified", "collector_identity_verified", "snapshot_complete",
                        "ledger_snapshot_verified", "complete_pagination_verified"))):
                raise KrakenProtectionDenied("complete_flat_ledger_proof_required")
            if stamp <= 0 or evidence_expiry_failure(snap, now_epoch=now) is not None:
                raise KrakenProtectionDenied("flat_ledger_expired_or_invalid")
            flat_source = (stamp, min(stamp + MAX_AGE, snap.get("expires_at_epoch", stamp + MAX_AGE)))
        normalized = []
        used = set()
        for lot_id, lot in positions.items():
            if (not isinstance(lot_id, str) or not lot_id
                    or not isinstance(lot, Mapping)
                    or set(lot) != {"pair", "side", "quantity", "stop_order_id", "take_profit_order_id"}
                    or lot.get("side") not in ("long", "short")):
                raise KrakenProtectionDenied("ledger_lot_invalid")
            try:
                pair = _canonical_pair(lot["pair"])
                qty = _decimal(lot["quantity"], positive=True)
            except Exception:
                raise KrakenProtectionDenied("ledger_quantity_invalid") from None
            stop, profit = lot["stop_order_id"], lot["take_profit_order_id"]
            if (not isinstance(stop, str) or not isinstance(profit, str)
                    or not _ORDER_ID.fullmatch(stop) or not _ORDER_ID.fullmatch(profit) or stop == profit
                    or stop in used or profit in used):
                raise KrakenProtectionDenied("exit_identity_missing_or_reused")
            used.update((stop, profit))
            normalized.append((lot_id, pair, lot["side"], qty, stop, profit))
        return (snap["snapshot_id"], tuple(sorted(normalized)), flat_source)

    def verify_coverage(positions: tuple, orders: Mapping[str, tuple]) -> None:
        for _lot, pair, side, quantity, stop_id, profit_id in positions:
            exit_side = "sell" if side == "long" else "buy"
            for order_id, allowed in ((stop_id, STOP_TYPES), (profit_id, PROFIT_TYPES)):
                row = orders.get(order_id)
                if row is None:
                    raise KrakenProtectionDenied("protective_order_not_open")
                order_pair, order_side, kind, _price, volume, executed = row
                remaining = Decimal(volume) - Decimal(executed)
                if (order_pair != pair or order_side != exit_side
                        or kind not in allowed or remaining < quantity):
                    raise KrakenProtectionDenied("protective_exit_coverage_mismatch")

    def observe() -> Mapping[str, Any]:
        try:
            start = clock()
            if not isinstance(start, (int, float)) or isinstance(start, bool) or not math.isfinite(start):
                raise KrakenProtectionDenied("clock_invalid")
            if identity().get("verified") is not True:
                raise KrakenProtectionDenied("broker_identity_unverified")
            first_ledger = ledger_snapshot()
            first_orders = _broker_orders(broker, monitoring_category=monitoring_category)
            flat = first_ledger[2] is not None
            if flat and first_orders:
                raise KrakenProtectionDenied("flat_open_order_inventory_not_empty")
            exposure_read, exposure_api = getattr(broker, "_kraken_private_call", None), getattr(broker, "api", None)
            first_exposure = flat_exposure(exposure_read, exposure_api) if flat else None
            second_orders = _broker_orders(broker, monitoring_category=monitoring_category)
            if flat and second_orders:
                raise KrakenProtectionDenied("flat_open_order_inventory_not_empty")
            second_exposure = flat_exposure(exposure_read, exposure_api) if flat else None
            second_ledger = ledger_snapshot()
            if flat:
                guard_flat_transport(exposure_read, exposure_api)
            if identity().get("verified") is not True:
                raise KrakenProtectionDenied("broker_identity_changed")
            if flat:
                guard_flat_transport(exposure_read, exposure_api)
            finish = clock()
            if (not isinstance(finish, (int, float)) or isinstance(finish, bool)
                    or not math.isfinite(finish) or not 0 <= finish - start <= MAX_AGE
                    or first_ledger[:2] != second_ledger[:2] or first_orders != second_orders
                    or first_exposure != second_exposure):
                raise KrakenProtectionDenied("readback_changed_or_stale")
            flat_details = {}
            evidence_parts = [first_ledger[0], sorted(first_orders.items())]
            if flat:
                if first_orders or second_ledger[2] is None:
                    raise KrakenProtectionDenied("flat_open_order_inventory_not_empty")
                oldest = min(start, first_ledger[2][0], second_ledger[2][0])
                expires = min(start + MAX_AGE, first_ledger[2][1], second_ledger[2][1])
                if not 0 < oldest <= finish < expires:
                    raise KrakenProtectionDenied("flat_ledger_expired_or_invalid")
                flat_details = {
                    "observed_at_epoch": oldest, "expires_at_epoch": expires,
                    "protection_status": "verified_flat_no_exits_required",
                }
                evidence_parts.append(first_exposure)
            verify_coverage(first_ledger[1], first_orders)
            digest = hashlib.sha256(json.dumps(
                evidence_parts,
                separators=(",", ":"),
            ).encode("utf-8")).hexdigest()
            return {
                "account": account_scope, "source": "authenticated_broker",
                "provider_id": reviewed_provider_id,
                "evidence_id": digest, "verified": True, "read_only": True,
                "scope_verified": True, "observed_at_epoch": start,
                "authorizes_orders": False,
                **flat_details,
                "provenance": {
                    "account_scope_verified": True,
                    "collector_identity_verified": True,
                    "snapshot_complete": True,
                    "authenticated_broker_read_verified": True,
                    "complete_pagination_verified": True,
                },
            }
        except KrakenProtectionDenied:
            raise
        except Exception:
            raise KrakenProtectionDenied("protective_readback_unavailable") from None

    return observe


__all__ = ["KrakenProtectionDenied", "make_kraken_protective_exit_provider"]
