"""Atomic, fail-closed registration for multiple reviewed brokerage accounts.

This helper is deliberately NOT called at import/startup. The trusted trading
composition root must supply independently reviewed, authenticated producers.
Registration is diagnostic-only and never authorizes order submission.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from bot.pretrade_attestation_validation_v452 import REQUIRED
from bot.pretrade_composition_bridge_v465 import make_collector
from bot.pretrade_independent_attestation import install_authenticated_collector


def register_reviewed_account_registry(
    *,
    providers_by_account: Mapping[str, Mapping[str, Callable[[], Mapping[str, Any]]]],
    trusted_provider_ids: Mapping[str, str],
    independently_reviewed: bool = False,
) -> None:
    """Validate all account bindings before atomically installing one collector.

    Never use environment readiness booleans, placeholder callbacks or inferred
    producer IDs. v465 validates canonical account scopes and source separation.
    """
    if independently_reviewed is not True:
        raise PermissionError("independent_provider_review_required")
    if not isinstance(providers_by_account, Mapping) or not providers_by_account:
        raise ValueError("complete_account_registry_required")
    for account, providers in providers_by_account.items():
        if not isinstance(account, str) or not isinstance(providers, Mapping):
            raise ValueError("complete_account_registry_required")
        if set(providers) != set(REQUIRED) or not all(
            callable(providers[field]) for field in REQUIRED
        ):
            raise ValueError("complete_provider_registry_required")
    if not isinstance(trusted_provider_ids, Mapping) or set(trusted_provider_ids) != set(REQUIRED):
        raise ValueError("complete_trusted_provider_registry_required")
    # Construct and fully validate before touching the process-wide collector.
    collector = make_collector(
        providers_by_account, trusted_provider_ids=trusted_provider_ids
    )
    install_authenticated_collector(collector)
