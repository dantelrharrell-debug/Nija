"""Explicit integration of independently reviewed Kraken source bindings.

This bridge composes existing production provider factories. It does not
install a collector, read the exchange, mutate state, or authorize orders.
The trusted runtime must provide the canonical broker and audited sources.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from bot.kraken_collector_composition_v487 import compose_reviewed_kraken_providers
from bot.kraken_six_source_binding_contract_v490 import (
    validate_six_source_bindings,
)
from bot.pretrade_attestation_validation_v452 import REQUIRED


class ReviewedCollectorCompositionDenied(PermissionError):
    """Fixed reason code; never include secrets or broker responses."""


def compose_authenticated_kraken_collector_sources(
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
    identity_method: str = "response_echo",
) -> Mapping[str, Callable[[], Mapping[str, Any]]]:
    """Compose, but never register, all thirteen account-scoped sources.

    This form requires all six independent sources; optional kill-switch and
    position-sync factory construction stays in the existing v487 interface.
    Independent review must verify source provenance outside this function.
    """
    if independently_reviewed is not True:
        raise ReviewedCollectorCompositionDenied("independent_review_required")
    # A duck-typed private-call method is insufficient: the reviewed collector
    # must share the exact native Kraken broker used by the nonce owner.
    from bot.broker_manager import KrakenBroker
    from bot.kraken_authenticated_account_identity_v478 import _broker_account_scope
    if type(broker) is not KrakenBroker or not callable(getattr(broker, "_kraken_private_call", None)):
        raise ReviewedCollectorCompositionDenied("canonical_broker_required")
    try:
        scope = _broker_account_scope(broker)
    except (AttributeError, ValueError, TypeError):
        raise ReviewedCollectorCompositionDenied("canonical_broker_scope_required") from None
    if scope != "platform:kraken":
        raise ReviewedCollectorCompositionDenied("canonical_broker_scope_required")
    if (not isinstance(approved_api_key_sha256, str)
            or len(approved_api_key_sha256) != 64
            or any(c not in "0123456789abcdef" for c in approved_api_key_sha256)
            or not isinstance(approved_iban_sha256, str)
            or len(approved_iban_sha256) != 64
            or any(c not in "0123456789abcdef" for c in approved_iban_sha256)):
        raise ReviewedCollectorCompositionDenied("approved_identity_pins_required")
    sources = validate_six_source_bindings(
        independent_remaining,
        reviewed_source_owners=reviewed_source_owners,
        independently_reviewed=True,
    )
    providers = compose_reviewed_kraken_providers(
        broker=broker,
        approved_api_key_sha256=approved_api_key_sha256,
        approved_iban_sha256=approved_iban_sha256,
        reviewed_provider_ids=reviewed_provider_ids,
        independent_open_intents=independent_open_intents,
        independent_positions=independent_positions,
        independent_remaining=sources,
        monitoring_category=monitoring_category,
        independently_reviewed=True, identity_method=identity_method,
    )
    if (not isinstance(providers, Mapping)
            or set(providers) != set(REQUIRED)
            or any(not callable(provider) for provider in providers.values())
            or len({id(provider) for provider in providers.values()}) != len(REQUIRED)):
        raise ReviewedCollectorCompositionDenied("incomplete_authenticated_sources")
    return providers
