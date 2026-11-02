"""Bridge fully validated, independent per-account pretrade evidence into v16.

This bridge supplies a missing *producer adapter*, not execution authority.
A trusted composition root must explicitly provide account-specific providers
and independently reviewed provider IDs. No environment flag, broker liveness,
old fill, synthetic proof, or user-supplied request may install or satisfy it.
It never makes an order, changes a ledger or connects itself to admission.
"""
from __future__ import annotations

import math
import time
from collections.abc import Callable, Mapping
from typing import Any

from bot.pretrade_attestation_validation_v452 import IndependentEvidenceRejected, REQUIRED, SOURCES
from bot.pretrade_authenticated_provider_adapter_v453 import collect_independent_pretrade_evidence
from bot.pretrade_independent_attestation import FIELDS, install_authenticated_collector


def _scope_ok(value: Any) -> bool:
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    if any(char.isspace() for char in value):
        return False
    parts = value.split(":")
    return (
        len(parts) == 2 and parts[0] == "platform"
        and parts[1] in {"kraken", "coinbase", "okx", "alpaca"}
    ) or (
        len(parts) == 3 and parts[0] == "user" and bool(parts[1])
        and parts[2] in {"kraken", "coinbase", "okx", "alpaca"}
    )


def make_collector(
    providers_by_account: Mapping[str, Mapping[str, Callable[[], Mapping[str, Any]]]],
    *, trusted_provider_ids: Mapping[str, str],
) -> Callable[[str], Mapping[str, Any]]:
    """Create a *non-authorizing* collector from prebound, trusted producers.

    Individual provider observations must satisfy the independently audited
    v452 provenance contract. A provider cannot certify another account; all
    13 distinct checks must be contemporaneous, with a vetted source registry.
    The missing source registry or any missing provider fails closed.
    """
    if not isinstance(providers_by_account, Mapping) or not providers_by_account:
        raise ValueError("audited_account_registry_required")
    if not isinstance(trusted_provider_ids, Mapping):
        raise ValueError("trusted_provider_registry_required")
    # Registry must bind every evidence field before the first read. A mapping
    # constructed from observations would not independently bind the producer.
    trusted = {field: trusted_provider_ids.get(field) for field in REQUIRED}
    if set(trusted_provider_ids) != set(REQUIRED) or any(
        not isinstance(value, str) or not value or value != value.strip()
        or any(c.isspace() for c in value) for value in trusted.values()
    ):
        raise ValueError("trusted_provider_registry_incomplete")
    # A provider ID may attest multiple *fields*, but not distinct authority
    # classes (broker, independent ledger, writer, operator, risk governor).
    roles: dict[str, str] = {}
    for field in REQUIRED:
        pid = trusted[field]
        role = SOURCES[field]
        old = roles.setdefault(pid, role)
        if old != role:
            raise ValueError("cross_authority_provider_identity_reuse")
    accounts: dict[str, dict[str, Callable[[], Mapping[str, Any]]]] = {}
    for account, providers in providers_by_account.items():
        if not _scope_ok(account) or not isinstance(providers, Mapping):
            raise ValueError("audited_account_scope_invalid")
        if set(providers) != set(REQUIRED) or any(
            not callable(providers[field]) for field in REQUIRED
        ):
            raise ValueError("audited_providers_incomplete")
        accounts[account] = {field: providers[field] for field in REQUIRED}

    def collect(account: str) -> Mapping[str, Any]:
        if not _scope_ok(account) or account not in accounts:
            raise ValueError("unregistered_account_scope")
        # Adapter asks the real producers for fresh evidence; v452 independently
        # checks account, source family, trusted provider ID, provenance and TTL.
        report = collect_independent_pretrade_evidence(
            accounts[account], account=account, trusted_provider_ids=trusted,
            now_epoch=None,  # validate after provider I/O, not before
        )
        result = report.get("certificate", {})
        observed = report.get("observations", {})
        if (not isinstance(result, Mapping)
                or result.get("certified") is not True
                or result.get("account_bound") is not True
                or result.get("authorizes_orders") is not False
                or not isinstance(observed, Mapping)
                or any(field not in observed for field in REQUIRED)
                or report.get("provider_errors")):
            missing = result.get("missing", REQUIRED) if isinstance(result, Mapping) else REQUIRED
            raise IndependentEvidenceRejected(missing)
        stamps = [observed[field].get("observed_at_epoch") for field in REQUIRED]
        if any(isinstance(t, bool) or not isinstance(t, (float, int))
               or not math.isfinite(t) for t in stamps):
            raise ValueError("independent_observation_clock_invalid")
        earliest = min(stamps)
        now = time.time()
        if earliest > now or now - earliest > 60:
            raise ValueError("independent_observation_stale")
        # These positive claims are *derived from accepted v452 inputs*, never
        # from a generic caller's true/ready switch. v16 still denies authority.
        return {
            "account": account,
            "source": "authenticated_independent",
            "observed_at_epoch": earliest,
            "read_only": True,
            "scope_verified": True,
            "provenance": {
                "authenticated_broker_read_verified": True,
                "ledger_snapshot_verified": True,
                "complete_pagination_verified": True,
                "collector_identity_verified": True,
                "account_scope_verified": True,
            },
            "checks": {field: observed[field].get("verified") is True for field in FIELDS},
            "authorizes_orders": False,
        }

    return collect


def install_audited_collector(
    providers_by_account: Mapping[str, Mapping[str, Callable[[], Mapping[str, Any]]]],
    *, trusted_provider_ids: Mapping[str, str],
) -> None:
    """Install only when the audited runtime supplies real, reviewed providers.

    Never called automatically. Installation does not change readiness, the
    kill switch, writer lease, trading state, or the activation controller.
    """
    install_authenticated_collector(make_collector(
        providers_by_account, trusted_provider_ids=trusted_provider_ids,
    ))


__all__ = ["make_collector", "install_audited_collector"]
