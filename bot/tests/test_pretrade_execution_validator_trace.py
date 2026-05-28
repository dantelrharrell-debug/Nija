from __future__ import annotations

import os
import time
import unittest
from unittest.mock import patch

from bot.execution_authority_context import (
    ExecutionDecision,
    RuntimeAuthoritySnapshot,
    StabilityAuthoritySnapshot,
    can_execute,
    emit_pretrade_execution_validator_trace,
    execution_authority_scope,
    get_pretrade_execution_validator_traces,
)


def _decision(allowed: bool, *, first_failed_gate: str = "", reason_code: str = "allowed", reason_detail: str = "allowed") -> ExecutionDecision:
    return ExecutionDecision(
        allowed=allowed,
        reason=reason_detail,
        circuit_state="CLOSED",
        state_live_active=True,
        lease_valid=True,
        lease_generation_current=True,
        nonce_ready=True,
        heartbeat_fresh=True,
        heartbeat_stage_sufficient=True,
        broker_health_ok=True,
        circuit_breaker_closed=True,
        dispatch_enabled=True,
        stability_allowed=True,
        stability_halt_state="NORMAL",
        stability_throttle=1.0,
        stability_size_multiplier=1.0,
        stability_stress_score=0.1,
        stability_collapsed_risk_score=0.1,
        stability_reason="ok",
        first_failed_gate=first_failed_gate,
        reason_code=reason_code,
        reason_detail=reason_detail,
        lifecycle_phase="LIVE",
    )


class TestPretradeExecutionValidatorTrace(unittest.TestCase):
    def test_block_trace_contains_required_contract_fields(self) -> None:
        before = len(get_pretrade_execution_validator_traces(limit=500))
        decision = _decision(
            False,
            first_failed_gate="state.live_active",
            reason_code="state_not_live_active",
            reason_detail="state.live_active",
        )
        emit_pretrade_execution_validator_trace(
            decision,
            symbol="BTC-USD",
            side="buy",
            size=100.0,
            attempt_id=f"attempt-{time.time_ns()}",
            terminal_surface="test_block",
        )
        rows = get_pretrade_execution_validator_traces(limit=500)
        self.assertEqual(len(rows), before + 1)
        latest = rows[0]
        self.assertEqual(latest.get("decision"), "BLOCK")
        self.assertEqual(latest.get("first_failed_gate"), "state.live_active")
        self.assertEqual(latest.get("reason_code"), "state_not_live_active")
        self.assertTrue(latest.get("reason_detail"))
        self.assertEqual(latest.get("validator_version"), "v1")

    def test_allow_trace_sets_blocker_to_none(self) -> None:
        decision = _decision(True)
        emit_pretrade_execution_validator_trace(
            decision,
            symbol="ETH-USD",
            side="sell",
            size=50.0,
            attempt_id=f"attempt-{time.time_ns()}",
            terminal_surface="test_allow",
        )
        latest = get_pretrade_execution_validator_traces(limit=1)[0]
        self.assertEqual(latest.get("decision"), "ALLOW")
        self.assertIsNone(latest.get("first_failed_gate"))
        self.assertEqual(latest.get("reason_code"), "allowed")

    def test_terminal_trace_is_emitted_once_per_attempt_id(self) -> None:
        before = len(get_pretrade_execution_validator_traces(limit=500))
        decision = _decision(False, first_failed_gate="lease.valid", reason_code="lease_invalid", reason_detail="lease.valid: fence_mismatch")
        attempt = f"attempt-{time.time_ns()}"
        emit_pretrade_execution_validator_trace(decision, attempt_id=attempt, terminal_surface="test_once")
        emit_pretrade_execution_validator_trace(decision, attempt_id=attempt, terminal_surface="test_once")
        rows = get_pretrade_execution_validator_traces(limit=500)
        self.assertEqual(len(rows), before + 1)

    def test_can_execute_uses_deterministic_first_failure_order(self) -> None:
        snapshot = RuntimeAuthoritySnapshot(
            ready=True,
            authority_ready=True,
            nonce_ready=True,
            dispatch_health_ready=True,
            dispatch_enabled=True,
            kill_switch_active=False,
            coordinator_state="EXECUTING",
            runtime_state="EXECUTING",
            reason="ok",
            lifecycle_phase="LIVE",
        )
        stability = StabilityAuthoritySnapshot(
            allowed=True,
            halt_state="NORMAL",
            throttle=1.0,
            size_multiplier=1.0,
            stress_score=0.1,
            collapsed_risk_score=0.1,
            reason="ok",
        )
        env = {
            "NIJA_RUNTIME_TRADING_STATE": "WARM",
            "NIJA_WRITER_LEASE_GENERATION": "3",
            "NIJA_EXECUTION_CIRCUIT_STATE": "CLOSED",
        }
        with patch.dict(os.environ, env, clear=False), execution_authority_scope(), patch(
            "bot.execution_authority_context.runtime_authority_snapshot",
            return_value=snapshot,
        ), patch(
            "bot.execution_authority_context.assert_distributed_writer_authority",
            return_value=None,
        ), patch(
            "bot.execution_authority_context._read_current_lease_generation",
            return_value=(3, ""),
        ), patch(
            "bot.trading_state_machine._heartbeat_marker_path",
            return_value="/tmp/heartbeat_validator_trace.flag",
        ), patch(
            "bot.trading_state_machine.heartbeat_marker_is_fresh",
            return_value=True,
            create=True,
        ), patch(
            "bot.trading_state_machine._required_heartbeat_stage",
            return_value="ORDER_VERIFY",
            create=True,
        ), patch(
            "bot.trading_state_machine.heartbeat_marker_stage_is_sufficient",
            return_value=True,
            create=True,
        ), patch(
            "bot.execution_authority_context._evaluate_stability_authority",
            return_value=stability,
        ):
            decision = can_execute()

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.first_failed_gate, "state.live_active")
        self.assertEqual(decision.reason_code, "state_not_live_active")


if __name__ == "__main__":
    unittest.main()
