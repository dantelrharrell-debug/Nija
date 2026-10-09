"""Offline coverage replay and confirmed-ledger/account-isolation regressions."""
from types import SimpleNamespace

import pytest

from bot.market_scan_coverage import MarketScanCoverage, get_market_scan_coverage
from bot.phase3_scan_budget_patch import _rotate_symbols
from bot.confirmed_performance_report import get_confirmed_performance_report
from bot import runtime_all_in_profitability_authority_v324_core as economics


@pytest.mark.parametrize("budget", [1, 2, 8, 24])
def test_priority_symbols_and_long_tail_never_starve(budget):
    universe = [f"{base}-USD" for base in
                ("BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "LINK", "LTC", "BCH", "AVAX")]
    universe += [f"TAIL{i}-USD" for i in range(40)]
    state = {}
    seen = set()
    for _ in range(len(universe) * 2):
        selected, _, _ = _rotate_symbols(universe, budget, state)
        assert len(selected) <= budget
        assert len(selected) == len(set(selected))
        seen.update(selected)
    assert seen == set(universe)


def test_nested_windows_replay_covers_all_1000_symbols():
    """A 100-symbol outer window and eight-symbol inner budget must converge."""
    universe = [f"S{i}" for i in range(1000)]
    coverage = MarketScanCoverage()
    downstream = {}
    for cycle in range(200):
        window = coverage.select(universe, start=(cycle * 100) % len(universe), limit=100)
        selected, _, _ = _rotate_symbols(window, 8, downstream)
        for symbol in selected:
            coverage.record_evaluation(symbol)
            coverage.record_data_result(symbol, available=True)
    report = coverage.snapshot()
    assert report["evaluated"] == 1000
    assert report["not_evaluated"] == 0
    assert report["global_coverage_verified"] is False
    assert report["candle_freshness_verified"] is False


def test_admission_is_not_evaluation_and_accounts_do_not_share_coverage():
    first, second = SimpleNamespace(), SimpleNamespace()
    a, b = get_market_scan_coverage(first), get_market_scan_coverage(second)
    a.select(["BTC-USD", "ETH-USD"], start=0, limit=2)
    b.select(["BTC-USD", "ETH-USD"], start=0, limit=2)
    assert a.snapshot()["evaluated"] == 0
    a.record_evaluation("BTC-USD")
    assert a.snapshot()["evaluated"] == 1
    assert a.snapshot()["data_available"] == 0
    assert b.snapshot()["evaluated"] == 0
    assert a.select(["BTC-USD", "ETH-USD"], start=0, limit=1) == ["ETH-USD"]


def test_removed_symbols_are_not_counted_in_current_coverage():
    coverage = MarketScanCoverage()
    coverage.select(["OLD", "NEW"], start=0, limit=2)
    coverage.record_evaluation("OLD")
    coverage.select(["NEW"], start=0, limit=1)
    assert coverage.snapshot()["evaluated"] == 0


def test_phase3_wrapper_keeps_broker_rotation_independent(monkeypatch):
    from types import ModuleType
    from bot import phase3_scan_budget_patch as patch

    class Core:
        def _phase3_scan_and_enter(self, broker, snapshot, symbols, available_slots, zero_signal_streak=0):
            self.selected = list(symbols)
            return (0, 0, len(symbols), {})

    module = ModuleType("bot.nija_core_loop")
    module.NijaCoreLoop = Core
    assert patch._install_on_module(module)
    monkeypatch.setenv("NIJA_PHASE3_MAX_SYMBOLS_PER_CYCLE", "8")
    owner = Core()
    first, second = SimpleNamespace(broker_type="alpaca"), SimpleNamespace(broker_type="alpaca")
    universe = [f"S{i}" for i in range(100)]
    owner._phase3_scan_and_enter(first, SimpleNamespace(), universe, 1)
    initial = owner.selected
    owner._phase3_scan_and_enter(first, SimpleNamespace(), universe, 1)
    assert owner.selected != initial
    owner._phase3_scan_and_enter(second, SimpleNamespace(), universe, 1)
    assert owner.selected == initial


def test_strategy_window_uses_actual_visit_coverage(monkeypatch):
    from bot.trading_strategy import TradingStrategy
    from bot.broker_manager import BrokerType

    broker = SimpleNamespace(broker_type=BrokerType.ALPACA)
    strategy = object.__new__(TradingStrategy)
    strategy._ensure_symbol_universe_state()
    strategy._symbols_by_broker["alpaca"] = ["AAPL", "MSFT", "NVDA", "SPY"]
    monkeypatch.setenv("NIJA_MAX_SCAN_SYMBOLS", "2")
    assert strategy._symbols_for_broker(broker) == ["AAPL", "MSFT"]
    get_market_scan_coverage(broker).record_evaluation("AAPL")
    assert strategy._symbols_for_broker(broker) == ["NVDA", "SPY"]
    assert strategy._symbols_for_broker(broker) == ["MSFT", "NVDA"]


@pytest.fixture
def ledger(tmp_path):
    from bot.trade_ledger_db import TradeLedgerDB
    return TradeLedgerDB(str(tmp_path / "ledger.db"))


def _closed(ledger, position, *, symbol="BTC-USD", broker="kraken", user="platform",
            gross=1.0, fees=0.2, direction="LONG", reason="canonical_confirmed_fill"):
    with ledger._get_connection() as conn:
        conn.execute(
            """INSERT INTO completed_trades
            (position_id, user_id, symbol, side, entry_price, exit_price, quantity,
             size_usd, entry_time, exit_time, gross_profit, total_fees,
             entry_fee, exit_fee, net_profit, exit_reason)
            VALUES (?, ?, ?, ?, 100, 101, 1, 100, '2026-10-08', '2026-10-08', ?, ?, ?, ?, ?, ?)""",
            (position, user, symbol, direction, gross, fees, fees / 2, fees / 2, gross - fees, reason),
        )
        conn.execute(
            """INSERT INTO trade_ledger
            (timestamp, user_id, symbol, side, action, price, quantity, size_usd,
             order_id, position_id, notes) VALUES ('2026-10-08', ?, ?, 'SELL', 'CLOSE',
             101, 1, 101, ?, ?, ?)""",
            (user, symbol, "ORDER-" + position, position,
             f"exit_reason={reason}; broker={broker}; net_pnl={gross - fees}"),
        )
        if broker == "kraken" and reason == "canonical_confirmed_fill":
            account = "platform:kraken" if user == "platform" else f"user:{user}:kraken"
            entry_id = "ENTRY-" + position
            conn.execute(
                """INSERT INTO trade_ledger
                (timestamp, user_id, symbol, side, action, price, quantity,
                 size_usd, fee, order_id, position_id, notes)
                VALUES ('2026-10-08', ?, ?, ?, 'OPEN', 100, 1, 100, ?, ?, ?, ?)""",
                (
                    user, symbol, "BUY" if direction == "LONG" else "SELL",
                    fees / 2, entry_id, position,
                    f"authenticated_kraken_queryorders_entry; order_id={entry_id}; account={account}",
                ),
            )


def test_net_winners_losers_breakeven_and_owner_isolation(ledger):
    _closed(ledger, "a", gross=2, fees=.2)
    _closed(ledger, "b", gross=.1, fees=.2, symbol="ETH-USD", direction="SHORT")
    _closed(ledger, "c", gross=.2, fees=.2)
    _closed(ledger, "other-venue", broker="coinbase", gross=999)
    _closed(ledger, "other-user", user="customer", gross=999)
    _closed(ledger, "manual", reason="manual_close", gross=999)
    report = get_confirmed_performance_report(ledger, broker="kraken", user_id="platform")
    assert report["overall"]["trades"] == 3
    assert report["overall"]["wins"] == 1
    assert report["overall"]["losses"] == 1
    assert report["overall"]["breakeven"] == 1
    assert report["overall"]["net_pnl_usd"] == pytest.approx(1.7)
    assert report["overall"]["profit_factor"] == pytest.approx(18)
    assert report["losers"][0]["direction"] == "short"
    assert report["strategy_attribution"] == "unavailable"
    assert report["automatic_trading_changes"] is False


def test_late_fee_updates_and_duplicate_close_rows_do_not_inflate_results(ledger):
    _closed(ledger, "a", gross=2, fees=.2)
    with ledger._get_connection() as conn:
        conn.execute("UPDATE completed_trades SET total_fees=3, entry_fee=1, exit_fee=2, net_profit=-1")
        conn.execute("UPDATE trade_ledger SET fee=1 WHERE action='OPEN' AND position_id='a'")
        conn.execute("""INSERT INTO trade_ledger
            (timestamp,user_id,symbol,side,action,price,quantity,size_usd,order_id,position_id,notes)
            SELECT timestamp,user_id,symbol,side,action,price,quantity,size_usd,order_id,position_id,notes
            FROM trade_ledger WHERE action='CLOSE'""")
    report = get_confirmed_performance_report(ledger, broker="kraken", user_id="platform")
    assert report["overall"]["trades"] == 1
    assert report["overall"]["losses"] == 1
    assert report["overall"]["net_pnl_usd"] == -1


def test_fee_inconsistent_rows_are_excluded(ledger):
    _closed(ledger, "a")
    with ledger._get_connection() as conn:
        conn.execute("UPDATE completed_trades SET net_profit=100")
    report = get_confirmed_performance_report(ledger, broker="kraken", user_id="platform")
    assert report["overall"]["trades"] == 0
    assert report["excluded_invalid_rows"] == 1


def test_unverified_kraken_close_cannot_inflate_winner_loser_totals(ledger):
    _closed(ledger, "real", gross=5, fees=0.2)
    _closed(ledger, "unproven", gross=999, fees=0.2)
    with ledger._get_connection() as conn:
        conn.execute(
            "DELETE FROM trade_ledger WHERE position_id='unproven' AND action='OPEN'"
        )
    report = get_confirmed_performance_report(
        ledger, broker="kraken", user_id="platform",
    )
    assert report["overall"]["trades"] == 1
    assert report["overall"]["net_pnl_usd"] == pytest.approx(4.8)
    assert report["excluded_kraken_closes_without_authenticated_open"] == 1


def test_unscoped_report_rejected(ledger):
    with pytest.raises(ValueError):
        get_confirmed_performance_report(ledger, broker="kraken", user_id="")


@pytest.mark.parametrize("status", ["hard_to_borrow", "unavailable", "unknown_new_status"])
def test_current_borrow_status_overrides_deprecated_easy_flag(status):
    broker = SimpleNamespace(get_asset=lambda symbol: {
        "shortable": True, "borrow_status": status, "easy_to_borrow": True,
    })
    strategy = SimpleNamespace(broker_client=broker, _get_broker_name=lambda: "alpaca")
    ok, _ = economics._short_capability(strategy, "AAPL", {})
    assert ok is False


@pytest.mark.parametrize("changes,expected", [
    ({}, True), ({"equity": "1999.99"}, False), ({"equity": "nan"}, False),
    ({"shorting_enabled": False}, False), ({"trading_blocked": True}, False),
    ({"account_blocked": True}, False), ({"trade_suspended_by_user": True}, False),
    ({"status": "approval_pending"}, False),
])
def test_alpaca_asset_adapter_reads_account_eligibility(changes, expected):
    from bot.broker_manager import AlpacaBroker
    account = {"equity": "2000", "shorting_enabled": True, "status": "active",
               "trading_blocked": False, "account_blocked": False, "trade_suspended_by_user": False}
    account.update(changes)
    asset = {"symbol": "AAPL", "shortable": True, "tradable": True,
             "status": "active", "borrow_status": "easy_to_borrow"}
    broker = object.__new__(AlpacaBroker)
    broker.api = SimpleNamespace(get_account=lambda: account, get_asset=lambda symbol: asset)
    metadata = broker.get_asset("AAPL")
    assert metadata["shortable"] is expected
    assert metadata["account_shorting_eligible"] is expected


def test_alpaca_asset_read_failure_does_not_authorize_shorting():
    from bot.broker_manager import AlpacaBroker
    broker = object.__new__(AlpacaBroker)
    broker.api = None
    assert broker.get_asset("AAPL") == {}


def test_coinbase_catalog_keeps_long_tickers_and_excludes_restricted_products(monkeypatch):
    from bot import broker_manager
    from bot.broker_manager import CoinbaseBroker

    def product(symbol, **kwargs):
        return {"product_id": symbol, "status": "online", "product_type": "SPOT", **kwargs}

    products = [product("VERYLONGTICKER-USD"), product("X-USD"), product("BTC-USD"),
                product("VIEW-USD", view_only=True), product("OFF-USD", is_disabled=True),
                product("LIMIT-USD", limit_only=True), product("POST-USD", post_only=True),
                product("CANCEL-USD", cancel_only=True), product("AUCTION-USD", auction_mode=True),
                product("FUTURE-USD", product_type="FUTURE")]
    broker = object.__new__(CoinbaseBroker)
    broker.client = SimpleNamespace(get_products=lambda **kwargs: {"products": products})
    broker._rate_limiter = None
    monkeypatch.setattr(broker_manager.time, "sleep", lambda seconds: None)
    assert set(broker.get_all_products()) == {"VERYLONGTICKER-USD", "X-USD", "BTC-USD"}


def test_kraken_catalog_excludes_offline_and_exact_quote_mismatches(monkeypatch):
    from bot import broker_manager
    from bot.broker_manager import KrakenBroker

    broker = object.__new__(KrakenBroker)
    # Exercise the adapter's row protocol without a heavyweight test dependency.
    rows = [
        {"wsname": "XBT/USD", "status": "online"},
        {"wsname": "ETH/USDT", "status": "online"},
        {"wsname": "DOGE/USDC", "status": "online"},
        {"wsname": "BAD/USD", "status": "cancel_only"},
        {"wsname": "BAD2/USD1", "status": "online"},
        {"wsname": "BAD3/EUR", "status": "online"},
    ]
    catalog = SimpleNamespace(iterrows=lambda: iter(enumerate(rows)))
    broker.kraken_api = SimpleNamespace(get_tradable_asset_pairs=lambda: catalog)
    broker._initialize_kraken_market_data = lambda: None
    monkeypatch.setattr(broker_manager, "get_kraken_symbol_mapper", None)
    assert set(broker.get_all_products()) == {"BTC-USD", "ETH-USDT", "DOGE-USDC"}
