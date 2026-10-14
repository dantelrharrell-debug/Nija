"""Per-member, per-broker cell identifiers and independent readiness policy.

Pure planning/state model. Not wired into production execution or broker orders.
Global emergency stops always supersede isolation.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256

BROKERS = frozenset({"kraken", "alpaca"})
ENVIRONMENTS = frozenset({"paper", "live"})


class CellState(str, Enum):
    DISABLED = "disabled"
    BLOCKED = "blocked"
    READY = "ready"


@dataclass(frozen=True)
class CellKey:
    member_id: str
    broker: str
    environment: str
    brokerage_account_id: str

    def __post_init__(self):
        if not all(isinstance(s, str) and s.strip() and ":" not in s for s in (
            self.member_id, self.brokerage_account_id
        )):
            raise ValueError("Member and broker account binding required")
        if self.broker not in BROKERS or self.environment not in ENVIRONMENTS:
            raise ValueError("Unsupported broker/environment")

    @property
    def isolation_id(self) -> str:
        # Opaque stable index; never use as authorization or identity proof.
        canonical = "\x00".join((self.member_id, self.broker, self.environment, self.brokerage_account_id))
        return sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CellChecks:
    subscription_valid: bool
    credential_owner_verified: bool
    broker_account_verified: bool
    connection_healthy: bool
    protective_exit_verified: bool
    ledger_reconciled: bool
    current_execution_proof: bool
    approved_for_live: bool


def cell_state(key: CellKey, checks: CellChecks, *, global_emergency_stop: bool) -> CellState:
    """Compute readiness without asserting any trading authority."""
    if global_emergency_stop:
        return CellState.DISABLED
    if not (checks.subscription_valid and checks.credential_owner_verified
            and checks.broker_account_verified and checks.connection_healthy):
        return CellState.BLOCKED
    if key.environment == "live" and not (
        checks.protective_exit_verified and checks.ledger_reconciled
        and checks.current_execution_proof and checks.approved_for_live
    ):
        return CellState.BLOCKED
    return CellState.READY


def isolation_report(
    checks_by_cell: dict[CellKey, CellChecks], *, global_emergency_stop: bool
) -> dict[CellKey, CellState]:
    """Evaluate separately; one unhealthy cell never mutates another's state."""
    return {
        key: cell_state(key, checks, global_emergency_stop=global_emergency_stop)
        for key, checks in checks_by_cell.items()
    }
