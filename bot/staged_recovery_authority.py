"""Staged recovery, per-account/broker isolation and exit-path health.

NIJA must never resume ordinary entries merely because the service restarted.
This module owns the staged recovery state machine and the per-broker /
per-account isolation registry that gate entries while keeping verified
protective exits available.

Staged recovery
---------------
``ENTRIES_OFF_EXITS_ON`` (always the state after a restart)
  → ``POSITIONS_VERIFIED``      (authoritative positions verified for every
                                 connected account)
  → ``EXIT_DISPATCH_VERIFIED``  (exit dispatcher verified independently for
                                 every active broker adapter)
  → ``EXIT_PROVEN``             (a genuine broker acknowledgment *and* a
                                 confirmed fill were observed)
  → ``FULL_TRADING``

Only :meth:`RecoveryCoordinator.transition_to_full_trading` can reach
``FULL_TRADING`` and it fails closed unless every earlier stage is satisfied.

Isolation
---------
Readiness, rejection rate, circuit-breaker state and exit health are tracked
separately for every ``(broker, account)`` scope:

* a customer credential failure quarantines **only that account**;
* a broker-specific failure quarantines **only that broker**;
* a shared execution-code failure stops **all new entries globally** while
  leaving protective exits available wherever the specific broker path is
  still verified healthy.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.recovery_authority")


class RecoveryStage(str, Enum):
    """Staged recovery states.  Ordered from most restrictive to least."""

    ENTRIES_OFF_EXITS_ON = "ENTRIES_OFF_EXITS_ON"
    POSITIONS_VERIFIED = "POSITIONS_VERIFIED"
    EXIT_DISPATCH_VERIFIED = "EXIT_DISPATCH_VERIFIED"
    EXIT_PROVEN = "EXIT_PROVEN"
    FULL_TRADING = "FULL_TRADING"


_STAGE_ORDER: Tuple[RecoveryStage, ...] = (
    RecoveryStage.ENTRIES_OFF_EXITS_ON,
    RecoveryStage.POSITIONS_VERIFIED,
    RecoveryStage.EXIT_DISPATCH_VERIFIED,
    RecoveryStage.EXIT_PROVEN,
    RecoveryStage.FULL_TRADING,
)


class QuarantineScope(str, Enum):
    """What a failure isolates."""

    ACCOUNT = "account"
    BROKER = "broker"
    GLOBAL = "global"


@dataclass
class ScopeHealth:
    """Health record for one ``(broker, account)`` execution scope."""

    broker: str
    account_id: str
    positions_verified: bool = False
    exit_dispatch_verified: bool = False
    exit_path_healthy: bool = True
    circuit_breaker_open: bool = False
    quarantined: bool = False
    quarantine_reason: str = ""
    submitted_orders: int = 0
    exchange_rejections: int = 0
    confirmed_fills: int = 0
    genuine_ack_order_ids: List[str] = field(default_factory=list)
    last_updated: float = field(default_factory=time.time)

    @property
    def rejection_rate(self) -> float:
        if self.submitted_orders <= 0:
            return 0.0
        return self.exchange_rejections / float(self.submitted_orders)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "broker": self.broker,
            "account_id": self.account_id,
            "positions_verified": self.positions_verified,
            "exit_dispatch_verified": self.exit_dispatch_verified,
            "exit_path_healthy": self.exit_path_healthy,
            "circuit_breaker_open": self.circuit_breaker_open,
            "quarantined": self.quarantined,
            "quarantine_reason": self.quarantine_reason,
            "submitted_orders": self.submitted_orders,
            "exchange_rejections": self.exchange_rejections,
            "rejection_rate": round(self.rejection_rate, 6),
            "confirmed_fills": self.confirmed_fills,
            "genuine_ack_order_ids": list(self.genuine_ack_order_ids),
            "last_updated": self.last_updated,
        }


class RecoveryCoordinator:
    """Owns the staged recovery state and the isolation registry."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._stage: RecoveryStage = RecoveryStage.ENTRIES_OFF_EXITS_ON
        self._scopes: Dict[Tuple[str, str], ScopeHealth] = {}
        self._quarantined_accounts: Dict[str, str] = {}
        self._quarantined_brokers: Dict[str, str] = {}
        self._global_entry_block: str = ""
        self._below_minimum: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

    # -- staged recovery ------------------------------------------------

    @property
    def stage(self) -> RecoveryStage:
        with self._lock:
            return self._stage

    def reset_for_restart(self, reason: str = "process_restart") -> RecoveryStage:
        """Force the most restrictive stage.  Called on every startup."""
        with self._lock:
            self._stage = RecoveryStage.ENTRIES_OFF_EXITS_ON
            for scope in self._scopes.values():
                scope.positions_verified = False
                scope.exit_dispatch_verified = False
            logger.critical(
                "RECOVERY_STAGE_RESET stage=%s reason=%s entries_enabled=false exits_enabled=true",
                self._stage.value, reason,
            )
            return self._stage

    def _advance_to(self, stage: RecoveryStage, reason: str) -> RecoveryStage:
        with self._lock:
            if _STAGE_ORDER.index(stage) > _STAGE_ORDER.index(self._stage) + 1:
                logger.error(
                    "RECOVERY_STAGE_SKIP_BLOCKED current=%s requested=%s reason=%s",
                    self._stage.value, stage.value, reason,
                )
                return self._stage
            self._stage = stage
            logger.critical(
                "RECOVERY_STAGE_ADVANCED stage=%s reason=%s entries_enabled=%s exits_enabled=true",
                stage.value, reason, str(stage is RecoveryStage.FULL_TRADING).lower(),
            )
            return self._stage

    def mark_positions_verified(self, broker: str, account_id: str) -> None:
        """Record that authoritative positions were verified for one account."""
        with self._lock:
            self._scope(broker, account_id).positions_verified = True
        self._maybe_advance()

    def mark_exit_dispatch_verified(self, broker: str, account_id: str) -> None:
        """Record an independent exit-dispatcher verification for one adapter."""
        with self._lock:
            scope = self._scope(broker, account_id)
            scope.exit_dispatch_verified = True
            scope.exit_path_healthy = True
        self._maybe_advance()

    def record_genuine_acknowledgment(
        self, broker: str, account_id: str, *, order_id: str, filled: bool
    ) -> None:
        """Record a genuine broker order ID and whether a fill was confirmed.

        An acknowledgment without a confirmed fill never satisfies the exit
        proof requirement.
        """
        order_id = str(order_id or "").strip()
        if not order_id:
            logger.error(
                "RECOVERY_ACK_REJECTED broker=%s account=%s reason=missing_broker_order_id "
                "fill_fabricated=false", broker, account_id,
            )
            return
        with self._lock:
            scope = self._scope(broker, account_id)
            scope.genuine_ack_order_ids.append(order_id)
            if filled:
                scope.confirmed_fills += 1
        self._maybe_advance()

    def _maybe_advance(self) -> None:
        with self._lock:
            scopes = [s for s in self._scopes.values() if not s.quarantined]
            if not scopes:
                return
            if self._stage is RecoveryStage.ENTRIES_OFF_EXITS_ON and all(
                s.positions_verified for s in scopes
            ):
                self._advance_to(RecoveryStage.POSITIONS_VERIFIED, "all_accounts_positions_verified")
            if self._stage is RecoveryStage.POSITIONS_VERIFIED and all(
                s.exit_dispatch_verified for s in scopes
            ):
                self._advance_to(
                    RecoveryStage.EXIT_DISPATCH_VERIFIED, "all_broker_exit_dispatchers_verified"
                )
            if self._stage is RecoveryStage.EXIT_DISPATCH_VERIFIED and any(
                s.genuine_ack_order_ids and s.confirmed_fills > 0 for s in scopes
            ):
                self._advance_to(RecoveryStage.EXIT_PROVEN, "genuine_ack_and_confirmed_fill")

    def transition_to_full_trading(self) -> Tuple[bool, str]:
        """Attempt the final transition.  Fails closed."""
        with self._lock:
            if self._global_entry_block:
                return False, f"global_entry_block:{self._global_entry_block}"
            if self._stage is not RecoveryStage.EXIT_PROVEN:
                return False, f"stage_not_exit_proven:{self._stage.value}"
            scopes = [s for s in self._scopes.values() if not s.quarantined]
            if not scopes:
                return False, "no_active_scopes"
            for scope in scopes:
                if not scope.positions_verified:
                    return False, f"positions_unverified:{scope.broker}:{scope.account_id}"
                if not scope.exit_dispatch_verified:
                    return False, f"exit_dispatch_unverified:{scope.broker}:{scope.account_id}"
                if not scope.exit_path_healthy:
                    return False, f"exit_path_unhealthy:{scope.broker}:{scope.account_id}"
            self._advance_to(RecoveryStage.FULL_TRADING, "all_recovery_gates_passed")
            return True, "full_trading"

    # -- isolation ------------------------------------------------------

    def _scope(self, broker: str, account_id: str) -> ScopeHealth:
        key = (str(broker or "").strip().lower(), str(account_id or "default").strip().lower())
        scope = self._scopes.get(key)
        if scope is None:
            scope = ScopeHealth(broker=key[0], account_id=key[1])
            self._scopes[key] = scope
        return scope

    def get_scope(self, broker: str, account_id: str) -> ScopeHealth:
        with self._lock:
            return self._scope(broker, account_id)

    def quarantine(
        self, *, scope: QuarantineScope, reason: str, broker: str = "", account_id: str = ""
    ) -> None:
        """Quarantine an account, a broker, or block all new entries globally."""
        with self._lock:
            if scope is QuarantineScope.ACCOUNT:
                account = str(account_id or "").strip().lower()
                self._quarantined_accounts[account] = reason
                for key, health in self._scopes.items():
                    if key[1] == account:
                        health.quarantined = True
                        health.quarantine_reason = reason
            elif scope is QuarantineScope.BROKER:
                name = str(broker or "").strip().lower()
                self._quarantined_brokers[name] = reason
                for key, health in self._scopes.items():
                    if key[0] == name:
                        health.quarantined = True
                        health.quarantine_reason = reason
            else:
                self._global_entry_block = reason
                if self._stage is RecoveryStage.FULL_TRADING:
                    self._stage = RecoveryStage.ENTRIES_OFF_EXITS_ON
            logger.critical(
                "EXECUTION_QUARANTINE scope=%s broker=%s account=%s reason=%s "
                "protective_exits_preserved=true",
                scope.value, broker or "*", account_id or "*", reason,
            )

    def record_credential_failure(self, broker: str, account_id: str, reason: str) -> None:
        """A customer credential failure quarantines only that account."""
        self.quarantine(
            scope=QuarantineScope.ACCOUNT,
            reason=f"credential_failure:{reason}",
            broker=broker,
            account_id=account_id,
        )

    def record_broker_failure(self, broker: str, reason: str) -> None:
        """A broker-specific failure quarantines only that broker."""
        self.quarantine(
            scope=QuarantineScope.BROKER, reason=f"broker_failure:{reason}", broker=broker
        )

    def record_shared_code_failure(self, reason: str) -> None:
        """A shared execution-code failure stops all new entries globally."""
        self.quarantine(scope=QuarantineScope.GLOBAL, reason=f"shared_code_failure:{reason}")

    def record_order_outcome(
        self,
        broker: str,
        account_id: str,
        *,
        accepted: bool,
        exchange_contacted: bool,
        order_id: str = "",
        filled: bool = False,
    ) -> None:
        """Record an execution outcome for one scope.

        ``exchange_contacted=False`` marks an internal pre-dispatch failure; it
        never contributes to the scope's exchange rejection rate.
        """
        with self._lock:
            scope = self._scope(broker, account_id)
            scope.last_updated = time.time()
            if not exchange_contacted:
                scope.exit_path_healthy = False
                logger.error(
                    "SCOPE_INTERNAL_DISPATCH_FAILURE broker=%s account=%s "
                    "exchange_rejection_recorded=false entries_blocked_for_scope=true",
                    scope.broker, scope.account_id,
                )
                return
            scope.submitted_orders += 1
            if accepted:
                oid = str(order_id or "").strip()
                if oid:
                    scope.genuine_ack_order_ids.append(oid)
                if filled:
                    scope.confirmed_fills += 1
                    scope.exit_path_healthy = True
            else:
                scope.exchange_rejections += 1
                if scope.submitted_orders >= 5 and scope.rejection_rate >= 0.5:
                    scope.circuit_breaker_open = True

    def mark_exit_path_unhealthy(self, broker: str, account_id: str, reason: str) -> None:
        with self._lock:
            scope = self._scope(broker, account_id)
            scope.exit_path_healthy = False
        logger.error(
            "EXIT_PATH_UNHEALTHY broker=%s account=%s reason=%s new_entries_blocked=true",
            broker, account_id, reason,
        )

    # -- gates ----------------------------------------------------------

    def entries_allowed(self, broker: str, account_id: str) -> Tuple[bool, str]:
        """Return whether a *new entry* may be submitted for this scope."""
        with self._lock:
            if self._global_entry_block:
                return False, f"global_entry_block:{self._global_entry_block}"
            if self._stage is not RecoveryStage.FULL_TRADING:
                return False, f"recovery_stage:{self._stage.value}"
            name = str(broker or "").strip().lower()
            account = str(account_id or "default").strip().lower()
            if name in self._quarantined_brokers:
                return False, f"broker_quarantined:{self._quarantined_brokers[name]}"
            if account in self._quarantined_accounts:
                return False, f"account_quarantined:{self._quarantined_accounts[account]}"
            scope = self._scope(name, account)
            if scope.circuit_breaker_open:
                return False, "circuit_breaker_open"
            if not scope.exit_path_healthy:
                # Never open a position that cannot be protected.
                return False, "exit_path_unhealthy"
            return True, "allowed"

    def exits_allowed(self, broker: str, account_id: str) -> Tuple[bool, str]:
        """Protective exits remain available wherever the broker path is healthy."""
        with self._lock:
            name = str(broker or "").strip().lower()
            account = str(account_id or "default").strip().lower()
            if name in self._quarantined_brokers:
                return False, f"broker_quarantined:{self._quarantined_brokers[name]}"
            if account in self._quarantined_accounts:
                reason = self._quarantined_accounts[account]
                # A credential failure genuinely prevents submission for that
                # account; every other account-scoped quarantine still permits
                # protective exits on a verified-healthy broker path.
                if "credential_failure" in reason:
                    return False, f"account_quarantined:{reason}"
            return True, "allowed"

    # -- below-minimum positions ---------------------------------------

    def record_below_minimum_position(
        self, broker: str, account_id: str, *, symbol: str, owned_qty: float, minimum_qty: float
    ) -> None:
        """Record an exchange-enforced dust position that cannot be exited.

        New purchases of the same symbol on the same scope are blocked so NIJA
        cannot repeatedly create unexitable positions.
        """
        with self._lock:
            key = (
                str(broker or "").strip().lower(),
                str(account_id or "default").strip().lower(),
                str(symbol or "").strip().upper(),
            )
            self._below_minimum[key] = {
                "broker": key[0],
                "account_id": key[1],
                "symbol": key[2],
                "owned_qty": float(owned_qty),
                "minimum_qty": float(minimum_qty),
                "executable_stop_protection": False,
                "recorded_at": time.time(),
            }
        logger.critical(
            "BELOW_MINIMUM_EXIT_REGISTERED broker=%s account=%s symbol=%s owned_qty=%.12f "
            "minimum_qty=%.12f new_entries_blocked_for_symbol=true "
            "executable_stop_protection=false position_preserved=true",
            broker, account_id, symbol, float(owned_qty), float(minimum_qty),
        )

    def clear_below_minimum_position(self, broker: str, account_id: str, symbol: str) -> None:
        """Clear a dust marking after a recheck proves the position is executable."""
        with self._lock:
            self._below_minimum.pop(
                (
                    str(broker or "").strip().lower(),
                    str(account_id or "default").strip().lower(),
                    str(symbol or "").strip().upper(),
                ),
                None,
            )

    def below_minimum_positions(self) -> List[Dict[str, Any]]:
        """Administrator dashboard feed of below-minimum positions."""
        with self._lock:
            return list(self._below_minimum.values())

    def purchase_allowed(self, broker: str, account_id: str, symbol: str) -> Tuple[bool, str]:
        """Return whether a *new purchase* of *symbol* may be opened."""
        allowed, reason = self.entries_allowed(broker, account_id)
        if not allowed:
            return False, reason
        with self._lock:
            key = (
                str(broker or "").strip().lower(),
                str(account_id or "default").strip().lower(),
                str(symbol or "").strip().upper(),
            )
            if key in self._below_minimum:
                return False, "below_minimum_exit_position_exists"
        return True, "allowed"

    # -- reporting ------------------------------------------------------

    def protection_report(self) -> Dict[str, Any]:
        """Per-account protection report used for production-readiness sign-off."""
        with self._lock:
            accounts = [scope.as_dict() for scope in self._scopes.values()]
            dust = list(self._below_minimum.values())
            production_ready = bool(
                self._stage is RecoveryStage.FULL_TRADING
                and not self._global_entry_block
                and accounts
                and all(
                    scope["exit_dispatch_verified"]
                    and scope["positions_verified"]
                    and scope["exit_path_healthy"]
                    and not scope["quarantined"]
                    for scope in accounts
                )
            )
            return {
                "stage": self._stage.value,
                "global_entry_block": self._global_entry_block,
                "quarantined_accounts": dict(self._quarantined_accounts),
                "quarantined_brokers": dict(self._quarantined_brokers),
                "accounts": accounts,
                "below_minimum_positions": dust,
                "production_ready": production_ready,
            }


_COORDINATOR: Optional[RecoveryCoordinator] = None
_COORDINATOR_LOCK = threading.Lock()


def get_recovery_coordinator() -> RecoveryCoordinator:
    """Return the process-wide :class:`RecoveryCoordinator` singleton."""
    global _COORDINATOR
    with _COORDINATOR_LOCK:
        if _COORDINATOR is None:
            _COORDINATOR = RecoveryCoordinator()
            _COORDINATOR.reset_for_restart("singleton_created")
    return _COORDINATOR


__all__ = [
    "QuarantineScope",
    "RecoveryCoordinator",
    "RecoveryStage",
    "ScopeHealth",
    "get_recovery_coordinator",
]
