"""Fail-closed recovery-mode classification; does not authorize trading.

This is a read-only diagnostic state machine. It deliberately separates
recoverability/observability from executable trading authority.
"""
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class RecoveryDecision:
    state: str
    allow_readonly_checks: bool
    allow_new_orders: bool
    reasons: tuple[str, ...]


def classify_recovery(readiness: Mapping[str, bool], *,
                      kill_switch_clear: bool,
                      startup_attempts_reconciled: bool,
                      protective_exits_verified: bool,
                      ledger_reconciled: bool) -> RecoveryDecision:
    """Classify startup without manufacturing execution evidence.

    A stale execution marker permits read-only checks but never new orders.
    An incomplete recovery path always fails closed. The existing canonical
    runtime gate remains independently authoritative.
    """
    required = ("broker_connected", "authority_ready", "capital_ready",
                "risk_ready", "strategy_ready", "nonce_ready",
                "position_sync_ready", "execution_ready")
    reasons = tuple(
        [name for name in required if readiness.get(name) is not True]
        + (["kill_switch"] if not kill_switch_clear else [])
        + (["startup_attempts"] if not startup_attempts_reconciled else [])
        + (["protective_exits"] if not protective_exits_verified else [])
        + (["ledger"] if not ledger_reconciled else [])
    )
    if not reasons:
        # This helper is *never* an execution-authorization source.
        return RecoveryDecision("VERIFICATION_COMPLETE", True, False, ())
    if readiness.get("broker_connected") is True:
        return RecoveryDecision("READ_ONLY_RECOVERY", True, False, reasons)
    return RecoveryDecision("DISCONNECTED", False, False, reasons)
