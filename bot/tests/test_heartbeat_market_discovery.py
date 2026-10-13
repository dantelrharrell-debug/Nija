"""
Unit tests for heartbeat market discovery (PR scope: get_available_markets).

Validates:
1. KrakenBroker implements the BaseBroker.get_available_markets interface
2. Heartbeat executor falls back gracefully when market discovery returns empty
3. Heartbeat executor still runs when market discovery raises an exception

Safety contract (from problem statement):
- Heartbeat verification MUST NOT become market-discovery dependent.
- An empty or failing market-discovery call must not block heartbeat execution.
"""

import unittest
import tempfile
import shutil
import json
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, PropertyMock


class TestKrakenBrokerImplementsInterface(unittest.TestCase):
    """Verify KrakenBroker exposes get_available_markets() and it satisfies BaseBroker."""

    def test_kraken_broker_has_get_available_markets(self):
        from bot.broker_manager import KrakenBroker
        self.assertTrue(
            callable(getattr(KrakenBroker, 'get_available_markets', None)),
            "KrakenBroker must expose get_available_markets()",
        )

    def test_base_broker_declares_get_available_markets_abstract(self):
        import inspect
        from bot.broker_manager import BaseBroker
        abstract_methods = getattr(BaseBroker, '__abstractmethods__', frozenset())
        self.assertIn(
            'get_available_markets',
            abstract_methods,
            "BaseBroker must declare get_available_markets() as @abstractmethod",
        )

    def test_kraken_get_available_markets_delegates_to_get_all_products(self):
        """get_available_markets() returns whatever get_all_products() returns."""
        from bot.broker_manager import KrakenBroker
        broker = KrakenBroker.__new__(KrakenBroker)
        expected = ['BTC-USD', 'ETH-USD']
        broker.get_all_products = MagicMock(return_value=expected)
        result = broker.get_available_markets()
        self.assertEqual(result, expected)
        broker.get_all_products.assert_called_once()

    def test_kraken_get_available_markets_returns_fallback_on_empty_products(self):
        """get_available_markets() returns non-empty fallback when get_all_products returns []."""
        from bot.broker_manager import KrakenBroker
        broker = KrakenBroker.__new__(KrakenBroker)
        broker.get_all_products = MagicMock(return_value=[])
        result = broker.get_available_markets()
        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0, "Fallback list must be non-empty")

    def test_kraken_get_available_markets_returns_fallback_on_exception(self):
        """get_available_markets() never raises; returns fallback when get_all_products fails."""
        from bot.broker_manager import KrakenBroker
        broker = KrakenBroker.__new__(KrakenBroker)
        broker.get_all_products = MagicMock(side_effect=RuntimeError("API unavailable"))
        result = broker.get_available_markets()
        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0, "Fallback list must be non-empty even after exception")


