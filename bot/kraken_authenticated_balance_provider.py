"""Pinned, read-only Kraken default-wallet balance evidence.

The reviewed composition root must bind the existing direct Kraken client and
independently approved account/key pins. This provider covers broker_balances
only. It neither installs a collector nor certifies ledger, exits or authority.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import time
from collections.abc import Callable, Mapping
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

from bot.kraken_authenticated_identity_v480 import make_kraken_account_identity_provider
from bot.kraken_authenticated_key_info_v477 import _sha256_fingerprint

_ASSET = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_FIELDS = frozenset({"balance", "hold_trade", "credit", "credit_used"})
_MAX_ASSETS = 4096


class KrakenBalanceDenied(ValueError):
    """Fixed refusal label; never include broker payloads or credentials."""


def _amount(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise KrakenBalanceDenied("balance_amount_invalid")
    text = str(value)
    if len(text) > 128:
        raise KrakenBalanceDenied("balance_amount_invalid")
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError):
        raise KrakenBalanceDenied("balance_amount_invalid") from None
    if not number.is_finite() or number < 0 or (number and abs(number.adjusted()) > 60):
        raise KrakenBalanceDenied("balance_amount_invalid")
    return number


def _snapshot_digest(rows: Any) -> str:
    if not isinstance(rows, Mapping) or len(rows) > _MAX_ASSETS:
        raise KrakenBalanceDenied("balance_snapshot_invalid")
    normalized: dict[str, dict[str, str]] = {}
    for asset, row in rows.items():
        if not isinstance(asset, str) or not _ASSET.fullmatch(asset):
            raise KrakenBalanceDenied("balance_asset_invalid")
        if (not isinstance(row, Mapping) or set(row) - _FIELDS
                or not {"balance", "hold_trade"}.issubset(row)
                or ("credit" in row) != ("credit_used" in row)):
            raise KrakenBalanceDenied("balance_fields_incomplete_or_unknown")
        values = {key: _amount(value) for key, value in row.items()}
        # Kraken omits both credit fields for accounts without a credit line.
        # Keep asset variants distinct; never sum staking/rewards into cash.
        with localcontext() as context:
            context.prec = 256
            available = (values["balance"] + values.get("credit", Decimal(0))
                         - values.get("credit_used", Decimal(0)) - values["hold_trade"])
        if available < 0:
            raise KrakenBalanceDenied("balance_available_negative")
        normalized[asset] = {key: format(value, "f") for key, value in values.items()}
    # Empty is valid for BalanceEx, but never establishes a reconciled ledger.
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def make_kraken_balance_provider(
    broker: Any, *, account_scope: str, approved_iban_sha256: str,
    approved_api_key_sha256: str, reviewed_provider_id: str,
    monitoring_category: Any, clock: Callable[[], float] = time.time,
) -> Callable[[], Mapping[str, Any]]:
    """Build a single-field provider for an independently mapped default wallet.

    Pins and the default-wallet/account mapping must be independently reviewed.
    No account selector, alternate transport, credential or nonce owner is made.
    The same existing authenticated client owns all three reads. Observations
    expose only a digest; raw asset balances and key/account pins stay private.
    Gateway and multi-wallet coverage require separately reviewed providers.
    """
    identity = make_kraken_account_identity_provider(
        broker, account_scope=account_scope, approved_iban_sha256=approved_iban_sha256,
        approved_api_key_sha256=approved_api_key_sha256,
        reviewed_provider_id=reviewed_provider_id,
        monitoring_category=monitoring_category, clock=clock,
    )
    key_pin = _sha256_fingerprint(approved_api_key_sha256)

    def guard_transport() -> None:
        if getattr(broker, "_gateway_url", "") or getattr(broker, "_gateway_only_mode", False):
            raise KrakenBalanceDenied("direct_authenticated_transport_required")
        key = getattr(getattr(broker, "api", None), "key", None)
        if (not isinstance(key, str) or not key
                or not hmac.compare_digest(hashlib.sha256(key.encode("utf-8")).hexdigest(),
                                           key_pin)):
            raise KrakenBalanceDenied("pinned_transport_key_unverified")

    def observe() -> Mapping[str, Any]:
        guard_transport()
        try:
            before = identity()
        except Exception:
            raise KrakenBalanceDenied("authenticated_balance_identity_unverified") from None
        guard_transport()
        try:
            response = broker._kraken_private_call("BalanceEx", {}, category=monitoring_category)
        except Exception:
            raise KrakenBalanceDenied("authenticated_balance_read_failed") from None
        guard_transport()
        if (not isinstance(response, Mapping) or set(response) != {"error", "result"}
                or response.get("error") != []):
            raise KrakenBalanceDenied("authenticated_balance_response_unverified")
        digest = _snapshot_digest(response["result"])
        try:
            after = identity()
        except Exception:
            raise KrakenBalanceDenied("authenticated_balance_identity_unverified") from None
        guard_transport()
        started, finished = before["observed_at_epoch"], clock()
        if (isinstance(finished, bool) or not isinstance(finished, (int, float))
                or not math.isfinite(finished) or not 0 <= finished - started <= 60
                or after["observed_at_epoch"] < started):
            raise KrakenBalanceDenied("balance_observation_stale_or_invalid")
        evidence_id = hashlib.sha256(
            ("kraken-default-wallet-balances:" + account_scope + ":" + digest + ":" + repr(started))
            .encode("utf-8")
        ).hexdigest()
        return {
            "account": account_scope, "source": "authenticated_broker",
            "provider_id": reviewed_provider_id, "evidence_id": evidence_id,
            "verified": True, "read_only": True, "scope_verified": True,
            "observed_at_epoch": started, "authorizes_orders": False,
            "provenance": {
                "account_scope_verified": True, "collector_identity_verified": True,
                "snapshot_complete": True, "authenticated_broker_read_verified": True,
                "complete_pagination_verified": True,
            },
        }

    return observe


__all__ = ["KrakenBalanceDenied", "make_kraken_balance_provider"]
