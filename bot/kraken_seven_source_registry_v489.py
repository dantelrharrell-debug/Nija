"""v489: seven-source reviewed Kraken registry composition; diagnostic only.

Combines four existing authenticated broker producers, v485 protective-exit
readback, and v488 read-only writer/nonce observations. The remaining six
independent sources MUST be supplied by independently approved production
owners. No provider is invoked and no order authority is granted.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from bot.kraken_five_source_registry_v487 import compose_five_source_kraken_registry
from bot.kraken_reviewed_registry_composition_v484 import KrakenRegistryIncomplete
from bot.kraken_writer_nonce_evidence_v488 import FIELDS as WRITER_FIELDS
from bot.pretrade_attestation_validation_v452 import REQUIRED

SEVEN_FIELDS = frozenset((
    "account_permissions", "account_identity", "broker_balances",
    "open_order_reconciliation", "protective_exit_readback",
    *WRITER_FIELDS,
))
REMAINING_FIELDS = frozenset(REQUIRED) - SEVEN_FIELDS


def compose_seven_source_kraken_registry(
    *, broker_providers: Mapping[str, Callable[[], Mapping[str, Any]]],
    protective_exit_provider: Callable[[], Mapping[str, Any]],
    writer_nonce_providers: Mapping[str, Callable[[], Mapping[str, Any]]],
    independent_providers: Mapping[str, Callable[[], Mapping[str, Any]]],
    trusted_provider_ids: Mapping[str, str],
    independently_reviewed: bool = False,
):
    """Compose all 13 only with six complete, independently owned sources.

    No factories or sources are invoked. A passing composition does not mean
    observations passed, and never installs the collector or enables trading.
    """
    if independently_reviewed is not True:
        raise KrakenRegistryIncomplete("independent_review_required")
    if (not isinstance(writer_nonce_providers, Mapping)
            or set(writer_nonce_providers) != set(WRITER_FIELDS)
            or not all(callable(v) for v in writer_nonce_providers.values())):
        raise KrakenRegistryIncomplete("writer_nonce_sources_incomplete")
    if (not isinstance(independent_providers, Mapping)
            or set(independent_providers) != REMAINING_FIELDS
            or not all(callable(v) for v in independent_providers.values())):
        raise KrakenRegistryIncomplete("six_independent_sources_incomplete")
    return compose_five_source_kraken_registry(
        broker_providers=broker_providers,
        protective_exit_provider=protective_exit_provider,
        independent_providers={**writer_nonce_providers, **independent_providers},
        trusted_provider_ids=trusted_provider_ids,
        independently_reviewed=True,
    )


__all__ = ["SEVEN_FIELDS", "REMAINING_FIELDS", "compose_seven_source_kraken_registry"]
