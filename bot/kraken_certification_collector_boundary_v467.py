"""Read-only Kraken certification collector boundary.

The caller supplies independently authenticated, account-scoped readbacks.
This adapter never makes orders, claims verification, or grants authority.
All missing or inconsistent evidence fails closed.
"""
from __future__ import annotations

import math
import time
from collections.abc import Mapping
from typing import Any

from bot.pretrade_independent_attestation import FIELDS, install_authenticated_collector
from bot.pretrade_composition_bridge_v465 import make_collector

PROVENANCE = (
    "authenticated_broker_read_verified",
    "ledger_snapshot_verified",
    "complete_pagination_verified",
    "collector_identity_verified",
    "account_scope_verified",
)


def build_kraken_certification_collector(readback):
    """Bind a separately audited read-only producer; never self-certify."""
    if not callable(readback):
        raise TypeError("authenticated_readback_required")

    def collect(account: str) -> dict[str, Any]:
        if not isinstance(account, str) or not account or account != account.strip() or any(c.isspace() for c in account):
            raise ValueError("invalid_account_scope")
        raw = readback(account)
        if not isinstance(raw, Mapping):
            raise ValueError("invalid_authenticated_readback")
        if raw.get("account") != account or raw.get("source") != "authenticated_independent":
            raise ValueError("account_or_provenance_mismatch")
        if raw.get("read_only") is not True or raw.get("scope_verified") is not True:
            raise ValueError("readback_unverified")
        provenance = raw.get("provenance")
        if not isinstance(provenance, Mapping) or not all(provenance.get(k) is True for k in PROVENANCE):
            raise ValueError("provenance_incomplete")
        checks = raw.get("checks")
        if not isinstance(checks, Mapping) or not all(checks.get(k) is True for k in FIELDS):
            raise ValueError("certification_checks_incomplete")
        stamp = raw.get("observed_at_epoch")
        now = time.time()
        if isinstance(stamp, bool) or not isinstance(stamp, (int, float)) or not math.isfinite(stamp) or not 0 <= now - stamp <= 60:
            raise ValueError("certification_observation_stale")
        return {
            "account": account, "source": "authenticated_independent",
            "read_only": True, "scope_verified": True,
            "observed_at_epoch": stamp,
            "provenance": {k: True for k in PROVENANCE},
            "checks": {k: True for k in FIELDS},
        }

    return collect


def install_kraken_certification_collector(readback) -> None:
    """Explicit installation; does not authorize orders or hook dispatch."""
    install_authenticated_collector(build_kraken_certification_collector(readback))


def build_audited_kraken_collector(providers_by_account, *, trusted_provider_ids):
    """Use v465 validated independent producers, never self-reported booleans.

    A complete, independently audited provider registry must exist first.
    This function does not install the collector or authorize execution.
    """
    independent = make_collector(providers_by_account, trusted_provider_ids=trusted_provider_ids)
    return build_kraken_certification_collector(independent)
