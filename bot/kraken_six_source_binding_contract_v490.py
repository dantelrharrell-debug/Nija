"""Fail-closed boundary for the six missing independent Kraken sources.

This module is deliberately non-authorizing. It never constructs providers,
reads credentials, imports live broker modules, or changes runtime state.
The trusted production composition root must supply independently reviewed
callables bound to actual ledger, writer, operator, risk and broker interfaces.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from bot.kraken_seven_source_registry_v489 import REMAINING_FIELDS
from bot.pretrade_attestation_validation_v452 import SOURCES

EXPECTED_OWNERS = {
    "position_ledger_reconciliation": "independent_ledger",
    "duplicate_order_fence": "writer_authority",
    "operator_authorization": "operator_authority",
    "kill_switch_clear": "risk_governor",
    "risk_limits": "risk_governor",
    "position_sync": "authenticated_broker",
}


class IndependentSourceBindingRequired(PermissionError):
    pass


def validate_six_source_bindings(
    providers: Mapping[str, Callable[[], Mapping[str, Any]]],
    *,
    reviewed_source_owners: Mapping[str, str],
    independently_reviewed: bool = False,
) -> dict[str, Callable[[], Mapping[str, Any]]]:
    """Return a copy of complete bindings, without calling any provider.

    Owner strings are an additional structural guard, not proof of independent
    approval or authenticated observations. Production registration must still
    use the v452 evidence validator and v474 reviewed registration boundary.
    """
    if independently_reviewed is not True:
        raise IndependentSourceBindingRequired("independent_review_required")
    if set(EXPECTED_OWNERS) != set(REMAINING_FIELDS):
        raise IndependentSourceBindingRequired("source_contract_changed")
    if not isinstance(providers, Mapping) or set(providers) != set(EXPECTED_OWNERS):
        raise IndependentSourceBindingRequired("six_sources_required")
    if not isinstance(reviewed_source_owners, Mapping):
        raise IndependentSourceBindingRequired("reviewed_owner_map_required")
    if set(reviewed_source_owners) != set(EXPECTED_OWNERS):
        raise IndependentSourceBindingRequired("complete_owner_map_required")
    for field, owner in EXPECTED_OWNERS.items():
        if SOURCES[field] != owner or reviewed_source_owners[field] != owner:
            raise IndependentSourceBindingRequired("source_owner_mismatch")
        if not callable(providers[field]):
            raise IndependentSourceBindingRequired("source_not_callable")
    return dict(providers)
