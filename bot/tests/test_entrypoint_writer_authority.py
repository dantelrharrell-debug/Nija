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
    "NIJA_WRITER_RELEASE_HEARTBEAT_JOIN_S",
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

    def test_release_joins_heartbeat_before_deleting_owned_lease(self):
        order = []
        client = MagicMock()

        def delete_owned_lease(*_args):
            order.append("delete")
            return 1

        client.eval.side_effect = delete_owned_lease

        class Heartbeat:
            alive = True

            def is_alive(self):
                return self.alive

            def join(self, timeout):
                self.assert_timeout = timeout
                order.append("join")
                self.alive = False

        runtime = EntrypointWriterAuthority()
        runtime._client = client
        runtime._lock_key = "nija:writer_lock:test"
        runtime._meta_key = "nija:writer_lock_meta:test"
        runtime._lock_value = "17:local-owner"
        runtime._heartbeat_thread = Heartbeat()

        self.assertTrue(runtime.release())
        self.assertEqual(order, ["join", "delete"])
        self.assertIsNone(runtime._heartbeat_thread)
        self.assertEqual(os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"], "0")

    def test_release_proceeds_with_deletion_when_heartbeat_cannot_quiesce(self):
        """release() must delete the lock even when the heartbeat thread survives the join.

        The heartbeat sets _stop before the join; the daemon thread therefore
        cannot reacquire the lock.  Skipping deletion would leave a live lock in
        Redis and force the successor instance to wait a full TTL before it can
        become the active writer.
        """
        client = MagicMock()
        client.eval.return_value = 1  # compare-and-delete succeeds

        class StuckHeartbeat:
            def is_alive(self):
                return True

            def join(self, timeout):
                pass

        runtime = EntrypointWriterAuthority()
        runtime._client = client
        runtime._lock_key = "nija:writer_lock:test"
        runtime._meta_key = "nija:writer_lock_meta:test"
        runtime._lock_value = "17:local-owner"
        runtime._heartbeat_thread = StuckHeartbeat()

        self.assertTrue(runtime.release())
        client.eval.assert_called_once()

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

    def test_supervised_thread_evidence_publishes_only_from_live_writer(self):
        heartbeat = types.SimpleNamespace(is_alive=lambda: True)
        runtime = types.SimpleNamespace(
            acquired=True,
            lost=False,
            _heartbeat_thread=heartbeat,
        )
        coordinator = MagicMock()

        with (
            patch.object(self.bot_main, "_writer_authority_runtime", runtime),
            patch(
                "bot.startup_coordinator.get_startup_coordinator",
                return_value=coordinator,
            ),
            patch.object(
                self.bot_main.threading,
                "enumerate",
                return_value=[self.bot_main.threading.current_thread(), heartbeat],
            ),
        ):
            self.assertTrue(self.bot_main._publish_supervised_thread_evidence())

        coordinator.record_threads_supervised.assert_called_once_with(
            1,
            bootstrap_state="RUNNING_SUPERVISED",
        )

    def test_supervised_thread_evidence_blocks_without_live_heartbeat(self):
        runtime = types.SimpleNamespace(
            acquired=True,
            lost=False,
            _heartbeat_thread=types.SimpleNamespace(is_alive=lambda: False),
        )
        coordinator = MagicMock()

        with (
            patch.object(self.bot_main, "_writer_authority_runtime", runtime),
            patch(
                "bot.startup_coordinator.get_startup_coordinator",
                return_value=coordinator,
            ),
        ):
            self.assertFalse(self.bot_main._publish_supervised_thread_evidence())

        coordinator.record_threads_supervised.assert_not_called()

    def test_atomic_supervised_thread_record_sets_complete_proof(self):
        from bot.startup_coordinator import (
            StartupCoordinator,
            StartupCoordinatorState,
            StartupEvent,
        )

        coordinator = StartupCoordinator()
        version = coordinator.record_threads_supervised(
            2,
            bootstrap_state="RUNNING_SUPERVISED",
        )

        self.assertGreater(version, 0)
        with coordinator._lock:
            self.assertEqual(coordinator._runtime.threads_launched, 2)
            self.assertTrue(coordinator._runtime.threads_confirmed_running)
            self.assertEqual(
                coordinator._runtime.bootstrap_state,
                "RUNNING_SUPERVISED",
            )
            self.assertEqual(
                coordinator._runtime.coordinator_state,
                StartupCoordinatorState.SUPERVISED_RUNNING,
            )
            history = list(coordinator._history)

        self.assertEqual(
            [entry["event"] for entry in history],
            [
                StartupEvent.THREADS_LAUNCHED.value,
                StartupEvent.THREADS_CONFIRMED_RUNNING.value,
            ],
        )
        self.assertEqual(
            [entry["state"] for entry in history],
            [
                StartupCoordinatorState.THREADS_PENDING.value,
                StartupCoordinatorState.SUPERVISED_RUNNING.value,
            ],
        )

        repeated_version = coordinator.record_threads_supervised(
            2,
            bootstrap_state="RUNNING_SUPERVISED",
        )
        self.assertEqual(repeated_version, version)
        with coordinator._lock:
            self.assertEqual(list(coordinator._history), history)

    def test_running_supervised_handoff_publishes_thread_evidence(self):
        from bot.bootstrap_state_machine import BootstrapState

        fsm = types.SimpleNamespace(state=BootstrapState.RUNNING_SUPERVISED)
        with (
            patch(
                "bot.bootstrap_state_machine.get_bootstrap_fsm",
                return_value=fsm,
            ),
            patch.object(self.bot_main, "_apply_bootstrap_i12_repair_direct"),
            patch.object(
                self.bot_main,
                "_publish_supervised_thread_evidence",
                return_value=True,
            ) as publish,
        ):
            self.assertTrue(
                self.bot_main._advance_bootstrap_fsm_to_running_supervised()
            )

        publish.assert_called_once_with()

    def test_running_supervised_handoff_fails_closed_without_thread_evidence(self):
        from bot.bootstrap_state_machine import BootstrapState

        fsm = types.SimpleNamespace(state=BootstrapState.RUNNING_SUPERVISED)
        with (
            patch(
                "bot.bootstrap_state_machine.get_bootstrap_fsm",
                return_value=fsm,
            ),
            patch.object(self.bot_main, "_apply_bootstrap_i12_repair_direct"),
            patch.object(
                self.bot_main,
                "_publish_supervised_thread_evidence",
                return_value=False,
            ) as publish,
        ):
            self.assertFalse(
                self.bot_main._advance_bootstrap_fsm_to_running_supervised()
            )

        publish.assert_called_once_with()

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
        prebootstrap_manager = types.SimpleNamespace(
            _fsm_initialized=True,
            _platform_brokers={"kraken": types.SimpleNamespace(connected=True)},
        )

        bootstrap_broker = types.SimpleNamespace(connected=True)
        published_strategy = types.SimpleNamespace(
            broker=bootstrap_broker,
            run_cycle=lambda: None,
        )

        def start_trading_engine(strategy):
            self.assertIs(strategy, published_strategy)
            order.append("trading")
            self.bot_main._shutdown_event.set()

        core_loop.start_trading_engine = start_trading_engine

        def acquire():
            order.append("authority")
            return True

        def prebootstrap():
            order.append("prebootstrap")
            return prebootstrap_manager

        def bootstrap():
            order.append("nonce_and_broker")
            return True, bootstrap_broker, "kraken"

        def advance():
            order.append("fsm")
            return True

        def publish_strategy(broker):
            self.assertIs(broker, bootstrap_broker)
            order.append("strategy")
            return published_strategy

        previous = sys.modules.get("bot.nija_core_loop")
        sys.modules["bot.nija_core_loop"] = core_loop
        try:
            with (
                patch.object(
                    self.bot_main,
                    "_acquire_writer_authority_before_nonce",
                    side_effect=acquire,
                ),
                patch(
                    "bot.canonical_broker_prebootstrap_v22.prepare_canonical_broker_runtime",
                    side_effect=prebootstrap,
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
                patch.object(
                    self.bot_main,
                    "_publish_canonical_strategy_for_runtime",
                    side_effect=publish_strategy,
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
        self.assertEqual(
            order,
            [
                "authority",
                "prebootstrap",
                "nonce_and_broker",
                "fsm",
                "strategy",
                "trading",
            ],
        )

    def test_prebootstrap_requires_connected_platform_broker(self):
        manager = types.SimpleNamespace(_fsm_initialized=True, _platform_brokers={})

        with (
            patch.object(
                self.bot_main,
                "_acquire_writer_authority_before_nonce",
                return_value=True,
            ),
            patch(
                "bot.canonical_broker_prebootstrap_v22.prepare_canonical_broker_runtime",
                return_value=manager,
            ),
            patch.object(self.bot_main, "_run_self_healing_startup") as startup,
            patch.object(self.bot_main, "_release_writer_authority"),
            patch.object(self.bot_main.signal, "signal"),
        ):
            code = self.bot_main.main()

        self.assertEqual(code, 1)
        startup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