class TestHeartbeatEmptyMarketFallback(unittest.TestCase):
    """Heartbeat executor gracefully handles empty market discovery."""

    def setUp(self):
        self._hb_tmpdir = tempfile.mkdtemp(prefix="hb-marker-")
        self._marker_patch = patch.dict(
            "os.environ",
            {"HEARTBEAT_MARKER_PATH": f"{self._hb_tmpdir}/heartbeat_verified.flag"},
            clear=False,
        )
        self._marker_patch.start()
        # Mock submit_market_order_via_pipeline so the DistributedWriterFence does not
        # interfere with tests that are only verifying market-discovery behaviour.
        self._pipeline_mock = MagicMock(return_value={"status": "filled", "order_id": "hb-pipeline-ok", "filled_price": 2500.0, "filled_size_usd": 28.75})
        self._pipeline_patch = patch(
            "bot.trading_strategy.submit_market_order_via_pipeline",
            self._pipeline_mock,
        )
        self._pipeline_patch.start()
        # Reset the module-level heartbeat log-rate-limiter so each test sees
        # a fresh window and rate-limited log lines are not suppressed.
        try:
            import bot.trading_strategy as _ts
            _ts._HEARTBEAT_LOG_LIMITER.reset_all()
        except Exception:
            pass

    def tearDown(self):
        self._pipeline_patch.stop()
        self._marker_patch.stop()
        shutil.rmtree(self._hb_tmpdir, ignore_errors=True)

    def _make_strategy_with_broker(self, broker):
        """Build a minimal TradingStrategy-shaped object for heartbeat tests."""
        from bot.trading_strategy import TradingStrategy
        strategy = TradingStrategy.__new__(TradingStrategy)
        strategy.broker = broker
        strategy.broker_manager = None
        strategy.multi_account_manager = None
        import threading
        strategy._heartbeat_trade_lock = threading.Lock()
        strategy._heartbeat_trade_completed = False
        strategy._heartbeat_trade_success = False
        # Ensure MagicMock broker passes eligibility checks in _is_broker_eligible_for_entry
        if not isinstance(getattr(broker, "exit_only_mode", None), bool):
            broker.exit_only_mode = False
        if not isinstance(getattr(broker, "_last_known_balance", None), (int, float)):
            broker._last_known_balance = 100.0
        return strategy

    def test_heartbeat_rejects_unprotected_entry_even_without_market_data(self):
        broker = MagicMock()
        broker.connected = True
        broker.get_available_markets = MagicMock(return_value=[])
        strategy = self._make_strategy_with_broker(broker)
        self.assertFalse(strategy._execute_heartbeat_trade())
        broker.get_available_markets.assert_not_called()
        self._pipeline_mock.assert_not_called()

    def test_unprotected_heartbeat_emits_fail_closed_log(self):
        import logging
        broker = MagicMock()
        strategy = self._make_strategy_with_broker(broker)
        with self.assertLogs("nija.trading_strategy", level="ERROR") as captured:
            self.assertFalse(strategy._execute_heartbeat_trade())
        self.assertTrue(any("HEARTBEAT_LEGACY_MARKET_ENTRY_FORBIDDEN" in line for line in captured.output))
        self._pipeline_mock.assert_not_called()

    def test_legacy_heartbeat_never_writes_execution_marker(self):
        strategy = self._make_strategy_with_broker(MagicMock())
        with tempfile.TemporaryDirectory() as tmp:
            marker_path = f"{tmp}/heartbeat_verified.flag"
            with patch.dict("os.environ", {"HEARTBEAT_MARKER_PATH": marker_path}, clear=False):
                self.assertFalse(strategy._execute_heartbeat_trade())
            self.assertFalse(Path(marker_path).exists())
        self._pipeline_mock.assert_not_called()

    def test_heartbeat_order_verify_does_not_override_confirmed_fill_truth(self):
        broker = MagicMock()
        broker.connected = True
        broker.get_available_markets = MagicMock(return_value=["BTC-USD"])
        # A broker acknowledgement is not a confirmed execution fill and cannot
        # create fresh canonical execution proof.
        self._pipeline_mock.return_value = {"status": "accepted", "order_id": "hb-order-only"}
        strategy = self._make_strategy_with_broker(broker)
        with tempfile.TemporaryDirectory() as tmp:
            marker_path = f"{tmp}/heartbeat_verified.flag"
            with patch.dict(
                "os.environ",
                {
                    "HEARTBEAT_MARKER_PATH": marker_path,
                    "HEARTBEAT_VERIFICATION_REQUIRED_STAGE": "ORDER_VERIFY",
                },
                clear=False,
            ):
                result = strategy._execute_heartbeat_trade()
            self.assertFalse(result, "ORDER_VERIFY must not convert an unfilled acknowledgement into heartbeat success")
            self.assertFalse(Path(marker_path).exists())

    def test_heartbeat_uses_canonical_ready_venue_not_cached_degraded_broker(self):
        """A cached Kraken broker cannot override Coinbase-only readiness."""
        from bot.trading_strategy import TradingStrategy

        kraken = SimpleNamespace(
            NAME="kraken",
            connected=True,
            exit_only_mode=False,
            _last_known_balance=250.0,
        )
        coinbase = SimpleNamespace(
            NAME="coinbase",
            connected=True,
            exit_only_mode=False,
            _last_known_balance=95.0,
        )

        strategy = self._make_strategy_with_broker(kraken)
        strategy.multi_account_manager = SimpleNamespace(
            platform_brokers={"kraken": kraken, "coinbase": coinbase}
        )

        with patch.dict(
            "os.environ",
            {"NIJA_EXECUTION_READY_VENUES": "coinbase,okx"},
            clear=False,
        ):
            selected = strategy._get_heartbeat_broker()

        self.assertIs(selected, coinbase)
        self.assertIs(strategy.broker, coinbase)

    def test_heartbeat_preserves_canonical_platform_broker_over_legacy_same_key(self):
        """Legacy/user broker maps cannot overwrite canonical PLATFORM Kraken."""
        class _BrokerType:
            value = "kraken"

        shared_key = _BrokerType()
        platform = SimpleNamespace(
            NAME="kraken",
            broker_type=shared_key,
            account_type="platform",
            connected=True,
            exit_only_mode=False,
            _last_known_balance=250.0,
        )
        user = SimpleNamespace(
            NAME="kraken",
            broker_type=shared_key,
            account_type="user",
            connected=True,
            exit_only_mode=False,
            _last_known_balance=500.0,
        )

        strategy = self._make_strategy_with_broker(user)
        strategy.multi_account_manager = SimpleNamespace(
            platform_brokers={shared_key: platform}
        )
        strategy.broker_manager = SimpleNamespace(
            brokers={shared_key: user},
            get_primary_broker=lambda: user,
            active_broker=None,
        )

        with patch.dict(
            "os.environ",
            {"NIJA_EXECUTION_READY_VENUES": "kraken"},
            clear=False,
        ):
            selected = strategy._get_heartbeat_broker()

        self.assertIs(selected, platform)
        self.assertIs(strategy.broker, platform)

    def test_heartbeat_excludes_explicit_non_platform_candidate_for_startup_proof(self):
        user = SimpleNamespace(
            NAME="kraken",
            account_type="user",
            connected=True,
            exit_only_mode=False,
            _last_known_balance=500.0,
        )
        strategy = self._make_strategy_with_broker(user)
        strategy.multi_account_manager = SimpleNamespace(platform_brokers={})
        strategy.broker_manager = SimpleNamespace(
            brokers={"kraken": user},
            get_primary_broker=lambda: user,
            active_broker=None,
        )

        with patch.dict(
            "os.environ",
            {"NIJA_EXECUTION_READY_VENUES": "kraken"},
            clear=False,
        ):
            selected = strategy._get_heartbeat_broker()

        self.assertIsNone(selected)

    def test_heartbeat_fails_closed_when_ready_venue_object_is_missing(self):
        """Published readiness never falls back to a degraded cached venue."""
        kraken = SimpleNamespace(
            NAME="kraken",
            connected=True,
            exit_only_mode=False,
            _last_known_balance=250.0,
        )
        strategy = self._make_strategy_with_broker(kraken)

        with patch.dict(
            "os.environ",
            {"NIJA_EXECUTION_READY_VENUES": "coinbase"},
            clear=False,
        ):
            selected = strategy._get_heartbeat_broker()

        self.assertIsNone(selected)

    def test_heartbeat_fails_closed_when_published_ready_set_is_empty(self):
        """An authoritative empty ready set is not treated as unpublished."""
        kraken = SimpleNamespace(
            NAME="kraken",
            connected=True,
            exit_only_mode=False,
            _last_known_balance=250.0,
        )
        strategy = self._make_strategy_with_broker(kraken)

        with patch.dict(
            "os.environ",
            {"NIJA_EXECUTION_READY_VENUES": ""},
            clear=False,
        ):
            selected = strategy._get_heartbeat_broker()

        self.assertIsNone(selected)

    def test_heartbeat_fill_verify_blocks_without_fill(self):
        broker = MagicMock()
        broker.connected = True
        broker.get_available_markets = MagicMock(return_value=["BTC-USD"])
        # Pipeline returns 'accepted' (submitted but not filled) to exercise FILL_VERIFY path
        self._pipeline_mock.return_value = {"status": "accepted", "order_id": "hb-order-only"}
        strategy = self._make_strategy_with_broker(broker)
        with tempfile.TemporaryDirectory() as tmp:
            marker_path = f"{tmp}/heartbeat_verified.flag"
            with patch.dict(
                "os.environ",
                {
                    "HEARTBEAT_MARKER_PATH": marker_path,
                    "HEARTBEAT_VERIFICATION_REQUIRED_STAGE": "FILL_VERIFY",
                },
                clear=False,
            ):
                result = strategy._execute_heartbeat_trade()
            self.assertFalse(result, "FILL_VERIFY should fail when buy order is accepted but not filled")
            self.assertFalse(Path(marker_path).exists())

    def test_legacy_heartbeat_cannot_refresh_proof_timestamp(self):
        strategy = self._make_strategy_with_broker(MagicMock())
        with tempfile.TemporaryDirectory() as tmp:
            marker_path = f"{tmp}/heartbeat_verified.flag"
            with patch.dict("os.environ", {"HEARTBEAT_MARKER_PATH": marker_path}, clear=False):
                self.assertFalse(strategy._execute_heartbeat_trade())
                self.assertFalse(strategy._execute_heartbeat_trade())
            self.assertFalse(Path(marker_path).exists())
        self._pipeline_mock.assert_not_called()

    def test_legacy_heartbeat_never_enters_startup_order_scopes(self):
        strategy = self._make_strategy_with_broker(MagicMock())
        reasons = []
        @contextmanager
        def _capture_scope(reason):
            reasons.append(reason)
            yield
        with patch("bot.trading_strategy.startup_execution_probe_scope", side_effect=_capture_scope):
            self.assertFalse(strategy._execute_heartbeat_trade())
        self.assertEqual(reasons, [])
        self._pipeline_mock.assert_not_called()

