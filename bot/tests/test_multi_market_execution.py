import sys
import threading
import types
from types import SimpleNamespace

import pytest


def _strategy_shell():
    from bot.trading_strategy import TradingStrategy

    strategy = object.__new__(TradingStrategy)
    strategy.broker = None
    strategy.broker_manager = None
    strategy.multi_account_manager = None
    strategy.symbols = []
    strategy._symbols_by_broker = {}
    strategy._symbol_scan_cursor = {}
    strategy._symbol_universe_lock = threading.RLock()
    strategy._last_symbol_refresh_ts = 0.0
    return strategy


def test_symbol_universes_are_scoped_to_each_broker() -> None:
    from bot.broker_manager import BrokerType

    class Broker:
        connected = True

        def __init__(self, broker_type, symbols):
            self.broker_type = broker_type
            self._symbols = symbols

        def get_available_markets(self):
            return list(self._symbols)

    crypto = Broker(BrokerType.COINBASE, ["BTC-USD", "ETH-USD"])
    equities = Broker(BrokerType.ALPACA, ["AAPL", "SPY", "QQQ"])
    strategy = _strategy_shell()
    strategy.multi_account_manager = SimpleNamespace(
        platform_brokers={
            BrokerType.COINBASE: crypto,
            BrokerType.ALPACA: equities,
        }
    )

    strategy._populate_symbols()

    assert strategy._symbols_by_broker["coinbase"] == ["BTC-USD", "ETH-USD"]
    assert strategy._symbols_by_broker["alpaca"] == ["AAPL", "SPY", "QQQ"]
    assert strategy._symbols_for_broker(crypto) == ["BTC-USD", "ETH-USD"]
    assert strategy._symbols_for_broker(equities) == ["AAPL", "SPY", "QQQ"]


def test_large_equity_universe_rotates_across_cycles(monkeypatch) -> None:
    from bot.broker_manager import BrokerType

    broker = SimpleNamespace(broker_type=BrokerType.ALPACA)
    strategy = _strategy_shell()
    strategy._symbols_by_broker["alpaca"] = ["AAPL", "MSFT", "NVDA", "SPY", "QQQ"]
    monkeypatch.setenv("NIJA_MAX_SCAN_SYMBOLS", "2")

    first = strategy._symbols_for_broker(broker)
    second = strategy._symbols_for_broker(broker)
    third = strategy._symbols_for_broker(broker)

    assert first == ["AAPL", "MSFT"]
    assert second == ["NVDA", "SPY"]
    assert third == ["QQQ", "AAPL"]
    assert set(first + second + third) == {"AAPL", "MSFT", "NVDA", "SPY", "QQQ"}


def test_alpaca_discovery_failure_uses_equity_only_fallback() -> None:
    from bot.broker_manager import BrokerType

    broker = SimpleNamespace(
        broker_type=BrokerType.ALPACA,
        get_available_markets=lambda: [],
        get_all_products=lambda: [],
    )
    strategy = _strategy_shell()

    symbols = strategy._symbols_for_broker(broker)

    assert "AAPL" in symbols
    assert "SPY" in symbols
    assert all("-USD" not in symbol for symbol in symbols)


def _install_fake_alpaca_trading_modules(monkeypatch):
    captured = []

    class MarketOrderRequest:
        def __init__(self, **kwargs):
            self.kwargs = dict(kwargs)
            for key, value in kwargs.items():
                setattr(self, key, value)
            captured.append(self)

    class OrderSide:
        BUY = "buy"
        SELL = "sell"

    class TimeInForce:
        DAY = "day"

    alpaca_module = types.ModuleType("alpaca")
    alpaca_module.__path__ = []
    trading_module = types.ModuleType("alpaca.trading")
    trading_module.__path__ = []
    requests_module = types.ModuleType("alpaca.trading.requests")
    requests_module.MarketOrderRequest = MarketOrderRequest
    enums_module = types.ModuleType("alpaca.trading.enums")
    enums_module.OrderSide = OrderSide
    enums_module.TimeInForce = TimeInForce

    monkeypatch.setitem(sys.modules, "alpaca", alpaca_module)
    monkeypatch.setitem(sys.modules, "alpaca.trading", trading_module)
    monkeypatch.setitem(sys.modules, "alpaca.trading.requests", requests_module)
    monkeypatch.setitem(sys.modules, "alpaca.trading.enums", enums_module)
    return captured


def _alpaca_order_broker(*, market_open: bool):
    from bot.broker_manager import AlpacaBroker, BrokerType

    class API:
        def __init__(self):
            self.submitted = []

        def get_clock(self):
            return SimpleNamespace(is_open=market_open)

        def submit_order(self, order_data):
            self.submitted.append(order_data)
            return SimpleNamespace(
                status="accepted",
                id="order-1",
                filled_avg_price=None,
            )

    broker = object.__new__(AlpacaBroker)
    broker.broker_type = BrokerType.ALPACA
    broker.account_identifier = "PLATFORM"
    broker.api = API()
    return broker


