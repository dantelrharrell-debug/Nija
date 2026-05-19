"""
Unit tests for heartbeat market discovery (PR scope: get_available_markets).

Validates:
1. KrakenBroker implements the BaseBroker.get_available_markets interface
2. Heartbeat executor falls back to built-in market list when discovery returns empty
3. Heartbeat executor still runs when market discovery raises an exception

Safety contract (from problem statement):
- Heartbeat verification MUST NOT become market-discovery dependent.
- An empty or failing get_available_markets() must not block heartbeat execution.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


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
    """Heartbeat executor uses built-in fallback when market discovery returns empty."""

    def _make_minimal_strategy(self):
        """Build a minimal TradingStrategy-shaped object for heartbeat tests."""
        from bot.trading_strategy import TradingStrategy
        strategy = TradingStrategy.__new__(TradingStrategy)
        strategy.heartbeat_last_trade_time = 0
        strategy.heartbeat_trade_count = 0
        strategy.broker = None
        return strategy

    def _make_broker(self, markets):
        """Create a mock broker whose get_available_markets returns *markets*."""
        broker = MagicMock()
        broker.connected = True
        broker.get_available_markets = MagicMock(return_value=markets)
        return broker

    def test_fallback_used_when_market_discovery_returns_empty(self):
        """When get_available_markets() returns [], the fallback list is used and
        execution is not aborted early."""
        import bot.trading_strategy as ts_mod

        strategy = self._make_minimal_strategy()
        broker = self._make_broker([])

        # We expect the heartbeat to proceed past market discovery into order submission.
        # Patch the order submission helper and balance service so execution can succeed.
        fake_order = {'status': 'filled', 'order_id': 'hb-001'}
        with patch.object(ts_mod, 'HEARTBEAT_TRADE_ENABLED', True), \
             patch.object(ts_mod, 'HEARTBEAT_ONESHOT_RESET', False), \
             patch.object(ts_mod, 'HEARTBEAT_TRADE_SIZE_USD', 5.0), \
             patch.object(ts_mod, 'HEARTBEAT_TRADE_MAX_USD', 5.0), \
             patch.object(ts_mod, 'HEARTBEAT_TRADE_INTERVAL_SECONDS', 0), \
             patch.object(ts_mod, 'HEARTBEAT_REQUIRED_FIRST_ACTIVATION', False), \
             patch('bot.trading_strategy.BalanceService') as mock_balance, \
             patch('bot.trading_strategy._submit_market_order_via_pipeline',
                   return_value=fake_order), \
             patch.object(strategy, '_is_heartbeat_one_shot_locked', return_value=False), \
             patch.object(strategy, '_mark_heartbeat_one_shot_lock'), \
             patch.object(strategy, '_get_broker_name', return_value='kraken'):
            mock_balance.get = MagicMock(return_value=100.0)
            result = strategy._execute_heartbeat_trade(broker=broker, force=False)

        # Heartbeat should have executed (fallback markets provided a symbol).
        self.assertTrue(result, "Heartbeat must succeed when fallback market list is used")

    def test_market_discovery_count_logged(self):
        """[HeartbeatTrade] market_discovery_count=%s is emitted during execution."""
        import logging
        import bot.trading_strategy as ts_mod

        strategy = self._make_minimal_strategy()
        broker = self._make_broker(['BTC-USD', 'ETH-USD', 'SOL-USD'])

        fake_order = {'status': 'filled', 'order_id': 'hb-002'}
        log_records = []

        class _Capture(logging.Handler):
            def emit(self, record):
                log_records.append(record.getMessage())

        handler = _Capture()
        ts_logger = logging.getLogger('nija')
        ts_logger.addHandler(handler)
        try:
            with patch.object(ts_mod, 'HEARTBEAT_TRADE_ENABLED', True), \
                 patch.object(ts_mod, 'HEARTBEAT_ONESHOT_RESET', False), \
                 patch.object(ts_mod, 'HEARTBEAT_TRADE_SIZE_USD', 5.0), \
                 patch.object(ts_mod, 'HEARTBEAT_TRADE_MAX_USD', 5.0), \
                 patch.object(ts_mod, 'HEARTBEAT_TRADE_INTERVAL_SECONDS', 0), \
                 patch.object(ts_mod, 'HEARTBEAT_REQUIRED_FIRST_ACTIVATION', False), \
                 patch('bot.trading_strategy.BalanceService') as mock_balance, \
                 patch('bot.trading_strategy._submit_market_order_via_pipeline',
                       return_value=fake_order), \
                 patch.object(strategy, '_is_heartbeat_one_shot_locked', return_value=False), \
                 patch.object(strategy, '_mark_heartbeat_one_shot_lock'), \
                 patch.object(strategy, '_get_broker_name', return_value='kraken'):
                mock_balance.get = MagicMock(return_value=100.0)
                strategy._execute_heartbeat_trade(broker=broker, force=False)
        finally:
            ts_logger.removeHandler(handler)

        matching = [m for m in log_records if 'market_discovery_count' in m]
        self.assertTrue(
            matching,
            "[HeartbeatTrade] market_discovery_count structured log line must be emitted",
        )


class TestHeartbeatExecutesOnDiscoveryFailure(unittest.TestCase):
    """Heartbeat executor continues when get_available_markets raises an exception."""

    def _make_minimal_strategy(self):
        from bot.trading_strategy import TradingStrategy
        strategy = TradingStrategy.__new__(TradingStrategy)
        strategy.heartbeat_last_trade_time = 0
        strategy.heartbeat_trade_count = 0
        strategy.broker = None
        return strategy

    def test_heartbeat_executes_when_market_discovery_raises(self):
        """If get_available_markets() raises, heartbeat falls back and still executes."""
        import bot.trading_strategy as ts_mod

        strategy = self._make_minimal_strategy()
        broker = MagicMock()
        broker.connected = True
        broker.get_available_markets = MagicMock(
            side_effect=ConnectionError("Exchange unreachable")
        )

        fake_order = {'status': 'filled', 'order_id': 'hb-003'}
        with patch.object(ts_mod, 'HEARTBEAT_TRADE_ENABLED', True), \
             patch.object(ts_mod, 'HEARTBEAT_ONESHOT_RESET', False), \
             patch.object(ts_mod, 'HEARTBEAT_TRADE_SIZE_USD', 5.0), \
             patch.object(ts_mod, 'HEARTBEAT_TRADE_MAX_USD', 5.0), \
             patch.object(ts_mod, 'HEARTBEAT_TRADE_INTERVAL_SECONDS', 0), \
             patch.object(ts_mod, 'HEARTBEAT_REQUIRED_FIRST_ACTIVATION', False), \
             patch('bot.trading_strategy.BalanceService') as mock_balance, \
             patch('bot.trading_strategy._submit_market_order_via_pipeline',
                   return_value=fake_order), \
             patch.object(strategy, '_is_heartbeat_one_shot_locked', return_value=False), \
             patch.object(strategy, '_mark_heartbeat_one_shot_lock'), \
             patch.object(strategy, '_get_broker_name', return_value='kraken'):
            mock_balance.get = MagicMock(return_value=100.0)
            result = strategy._execute_heartbeat_trade(broker=broker, force=False)

        self.assertTrue(
            result,
            "Heartbeat must succeed even when get_available_markets() raises an exception",
        )

    def test_heartbeat_executes_when_broker_lacks_get_available_markets(self):
        """If broker has no get_available_markets(), heartbeat uses built-in fallback."""
        import bot.trading_strategy as ts_mod

        strategy = self._make_minimal_strategy()
        # Use SimpleNamespace: no get_available_markets attribute at all
        broker = SimpleNamespace(connected=True)

        fake_order = {'status': 'filled', 'order_id': 'hb-004'}
        with patch.object(ts_mod, 'HEARTBEAT_TRADE_ENABLED', True), \
             patch.object(ts_mod, 'HEARTBEAT_ONESHOT_RESET', False), \
             patch.object(ts_mod, 'HEARTBEAT_TRADE_SIZE_USD', 5.0), \
             patch.object(ts_mod, 'HEARTBEAT_TRADE_MAX_USD', 5.0), \
             patch.object(ts_mod, 'HEARTBEAT_TRADE_INTERVAL_SECONDS', 0), \
             patch.object(ts_mod, 'HEARTBEAT_REQUIRED_FIRST_ACTIVATION', False), \
             patch('bot.trading_strategy.BalanceService') as mock_balance, \
             patch('bot.trading_strategy._submit_market_order_via_pipeline',
                   return_value=fake_order), \
             patch.object(strategy, '_is_heartbeat_one_shot_locked', return_value=False), \
             patch.object(strategy, '_mark_heartbeat_one_shot_lock'), \
             patch.object(strategy, '_get_broker_name', return_value='mock'):
            mock_balance.get = MagicMock(return_value=100.0)
            result = strategy._execute_heartbeat_trade(broker=broker, force=False)

        self.assertTrue(
            result,
            "Heartbeat must succeed when broker has no get_available_markets method",
        )


if __name__ == '__main__':
    unittest.main()
