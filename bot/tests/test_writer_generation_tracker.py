"""Tests for bot.writer_generation_tracker — authority lineage generation tracking."""

from __future__ import annotations

import os
import threading
import unittest
from unittest.mock import MagicMock, patch


class TestGetLocalGeneration(unittest.TestCase):
    """Tests for get_local_generation()."""

    def test_returns_zero_when_env_not_set(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NIJA_WRITER_LEASE_GENERATION", None)
            from bot.writer_generation_tracker import get_local_generation
            self.assertEqual(get_local_generation(), 0)

    def test_returns_value_from_env(self) -> None:
        with patch.dict(os.environ, {"NIJA_WRITER_LEASE_GENERATION": "42"}, clear=False):
            from bot.writer_generation_tracker import get_local_generation
            self.assertEqual(get_local_generation(), 42)

    def test_returns_zero_for_invalid_env_value(self) -> None:
        with patch.dict(os.environ, {"NIJA_WRITER_LEASE_GENERATION": "not-a-number"}, clear=False):
            from bot.writer_generation_tracker import get_local_generation
            self.assertEqual(get_local_generation(), 0)

    def test_returns_zero_for_negative_value(self) -> None:
        with patch.dict(os.environ, {"NIJA_WRITER_LEASE_GENERATION": "-5"}, clear=False):
            from bot.writer_generation_tracker import get_local_generation
            self.assertEqual(get_local_generation(), 0)

    def test_returns_zero_for_empty_env(self) -> None:
        with patch.dict(os.environ, {"NIJA_WRITER_LEASE_GENERATION": ""}, clear=False):
            from bot.writer_generation_tracker import get_local_generation
            self.assertEqual(get_local_generation(), 0)


class TestGetRedisGeneration(unittest.TestCase):
    """Tests for get_redis_generation()."""

    def test_returns_zero_and_error_when_redis_not_configured(self) -> None:
        with patch("bot.writer_generation_tracker._connect_redis", return_value=(None, "redis_url_not_configured")):
            from bot.writer_generation_tracker import get_redis_generation
            gen, err = get_redis_generation()
            self.assertEqual(gen, 0)
            self.assertIn("redis_url_not_configured", err)

    def test_returns_generation_from_redis(self) -> None:
        mock_client = MagicMock()
        mock_client.get.return_value = "7"
        with patch("bot.writer_generation_tracker._connect_redis", return_value=(mock_client, "")):
            from bot.writer_generation_tracker import get_redis_generation
            gen, err = get_redis_generation()
            self.assertEqual(gen, 7)
            self.assertEqual(err, "")

    def test_returns_zero_and_error_when_key_missing(self) -> None:
        mock_client = MagicMock()
        mock_client.get.return_value = None
        with patch("bot.writer_generation_tracker._connect_redis", return_value=(mock_client, "")):
            from bot.writer_generation_tracker import get_redis_generation
            gen, err = get_redis_generation()
            self.assertEqual(gen, 0)
            self.assertEqual(err, "generation_key_missing")

    def test_returns_zero_and_error_on_redis_exception(self) -> None:
        mock_client = MagicMock()
        mock_client.get.side_effect = RuntimeError("connection refused")
        with patch("bot.writer_generation_tracker._connect_redis", return_value=(mock_client, "")):
            from bot.writer_generation_tracker import get_redis_generation
            gen, err = get_redis_generation()
            self.assertEqual(gen, 0)
            self.assertIn("redis_read_error", err)

    def test_uses_custom_generation_key_from_env(self) -> None:
        mock_client = MagicMock()
        mock_client.get.return_value = "3"
        with patch("bot.writer_generation_tracker._connect_redis", return_value=(mock_client, "")), \
             patch.dict(os.environ, {"NIJA_LEASE_GENERATION_KEY": "custom:gen:key"}, clear=False):
            from bot.writer_generation_tracker import get_redis_generation
            get_redis_generation()
            mock_client.get.assert_called_once_with("custom:gen:key")


class TestValidateGeneration(unittest.TestCase):
    """Tests for validate_generation()."""

    def test_ok_when_local_and_redis_match(self) -> None:
        with patch.dict(os.environ, {"NIJA_WRITER_LEASE_GENERATION": "5"}, clear=False), \
             patch("bot.writer_generation_tracker.get_redis_generation", return_value=(5, "")):
            from bot.writer_generation_tracker import validate_generation
            ok, local, redis_gen, err = validate_generation()
            self.assertTrue(ok)
            self.assertEqual(local, 5)
            self.assertEqual(redis_gen, 5)
            self.assertEqual(err, "")

    def test_fails_when_local_not_set(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NIJA_WRITER_LEASE_GENERATION", None)
            with patch("bot.writer_generation_tracker.get_redis_generation", return_value=(5, "")):
                from bot.writer_generation_tracker import validate_generation
                ok, local, redis_gen, err = validate_generation()
                self.assertFalse(ok)
                self.assertEqual(local, 0)
                self.assertIn("local_generation_not_set", err)

    def test_fails_when_redis_generation_missing(self) -> None:
        with patch.dict(os.environ, {"NIJA_WRITER_LEASE_GENERATION": "5"}, clear=False), \
             patch("bot.writer_generation_tracker.get_redis_generation", return_value=(0, "generation_key_missing")):
            from bot.writer_generation_tracker import validate_generation
            ok, local, redis_gen, err = validate_generation()
            self.assertFalse(ok)
            self.assertIn("redis_read_failed", err)

    def test_fails_on_generation_mismatch(self) -> None:
        with patch.dict(os.environ, {"NIJA_WRITER_LEASE_GENERATION": "3"}, clear=False), \
             patch("bot.writer_generation_tracker.get_redis_generation", return_value=(7, "")):
            from bot.writer_generation_tracker import validate_generation
            ok, local, redis_gen, err = validate_generation()
            self.assertFalse(ok)
            self.assertEqual(local, 3)
            self.assertEqual(redis_gen, 7)
            self.assertIn("generation_mismatch", err)
            self.assertIn("local=3", err)
            self.assertIn("redis=7", err)

    def test_fails_when_redis_read_error(self) -> None:
        with patch.dict(os.environ, {"NIJA_WRITER_LEASE_GENERATION": "5"}, clear=False), \
             patch("bot.writer_generation_tracker.get_redis_generation", return_value=(0, "connection_refused")):
            from bot.writer_generation_tracker import validate_generation
            ok, local, redis_gen, err = validate_generation()
            self.assertFalse(ok)
            self.assertIn("redis_read_failed", err)


class TestValidateGenerationForHeartbeat(unittest.TestCase):
    """Tests for validate_generation_for_heartbeat()."""

    def test_returns_ok_when_redis_not_configured(self) -> None:
        with patch("bot.redis_env.get_redis_url", return_value=""):
            from bot.writer_generation_tracker import validate_generation_for_heartbeat
            ok, err = validate_generation_for_heartbeat()
            self.assertTrue(ok)
            self.assertEqual(err, "")

    def test_returns_ok_when_lease_not_yet_acquired(self) -> None:
        with patch("bot.redis_env.get_redis_url", return_value="redis://localhost:6379"), \
             patch.dict(os.environ, {
                 "NIJA_WRITER_LEASE_ACQUIRED": "0",
                 "NIJA_WRITER_FENCING_TOKEN_FALLBACK": "0",
             }, clear=False):
            from bot.writer_generation_tracker import validate_generation_for_heartbeat
            ok, err = validate_generation_for_heartbeat()
            self.assertTrue(ok)
            self.assertEqual(err, "")

    def test_returns_ok_when_generation_matches(self) -> None:
        with patch("bot.redis_env.get_redis_url", return_value="redis://localhost:6379"), \
             patch.dict(os.environ, {
                 "NIJA_WRITER_LEASE_ACQUIRED": "1",
                 "NIJA_WRITER_FENCING_TOKEN_FALLBACK": "0",
             }, clear=False), \
             patch("bot.writer_generation_tracker.validate_generation", return_value=(True, 5, 5, "")):
            from bot.writer_generation_tracker import validate_generation_for_heartbeat
            ok, err = validate_generation_for_heartbeat()
            self.assertTrue(ok)
            self.assertEqual(err, "")

    def test_returns_failure_on_generation_mismatch(self) -> None:
        with patch("bot.redis_env.get_redis_url", return_value="redis://localhost:6379"), \
             patch.dict(os.environ, {
                 "NIJA_WRITER_LEASE_ACQUIRED": "1",
                 "NIJA_WRITER_FENCING_TOKEN_FALLBACK": "0",
             }, clear=False), \
             patch("bot.writer_generation_tracker.validate_generation",
                   return_value=(False, 3, 7, "generation_mismatch:local=3 redis=7")):
            from bot.writer_generation_tracker import validate_generation_for_heartbeat
            ok, err = validate_generation_for_heartbeat()
            self.assertFalse(ok)
            self.assertIn("generation_mismatch", err)

    def test_returns_failure_on_redis_read_error(self) -> None:
        with patch("bot.redis_env.get_redis_url", return_value="redis://localhost:6379"), \
             patch.dict(os.environ, {
                 "NIJA_WRITER_LEASE_ACQUIRED": "1",
                 "NIJA_WRITER_FENCING_TOKEN_FALLBACK": "0",
             }, clear=False), \
             patch("bot.writer_generation_tracker.validate_generation",
                   return_value=(False, 5, 0, "redis_read_failed:connection_refused")):
            from bot.writer_generation_tracker import validate_generation_for_heartbeat
            ok, err = validate_generation_for_heartbeat()
            self.assertFalse(ok)
            self.assertIn("generation_mismatch", err)

    def test_skips_generation_check_in_fallback_mode(self) -> None:
        with patch("bot.redis_env.get_redis_url", return_value="redis://localhost:6379"), \
             patch.dict(os.environ, {
                 "NIJA_WRITER_LEASE_ACQUIRED": "0",
                 "NIJA_WRITER_FENCING_TOKEN_FALLBACK": "1",
             }, clear=False):
            from bot.writer_generation_tracker import validate_generation_for_heartbeat
            ok, err = validate_generation_for_heartbeat()
            self.assertTrue(ok)
            self.assertEqual(err, "")


class TestAttemptLockReacquisition(unittest.TestCase):
    """Tests for attempt_lock_reacquisition()."""

    def test_fails_when_no_platform_key(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KRAKEN_PLATFORM_API_KEY", None)
            os.environ.pop("KRAKEN_API_KEY", None)
            # Patch SEAK halt to avoid side effects.
            mock_seak = MagicMock()
            with patch("bot.single_execution_authority_kernel.get_seak", return_value=mock_seak):
                from bot.writer_generation_tracker import attempt_lock_reacquisition
                success, gen, err = attempt_lock_reacquisition(timeout_s=0.1)
            self.assertFalse(success)
            self.assertEqual(gen, 0)
            self.assertIn("no_platform_key", err)

    def test_succeeds_when_manager_returns_valid_version(self) -> None:
        mock_seak = MagicMock()
        mock_manager = MagicMock()
        mock_manager.ensure_writer_lock.return_value = 8

        with patch.dict(os.environ, {
            "KRAKEN_PLATFORM_API_KEY": "test-key",
            "NIJA_WRITER_LEASE_GENERATION": "8",
        }, clear=False), \
             patch("bot.single_execution_authority_kernel.get_seak", return_value=mock_seak), \
             patch("bot.distributed_nonce_manager.get_distributed_nonce_manager", return_value=mock_manager), \
             patch("bot.distributed_nonce_manager.make_api_key_id", return_value="abc123"):
            from bot.writer_generation_tracker import attempt_lock_reacquisition
            success, gen, err = attempt_lock_reacquisition(timeout_s=2.0)
        self.assertTrue(success)
        self.assertEqual(gen, 8)
        self.assertEqual(err, "")

    def test_halts_seak_before_reacquisition(self) -> None:
        """SEAK must be halted before any re-acquisition attempt."""
        halt_called = threading.Event()

        class _MockSEAK:
            def emergency_halt(self, reason: str) -> None:
                halt_called.set()

            def resume(self, caller: str = "") -> None:
                pass

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KRAKEN_PLATFORM_API_KEY", None)
            os.environ.pop("KRAKEN_API_KEY", None)
            with patch("bot.single_execution_authority_kernel.get_seak", return_value=_MockSEAK()):
                from bot.writer_generation_tracker import attempt_lock_reacquisition
                attempt_lock_reacquisition(timeout_s=0.05)

        self.assertTrue(halt_called.is_set(), "SEAK.emergency_halt() must be called before re-acquisition")


class TestCheckAndHandleGenerationMismatch(unittest.TestCase):
    """Tests for check_and_handle_generation_mismatch()."""

    def test_returns_true_when_no_mismatch(self) -> None:
        with patch("bot.writer_generation_tracker.validate_generation", return_value=(True, 5, 5, "")):
            from bot.writer_generation_tracker import check_and_handle_generation_mismatch
            result = check_and_handle_generation_mismatch()
            self.assertTrue(result)

    def test_returns_true_after_successful_reacquisition(self) -> None:
        mock_seak = MagicMock()
        with patch("bot.writer_generation_tracker.validate_generation",
                   return_value=(False, 3, 7, "generation_mismatch:local=3 redis=7")), \
             patch("bot.writer_generation_tracker.attempt_lock_reacquisition",
                   return_value=(True, 8, "")), \
             patch("bot.single_execution_authority_kernel.get_seak", return_value=mock_seak):
            from bot.writer_generation_tracker import check_and_handle_generation_mismatch
            result = check_and_handle_generation_mismatch()
        self.assertTrue(result)
        mock_seak.resume.assert_called_once()

    def test_returns_false_and_enters_emergency_stop_on_failed_reacquisition(self) -> None:
        mock_seak = MagicMock()
        mock_sm = MagicMock()

        with patch("bot.writer_generation_tracker.validate_generation",
                   return_value=(False, 3, 7, "generation_mismatch:local=3 redis=7")), \
             patch("bot.writer_generation_tracker.attempt_lock_reacquisition",
                   return_value=(False, 0, "lock_reacquisition_failed:timeout")), \
             patch("bot.single_execution_authority_kernel.get_seak", return_value=mock_seak), \
             patch("bot.trading_state_machine.get_state_machine", return_value=mock_sm), \
             patch("bot.trading_state_machine.TradingState") as mock_ts:
            mock_ts.EMERGENCY_STOP = "EMERGENCY_STOP"
            from bot.writer_generation_tracker import check_and_handle_generation_mismatch
            result = check_and_handle_generation_mismatch()

        self.assertFalse(result)
        mock_sm.transition_to.assert_called_once()
        call_args = mock_sm.transition_to.call_args
        self.assertIn("EMERGENCY_STOP", str(call_args))

    def test_logs_critical_on_mismatch(self) -> None:
        import logging
        with patch("bot.writer_generation_tracker.validate_generation",
                   return_value=(False, 2, 9, "generation_mismatch:local=2 redis=9")), \
             patch("bot.writer_generation_tracker.attempt_lock_reacquisition",
                   return_value=(True, 10, "")), \
             patch("bot.single_execution_authority_kernel.get_seak", return_value=MagicMock()), \
             self.assertLogs("nija.writer_generation_tracker", level=logging.CRITICAL):
            from bot.writer_generation_tracker import check_and_handle_generation_mismatch
            check_and_handle_generation_mismatch()


class TestHeartbeatGenerationIntegration(unittest.TestCase):
    """Tests for generation validation integration in authority_heartbeat._check_authority_once."""

    def test_heartbeat_fails_when_generation_mismatches(self) -> None:
        """_check_authority_once must return failure when generation diverges."""
        with patch.dict(os.environ, {
            "NIJA_WRITER_FENCING_TOKEN": "test-token",
            "NIJA_WRITER_LEASE_ACQUIRED": "1",
            "NIJA_WRITER_FENCING_TOKEN_FALLBACK": "0",
        }, clear=False), \
             patch("bot.redis_env.get_redis_url", return_value="redis://localhost:6379"), \
             patch("bot.execution_authority_context.assert_distributed_writer_authority", return_value=None), \
             patch("bot.writer_generation_tracker.validate_generation_for_heartbeat",
                   return_value=(False, "generation_mismatch:local=3 redis=7")):
            from bot.authority_heartbeat import _check_authority_once
            ok, err = _check_authority_once(timeout_s=2.0)
        self.assertFalse(ok)
        self.assertIn("generation_mismatch", err)

    def test_heartbeat_passes_when_generation_matches(self) -> None:
        """_check_authority_once must pass when generation is current."""
        with patch.dict(os.environ, {
            "NIJA_WRITER_FENCING_TOKEN": "test-token",
            "NIJA_WRITER_LEASE_ACQUIRED": "1",
            "NIJA_WRITER_FENCING_TOKEN_FALLBACK": "0",
        }, clear=False), \
             patch("bot.redis_env.get_redis_url", return_value="redis://localhost:6379"), \
             patch("bot.execution_authority_context.assert_distributed_writer_authority", return_value=None), \
             patch("bot.writer_generation_tracker.validate_generation_for_heartbeat",
                   return_value=(True, "")):
            from bot.authority_heartbeat import _check_authority_once
            ok, err = _check_authority_once(timeout_s=2.0)
        self.assertTrue(ok)
        self.assertEqual(err, "")

    def test_heartbeat_skips_generation_check_in_fallback_mode(self) -> None:
        """Generation check must be skipped when is_fallback=True."""
        with patch.dict(os.environ, {
            "NIJA_WRITER_FENCING_TOKEN": "test-token",
            "NIJA_WRITER_LEASE_ACQUIRED": "0",
            "NIJA_WRITER_FENCING_TOKEN_FALLBACK": "1",
        }, clear=False), \
             patch("bot.redis_env.get_redis_url", return_value="redis://localhost:6379"):
            import redis as _redis_lib
            mock_redis_client = MagicMock()
            mock_redis_client.ping.return_value = True
            with patch.object(_redis_lib, "from_url", return_value=mock_redis_client), \
                 patch("bot.writer_generation_tracker.validate_generation_for_heartbeat",
                       return_value=(False, "generation_mismatch:local=0 redis=5")) as mock_gen_check:
                from bot.authority_heartbeat import _check_authority_once
                ok, err = _check_authority_once(timeout_s=2.0)
            # Generation check should NOT have been called in fallback mode.
            mock_gen_check.assert_not_called()
        self.assertTrue(ok)

    def test_heartbeat_generation_exception_is_non_fatal(self) -> None:
        """A generation validation exception must not crash the heartbeat check."""
        with patch.dict(os.environ, {
            "NIJA_WRITER_FENCING_TOKEN": "test-token",
            "NIJA_WRITER_LEASE_ACQUIRED": "1",
            "NIJA_WRITER_FENCING_TOKEN_FALLBACK": "0",
        }, clear=False), \
             patch("bot.redis_env.get_redis_url", return_value="redis://localhost:6379"), \
             patch("bot.execution_authority_context.assert_distributed_writer_authority", return_value=None), \
             patch("bot.writer_generation_tracker.validate_generation_for_heartbeat",
                   side_effect=RuntimeError("unexpected tracker error")):
            from bot.authority_heartbeat import _check_authority_once
            ok, err = _check_authority_once(timeout_s=2.0)
        # Exception in generation check is non-fatal; authority check still passes.
        self.assertTrue(ok)
        self.assertEqual(err, "")


if __name__ == "__main__":
    unittest.main()
