from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
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
            "schema": 1,
        }
        self.redis_value = json.dumps(self.stop_record)
        self.redis_clear_ok = True
        redis = Mock()
        redis.eval.side_effect = self._redis_compare_and_set
        redis.get.side_effect = lambda key: self.redis_value
        redis.set.side_effect = self._redis_set
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
        self.canonical_capital_ready = False
        self.ca_total = 600.0
        self.holding_value = 176.0
        self.position_proof = True
        self.snapshot_fresh = True
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
        broker = object()
        self.v409._canonical_manager = lambda: object()
        self.v409._platform_coinbase = lambda manager: broker
        self.v409._reclassify_false_halt_if_proven = Mock(return_value=False)
        self.v409._recover_exact_false_drawdown_stop = lambda: False
        self.v409.install = self._install_v409
        modules = {
            "bot.runtime_drawdown_portfolio_equity_v409_patch": self.v409,
            "bot.capital_authority": types.SimpleNamespace(get_capital_authority=lambda: self.ca),
            "bot.readiness_proof_convergence_v134_patch": types.SimpleNamespace(
                _current_capital_proof=lambda: {
                    "hydrated": self.canonical_capital_ready,
                    "stale": not self.canonical_capital_ready,
                    "real": self.ca_total if self.canonical_capital_ready else 0.0,
                    "registered": 3 if self.canonical_capital_ready else 0,
                },
                _current_capital_accepted=lambda proof: bool(
                    proof.get("hydrated")
                    and not proof.get("stale")
                    and float(proof.get("real", 0.0) or 0.0) > 0.0
                    and int(proof.get("registered", 0) or 0) > 0
                ),
            ),
            "bot.global_drawdown_circuit_breaker": types.SimpleNamespace(get_global_drawdown_cb=lambda: self.cb),
            "bot.kill_switch": types.SimpleNamespace(get_kill_switch=lambda: self.ks),
            "bot.kill_switch_persistence_provenance_v143_patch": types.SimpleNamespace(
                _causal_activation_from_status=self._causal_activation,
            ),
            "bot.runtime_authoritative_position_coverage_v285_patch": types.SimpleNamespace(
                _snapshot_status=lambda current_broker: (
                    self.snapshot_fresh,
                    "fresh_snapshot" if self.snapshot_fresh else "stale_snapshot",
                    (),
                    1.0,
                    2,
                ),
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
        env_patch = patch.dict(
            "os.environ",
            {
                "NIJA_KILL_SWITCH": "false",
                "NIJA_ALLOW_PROVEN_LEGACY_STOP_RECOVERY": "0",
            },
        )
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
        monitor = self.v414._RECOVERY_MONITOR_THREAD
        if monitor is not None:
            monitor.join(timeout=1.0)
            self.assertFalse(monitor.is_alive())

    def _redis_set(self, key: str, value: str) -> bool:
        if self.redis_clear_ok:
            self.redis_value = value
        return self.redis_clear_ok

    def _redis_compare_and_set(
        self,
        script: str,
        key_count: int,
        key: str,
        expected: str,
        replacement: str,
    ) -> int:
        if self.redis_value != expected:
            return 0
        self.redis_value = replacement
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
        self.canonical_capital_ready = True
        self.cb._current_equity = self.ca_total + (self.holding_value if corrected_breaker else 0.0)

    def test_canonical_v134_capital_proof_is_authoritative(self) -> None:
        self.ca.is_fresh.return_value = True
        self.canonical_capital_ready = False
        self.assertFalse(self.v414._capital_proof_current())

        self.ca.is_fresh.return_value = False
        self.canonical_capital_ready = True
        self.assertTrue(self.v414._capital_proof_current())

    def test_canonical_import_failures_never_select_standalone_freshness(self) -> None:
        self.ca.is_fresh.return_value = True
        canonical = "bot.readiness_proof_convergence_v134_patch"
        original_import = self.v414.importlib.import_module
        for failure in (
            RuntimeError("provider initialization failed"),
            ImportError("provider broken"),
            ModuleNotFoundError("dependency missing", name="missing_dependency"),
            ModuleNotFoundError("parent missing", name="bot"),
        ):
            with self.subTest(failure=type(failure).__name__, name=getattr(failure, "name", None)):
                def importer(name: str):
                    if name == canonical:
                        raise failure
                    return original_import(name)

                with patch.object(self.v414.importlib, "import_module", side_effect=importer):
                    self.assertFalse(self.v414._capital_proof_current())
        self.ca.is_fresh.assert_not_called()

    def test_standalone_fallback_requires_genuinely_absent_optional_provider(self) -> None:
        self.ca.is_fresh.return_value = True
        canonical = "bot.readiness_proof_convergence_v134_patch"
        original_import = self.v414.importlib.import_module

        def importer(name: str):
            if name == canonical:
                raise ModuleNotFoundError("optional provider absent", name=canonical)
            return original_import(name)

        with patch.object(self.v414.importlib, "import_module", side_effect=importer):
            with patch.object(self.v414.importlib.util, "find_spec", return_value=None):
                self.assertTrue(self.v414._capital_proof_current())
            self.ca.is_fresh.reset_mock()
            with patch.object(self.v414.importlib.util, "find_spec", return_value=object()):
                self.assertFalse(self.v414._capital_proof_current())
            with patch.object(
                self.v414.importlib.util, "find_spec",
                side_effect=ModuleNotFoundError("parent missing", name="bot"),
            ):
                self.assertFalse(self.v414._capital_proof_current())
            self.ca.is_fresh.assert_not_called()

    def test_invalid_or_broken_canonical_providers_fail_closed(self) -> None:
        self.ca.is_fresh.return_value = True
        for provider in (
            types.SimpleNamespace(),
            types.SimpleNamespace(_current_capital_proof=lambda: None, _current_capital_accepted=lambda p: True),
            types.SimpleNamespace(
                _current_capital_proof=Mock(side_effect=RuntimeError("reader broken")),
                _current_capital_accepted=lambda p: True,
            ),
            types.SimpleNamespace(
                _current_capital_proof=lambda: {},
                _current_capital_accepted=Mock(side_effect=RuntimeError("acceptor broken")),
            ),
        ):
            with self.subTest(provider=provider):
                with patch.dict(sys.modules, {"bot.readiness_proof_convergence_v134_patch": provider}):
                    self.assertFalse(self.v414._capital_proof_current())
        self.ca.is_fresh.assert_not_called()

    def test_capital_diagnostic_reports_provider_and_duplicate_v16_identities(self) -> None:
        root_v16 = types.ModuleType("preactivation_readiness_convergence_v16_patch")
        package_v16 = types.ModuleType("bot.preactivation_readiness_convergence_v16_patch")
        collector = lambda: ({}, {})
        collector._nija_v358_capital_mode_decoupled = True
        root_v16._collect_proofs = collector
        v358 = types.ModuleType("bot.runtime_capital_readiness_mode_decoupling_v358_patch")

        def current_proof() -> dict[str, object]:
            sys.modules[root_v16.__name__] = root_v16
            sys.modules[package_v16.__name__] = package_v16
            return {
                "hydrated": True, "stale": False, "real": 5.0, "registered": 1,
            }

        provider = types.SimpleNamespace(
            _current_capital_proof=current_proof,
            _current_capital_accepted=lambda proof: True,
        )

        with patch.dict(sys.modules, {
            "bot.readiness_proof_convergence_v134_patch": provider,
            "bot.runtime_capital_readiness_mode_decoupling_v358_patch": v358,
        }):
            accepted, diagnostic = self.v414._capital_proof_diagnostic()

        self.assertTrue(accepted)
        self.assertTrue(diagnostic["proof_provider_identity"].startswith("SimpleNamespace:"))
        self.assertEqual(diagnostic["v16_alias_identity"], "distinct_modules")
        self.assertEqual(
            diagnostic["v16_reader_module"], "preactivation_readiness_convergence_v16_patch"
        )
        self.assertEqual(
            diagnostic["v358_reader_module"], "preactivation_readiness_convergence_v16_patch"
        )
        self.assertEqual(diagnostic["v358_collector"], "installed")
        self.assertNotIn("5.0", " ".join(diagnostic.values()))
        self.assertNotIn("real=5", " ".join(diagnostic.values()))

    def test_capital_diagnostic_classifies_broken_reader_without_error_payload(self) -> None:
        provider = types.SimpleNamespace(
            _current_capital_proof=Mock(side_effect=RuntimeError("private payload")),
            _current_capital_accepted=lambda proof: True,
        )
        with patch.dict(
            sys.modules,
            {"bot.readiness_proof_convergence_v134_patch": provider},
        ):
            accepted, diagnostic = self.v414._capital_proof_diagnostic()

        self.assertFalse(accepted)
        self.assertEqual(diagnostic["proof_rejection"], "reader_error")
        self.assertEqual(diagnostic["proof_exception"], "RuntimeError")
        self.assertNotIn("private payload", " ".join(diagnostic.values()))

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

    def test_operator_gate_is_required_after_one_time_redis_annotation(self) -> None:
        self._hydrate()
        self.assertTrue(self.v414._install_v409_guarded_recovery())

        self.assertFalse(self.v409._recover_exact_false_drawdown_stop())
        annotated = json.loads(self.redis_value)
        self.assertTrue(annotated["is_active"])
        self.assertEqual(annotated["schema"], 2)
        self.assertEqual(annotated["origin_source"], "GlobalDrawdownCircuitBreaker")
        self.assertEqual(
            annotated["origin_reason"],
            "GlobalDrawdownCircuitBreaker: HALT level reached (drawdown=20.31%, equity=$617.89)",
        )
        self.assertTrue(annotated["incident_id"])
        self.assertEqual(annotated["timestamp"], self.stop_record["timestamp"])
        self.redis.eval.assert_called_once()
        self.ks.deactivate.assert_not_called()
        self._assert_stopped()

        self.assertFalse(self.v409._recover_exact_false_drawdown_stop())
        self.assertEqual(self.redis.eval.call_count, 1)
        self.ks.deactivate.assert_not_called()

    def test_stale_authoritative_snapshot_blocks_migration_and_deactivation(self) -> None:
        self._hydrate()
        self.snapshot_fresh = False
        self.assertTrue(self.v414._install_v409_guarded_recovery())

        with self.assertLogs(self.v414.LOGGER, level="CRITICAL") as logs:
            self.assertFalse(self.v409._recover_exact_false_drawdown_stop())
        self.assertEqual(json.loads(self.redis_value)["schema"], 1)
        self.redis.eval.assert_not_called()
        self.ks.deactivate.assert_not_called()
        self._assert_stopped()
        self.assertTrue(any(
            "authoritative_position_proof" in line
            and "freshness_status=stale_snapshot" in line
            for line in logs.output
        ))

    def test_operator_history_blocks_legacy_annotation(self) -> None:
        self._hydrate()
        self.ks._activation_history.append(
            {
                "source": "UI",
                "reason": "operator stop after incident",
                "timestamp": "2026-10-06T19:00:00+00:00",
            }
        )
        self.assertTrue(self.v414._install_v409_guarded_recovery())

        self.assertFalse(self.v409._recover_exact_false_drawdown_stop())
        self.assertEqual(json.loads(self.redis_value)["schema"], 1)
        self.redis.eval.assert_not_called()
        self.ks.deactivate.assert_not_called()
        self._assert_stopped()

    def test_redis_compare_and_set_race_blocks_legacy_annotation(self) -> None:
        self._hydrate()
        self.redis.eval.side_effect = None
        self.redis.eval.return_value = 0
        self.assertTrue(self.v414._install_v409_guarded_recovery())

        self.assertFalse(self.v409._recover_exact_false_drawdown_stop())
        self.assertEqual(json.loads(self.redis_value)["schema"], 1)
        self.ks.deactivate.assert_not_called()
        self._assert_stopped()

    def test_worker_waits_for_hydration_then_recovers_and_terminates(self) -> None:
        os.environ["NIJA_ALLOW_PROVEN_LEGACY_STOP_RECOVERY"] = "1"
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
        self.assertTrue(any("LEGACY_KILL_SWITCH_V1_MIGRATION_APPLIED" in line for line in logs.output))
        self.assertEqual(self.cb._config.halt_pct, 20.0)
        self.assertEqual(self.cb._peak_equity, 600.0)
        self.assertEqual(self.readiness, {"execution_ready": False, "capital_ready": False})
        self.state.transition_to.assert_called_once_with("OFF", ANY)
        self.assertEqual(self.orders.mock_calls, [])
        self.assertTrue(self.v414.install())
        self.assertIsNone(self.v414._RETRY_THREAD)
        self.ks.deactivate.assert_called_once()

    def test_recovery_accepts_raw_breaker_series(self) -> None:
        os.environ["NIJA_ALLOW_PROVEN_LEGACY_STOP_RECOVERY"] = "1"
        self._hydrate()
        self.assertTrue(self.v414._install_v409_guarded_recovery())
        self.assertTrue(self.v409._recover_exact_false_drawdown_stop())
        self.assertFalse(self.ks.is_active())
        self.ks.deactivate.assert_called_once()
        self.assertFalse(self.v409._recover_exact_false_drawdown_stop())
        self.ks.deactivate.assert_called_once()

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
        os.environ["NIJA_ALLOW_PROVEN_LEGACY_STOP_RECOVERY"] = "1"
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
        os.environ["NIJA_ALLOW_PROVEN_LEGACY_STOP_RECOVERY"] = "1"
        self._hydrate()
        self.ks.deactivate = Mock(return_value=True)
        self.assertTrue(self.v414._install_v409_guarded_recovery())
        self.assertFalse(self.v409._recover_exact_false_drawdown_stop())
        self._assert_stopped()

    def test_worker_retries_redis_failure_and_exits_on_confirmed_success(self) -> None:
        os.environ["NIJA_ALLOW_PROVEN_LEGACY_STOP_RECOVERY"] = "1"
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
        os.environ["NIJA_ALLOW_PROVEN_LEGACY_STOP_RECOVERY"] = "1"
        self._hydrate()
        self.assertTrue(self.v414.install())
        self.assertIsNone(self.v414._RETRY_THREAD)
        self.ks.deactivate.assert_called_once()
        self.assertTrue(self.v414.install())
        self.ks.deactivate.assert_called_once()

    def test_worker_serializes_recovery_with_v409_installation_lock(self) -> None:
        self._hydrate()
        lock = threading.Lock()

        def recovery() -> bool:
            self.assertFalse(lock.acquire(blocking=False))
            return True

        self.v409._recover_exact_false_drawdown_stop = Mock(side_effect=recovery)
        self.v409._LOCK = lock
        with patch.object(self.v414._RECOVERY_COMPLETE, "wait", return_value=False):
            self.v414._retry_recovery()
        self.v409._recover_exact_false_drawdown_stop.assert_called_once()
        self.assertTrue(lock.acquire(blocking=False))
        lock.release()
        self.assertTrue(self.v414._RECOVERY_COMPLETE.is_set())

    def test_worker_reports_bounded_lock_contention_without_running_predicate(self) -> None:
        self._hydrate()
        lock = threading.Lock()
        lock.acquire()
        self.v409._LOCK = lock
        recovery = Mock(return_value=True)
        self.v409._recover_exact_false_drawdown_stop = recovery
        waits = Mock(side_effect=[False, True])
        with patch.object(self.v414._RECOVERY_COMPLETE, "wait", waits):
            with self.assertLogs(self.v414.LOGGER, level="CRITICAL") as logs:
                self.v414._retry_recovery()

        lock.release()
        recovery.assert_not_called()
        self.assertTrue(any(
            "phase=installation_lock_wait" in line and "status=busy" in line
            for line in logs.output
        ))

    def test_worker_deduplicates_repeated_capital_wait_diagnostics(self) -> None:
        waits = Mock(side_effect=[False, False, False, True])
        with patch.object(self.v414._RECOVERY_COMPLETE, "wait", waits):
            with self.assertLogs(self.v414.LOGGER, level="CRITICAL") as logs:
                worker = threading.Thread(
                    target=self.v414._retry_recovery,
                    name="DrawdownRecoveryV414",
                )
                worker.start()
                worker.join(timeout=1.0)

        self.assertFalse(worker.is_alive())
        waiting_transitions = [
            line for line in logs.output
            if "phase=awaiting_capital_proof" in line
        ]
        self.assertEqual(len(waiting_transitions), 1)
        self.assertIn("proof_rejection=hydrated", waiting_transitions[0])
        self.assertNotIn("real=", waiting_transitions[0])
        self.assertEqual(sum("DRAWDOWN_V414_RETRY_WAITING" in line for line in logs.output), 1)

    def test_diagnostic_monitor_reports_stuck_live_predicate_phase(self) -> None:
        class AliveWorker:
            def is_alive(self) -> bool:
                return True

        prior_worker = self.v414._RETRY_THREAD
        self.v414._RETRY_THREAD = AliveWorker()
        self.v414._RECOVERY_PHASE = "predicate_evaluation"
        self.v414._RECOVERY_PHASE_STARTED_AT = time.monotonic() - 11.0
        waits = Mock(side_effect=[False, True])
        try:
            with patch.object(self.v414._RECOVERY_COMPLETE, "wait", waits):
                with self.assertLogs(self.v414.LOGGER, level="CRITICAL") as logs:
                    self.v414._recovery_diagnostic_monitor()
        finally:
            self.v414._RETRY_THREAD = prior_worker

        self.assertTrue(any(
            "worker_alive=true" in line
            and "phase=predicate_evaluation" in line
            and "status=stalled" in line
            for line in logs.output
        ))

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
                self.canonical_capital_ready = fresh
                self.position_proof = positions
                self.cb._current_equity = equity
                self.holding_value = holding
                self.assertFalse(self.v409._recover_exact_false_drawdown_stop())
                self.ks.deactivate.assert_not_called()
                self._assert_stopped()


if __name__ == "__main__":
    unittest.main()
