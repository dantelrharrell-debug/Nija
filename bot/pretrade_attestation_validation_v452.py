"""Fail-closed validation for *independently sourced* pre-trade observations.

This module is a non-authorizing reviewer of evidence from the trusted
application composition root. It never reads broker credentials, makes an
exchange request, or changes live order admission. A self-reported verified
boolean or an untrusted provider name is not sufficient evidence.
"""
from __future__ import annotations

import math
import time
from collections.abc import Mapping
from typing import Any

REQUIRED = (
    "account_permissions", "account_identity", "broker_balances",
    "position_ledger_reconciliation", "protective_exit_readback",
    "open_order_reconciliation", "duplicate_order_fence",
    "writer_lease", "nonce_sequence", "operator_authorization",
    "kill_switch_clear", "risk_limits", "position_sync",
)

# A broker response may not certify its own ledger, writer lease, risk policy,
# or operator approval. Independent provider identities are bound out of band.
SOURCES = {
    "account_permissions": "authenticated_broker",
    "account_identity": "authenticated_broker",
    "broker_balances": "authenticated_broker",
    "position_ledger_reconciliation": "independent_ledger",
    "protective_exit_readback": "authenticated_broker",
    "open_order_reconciliation": "authenticated_broker",
    "duplicate_order_fence": "writer_authority",
    "writer_lease": "writer_authority",
    "nonce_sequence": "writer_authority",
    "operator_authorization": "operator_authority",
    "kill_switch_clear": "risk_governor",
    "risk_limits": "risk_governor",
    "position_sync": "authenticated_broker",
}

PROOF_BY_SOURCE = {
    "authenticated_broker": "authenticated_broker_read_verified",
    "independent_ledger": "ledger_snapshot_verified",
    "writer_authority": "writer_fencing_verified",
    "operator_authority": "operator_approval_verified",
    "risk_governor": "risk_state_verified",
}

_MAX_AGE_S = 60.0


def _denied() -> dict[str, Any]:
    return {
        "certified": False,
        "missing": list(REQUIRED),
        "authorizes_orders": False,
        "execution_proof_required_for_this_certificate": False,
        "post_trade_confirmation_required": True,
        "account_bound": False,
    }


def _valid_identifier(value: Any) -> bool:
    return (
        isinstance(value, str) and bool(value)
        and value == value.strip()
        and not any(char.isspace() for char in value)
    )


def evaluate_pretrade_certificate(
    observations: Mapping[str, Any],
    *,
    account: str | None = None,
    trusted_provider_ids: Mapping[str, str] | None = None,
    now_epoch: float | None = None,
    max_age_s: float = _MAX_AGE_S,
) -> dict[str, Any]:
    """Require authenticated account and trusted, independently bound sources.

    The trusted provider-ID registry MUST be supplied by an audited composition
    root, never copied from the observation itself. The maximum allowed age
    cannot be widened by a caller. A passing result remains diagnostic only.
    """
    denied = _denied()
    if not _valid_identifier(account):
        return denied
    if not isinstance(observations, Mapping):
        return denied
    if not isinstance(trusted_provider_ids, Mapping):
        return denied

    if isinstance(now_epoch, bool) or (
        now_epoch is not None and not isinstance(now_epoch, (int, float))
    ):
        return denied
    now = time.time() if now_epoch is None else float(now_epoch)
    if isinstance(max_age_s, bool) or not isinstance(max_age_s, (int, float)):
        return denied
    if (not math.isfinite(now) or not math.isfinite(max_age_s)
            or not 0 < max_age_s <= _MAX_AGE_S):
        return denied

    # A single producer is not independent merely because it changes the
    # source field in its own observation.
    producer_sources: dict[str, str] = {}
    seen_provider_ids: set[str] = set()
    for field in REQUIRED:
        identity = trusted_provider_ids.get(field)
        if not _valid_identifier(identity):
            return denied
        source = SOURCES[field]
        previous = producer_sources.setdefault(identity, source)
        if previous != source:
            return denied
        if identity in seen_provider_ids:
            return denied
        seen_provider_ids.add(identity)

    missing: list[str] = []
    evidence_fields: dict[str, list[str]] = {}
    for field in REQUIRED:
        row = observations.get(field)
        if not isinstance(row, Mapping):
            missing.append(field)
            continue
        evidence_id = row.get("evidence_id")
        if _valid_identifier(evidence_id):
            evidence_fields.setdefault(evidence_id, []).append(field)
        source = SOURCES[field]
        provenance = row.get("provenance")
        if (row.get("account") != account
                or row.get("verified") is not True
                or row.get("read_only") is not True
                or row.get("scope_verified") is not True
                or row.get("source") != source
                or row.get("provider_id") != trusted_provider_ids[field]
                or not _valid_identifier(evidence_id)
                or not isinstance(provenance, Mapping)
                or provenance.get("account_scope_verified") is not True
                or provenance.get("collector_identity_verified") is not True
                or provenance.get("snapshot_complete") is not True
                or provenance.get(PROOF_BY_SOURCE[source]) is not True):
            missing.append(field)
            continue
        if source in {"authenticated_broker", "independent_ledger"}:
            if provenance.get("complete_pagination_verified") is not True:
                missing.append(field)
                continue
        stamp = row.get("observed_at_epoch")
        if (isinstance(stamp, bool) or not isinstance(stamp, (int, float))
                or not math.isfinite(stamp) or stamp <= 0):
            missing.append(field)
            continue
        age_s = now - stamp
        if age_s < 0 or age_s > max_age_s:
            missing.append(field)

    for fields in evidence_fields.values():
        if len(fields) > 1:
            missing.extend(fields)
    missing = list(dict.fromkeys(missing))

    return {
        "certified": not missing,
        "missing": missing,
        "authorizes_orders": False,
        "execution_proof_required_for_this_certificate": False,
        "post_trade_confirmation_required": True,
        "account_bound": True,
    }
