"""Fail-closed installation boundary for independently audited pretrade providers.

This is a composition-root helper, not an auto-discovery or trading-admission
hook. A production owner must explicitly supply vetted provider callables and
identity bindings from the existing nonce-owning authenticated runtime.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from bot.pretrade_attestation_validation_v452 import REQUIRED
from bot.pretrade_composition_bridge_v465 import install_audited_collector


def register_reviewed_pretrade_providers(
    *,
    account_scope: str,
    providers: Mapping[str, Callable[[], Mapping[str, Any]]],
    trusted_provider_ids: Mapping[str, str],
    independently_reviewed: bool = False,
) -> None:
    """Install diagnostic collector only after explicit independent review.

    Installation cannot grant execution authority. Never construct a provider
    from environment readiness booleans, historical fills or synthetic data.
    """
    if independently_reviewed is not True:
        raise PermissionError("independent_provider_review_required")
    if not isinstance(account_scope, str) or not account_scope:
        raise ValueError("explicit_account_scope_required")
    if not isinstance(providers, Mapping) or set(providers) != set(REQUIRED):
        raise ValueError("complete_provider_registry_required")
    if not all(callable(providers[key]) for key in REQUIRED):
        raise ValueError("callable_provider_required")
    if not isinstance(trusted_provider_ids, Mapping) or set(trusted_provider_ids) != set(REQUIRED):
        raise ValueError("complete_trusted_provider_registry_required")
    install_audited_collector(
        {account_scope: dict(providers)},
        trusted_provider_ids=trusted_provider_ids,
    )
