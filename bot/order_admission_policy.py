"""Candidate-specific admission contract, separate from historical fill evidence.

This module is deliberately not an authority producer or broker transport.
Trusted runtime collectors must supply independently verified current facts.
An eligible result is only an input to canonical dispatch; it cannot replace
the writer fence, nonce owner, kill switch, or broker-side checks at dispatch.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping


CURRENT_FACT_TTL_S = 30.0
EXECUTION_EVIDENCE_TTL_S = 1800.0
REQUIRED_CONTROLS = (
    "authenticated_account", "trade_permissions", "writer_lease", "nonce_owner",
    "balances_and_holds", "positions_and_open_orders", "ledger_reconciliation",
    "startup_attempt_reconciliation", "protective_exits", "kill_switch_clear",
    "circuit_breaker_clear", "strategy_signal", "risk_and_sizing",
    "market_data", "venue_minimums", "pipeline_ready",
)
ORDER_STATES = frozenset({"none", "verified", "pending", "unknown", "failed"})


@dataclass(frozen=True)
class Candidate:
    """Immutable canonical strategy intent identity, including all order terms."""

    account: str
    credential_fingerprint: str
    writer_generation: int
    intent_digest: str


@dataclass(frozen=True)
class CurrentFact:
    """Verified fact bound to the exact candidate and current writer epoch.

    Construction alone is not proof. Only audited runtime collectors may
    construct facts in a future integration; caller/JSON booleans are not a
    substitute for those collectors.
    """

    candidate: Candidate
    verified: bool
    observed_at: float
    producer: str


@dataclass(frozen=True)
class OrderOutcome:
    """Latest durable intent outcome; absence of history is an explicit state."""

    account: str
    state: str
    broker_event_at: float | None = None
    verified_at: float | None = None
    broker_order_id: str = ""
    canonical_fill_verified: bool = False
    ledger_reconciled: bool = False


@dataclass(frozen=True)
class AdmissionDecision:
    """Policy eligibility and separate fill-evidence status; never authority."""

    eligible_for_canonical_dispatch: bool
    execution_evidence_fresh: bool
    reasons: tuple[str, ...]


def _finite_number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _fresh(observed_at: object, now: float, ttl: float) -> bool:
    return _finite_number(observed_at) and 0 < observed_at <= now and now - observed_at <= ttl


def evaluate_candidate(
    candidate: Candidate,
    facts: Mapping[str, CurrentFact],
    outcome: OrderOutcome,
    *,
    now: float,
) -> AdmissionDecision:
    """Evaluate startup/idle candidates without requiring an unrelated fill.

    Pending, ambiguous, failed or unreconciled real orders block new entries.
    Expiry of a reconciled historical fill only changes evidence status; it
    does not expire a fresh operational check. Missing data never passes.
    No result starts a worker, changes readiness, writes a marker or submits.
    """
    reasons: list[str] = []
    if not _finite_number(now) or now <= 0:
        return AdmissionDecision(False, False, ("clock_invalid",))
    if (
        type(candidate) is not Candidate
        or not isinstance(candidate.account, str) or not candidate.account.strip()
        or not isinstance(candidate.credential_fingerprint, str)
        or not candidate.credential_fingerprint.strip()
        or type(candidate.writer_generation) is not int or candidate.writer_generation <= 0
        or not isinstance(candidate.intent_digest, str) or len(candidate.intent_digest) != 64
        or any(char not in "0123456789abcdef" for char in candidate.intent_digest)
    ):
        return AdmissionDecision(False, False, ("candidate_identity_invalid",))
    if not isinstance(facts, Mapping):
        return AdmissionDecision(False, False, ("current_facts_unavailable",))
    for control in REQUIRED_CONTROLS:
        fact = facts.get(control)
        if type(fact) is not CurrentFact:
            reasons.append(f"{control}:missing")
        elif type(fact.candidate) is not Candidate or fact.candidate != candidate:
            reasons.append(f"{control}:identity_mismatch")
        elif fact.verified is not True:
            reasons.append(f"{control}:unverified")
        elif not isinstance(fact.producer, str) or not fact.producer.strip():
            reasons.append(f"{control}:producer_missing")
        elif not _fresh(fact.observed_at, now, CURRENT_FACT_TTL_S):
            reasons.append(f"{control}:stale_or_invalid")
    evidence_fresh = False
    if type(outcome) is not OrderOutcome or outcome.account != candidate.account:
        reasons.append("order_outcome:missing_or_wrong_account")
    elif not isinstance(outcome.state, str) or outcome.state not in ORDER_STATES:
        reasons.append("order_outcome:invalid_state")
    elif outcome.state in {"pending", "unknown", "failed"}:
        reasons.append(f"order_outcome:{outcome.state}")
    elif outcome.state == "none":
        if (outcome.broker_order_id or outcome.broker_event_at is not None
                or outcome.verified_at is not None or outcome.canonical_fill_verified is not False
                or outcome.ledger_reconciled is not False):
            reasons.append("order_outcome:contradictory_empty_history")
    elif (
        outcome.canonical_fill_verified is not True
        or outcome.ledger_reconciled is not True
        or not isinstance(outcome.broker_order_id, str) or not outcome.broker_order_id.strip()
        or not _finite_number(outcome.broker_event_at)
        or not _finite_number(outcome.verified_at)
        or not 0 < outcome.broker_event_at <= outcome.verified_at <= now
    ):
        reasons.append("order_outcome:unreconciled_or_invalid")
    else:
        evidence_fresh = (
            _fresh(outcome.broker_event_at, now, EXECUTION_EVIDENCE_TTL_S)
            and _fresh(outcome.verified_at, now, EXECUTION_EVIDENCE_TTL_S)
        )
    return AdmissionDecision(not reasons, evidence_fresh, tuple(reasons))
