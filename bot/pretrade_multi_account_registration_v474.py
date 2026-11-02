"""Atomic, fail-closed registration for multiple reviewed brokerage accounts.

This helper is deliberately NOT called at import/startup. The trusted trading
composition root must supply independently reviewed, authenticated producers.
Registration is diagnostic-only and never authorizes order submission.
"""
from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable, Mapping
from typing import Any

from bot.pretrade_attestation_validation_v452 import IndependentEvidenceRejected, REQUIRED, SOURCES
from bot.pretrade_composition_bridge_v465 import make_collector
from bot.pretrade_independent_attestation import install_authenticated_collector

logger = logging.getLogger(__name__)


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
    provider_ids = tuple(trusted_provider_ids[field] for field in REQUIRED)
    if any(not isinstance(value, str) or not value or value != value.strip()
           or any(char.isspace() for char in value) for value in provider_ids):
        raise ValueError("unique_complete_provider_registry_required")
    provider_sources: dict[str, str] = {}
    for field, identity in zip(REQUIRED, provider_ids):
        previous = provider_sources.setdefault(identity, SOURCES[field])
        if previous != SOURCES[field]:
            raise ValueError("cross_authority_provider_identity_reuse")
    if len(set(provider_ids)) != len(REQUIRED):
        raise ValueError("unique_complete_provider_registry_required")
    # Construct and fully validate before touching the process-wide collector.
    collector = make_collector(
        providers_by_account, trusted_provider_ids=trusted_provider_ids
    )
    for account in providers_by_account:
        try:
            result = collector(account)
        except IndependentEvidenceRejected as exc:
            logger.error(
                "PRETRADE_COLLECTOR_INSTALL_REJECTED failed_fields=%s collector_replaced=false",
                ",".join(exc.failed_fields),
            )
            raise
        if not isinstance(result, Mapping):
            raise ValueError("fresh_independent_attestations_required")
        checks = result.get("checks")
        provenance = result.get("provenance")
        stamp = result.get("observed_at_epoch")
        now = time.time()
        if (result.get("account") != account
                or result.get("source") != "authenticated_independent"
                or result.get("authorizes_orders") is not False
                or result.get("read_only") is not True
                or result.get("scope_verified") is not True
                or not isinstance(checks, Mapping)
                or set(checks) != set(REQUIRED)
                or any(checks[field] is not True for field in REQUIRED)
                or not isinstance(provenance, Mapping)
                or any(provenance.get(field) is not True for field in (
                    "authenticated_broker_read_verified",
                    "ledger_snapshot_verified",
                    "complete_pagination_verified",
                    "collector_identity_verified",
                    "account_scope_verified",
                ))
                or isinstance(stamp, bool)
                or not isinstance(stamp, (int, float))
                or not math.isfinite(stamp)
                or not 0 <= now - stamp <= 60):
            raise ValueError("fresh_independent_attestations_required")
    install_authenticated_collector(collector)
