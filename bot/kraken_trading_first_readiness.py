"""Pure Kraken trading-first readiness projection; never grants order authority.

Keeps administrative/reporting outages separate from account-integrity faults.
Inputs must be authenticated by the caller; no network, credentials, or orders.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

CRITICAL = frozenset({
    "account_permissions", "account_identity", "broker_balances",
    "position_ledger_reconciliation", "protective_exit_readback",
    "open_order_reconciliation", "duplicate_order_fence", "writer_lease",
    "nonce_sequence", "operator_authorization", "kill_switch_clear",
    "risk_limits", "position_sync",
})


class Mode(str, Enum):
    RECOVERY = "RECOVERY"
    VERIFYING = "VERIFYING"
    LIVE_ELIGIBLE = "LIVE_ELIGIBLE"
    LIMITED_LIVE_OBSERVED = "LIMITED_LIVE_OBSERVED"
    PROTECTIVE_STOP = "PROTECTIVE_STOP"


@dataclass(frozen=True)
class Evidence:
    protected_source_verified: bool
    collector_installed: bool
    current_observations: Mapping[str, bool]
    broker_ledger_reconciled: bool
    release_security_verified: bool
    required_receipts_verified: bool
    bounded_operator_authorization: bool
    canonical_execution_gate_allows: bool
    material_integrity_failure: bool = False
    noncritical_reporting_available: bool = True


@dataclass(frozen=True)
class Result:
    mode: Mode
    blockers: tuple[str, ...]
    verified_count: int
    diagnostic_only: bool = True
    authorizes_orders: bool = False


def evaluate(evidence: Evidence) -> Result:
    """Report current readiness, never change the existing canonical gate.

    All stale, missing or unverified observations must be represented as False.
    The result's LIMITED_LIVE_OBSERVED label is NOT an authorization token.
    """
    unknown = set(evidence.current_observations) - CRITICAL
    if unknown:
        raise ValueError("unknown_observation")
    verified = sum(evidence.current_observations.get(key) is True for key in CRITICAL)
    missing = sorted(key for key in CRITICAL
                     if evidence.current_observations.get(key) is not True)
    blockers = []
    if not evidence.protected_source_verified:
        blockers.append("protected_source_unverified")
    if not evidence.collector_installed:
        blockers.append("collector_missing")
    blockers.extend("observation_missing:" + key for key in missing)
    if not evidence.broker_ledger_reconciled:
        blockers.append("broker_ledger_unreconciled")
    if not evidence.release_security_verified:
        blockers.append("release_security_unverified")
    if not evidence.required_receipts_verified:
        blockers.append("required_receipts_unverified")
    if not evidence.bounded_operator_authorization:
        blockers.append("bounded_authorization_missing")
    if not evidence.canonical_execution_gate_allows:
        blockers.append("canonical_execution_gate_denied")
    if evidence.material_integrity_failure:
        blockers.append("material_integrity_failure")
        mode = Mode.PROTECTIVE_STOP
    elif not evidence.protected_source_verified or not evidence.collector_installed:
        mode = Mode.RECOVERY
    elif missing or not all((
        evidence.broker_ledger_reconciled,
        evidence.release_security_verified,
        evidence.required_receipts_verified,
    )):
        mode = Mode.VERIFYING
    elif not evidence.bounded_operator_authorization or not evidence.canonical_execution_gate_allows:
        mode = Mode.LIVE_ELIGIBLE
    else:
        mode = Mode.LIMITED_LIVE_OBSERVED
    # Reporting failure is intentionally not a blocker, and cannot override
    # a critical failure. This module is read-only and never enables orders.
    return Result(mode=mode, blockers=tuple(blockers), verified_count=verified)
