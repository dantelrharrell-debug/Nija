from __future__ import annotations

import os
import sys
import types
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
            lifecycle_phase="LIVE",
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

    def test_can_execute_blocks_when_stability_halt_gate_unavailable(self) -> None:
        env = {
            "NIJA_RUNTIME_TRADING_STATE": "LIVE_ACTIVE",
            "NIJA_WRITER_LEASE_GENERATION": "7",
            "NIJA_EXECUTION_CIRCUIT_STATE": "CLOSED",
            "NIJA_STABILITY_GOVERNOR_HALT_ENABLED": "true",
        }
        fake_stability_module = types.ModuleType("bot.stability_governor")

        def _raise_stability_unavailable():
            raise RuntimeError("stability dependency unavailable")

        fake_stability_module.get_stability_governor = _raise_stability_unavailable  # type: ignore[attr-defined]
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
        ), patch(
            "bot.execution_authority_context._env_truthy",
            side_effect=lambda name: {
                "NIJA_STABILITY_GOVERNOR_HALT_ENABLED": True,
                "NIJA_KRAKEN_MARGIN_ENABLED": False,
                "NIJA_EXECUTION_RECOVERY_APPROVED": False,
            }.get(name, False),
        ), patch.dict(
            sys.modules,
            {
                "bot.stability_governor": fake_stability_module,
                "stability_governor": fake_stability_module,
            },
            clear=False,
        ):
            decision = can_execute()
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.first_failed_gate, "stability.allowed")
        self.assertIn("stability_halt_gate_unavailable", decision.reason_detail)

    def test_can_execute_blocks_when_margin_gate_unavailable(self) -> None:
        env = {
            "NIJA_RUNTIME_TRADING_STATE": "LIVE_ACTIVE",
            "NIJA_WRITER_LEASE_GENERATION": "7",
            "NIJA_EXECUTION_CIRCUIT_STATE": "CLOSED",
            "NIJA_KRAKEN_MARGIN_ENABLED": "true",
        }
        fake_margin_module = types.ModuleType("bot.kraken_margin_engine")

        def _raise_margin_unavailable():
            raise RuntimeError("margin dependency unavailable")

        fake_margin_module.get_margin_engine = _raise_margin_unavailable  # type: ignore[attr-defined]
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
        ), patch(
            "bot.execution_authority_context._env_truthy",
            side_effect=lambda name: {
                "NIJA_STABILITY_GOVERNOR_HALT_ENABLED": False,
                "NIJA_KRAKEN_MARGIN_ENABLED": True,
                "NIJA_EXECUTION_RECOVERY_APPROVED": False,
            }.get(name, False),
        ), patch.dict(
            sys.modules,
            {
                "bot.kraken_margin_engine": fake_margin_module,
                "kraken_margin_engine": fake_margin_module,
            },
            clear=False,
        ):
            decision = can_execute()
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.first_failed_gate, "margin.critical_ok")
        self.assertIn("margin_health_gate_unavailable", decision.reason_detail)


if __name__ == "__main__":
    unittest.main()
