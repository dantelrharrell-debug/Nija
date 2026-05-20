from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from bot.execution_authority_context import (
    RuntimeAuthoritySnapshot,
    StabilityAuthoritySnapshot,
    can_execute,
    execution_authority_scope,
)


class TestExecutionStabilityAuthorityGate(unittest.TestCase):
    def _runtime_snapshot(self) -> RuntimeAuthoritySnapshot:
        return RuntimeAuthoritySnapshot(
            ready=True,
            authority_ready=True,
            nonce_ready=True,
            dispatch_health_ready=True,
            dispatch_enabled=True,
            kill_switch_active=False,
            coordinator_state="EXECUTING",
            runtime_state="EXECUTING",
            reason="ok",
        )

    def _stability(self, allowed: bool, reason: str = "ok") -> StabilityAuthoritySnapshot:
        return StabilityAuthoritySnapshot(
            allowed=allowed,
            halt_state="NORMAL" if allowed else "HALTED",
            throttle=0.8 if allowed else 0.0,
            size_multiplier=0.7 if allowed else 0.0,
            stress_score=0.3 if allowed else 0.95,
            collapsed_risk_score=0.35 if allowed else 0.99,
            reason=reason,
        )

    def test_can_execute_allows_when_stability_allows(self) -> None:
        env = {
            "NIJA_RUNTIME_TRADING_STATE": "LIVE_ACTIVE",
            "NIJA_WRITER_LEASE_GENERATION": "7",
            "NIJA_EXECUTION_CIRCUIT_STATE": "CLOSED",
        }
        with patch.dict(os.environ, env, clear=False), execution_authority_scope(), patch(
            "bot.execution_authority_context.runtime_authority_snapshot",
            return_value=self._runtime_snapshot(),
        ), patch(
            "bot.execution_authority_context.assert_distributed_writer_authority",
            return_value=None,
        ), patch(
            "bot.execution_authority_context._read_current_lease_generation",
            return_value=(7, ""),
        ), patch(
            "bot.trading_state_machine._heartbeat_marker_path",
            return_value="/tmp/heartbeat_verified.flag",
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
            return_value=self._stability(True),
        ):
            decision = can_execute()
        self.assertTrue(decision.allowed)
        self.assertTrue(decision.stability_allowed)

    def test_can_execute_blocks_when_stability_denies(self) -> None:
        env = {
            "NIJA_RUNTIME_TRADING_STATE": "LIVE_ACTIVE",
            "NIJA_WRITER_LEASE_GENERATION": "7",
            "NIJA_EXECUTION_CIRCUIT_STATE": "CLOSED",
        }
        with patch.dict(os.environ, env, clear=False), execution_authority_scope(), patch(
            "bot.execution_authority_context.runtime_authority_snapshot",
            return_value=self._runtime_snapshot(),
        ), patch(
            "bot.execution_authority_context.assert_distributed_writer_authority",
            return_value=None,
        ), patch(
            "bot.execution_authority_context._read_current_lease_generation",
            return_value=(7, ""),
        ), patch(
            "bot.trading_state_machine._heartbeat_marker_path",
            return_value="/tmp/heartbeat_verified.flag",
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
            return_value=self._stability(False, reason="hard_collapse_containment"),
        ):
            decision = can_execute()
        self.assertFalse(decision.allowed)
        self.assertIn("stability.allowed", decision.reason)
        self.assertIn("hard_collapse_containment", decision.reason)


if __name__ == "__main__":
    unittest.main()
