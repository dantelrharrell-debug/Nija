"""NIJA member trading activation control plane.

Verified payment automatically approves membership per NIJA's business rule.
Trading authorization remains fail-closed and requires authoritative broker,
account, reconciliation, risk, protection, writer and execution evidence.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, replace
from enum import Enum
from typing import Dict, Mapping, Optional, Tuple

from bot.broker_isolation_registry import (
    BrokerIsolationRegistry,
    CellHealth,
    get_broker_isolation_registry,
)


class ActivationState(Enum):
    LEAD = "lead"
    PAYMENT_PENDING = "payment_pending"
    PAID = "paid"
    MEMBER_APPROVED = "member_approved"
    API_KEYS_REQUIRED = "api_keys_required"
    VERIFYING_BROKER = "verifying_broker"
    SYNCING_ACCOUNT = "syncing_account"
    SAFETY_CHECK = "safety_check"
    TRADING_READY = "trading_ready"
    ACTIVE = "active"
    NOT_READY = "not_ready"
    HALTED = "halted"


@dataclass(frozen=True)
class ActivationEvidence:
    payment_verified: bool = False
    credentials_stored: bool = False
    broker_authenticated: bool = False
    trading_permission_verified: bool = False
    capital_hydrated: bool = False
    positions_authoritative: bool = False
    open_orders_authoritative: bool = False
    reconciliation_fresh: bool = False
    risk_ready: bool = False
    strategy_ready: bool = False
    protective_coverage_ready: bool = False
    writer_authority_ready: bool = False
    execution_ready: bool = False

    def missing(self) -> Tuple[str, ...]:
        return tuple(name for name, value in vars(self).items() if not value)


@dataclass(frozen=True)
class MemberActivation:
    user_id: str
    broker_id: str
    account_id: str
    state: ActivationState = ActivationState.LEAD
    paid_member: bool = False
    member_approved: bool = False
    trading_enabled: bool = False
    reason: str = ""
    updated_at: float = 0.0


class MemberTradingActivationManager:
    """Fail-closed authorization registry keyed by user/broker/account cell."""

    def __init__(self, broker_registry: Optional[BrokerIsolationRegistry] = None) -> None:
        # Production must observe the same canonical broker-cell halts as execution.
        # Tests may inject an isolated registry.
        self._broker_registry = broker_registry if broker_registry is not None else get_broker_isolation_registry()
        self._members: Dict[Tuple[str, str, str], MemberActivation] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _key(user_id: str, broker_id: str, account_id: str) -> Tuple[str, str, str]:
        return str(user_id), str(broker_id).lower(), str(account_id)

    def _get_or_create_locked(self, user_id: str, broker_id: str, account_id: str) -> MemberActivation:
        key = self._key(user_id, broker_id, account_id)
        member = self._members.get(key)
        if member is None:
            member = MemberActivation(*key, updated_at=time.time())
            self._members[key] = member
        return member

    def get_or_create(self, user_id: str, broker_id: str, account_id: str) -> MemberActivation:
        with self._lock:
            return replace(self._get_or_create_locked(user_id, broker_id, account_id))

    def _store(self, member: MemberActivation, **changes: object) -> MemberActivation:
        updated = replace(member, updated_at=time.time(), **changes)
        self._members[self._key(updated.user_id, updated.broker_id, updated.account_id)] = updated
        return replace(updated)

    def record_payment(self, user_id: str, broker_id: str, account_id: str, *, verified: bool) -> MemberActivation:
        """Authoritative verified payment automatically approves NIJA membership."""
        with self._lock:
            member = self._get_or_create_locked(user_id, broker_id, account_id)
            return self._store(
                member,
                paid_member=bool(verified),
                member_approved=bool(verified),
                trading_enabled=False,
                state=ActivationState.API_KEYS_REQUIRED if verified else ActivationState.PAYMENT_PENDING,
                reason="payment_verified_auto_approved" if verified else "payment_not_verified",
            )

    def evaluate(self, user_id: str, broker_id: str, account_id: str, evidence: ActivationEvidence) -> MemberActivation:
        broker = str(broker_id).lower()
        with self._lock:
            member = self._get_or_create_locked(user_id, broker, account_id)

            if not evidence.payment_verified or not member.paid_member or not member.member_approved:
                return self._store(member, state=ActivationState.PAYMENT_PENDING, trading_enabled=False, reason="authoritative_payment_required")
            if not evidence.credentials_stored:
                return self._store(member, state=ActivationState.API_KEYS_REQUIRED, trading_enabled=False, reason="broker_credentials_required")

            cell = self._broker_registry.get_or_default(broker)
            if cell.state.health in {CellHealth.HALTED, CellHealth.DISABLED} or cell.skip_execution():
                return self._store(member, state=ActivationState.HALTED, trading_enabled=False, reason=cell.state.halted_reason or "broker_cell_not_execution_eligible")

            if broker == "kraken" and not (evidence.positions_authoritative and evidence.open_orders_authoritative):
                return self._store(member, state=ActivationState.NOT_READY, trading_enabled=False, reason="kraken_authoritative_position_order_visibility_required")

            missing = evidence.missing()
            if missing:
                if not evidence.broker_authenticated or not evidence.trading_permission_verified:
                    state = ActivationState.VERIFYING_BROKER
                elif not (evidence.capital_hydrated and evidence.positions_authoritative and evidence.open_orders_authoritative and evidence.reconciliation_fresh):
                    state = ActivationState.SYNCING_ACCOUNT
                else:
                    state = ActivationState.SAFETY_CHECK
                return self._store(member, state=state, trading_enabled=False, reason="missing:" + ",".join(missing))

            if not self._broker_registry.register_user(broker, member.user_id):
                return self._store(member, state=ActivationState.NOT_READY, trading_enabled=False, reason="broker_cell_registration_failed")

            # Re-read canonical cell after registration. ACTIVE is never granted from
            # the pre-registration snapshot.
            cell = self._broker_registry.get_or_default(broker)
            if cell.state.health in {CellHealth.HALTED, CellHealth.DISABLED} or cell.skip_execution():
                return self._store(member, state=ActivationState.HALTED, trading_enabled=False, reason=cell.state.halted_reason or "broker_cell_halted_during_activation")

            return self._store(member, state=ActivationState.TRADING_READY, trading_enabled=False, reason="all_activation_gates_passed")

    def activate(self, user_id: str, broker_id: str, account_id: str, evidence: ActivationEvidence) -> MemberActivation:
        evaluated = self.evaluate(user_id, broker_id, account_id, evidence)
        if evaluated.state != ActivationState.TRADING_READY:
            return evaluated

        with self._lock:
            member = self._get_or_create_locked(user_id, broker_id, account_id)
            # Final canonical execution-cell validation immediately before granting
            # authorization. Execution must continue to enforce its own cell gate.
            cell = self._broker_registry.get_or_default(str(broker_id).lower())
            if cell.state.health in {CellHealth.HALTED, CellHealth.DISABLED} or cell.skip_execution():
                return self._store(member, state=ActivationState.HALTED, trading_enabled=False, reason=cell.state.halted_reason or "broker_cell_not_execution_eligible_at_authorization")
            return self._store(member, state=ActivationState.ACTIVE, trading_enabled=True, reason="member_trading_activation_authorized")

    def halt(self, user_id: str, broker_id: str, account_id: str, reason: str) -> MemberActivation:
        with self._lock:
            member = self._get_or_create_locked(user_id, broker_id, account_id)
            return self._store(member, state=ActivationState.HALTED, trading_enabled=False, reason=str(reason)[:240])

    def snapshot(self, user_id: str, broker_id: str, account_id: str) -> Mapping[str, object]:
        member = self.get_or_create(user_id, broker_id, account_id)
        return {
            "user_id": member.user_id,
            "broker_id": member.broker_id,
            "account_id": member.account_id,
            "state": member.state.value,
            "paid_member": member.paid_member,
            "member_approved": member.member_approved,
            "trading_enabled": member.trading_enabled,
            "reason": member.reason,
            "updated_at": member.updated_at,
        }
