"""Tests for writer epoch telemetry and capital broker classification.

Validates:
  1. Single canonical WRITER_EPOCH_ENDED emission ordering
  2. No duplicate emission
  3. No emission for generation=0
  4. WRITER_EPOCH_INVARIANT_VIOLATION for unsanctioned transition
  5. Sanctioned transitions pass invariant check
  6. CAPITAL_BROKER_CLASSIFICATION: may_fund_new_orders=False when disconnected
  7. CAPITAL_BALANCE_OBSERVATION: source label correctness
  8. classify_observation_source taxonomy
  9. Non-regression: generation=0 → no epoch-ended event emitted
 10. Non-regression: terminal_writer_loss_latch hooks epoch telemetry
"""

from __future__ import annotations

import logging
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

logging.basicConfig(level=logging.DEBUG)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _import_epoch_telemetry():
    for name in ("bot.writer_epoch_telemetry", "writer_epoch_telemetry"):
        sys.modules.pop(name, None)
    try:
        import bot.writer_epoch_telemetry as mod
    except ImportError:
        import writer_epoch_telemetry as mod  # type: ignore[import]
    return mod


def _import_capital_telemetry():
    for name in ("bot.capital_broker_telemetry", "capital_broker_telemetry"):
        sys.modules.pop(name, None)
    try:
        import bot.capital_broker_telemetry as mod
    except ImportError:
        import capital_broker_telemetry as mod  # type: ignore[import]
    return mod


def _import_latch():
    for name in ("bot.terminal_writer_loss_latch", "terminal_writer_loss_latch"):
        sys.modules.pop(name, None)
    try:
        import bot.terminal_writer_loss_latch as mod
    except ImportError:
        import terminal_writer_loss_latch as mod  # type: ignore[import]
    return mod


# ---------------------------------------------------------------------------
# Test: WRITER_EPOCH_ENDED emission
# ---------------------------------------------------------------------------

