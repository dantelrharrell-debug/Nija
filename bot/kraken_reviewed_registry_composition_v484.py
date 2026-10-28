"""Assemble an independently reviewed Kraken provider registry without installing it.

This boundary accepts the existing four authenticated Kraken providers and nine
separately reviewed authority providers. It performs no I/O, no registration,
no order submission and no activation. The trusted runtime remains responsible
for independently approving identities and providing actual source callables.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any

from bot.kraken_reviewed_producer_bundle_v483 import FIELDS as BROKER_FIELDS
from bot.pretrade_attestation_validation_v452 import REQUIRED, SOURCES


class KrakenRegistryIncomplete(ValueError):
    """Redacted composition failure; never includes credential material."""


def compose_reviewed_kraken_registry(
    *,
    broker_providers: Mapping[str, Callable[[], Mapping[str, Any]]],
    independent_providers: Mapping[str, Callable[[], Mapping[str, Any]]],
    trusted_provider_ids: Mapping[str, str],
    independently_reviewed: bool = False,
) -> tuple[Mapping[str, Callable[[], Mapping[str, Any]]], Mapping[str, str]]:
    """Validate a complete 13-field registry; return immutable, non-installed data.

    A passing composition is NOT a certification. Provider observations must
    subsequently pass the existing v452 source, account, freshness and
    provenance checks before the trusted composition root can register them.
    """
    if independently_reviewed is not True:
        raise KrakenRegistryIncomplete("independent_review_required")
    if not isinstance(broker_providers, Mapping) or set(broker_providers) != set(BROKER_FIELDS):
        raise KrakenRegistryIncomplete("broker_provider_set_incomplete")
    remaining = set(REQUIRED) - set(BROKER_FIELDS)
    if not isinstance(independent_providers, Mapping) or set(independent_providers) != remaining:
        raise KrakenRegistryIncomplete("independent_provider_set_incomplete")
    if not isinstance(trusted_provider_ids, Mapping) or set(trusted_provider_ids) != set(REQUIRED):
        raise KrakenRegistryIncomplete("trusted_provider_ids_incomplete")
    all_providers = {**broker_providers, **independent_providers}
    if any(not callable(all_providers[field]) for field in REQUIRED):
        raise KrakenRegistryIncomplete("provider_not_callable")
    # IDs are approved out of band; never derive them from a provider's
    # self-reported observation or from a runtime health flag.
    roles: dict[str, str] = {}
    for field in REQUIRED:
        provider_id = trusted_provider_ids[field]
        if (not isinstance(provider_id, str) or not provider_id
                or provider_id != provider_id.strip()
                or any(ch.isspace() for ch in provider_id)):
            raise KrakenRegistryIncomplete("trusted_provider_id_invalid")
        role = SOURCES[field]
        if roles.setdefault(provider_id, role) != role:
            raise KrakenRegistryIncomplete("cross_authority_identity_reuse")
    return (
        MappingProxyType({field: all_providers[field] for field in REQUIRED}),
        MappingProxyType({field: trusted_provider_ids[field] for field in REQUIRED}),
    )


__all__ = ["KrakenRegistryIncomplete", "compose_reviewed_kraken_registry"]
