from __future__ import annotations

import unittest
from types import SimpleNamespace

from bot.stability_governor import StabilityGovernor, StabilityState


class TestStabilityGovernor(unittest.TestCase):
    def setUp(self) -> None:
        self.gov = StabilityGovernor()

    def _runtime_snapshot(self) -> SimpleNamespace:
        return SimpleNamespace(coordinator_state="EXECUTING")

    def _evaluate(self, **kwargs):
        base = {
            "runtime_snapshot": self._runtime_snapshot(),
            "state_live_active": True,
            "lease_valid": True,
            "lease_generation_current": True,
            "heartbeat_fresh": True,
            "heartbeat_stage_sufficient": True,
            "broker_health_ok": True,
            "dispatch_enabled": True,
            "circuit_breaker_closed": True,
        }
        base.update(kwargs)
        return self.gov.evaluate(**base)

    def test_hard_collapse_blocks_new_entries(self) -> None:
        self.gov._collect_predictors = lambda: {  # type: ignore[method-assign]
            "loss_cluster_pressure": 0.9,
            "rejection_burst": 0.0,
            "partial_fill_pressure": 0.0,
            "liquidity_stress": 0.0,
            "volatility_shock": 0.0,
            "regime_confidence_decay": 0.0,
            "global_halt_active": 1.0,
            "execution_breaker_tripped": 0.0,
            "daily_loss_pct": 0.0,
        }
        decision = self._evaluate()
        self.assertFalse(decision.allow)
        self.assertEqual(decision.stability_state, StabilityState.HALTED.value)
        self.assertEqual(decision.size_multiplier, 0.0)

    def test_monotonic_size_shrink_when_stress_worsens(self) -> None:
        self.gov._collect_predictors = lambda: {  # type: ignore[method-assign]
            "loss_cluster_pressure": 0.2,
            "rejection_burst": 0.0,
            "partial_fill_pressure": 0.0,
            "liquidity_stress": 0.0,
            "volatility_shock": 0.0,
            "regime_confidence_decay": 0.0,
            "global_halt_active": 0.0,
            "execution_breaker_tripped": 0.0,
            "daily_loss_pct": 0.0,
        }
        d1 = self._evaluate()
        self.gov._collect_predictors = lambda: {  # type: ignore[method-assign]
            "loss_cluster_pressure": 0.8,
            "rejection_burst": 0.7,
            "partial_fill_pressure": 0.6,
            "liquidity_stress": 0.4,
            "volatility_shock": 0.4,
            "regime_confidence_decay": 0.4,
            "global_halt_active": 0.0,
            "execution_breaker_tripped": 0.0,
            "daily_loss_pct": 0.0,
        }
        d2 = self._evaluate()
        self.assertLessEqual(d2.size_multiplier, d1.size_multiplier)

    def test_halted_state_uses_staged_recovery(self) -> None:
        self.gov._state = StabilityState.HALTED
        self.gov._pending_state = StabilityState.HALTED
        self.gov._pending_count = self.gov._mode_persistence
        self.gov._collect_predictors = lambda: {  # type: ignore[method-assign]
            "loss_cluster_pressure": 0.0,
            "rejection_burst": 0.0,
            "partial_fill_pressure": 0.0,
            "liquidity_stress": 0.0,
            "volatility_shock": 0.0,
            "regime_confidence_decay": 0.0,
            "global_halt_active": 0.0,
            "execution_breaker_tripped": 0.0,
            "daily_loss_pct": 0.0,
        }
        d1 = self._evaluate()
        self.assertEqual(d1.stability_state, StabilityState.RECOVERING.value)
        self.assertLessEqual(d1.size_multiplier, 0.35)

    def test_authority_ambiguity_fails_closed(self) -> None:
        self.gov._collect_predictors = lambda: {  # type: ignore[method-assign]
            "loss_cluster_pressure": 0.0,
            "rejection_burst": 0.0,
            "partial_fill_pressure": 0.0,
            "liquidity_stress": 0.0,
            "volatility_shock": 0.0,
            "regime_confidence_decay": 0.0,
            "global_halt_active": 0.0,
            "execution_breaker_tripped": 0.0,
            "daily_loss_pct": 0.0,
        }
        decision = self._evaluate(runtime_snapshot=SimpleNamespace(coordinator_state="UNKNOWN"))
        self.assertFalse(decision.allow)
        self.assertEqual(decision.reason, "authority_ambiguity_fail_closed")


if __name__ == "__main__":
    unittest.main()

