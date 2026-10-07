from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import ANY, Mock, patch

from bot.kill_switch import KillSwitch


MODULE_PATH = Path(__file__).resolve().parents[1] / "bot" / "runtime_drawdown_stop_provenance_v414_patch.py"


class DrawdownRecoveryRetryV414Tests(unittest.TestCase):
    def setUp(self) -> None:
        spec = importlib.util.spec_from_file_location("v414_retry_under_test", MODULE_PATH)
        assert spec is not None and spec.loader is not None
        self.v414 = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.v414)

        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.stop_record = {
            "is_active": True,
            "source": "FILE_SYSTEM",
            "reason": "Kill switch file detected",
            "timestamp": "2026-10-06T18:32:01.539636+00:00",
        }
        self.redis_value = json.dumps(self.stop_record)
        self.redis_clear_ok = True
        redis = Mock()
        redis.get.side_effect = lambda key: self.redis_value
        redis.set.side_effect = self._redis_set
        redis_patch = patch.object(KillSwitch, "_redis_client", return_value=redis)
        redis_patch.start()
        self.addCleanup(redis_patch.stop)

        self.state = Mock()
        self.state.get_current_state.return_value = "EMERGENCY_STOP"
        self.readiness = {"execution_ready": False, "capital_ready": False}
        self.orders = Mock()
        self.ca = Mock()
        self.ca.is_fresh.return_value = False
        self.ca_total = 600.0
        self.holding_value = 176.0
        self.position_proof = True
        self.cb = types.SimpleNamespace(
            _current_equity=0.0, _peak_equity=600.0,
            _config=types.SimpleNamespace(halt_pct=20.0),
        )
        self.v409 = types.ModuleType("bot.runtime_drawdown_portfolio_equity_v409_patch")
        self.v409._LOCK = threading.RLock()
        self.v409._capital_authority_matches = lambda raw: (
            abs(raw - self.ca_total) <= max(1.0, self.ca_total * 0.02), self.ca_total,
        )
        self.v409._authoritative_coinbase_holding_value = Mock(
            side_effect=lambda: (self.position_proof, self.holding_value, ("ETH-USD",), "test_position_proof"),
        )
        self.v409._reclassify_false_halt_if_proven = Mock(return_value=False)
        self.v409._recover_exact_false_drawdown_stop = lambda: False
        self.v409.install = self._install_v409
        modules = {
            "bot.runtime_drawdown_portfolio_equity_v409_patch": self.v409,
            "bot.capital_authority": types.SimpleNamespace(get_capital_authority=lambda: self.ca),
            "bot.global_drawdown_circuit_breaker": types.SimpleNamespace(get_global_drawdown_cb=lambda: self.cb),
            "bot.kill_switch": types.SimpleNamespace(get_kill_switch=lambda: self.ks),
            "bot.kill_switch_persistence_provenance_v143_patch": types.SimpleNamespace(
                _causal_activation_from_status=self._causal_activation,
            ),
            "bot.trading_state_machine": types.SimpleNamespace(
                get_state_machine=lambda: self.state,
                TradingState=types.SimpleNamespace(EMERGENCY_STOP="EMERGENCY_STOP", OFF="OFF"),
            ),
            "bot.readiness_table": types.SimpleNamespace(snapshot=lambda: dict(self.readiness)),
            "bot.execution_engine": self.orders,
        }
        module_patch = patch.dict(sys.modules, modules)
        module_patch.start()
        self.addCleanup(module_patch.stop)
        env_patch = patch.dict("os.environ", {"NIJA_KILL_SWITCH": "false"})
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.ks = KillSwitch(base_path=temp.name)
        self.ks.deactivate = Mock(wraps=self.ks.deactivate)
        self.addCleanup(self._stop_worker)

    def _stop_worker(self) -> None:
        self.v414._RECOVERY_COMPLETE.set()
        worker = self.v414._RETRY_THREAD
        if worker is not None:
            worker.join(timeout=1.0)
            self.assertFalse(worker.is_alive())

    def _redis_set(self, key: str, value: str) -> bool:
        if self.redis_clear_ok:
            self.redis_value = value
        return self.redis_clear_ok

    def _install_v409(self) -> bool:
        with self.v409._LOCK:
            self.v409._recover_exact_false_drawdown_stop()
        return True

    def _causal_activation(self, status: dict) -> tuple[str, str]:
        latest = status["recent_history"][-1]
        if latest["source"] == "FILE_SYSTEM":
            return "v143_provenance_blocked:origin_unavailable", "PROVENANCE_BOUNDARY"
        return latest["reason"], latest["source"]

    def _hydrate(self, corrected_breaker: bool = False) -> None:
        self.ca.is_fresh.return_value = True
        self.cb._current_equity = self.ca_total + (self.holding_value if corrected_breaker else 0.0)

    def _assert_stopped(self) -> None:
        self.assertTrue(self.ks.is_active())
        self.assertTrue(Path(self.ks._kill_file).exists())
        self.assertTrue(json.loads(self.redis_value)["is_active"])
        self.assertFalse(self.v414._RECOVERY_COMPLETE.is_set())

    def test_startup_without_capital_proof_leaves_stop_and_starts_only_one_worker(self) -> None:
        self.assertTrue(self.v414.install())
        worker = self.v414._RETRY_THREAD
        self.assertTrue(worker.is_alive())
        self.assertTrue(worker.daemon)
        self.assertTrue(self.v414.install())
        self.assertIs(self.v414._RETRY_THREAD, worker)
        self.ks.deactivate.assert_not_called()
        self.v409._authoritative_coinbase_holding_value.assert_not_called()
        self._assert_stopped()

    def test_worker_waits_for_hydration_then_recovers_and_terminates(self) -> None:
        self.assertTrue(self.v414._install_v409_guarded_recovery())
        guarded_recovery = Mock(wraps=self.v409._recover_exact_false_drawdown_stop)
        self.v409._recover_exact_false_drawdown_stop = guarded_recovery
        waits = Mock()

        def wait(interval: float) -> bool:
            if waits.call_count == 1:
                return False
            if waits.call_count > 2:
                return True
            guarded_recovery.assert_not_called()
            self._hydrate(corrected_breaker=True)
            return False

        waits.side_effect = wait
        with patch.object(self.v414._RECOVERY_COMPLETE, "wait", waits):
            with self.assertLogs(self.v414.LOGGER, level="CRITICAL") as logs:
                worker = threading.Thread(target=self.v414._retry_recovery, daemon=True)
                worker.start()
                worker.join(timeout=1.0)
        self.assertFalse(worker.is_alive())
        self.assertEqual(waits.call_count, 2)
        guarded_recovery.assert_called_once()
        self.ks.deactivate.assert_called_once()
        self.assertTrue(self.v414._RECOVERY_COMPLETE.is_set())
        self.assertFalse(self.ks.is_active())
        self.assertFalse(Path(self.ks._kill_file).exists())
        self.assertFalse(json.loads(self.redis_value)["is_active"])
        self.assertTrue(any("DRAWDOWN_V414_FALSE_KILL_SWITCH_CLEARED" in line for line in logs.output))
        self.assertEqual(self.cb._config.halt_pct, 20.0)
        self.assertEqual(self.cb._peak_equity, 600.0)
        self.assertEqual(self.readiness, {"execution_ready": False, "capital_ready": False})
        self.state.transition_to.assert_called_once_with("OFF", ANY)
        self.assertEqual(self.orders.mock_calls, [])
        self.assertTrue(self.v414.install())
        self.assertIsNone(self.v414._RETRY_THREAD)
        self.ks.deactivate.assert_called_once()

    def test_recovery_accepts_raw_breaker_series(self) -> None:
        self._hydrate()
        self.assertTrue(self.v414._install_v409_guarded_recovery())
        self.assertTrue(self.v409._recover_exact_false_drawdown_stop())
        self.assertFalse(self.ks.is_active())

    def test_manual_and_unrelated_filesystem_stops_never_clear(self) -> None:
        self._hydrate()
        self.assertTrue(self.v414._install_v409_guarded_recovery())
        for source, reason, timestamp in (
            ("MANUAL", "Owner emergency stop", self.stop_record["timestamp"]),
            ("ENV", "Deployment kill switch", self.stop_record["timestamp"]),
            ("FILE_SYSTEM", "Kill switch file detected", "2026-10-06T18:32:01.539637+00:00"),
            ("FILE_SYSTEM", "Owner emergency stop", self.stop_record["timestamp"]),
        ):
            with self.subTest(source=source, reason=reason):
                self.ks._activation_history = [{"source": source, "reason": reason, "timestamp": timestamp}]
                self.assertFalse(self.v409._recover_exact_false_drawdown_stop())
                self.ks.deactivate.assert_not_called()
                self._assert_stopped()

    def test_durable_clear_failure_stays_active_and_can_retry(self) -> None:
        self._hydrate()
        self.redis_clear_ok = False
        self.v409._reclassify_false_halt_if_proven.side_effect = (
            lambda cb, equity: setattr(cb, "_current_equity", equity)
        )
        self.assertTrue(self.v414._install_v409_guarded_recovery())
        self.assertFalse(self.v409._recover_exact_false_drawdown_stop())
        self._assert_stopped()
        self.redis_clear_ok = True
        self.assertTrue(self.v409._recover_exact_false_drawdown_stop())
        self.assertFalse(self.ks.is_active())
        self.assertEqual(self.ks.deactivate.call_count, 2)

    def test_deactivate_success_without_inactive_local_stop_is_not_recovery(self) -> None:
        self._hydrate()
        self.ks.deactivate = Mock(return_value=True)
        self.assertTrue(self.v414._install_v409_guarded_recovery())
        self.assertFalse(self.v409._recover_exact_false_drawdown_stop())
        self._assert_stopped()

    def test_worker_retries_redis_failure_and_exits_on_confirmed_success(self) -> None:
        self._hydrate()
        self.redis_clear_ok = False
        self.assertTrue(self.v414._install_v409_guarded_recovery())
        waits = Mock()

        def wait(interval: float) -> bool:
            if waits.call_count == 1:
                return False
            if waits.call_count == 2:
                self._assert_stopped()
                self.ks.deactivate.assert_called_once()
                self.redis_clear_ok = True
                return False
            return True

        waits.side_effect = wait
        with patch.object(self.v414._RECOVERY_COMPLETE, "wait", waits):
            self.v414._retry_recovery()
        self.assertEqual(waits.call_count, 2)
        self.assertEqual(self.ks.deactivate.call_count, 2)
        self.assertTrue(self.v414._RECOVERY_COMPLETE.is_set())
        self.assertFalse(self.ks.is_active())

    def test_startup_success_does_not_start_retry_worker(self) -> None:
        self._hydrate()
        self.assertTrue(self.v414.install())
        self.assertIsNone(self.v414._RETRY_THREAD)
        self.ks.deactivate.assert_called_once()
        self.assertTrue(self.v414.install())
        self.ks.deactivate.assert_called_once()

    def test_worker_serializes_recovery_with_v409_installation_lock(self) -> None:
        self._hydrate()
        recovery = Mock(return_value=True)
        self.v409._recover_exact_false_drawdown_stop = recovery
        lock = Mock()
        lock.__enter__ = Mock()
        lock.__exit__ = Mock()
        self.v409._LOCK = lock
        with patch.object(self.v414._RECOVERY_COMPLETE, "wait", return_value=False):
            self.v414._retry_recovery()
        lock.__enter__.assert_called_once()
        lock.__exit__.assert_called_once()
        recovery.assert_called_once()
        self.assertTrue(self.v414._RECOVERY_COMPLETE.is_set())

    def test_missing_positions_stale_capital_or_contradictory_equity_fail_closed(self) -> None:
        self._hydrate()
        self.assertTrue(self.v414._install_v409_guarded_recovery())
        for fresh, positions, equity, holding in (
            (False, True, 600.0, 176.0),
            (True, False, 600.0, 176.0),
            (True, True, 400.0, 176.0),
            (True, True, 600.0, float("inf")),
            (True, True, 600.0, -176.0),
            (True, True, 600.0, 0.0),
            (True, True, 600.0, 20.0),
        ):
            with self.subTest(fresh=fresh, positions=positions, equity=equity, holding=holding):
                self.ca.is_fresh.return_value = fresh
                self.position_proof = positions
                self.cb._current_equity = equity
                self.holding_value = holding
                self.assertFalse(self.v409._recover_exact_false_drawdown_stop())
                self.ks.deactivate.assert_not_called()
                self._assert_stopped()


if __name__ == "__main__":
    unittest.main()
