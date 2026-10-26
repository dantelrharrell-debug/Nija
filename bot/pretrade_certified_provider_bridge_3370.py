"""Non-authorizing bridge from independently verified provider observations.

This module deliberately does not install itself, fetch broker data, or call
order admission. The trusted composition root must separately supply callable
providers and an out-of-band registry of their identities.
"""
from __future__ import annotations

import math
import time
from collections.abc import Callable, Mapping
from typing import Any

from bot.pretrade_authenticated_provider_adapter_v453 import (
    collect_independent_pretrade_evidence,
)
from bot.pretrade_attestation_validation_v452 import REQUIRED
from bot.pretrade_independent_attestation import FIELDS


def build_diagnostic_collector(
    providers: Mapping[str, Callable[[], Mapping[str, Any]]],
    trusted_provider_ids: Mapping[str, str],
    *,
    clock: Callable[[], float] = time.time,
) -> Callable[[str], dict[str, Any]]:
    """Build a collector only; callers must explicitly review/install it.

    A valid result does not grant order authority. Reject missing trust
    bindings or evidence, and never use an observation's self-declared
    provider identity as a trusted binding.
    """
    def collect(account: str) -> dict[str, Any]:
        # Evaluate freshness after all provider I/O completes. A timestamp
        # captured before a slow read can accept evidence already expired.
        report = collect_independent_pretrade_evidence(
            providers, account=account,
            trusted_provider_ids=trusted_provider_ids,
            now_epoch=None,
        )
        observed_at = clock()
        cert = report["certificate"]
        observations = report["observations"]
        missing = set(cert["missing"])
        checks = {field: field in REQUIRED and field not in missing
                  and cert.get("account_bound") is True
                  for field in FIELDS}
        # Independent checks outside FIELDS are still mandatory.
        all_valid = cert.get("certified") is True and not report["provider_errors"]
        # The outer attestation contract expects source-specific provenance.
        source_ids = {str(observations[field].get("provider_id"))
                      for field in REQUIRED if isinstance(observations.get(field), Mapping)}
        trusted_ids = {str(trusted_provider_ids.get(field)) for field in REQUIRED}
        provenance = {
            "authenticated_broker_read_verified": all_valid,
            "ledger_snapshot_verified": all_valid,
            "complete_pagination_verified": all_valid,
            "collector_identity_verified": all_valid and source_ids == trusted_ids,
            "account_scope_verified": all_valid,
        }
        if not all_valid:
            checks = {field: False for field in FIELDS}
        return {
            "account": account,
            "observed_at_epoch": observed_at,
            "source": "authenticated_independent" if all_valid else "unverified",
            "read_only": True,
            "scope_verified": all_valid,
            "provenance": provenance,
            "checks": checks,
            "authorizes_orders": False,
        }
    return collect
