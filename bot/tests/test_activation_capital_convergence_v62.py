from __future__ import annotations

import importlib
import os
import sys
import types
import unittest
from enum import Enum


class _State(Enum):
    RUNNING_SUPERVISED = "RUNNING_SUPERVISED"
    READY = "READY"


class ActivationCapitalConvergenceV62Tests(unittest.TestCase):
    def setUp(self):
        self.mod = importlib.import_module("bot.activation_capital_convergence_v62_patch")
        self.saved_modules = {
            name: sys.modules.get(name)
            for name in (
                "bot.bootstrap_state_machine",
                "bot.capital_flow_state_machine",
                "bot.capital_authority",
                "bot.readiness_table",
            )
        }
        self.saved_env = {
            key: os.environ.get(key)
            for key in ("CAPITAL_SYSTEM_READY", "NIJA_CAPITAL_READY")
        }

    def tearDown(self):
        for name, module in self.saved_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        for key, value in self.saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _install_canonical_fakes(self, *, stale: bool = False, capital: float = 300.0):
        bootstrap = types.ModuleType("bot.bootstrap_state_machine")
        bootstrap.get_bootstrap_fsm = lambda: types.SimpleNamespace(
            state=_State.RUNNING_SUPERVISED
        )
        sys.modules[bootstrap.__name__] = bootstrap

        capital_fsm = types.ModuleType("bot.capital_flow_state_machine")
        capital_fsm.get_capital_bootstrap_fsm = lambda: types.SimpleNamespace(
            state=_State.READY
        )
        sys.modules[capital_fsm.__name__] = capital_fsm

        authority = types.SimpleNamespace(
            is_hydrated=True,
            get_real_capital=lambda: capital,
            get_snapshot_publication_status=lambda: types.SimpleNamespace(stale=stale),
        )
        authority_mod = types.ModuleType("bot.capital_authority")
        authority_mod.get_capital_authority = lambda: authority
        sys.modules[authority_mod.__name__] = authority_mod

        readiness = types.ModuleType("bot.readiness_table")
        readiness.snapshot_with_version = lambda: (
            9,
            {
                "broker_connected": True,
                "balance_hydrated": True,
                "capital_ready": True,
            },
        )
        sys.modules[readiness.__name__] = readiness

    def test_sync_copies_canonical_running_capital_before_compatibility_proof(self):
        self._install_canonical_fakes(stale=False, capital=300.17)
        calls = {}

        class Coordinator:
            def record_bootstrap_state(self, state):
                calls["bootstrap"] = state

            def record_capital_state(self, **kwargs):
                calls["capital"] = kwargs

            def record_readiness(self, **kwargs):
                calls["readiness"] = kwargs

        self.mod._sync_coordinator_inputs(Coordinator())
        self.assertEqual(calls["bootstrap"], "RUNNING_SUPERVISED")
        self.assertEqual(calls["capital"]["state"], "READY")
        self.assertTrue(calls["capital"]["hydrated"])
        self.assertEqual(calls["capital"]["balance"], 300.17)
        self.assertFalse(calls["capital"]["stale"])
        self.assertTrue(calls["readiness"]["value"])

    def test_canonical_capital_observer_rejects_stale_snapshot_even_with_env_handoff(self):
        self._install_canonical_fakes(stale=True, capital=300.17)
        os.environ["CAPITAL_SYSTEM_READY"] = "1"
        os.environ["NIJA_CAPITAL_READY"] = "1"
        self.assertFalse(self.mod._canonical_capital_ready())

    def test_canonical_capital_observer_accepts_fresh_positive_hydrated_snapshot(self):
        self._install_canonical_fakes(stale=False, capital=155.21)
        self.assertTrue(self.mod._canonical_capital_ready())

    def test_canonical_capital_observer_rejects_zero_capital(self):
        self._install_canonical_fakes(stale=False, capital=0.0)
        self.assertFalse(self.mod._canonical_capital_ready())

    def test_force_activation_wrapper_syncs_before_original_proof(self):
        self._install_canonical_fakes(stale=False, capital=300.17)
        fake = types.ModuleType("startup_coordinator_v62_fake")
        events = []

        class StartupCoordinator:
            def record_bootstrap_state(self, state):
                events.append(("bootstrap", state))

            def record_capital_state(self, **kwargs):
                events.append(("capital", kwargs["state"]))

            def record_readiness(self, **kwargs):
                events.append(("readiness", kwargs["value"]))

            def force_activate_bypass(self, reason):
                events.append(("original", reason))
                return 77

        fake.StartupCoordinator = StartupCoordinator
        self.assertTrue(self.mod._patch_startup_coordinator(fake))
        result = StartupCoordinator().force_activate_bypass("bridge")
        self.assertEqual(result, 77)
        self.assertEqual(events[-1], ("original", "bridge"))
        self.assertIn(("capital", "READY"), events[:-1])


if __name__ == "__main__":
    unittest.main()
