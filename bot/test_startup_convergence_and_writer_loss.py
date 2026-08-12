"""Deterministic unit tests for startup convergence and terminal writer loss."""

from __future__ import annotations

import importlib
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


_BOT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_BOT_DIR)
for _p in (_BOT_DIR, _REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _import_readiness_table():
    try:
        import bot.readiness_table as mod
    except ImportError:
        import readiness_table as mod  # type: ignore[import]
    return mod


def _import_latch():
    for name in ("bot.terminal_writer_loss_latch", "terminal_writer_loss_latch"):
        sys.modules.pop(name, None)
    return importlib.import_module("bot.terminal_writer_loss_latch")


class TestReadinessConvergenceTruth(unittest.TestCase):
    def setUp(self) -> None:
        self.readiness_table = _import_readiness_table()
        self.readiness_table.reset()
        self.addCleanup(self.readiness_table.reset)

    def test_truthful_incremental_readiness(self) -> None:
        expected_pending = set(self.readiness_table.KEYS)
        for key in (
            "broker_connected",
            "balance_hydrated",
            "authority_ready",
            "capital_ready",
            "risk_ready",
            "strategy_ready",
            "execution_ready",
            "nonce_ready",
            "bootstrap_ready",
        ):
            before = self.readiness_table.snapshot()
            self.readiness_table.mark_ready(key)
            after = self.readiness_table.snapshot()
            self.assertFalse(before.get(key, False))
            self.assertTrue(after.get(key, False))
            expected_pending.discard(key)
            self.assertEqual(set(self.readiness_table.pending()), expected_pending)
        self.assertTrue(self.readiness_table.is_ready())

    def test_nonce_contradiction_impossible_under_bulk_revoke(self) -> None:
        for key in ("authority_ready", "nonce_ready", "execution_ready"):
            self.readiness_table.mark_ready(key)
        before_version, before = self.readiness_table.snapshot_with_version()
        self.assertTrue(before["authority_ready"])
        self.assertTrue(before["nonce_ready"])
        self.assertTrue(before["execution_ready"])

        self.readiness_table.revoke_many(
            ("authority_ready", "nonce_ready", "execution_ready"),
            reason="terminal_writer_loss:test",
        )

        after_version, after = self.readiness_table.snapshot_with_version()
        self.assertGreater(after_version, before_version)
        self.assertFalse(after["authority_ready"])
        self.assertFalse(after["nonce_ready"])
        self.assertFalse(after["execution_ready"])


class TestTerminalWriterLossLatch(unittest.TestCase):
    def setUp(self) -> None:
        self.latch = _import_latch()
        self.readiness_table = _import_readiness_table()
        self.readiness_table.reset()
        self.latch.reset_for_test()
        self.addCleanup(self.readiness_table.reset)
        self.addCleanup(self.latch.reset_for_test)
        self.addCleanup(os.environ.pop, "NIJA_RUNTIME_EXECUTION_AUTHORITY", None)
        self.addCleanup(os.environ.pop, "NIJA_EXECUTION_ACTIVE", None)
        self.addCleanup(os.environ.pop, "NIJA_WRITER_LEASE_GENERATION", None)
        self.addCleanup(os.environ.pop, "NIJA_PRIVATE_IO_STOP", None)
        self.addCleanup(os.environ.pop, "NIJA_WRITER_AUTHORITY_RESTART_GRACE_S", None)

    def _install_fake_runtime_hooks(self):
        revoke_spy = MagicMock(side_effect=self.readiness_table.revoke_many)
        seak = MagicMock()
        shutdown = MagicMock()
        request_exit = MagicMock(return_value=75)
        timer = MagicMock()

        fake_readiness = types.ModuleType("bot.readiness_table")
        fake_readiness.revoke_many = revoke_spy
        fake_seak_mod = types.ModuleType("bot.single_execution_authority_kernel")
        fake_seak_mod.get_seak = MagicMock(return_value=seak)
        fake_bootstrap = types.ModuleType("bot.bootstrap_utils")
        fake_bootstrap.signal_shutdown = shutdown
        fake_bot_main = types.ModuleType("bot.bot_main")
        fake_bot_main.request_process_exit = request_exit

        return {
            "revoke_spy": revoke_spy,
            "seak": seak,
            "shutdown": shutdown,
            "request_exit": request_exit,
            "timer": timer,
            "modules": {
                "bot.readiness_table": fake_readiness,
                "bot.single_execution_authority_kernel": fake_seak_mod,
                "bot.bootstrap_utils": fake_bootstrap,
                "bot.bot_main": fake_bot_main,
            },
        }

    def test_terminal_authority_loss_triggers_latch_once(self) -> None:
        hooks = self._install_fake_runtime_hooks()
        for key in ("authority_ready", "nonce_ready", "execution_ready"):
            self.readiness_table.mark_ready(key)
        with (
            patch.dict(sys.modules, hooks["modules"], clear=False),
            patch.object(self.latch.threading, "Timer", return_value=hooks["timer"]),
            patch.dict(os.environ, {"NIJA_WRITER_LEASE_GENERATION": "12"}, clear=False),
        ):
            fired = self.latch.report_terminal_writer_loss(
                "lease_no_longer_owned",
                "heartbeat_monitor",
            )
            self.assertEqual(os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"], "0")
            self.assertEqual(os.environ["NIJA_EXECUTION_ACTIVE"], "false")
            self.assertEqual(os.environ["NIJA_PRIVATE_IO_STOP"], "1")

        self.assertTrue(fired)
        self.assertTrue(self.latch.is_latched())
        info = self.latch.get_latch_info()
        self.assertEqual(info["reason"], "lease_no_longer_owned")
        self.assertEqual(info["source"], "heartbeat_monitor")
        self.assertEqual(info["writer_generation"], "12")
        self.assertTrue(self.latch.private_io_suppressed("post_latch"))
        hooks["revoke_spy"].assert_called_once()
        hooks["seak"].emergency_halt.assert_called_once_with(
            "terminal_writer_loss:lease_no_longer_owned",
            source="terminal_writer_loss_latch",
        )
        hooks["shutdown"].assert_called_once_with()
        hooks["request_exit"].assert_called_once_with(
            "terminal_writer_loss:lease_no_longer_owned",
            exit_code=75,
            terminal_startup_failure=False,
        )
        hooks["timer"].start.assert_called_once_with()
        table = self.readiness_table.snapshot()
        self.assertFalse(table["authority_ready"])
        self.assertFalse(table["nonce_ready"])
        self.assertFalse(table["execution_ready"])

    def test_terminal_latch_is_idempotent(self) -> None:
        hooks = self._install_fake_runtime_hooks()
        with (
            patch.dict(sys.modules, hooks["modules"], clear=False),
            patch.object(self.latch.threading, "Timer", return_value=hooks["timer"]),
        ):
            self.assertTrue(
                self.latch.report_terminal_writer_loss(
                    "fencing_token_invalid",
                    "authority_context",
                )
            )
            self.assertFalse(
                self.latch.report_terminal_writer_loss(
                    "generation_changed",
                    "heartbeat_monitor",
                )
            )

        hooks["request_exit"].assert_called_once()
        hooks["timer"].start.assert_called_once_with()
        info = self.latch.get_latch_info()
        self.assertEqual(info["reason"], "fencing_token_invalid")
        self.assertEqual(info["source"], "authority_context")

    def test_transient_probe_failure_does_not_trigger_latch(self) -> None:
        hooks = self._install_fake_runtime_hooks()
        with (
            patch.dict(sys.modules, hooks["modules"], clear=False),
            patch.object(self.latch.threading, "Timer", return_value=hooks["timer"]),
        ):
            fired = self.latch.report_terminal_writer_loss(
                "redis_timeout_on_probe",
                "heartbeat_monitor",
            )

        self.assertFalse(fired)
        self.assertFalse(self.latch.is_latched())
        hooks["request_exit"].assert_not_called()
        hooks["timer"].start.assert_not_called()

    def test_private_io_suppressed_after_latch(self) -> None:
        hooks = self._install_fake_runtime_hooks()
        with (
            patch.dict(sys.modules, hooks["modules"], clear=False),
            patch.object(self.latch.threading, "Timer", return_value=hooks["timer"]),
        ):
            self.assertFalse(self.latch.private_io_suppressed("before"))
            self.latch.report_terminal_writer_loss(
                "writer_authority_lost",
                "on_lease_lost",
            )
            self.assertTrue(self.latch.private_io_suppressed("after"))

    def test_process_exit_code_75_semantics(self) -> None:
        hooks = self._install_fake_runtime_hooks()
        with (
            patch.dict(sys.modules, hooks["modules"], clear=False),
            patch.object(self.latch.threading, "Timer", return_value=hooks["timer"]) as timer_factory,
            patch.dict(
                os.environ,
                {"NIJA_WRITER_AUTHORITY_RESTART_GRACE_S": "7"},
                clear=False,
            ),
        ):
            self.latch.report_terminal_writer_loss(
                "generation_mismatch",
                "authority_context",
            )

        hooks["request_exit"].assert_called_once_with(
            "terminal_writer_loss:generation_mismatch",
            exit_code=75,
            terminal_startup_failure=False,
        )
        self.assertEqual(timer_factory.call_args.args[0], 7.0)
        self.assertEqual(hooks["timer"].name, "terminal-writer-loss-forced-restart")
        self.assertTrue(hooks["timer"].daemon)

    def test_terminal_proof_classifications(self) -> None:
        self.assertTrue(self.latch._is_terminal_proof("authority_LOST"))
        self.assertTrue(self.latch._is_terminal_proof("lease_no_longer_owned"))
        self.assertTrue(self.latch._is_terminal_proof("generation_changed"))
        self.assertFalse(self.latch._is_terminal_proof("redis_timeout"))
        self.assertFalse(self.latch._is_terminal_proof("exchange_error"))
        self.assertFalse(self.latch._is_terminal_proof("mystery_signal"))
