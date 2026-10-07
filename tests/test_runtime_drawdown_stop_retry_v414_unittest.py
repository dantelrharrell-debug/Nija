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
            "timestamp": "2026-10-07T00:39:22.506451+00:00",
            "schema": 1,
        }
        self.redis_value = json.dumps(self.stop_record)
        self.redis_clear_ok = True
        self.redis_migrate_ok = True
        self.redis_verify_ok = True
        redis = Mock()
        redis.get.side_effect = lambda key: self.redis_value
        redis.set.side_effect = self._redis_set
        redis.eval.side_effect = self._redis_eval
        self.redis = redis
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
        env_patch = patch.dict("os.environ", {
            "NIJA_KILL_SWITCH": "false",
            self.v414._LEGACY_ATTESTATION_ENV: self.v414._INCIDENT_20261006_ID,
        })
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

    def _redis_eval(self, script: str, numkeys: int, key: str, expected: str, value: str | None = None) -> int | str:
        if value in (None, "replay", "activation"):
            current = json.loads(self.redis_value)
            if value != "activation" and current["is_active"]:
                return self.redis_value
            incoming = json.loads(expected)
            if current.get("is_active"):
                incoming["superseding_stop"] = True
                if current.get("schema") == 2:
                    for field in ("origin_source", "origin_reason", "origin_timestamp", "origin_date", "incident_id"):
                        if field in current:
                            incoming[field] = current[field]
                        else:
                            incoming.pop(field, None)
            if current.get("legacy_v414_migration_consumed"):
                incoming["legacy_v414_migration_consumed"] = True
            self.redis_value = json.dumps(incoming)
            return self.redis_value
        if expected != self.redis_value:
            return 0
        replacement = json.loads(value)
        ok = self.redis_clear_ok if replacement["is_active"] is False else self.redis_migrate_ok
        if not ok:
            return 0
        if self.redis_verify_ok:
            self.redis_value = value
        return 1

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
            ("UI", "Owner emergency stop", self.stop_record["timestamp"]),
            ("CLI", "Operator stop", self.stop_record["timestamp"]),
            ("AUTO_TRIGGER", "Daily loss limit exceeded", self.stop_record["timestamp"]),
            ("AUTO_TRIGGER", "Weekly loss limit exceeded", self.stop_record["timestamp"]),
            ("AUTO_TRIGGER", "API instability", self.stop_record["timestamp"]),
            ("AUTO_TRIGGER", "Liquidation panic", self.stop_record["timestamp"]),
            ("UNKNOWN", "Unknown stop", self.stop_record["timestamp"]),
            ("FILE_SYSTEM", "Owner emergency stop", self.stop_record["timestamp"]),
        ):
            with self.subTest(source=source, reason=reason):
                self.ks._activation_history = [{"source": source, "reason": reason, "timestamp": timestamp}]
                self.assertFalse(self.v409._recover_exact_false_drawdown_stop())
                self.ks.deactivate.assert_not_called()
                self._assert_stopped()

    def test_generic_stop_without_incident_attestation_is_unknown_and_never_migrates(self) -> None:
        self._hydrate()
        self.assertTrue(self.v414._install_v409_guarded_recovery())
        with patch.dict("os.environ", {self.v414._LEGACY_ATTESTATION_ENV: ""}):
            self.assertFalse(self.v409._recover_exact_false_drawdown_stop())
        self.redis.eval.assert_not_called()
        self.ks.deactivate.assert_not_called()
        self._assert_stopped()

    def test_migration_write_or_verification_failure_never_deactivates(self) -> None:
        self._hydrate()
        self.assertTrue(self.v414._install_v409_guarded_recovery())
        for write_ok, verify_ok in ((False, True), (True, False)):
            with self.subTest(write_ok=write_ok, verify_ok=verify_ok):
                self.redis_migrate_ok = write_ok
                self.redis_verify_ok = verify_ok
                self.assertFalse(self.v409._recover_exact_false_drawdown_stop())
                self.ks.deactivate.assert_not_called()
                self._assert_stopped()

    def test_durable_migration_survives_restart_without_attestation_or_replay_identity(self) -> None:
        self._hydrate()
        self.redis_clear_ok = False
        self.assertTrue(self.v414._install_v409_guarded_recovery())
        self.assertFalse(self.v409._recover_exact_false_drawdown_stop())
        migrated = json.loads(self.redis_value)
        self.assertEqual(migrated["incident_id"], self.v414._INCIDENT_20261006_ID)
        self.assertEqual(migrated["origin_reason"], self.v414._INCIDENT_20261006_CAUSAL_REASON)
        self.assertIsNone(migrated["origin_timestamp"])
        self.assertEqual(migrated["origin_date"], "2026-10-06")
        self.ks = KillSwitch(base_path=self.ks._base_path)
        self.ks.deactivate = Mock(wraps=self.ks.deactivate)
        self.assertNotEqual(self.ks._activation_history[-1]["timestamp"], self.stop_record["timestamp"])
        self.assertEqual(json.loads(self.redis_value), migrated)
        self.redis_clear_ok = True
        with patch.dict("os.environ", {self.v414._LEGACY_ATTESTATION_ENV: ""}):
            self.assertTrue(self.v409._recover_exact_false_drawdown_stop())
        self.ks.deactivate.assert_called_once()
        self.assertTrue(self.v414._RECOVERY_COMPLETE.is_set())
        inactive = json.loads(self.redis_value)
        for field in ("origin_source", "origin_reason", "origin_timestamp", "incident_id"):
            self.assertEqual(inactive[field], migrated[field])
        restarted = KillSwitch(base_path=self.ks._base_path)
        self.assertFalse(restarted.is_active())
        self.assertFalse(Path(restarted._kill_file).exists())

    def test_new_durable_risk_stop_during_migration_cannot_be_overwritten(self) -> None:
        self._hydrate()
        self.assertTrue(self.v414._install_v409_guarded_recovery())
        risk = dict(self.stop_record, source="MANUAL", reason="Operator emergency stop")

        def race(*args: object) -> int:
            self.redis_value = json.dumps(risk)
            return 0

        self.redis.eval.side_effect = race
        self.assertFalse(self.v409._recover_exact_false_drawdown_stop())
        self.ks.deactivate.assert_not_called()
        self.assertEqual(json.loads(self.redis_value), risk)
        self._assert_stopped()

    def test_new_local_stop_after_proof_blocks_normal_deactivation_even_if_redis_write_fails(self) -> None:
        self._hydrate()
        self.assertTrue(self.v414._install_v409_guarded_recovery())

        def new_stop(cb: object, equity: float) -> None:
            self.ks._activation_history.append({"source": "MANUAL", "reason": "Operator stop"})

        self.v409._reclassify_false_halt_if_proven.side_effect = new_stop
        self.assertFalse(self.v409._recover_exact_false_drawdown_stop())
        self._assert_stopped()

    def test_one_time_migration_cannot_be_reused_for_a_future_generic_stop(self) -> None:
        self._hydrate()
        self.assertTrue(self.v414._install_v409_guarded_recovery())
        self.assertTrue(self.v409._recover_exact_false_drawdown_stop())
        self.ks._activate_internal("Kill switch file detected", "FILE_SYSTEM")
        record = json.loads(self.redis_value)
        self.assertTrue(record["legacy_v414_migration_consumed"])
        self.v414._RECOVERY_COMPLETE.clear()
        self.assertFalse(self.v409._recover_exact_false_drawdown_stop())
        self.ks.deactivate.assert_called_once()
        self._assert_stopped()

    def test_conflicting_history_outside_recent_window_blocks_migration(self) -> None:
        self._hydrate()
        self.ks._activation_history = [
            {"reason": "Operator stop", "source": "MANUAL"},
            *[dict(self.stop_record) for _ in range(6)],
        ]
        self.assertEqual(len(self.ks.get_status()["recent_history"]), 5)
        self.assertTrue(self.v414._install_v409_guarded_recovery())
        self.assertFalse(self.v409._recover_exact_false_drawdown_stop())
        self.redis.eval.assert_not_called()
        self._assert_stopped()

    def test_operator_marker_or_env_stop_blocks_migration(self) -> None:
        self._hydrate()
        self.assertTrue(self.v414._install_v409_guarded_recovery())
        for text in ("Owner stop", "Reason: Operator emergency stop\n"):
            Path(self.ks._kill_file).write_text(text)
            self.assertFalse(self.v409._recover_exact_false_drawdown_stop())
            self.redis.eval.assert_not_called()
            self._assert_stopped()
        self.ks._create_kill_file("Kill switch file detected")
        with patch.dict("os.environ", {"NIJA_KILL_SWITCH": "true"}):
            self.assertFalse(self.v409._recover_exact_false_drawdown_stop())
        self.redis.eval.assert_not_called()

    def test_new_redis_risk_after_migration_blocks_deactivation(self) -> None:
        self._hydrate()
        self.assertTrue(self.v414._install_v409_guarded_recovery())

        def new_risk(cb: object, equity: float) -> None:
            self.redis_value = json.dumps(dict(self.stop_record, source="AUTO_TRIGGER", reason="Daily loss limit"))

        self.v409._reclassify_false_halt_if_proven.side_effect = new_risk
        self.assertFalse(self.v409._recover_exact_false_drawdown_stop())
        self._assert_stopped()
        self.assertEqual(json.loads(self.redis_value)["reason"], "Daily loss limit")

    def test_original_reference_and_halt_proofs_required_before_any_migration_write(self) -> None:
        self._hydrate()
        self.assertTrue(self.v414._install_v409_guarded_recovery())
        with patch.object(self.v414, "_original_drawdown_reference", return_value=(False, 0, 0, 0, "invalid")):
            self.assertFalse(self.v409._recover_exact_false_drawdown_stop())
        self.cb._config.halt_pct = 21.0
        self.assertFalse(self.v409._recover_exact_false_drawdown_stop())
        self.redis.eval.assert_not_called()
        self.ks.deactivate.assert_not_called()
        self._assert_stopped()

    def test_redis_read_failure_blocks_migration(self) -> None:
        self._hydrate()
        self.assertTrue(self.v414._install_v409_guarded_recovery())
        self.redis.get.side_effect = RuntimeError("Redis unavailable")
        self.assertFalse(self.v409._recover_exact_false_drawdown_stop())
        self.redis.eval.assert_not_called()
        self.ks.deactivate.assert_not_called()
        self._assert_stopped()

    def test_existing_real_cause_upgrades_without_generic_incident_attestation(self) -> None:
        self._hydrate()
        real = dict(
            self.stop_record,
            source=self.v414._INCIDENT_20261006_CAUSAL_SOURCE,
            reason=self.v414._INCIDENT_20261006_CAUSAL_REASON,
        )
        self.redis_value = json.dumps(real)
        self.ks._activation_history = [real]
        self.ks._create_kill_file(real["reason"])
        self.assertTrue(self.v414._install_v409_guarded_recovery())
        with patch.dict("os.environ", {self.v414._LEGACY_ATTESTATION_ENV: ""}):
            self.assertTrue(self.v409._recover_exact_false_drawdown_stop())
        self.assertFalse(self.ks.is_active())
        inactive = json.loads(self.redis_value)
        self.assertEqual(inactive["origin_timestamp"], real["timestamp"])

    def test_v213_preserved_marker_replay_retains_durable_recovery(self) -> None:
        self._hydrate()
        self.redis_clear_ok = False
        self.assertTrue(self.v414._install_v409_guarded_recovery())
        self.assertFalse(self.v409._recover_exact_false_drawdown_stop())
        reason = self.v414._INCIDENT_20261006_CAUSAL_REASON
        self.ks._activation_history.append({
            "source": "FILE_SYSTEM",
            "reason": f"Kill switch file detected | persisted_reason={reason}",
            "persisted_marker_reason": reason,
        })
        self.ks._create_kill_file(reason)
        self.redis_clear_ok = True
        self.assertTrue(self.v409._recover_exact_false_drawdown_stop())
        self.assertFalse(self.ks.is_active())

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
                self.redis.eval.assert_not_called()


if __name__ == "__main__":
    unittest.main()
