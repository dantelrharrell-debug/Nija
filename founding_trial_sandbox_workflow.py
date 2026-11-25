"""TEST-only composition of the existing Founding 100 trial and billing gates.

This module returns a non-executable sandbox rehearsal record. It has no Stripe
or Kraken client, no HTTP route, and no transport, recurring billing, entitlement
or deployment side effects. It is not a checkout or billing dispatcher.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol

from founding_trial_billing_gate import (
    FOUNDING_MONTHLY_USD,
    EnrollmentConsent,
    SandboxReadiness,
    TrialNotice,
    evaluate_sandbox_billing_candidate,
)
from founding_trial_evidence import (
    BrokerExecutionReader,
    MemberAccountReader,
    verify_and_record_first_fill,
)
from founding_trial_ledger import FoundingTrialLedger, TrialRecord, _identifier

FOUNDING_STRIPE_SANDBOX_ACCOUNT = "acct_1Tzy1CRS5Ezp77RQ"


@dataclass(frozen=True)
class TrustedBillingEvidence:
    consent: EnrollmentConsent | None
    notice: TrialNotice | None
    legal_approval: bool
    cancellation_operational: bool


class TrustedBillingEvidenceReader(Protocol):
    def evidence_for(self, member_id: str) -> TrustedBillingEvidence | None: ...


@dataclass(frozen=True)
class SandboxBillingRehearsal:
    """A local evidence record, deliberately not a payment API payload."""

    sandbox_account_id: str
    amount_usd_cents: int
    first_charge_at: datetime
    replay_fingerprint: str


@dataclass(frozen=True)
class SandboxWorkflowResult:
    readiness: SandboxReadiness
    rehearsal: SandboxBillingRehearsal | None = None


class FoundingTrialSandboxWorkflow:
    """Compose trusted backend readers and an isolated ledger without network I/O.

    Callers must provide local fixtures or verified backend adapters and the
    trusted clock. Do not bind request data to readers, clocks or billing
    evidence. Do not use this reference ledger or rehearsal as live authority.
    """

    def __init__(
        self,
        *,
        ledger: FoundingTrialLedger,
        executions: BrokerExecutionReader,
        accounts: MemberAccountReader,
        billing_evidence: TrustedBillingEvidenceReader,
        clock: Callable[[], datetime],
        stripe_account: str,
        livemode: bool,
    ):
        if livemode is not False or stripe_account != FOUNDING_STRIPE_SANDBOX_ACCOUNT:
            raise ValueError("the configured NIJA Stripe sandbox account is required")
        self._ledger = ledger
        self._executions = executions
        self._accounts = accounts
        self._evidence = billing_evidence
        self._clock = clock

    def record_verified_fill(
        self, *, member_id: str, execution_id: str, brokerage_account_id: str,
    ) -> TrialRecord:
        return verify_and_record_first_fill(
            self._ledger,
            member_id=member_id,
            execution_id=execution_id,
            brokerage_account_id=brokerage_account_id,
            executions=self._executions,
            accounts=self._accounts,
            now=self._clock(),
        )

    def evaluate(self, member_id: str) -> SandboxWorkflowResult:
        """Read the latest trial and prepare a rehearsal only at the approved time."""

        member_id = _identifier(member_id, "member_id")
        try:
            evidence = self._evidence.evidence_for(member_id)
            # Fetch after the external evidence reader, not from the fill result
            # or earlier evaluation. Subsequent dispatch is explicitly out of scope.
            trial = self._ledger.get(member_id)
            now = self._clock()
            if not isinstance(evidence, TrustedBillingEvidence):
                return SandboxWorkflowResult(SandboxReadiness("not_ready", ("billing_evidence_unavailable",)))
            consent = evidence.consent
            notice = evidence.notice
            if consent is not None and (
                not isinstance(consent, EnrollmentConsent)
                or consent.recurring_charge_accepted is not True
            ):
                consent = None
            if notice is not None and not isinstance(notice, TrialNotice):
                notice = None
            decision = evaluate_sandbox_billing_candidate(
                trial=trial,
                consent=consent,
                notice=notice,
                now=now,
                legal_approval=evidence.legal_approval is True,
                cancellation_operational=evidence.cancellation_operational is True,
            )
        except (AttributeError, TypeError, ValueError):
            return SandboxWorkflowResult(SandboxReadiness("not_ready", ("billing_evidence_invalid",)))
        except Exception:
            return SandboxWorkflowResult(SandboxReadiness("not_ready", ("billing_evidence_unavailable",)))
        if not decision.ready:
            return SandboxWorkflowResult(decision)

        first_charge_at = datetime.fromisoformat(trial.ends_at).astimezone(timezone.utc)
        if now.astimezone(timezone.utc) != first_charge_at:
            return SandboxWorkflowResult(SandboxReadiness("not_ready", ("scheduled_test_charge_time_missed",)))
        replay_fingerprint = hashlib.sha256(
            json.dumps(
                ["founding100-sandbox-v1", FOUNDING_STRIPE_SANDBOX_ACCOUNT,
                 member_id, trial.execution_id, first_charge_at.isoformat()],
                separators=(",", ":"),
            ).encode(),
        ).hexdigest()
        return SandboxWorkflowResult(
            decision,
            SandboxBillingRehearsal(
                sandbox_account_id=FOUNDING_STRIPE_SANDBOX_ACCOUNT,
                amount_usd_cents=int(FOUNDING_MONTHLY_USD * 100),
                first_charge_at=first_charge_at,
                replay_fingerprint=replay_fingerprint,
            ),
        )