class TestWriterEpochEnded(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _import_epoch_telemetry()
        self.mod.reset_for_test()
        self.addCleanup(self.mod.reset_for_test)
        self.addCleanup(os.environ.pop, "NIJA_WRITER_LEASE_GENERATION", None)

    def test_emits_once_for_positive_generation(self) -> None:
        with patch.dict(os.environ, {"NIJA_WRITER_LEASE_GENERATION": "5"}, clear=False):
            first = self.mod.emit_writer_epoch_ended(reason="lease_no_longer_owned", source="test")
        self.assertTrue(first)
        self.assertTrue(self.mod.is_epoch_ended_emitted())

    def test_no_duplicate_emission(self) -> None:
        with patch.dict(os.environ, {"NIJA_WRITER_LEASE_GENERATION": "3"}, clear=False):
            first = self.mod.emit_writer_epoch_ended(reason="lease_no_longer_owned", source="test1")
            second = self.mod.emit_writer_epoch_ended(reason="terminal_shutdown", source="test2")
        self.assertTrue(first)
        self.assertFalse(second)

    def test_no_emission_for_generation_zero(self) -> None:
        with patch.dict(os.environ, {"NIJA_WRITER_LEASE_GENERATION": "0"}, clear=False):
            result = self.mod.emit_writer_epoch_ended(reason="lease_no_longer_owned", source="test")
        self.assertFalse(result)
        self.assertFalse(self.mod.is_epoch_ended_emitted())

    def test_no_emission_for_missing_generation(self) -> None:
        os.environ.pop("NIJA_WRITER_LEASE_GENERATION", None)
        result = self.mod.emit_writer_epoch_ended(reason="lease_no_longer_owned", source="test")
        self.assertFalse(result)

    def test_explicit_generation_before_overrides_env(self) -> None:
        os.environ["NIJA_WRITER_LEASE_GENERATION"] = "0"
        result = self.mod.emit_writer_epoch_ended(
            reason="lease_no_longer_owned",
            source="test",
            generation_before=7,
        )
        self.assertTrue(result)

    def test_log_contains_required_fields(self) -> None:
        with self.assertLogs("nija.writer_epoch_telemetry", level="CRITICAL") as cm:
            with patch.dict(os.environ, {"NIJA_WRITER_LEASE_GENERATION": "12"}, clear=False):
                self.mod.emit_writer_epoch_ended(
                    reason="lease_no_longer_owned",
                    source="heartbeat_monitor",
                )
        full_log = "\n".join(cm.output)
        for field in (
            "WRITER_EPOCH_ENDED",
            "timestamp=",
            "source=heartbeat_monitor",
            "reason=lease_no_longer_owned",
            "generation_before=12",
            "generation_after=0",
            "token_present_before=",
            "lease_owned_before=",
            "heartbeat_active_before=",
            "core_alive=",
            "core_registered=",
            "shutdown_requested=",
            "terminal_loss_latched=",
        ):
            self.assertIn(field, full_log, f"Missing field in log: {field}")


# ---------------------------------------------------------------------------
# Test: WRITER_EPOCH_INVARIANT_VIOLATION
# ---------------------------------------------------------------------------

class TestWriterEpochInvariant(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _import_epoch_telemetry()
        self.mod.reset_for_test()
        self.addCleanup(self.mod.reset_for_test)
        self.addCleanup(os.environ.pop, "NIJA_RUNTIME_EXECUTION_AUTHORITY", None)
        self.addCleanup(os.environ.pop, "NIJA_EXECUTION_ACTIVE", None)

    def test_sanctioned_reason_passes(self) -> None:
        result = self.mod.check_writer_epoch_invariant(
            reason="lease_no_longer_owned",
            source="test",
            generation_before=5,
            core_alive_before=True,
            core_registered_before=True,
        )
        self.assertTrue(result)

    def test_unsanctioned_reason_fails_closed(self) -> None:
        with self.assertLogs("nija.writer_epoch_telemetry", level="CRITICAL") as cm:
            result = self.mod.check_writer_epoch_invariant(
                reason="unknown_reason_xyz",
                source="test_caller",
                generation_before=5,
                core_alive_before=True,
                core_registered_before=True,
            )
        self.assertFalse(result)
        self.assertIn("WRITER_EPOCH_INVARIANT_VIOLATION", "\n".join(cm.output))
        self.assertEqual(os.environ.get("NIJA_RUNTIME_EXECUTION_AUTHORITY"), "0")
        self.assertEqual(os.environ.get("NIJA_EXECUTION_ACTIVE"), "false")

    def test_invariant_not_applicable_for_generation_zero(self) -> None:
        result = self.mod.check_writer_epoch_invariant(
            reason="unknown_reason",
            source="test",
            generation_before=0,
            core_alive_before=True,
            core_registered_before=True,
        )
        self.assertTrue(result)

    def test_invariant_not_applicable_when_core_not_alive(self) -> None:
        result = self.mod.check_writer_epoch_invariant(
            reason="unknown_reason",
            source="test",
            generation_before=5,
            core_alive_before=False,
            core_registered_before=True,
        )
        self.assertTrue(result)

    def test_all_sanctioned_terminal_keywords(self) -> None:
        sanctioned = [
            "terminal_shutdown",
            "intentional_release",
            "lease_no_longer_owned",
            "fencing_token_invalid",
            "generation_changed",
            "authority_LOST",
            "startup_failure",
            "controlled_handoff",
        ]
        for reason in sanctioned:
            with self.subTest(reason=reason):
                r = self.mod.check_writer_epoch_invariant(
                    reason=reason,
                    source="test",
                    generation_before=1,
                    core_alive_before=True,
                    core_registered_before=True,
                )
                self.assertTrue(r, f"Expected sanctioned for reason={reason}")


# ---------------------------------------------------------------------------
# Test: CAPITAL_BROKER_CLASSIFICATION
# ---------------------------------------------------------------------------

class TestCapitalBrokerClassification(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _import_capital_telemetry()

    def test_disconnected_broker_may_not_fund_orders(self) -> None:
        with self.assertLogs("nija.capital_broker_telemetry", level="INFO") as cm:
            self.mod.emit_capital_broker_classification(
                broker="kraken",
                equity_usd=227.75,
                observation_age_s=30.0,
                observation_source="sticky_success",
                connected=False,
                execution_eligible=False,
                may_count_in_portfolio_equity=True,
                may_fund_new_orders=False,
            )
        log = "\n".join(cm.output)
        self.assertIn("CAPITAL_BROKER_CLASSIFICATION", log)
        self.assertIn("broker=kraken", log)
        self.assertIn("may_fund_new_orders=false", log)
        self.assertIn("may_count_in_portfolio_equity=true", log)

    def test_disconnected_broker_fund_overridden_to_false(self) -> None:
        """may_fund_new_orders=True is overridden when connected=False."""
        with self.assertLogs("nija.capital_broker_telemetry", level="CRITICAL") as cm:
            self.mod.emit_capital_broker_classification(
                broker="kraken",
                equity_usd=100.0,
                observation_age_s=5.0,
                observation_source="sticky_success",
                connected=False,
                execution_eligible=False,
                may_count_in_portfolio_equity=True,
                may_fund_new_orders=True,  # must be overridden
            )
        log = "\n".join(cm.output)
        self.assertIn("CAPITAL_BROKER_CLASSIFICATION_CONSTRAINT_VIOLATION", log)

    def test_connected_eligible_broker_may_fund(self) -> None:
        with self.assertLogs("nija.capital_broker_telemetry", level="INFO") as cm:
            self.mod.emit_capital_broker_classification(
                broker="coinbase",
                equity_usd=240.07,
                observation_age_s=1.0,
                observation_source="live_http",
                connected=True,
                execution_eligible=True,
                may_count_in_portfolio_equity=True,
                may_fund_new_orders=True,
            )
        log = "\n".join(cm.output)
        self.assertIn("may_fund_new_orders=true", log)


# ---------------------------------------------------------------------------
# Test: CAPITAL_BALANCE_OBSERVATION
# ---------------------------------------------------------------------------

class TestCapitalBalanceObservation(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _import_capital_telemetry()

    def test_live_http_source(self) -> None:
        with self.assertLogs("nija.capital_broker_telemetry", level="INFO") as cm:
            self.mod.emit_capital_balance_observation(
                broker="coinbase",
                value=240.07,
                source="live_http",
                network_request_started=True,
                network_response_received=True,
                writer_generation=5,
                observation_generation=5,
                age_s=0.5,
            )
        log = "\n".join(cm.output)
        self.assertIn("CAPITAL_BALANCE_OBSERVATION", log)
        self.assertIn("source=live_http", log)
        self.assertIn("network_response_received=true", log)

    def test_sticky_source_network_response_overridden(self) -> None:
        """network_response_received=True must not be allowed for non-live_http."""
        with self.assertLogs("nija.capital_broker_telemetry", level="WARNING") as cm:
            self.mod.emit_capital_balance_observation(
                broker="kraken",
                value=227.75,
                source="sticky_success",
                network_request_started=True,
                network_response_received=True,  # invalid — must be overridden
                writer_generation=0,
                observation_generation=5,
                age_s=120.0,
            )
        log = "\n".join(cm.output)
        self.assertIn("CAPITAL_BALANCE_OBSERVATION_LABEL_WARNING", log)

    def test_prior_snapshot_source(self) -> None:
        with self.assertLogs("nija.capital_broker_telemetry", level="INFO") as cm:
            self.mod.emit_capital_balance_observation(
                broker="kraken",
                value=227.75,
                source="prior_authenticated_snapshot",
                network_request_started=False,
                network_response_received=False,
                writer_generation=0,
                observation_generation=5,
                age_s=600.0,
            )
        log = "\n".join(cm.output)
        self.assertIn("source=prior_authenticated_snapshot", log)


# ---------------------------------------------------------------------------
# Test: classify_observation_source
# ---------------------------------------------------------------------------

class TestClassifyObservationSource(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _import_capital_telemetry()

    def test_live_http(self) -> None:
        src = self.mod.classify_observation_source(
            network_success=True,
            is_cached=False,
            is_sticky_preserved=False,
            observation_generation=5,
            current_writer_generation=5,
        )
        self.assertEqual(src, "live_http")

    def test_sticky_success_same_generation(self) -> None:
        src = self.mod.classify_observation_source(
            network_success=False,
            is_cached=False,
            is_sticky_preserved=True,
            observation_generation=5,
            current_writer_generation=5,
        )
        self.assertEqual(src, "sticky_success")

    def test_prior_authenticated_snapshot_when_generation_differs(self) -> None:
        src = self.mod.classify_observation_source(
            network_success=False,
            is_cached=False,
            is_sticky_preserved=True,
            observation_generation=5,
            current_writer_generation=0,
        )
        self.assertEqual(src, "prior_authenticated_snapshot")

    def test_fresh_cache(self) -> None:
        src = self.mod.classify_observation_source(
            network_success=False,
            is_cached=True,
            is_sticky_preserved=False,
            observation_generation=5,
            current_writer_generation=5,
        )
        self.assertEqual(src, "fresh_cache")


# ---------------------------------------------------------------------------
# Test: terminal_writer_loss_latch hooks epoch telemetry
# ---------------------------------------------------------------------------

class TestLatchEpochHook(unittest.TestCase):
    def setUp(self) -> None:
        self.latch = _import_latch()
        self.epoch_mod = _import_epoch_telemetry()
        self.latch.reset_for_test()
        self.epoch_mod.reset_for_test()
        self.addCleanup(self.latch.reset_for_test)
        self.addCleanup(self.epoch_mod.reset_for_test)
        self.addCleanup(os.environ.pop, "NIJA_RUNTIME_EXECUTION_AUTHORITY", None)
        self.addCleanup(os.environ.pop, "NIJA_EXECUTION_ACTIVE", None)
        self.addCleanup(os.environ.pop, "NIJA_WRITER_LEASE_GENERATION", None)
        self.addCleanup(os.environ.pop, "NIJA_PRIVATE_IO_STOP", None)
        self.addCleanup(os.environ.pop, "NIJA_WRITER_AUTHORITY_RESTART_GRACE_S", None)

    def _make_fake_modules(self) -> dict:
        fake_readiness = types.ModuleType("bot.readiness_table")
        fake_readiness.revoke_many = MagicMock()
        fake_seak_mod = types.ModuleType("bot.single_execution_authority_kernel")
        fake_seak_mod.get_seak = MagicMock(return_value=MagicMock())
        fake_bootstrap = types.ModuleType("bot.bootstrap_utils")
        fake_bootstrap.signal_shutdown = MagicMock()
        fake_bot_main = types.ModuleType("bot.bot_main")
        fake_bot_main.request_process_exit = MagicMock(return_value=75)
        return {
            "bot.readiness_table": fake_readiness,
            "bot.single_execution_authority_kernel": fake_seak_mod,
            "bot.bootstrap_utils": fake_bootstrap,
            "bot.bot_main": fake_bot_main,
        }

    def test_epoch_ended_emitted_when_latch_fires(self) -> None:
        """WRITER_EPOCH_ENDED must be emitted when terminal loss latch fires."""
        fake_mods = self._make_fake_modules()
        timer_mock = MagicMock()
        with (
            patch.dict(sys.modules, fake_mods, clear=False),
            patch.object(self.latch.threading, "Timer", return_value=timer_mock),
            patch.dict(
                os.environ,
                {"NIJA_WRITER_LEASE_GENERATION": "7", "NIJA_WRITER_AUTHORITY_RESTART_GRACE_S": "0"},
                clear=False,
            ),
        ):
            fired = self.latch.report_terminal_writer_loss(
                "lease_no_longer_owned",
                "heartbeat_monitor",
            )

        self.assertTrue(fired)
        self.assertTrue(self.epoch_mod.is_epoch_ended_emitted())

    def test_epoch_ended_not_emitted_when_generation_zero(self) -> None:
        """No WRITER_EPOCH_ENDED if generation was already 0."""
        fake_mods = self._make_fake_modules()
        timer_mock = MagicMock()
        with (
            patch.dict(sys.modules, fake_mods, clear=False),
            patch.object(self.latch.threading, "Timer", return_value=timer_mock),
            patch.dict(
                os.environ,
                {"NIJA_WRITER_LEASE_GENERATION": "0", "NIJA_WRITER_AUTHORITY_RESTART_GRACE_S": "0"},
                clear=False,
            ),
        ):
            self.latch.report_terminal_writer_loss(
                "lease_no_longer_owned",
                "heartbeat_monitor",
            )

        self.assertFalse(self.epoch_mod.is_epoch_ended_emitted())


if __name__ == "__main__":
    unittest.main()
