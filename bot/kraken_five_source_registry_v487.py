"""Compose five reviewed Kraken broker producers and eight independent checks.

Read-only, offline composition. No producer is invoked, no collector is installed,
and no trading authority is granted. The existing v484 composition gate remains
responsible for source separation and completeness. Production callers must
obtain the protective provider from the reviewed v485 factory, bound to the
existing nonce-owning Kraken client and independently reconciled ledger lots.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from bot.kraken_reviewed_producer_bundle_v483 import FIELDS as FOUR_FIELDS
from bot.kraken_reviewed_registry_composition_v484 import (
    KrakenRegistryIncomplete,
    compose_reviewed_kraken_registry,
)
from bot.pretrade_attestation_validation_v452 import REQUIRED

PROTECTIVE_FIELD = "protective_exit_readback"
REMAINING_FIELDS = frozenset(REQUIRED) - frozenset(FOUR_FIELDS) - {PROTECTIVE_FIELD}


def compose_five_source_kraken_registry(
    *,
    broker_providers: Mapping[str, Callable[[], Mapping[str, Any]]],
    protective_exit_provider: Callable[[], Mapping[str, Any]],
    independent_providers: Mapping[str, Callable[[], Mapping[str, Any]]],
    trusted_provider_ids: Mapping[str, str],
    independently_reviewed: bool = False,
):
    """Return immutable 13-source registry; never install or execute providers.

    A caller-supplied callable is not proof of its provenance. The trusted
    composition root must audit the v485 factory and actual independent lot
    reader before passing independently_reviewed=True. Subsequent authenticated
    observations must pass v452 before the collector can be registered.
    """
    if independently_reviewed is not True:
        raise KrakenRegistryIncomplete("independent_review_required")
    if not isinstance(broker_providers, Mapping) or set(broker_providers) != set(FOUR_FIELDS):
        raise KrakenRegistryIncomplete("broker_provider_set_incomplete")
    if not callable(protective_exit_provider):
        raise KrakenRegistryIncomplete("protective_exit_provider_required")
    if not isinstance(independent_providers, Mapping) or set(independent_providers) != REMAINING_FIELDS:
        raise KrakenRegistryIncomplete("independent_provider_set_incomplete")
    return compose_reviewed_kraken_registry(
        broker_providers=broker_providers,
        independent_providers={
            **independent_providers,
            PROTECTIVE_FIELD: protective_exit_provider,
        },
        trusted_provider_ids=trusted_provider_ids,
        independently_reviewed=True,
    )


__all__ = ["REMAINING_FIELDS", "compose_five_source_kraken_registry"]
