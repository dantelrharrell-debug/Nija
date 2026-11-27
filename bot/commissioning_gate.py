"""Review-gated commissioning admission; deliberately not installed in production.

This boundary consumes one exact entry permission, not general LIVE authority.
The terminal transport must still enforce canonical risk, fencing, nonce and
broker restrictions. No method submits orders, publishes execution_ready,
clears stops, or changes the legacy activation FSM.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import sqlite3
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from .account_order_admission import AccountOrderAdmission, AdmissionDenied, Collector, Fence, Reservation
from .kraken_operator_authorization import (
    OperatorAuthorizationDenied, _canonical, _digest, _identifier, _timestamp, _verified_payload,
)
from .kraken_authenticated_account_identity_v478 import _scope_valid
from .order_admission_policy import Candidate, OrderOutcome
from .pretrade_attestation_validation_v452 import REQUIRED, evaluate_pretrade_certificate
from .startup_verification_plan import StartupVerificationPlan, decimal_value

logger = logging.getLogger(__name__)
_APPROVAL_FIELDS = frozenset({
    "contract", "approval_id", "operator_id", "account", "account_fingerprint",
    "credential_fingerprint", "writer_generation", "plan_digest", "release_id",
    "maximum_cash_debit_usd", "approved_at_epoch", "expires_at_epoch",
})
_STATUS_FIELDS = frozenset({
    "contract", "approval_id", "approval_sha256", "status", "generation",
    "observed_at_epoch", "expires_at_epoch",
})
Observations = Callable[[Candidate, sqlite3.Connection], Mapping[str, Any]]
ExecutionReader = Callable[[Candidate, StartupVerificationPlan, sqlite3.Connection], Mapping[str, Any]]


@dataclass(frozen=True)
class CommissioningDecision:
    """Stage eligibility, never broad execution authority or a fill marker."""

    state: str
    allow_new_orders: bool = False
    allow_controlled_first_trade: bool = False
    reasons: tuple[str, ...] = ()


class CommissioningGate(AccountOrderAdmission):
    """Use the shared canonical ledger to latch a single commissioning attempt.

    Dependencies and public keys must come from an independently reviewed
    composition root, not request metadata or environment flags. General
    signed operator authorization and exact first-order approval are distinct.
    Kraken USD spot is the only supported commissioning envelope; unsupported
    brokers/margin never inherit a new privilege.
    """

    def __init__(
        self, ledger: Path, collector: Collector, fence: Fence, *,
        observations: Observations, trusted_provider_ids: Mapping[str, str],
        execution_reader: ExecutionReader, read_approval: Callable[[], Mapping[str, Any]],
        operator_public_keys: Mapping[str, bytes], status_public_key: bytes,
        release_id: str, maximum_cash_debit_usd: str,
        account_scope: str, account_fingerprint: str, credential_fingerprint: str,
        independently_reviewed: bool = False,
    ) -> None:
        super().__init__(ledger, collector, fence)
        if independently_reviewed is not True:
            raise AdmissionDenied("commissioning_independent_review_required")
        keys = dict(operator_public_keys)
        if (not callable(observations) or not callable(execution_reader) or not callable(read_approval)
                or set(trusted_provider_ids) != set(REQUIRED) or not _identifier(release_id)
                or not _scope_valid(account_scope) or not _digest(account_fingerprint)
                or not isinstance(credential_fingerprint, str) or len(credential_fingerprint) != 128
                or any(char not in "0123456789abcdef" for char in credential_fingerprint)
                or not keys or any(not _identifier(name) or type(key) is not bytes or len(key) != 32
                                   for name, key in keys.items())
                or type(status_public_key) is not bytes or len(status_public_key) != 32
                or status_public_key in keys.values()):
            raise AdmissionDenied("commissioning_reviewed_dependencies_required")
        ceiling = decimal_value(maximum_cash_debit_usd)
        if ceiling <= 0:
            raise AdmissionDenied("commissioning_reviewed_cash_ceiling_required")
        self.observations = observations
        self.trusted_provider_ids = dict(trusted_provider_ids)
        self.execution_reader = execution_reader
        self.read_approval = read_approval
        self.operator_public_keys = keys
        self.status_public_key = status_public_key
        self.release_id = release_id
        self.maximum_cash_debit = ceiling
        self.account_scope = account_scope
        self.account_fingerprint = account_fingerprint
        self.credential_fingerprint = credential_fingerprint

    def install_schema(self) -> None:
        """Explicit migration only; never called at import or runtime startup."""
        with self._transaction() as conn:
            self._install_schema(conn)
            conn.execute("""CREATE TABLE IF NOT EXISTS commissioning_attempts (
                account_fingerprint TEXT PRIMARY KEY, account TEXT NOT NULL UNIQUE,
                credential_fingerprint TEXT NOT NULL, writer_generation INTEGER NOT NULL,
                plan_digest TEXT NOT NULL, release_id TEXT NOT NULL,
                approval_id TEXT NOT NULL UNIQUE, approval_sha256 TEXT NOT NULL UNIQUE,
                token TEXT NOT NULL UNIQUE, submitted_at REAL NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('CONTROLLED_FIRST_TRADE','POSTTRADE_VERIFIED')),
                broker_order_id TEXT NOT NULL DEFAULT '', broker_event_at REAL
            )""")
            for table, required in (
                ("account_entry_reservations", {
                    "token", "account", "credential_fingerprint", "writer_generation",
                    "intent_digest", "state", "created_at",
                }),
                ("commissioning_attempts", {
                    "account_fingerprint", "account", "credential_fingerprint",
                    "writer_generation", "plan_digest", "release_id", "approval_id",
                    "approval_sha256", "token", "submitted_at", "state",
                    "broker_order_id", "broker_event_at",
                }),
            ):
                obj = conn.execute(
                    "SELECT type FROM sqlite_master WHERE name=?", (table,)
                ).fetchone()
                columns = {
                    row[1] for row in conn.execute("PRAGMA table_info(" + table + ")").fetchall()
                }
                if obj != ("table",) or not required.issubset(columns):
                    raise AdmissionDenied("commissioning_ledger_migration_invalid:" + table)

    def reserve(self, candidate: Candidate) -> Reservation:
        """Forbid inherited generic admission as a commissioning shortcut."""
        raise AdmissionDenied("commissioning_exact_first_trade_method_required")

    def consume(self, reservation: Reservation) -> None:
        """Forbid replaying a consumed commissioning permission via the base API."""
        raise AdmissionDenied("commissioning_exact_first_trade_method_required")

    def _pretrade(
        self, candidate: Candidate, plan: StartupVerificationPlan, conn: sqlite3.Connection,
        *, permit_expired_plan: bool = False,
    ) -> None:
        plan.validate()
        if (type(candidate) is not Candidate
                or candidate.account != self.account_scope
                or plan.account_fingerprint != self.account_fingerprint
                or candidate.credential_fingerprint != self.credential_fingerprint
                or candidate.credential_fingerprint != plan.api_key_fingerprint
                or candidate.intent_digest != plan.digest()
                or decimal_value(plan.budget_usd) > self.maximum_cash_debit):
            raise AdmissionDenied("commissioning_plan_binding_or_ceiling_invalid")
        conn.execute("PRAGMA query_only=ON")
        try:
            rows = self.observations(candidate, conn)
        finally:
            conn.execute("PRAGMA query_only=OFF")
        # The existing admission collector preserves ALL candidate-level risk,
        # signal, market, minimum, account, ledger and startup-attempt controls.
        self._check(candidate, conn)
        now = time.time()
        certificate = evaluate_pretrade_certificate(
            rows, account=candidate.account, trusted_provider_ids=self.trusted_provider_ids, now_epoch=now,
        )
        if certificate["certified"] is not True:
            raise AdmissionDenied("commissioning_pretrade:" + ",".join(certificate["missing"]))
        operator = rows["operator_authorization"]
        provenance = operator["provenance"]
        if (provenance.get("signature_algorithm") != "Ed25519"
                or provenance.get("approval_contract") != "nija.general-live-approval.v1"
                or provenance.get("revocation_contract") != "nija.general-live-approval-status.v1"
                or not _identifier(operator.get("approval_id"))
                or type(operator.get("status_generation")) is not int
                or operator["status_generation"] <= 0
                or not _timestamp(operator.get("expires_at_epoch"))):
            raise AdmissionDenied("commissioning_signed_general_authorization_required")
        if not _timestamp(plan.expires_at_epoch) or (
            not permit_expired_plan and now >= plan.expires_at_epoch
        ):
            raise AdmissionDenied("commissioning_plan_expired")

    def _approval(
        self, candidate: Candidate, plan: StartupVerificationPlan,
    ) -> tuple[str, str, float]:
        import json

        records = self.read_approval()
        if not isinstance(records, dict) or set(records) != {"approval", "status"}:
            raise AdmissionDenied("commissioning_signed_approval_and_status_required")
        frozen = _canonical(records)
        records = json.loads(frozen)
        envelope = records["approval"]
        if not isinstance(envelope, dict) or not isinstance(envelope.get("payload"), dict):
            raise AdmissionDenied("commissioning_signed_first_order_required")
        operator = envelope["payload"].get("operator_id")
        if not isinstance(operator, str) or operator not in self.operator_public_keys:
            raise AdmissionDenied("commissioning_operator_untrusted")
        try:
            approval = _verified_payload(envelope, self.operator_public_keys[operator], _APPROVAL_FIELDS)
            status = _verified_payload(records["status"], self.status_public_key, _STATUS_FIELDS)
        except OperatorAuthorizationDenied:
            raise AdmissionDenied("commissioning_signature_invalid") from None
        expected = {
            "contract": "nija.controlled-first-trade.v1",
            "account": candidate.account, "account_fingerprint": plan.account_fingerprint,
            "credential_fingerprint": candidate.credential_fingerprint,
            "writer_generation": candidate.writer_generation, "plan_digest": plan.digest(),
            "release_id": self.release_id,
        }
        if (any(approval[key] != value for key, value in expected.items())
                or type(approval["writer_generation"]) is not int
                or not _identifier(approval["approval_id"])):
            raise AdmissionDenied("commissioning_first_order_binding_mismatch")
        ceiling = decimal_value(approval["maximum_cash_debit_usd"])
        if not plan.maximum_cash_debit() <= ceiling <= self.maximum_cash_debit:
            raise AdmissionDenied("commissioning_first_order_cash_ceiling_invalid")
        digest = hashlib.sha256(_canonical(approval)).hexdigest()
        if (status["contract"] != "nija.controlled-first-trade-status.v1"
                or status["approval_id"] != approval["approval_id"]
                or status["approval_sha256"] != digest or status["status"] != "active"
                or type(status["generation"]) is not int or status["generation"] <= 0):
            raise AdmissionDenied("commissioning_approval_revoked_or_unbound")
        if _canonical(self.read_approval()) != frozen:
            raise AdmissionDenied("commissioning_approval_changed_during_read")
        now = time.time()
        approved, expires = approval["approved_at_epoch"], approval["expires_at_epoch"]
        observed, status_expires = status["observed_at_epoch"], status["expires_at_epoch"]
        if (not all(_timestamp(value) for value in (approved, expires, observed, status_expires))
                or not approved <= now < min(expires, plan.expires_at_epoch)
                or expires - approved > 300
                or not 0 <= now - observed <= 60 or not observed <= now < status_expires):
            raise AdmissionDenied("commissioning_approval_future_expired_or_stale")
        return approval["approval_id"], digest, min(expires, status_expires, observed + 60, plan.expires_at_epoch)

    def _first_trade_checks(
        self, candidate: Candidate, plan: StartupVerificationPlan, conn: sqlite3.Connection,
    ) -> tuple[str, str]:
        approval_id, digest, deadline = self._approval(candidate, plan)
        self._pretrade(candidate, plan, conn)
        if time.time() >= deadline:
            raise AdmissionDenied("commissioning_approval_expired_during_pretrade")
        if conn.execute(
            "SELECT 1 FROM commissioning_attempts WHERE account=? OR account_fingerprint=?",
            (candidate.account, plan.account_fingerprint),
        ).fetchone() or conn.execute(
            "SELECT 1 FROM account_entry_reservations WHERE account=? AND state!='reconciled'",
            (candidate.account,),
        ).fetchone():
            raise AdmissionDenied("commissioning_attempt_or_account_consumed")
        return approval_id, digest

    def inspect_first_trade(
        self, candidate: Candidate, plan: StartupVerificationPlan,
    ) -> CommissioningDecision:
        """Review one exact signed first-order eligibility without consuming it."""
        with self._transaction() as conn:
            self._first_trade_checks(candidate, plan, conn)
        return CommissioningDecision("PRETRADE_READY", allow_controlled_first_trade=True)

    def inspect_pretrade(self, candidate: Candidate, plan: StartupVerificationPlan) -> CommissioningDecision:
        """Certify current pretrade controls without requiring a new execution."""
        try:
            with self._transaction() as conn:
                self._pretrade(candidate, plan, conn)
                if conn.execute(
                    "SELECT 1 FROM commissioning_attempts WHERE account=? OR account_fingerprint=?",
                    (candidate.account, plan.account_fingerprint),
                ).fetchone():
                    return CommissioningDecision("ATTEMPT_CONSUMED", reasons=("reconciliation_required",))
            return CommissioningDecision("PRETRADE_READY")
        except AdmissionDenied:
            logger.warning("COMMISSIONING_PRETRADE_DENIED fail_closed=true")
            raise

    def verify_consumed_first_trade(self, reservation: Reservation, plan: StartupVerificationPlan) -> None:
        """Recheck the exact consumed attempt immediately before terminal transport.

        This never creates or releases a reservation. A denial leaves the
        durable attempt consumed for independent reconciliation. The adapter
        separately disarms its one transport attempt before invoking this read.
        """
        if type(reservation) is not Reservation or type(reservation.candidate) is not Candidate:
            raise AdmissionDenied("commissioning_consumed_reservation_required")
        candidate = reservation.candidate
        with self._transaction() as conn:
            approval_id, digest, deadline = self._approval(candidate, plan)
            row = conn.execute("""SELECT a.credential_fingerprint,a.writer_generation,a.plan_digest,
                a.release_id,a.approval_id,a.approval_sha256,a.token,a.state,
                r.account,r.credential_fingerprint,r.writer_generation,r.intent_digest,r.state
                FROM commissioning_attempts a JOIN account_entry_reservations r ON r.token=a.token
                WHERE a.account=? AND a.account_fingerprint=?""",
                (candidate.account, plan.account_fingerprint)).fetchone()
            expected = (
                candidate.credential_fingerprint, candidate.writer_generation, plan.digest(),
                self.release_id, approval_id, digest, reservation.token, "CONTROLLED_FIRST_TRADE",
                candidate.account, candidate.credential_fingerprint, candidate.writer_generation,
                candidate.intent_digest, "submitting",
            )
            if row != expected:
                raise AdmissionDenied("commissioning_consumed_attempt_binding_mismatch")
            self._pretrade(candidate, plan, conn)
            current_id, current_digest, current_deadline = self._approval(candidate, plan)
            if (current_id, current_digest) != (approval_id, digest):
                raise AdmissionDenied("commissioning_approval_changed_before_transport")
            if time.time() >= min(deadline, current_deadline):
                raise AdmissionDenied("commissioning_approval_expired_before_transport")

    def consume_first_trade(self, candidate: Candidate, plan: StartupVerificationPlan) -> Reservation:
        """Atomically latch one signed, bounded intent BEFORE transport.

        The returned reservation is already consumed. Timeout, rejection,
        cancellation, restart, approval/key rotation and writer handoff cannot
        release it. This is not a dispatch call or broad authorization.
        """
        try:
            with self._transaction() as conn:
                approval_id, digest = self._first_trade_checks(candidate, plan, conn)
                token = secrets.token_hex(32)
                submitted = time.time()
                conn.execute("""INSERT INTO account_entry_reservations
                    (token,account,credential_fingerprint,writer_generation,intent_digest,state,created_at)
                    VALUES (?,?,?,?,?,'submitting',?)""", (
                        token, candidate.account, candidate.credential_fingerprint,
                        candidate.writer_generation, candidate.intent_digest, submitted,
                    ))
                conn.execute("""INSERT INTO commissioning_attempts
                    (account_fingerprint,account,credential_fingerprint,writer_generation,plan_digest,
                     release_id,approval_id,approval_sha256,token,submitted_at,state)
                    VALUES (?,?,?,?,?,?,?,?,?,?,'CONTROLLED_FIRST_TRADE')""", (
                        plan.account_fingerprint, candidate.account, candidate.credential_fingerprint,
                        candidate.writer_generation, plan.digest(), self.release_id,
                        approval_id, digest, token, submitted,
                    ))
            logger.info("COMMISSIONING_CONTROLLED_FIRST_TRADE consumed=true broad_authority=false")
            return Reservation(token, candidate)
        except sqlite3.IntegrityError:
            logger.warning("COMMISSIONING_FIRST_TRADE_DENIED reason=attempt_or_account_consumed fail_closed=true")
            raise AdmissionDenied("commissioning_attempt_or_account_consumed") from None
        except AdmissionDenied:
            logger.warning("COMMISSIONING_FIRST_TRADE_DENIED fail_closed=true")
            raise

    def verify_posttrade(
        self, candidate: Candidate, plan: StartupVerificationPlan,
    ) -> CommissioningDecision:
        """Verify THIS attempt's authoritative fill, ledger and protective exit.

        The reviewed reader must authenticate the exact broker account/order
        and correlate canonical fills, complete ledger pagination and exits.
        Stored completion is not fresh evidence: every call re-reads the broker.
        Neither a broker ACK nor historical/simulated/synthetic data qualifies.
        """
        with self._transaction() as conn:
            row = conn.execute("""SELECT credential_fingerprint,writer_generation,plan_digest,release_id,
                submitted_at,token,state,broker_order_id,broker_event_at
                FROM commissioning_attempts WHERE account=? AND account_fingerprint=?""",
                (candidate.account, plan.account_fingerprint)).fetchone()
            if row is None or row[:4] != (
                candidate.credential_fingerprint, candidate.writer_generation, plan.digest(), self.release_id,
            ):
                raise AdmissionDenied("commissioning_attempt_missing_or_identity_mismatch")
            conn.execute("PRAGMA query_only=ON")
            try:
                evidence = self.execution_reader(candidate, plan, conn)
                _, outcome = self.collector(candidate, conn)
            finally:
                conn.execute("PRAGMA query_only=OFF")
            self._pretrade(candidate, plan, conn, permit_expired_plan=True)
            now = time.time()
            if not isinstance(evidence, Mapping):
                raise AdmissionDenied("commissioning_execution_evidence_missing")
            expected = {
                "candidate": candidate, "account_fingerprint": plan.account_fingerprint,
                "client_order_id": plan.order_parameters("entry")["cl_ord_id"],
                "entry_parameters": plan.order_parameters("entry"),
                "source": "canonical_confirmed_fill", "stage": "FILL_VERIFY", "proof_kind": "execution_probe",
                "authoritative_broker_verified": True, "ledger_reconciled": True,
                "protective_exit_verified": True, "synthetic": False, "simulated": False, "historical": False,
            }
            if any(type(evidence.get(key)) is not type(value) or evidence.get(key) != value
                   for key, value in expected.items()):
                raise AdmissionDenied("commissioning_execution_provenance_or_reconciliation_invalid")
            event, verified = evidence.get("broker_event_at_epoch"), evidence.get("verified_at_epoch")
            if (not _timestamp(event) or not _timestamp(verified)
                    or not row[4] <= event <= verified <= now
                    or now - event > 1800 or now - verified > 1800
                    or not _identifier(evidence.get("broker_order_id"))
                    or not _identifier(evidence.get("protective_order_id"))):
                raise AdmissionDenied("commissioning_execution_event_not_fresh_for_this_attempt")
            if (type(outcome) is not OrderOutcome or outcome.account != candidate.account
                    or outcome.state != "verified" or outcome.canonical_fill_verified is not True
                    or outcome.ledger_reconciled is not True
                    or outcome.broker_order_id != evidence["broker_order_id"]
                    or outcome.broker_event_at != event or outcome.verified_at != verified):
                raise AdmissionDenied("commissioning_execution_ledger_outcome_mismatch")
            quantity = decimal_value(evidence.get("filled_base_quantity"))
            debit = decimal_value(evidence.get("cash_debit_usd"))
            owned = decimal_value(evidence.get("owned_base_quantity"))
            protected = decimal_value(evidence.get("protected_base_quantity"))
            if (quantity != decimal_value(plan.base_quantity)
                    or not 0 < owned <= protected <= quantity
                    or not Decimal(0) < debit <= plan.maximum_cash_debit()):
                raise AdmissionDenied("commissioning_execution_outside_approved_envelope")
            if row[6] == "POSTTRADE_VERIFIED":
                if row[7] != evidence["broker_order_id"] or row[8] != event:
                    raise AdmissionDenied("commissioning_execution_readback_changed")
            elif row[6] == "CONTROLLED_FIRST_TRADE":
                updated = conn.execute("""UPDATE commissioning_attempts SET state='POSTTRADE_VERIFIED',
                    broker_order_id=?,broker_event_at=? WHERE account_fingerprint=?
                    AND state='CONTROLLED_FIRST_TRADE' AND broker_order_id='' AND broker_event_at IS NULL""", (
                        evidence["broker_order_id"], event, plan.account_fingerprint,
                    )).rowcount
                if updated != 1:
                    raise AdmissionDenied("commissioning_attempt_state_changed")
            else:
                raise AdmissionDenied("commissioning_attempt_state_invalid")
            # Do not release account_entry_reservations here. The canonical
            # terminal reconciliation adapter must independently do that.
        logger.info("COMMISSIONING_POSTTRADE_VERIFIED fresh_execution=true broad_authority=false")
        return CommissioningDecision("POSTTRADE_VERIFIED")
