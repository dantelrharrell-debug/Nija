"""Fail-closed composition of real Kraken providers; no automatic installation.

The caller must hold the existing nonce-owning broker and independently approved
account/key pins, ledger/intent readers and nine trusted producer identities.
This module cannot create broker evidence, authorize orders or register at import.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any

from bot.kraken_reviewed_producer_bundle_v483 import (
    FIELDS as BROKER_FIELDS, make_reviewed_kraken_producer_bundle,
)
from bot.kraken_protective_exit_readback_v485 import make_kraken_protective_exit_provider
from bot.pretrade_attestation_validation_v452 import REQUIRED
from bot.pretrade_multi_account_registration_v474 import register_reviewed_account_registry

ACCOUNT = "platform:kraken"
OTHER_FIELDS = frozenset(REQUIRED) - frozenset(BROKER_FIELDS) - {"protective_exit_readback"}


class KrakenCollectorBindingDenied(ValueError):
    """Fixed non-sensitive denial messages only."""


def compose_reviewed_kraken_providers(
    *, broker: Any, approved_api_key_sha256: str,
    approved_iban_sha256: str, reviewed_provider_ids: Mapping[str, str],
    independent_open_intents: Callable[[], Mapping[str, Any]],
    independent_positions: Callable[[], Mapping[str, Any]],
    independent_remaining: Mapping[str, Callable[[], Mapping[str, Any]]],
    monitoring_category: Any, independently_reviewed: bool = False,
    clock: Callable[[], float] | None = None,
) -> Mapping[str, Callable[[], Mapping[str, Any]]]:
    """Compose complete 13-field *callable registry*, without reading or installing.

    Remaining providers must be externally implemented against their approved
    independent sources. Validation here checks wiring, not truth of observations.
    """
    if independently_reviewed is not True:
        raise KrakenCollectorBindingDenied("independent_review_required")
    if (not isinstance(reviewed_provider_ids, Mapping)
            or set(reviewed_provider_ids) != set(REQUIRED)
            or any(not isinstance(value, str) or not value or value != value.strip()
                   for value in reviewed_provider_ids.values())
            or len(set(reviewed_provider_ids.values())) != len(REQUIRED)):
        raise KrakenCollectorBindingDenied("unique_complete_provider_registry_required")
    if (not isinstance(independent_remaining, Mapping)
            or set(independent_remaining) != OTHER_FIELDS
            or any(not callable(p) for p in independent_remaining.values())
            or not callable(independent_positions)):
        raise KrakenCollectorBindingDenied("independent_sources_incomplete")
    if (len({id(p) for p in independent_remaining.values()})
            != len(independent_remaining)):
        raise KrakenCollectorBindingDenied("independent_sources_reused")
    options = {} if clock is None else {"clock": clock}
    broker_ids = {field: reviewed_provider_ids[field] for field in BROKER_FIELDS}
    try:
        broker_providers = make_reviewed_kraken_producer_bundle(
            broker, account_scope=ACCOUNT,
            approved_api_key_sha256=approved_api_key_sha256,
            approved_iban_sha256=approved_iban_sha256,
            reviewed_provider_ids=broker_ids,
            reviewed_ledger_provider_id=reviewed_provider_ids["position_ledger_reconciliation"],
            independent_open_intents=independent_open_intents,
            monitoring_category=monitoring_category,
            independently_reviewed=True, **options,
        )
        exits = make_kraken_protective_exit_provider(
            broker, account_scope=ACCOUNT,
            approved_api_key_sha256=approved_api_key_sha256,
            approved_iban_sha256=approved_iban_sha256,
            reviewed_provider_id=reviewed_provider_ids["protective_exit_readback"],
            reviewed_ledger_provider_id=reviewed_provider_ids["position_ledger_reconciliation"],
            independent_positions=independent_positions,
            monitoring_category=monitoring_category, **options,
        )
    except Exception:
        raise KrakenCollectorBindingDenied("reviewed_producer_construction_failed") from None
    providers = dict(broker_providers)
    providers["protective_exit_readback"] = exits
    providers.update(independent_remaining)
    if set(providers) != set(REQUIRED):
        raise KrakenCollectorBindingDenied("complete_provider_registry_required")
    return MappingProxyType(providers)


def install_reviewed_kraken_collector(
    *, providers: Mapping[str, Callable[[], Mapping[str, Any]]],
    reviewed_provider_ids: Mapping[str, str],
    independently_reviewed: bool = False,
    backup_restore_certified: bool = False,
    broker_ledger_exits_certified: bool = False,
) -> None:
    """Explicit trusted-root-only diagnostic install; NEVER grants order authority.

    Boolean arguments are *operator approvals*, NOT substitutes for independent
    proof. The trusted caller must verify the actual receipts before invoking.
    """
    if (independently_reviewed is not True
            or backup_restore_certified is not True
            or broker_ledger_exits_certified is not True):
        raise KrakenCollectorBindingDenied("independent_production_certification_required")
    if (not isinstance(providers, Mapping) or set(providers) != set(REQUIRED)
            or not all(callable(p) for p in providers.values())):
        raise KrakenCollectorBindingDenied("complete_provider_registry_required")
    register_reviewed_account_registry(
        providers_by_account={ACCOUNT: providers},
        trusted_provider_ids=reviewed_provider_ids,
        independently_reviewed=True,
    )


__all__ = [
    "ACCOUNT", "OTHER_FIELDS", "KrakenCollectorBindingDenied",
    "compose_reviewed_kraken_providers", "install_reviewed_kraken_collector",
]
