"""Fail-closed evidence gate for the *isolated* Founding 100 trial prototype.

The readers must be trusted internal services that independently fetch brokerage
records and account ownership. Neither HTTP request data nor client-supplied
'verified' flags may implement these readers. No Stripe calls or charges occur.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Protocol

from founding_trial_ledger import FoundingTrialLedger, TrialRecord, _identifier


class UnverifiedFill(ValueError):
    """A first-trade claim is not supported by authoritative evidence."""


@dataclass(frozen=True)
class BrokerExecution:
    execution_id: str
    brokerage_account_id: str
    environment: str
    status: str
    filled_quantity: str
    executed_at: datetime


class BrokerExecutionReader(Protocol):
    def retrieve_execution(self, execution_id: str) -> BrokerExecution | None: ...


class MemberAccountReader(Protocol):
    def owner_of(self, brokerage_account_id: str) -> str | None: ...


def verify_and_record_first_fill(
    ledger: FoundingTrialLedger,
    *,
    member_id: str,
    execution_id: str,
    brokerage_account_id: str,
    executions: BrokerExecutionReader,
    accounts: MemberAccountReader,
    now: datetime,
) -> TrialRecord:
    """Independently retrieve and validate evidence before writing trial state.

    This is a test-only adapter contract, not a live broker connector. Callers
    must supply independently authenticated readers from a trusted backend.
    The ledger must not be called directly by untrusted API requests.
    Consent, eligibility, customer notices, legal approvals, and Stripe start
    remain additional release gates. Duplicate or late fills never reset state.
    """
    member_id = _identifier(member_id, 'member_id')
    execution_id = _identifier(execution_id, 'execution_id')
    brokerage_account_id = _identifier(brokerage_account_id, 'brokerage_account_id')
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise UnverifiedFill('trusted current time is missing or naive')
    if not callable(getattr(executions, 'retrieve_execution', None)) or not callable(getattr(accounts, 'owner_of', None)):
        raise UnverifiedFill('trusted evidence readers are required')
    try:
        owner = accounts.owner_of(brokerage_account_id)
        evidence = executions.retrieve_execution(execution_id)
    except Exception as exc:
        raise UnverifiedFill('broker evidence unavailable') from exc
    if owner != member_id:
        raise UnverifiedFill('brokerage account ownership not established')
    if not isinstance(evidence, BrokerExecution):
        raise UnverifiedFill('broker execution not established')
    if evidence.execution_id != execution_id or evidence.brokerage_account_id != brokerage_account_id:
        raise UnverifiedFill('execution identity mismatch')
    if evidence.environment != 'live' or evidence.status != 'filled':
        raise UnverifiedFill('no confirmed live execution')
    try:
        quantity = Decimal(evidence.filled_quantity)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise UnverifiedFill('invalid executed quantity') from exc
    if not quantity.is_finite() or quantity <= 0:
        raise UnverifiedFill('executed quantity must be positive')
    if not isinstance(evidence.executed_at, datetime) or evidence.executed_at.tzinfo is None or evidence.executed_at.utcoffset() is None:
        raise UnverifiedFill('execution timestamp missing or naive')
    execution_time = evidence.executed_at.astimezone(timezone.utc)
    observed_at = now.astimezone(timezone.utc)
    if execution_time > observed_at:
        raise UnverifiedFill('future-dated execution rejected')
    return ledger.record_fill(member_id, execution_id, execution_time)