class TestHeartbeatExecutesOnDiscoveryFailure(unittest.TestCase):
    """Heartbeat executor continues when market discovery raises an exception."""

    def setUp(self):
        self._hb_tmpdir = tempfile.mkdtemp(prefix="hb-marker-")
        self._marker_patch = patch.dict(
            "os.environ",
            {"HEARTBEAT_MARKER_PATH": f"{self._hb_tmpdir}/heartbeat_verified.flag"},
            clear=False,
        )
        self._marker_patch.start()
        # Mock submit_market_order_via_pipeline so the DistributedWriterFence does not
        # interfere with tests that are only verifying market-discovery behaviour.
        self._pipeline_mock = MagicMock(return_value={"status": "filled", "order_id": "hb-pipeline-ok", "filled_price": 2500.0, "filled_size_usd": 28.75})
        self._pipeline_patch = patch(
            "bot.trading_strategy.submit_market_order_via_pipeline",
            self._pipeline_mock,
        )
        self._pipeline_patch.start()
        # Reset the module-level heartbeat log-rate-limiter so each test sees
        # a fresh window and rate-limited log lines are not suppressed.
        try:
            import bot.trading_strategy as _ts
            _ts._HEARTBEAT_LOG_LIMITER.reset_all()
        except Exception:
            pass

    def tearDown(self):
        self._pipeline_patch.stop()
        self._marker_patch.stop()
        shutil.rmtree(self._hb_tmpdir, ignore_errors=True)

    def _make_strategy_with_broker(self, broker):
        from bot.trading_strategy import TradingStrategy
        strategy = TradingStrategy.__new__(TradingStrategy)
        strategy.broker = broker
        strategy.broker_manager = None
        strategy.multi_account_manager = None
        import threading
        strategy._heartbeat_trade_lock = threading.Lock()
        strategy._heartbeat_trade_completed = False
        strategy._heartbeat_trade_success = False
        # Ensure MagicMock broker passes eligibility checks in _is_broker_eligible_for_entry
        if not isinstance(getattr(broker, "exit_only_mode", None), bool):
            broker.exit_only_mode = False
        if not isinstance(getattr(broker, "_last_known_balance", None), (int, float)):
            broker._last_known_balance = 100.0
        return strategy

    def test_heartbeat_executes_when_market_discovery_raises(self):
        """If get_available_markets() raises, heartbeat falls back and still executes."""
        broker = MagicMock()
        broker.connected = True
        broker.get_available_markets = MagicMock(
            side_effect=ConnectionError("Exchange unreachable")
        )

        strategy = self._make_strategy_with_broker(broker)

        result = strategy._execute_heartbeat_trade()
        self.assertTrue(
            result,
            "Heartbeat must succeed even when get_available_markets() raises an exception",
        )

    def test_heartbeat_executes_when_broker_lacks_market_discovery(self):
        """If broker has no get_available_markets() or get_all_products(), heartbeat uses default symbol."""
        broker = MagicMock(spec=[])  # spec=[] means no attributes
        # Force-set the minimal attributes the heartbeat path needs to function
        object.__setattr__(broker, 'connected', True)
        object.__setattr__(broker, 'execute_order', MagicMock(return_value={"status": "filled", "order_id": "hb-007"}))

        strategy = self._make_strategy_with_broker(broker)

        result = strategy._execute_heartbeat_trade()
        self.assertTrue(
            result,
            "Heartbeat must succeed when broker has no market discovery method",
        )


if __name__ == '__main__':
    unittest.main()
