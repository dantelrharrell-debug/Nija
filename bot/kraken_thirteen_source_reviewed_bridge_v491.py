"""Bridge reviewed six-source ownership into the existing seven-source registry.

This module is an offline composition boundary only. It does not call any
provider, register a collector, mutate production, or authorize trading.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from bot.kraken_seven_source_registry_v489 import compose_seven_source_kraken_registry
from bot.kraken_six_source_binding_contract_v490 import validate_six_source_bindings


def compose_reviewed_thirteen_source_registry(
    *,
    broker_providers: Mapping[str, Callable[[], Mapping[str, Any]]],
    protective_exit_provider: Callable[[], Mapping[str, Any]],
    writer_nonce_providers: Mapping[str, Callable[[], Mapping[str, Any]]],
    independent_providers: Mapping[str, Callable[[], Mapping[str, Any]]],
    reviewed_source_owners: Mapping[str, str],
    trusted_provider_ids: Mapping[str, str],
    independently_reviewed: bool = False,
):
    """Compose only reviewed complete registries; never invoke evidence sources."""
    six = validate_six_source_bindings(
        independent_providers,
        reviewed_source_owners=reviewed_source_owners,
        independently_reviewed=independently_reviewed,
    )
    return compose_seven_source_kraken_registry(
        broker_providers=broker_providers,
        protective_exit_provider=protective_exit_provider,
        writer_nonce_providers=writer_nonce_providers,
        independent_providers=six,
        trusted_provider_ids=trusted_provider_ids,
        independently_reviewed=independently_reviewed,
    )