def _allow_test_order_dispatch(monkeypatch) -> None:
    from bot import app_store_mode, broker_manager

    monkeypatch.setattr(
        app_store_mode,
        "get_app_store_mode",
        lambda: SimpleNamespace(is_enabled=lambda: False),
    )
    monkeypatch.setattr(
        broker_manager,
        "_reject_if_unauthorized_order_submit",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        broker_manager,
        "_check_broker_isolation",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(broker_manager, "_FIRST_TRADE_EXECUTED", True)


def test_alpaca_quote_sizing_uses_notional_not_share_quantity(monkeypatch) -> None:
    captured = _install_fake_alpaca_trading_modules(monkeypatch)
    _allow_test_order_dispatch(monkeypatch)
    broker = _alpaca_order_broker(market_open=True)

    result = broker.place_market_order(
        "AAPL",
        "buy",
        12.34,
        size_type="quote",
    )

    assert result["status"] == "open"
    assert len(captured) == 1
    assert captured[0].kwargs["notional"] == 12.34
    assert "qty" not in captured[0].kwargs


def test_alpaca_base_sizing_uses_share_quantity(monkeypatch) -> None:
    captured = _install_fake_alpaca_trading_modules(monkeypatch)
    _allow_test_order_dispatch(monkeypatch)
    broker = _alpaca_order_broker(market_open=True)

    result = broker.place_market_order(
        "AAPL",
        "sell",
        0.25,
        size_type="base",
    )

    assert result["status"] == "open"
    assert captured[0].kwargs["qty"] == 0.25
    assert "notional" not in captured[0].kwargs


def test_alpaca_new_entries_fail_closed_outside_regular_session(monkeypatch) -> None:
    captured = _install_fake_alpaca_trading_modules(monkeypatch)
    _allow_test_order_dispatch(monkeypatch)
    broker = _alpaca_order_broker(market_open=False)

    result = broker.place_market_order(
        "SPY",
        "buy",
        10.0,
        size_type="quote",
    )

    assert result == {"status": "skipped", "error": "MARKET_CLOSED"}
    assert captured == []
    assert broker.api.submitted == []


def test_alpaca_invalid_side_fails_closed(monkeypatch) -> None:
    captured = _install_fake_alpaca_trading_modules(monkeypatch)
    _allow_test_order_dispatch(monkeypatch)
    broker = _alpaca_order_broker(market_open=True)

    result = broker.place_market_order(
        "SPY",
        "hold",
        10.0,
        size_type="quote",
    )

    assert result == {"status": "error", "error": "INVALID_ORDER_SIDE"}
    assert captured == []
    assert broker.api.submitted == []


def test_router_does_not_treat_market_closed_skip_as_a_fill(monkeypatch) -> None:
    from bot.multi_broker_execution_router import MultiBrokerExecutionRouter

    monkeypatch.setenv("NIJA_DIRECT_BROKER_VENUE_CASH_HARD_GATE", "false")
    broker = SimpleNamespace(
        place_market_order=lambda *args, **kwargs: {
            "status": "skipped",
            "error": "MARKET_CLOSED",
        }
    )

    with pytest.raises(RuntimeError, match="MARKET_CLOSED"):
        MultiBrokerExecutionRouter._dispatch_direct_broker_market_order(
            broker,
            symbol="SPY",
            side="buy",
            size_usd=10.0,
            metadata={"price_hint_usd": 500.0},
        )


def test_router_dispatches_equity_signal_to_concrete_alpaca_broker(monkeypatch) -> None:
    from bot.broker_manager import BrokerType
    from bot.multi_broker_execution_router import (
        AssetClass,
        MultiBrokerExecutionRouter,
        RouteRequest,
        detect_asset_class,
    )

    submitted = []

    class Broker:
        broker_type = BrokerType.ALPACA
        connected = True

        def get_available_balance(self):
            return 100.0

        def place_market_order(self, symbol, side, quantity, size_type="quote"):
            submitted.append(
                {
                    "symbol": symbol,
                    "side": side,
                    "quantity": quantity,
                    "size_type": size_type,
                }
            )
            return {
                "status": "open",
                "order_id": "alpaca-order-1",
                "filled_price": 475.0,
            }

    broker = Broker()
    monkeypatch.setenv(
        "NIJA_ALLOWED_EXECUTION_BROKERS",
        "okx,coinbase,kraken,alpaca",
    )
    monkeypatch.setenv("NIJA_DIRECT_BROKER_VENUE_CASH_HARD_GATE", "true")
    router = MultiBrokerExecutionRouter()
    router._get_execution_quality_filter = lambda: None
    router._get_scorer = lambda: None

    result = router.route(
        RouteRequest(
            strategy="test",
            symbol="BRK.B",
            side="buy",
            size_usd=25.0,
            preferred_broker="alpaca",
            metadata={
                "broker_client": broker,
                "broker_name": "alpaca",
                "price_hint_usd": 475.0,
            },
        )
    )

    assert detect_asset_class("BRK.B") is AssetClass.EQUITY
    assert result.success is True
    assert result.asset_class == "equity"
    assert result.broker == "alpaca"
    assert submitted == [
        {
            "symbol": "BRK.B",
            "side": "buy",
            "quantity": 25.0,
            "size_type": "quote",
        }
    ]


def test_unwired_derivative_profiles_are_unavailable_by_default() -> None:
    from bot.multi_broker_execution_router import MultiBrokerExecutionRouter

    router = MultiBrokerExecutionRouter()

    for broker_name in (
        "interactive_brokers_equity",
        "interactive_brokers_futures",
        "td_ameritrade_futures",
        "interactive_brokers_options",
        "td_ameritrade_options",
    ):
        assert router._brokers[broker_name].available is False


def test_alpaca_force_liquidation_can_reach_broker_when_market_clock_closed(
    monkeypatch,
) -> None:
    captured = _install_fake_alpaca_trading_modules(monkeypatch)
    _allow_test_order_dispatch(monkeypatch)
    broker = _alpaca_order_broker(market_open=False)

    result = broker.place_market_order(
        "SPY",
        "sell",
        0.5,
        size_type="base",
        force_liquidate=True,
    )

    assert result["status"] == "open"
    assert captured[0].kwargs["qty"] == 0.5


def test_alpaca_market_data_uses_connected_account_credentials(monkeypatch) -> None:
    from bot.broker_manager import AlpacaBroker

    client_credentials = []

    class StockHistoricalDataClient:
        def __init__(self, api_key, api_secret):
            client_credentials.append((api_key, api_secret))

        def get_stock_bars(self, request):
            bars = [
                SimpleNamespace(
                    timestamp=index,
                    open=100,
                    high=101,
                    low=99,
                    close=100.5,
                    volume=1000,
                )
                for index in range(3)
            ]
            return {request.symbol_or_symbols: bars}

    class StockBarsRequest:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    class TimeFrame:
        Minute = "minute"
        Hour = "hour"
        Day = "day"

        def __init__(self, amount, unit):
            self.amount = amount
            self.unit = unit

    historical_module = types.ModuleType("alpaca.data.historical")
    historical_module.StockHistoricalDataClient = StockHistoricalDataClient
    requests_module = types.ModuleType("alpaca.data.requests")
    requests_module.StockBarsRequest = StockBarsRequest
    timeframe_module = types.ModuleType("alpaca.data.timeframe")
    timeframe_module.TimeFrame = TimeFrame
    monkeypatch.setitem(sys.modules, "alpaca.data.historical", historical_module)
    monkeypatch.setitem(sys.modules, "alpaca.data.requests", requests_module)
    monkeypatch.setitem(sys.modules, "alpaca.data.timeframe", timeframe_module)

    broker = object.__new__(AlpacaBroker)
    broker.account_identifier = "USER:alice"
    broker._api_key = "alice-key"
    broker._api_secret = "alice-secret"

    candles = broker.get_candles("AAPL", limit=2)

    assert client_credentials == [("alice-key", "alice-secret")]
    assert len(candles) == 2


def test_alpaca_spendable_balance_excludes_position_equity() -> None:
    from bot.broker_manager import AlpacaBroker

    broker = object.__new__(AlpacaBroker)
    broker.account_identifier = "PLATFORM"
    broker.api = SimpleNamespace(
        get_account=lambda: SimpleNamespace(
            cash="25.50",
            equity="1000.00",
        )
    )

    assert broker.get_account_balance(verbose=False) == 1000.0
    assert broker.get_available_balance() == 25.5


def test_runtime_metadata_guard_recognizes_alpaca_as_supported() -> None:
    from bot import direct_broker_metadata_guard_patch as patch

    assert patch._is_configured_target("alpaca") is True
    assert patch._norm("AlpacaBroker") == "alpaca"


def test_alpaca_declares_stock_equity_and_etf_support() -> None:
    from bot.broker_manager import AlpacaBroker

    broker = object.__new__(AlpacaBroker)

    assert broker.supports_asset_class("stocks") is True
    assert broker.supports_asset_class("equities") is True
    assert broker.supports_asset_class("ETF") is True
    assert broker.supports_asset_class("options") is False
