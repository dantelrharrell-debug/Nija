"""Explicit 13-provider Kraken collector connection at the reviewed runtime boundary.

No import-time installation, automatic approval, broker construction, or order
authorization. The trusted production root must supply the real broker, source
owners, independently approved identity pins and certification receipts.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from bot.kraken_reviewed_collector_bridge import (
    compose_authenticated_kraken_collector_sources,
)
from bot.kraken_collector_composition_v487 import (
    install_reviewed_kraken_collector,
)
from bot.pretrade_attestation_validation_v452 import REQUIRED


class KrakenCollectorConnectionDenied(PermissionError):
    """Non-sensitive denial for incomplete independent certification."""


def connect_reviewed_kraken_collector(
    *,
    broker: Any,
    approved_api_key_sha256: str,
    approved_iban_sha256: str,
    reviewed_provider_ids: Mapping[str, str],
    independent_open_intents: Callable[[], Mapping[str, Any]],
    independent_positions: Callable[[], Mapping[str, Any]],
    independent_remaining: Mapping[str, Callable[[], Mapping[str, Any]]],
    reviewed_source_owners: Mapping[str, str],
    monitoring_category: Any,
    independently_reviewed: bool = False,
    backup_restore_certified: bool = False,
    broker_ledger_exits_certified: bool = False,
) -> None:
    """Connect reviewed sources to the existing diagnostic-only collector.

    The three certification flags attest external reviews, not their existence.
    Only a trusted production owner holding actual independent receipts may set
    them. Registration itself samples all 13 sources and rejects stale or
    invalid evidence before replacing the process-wide collector.
    """
    if (independently_reviewed is not True
            or backup_restore_certified is not True
            or broker_ledger_exits_certified is not True):
        raise KrakenCollectorConnectionDenied(
            "independent_production_certification_required"
        )
    providers = compose_authenticated_kraken_collector_sources(
        broker=broker,
        approved_api_key_sha256=approved_api_key_sha256,
        approved_iban_sha256=approved_iban_sha256,
        reviewed_provider_ids=reviewed_provider_ids,
        independent_open_intents=independent_open_intents,
        independent_positions=independent_positions,
        independent_remaining=independent_remaining,
        reviewed_source_owners=reviewed_source_owners,
        monitoring_category=monitoring_category,
        independently_reviewed=True,
    )
    if (not isinstance(providers, Mapping)
            or set(providers) != set(REQUIRED)
            or any(not callable(provider) for provider in providers.values())
            or len({id(provider) for provider in providers.values()}) != len(REQUIRED)):
        raise KrakenCollectorConnectionDenied("complete_provider_registry_required")
    install_reviewed_kraken_collector(
        providers=providers,
        reviewed_provider_ids=reviewed_provider_ids,
        independently_reviewed=True,
        backup_restore_certified=True,
        broker_ledger_exits_certified=True,
    )


__all__ = ["KrakenCollectorConnectionDenied", "connect_reviewed_kraken_collector"]
