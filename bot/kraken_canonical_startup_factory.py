"""Assemble the existing collector against canonical objects; never discover trust.

The protected final Python root supplies actual independently reviewed source
objects and signed receipts. No broker/client, risk snapshot, inventory, receipt
or approval is created here. Registration itself never authorizes an order.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import time
from types import MappingProxyType
from typing import Any

from bot.kraken_reviewed_collector_bridge import compose_authenticated_kraken_collector_sources
from bot.kraken_six_source_binding_contract_v490 import validate_six_source_bindings
from bot.kraken_startup_evidence_binding import RECEIPTS, ReviewedStartupBinding
from bot.kraken_startup_receipts import StartupReceiptTrust, register_signed_kraken_startup


class CanonicalKrakenStartupDenied(ValueError):
    """Fixed non-sensitive denial; never expose source objects or exceptions."""


@dataclass(frozen=True, eq=False)
class ReviewedCanonicalKrakenSources:
    """Exact live owners supplied by the separately reviewed protected root.

    Resolver and review callbacks are trust boundaries. They must authenticate
    the actual object/source binding, not return synthetic readiness or infer
    review from these structural fields. Receipts are immutable signed JSON.
    """

    manager: Any = field(repr=False)
    strategy: Any = field(repr=False)
    broker: Any = field(repr=False)
    independent_open_intents: Callable = field(repr=False)
    independent_positions: Callable = field(repr=False)
    independent_remaining: Mapping[str, Callable] = field(repr=False)
    reviewed_source_owners: Mapping[str, str] = field(repr=False)
    monitoring_category: Any = field(repr=False)
    receipts: Mapping[str, str] = field(repr=False)

    def __post_init__(self) -> None:
        for name in ("independent_remaining", "reviewed_source_owners", "receipts"):
            value = getattr(self, name)
            if not isinstance(value, Mapping):
                raise CanonicalKrakenStartupDenied("reviewed_source_maps_required")
            object.__setattr__(self, name, MappingProxyType(dict(value)))
        if (set(self.receipts) != RECEIPTS
                or any(type(value) is not str or not value for value in self.receipts.values())
                or not callable(self.independent_open_intents)
                or not callable(self.independent_positions)
                or self.monitoring_category is None):
            raise CanonicalKrakenStartupDenied("complete_live_sources_and_receipts_required")


def _canonical_broker(manager: Any) -> Any:
    from bot.broker_manager import KrakenBroker
    from bot.kraken_authenticated_account_identity_v478 import _broker_account_scope

    brokers = getattr(manager, "platform_brokers", None)
    if callable(brokers):
        brokers = brokers()
    if not isinstance(brokers, Mapping):
        raise CanonicalKrakenStartupDenied("canonical_kraken_broker_required")
    matches = [broker for key, broker in brokers.items() if getattr(key, "value", key) == "kraken"]
    if (len(matches) != 1 or type(matches[0]) is not KrakenBroker
            or getattr(matches[0], "connected", False) is not True
            or not callable(getattr(matches[0], "_kraken_private_call", None))
            or _broker_account_scope(matches[0]) != "platform:kraken"):
        raise CanonicalKrakenStartupDenied("canonical_kraken_broker_required")
    return matches[0]


def make_canonical_kraken_startup_factory(
    *, trust: StartupReceiptTrust, resolve_sources: Callable, review_sources: Callable,
) -> Callable[..., ReviewedStartupBinding]:
    """Build all thirteen providers using the exact manager/strategy broker.

    The resolver receives canonical manager, strategy and broker objects only
    when the existing bot_main hook invokes the factory. Built-in provider
    construction performs no broker read. Resolution/review must themselves be
    separately audited. Original source freshness and provenance checks remain
    in the existing provider implementations and atomic installer.
    """
    if (type(trust) is not StartupReceiptTrust or not callable(resolve_sources)
            or not callable(review_sources)):
        raise CanonicalKrakenStartupDenied("reviewed_runtime_resolver_required")

    def factory(*, manager: Any, strategy: Any) -> ReviewedStartupBinding:
        try:
            if manager is None or strategy is None:
                raise CanonicalKrakenStartupDenied("canonical_runtime_objects_required")
            broker = _canonical_broker(manager)
            sources = resolve_sources(manager=manager, strategy=strategy, broker=broker)
            if (type(sources) is not ReviewedCanonicalKrakenSources
                    or sources.manager is not manager or sources.strategy is not strategy
                    or sources.broker is not broker or review_sources(sources) is not True):
                raise CanonicalKrakenStartupDenied("reviewed_runtime_source_binding_required")
            remaining = validate_six_source_bindings(
                sources.independent_remaining,
                reviewed_source_owners=sources.reviewed_source_owners,
                independently_reviewed=True,
            )
            providers = compose_authenticated_kraken_collector_sources(
                broker=broker, approved_api_key_sha256=trust.api_key_sha256,
                approved_iban_sha256=trust.account_iiban_sha256,
                reviewed_provider_ids=trust.reviewed_provider_ids,
                independent_open_intents=sources.independent_open_intents,
                independent_positions=sources.independent_positions,
                independent_remaining=remaining,
                reviewed_source_owners=sources.reviewed_source_owners,
                monitoring_category=sources.monitoring_category, independently_reviewed=True,
            )
            if review_sources(sources) is not True or _canonical_broker(manager) is not broker:
                raise CanonicalKrakenStartupDenied("runtime_source_binding_changed")
            return ReviewedStartupBinding(
                manager, strategy, broker, providers, trust.reviewed_provider_ids, sources.receipts,
            )
        except Exception:
            # A resolver/provider constructor can carry secrets in its error.
            raise CanonicalKrakenStartupDenied("canonical_startup_source_binding_denied") from None

    return factory


def register_canonical_kraken_collector_startup(
    *, trust: StartupReceiptTrust, resolve_sources: Callable, review_sources: Callable,
    clock: Callable[[], float] = time.time,
) -> None:
    """Explicit final-interpreter registration with the authenticated verifier.

    Does not read sources, install the collector or enable orders. Call from the
    approved protected composition root in the same interpreter as bot_main;
    registration before the outer bootstrap's exec handoff cannot survive.
    """
    factory = make_canonical_kraken_startup_factory(
        trust=trust, resolve_sources=resolve_sources, review_sources=review_sources,
    )
    register_signed_kraken_startup(factory, trust, clock=clock)
