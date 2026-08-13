from __future__ import annotations

import os
import sys
import types
import unittest

from bot import live_capital_freshness_v64_patch as v64


class _Authority:
    def __init__(
        self,
        *,
        hydrated: bool = True,
        real: float = 100.0,
        registered: int = 1,
        fresh: bool = True,
        complete: bool = True,
    ) -> None:
        self.is_hydrated = hydrated
        self._real = real
        self.registered_broker_count = registered
        self.valid_broker_count = registered if real > 0 else 0
        self._fresh = fresh
        self._complete = complete
        self.freshness_calls: list[float] = []

    @property
    def total_capital(self) -> float:
        return self._real

    def get_real_capital(self) -> float:
        return self._real

    def get_total_capital(self) -> float:
        return self._real

    def get_usable_capital(self) -> float:
        return max(0.0, self._real * 0.98)

    def is_fresh(self, ttl_s: float = 90.0) -> bool:
        self.freshness_calls.append(float(ttl_s))
        return self._fresh

    def is_brokers_complete(self) -> bool:
        return self._complete


class LiveCapitalFreshnessV64Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.saved_env = {
            key: os.environ.get(key)
            for key in (
                "LIVE_CAPITAL_VERIFIED",
                "NIJA_CAPITAL_FRESHNESS_TTL_S",
            )
        }
        os.environ["LIVE_CAPITAL_VERIFIED"] = "true"
        os.environ.pop("NIJA_CAPITAL_FRESHNESS_TTL_S", None)
        self.saved_modules = {
            name: sys.modules.get(name)
            for name in (
                "bot.capital_authority",
                "capital_authority",
            )
        }

    def tearDown(self) -> None:
        for key, value in self.saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        for name, module in self.saved_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def _install_authority(self, authority: _Authority) -> None:
        module = types.ModuleType("bot.capital_authority")
        module.get_capital_authority = lambda: authority
        sys.modules["bot.capital_authority"] = module
        sys.modules["capital_authority"] = module

    def test_canonical_status_uses_90_second_default_ttl(self):
        authority = _Authority(fresh=True)
        self._install_authority(authority)

        ready, reason, details = v64._canonical_capital_status()

        self.assertTrue(ready)
        self.assertEqual(reason, "capital_fresh_funded_complete")
        self.assertEqual(details["ttl_s"], 90.0)
        self.assertEqual(authority.freshness_calls, [90.0])

    def test_canonical_status_honors_configured_ttl(self):
        os.environ["NIJA_CAPITAL_FRESHNESS_TTL_S"] = "75"
        authority = _Authority(fresh=True)
        self._install_authority(authority)

        ready, _, details = v64._canonical_capital_status()

        self.assertTrue(ready)
        self.assertEqual(details["ttl_s"], 75.0)
        self.assertEqual(authority.freshness_calls, [75.0])

    def test_v16_snapshot_replaces_legacy_60_second_stale_result(self):
        authority = _Authority(fresh=True)
        self._install_authority(authority)
        module = types.ModuleType("preactivation_readiness_convergence_v16_patch")
        module._capital_snapshot = lambda: {
            "hydrated": True,
            "stale": True,
            "real": 100.0,
            "registered": 1,
        }

        self.assertTrue(v64._patch_v16(module))
        result = module._capital_snapshot()

        self.assertFalse(result["stale"])
        self.assertEqual(result["v64_freshness_ttl_s"], 90.0)
        self.assertEqual(authority.freshness_calls, [90.0])

    def test_live_compat_gate_rejects_stale_capital_despite_live_mode_flag(self):
        authority = _Authority(fresh=False)
        self._install_authority(authority)
        module = types.ModuleType("bot.live_active_execution_gate_final_patch")
        module._capital_ready = lambda: True

        self.assertTrue(v64._patch_live_active_gate(module))

        self.assertFalse(module._capital_ready())
        self.assertEqual(authority.freshness_calls, [90.0])

    def test_live_compat_gate_accepts_fresh_funded_complete_authority(self):
        authority = _Authority(fresh=True, real=250.0, registered=2, complete=True)
        self._install_authority(authority)
        module = types.ModuleType("bot.live_active_execution_gate_final_patch")
        module._capital_ready = lambda: False

        self.assertTrue(v64._patch_live_active_gate(module))

        self.assertTrue(module._capital_ready())

    def test_pipeline_blocks_new_entry_when_capital_is_stale(self):
        authority = _Authority(fresh=False)
        self._install_authority(authority)
        module = types.ModuleType("bot.execution_pipeline")

        class Pipeline:
            def _enforce_execution_gate(self, request, t_start):
                return None

            def _deny(self, request, t_start, reason):
                return {"blocked": True, "reason": reason}

        module.ExecutionPipeline = Pipeline
        self.assertTrue(v64._patch_execution_pipeline(module))

        pipeline = Pipeline()
        request = types.SimpleNamespace(
            intent_type="entry",
            reduce_only=False,
            symbol="BTC-USD",
            side="buy",
        )
        result = pipeline._enforce_execution_gate(request, 0.0)

        self.assertEqual(
            result,
            {"blocked": True, "reason": "Capital freshness deny: capital_snapshot_stale"},
        )

    def test_pipeline_preserves_reduce_and_exit_during_stale_capital(self):
        authority = _Authority(fresh=False)
        self._install_authority(authority)
        module = types.ModuleType("bot.execution_pipeline")

        class Pipeline:
            def _enforce_execution_gate(self, request, t_start):
                return None

            def _deny(self, request, t_start, reason):
                return {"blocked": True, "reason": reason}

        module.ExecutionPipeline = Pipeline
        self.assertTrue(v64._patch_execution_pipeline(module))
        pipeline = Pipeline()

        for intent in ("reduce", "exit"):
            with self.subTest(intent=intent):
                request = types.SimpleNamespace(
                    intent_type=intent,
                    reduce_only=True,
                    symbol="BTC-USD",
                    side="sell",
                )
                self.assertIsNone(pipeline._enforce_execution_gate(request, 0.0))

    def test_pipeline_fails_closed_when_capital_authority_is_unavailable(self):
        sys.modules.pop("bot.capital_authority", None)
        sys.modules.pop("capital_authority", None)
        module = types.ModuleType("bot.execution_pipeline")

        class Pipeline:
            def _enforce_execution_gate(self, request, t_start):
                return None

            def _deny(self, request, t_start, reason):
                return reason

        module.ExecutionPipeline = Pipeline
        self.assertTrue(v64._patch_execution_pipeline(module))
        request = types.SimpleNamespace(
            intent_type="entry",
            reduce_only=False,
            symbol="ETH-USD",
            side="buy",
        )

        # Force the import path itself to fail closed rather than accidentally
        # resolving a previously imported singleton from another test.
        original = v64._capital_authority
        try:
            v64._capital_authority = lambda: None
            result = Pipeline()._enforce_execution_gate(request, 0.0)
        finally:
            v64._capital_authority = original

        self.assertEqual(result, "Capital freshness deny: capital_authority_unavailable")


if __name__ == "__main__":
    unittest.main()
