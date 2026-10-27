"""v483: bind reviewed Kraken read-only producers without installing a collector.

This adapter intentionally exposes only FOUR of thirteen required v452 fields.
It is NOT an installation hook or a source of execution authority. The trusted
composition root must own the existing serialized authenticated broker, approve
pins and producer identities out-of-band, and supply a genuinely independent
ledger-intent reader. Missing fields must NEVER be filled with placeholders.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any

from bot.kraken_authenticated_balance_provider import make_kraken_balance_provider
from bot.kraken_authenticated_identity_v480 import make_kraken_account_identity_provider
from bot.kraken_authenticated_key_info_v477 import make_kraken_key_permission_provider
from bot.kraken_authenticated_open_order_reconciliation_v482 import (
    make_kraken_open_order_reconciliation_provider,
)
from bot.pretrade_attestation_validation_v452 import REQUIRED

FIELDS = (
    "account_permissions",
    "account_identity",
    "broker_balances",
    "open_order_reconciliation",
)
MISSING_FIELDS = tuple(field for field in REQUIRED if field not in FIELDS)
_HEX = frozenset("0123456789abcdefABCDEF")


class KrakenCompositionDenied(ValueError):
    """Fixed non-sensitive failure label only."""


def _identifier(value: Any) -> bool:
    return (
        isinstance(value, str) and bool(value) and value == value.strip()
        and not any(character.isspace() for character in value)
    )


def _reviewed_pin(value: Any) -> bool:
    return (
        isinstance(value, str) and len(value) == 64
        and all(character in _HEX for character in value)
    )


def make_reviewed_kraken_producer_bundle(
    broker: Any, *,
    account_scope: str,
    approved_api_key_sha256: str,
    approved_iban_sha256: str,
    reviewed_provider_ids: Mapping[str, str],
    reviewed_ledger_provider_id: str,
    independent_open_intents: Callable[[], Mapping[str, Any]],
    monitoring_category: Any,
    independently_reviewed: bool = False,
    clock: Callable[[], float] | None = None,
) -> Mapping[str, Callable[[], Mapping[str, Any]]]:
    """Construct four independent-field brokers using one existing nonce owner.

    These factories perform no broker I/O at construction. They share one exact
    broker object and one externally approved account/key binding. Observations
    remain subject to each producer's own fail-closed checks. The returned
    mapping is immutable, partial and NOT registered anywhere.
    """
    if independently_reviewed is not True:
        raise KrakenCompositionDenied("independent_review_required")
    # The balance provider covers only Kraken's independently mapped default
    # wallet. Do not silently assume a member account or subwallet is covered.
    if account_scope != "platform:kraken":
        raise KrakenCompositionDenied("default_wallet_scope_only")
    if not (_reviewed_pin(approved_api_key_sha256)
            and _reviewed_pin(approved_iban_sha256)):
        raise KrakenCompositionDenied("independently_approved_pins_required")
    if (not isinstance(reviewed_provider_ids, Mapping)
            or set(reviewed_provider_ids) != set(FIELDS)
            or any(not _identifier(reviewed_provider_ids[field]) for field in FIELDS)
            or not _identifier(reviewed_ledger_provider_id)
            or reviewed_ledger_provider_id in set(reviewed_provider_ids.values())):
        raise KrakenCompositionDenied("independent_provider_registry_required")
    if (not callable(independent_open_intents) or monitoring_category is None
            or (clock is not None and not callable(clock))):
        raise KrakenCompositionDenied("trusted_runtime_bindings_required")
    if (broker is None
            or not callable(getattr(broker, "_kraken_private_call", None))):
        raise KrakenCompositionDenied("existing_nonce_owner_required")

    common = dict(
        broker=broker,
        account_scope=account_scope,
        approved_api_key_sha256=approved_api_key_sha256,
        monitoring_category=monitoring_category,
    )
    if clock is not None:
        common["clock"] = clock

    # Each producer remains responsible for its own authenticated reads,
    # exact scope/identity continuity, freshness, and redacted observations.
    # Constructor exceptions carry no broker response or secret payload.
    try:
        permissions = make_kraken_key_permission_provider(
            **common,
            reviewed_provider_id=reviewed_provider_ids["account_permissions"],
        )
        identity = make_kraken_account_identity_provider(
            **common,
            approved_iban_sha256=approved_iban_sha256,
            reviewed_provider_id=reviewed_provider_ids["account_identity"],
        )
        balances = make_kraken_balance_provider(
            **common,
            approved_iban_sha256=approved_iban_sha256,
            reviewed_provider_id=reviewed_provider_ids["broker_balances"],
        )
        open_orders = make_kraken_open_order_reconciliation_provider(
            **common,
            approved_iban_sha256=approved_iban_sha256,
            reviewed_provider_id=reviewed_provider_ids["open_order_reconciliation"],
            reviewed_ledger_provider_id=reviewed_ledger_provider_id,
            independent_open_intents=independent_open_intents,
        )
    except Exception:
        raise KrakenCompositionDenied("reviewed_provider_construction_failed") from None

    return MappingProxyType({
        "account_permissions": permissions,
        "account_identity": identity,
        "broker_balances": balances,
        "open_order_reconciliation": open_orders,
    })


__all__ = [
    "FIELDS", "MISSING_FIELDS", "KrakenCompositionDenied",
    "make_reviewed_kraken_producer_bundle",
]
