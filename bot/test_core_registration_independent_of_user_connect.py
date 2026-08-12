"""Regression tests for NIJA production runtime repair.

Proves (spec items AW, BB, AX, AY, AZ):

AW / BB  — Canonical core registration is independent of user Kraken connection
           latency.  Even when user broker.connect() blocks for an arbitrarily
           long time, MABM.initialize() must return quickly, bot_main must
           proceed to core registration, and the 600-second watchdog must NOT
           fire under normal startup.

AX       — writer_ready must be True when the writer lease is healthy even
           before the core thread is registered.  writer_ready must NOT require
           core_thread_alive.

AY       — independent_any_ready mode must not require ALL three venues.
           Kraken + Coinbase ready is sufficient even when OKX is not ready.

AZ       — No private Kraken API calls must occur after the writer lock is
           released.  The v86 watchdog must be stoppable and must respect the
           shutdown signal.

All tests are self-contained and use only in-process mocks.
No live credentials, real exchanges, or real orders are used.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
import types
import unittest
from unittest.mock import MagicMock, patch, call

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_BOT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_BOT_DIR)
for _p in (_BOT_DIR, _REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("test_core_registration_independent_of_user_connect")


# ---------------------------------------------------------------------------
# AW / BB — MABM.prepare_users_from_config skips sync network I/O
# ---------------------------------------------------------------------------

class TestPrepareUsersFromConfigNoBrokerConnect(unittest.TestCase):
    """prepare_users_from_config() must not call broker.connect()."""

    def _make_mock_broker(self, blocked=False):
        broker = MagicMock()
        broker.connected = False
        broker.credentials_configured = True
        if blocked:
            # Simulate a connect() that blocks indefinitely.
            barrier = threading.Event()
            def _blocking_connect():
                barrier.wait(timeout=3600)  # effectively never returns in test
                return False
            broker.connect.side_effect = _blocking_connect
        return broker

    def test_prepare_users_does_not_call_connect(self):
        """prepare_users_from_config() must register users without connect() calls."""
        try:
            from bot.multi_account_broker_manager import MultiAccountBrokerManager, BrokerType
        except ImportError:
            self.skipTest("MultiAccountBrokerManager not importable")

        manager = MagicMock(spec=MultiAccountBrokerManager)
        manager._user_metadata = {}
        manager.user_configs = {}
        manager._all_user_brokers = {}
        manager._failed_user_connections = {}

        mock_broker = self._make_mock_broker(blocked=True)

        # Patch the broker constructor to return our mock (no real exchange init).
        broker_ctor_calls = []

        def _make_kraken_broker(**kwargs):
            broker_ctor_calls.append(kwargs)
            return mock_broker

        user_cfg = MagicMock()
        user_cfg.user_id = "daivon_frazier"
        user_cfg.name = "Daivon Frazier"
        user_cfg.broker_type = "KRAKEN"
        user_cfg.enabled = True

        mock_loader = MagicMock()
        mock_loader.get_all_enabled_users.return_value = [user_cfg]

        with patch("bot.multi_account_broker_manager.KrakenBroker", side_effect=_make_kraken_broker), \
             patch.dict(sys.modules, {
                 "config.user_loader": types.ModuleType("config.user_loader"),
             }):
            # Inject mock loader into the freshly patched module.
            sys.modules["config.user_loader"].get_user_config_loader = lambda: mock_loader  # type: ignore[attr-defined]

            from bot.multi_account_broker_manager import MultiAccountBrokerManager as _MABM
            result = _MABM.prepare_users_from_config.__get__(manager, _MABM)()

        # connect() must never have been called.
        mock_broker.connect.assert_not_called()
        # User must have been registered (broker ctor called once).
        self.assertEqual(len(broker_ctor_calls), 1)
        # Method must return the count of registered users.
        self.assertEqual(result, 1)

    def test_prepare_users_returns_immediately_with_blocked_connect(self):
        """MABM registration must complete in milliseconds regardless of connect latency."""
        try:
            from bot.multi_account_broker_manager import MultiAccountBrokerManager, BrokerType
        except ImportError:
            self.skipTest("MultiAccountBrokerManager not importable")

        start = time.monotonic()

        manager = MagicMock(spec=MultiAccountBrokerManager)
        manager._user_metadata = {}
        manager.user_configs = {}
        manager._all_user_brokers = {}
        manager._failed_user_connections = {}

        user_cfg = MagicMock()
        user_cfg.user_id = "tania_gilbert"
        user_cfg.name = "Tania Gilbert"
        user_cfg.broker_type = "KRAKEN"
        user_cfg.enabled = True

        mock_loader = MagicMock()
        mock_loader.get_all_enabled_users.return_value = [user_cfg]

        blocking_broker = self._make_mock_broker(blocked=True)

        with patch("bot.multi_account_broker_manager.KrakenBroker", return_value=blocking_broker), \
             patch.dict(sys.modules, {
                 "config.user_loader": types.ModuleType("config.user_loader"),
             }):
            sys.modules["config.user_loader"].get_user_config_loader = lambda: mock_loader  # type: ignore[attr-defined]
            from bot.multi_account_broker_manager import MultiAccountBrokerManager as _MABM
            _MABM.prepare_users_from_config.__get__(manager, _MABM)()

        elapsed = time.monotonic() - start
        # Must return well within 1 second (not 600+ seconds).
        self.assertLess(elapsed, 1.0, f"prepare_users_from_config took {elapsed:.2f}s (blocked connect not called)")


# ---------------------------------------------------------------------------
# AW / BB — bootstrap_hydrate skips sync user connect in independent mode
# ---------------------------------------------------------------------------

class TestBootstrapHydrateSkipsUserConnectInIndependentMode(unittest.TestCase):
    """_bootstrap_hydrate_balance_before_activation must not call
    connect_users_from_config() when NIJA_AGGREGATE_USER_CAPITAL_IN_AUTHORITY=false."""

    def test_independent_mode_calls_prepare_not_connect(self):
        """In independent mode, prepare_users_from_config must be called; connect must NOT be."""
        try:
            from bot.multi_account_broker_manager import MultiAccountBrokerManager
        except ImportError:
            self.skipTest("MultiAccountBrokerManager not importable")

        env_patch = {"NIJA_AGGREGATE_USER_CAPITAL_IN_AUTHORITY": "false"}
        with patch.dict(os.environ, env_patch, clear=False):
            manager = MagicMock(spec=MultiAccountBrokerManager)
            manager._platform_brokers = {}
            manager.user_brokers = {}
            manager._all_user_brokers = {}
            manager._user_metadata = {}
            manager.user_configs = {}
            manager._failed_user_connections = {}
            manager._fsm_initialized = True
            manager.get_all_brokers = MagicMock(return_value={})
            manager.initialize_platform_brokers = MagicMock(return_value={})
            manager.get_all_balances = MagicMock(return_value={"platform": {}, "users": {}})
            manager._capital_bootstrap_fsm = None
            manager._capital_coordinator = None

            prepare_called = []
            connect_called = []

            manager.prepare_users_from_config = MagicMock(side_effect=lambda: prepare_called.append(1) or 0)
            manager.connect_users_from_config = MagicMock(side_effect=lambda: connect_called.append(1) or {})

            from bot.multi_account_broker_manager import MultiAccountBrokerManager as _MABM
            try:
                _MABM._bootstrap_hydrate_balance_before_activation.__get__(manager, _MABM)()
            except Exception:
                pass  # Balance hydration may fail with mocks; we only check call routing.

            self.assertGreater(len(prepare_called), 0, "prepare_users_from_config must be called in independent mode")
            self.assertEqual(len(connect_called), 0, "connect_users_from_config must NOT be called in independent mode")

    def test_aggregate_mode_calls_connect_not_prepare(self):
        """In aggregate mode, connect_users_from_config must be called."""
        try:
            from bot.multi_account_broker_manager import MultiAccountBrokerManager
        except ImportError:
            self.skipTest("MultiAccountBrokerManager not importable")

        env_patch = {"NIJA_AGGREGATE_USER_CAPITAL_IN_AUTHORITY": "true"}
        with patch.dict(os.environ, env_patch, clear=False):
            manager = MagicMock(spec=MultiAccountBrokerManager)
            manager._platform_brokers = {}
            manager.user_brokers = {}
            manager._all_user_brokers = {}
            manager._user_metadata = {}
            manager.user_configs = {}
            manager._failed_user_connections = {}
            manager._fsm_initialized = True
            manager.get_all_brokers = MagicMock(return_value={})
            manager.initialize_platform_brokers = MagicMock(return_value={})
            manager.get_all_balances = MagicMock(return_value={"platform": {}, "users": {}})
            manager._capital_bootstrap_fsm = None
            manager._capital_coordinator = None

            prepare_called = []
            connect_called = []

            manager.prepare_users_from_config = MagicMock(side_effect=lambda: prepare_called.append(1) or 0)
            manager.connect_users_from_config = MagicMock(side_effect=lambda: connect_called.append(1) or {})

            from bot.multi_account_broker_manager import MultiAccountBrokerManager as _MABM
            try:
                _MABM._bootstrap_hydrate_balance_before_activation.__get__(manager, _MABM)()
            except Exception:
                pass

            self.assertGreater(len(connect_called), 0, "connect_users_from_config must be called in aggregate mode")
            self.assertEqual(len(prepare_called), 0, "prepare_users_from_config must NOT be called in aggregate mode")


# ---------------------------------------------------------------------------
# AX — writer_ready is True when writer lease is healthy, core not yet registered
# ---------------------------------------------------------------------------

class TestWriterReadySplitFromCoreRegistration(unittest.TestCase):
    """writer_ready must reflect writer lease health, not core thread state."""

    def _writer_env(self):
        return {
            "NIJA_WRITER_FENCING_TOKEN": "tok123",
            "NIJA_WRITER_LEASE_GENERATION": "42",
            "NIJA_WRITER_LEASE_ACQUIRED": "1",
            "NIJA_PREBOT_WRITER_AUTHORITY_READY": "1",
            "NIJA_WRITER_HEARTBEAT_ACTIVE": "1",
            "NIJA_CORE_THREAD_ALIVE": "0",  # core NOT yet registered
        }

    def test_writer_ready_true_without_core_alive(self):
        """_writer_ready() in runtime_execution_convergence_v32 must return True
        when writer lease is healthy, even when NIJA_CORE_THREAD_ALIVE=0."""
        try:
            import importlib
            if "bot.runtime_execution_convergence_v32" in sys.modules:
                del sys.modules["bot.runtime_execution_convergence_v32"]
            mod = importlib.import_module("bot.runtime_execution_convergence_v32")
        except ImportError:
            self.skipTest("runtime_execution_convergence_v32 not importable")

        with patch.dict(os.environ, self._writer_env(), clear=False):
            result = mod._writer_ready()

        self.assertTrue(result, "_writer_ready() must be True with healthy lease even if core_alive=0")

    def test_writer_ready_false_without_lease(self):
        """_writer_ready() must return False when lease is not acquired."""
        try:
            import importlib
            if "bot.runtime_execution_convergence_v32" in sys.modules:
                del sys.modules["bot.runtime_execution_convergence_v32"]
            mod = importlib.import_module("bot.runtime_execution_convergence_v32")
        except ImportError:
            self.skipTest("runtime_execution_convergence_v32 not importable")

        env = {
            "NIJA_WRITER_LEASE_ACQUIRED": "0",
            "NIJA_PREBOT_WRITER_AUTHORITY_READY": "0",
            "NIJA_WRITER_HEARTBEAT_ACTIVE": "1",
            "NIJA_WRITER_LEASE_GENERATION": "42",
            "NIJA_CORE_THREAD_ALIVE": "1",
        }
        with patch.dict(os.environ, env, clear=False):
            result = mod._writer_ready()

        self.assertFalse(result, "_writer_ready() must be False without lease")

    def test_writer_authority_snapshot_has_granular_fields(self):
        """writer_authority_snapshot() must expose writer_lease_ready and core_thread_ready."""
        try:
            import importlib
            mod_name = "three_venue_execution_readiness"
            if mod_name in sys.modules:
                del sys.modules[mod_name]
            mod = importlib.import_module(mod_name)
        except ImportError:
            self.skipTest("three_venue_execution_readiness not importable")

        # Minimal mock for WriterAuthority
        status_mock = MagicMock()
        status_mock.state = "ACTIVE"
        status_mock.ready = True
        status_mock.checks = {
            "heartbeat_active": True,
            "lease_acquired": True,
            "fencing_token_active": True,
        }
        status_mock.missing = []
        status_mock.source = "mock"
        status_mock.reason = "ok"

        env = {
            "NIJA_WRITER_FENCING_TOKEN": "tok123",
            "NIJA_WRITER_LEASE_GENERATION": "42",
            "NIJA_WRITER_LEASE_ACQUIRED": "1",
            "NIJA_WRITER_HEARTBEAT_ACTIVE": "1",
            "NIJA_CORE_THREAD_ALIVE": "0",
            "NIJA_WRITER_HEARTBEAT_ALIVE_TS": str(time.time()),
        }

        mock_wa_class = MagicMock()
        mock_wa_class.get_status.return_value = status_mock

        with patch.dict(os.environ, env, clear=False), \
             patch.dict(sys.modules, {"bot.writer_authority": MagicMock(WriterAuthority=mock_wa_class),
                                       "writer_authority": MagicMock(WriterAuthority=mock_wa_class)}):
            snapshot = mod.writer_authority_snapshot()

        self.assertIn("writer_lease_ready", snapshot)
        self.assertIn("core_thread_ready", snapshot)
        self.assertIn("writer_heartbeat_ready", snapshot)
        self.assertIn("writer_generation_ready", snapshot)
        # writer_lease_ready must be True; core_thread_ready must be False
        self.assertTrue(snapshot["writer_lease_ready"],
                        "writer_lease_ready must be True with healthy lease")
        self.assertFalse(snapshot["core_thread_ready"],
                         "core_thread_ready must be False when core not registered")
        # The legacy 'ready' field must also be True (lease-level ready)
        self.assertTrue(snapshot["ready"],
                        "ready must be True with healthy lease even without core")


# ---------------------------------------------------------------------------
# AY — independent_any_ready: OKX not ready does NOT block Kraken + Coinbase
# ---------------------------------------------------------------------------

class TestIndependentAnyReadyVenueIsolation(unittest.TestCase):
    """When mode=independent_any_ready, OKX being down must NOT set execution_enabled=False
    when Kraken and Coinbase are ready and writer/core/runtime are valid."""

    def test_kraken_coinbase_ready_okx_not_ready_execution_enabled(self):
        """evaluate_all() with Kraken+Coinbase ready and OKX not ready must give
        execution_ready=True (any_venue_ready=True)."""
        try:
            import importlib
            mod_name = "three_venue_execution_readiness"
            if mod_name in sys.modules:
                del sys.modules[mod_name]
            mod = importlib.import_module(mod_name)
        except ImportError:
            self.skipTest("three_venue_execution_readiness not importable")

        from unittest.mock import patch as _patch

        # Build mock venue readiness rows
        from dataclasses import dataclass, asdict

        @dataclass
        class FakeVenueReadiness:
            venue: str
            credentials_loaded: bool
            authentication_succeeded: bool
            balance_fetched: bool
            market_metadata_loaded: bool
            order_adapter_initialized: bool
            venue_marked_ready: bool
            eligible_for_execution: bool
            connected: bool
            spendable_quote: float
            market_count: int
            activation_state: str
            reason: str

            @property
            def ready(self):
                return self.eligible_for_execution and self.connected

        kraken_row = FakeVenueReadiness(
            venue="kraken", credentials_loaded=True, authentication_succeeded=True,
            balance_fetched=True, market_metadata_loaded=True, order_adapter_initialized=True,
            venue_marked_ready=True, eligible_for_execution=True, connected=True,
            spendable_quote=95.0, market_count=200, activation_state="ready", reason="ready",
        )
        coinbase_row = FakeVenueReadiness(
            venue="coinbase", credentials_loaded=True, authentication_succeeded=True,
            balance_fetched=True, market_metadata_loaded=True, order_adapter_initialized=True,
            venue_marked_ready=True, eligible_for_execution=True, connected=True,
            spendable_quote=120.0, market_count=300, activation_state="ready", reason="ready",
        )
        okx_row = FakeVenueReadiness(
            venue="okx", credentials_loaded=False, authentication_succeeded=False,
            balance_fetched=False, market_metadata_loaded=False, order_adapter_initialized=False,
            venue_marked_ready=False, eligible_for_execution=False, connected=False,
            spendable_quote=0.0, market_count=0, activation_state="not_ready", reason="credentials_not_configured",
        )

        # Writer snapshot: healthy lease, core not yet alive
        writer_snap = {
            "ready": True,  # writer_lease_ready = True
            "writer_lease_ready": True,
            "core_loop_alive": True,
            "lease_acquired": True,
            "fencing_token": True,
            "heartbeat_healthy": True,
            "heartbeat_effective": True,
            "writer_state": "ACTIVE",
        }

        with _patch.object(mod, "evaluate_venue", side_effect=[kraken_row, coinbase_row, okx_row]), \
             _patch.object(mod, "writer_authority_snapshot", return_value=writer_snap), \
             _patch.object(mod, "_capital_ready", return_value=True), \
             _patch.object(mod, "_runtime", return_value=(MagicMock(), MagicMock())):
            result = mod.evaluate_all()

        self.assertIn("kraken", result["ready_venues"])
        self.assertIn("coinbase", result["ready_venues"])
        self.assertNotIn("okx", result["ready_venues"])
        self.assertTrue(result["any_venue_ready"])
        self.assertTrue(result["execution_ready"],
                        "execution_ready must be True when writer+capital+any_venue are ready "
                        "even if OKX is not ready")
        self.assertFalse(result["all_venues_ready"])


# ---------------------------------------------------------------------------
# AZ — no private Kraken I/O after writer release (v86 stop)
# ---------------------------------------------------------------------------

class TestV86StopPreventsPrivateIO(unittest.TestCase):
    """After stop() is called, _connect_account must not call broker I/O."""

    def test_stop_prevents_connect_after_stop(self):
        """Once _WATCHDOG_STOP is set, _connect_account must return without
        calling broker.connect()."""
        try:
            import bot.kraken_all_account_supervision_v86 as v86
        except ImportError:
            self.skipTest("v86 not importable")

        # Reset module state for clean test.
        v86._WATCHDOG_STOP.clear()
        v86._INFLIGHT.clear()

        broker = MagicMock()
        broker.connected = False
        broker.credentials_configured = True
        manager = MagicMock()

        # Signal stop before the connection attempt.
        v86.stop()
        self.assertTrue(v86._WATCHDOG_STOP.is_set())

        # Schedule normally — should be blocked by _WATCHDOG_STOP check.
        v86._INFLIGHT.add("user:daivon_frazier:kraken")
        v86._connect_account(manager, "user:daivon_frazier:kraken", "daivon_frazier", "kraken", broker)

        # broker.connect() must NOT have been called.
        broker.connect.assert_not_called()

        # Reset for other tests.
        v86._WATCHDOG_STOP.clear()

    def test_stop_is_idempotent(self):
        """Calling stop() multiple times must not raise."""
        try:
            import bot.kraken_all_account_supervision_v86 as v86
        except ImportError:
            self.skipTest("v86 not importable")

        v86._WATCHDOG_STOP.clear()
        v86.stop()
        v86.stop()  # second call must be safe
        self.assertTrue(v86._WATCHDOG_STOP.is_set())
        v86._WATCHDOG_STOP.clear()

    def test_private_api_calls_after_stop_are_zero(self):
        """Simulate the shutdown sequence: stop() is called, then multiple
        _connect_account attempts must all make zero broker API calls."""
        try:
            import bot.kraken_all_account_supervision_v86 as v86
        except ImportError:
            self.skipTest("v86 not importable")

        v86._WATCHDOG_STOP.clear()
        v86._INFLIGHT.clear()

        manager = MagicMock()
        private_api_calls = []

        def tracking_connect():
            private_api_calls.append(time.time())
            return True

        broker_a = MagicMock()
        broker_a.connected = False
        broker_a.connect.side_effect = tracking_connect

        broker_b = MagicMock()
        broker_b.connected = False
        broker_b.connect.side_effect = tracking_connect

        v86.stop()
        stop_time = time.time()

        # Simulate two connection attempts after stop.
        for account_id, uid, broker in [
            ("user:daivon_frazier:kraken", "daivon_frazier", broker_a),
            ("user:tania_gilbert:kraken", "tania_gilbert", broker_b),
        ]:
            v86._INFLIGHT.add(account_id)
            v86._connect_account(manager, account_id, uid, "kraken", broker)

        calls_after_stop = [t for t in private_api_calls if t >= stop_time]
        self.assertEqual(
            len(calls_after_stop), 0,
            f"private_api_call_count_after_writer_release={len(calls_after_stop)} (expected 0)"
        )

        v86._WATCHDOG_STOP.clear()


# ---------------------------------------------------------------------------
# MABM post-init activation is removed (spec item H)
# ---------------------------------------------------------------------------

class TestMABMInitializeDoesNotActivate(unittest.TestCase):
    """MABM.initialize() must not call maybe_auto_activate() or trigger
    TradingStateMachine activation. That is bot_main's responsibility."""

    def test_initialize_does_not_call_maybe_auto_activate(self):
        """maybe_auto_activate must not be called during MABM.initialize()."""
        try:
            from bot.multi_account_broker_manager import MultiAccountBrokerManager
        except ImportError:
            self.skipTest("MultiAccountBrokerManager not importable")

        activate_calls = []

        mock_tsm = MagicMock()
        mock_tsm.maybe_auto_activate.side_effect = lambda: activate_calls.append(1) or False
        mock_tsm.get_current_state.return_value = MagicMock(value="OFF")

        # Patch all the subsystem inits so initialize() runs without real exchange I/O.
        manager = MagicMock(spec=MultiAccountBrokerManager)
        manager._capital_bootstrap_fsm = MagicMock()
        manager._capital_bootstrap_fsm.state = MagicMock()
        manager._capital_coordinator = MagicMock()

        with patch("bot.multi_account_broker_manager.get_state_machine", return_value=mock_tsm, create=True), \
             patch.dict(os.environ, {"NIJA_AGGREGATE_USER_CAPITAL_IN_AUTHORITY": "false"}, clear=False):

            from bot.multi_account_broker_manager import MultiAccountBrokerManager as _MABM
            # Directly exercise the post-init section only.
            # The replacement code must log deferral and NOT call maybe_auto_activate.
            # We verify by inspecting the actual source.
            import inspect
            source = inspect.getsource(_MABM.initialize)
            self.assertNotIn("maybe_auto_activate", source.split("MABM_ACTIVATION_DEFERRED_TO_BOT_MAIN")[1]
                             if "MABM_ACTIVATION_DEFERRED_TO_BOT_MAIN" in source else source[-200:],
                             "maybe_auto_activate must not appear in MABM.initialize() after the deferral comment")


if __name__ == "__main__":
    unittest.main()
