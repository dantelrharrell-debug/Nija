"""NIJA member trading activation control plane.

This module owns the lifecycle that turns a paid member with broker credentials
into an execution-eligible NIJA user.  It deliberately does not place orders and
does not bypass broker-cell, writer, reconciliation, risk, or protective-exit
contracts.  Callers must provide authoritative evidence for every readiness
check; missing evidence fails closed.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Mapping, Optional, Tuple

from bot.broker_isolation_registry import BrokerIsolationRegistry, CellHealth


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
    """Authoritative, broker/account-local evidence required for activation."""

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


@dataclass
class MemberActivation:
    user_id: str
    broker_id: str
    account_id: str
    state: ActivationState = ActivationState.LEAD
    paid_member: bool = False
    member_approved: bool = False
    trading_enabled: bool = False
    reason: str = ""
    updated_at: float = field(default_factory=time.time)


class MemberTradingActivationManager:
    """Thread-safe, fail-closed activation registry for NIJA member accounts."""

    def __init__(self, broker_registry: Optional[BrokerIsolationRegistry] = None) -> None:
        self._broker_registry = broker_registry or BrokerIsolationRegistry()
        self._members: Dict[Tuple[str, str, str], MemberActivation] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _key(user_id: str, broker_id: str, account_id: str) -> Tuple[str, str, str]:
        return str(user_id), str(broker_id).lower(), str(account_id)

    def get_or_create(self, user_id: str, broker_id: str, account_id: str) -> MemberActivation:
        key = self._key(user_id, broker_id, account_id)
        with self._lock:
            if key not in self._members:
                self._members[key] = MemberActivation(*key)
            return self._members[key]

    def record_payment(self, user_id: str, broker_id: str, account_id: str, *, verified: bool) -> MemberActivation:
        member = self.get_or_create(user_id, broker_id, account_id)
        with self._lock:
            member.paid_member = bool(verified)
            member.member_approved = bool(verified)
            member.trading_enabled = False
            member.state = ActivationState.API_KEYS_REQUIRED if verified else ActivationState.PAYMENT_PENDING
            member.reason = "payment_verified" if verified else "payment_not_verified"
            member.updated_at = time.time()
            return member

    def evaluate(self, user_id: str, broker_id: str, account_id: str, evidence: ActivationEvidence) -> MemberActivation:
        """Evaluate activation without placing orders or bypassing canonical gates."""
        member = self.get_or_create(user_id, broker_id, account_id)
        broker = str(broker_id).lower()
        cell = self._broker_registry.get_or_default(broker)

        with self._lock:
            member.trading_enabled = False
            member.updated_at = time.time()

            if not evidence.payment_verified or not member.paid_member or not member.member_approved:
                member.state = ActivationState.PAYMENT_PENDING
                member.reason = "authoritative_payment_required"
                return member

            if not evidence.credentials_stored:
                member.state = ActivationState.API_KEYS_REQUIRED
                member.reason = "broker_credentials_required"
                return member

            if cell.state.health in {CellHealth.HALTED, CellHealth.DISABLED} or cell.skip_execution():
                member.state = ActivationState.HALTED
                member.reason = cell.state.halted_reason or "broker_cell_not_execution_eligible"
                return member

            # Kraken must never advance without authoritative position/order state.
            if broker == "kraken" and not (evidence.positions_authoritative and evidence.open_orders_authoritative):
                member.state = ActivationState.NOT_READY
                member.reason = "kraken_authoritative_position_order_visibility_required"
                return member

            missing = evidence.missing()
            if missing:
                if not evidence.broker_authenticated or not evidence.trading_permission_verified:
                    member.state = ActivationState.VERIFYING_BROKER
                elif not (evidence.capital_hydrated and evidence.positions_authoritative and evidence.open_orders_authoritative and evidence.reconciliation_fresh):
                    member.state = ActivationState.SYNCING_ACCOUNT
                else:
                    member.state = ActivationState.SAFETY_CHECK
                member.reason = "missing:" + ",".join(missing)
                return member

            if not self._broker_registry.register_user(broker, member.user_id):
                member.state = ActivationState.NOT_READY
                member.reason = "broker_cell_registration_failed"
                return member

            member.state = ActivationState.TRADING_READY
            member.reason = "all_activation_gates_passed"
            return member

    def activate(self, user_id: str, broker_id: str, account_id: str, evidence: ActivationEvidence) -> MemberActivation:
        """Mark a user ACTIVE only after a fresh all-green readiness evaluation.

        This is authorization state only.  The canonical execution engine remains
        responsible for writer fencing, risk evaluation and actual order placement.
        """
        member = self.evaluate(user_id, broker_id, account_id, evidence)
        with self._lock:
            if member.state != ActivationState.TRADING_READY:
                return member
            member.state = ActivationState.ACTIVE
            member.trading_enabled = True
            member.reason = "member_trading_activation_authorized"
            member.updated_at = time.time()
            return member

    def halt(self, user_id: str, broker_id: str, account_id: str, reason: str) -> MemberActivation:
        member = self.get_or_create(user_id, broker_id, account_id)
        with self._lock:
            member.state = ActivationState.HALTED
            member.trading_enabled = False
            member.reason = str(reason)[:240]
            member.updated_at = time.time()
            return member

    def snapshot(self, user_id: str, broker_id: str, account_id: str) -> Mapping[str, object]:
        member = self.get_or_create(user_id, broker_id, account_id)
        with self._lock:
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
