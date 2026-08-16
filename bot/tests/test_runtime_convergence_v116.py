from __future__ import annotations

import os
import threading
import types
import unittest
from unittest.mock import patch as mock_patch

from bot import runtime_convergence_v116_patch as v116


class _State:
    value = "LIVE_PENDING_CONFIRMATION"


class RuntimeConvergenceV116Tests(unittest.TestCase):
    def setUp(self) -> None:
        self._env = dict(os.environ)
        v116._BROKER_LOCKS.clear()

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._env)

    def test_activation_bridge_requires_canonical_readiness(self) -> None:
        module = types.ModuleType("activation_bridge_test")
        module._concrete_activation_gates_pass = lambda _tsm: (True, "")
        with mock_patch.object(v116, "_loaded", return_value=module), mock_patch.object(
            v116, "_readiness_complete", return_value=(False, ["position_sync_ready"])
        ):
            self.assertTrue(v116._patch_activation_bridge())
            ok, detail = module._concrete_activation_gates_pass(object())
        self.assertFalse(ok)
        self.assertIn("position_sync_ready", detail)

    def test_commit_activation_does_not_bypass_incomplete_readiness(self) -> None:
        calls = []

        class FakeTSM:
            def get_current_state(self):
                return _State()

            def commit_activation(self):
                calls.append("commit")
                return True

        module = types.ModuleType("trading_state_machine_test")
        module.TradingStateMachine = FakeTSM
        with mock_patch.object(v116, "_loaded", return_value=module), mock_patch.object(
            v116, "_readiness_complete", return_value=(False, ["position_sync_ready"])
        ):
            self.assertTrue(v116._patch_trading_state_machine())
            self.assertFalse(FakeTSM().commit_activation())
        self.assertEqual(calls, [])

    def test_post_core_pending_is_nonfatal_when_writer_and_core_are_healthy(self) -> None:
        module = types.ModuleType("bot_main_test")
        module._perform_post_core_activation_convergence = lambda *_a, **_k: False

        class Runtime:
            acquired = True
            lost = False
            _local_fallback = False

        class Thread:
            @staticmethod
            def is_alive():
                return True

        with mock_patch.object(v116, "_loaded", return_value=module), mock_patch.object(
            v116, "_bootstrap_running_supervised", return_value=True
        ):
            self.assertTrue(v116._patch_bot_main())
            result = module._perform_post_core_activation_convergence(Runtime(), Thread())
        self.assertTrue(result)
        self.assertEqual(os.environ.get("NIJA_RUNTIME_EXECUTION_AUTHORITY"), "0")
        self.assertEqual(os.environ.get("NIJA_EXECUTION_ACTIVE"), "false")

    def test_position_sync_duplicate_is_coalesced_after_authoritative_success(self) -> None:
        module = types.ModuleType("startup_position_sync_test")
        calls = []

        def adopt(broker, _name, _eps):
            calls.append(1)
            broker._startup_position_sync_adopted = True
            return 0

        module._adopt_broker_positions = adopt
        broker = types.SimpleNamespace(_startup_position_sync_adopted=False)
        with mock_patch.object(v116, "_loaded", return_value=module):
            self.assertTrue(v116._patch_position_sync())
            module._adopt_broker_positions(broker, "platform:kraken", None)
            module._adopt_broker_positions(broker, "platform:kraken", None)
        self.assertEqual(len(calls), 1)
        self.assertTrue(broker._startup_position_sync_adopted)
        self.assertTrue(broker._startup_position_sync_fetch_ok)

    def test_writer_state_cannot_resurrect_after_release_starts(self) -> None:
        transitions = []

        class FakeWriter:
            def __init__(self):
                self._stop = threading.Event()
                self._lost = threading.Event()

            def _set_writer_state(self, state, *args, **kwargs):
                transitions.append(str(getattr(state, "value", state)))

        module = types.ModuleType("entrypoint_writer_test")
        module.EntrypointWriterAuthority = FakeWriter
        writer = FakeWriter()
        writer._stop.set()
        active = types.SimpleNamespace(value="ACTIVE")
        lost = types.SimpleNamespace(value="LOST")
        with mock_patch.object(v116, "_loaded", return_value=module):
            self.assertTrue(v116._patch_writer_state())
            writer._set_writer_state(active)
            writer._set_writer_state(lost)
        self.assertEqual(transitions, ["LOST"])

    def test_user_trading_eligibility_requires_position_sync(self) -> None:
        module = types.ModuleType("kraken_user_test")

        def reconcile(manager, user_id, broker_type, _broker):
            manager._user_metadata.setdefault(user_id, {}).setdefault("brokers", {})[broker_type] = True

        module._reconcile_post_connect = reconcile
        manager = types.SimpleNamespace(_user_metadata={}, _capital_blocked_users={})
        broker = types.SimpleNamespace(connected=True, _startup_position_sync_adopted=False)
        with mock_patch.object(v116, "_loaded", return_value=module):
            self.assertTrue(v116._patch_kraken_user_eligibility())
            module._reconcile_post_connect(manager, "u1", "kraken", broker)
        self.assertFalse(manager._user_metadata["u1"]["brokers"]["kraken"])
        self.assertEqual(manager._capital_blocked_users[("u1", "kraken")], "position_sync_incomplete")


if __name__ == "__main__":
    unittest.main()
