"""v487: opt-in, non-authorizing composition of five reviewed Kraken producers.

Adds the independently sourced protective-exit readback to the existing four
v483 producers. No collector installation, broker I/O at construction, or
trading admission occurs here. The other eight v452 fields remain required.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any

from bot.kraken_protective_exit_readback_v485 import make_kraken_protective_exit_provider
from bot.kraken_reviewed_producer_bundle_v483 import (
    FIELDS as BASE_FIELDS,
    KrakenCompositionDenied,
    _identifier,
    _reviewed_pin,
    make_reviewed_kraken_producer_bundle,
)
from bot.pretrade_attestation_validation_v452 import REQUIRED

FIELDS = BASE_FIELDS + ("protective_exit_readback",)
MISSING_FIELDS = tuple(field for field in REQUIRED if field not in FIELDS)


def make_reviewed_kraken_five_field_bundle(
    broker: Any, *,
    account_scope: str,
    approved_api_key_sha256: str,
    approved_iban_sha256: str,
    reviewed_provider_ids: Mapping[str, str],
    reviewed_ledger_provider_id: str,
    independent_open_intents: Callable[[], Mapping[str, Any]],
    independent_positions: Callable[[], Mapping[str, Any]],
    monitoring_category: Any,
    independently_reviewed: bool = False,
    clock: Callable[[], float] | None = None,
) -> Mapping[str, Callable[[], Mapping[str, Any]]]:
    """Return five distinct reviewed producers; fail closed on incomplete pins."""
    if independently_reviewed is not True:
        raise KrakenCompositionDenied("independent_review_required")
    if (account_scope != "platform:kraken"
            or not _reviewed_pin(approved_api_key_sha256)
            or not _reviewed_pin(approved_iban_sha256)
            or not isinstance(reviewed_provider_ids, Mapping)
            or set(reviewed_provider_ids) != set(FIELDS)
            or any(not _identifier(reviewed_provider_ids[field]) for field in FIELDS)
            or len(set(reviewed_provider_ids.values())) != len(FIELDS)
            or not _identifier(reviewed_ledger_provider_id)
            or reviewed_ledger_provider_id in set(reviewed_provider_ids.values())
            or not callable(independent_positions)):
        raise KrakenCompositionDenied("independent_five_field_registry_required")
    base = make_reviewed_kraken_producer_bundle(
        broker,
        account_scope=account_scope,
        approved_api_key_sha256=approved_api_key_sha256,
        approved_iban_sha256=approved_iban_sha256,
        reviewed_provider_ids={field: reviewed_provider_ids[field] for field in BASE_FIELDS},
        reviewed_ledger_provider_id=reviewed_ledger_provider_id,
        independent_open_intents=independent_open_intents,
        monitoring_category=monitoring_category,
        independently_reviewed=True,
        clock=clock,
    )
    kwargs = {}
    if clock is not None:
        kwargs["clock"] = clock
    try:
        protective = make_kraken_protective_exit_provider(
            broker,
            account_scope=account_scope,
            approved_api_key_sha256=approved_api_key_sha256,
            approved_iban_sha256=approved_iban_sha256,
            reviewed_provider_id=reviewed_provider_ids["protective_exit_readback"],
            reviewed_ledger_provider_id=reviewed_ledger_provider_id,
            independent_positions=independent_positions,
            monitoring_category=monitoring_category,
            **kwargs,
        )
    except Exception:
        raise KrakenCompositionDenied("protective_provider_construction_failed") from None
    return MappingProxyType({**base, "protective_exit_readback": protective})


__all__ = [
    "FIELDS", "MISSING_FIELDS", "make_reviewed_kraken_five_field_bundle",
]
