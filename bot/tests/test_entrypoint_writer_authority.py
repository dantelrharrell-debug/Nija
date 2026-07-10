from __future__ import annotations

import os
import sys
import threading
import types
import unittest
from unittest.mock import MagicMock, patch

from bot.entrypoint_writer_authority import EntrypointWriterAuthority


_ENV_KEYS = (
    "LIVE_CAPITAL_VERIFIED",
    "DRY_RUN_MODE",
    "PAPER_MODE",
    "KRAKEN_PLATFORM_API_KEY",
    "NIJA_WRITER_LOCK_SCOPE",
    "NIJA_WRITER_LOCK_KEY",
    "NIJA_WRITER_LOCK_META_KEY",
    "NIJA_WRITER_FENCING_KEY",
    "NIJA_WRITER_FENCING_TOKEN",
    "NIJA_WRITER_OWNER_ID",
    "NIJA_WRITER_INSTANCE_ID",
    "NIJA_WRITER_LEASE_GENERATION",
    "NIJA_WRITER_LEASE_ACQUIRED",
    "NIJA_LOCK_ACQUIRED",
    "NIJA_WRITER_HEARTBEAT_ACTIVE",
    "NIJA_WRITER_HEARTBEAT_LAST_TS",
    "NIJA_WRITER_HEARTBEAT_ALIVE_TS",
    "NIJA_ENTRYPOINT_WRITER_LOCK_WAIT_S",
    "NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK",
    "NIJA_CONFIRM_BYPASS_RISKS",
    "NIJA_WRITER_FENCING_TOKEN_FALLBACK",
)


class EntrypointWriterAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.saved = {key: os.environ.get(key) for key in _ENV_KEYS}
        for key in _ENV_KEYS:
            os.environ.pop(key, None)
        os.environ["LIVE_CAPITAL_VERIFIED"] = "true"
        os.environ["DRY_RUN_MODE"] = "false"
        os.environ["PAPER_MODE"] = "false"
        os.environ["KRAKEN_PLATFORM_API_KEY"] = "test-platform-key"
        os.environ["NIJA_ENTRYPOINT_WRITER_LOCK_WAIT_S"] = "0"

    def tearDown(self) -> None:
        for key in _ENV_KEYS:
            os.environ.pop(key, None)
        for key, value in self.saved.items():
            if value is not None:
                os.environ[key] = value

    @staticmethod
    def _identity():
        return (
            {"instance_id": "render-instance-1", "hostname": "host-1"},
            "instance=render-instance-1|host=host-1|pid=123",
            "render-instance-1",
        )

    def test_atomic_acquire_publishes_fencing_lineage_before_nonce_startup(self):
        client = MagicMock()
        client.eval.return_value = [17, "17:owner", 60000, 23]
        client.set.return_value = True

        runtime = EntrypointWriterAuthority()
        with (
            patch(
                "bot.entrypoint_writer_authority._connect_redis",
                return_value=(client, "rediss://example", ""),
            ),
            patch(
                "bot.entrypoint_writer_authority._instance_identity",
                side_effect=self._identity,
            ),
            patch.object(runtime, "_start_heartbeat"),
        ):
            result = runtime.acquire_once()

        self.assertTrue(result.acquired)
        self.assertEqual(result.token, "17")
        self.assertEqual(result.generation, 23)
        self.assertEqual(os.environ["NIJA_WRITER_FENCING_TOKEN"], "17")
        self.assertEqual(os.environ["NIJA_WRITER_LEASE_GENERATION"], "23")
        self.assertEqual(os.environ["NIJA_WRITER_LEASE_ACQUIRED"], "1")
        self.assertEqual(os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"], "1")
        self.assertTrue(os.environ["NIJA_WRITER_LOCK_KEY"].startswith("nija:writer_lock:"))

    def test_active_writer_is_never_force_deleted(self):
        client = MagicMock()
        client.eval.return_value = [0, "9:other-instance", 42000, 8]

        runtime = EntrypointWriterAuthority()
        with (
            patch(
                "bot.entrypoint_writer_authority._connect_redis",
                return_value=(client, "rediss://example", ""),
            ),
            patch(
                "bot.entrypoint_writer_authority._instance_identity",
                side_effect=self._identity,
            ),
        ):
            result = runtime.acquire_once()

        self.assertFalse(result.acquired)
        self.assertEqual(result.error, "active_writer_lock_held")
        self.assertEqual(result.holder, "9:other-instance")
        client.delete.assert_not_called()

    def test_redis_unavailable_remains_fail_closed_without_explicit_fallback(self):
        runtime = EntrypointWriterAuthority()
        with patch(
            "bot.entrypoint_writer_authority._connect_redis",
            return_value=(None, "rediss://example", "redis_unavailable:test"),
        ):
            result = runtime.acquire_once()

        self.assertFalse(result.acquired)
        self.assertEqual(result.error, "redis_unavailable:test")
        self.assertNotIn("NIJA_WRITER_FENCING_TOKEN", os.environ)

    def test_local_fallback_requires_risk_confirmation(self):
        os.environ["NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK"] = "true"
        runtime = EntrypointWriterAuthority()
        with patch(
            "bot.entrypoint_writer_authority._connect_redis",
            return_value=(None, "", "redis_unavailable:test"),
        ):
            denied = runtime.acquire_once()
        self.assertFalse(denied.acquired)

        os.environ["NIJA_CONFIRM_BYPASS_RISKS"] = "true"
        runtime = EntrypointWriterAuthority()
        with (
            patch(
                "bot.entrypoint_writer_authority._connect_redis",
                return_value=(None, "", "redis_unavailable:test"),
            ),
            patch(
                "bot.entrypoint_writer_authority._instance_identity",
                side_effect=self._identity,
            ),
        ):
            granted = runtime.acquire_once()

        self.assertTrue(granted.acquired)
        self.assertTrue(granted.local_fallback)
        self.assertEqual(os.environ["NIJA_WRITER_FENCING_TOKEN_FALLBACK"], "1")

    def test_release_uses_compare_and_delete_script(self):
        client = MagicMock()
        client.eval.side_effect = [
            [31, "31:owner", 60000, 44],
            1,
        ]
        client.set.return_value = True

        runtime = EntrypointWriterAuthority()
        with (
            patch(
                "bot.entrypoint_writer_authority._connect_redis",
                return_value=(client, "rediss://example", ""),
            ),
            patch(
                "bot.entrypoint_writer_authority._instance_identity",
                side_effect=self._identity,
            ),
            patch.object(runtime, "_start_heartbeat"),
        ):
            acquired = runtime.acquire_once()
            released = runtime.release()

        self.assertTrue(acquired.acquired)
        self.assertTrue(released)
        release_call = client.eval.call_args_list[-1]
        self.assertIn("current ~= ARGV[1]", release_call.args[0])
        self.assertNotIn("NIJA_WRITER_FENCING_TOKEN", os.environ)


class BotMainAuthorityOrderingTests(unittest.TestCase):
    def setUp(self) -> None:
        import bot.bot_main as bot_main

        self.bot_main = bot_main
        bot_main._shutdown_event.clear()
        bot_main._startup_complete = False

    def tearDown(self) -> None:
        self.bot_main._shutdown_event.clear()
        self.bot_main._startup_complete = False

    def test_bootstrap_is_not_called_when_writer_authority_is_missing(self):
        with (
            patch.object(
                self.bot_main,
                "_acquire_writer_authority_before_nonce",
                return_value=False,
            ),
            patch.object(self.bot_main, "_run_self_healing_startup") as startup,
            patch.object(self.bot_main.signal, "signal"),
        ):
            code = self.bot_main.main()

        self.assertEqual(code, 1)
        startup.assert_not_called()

    def test_authority_precedes_nonce_and_broker_bootstrap(self):
        order: list[str] = []
        core_loop = types.ModuleType("bot.nija_core_loop")

        def start_trading_engine(_broker):
            order.append("trading")
            self.bot_main._shutdown_event.set()

        core_loop.start_trading_engine = start_trading_engine

        def acquire():
            order.append("authority")
            return True

        def bootstrap():
            order.append("nonce_and_broker")
            return True, object(), "kraken"

        def advance():
            order.append("fsm")
            return True

        previous = sys.modules.get("bot.nija_core_loop")
        sys.modules["bot.nija_core_loop"] = core_loop
        try:
            with (
                patch.object(
                    self.bot_main,
                    "_acquire_writer_authority_before_nonce",
                    side_effect=acquire,
                ),
                patch.object(
                    self.bot_main,
                    "_run_self_healing_startup",
                    side_effect=bootstrap,
                ),
                patch.object(
                    self.bot_main,
                    "_advance_bootstrap_fsm_to_running_supervised",
                    side_effect=advance,
                ),
                patch.object(self.bot_main, "_release_writer_authority"),
                patch.object(self.bot_main.signal, "signal"),
            ):
                code = self.bot_main.main()
        finally:
            if previous is None:
                sys.modules.pop("bot.nija_core_loop", None)
            else:
                sys.modules["bot.nija_core_loop"] = previous

        self.assertEqual(code, 0)
        self.assertEqual(order, ["authority", "nonce_and_broker", "fsm", "trading"])


if __name__ == "__main__":
    unittest.main()
