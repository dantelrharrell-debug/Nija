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
    "NIJA_WRITER_GENERATION",
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
    "NIJA_CORE_THREAD_ALIVE",
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
        self.assertEqual(os.environ["NIJA_WRITER_GENERATION"], "23")
        self.assertEqual(os.environ["NIJA_WRITER_LEASE_ACQUIRED"], "1")
        self.assertEqual(os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"], "1")
        self.assertTrue(os.environ["NIJA_WRITER_LOCK_KEY"].startswith("nija:writer_lock:"))

    def test_package_and_compatibility_imports_share_one_singleton(self):
        import importlib

        package_module = importlib.import_module("bot.entrypoint_writer_authority")
        compatibility_module = importlib.import_module("entrypoint_writer_authority")

        self.assertIs(compatibility_module, package_module)
        self.assertIs(
            compatibility_module.get_entrypoint_writer_authority(),
            package_module.get_entrypoint_writer_authority(),
        )

    def test_explicit_canonical_runtime_replaces_split_compatibility_singleton(self):
        import bot.entrypoint_writer_authority as authority

        original_runtime = authority.get_entrypoint_writer_authority()
        stale_runtime = types.SimpleNamespace(
            acquired=False,
            lost=False,
            _local_fallback=False,
            _generation=0,
        )
        legacy_module = types.ModuleType("entrypoint_writer_authority")
        legacy_module._SINGLETON = stale_runtime
        legacy_module.get_entrypoint_writer_authority = lambda: legacy_module._SINGLETON
        canonical_runtime = types.SimpleNamespace(
            acquired=True,
            lost=False,
            _local_fallback=False,
            _generation=91,
        )
        try:
            sys.modules["entrypoint_writer_authority"] = legacy_module
            selected = authority.bind_entrypoint_writer_authority_aliases(
                canonical_runtime
            )
            self.assertIs(selected, canonical_runtime)
            self.assertIs(
                sys.modules["entrypoint_writer_authority"],
                sys.modules["bot.entrypoint_writer_authority"],
            )
            self.assertIs(
                authority.get_entrypoint_writer_authority(), canonical_runtime
            )
        finally:
            authority.bind_entrypoint_writer_authority_aliases(original_runtime)

    def test_acquire_reconciles_only_after_writer_state_becomes_active(self):
        client = MagicMock()
        client.eval.return_value = [17, "17:owner", 60000, 23]
        client.set.return_value = True
        runtime = EntrypointWriterAuthority()
        calls = []
        readiness = types.ModuleType("three_venue_execution_readiness")
        readiness.reconcile_execution_readiness = lambda **kwargs: calls.append(
            (kwargs, os.environ.get("NIJA_WRITER_STATE"))
        )

        with (
            patch.dict(sys.modules, {"three_venue_execution_readiness": readiness}),
            patch(
                "bot.entrypoint_writer_authority._connect_redis",
                return_value=(client, "rediss://example", ""),
            ),
            patch(
                "bot.entrypoint_writer_authority._instance_identity",
                side_effect=self._identity,
            ),
            patch.object(runtime, "_start_heartbeat"),
            patch.object(runtime, "_start_scan_started_watchdog"),
        ):
            result = runtime.acquire_once()

        self.assertTrue(result.acquired)
        self.assertEqual(
            calls,
            [({"trigger": "writer_acquired", "force": True}, "ACTIVE")],
        )

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

    def test_release_skips_deletion_when_heartbeat_cannot_quiesce(self):
        """An in-flight renewal must never race compare-and-delete."""
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

        self.assertFalse(runtime.release())
        client.eval.assert_not_called()
        self.assertIsNotNone(runtime._heartbeat_thread)
        self.assertEqual(os.environ["NIJA_WRITER_LEASE_ACQUIRED"], "0")

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

    def test_register_core_thread_publishes_liveness_and_reconciles_immediately(self):
        runtime = EntrypointWriterAuthority()
        calls = []
        readiness = types.ModuleType("three_venue_execution_readiness")
        readiness.reconcile_execution_readiness = lambda **kwargs: calls.append(kwargs)

        class _Thread:
            name = "nija-core-loop"
            ident = 123

            @staticmethod
            def is_alive():
                return True

        with patch.dict(sys.modules, {"three_venue_execution_readiness": readiness}):
            runtime.register_core_thread(_Thread())

        self.assertEqual(os.environ["NIJA_CORE_THREAD_ALIVE"], "1")
        self.assertEqual(
            calls,
            [{"trigger": "core_thread_registered", "force": True}],
        )

    def test_register_core_thread_clears_scan_deadline_exceeded(self):
        runtime = EntrypointWriterAuthority()
        runtime._scan_deadline_exceeded = True

        class _Thread:
            name = "nija-core-loop"
            ident = 123

            @staticmethod
            def is_alive():
                return True

        runtime.register_core_thread(_Thread())

        self.assertFalse(runtime._scan_deadline_exceeded)

    def test_callback_free_live_writer_loss_schedules_bounded_restart(self):
        runtime = EntrypointWriterAuthority()
        timer = MagicMock()
        runtime._heartbeat_thread = MagicMock(is_alive=MagicMock(return_value=True))

        with (
            patch.dict(
                os.environ,
                {"NIJA_WRITER_AUTHORITY_FALLBACK_RESTART_GRACE_S": "4"},
                clear=False,
            ),
            patch(
                "bot.entrypoint_writer_authority.threading.Timer",
                return_value=timer,
            ) as factory,
            patch("bot.entrypoint_writer_authority.os._exit") as force_exit,
        ):
            runtime._schedule_unhandled_loss_restart(
                "core_thread_registration_deadline_exceeded"
            )
            callback = factory.call_args.args[1]
            callback()

        factory.assert_called_once()
        self.assertEqual(factory.call_args.args[0], 4.0)
        self.assertEqual(timer.name, "entrypoint-writer-unhandled-loss-restart")
        self.assertTrue(timer.daemon)
        timer.start.assert_called_once_with()
        force_exit.assert_called_once_with(75)

    def test_confirmed_loss_callback_owns_restart_scheduling(self):
        runtime = EntrypointWriterAuthority()

        with patch("bot.entrypoint_writer_authority.threading.Timer") as factory:
            runtime._schedule_unhandled_loss_restart(
                "writer_lost",
                handler_confirmed=True,
            )

        factory.assert_not_called()

    def test_unconfirmed_loss_callback_falls_back_to_runtime_restart(self):
        runtime = EntrypointWriterAuthority()
        runtime._heartbeat_thread = MagicMock(is_alive=MagicMock(return_value=True))
        runtime.set_on_lost_callback(lambda _reason: None)
        timer = MagicMock()

        with patch(
            "bot.entrypoint_writer_authority.threading.Timer",
            return_value=timer,
        ) as factory:
            runtime._mark_lost("core_thread_registration_deadline_exceeded")

        factory.assert_called_once()
        timer.start.assert_called_once_with()

    def test_local_fallback_is_always_refused(self):
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

        self.assertFalse(granted.acquired)
        self.assertFalse(granted.local_fallback)
        self.assertNotIn("NIJA_WRITER_FENCING_TOKEN_FALLBACK", os.environ)

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
        self.assertNotIn("NIJA_WRITER_GENERATION", os.environ)


class BotMainAuthorityOrderingTests(unittest.TestCase):
    def setUp(self) -> None:
        import bot.bot_main as bot_main

        self.bot_main = bot_main
        self._previous_writer_runtime = bot_main._writer_authority_runtime
        bot_main._writer_authority_runtime = types.SimpleNamespace(
            arm_scan_start_deadline=MagicMock(),
            register_core_thread=MagicMock(),
        )
        bot_main._shutdown_event.clear()
        bot_main._startup_complete = False
        bot_main._core_loop_thread = None

    def tearDown(self) -> None:
        self.bot_main._writer_authority_runtime = self._previous_writer_runtime
        self.bot_main._shutdown_event.clear()
        self.bot_main._startup_complete = False
        self.bot_main._core_loop_thread = None

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

    def test_writer_acquisition_pins_exact_runtime_before_heartbeat_start(self):
        import bot.entrypoint_writer_authority as authority

        order: list[str] = []
        previous_monitor = self.bot_main._authority_heartbeat_monitor
        self.addCleanup(
            setattr,
            self.bot_main,
            "_authority_heartbeat_monitor",
            previous_monitor,
        )
        runtime = MagicMock()
        runtime.acquire_with_standby.return_value = types.SimpleNamespace(
            acquired=True,
            error="",
            holder="",
            pttl_ms=60000,
            token="writer-token-91",
            generation=91,
            instance_id="instance-91",
            local_fallback=False,
        )
        runtime._generation = 91
        monitor = MagicMock()

        def bind(value):
            self.assertIs(value, runtime)
            order.append("bind")
            return value

        def start_heartbeat():
            order.append("heartbeat")
            return monitor

        with (
            patch.object(
                authority,
                "get_entrypoint_writer_authority",
                return_value=runtime,
            ),
            patch.object(
                authority,
                "bind_entrypoint_writer_authority_aliases",
                side_effect=bind,
            ),
            patch(
                "bot.authority_heartbeat.start_authority_heartbeat",
                side_effect=start_heartbeat,
            ),
            patch(
                "bot.execution_authority_context.assert_distributed_writer_authority"
            ) as assert_writer,
        ):
            self.assertTrue(
                self.bot_main._acquire_writer_authority_before_nonce()
            )

        self.assertEqual(order, ["bind", "heartbeat"])
        assert_writer.assert_called_once_with()
        runtime.set_on_lost_callback.assert_called_once()
        callback = runtime.set_on_lost_callback.call_args.args[0]
        self.addCleanup(self.bot_main._shutdown_event.clear)
        with patch.object(
            self.bot_main,
            "_schedule_writer_authority_restart",
        ) as schedule_restart:
            handled = callback("core_thread_registration_deadline_exceeded")
        self.assertTrue(handled)
        schedule_restart.assert_called_once_with(
            "core_thread_registration_deadline_exceeded"
        )

    def test_post_acquisition_exception_releases_writer_and_revokes_readiness(self):
        import bot.entrypoint_writer_authority as authority

        runtime = MagicMock()
        runtime.acquire_with_standby.return_value = types.SimpleNamespace(
            acquired=True,
            error="",
            holder="",
            pttl_ms=60000,
            token="writer-token-91",
            generation=91,
            instance_id="instance-91",
            local_fallback=False,
        )
        previous_runtime = self.bot_main._writer_authority_runtime
        previous_monitor = self.bot_main._authority_heartbeat_monitor
        self.addCleanup(
            setattr,
            self.bot_main,
            "_writer_authority_runtime",
            previous_runtime,
        )
        self.addCleanup(
            setattr,
            self.bot_main,
            "_authority_heartbeat_monitor",
            previous_monitor,
        )

        with (
            patch.object(
                authority,
                "get_entrypoint_writer_authority",
                return_value=runtime,
            ),
            patch.object(
                authority,
                "bind_entrypoint_writer_authority_aliases",
                side_effect=RuntimeError("identity_bind_crashed"),
            ),
        ):
            self.assertFalse(
                self.bot_main._acquire_writer_authority_before_nonce()
            )

        runtime.release.assert_called_once_with()
        self.assertIsNone(self.bot_main._writer_authority_runtime)
        self.assertEqual(os.environ["NIJA_WRITER_LEASE_ACQUIRED"], "0")
        self.assertEqual(os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"], "0")

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
            return types.SimpleNamespace(
                name="TradingLoop",
                ident=777,
                is_alive=lambda: True,
            )

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

    def test_main_registers_core_thread_without_fabricating_scan_started(self):
        core_loop = types.ModuleType("bot.nija_core_loop")
        manager = types.SimpleNamespace(
            _fsm_initialized=True,
            _platform_brokers={"kraken": types.SimpleNamespace(connected=True)},
        )
        broker = types.SimpleNamespace(connected=True)
        strategy = types.SimpleNamespace(broker=broker, run_cycle=lambda: None)
        runtime = types.SimpleNamespace(
            arm_scan_start_deadline=MagicMock(),
            register_core_thread=MagicMock(),
            record_scan_started=MagicMock(),
        )

        class _TradingThread:
            name = "TradingLoop"
            ident = 777

            @staticmethod
            def is_alive():
                return True

        core_loop.start_trading_engine = lambda _strategy: _TradingThread()

        previous = sys.modules.get("bot.nija_core_loop")
        sys.modules["bot.nija_core_loop"] = core_loop
        try:
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
                patch.object(
                    self.bot_main,
                    "_run_self_healing_startup",
                    return_value=(True, broker, "kraken"),
                ),
                patch.object(
                    self.bot_main,
                    "_advance_bootstrap_fsm_to_running_supervised",
                    return_value=True,
                ),
                patch.object(
                    self.bot_main,
                    "_publish_canonical_strategy_for_runtime",
                    return_value=strategy,
                ),
                patch.object(self.bot_main, "_writer_authority_runtime", runtime),
                patch.object(self.bot_main, "_release_writer_authority"),
                patch.object(self.bot_main, "_keep_process_alive_after_loop_return"),
                patch.object(self.bot_main.signal, "signal"),
            ):
                code = self.bot_main.main()
        finally:
            if previous is None:
                sys.modules.pop("bot.nija_core_loop", None)
            else:
                sys.modules["bot.nija_core_loop"] = previous

        self.assertEqual(code, 0)
        runtime.arm_scan_start_deadline.assert_called_once_with("bot_main_step3")
        runtime.register_core_thread.assert_called_once()
        runtime.record_scan_started.assert_not_called()

    def test_main_does_not_record_scan_started_before_real_scan(self):
        core_loop = types.ModuleType("bot.nija_core_loop")
        manager = types.SimpleNamespace(
            _fsm_initialized=True,
            _platform_brokers={"kraken": types.SimpleNamespace(connected=True)},
        )
        broker = types.SimpleNamespace(connected=True)
        strategy = types.SimpleNamespace(broker=broker, run_cycle=lambda: None)
        runtime = types.SimpleNamespace(
            arm_scan_start_deadline=MagicMock(),
            register_core_thread=MagicMock(),
            record_scan_started=MagicMock(),
        )

        class _TradingThread:
            name = "TradingLoop"
            ident = 777

            @staticmethod
            def is_alive():
                return True

        core_loop.start_trading_engine = lambda _strategy: _TradingThread()

        previous = sys.modules.get("bot.nija_core_loop")
        sys.modules["bot.nija_core_loop"] = core_loop
        try:
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
                patch.object(
                    self.bot_main,
                    "_run_self_healing_startup",
                    return_value=(True, broker, "kraken"),
                ),
                patch.object(
                    self.bot_main,
                    "_advance_bootstrap_fsm_to_running_supervised",
                    return_value=True,
                ),
                patch.object(
                    self.bot_main,
                    "_publish_canonical_strategy_for_runtime",
                    return_value=strategy,
                ),
                patch.object(self.bot_main, "_writer_authority_runtime", runtime),
                patch.object(self.bot_main, "_release_writer_authority"),
                patch.object(self.bot_main, "_keep_process_alive_after_loop_return"),
                patch.object(self.bot_main.signal, "signal"),
            ):
                code = self.bot_main.main()
        finally:
            if previous is None:
                sys.modules.pop("bot.nija_core_loop", None)
            else:
                sys.modules["bot.nija_core_loop"] = previous

        self.assertEqual(code, 0)
        runtime.arm_scan_start_deadline.assert_called_once_with("bot_main_step3")
        runtime.register_core_thread.assert_called_once()
        runtime.record_scan_started.assert_not_called()

    def test_main_skips_duplicate_registration_for_pre_registered_core_thread(self):
        core_loop = types.ModuleType("bot.nija_core_loop")
        manager = types.SimpleNamespace(
            _fsm_initialized=True,
            _platform_brokers={"kraken": types.SimpleNamespace(connected=True)},
        )
        broker = types.SimpleNamespace(connected=True)
        strategy = types.SimpleNamespace(broker=broker, run_cycle=lambda: None)

        class _TradingThread:
            name = "TradingLoop"
            ident = 777

            @staticmethod
            def is_alive():
                return True

        trading_thread = _TradingThread()
        runtime = types.SimpleNamespace(
            arm_scan_start_deadline=MagicMock(),
            register_core_thread=MagicMock(),
            record_scan_started=MagicMock(),
            _core_thread=trading_thread,
            _generation=91,
        )
        core_loop.start_trading_engine = lambda _strategy: trading_thread

        previous = sys.modules.get("bot.nija_core_loop")
        sys.modules["bot.nija_core_loop"] = core_loop
        try:
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
                patch.object(
                    self.bot_main,
                    "_run_self_healing_startup",
                    return_value=(True, broker, "kraken"),
                ),
                patch.object(
                    self.bot_main,
                    "_advance_bootstrap_fsm_to_running_supervised",
                    return_value=True,
                ),
                patch.object(
                    self.bot_main,
                    "_publish_canonical_strategy_for_runtime",
                    return_value=strategy,
                ),
                patch.object(self.bot_main, "_writer_authority_runtime", runtime),
                patch.object(self.bot_main, "_release_writer_authority"),
                patch.object(self.bot_main, "_keep_process_alive_after_loop_return"),
                patch.object(self.bot_main.signal, "signal"),
            ):
                code = self.bot_main.main()
        finally:
            if previous is None:
                sys.modules.pop("bot.nija_core_loop", None)
            else:
                sys.modules["bot.nija_core_loop"] = previous

        self.assertEqual(code, 0)
        runtime.register_core_thread.assert_not_called()

    def test_main_fail_closed_when_trading_thread_not_alive(self):
        core_loop = types.ModuleType("bot.nija_core_loop")
        manager = types.SimpleNamespace(
            _fsm_initialized=True,
            _platform_brokers={"kraken": types.SimpleNamespace(connected=True)},
        )
        broker = types.SimpleNamespace(connected=True)
        strategy = types.SimpleNamespace(broker=broker, run_cycle=lambda: None)
        runtime = types.SimpleNamespace(
            arm_scan_start_deadline=MagicMock(),
            register_core_thread=MagicMock(),
            record_scan_started=MagicMock(),
        )

        class _DeadTradingThread:
            name = "TradingLoop"
            ident = 999

            @staticmethod
            def is_alive():
                return False

        core_loop.start_trading_engine = lambda _strategy: _DeadTradingThread()
        previous = sys.modules.get("bot.nija_core_loop")
        sys.modules["bot.nija_core_loop"] = core_loop
        try:
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
                patch.object(
                    self.bot_main,
                    "_run_self_healing_startup",
                    return_value=(True, broker, "kraken"),
                ),
                patch.object(
                    self.bot_main,
                    "_advance_bootstrap_fsm_to_running_supervised",
                    return_value=True,
                ),
                patch.object(
                    self.bot_main,
                    "_publish_canonical_strategy_for_runtime",
                    return_value=strategy,
                ),
                patch.object(self.bot_main, "_writer_authority_runtime", runtime),
                patch.object(self.bot_main, "_release_writer_authority") as release,
                patch.object(self.bot_main.signal, "signal"),
            ):
                code = self.bot_main.main()
        finally:
            if previous is None:
                sys.modules.pop("bot.nija_core_loop", None)
            else:
                sys.modules["bot.nija_core_loop"] = previous

        self.assertEqual(code, 1)
        runtime.register_core_thread.assert_not_called()
        release.assert_called_once_with()

    def test_thread_start_failure_still_releases_writer_authority(self):
        core_loop = types.ModuleType("bot.nija_core_loop")
        manager = types.SimpleNamespace(
            _fsm_initialized=True,
            _platform_brokers={"kraken": types.SimpleNamespace(connected=True)},
        )
        broker = types.SimpleNamespace(connected=True)
        strategy = types.SimpleNamespace(broker=broker, run_cycle=lambda: None)

        def start_trading_engine(_strategy):
            raise RuntimeError("thread start failed")

        core_loop.start_trading_engine = start_trading_engine
        previous = sys.modules.get("bot.nija_core_loop")
        sys.modules["bot.nija_core_loop"] = core_loop
        try:
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
                patch.object(
                    self.bot_main,
                    "_run_self_healing_startup",
                    return_value=(True, broker, "kraken"),
                ),
                patch.object(
                    self.bot_main,
                    "_advance_bootstrap_fsm_to_running_supervised",
                    return_value=True,
                ),
                patch.object(
                    self.bot_main,
                    "_publish_canonical_strategy_for_runtime",
                    return_value=strategy,
                ),
                patch.object(self.bot_main, "_release_writer_authority") as release,
                patch.object(self.bot_main.signal, "signal"),
            ):
                code = self.bot_main.main()
        finally:
            if previous is None:
                sys.modules.pop("bot.nija_core_loop", None)
            else:
                sys.modules["bot.nija_core_loop"] = previous

        self.assertEqual(code, 1)
        release.assert_called_once()

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
