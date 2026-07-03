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
        self._pipeline_mock = MagicMock(return_value={"status": "filled", "order_id": "hb-pipeline-ok"})
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

    def test_heartbeat_proceeds_when_market_discovery_returns_empty(self):
        """When get_available_markets() returns [], heartbeat falls back and executes."""
        from bot.trading_strategy import TradingStrategy

        broker = MagicMock()
        broker.connected = True
        broker.get_available_markets = MagicMock(return_value=[])
        # Remove get_all_products so only get_available_markets path is exercised
        del broker.get_all_products

        strategy = self._make_strategy_with_broker(broker)

        result = strategy._execute_heartbeat_trade()
        # Heartbeat must succeed — it falls back to _HEARTBEAT_TRADE_SYMBOL
        self.assertTrue(result, "Heartbeat must succeed even when market discovery returns empty")

    def test_market_discovery_count_logged(self):
        """[HeartbeatTrade] market_discovery_count=%s is emitted during execution."""
        import logging

        broker = MagicMock()
        broker.connected = True
        broker.get_available_markets = MagicMock(return_value=['BTC-USD', 'ETH-USD', 'SOL-USD'])

        strategy = self._make_strategy_with_broker(broker)

        log_records = []

        class _Capture(logging.Handler):
            def emit(self, record):
                log_records.append(record.getMessage())

        handler = _Capture()
        ts_logger = logging.getLogger('nija.trading_strategy')
        ts_logger.addHandler(handler)
        ts_logger.setLevel(logging.DEBUG)
        try:
            strategy._execute_heartbeat_trade()
        finally:
            ts_logger.removeHandler(handler)

        matching = [m for m in log_records if 'market_discovery_count' in m]
        self.assertTrue(
            matching,
            "[HeartbeatTrade] market_discovery_count structured log line must be emitted",
        )

    def test_heartbeat_writes_marker_and_uses_safe_minimum_size(self):
        """Successful heartbeat writes verification marker and uses >= $10 notional."""
        broker = MagicMock()
        broker.connected = True
        broker.get_available_markets = MagicMock(return_value=["BTC-USD"])

        strategy = self._make_strategy_with_broker(broker)

        with tempfile.TemporaryDirectory() as tmp:
            marker_path = f"{tmp}/heartbeat_verified.flag"
            with patch.dict("os.environ", {"HEARTBEAT_MARKER_PATH": marker_path}, clear=False):
                result = strategy._execute_heartbeat_trade()

            self.assertTrue(result, "Heartbeat should succeed and persist marker")
            with open(marker_path, "r", encoding="utf-8") as marker_file:
                marker_payload = json.load(marker_file)
            self.assertTrue(marker_payload.get("verified"))
            self.assertIn(marker_payload.get("stage"), ("ORDER_VERIFY", "FILL_VERIFY"))
            self.assertIsNotNone(marker_payload.get("verified_at_epoch"))

        # Verify the pipeline was called with a quantity >= $10 (safe minimum notional)
        buy_call = self._pipeline_mock.call_args_list[0]
        self.assertGreaterEqual(
            float(buy_call.kwargs.get("quantity", 0.0)),
            10.0,
            "Heartbeat buy should be safely sized above micro-order thresholds",
        )

    def test_heartbeat_order_verify_passes_without_immediate_fill_when_configured(self):
        broker = MagicMock()
        broker.connected = True
        broker.get_available_markets = MagicMock(return_value=["BTC-USD"])
        # Pipeline returns 'accepted' (submitted but not filled) to exercise ORDER_VERIFY path
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
            self.assertTrue(result, "ORDER_VERIFY should pass on accepted order without immediate fill")
            with open(marker_path, "r", encoding="utf-8") as marker_file:
                marker_payload = json.loads(marker_file.read())
                self.assertEqual(marker_payload.get("stage"), "ORDER_VERIFY")

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

    def test_heartbeat_marker_refresh_updates_timestamp(self):
        broker = MagicMock()
        broker.connected = True
        broker.get_available_markets = MagicMock(return_value=["BTC-USD"])
        strategy = self._make_strategy_with_broker(broker)
        with tempfile.TemporaryDirectory() as tmp:
            marker_path = f"{tmp}/heartbeat_verified.flag"
            with patch.dict("os.environ", {"HEARTBEAT_MARKER_PATH": marker_path}, clear=False):
                self.assertTrue(strategy._execute_heartbeat_trade())
                with open(marker_path, "r", encoding="utf-8") as marker_file:
                    first_payload = json.loads(marker_file.read())
                time.sleep(0.02)
                self.assertTrue(strategy._execute_heartbeat_trade())
                with open(marker_path, "r", encoding="utf-8") as marker_file:
                    second_payload = json.loads(marker_file.read())
            self.assertGreater(
                float(second_payload.get("verified_at_epoch", 0)),
                float(first_payload.get("verified_at_epoch", 0)),
                "Successful re-verification should refresh marker timestamp",
            )

    def test_heartbeat_executes_with_startup_probe_scopes(self):
        broker = MagicMock()
        broker.connected = True
        broker.get_available_markets = MagicMock(return_value=["BTC-USD"])
        strategy = self._make_strategy_with_broker(broker)
        reasons: list[str] = []

        @contextmanager
        def _capture_scope(reason):
            reasons.append(reason)
            yield

        with patch("bot.trading_strategy.startup_execution_probe_scope", side_effect=_capture_scope):
            self.assertTrue(strategy._execute_heartbeat_trade())

        # The auth probe (AUTH_VERIFY stage) also uses HEARTBEAT_TRADE scope; the buy
        # order and the sell-close order use HEARTBEAT_TRADE and HEARTBEAT_TRADE_CLOSE
        # respectively.  Assert that both buy and close scopes are present in order.
        self.assertIn("HEARTBEAT_TRADE", reasons, "Buy scope must be tagged HEARTBEAT_TRADE")
        self.assertIn("HEARTBEAT_TRADE_CLOSE", reasons, "Close scope must be tagged HEARTBEAT_TRADE_CLOSE")
        hb_idx = next(i for i, r in enumerate(reasons) if r == "HEARTBEAT_TRADE")
        close_idx = next(i for i, r in enumerate(reasons) if r == "HEARTBEAT_TRADE_CLOSE")
        self.assertLess(hb_idx, close_idx, "HEARTBEAT_TRADE scope must precede HEARTBEAT_TRADE_CLOSE scope")


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
        self._pipeline_mock = MagicMock(return_value={"status": "filled", "order_id": "hb-pipeline-ok"})
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
