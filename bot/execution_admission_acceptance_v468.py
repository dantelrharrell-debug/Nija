"""Read-only production admission acceptance: never asserts trading authority.

Run within the actual trading process after independently audited producers
have been installed. Returns structured evidence without changing runtime
flags, submitting orders, or clearing safety controls.
"""
from __future__ import annotations

from typing import Any


def inspect_execution_admission(account_scope: str) -> dict[str, Any]:
    from bot.pretrade_independent_attestation import inspect_authenticated_attestations
    from preactivation_readiness_convergence_v16_patch import (
        _genuine_execution_marker_proof, _strict_authority_ready, _kill_switch_clear,
    )

    attestation = inspect_authenticated_attestations(account_scope)
    checks = attestation.get("checks", {})
    independently_certified = bool(checks) and all(value is True for value in checks.values())
    writer_ok, writer_reason = _strict_authority_ready()
    kill_clear, kill_reason = _kill_switch_clear()
    execution_proof_ok, execution_reason = _genuine_execution_marker_proof()
    # A pretrade certificate is not order authority. The legacy execution
    # proof is mandatory until the separate admission migration is reviewed.
    eligible_for_existing_gate = bool(
        independently_certified and writer_ok and kill_clear and execution_proof_ok
    )
    return {
        "account_scope_configured": bool(account_scope and account_scope.strip() == account_scope),
        "collector_installed": attestation.get("collector_installed") is True,
        "pretrade_checks_passed": independently_certified,
        "writer_verified": writer_ok,
        "kill_switch_clear": kill_clear,
        "execution_proof_fresh": execution_proof_ok,
        "eligible_for_existing_gate": eligible_for_existing_gate,
        "authorizes_orders": False,
        "missing_checks": [key for key, value in checks.items() if value is not True],
        "producer_status": attestation.get("producer_status"),
        "writer_reason": str(writer_reason)[:120],
        "kill_switch_reason": str(kill_reason)[:120],
        "execution_proof_reason": str(execution_reason)[:120],
    }
