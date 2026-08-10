from __future__ import annotations

import inspect
import os
import threading
import types
import unittest
from unittest.mock import MagicMock, patch


class RuntimeFailClosedV84Tests(unittest.TestCase):
    def test_core_scan_blocks_before_broker_io_without_exact_authority(self):
        from bot import nija_core_loop as core

        loop = object.__new__(core.NijaCoreLoop)
        broker = MagicMock()
        broker.connected = True
        with patch.object(
            core,
            "_require_exact_runtime_cycle_authority",
            return_value=(False, "test_missing_writer"),
        ):
            result = loop.run_scan_phase(
                broker=broker,
                balance=100.0,
                symbols=["BTC-USD"],
            )

        self.assertEqual(result.entries_taken, 0)
        self.assertEqual(result.exits_taken, 0)
        self.assertEqual(result.entries_blocked, 1)
        self.assertIn("runtime_authority_blocked", result.errors[0])
        self.assertEqual(broker.mock_calls, [])

    def test_runtime_authority_bit_defaults_fail_closed(self):
        from bot import nija_core_loop as core

        with (
            patch.object(core, "_is_live_mode", return_value=True),
            patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop("NIJA_RUNTIME_EXECUTION_AUTHORITY", None)
            allowed, reason = core._require_exact_runtime_cycle_authority("test")

        self.assertFalse(allowed)
        self.assertEqual(reason, "runtime_execution_authority_not_granted")

    def test_forced_balance_cannot_authorize_scan_entries(self):
        from bot import nija_core_loop as core

        source = inspect.getsource(core.NijaCoreLoop.run_scan_phase)
        self.assertNotIn("NIJA_FORCE_TRADE_BALANCE", source)
        self.assertIn("_entry_capital_ready", source)
        self.assertIn("CAPITAL_ENTRY_SCAN_BLOCKED", source)

    def test_forced_entry_modes_are_disabled(self):
        from bot import nija_core_loop as core

        self.assertFalse(core.FORCED_ENTRY_MODES_ENABLED)
        self.assertEqual(core._get_relaxation_factor(10_000), 0.0)
        self.assertFalse(core._env_truthy("FORCE_TRADE", "true"))
        self.assertFalse(core._env_truthy("NIJA_FORCE_ACTIVATION", "true"))

    def test_loop_does_not_report_scan_before_authorized_scan_phase(self):
        from bot import nija_core_loop as core

        loop_source = inspect.getsource(core.run_trading_loop)
        scan_source = inspect.getsource(core.NijaCoreLoop.run_scan_phase)
        self.assertNotIn("record_scan_started", loop_source)
        self.assertEqual(scan_source.count("record_scan_started"), 1)
        self.assertIn("_require_exact_runtime_cycle_authority", scan_source)

    def test_execution_authority_requires_exact_writer_without_force_repair(self):
        from bot import execution_authority_context as authority

        writer_source = inspect.getsource(authority.assert_distributed_writer_authority)
        execute_source = inspect.getsource(authority.can_execute)
        repair_source = inspect.getsource(authority._attempt_live_dispatch_commit_repair)
        self.assertIn("_exact_process_writer", writer_source)
        self.assertNotIn("FORCE_TRADE", execute_source)
        self.assertNotIn("force_activate_bypass", repair_source)
        self.assertIn("return False", repair_source)

    def test_raw_running_transition_requires_startup_authority(self):
        from bot.bootstrap_state_machine import BootstrapState, BootstrapStateMachine

        fsm = BootstrapStateMachine()
        fsm._state = BootstrapState.THREADS_STARTING
        fsm._owner_thread_id = threading.get_ident()
        authority = types.SimpleNamespace(
            require_startup_execution_authority=lambda **_: {
                "ready": False,
                "missing": ["writer.lock.exact"],
            }
        )
        with patch.dict(
            "sys.modules",
            {"bot.execution_authority_context": authority},
        ):
            transitioned = fsm.transition(
                BootstrapState.RUNNING_SUPERVISED,
                "test must fail closed",
            )

        self.assertFalse(transitioned)
        self.assertEqual(fsm.state, BootstrapState.THREADS_STARTING)
        self.assertFalse(fsm.execution_authority)

    def test_scan_wrapper_blocks_before_base_scan(self):
        import scan_wrapper_convergence_repair_patch as wrapper

        calls: list[str] = []

        class Core:
            def run_scan_phase(self, *args, **kwargs):
                calls.append("base")
                return types.SimpleNamespace(
                    symbols_scored=1,
                    entries_taken=0,
                    entries_blocked=0,
                    exits_taken=0,
                    next_interval=15,
                )

        module = types.ModuleType("test_core_module")
        module.NijaCoreLoop = Core
        module._require_exact_runtime_cycle_authority = lambda _source: (
            False,
            "test_missing_writer",
        )
        self.assertTrue(wrapper._patch_core_loop(module))

        result = module.NijaCoreLoop().run_scan_phase()
        self.assertEqual(calls, [])
        self.assertEqual(result.entries_blocked, 1)
        self.assertIn("runtime_authority_blocked", result.errors[0])

    def test_coinbase_existing_positions_do_not_trigger_balance_probe(self):
        from bot import coinbase_position_runtime_patch as coinbase_patch

        class CoinbaseBroker:
            def __init__(self):
                self.balance_calls = 0

            def get_positions(self):
                return [{"symbol": "BTC-USD", "quantity": 0.1}]

            def get_portfolio_breakdown(self):
                self.balance_calls += 1
                return {"crypto": {"ETH": 1.0}}

        self.assertTrue(coinbase_patch._patch_coinbase_class(CoinbaseBroker))
        broker = CoinbaseBroker()
        positions = broker.get_positions()

        self.assertEqual([p["symbol"] for p in positions], ["BTC-USD"])
        self.assertEqual(broker.balance_calls, 0)

    def test_coinbase_uses_cache_before_live_balance_probe(self):
        from bot import coinbase_position_runtime_patch as coinbase_patch

        broker = types.SimpleNamespace(
            _last_raw_balances={"crypto": {"ETH": 1.0}},
            get_portfolio_breakdown=MagicMock(),
        )
        payload = coinbase_patch._call_possible_balance_methods(broker)

        self.assertEqual(payload, {"crypto": {"ETH": 1.0}})
        broker.get_portfolio_breakdown.assert_not_called()


if __name__ == "__main__":
    unittest.main()
