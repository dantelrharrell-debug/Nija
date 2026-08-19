from decimal import Decimal

from bot.liquidity_routing_system import Exchange, LiquidityRoutingSystem


def D(value):
    return Decimal(str(value))


def test_backward_compatible_order_book_update_and_summary():
    router = LiquidityRoutingSystem()
    router.update_order_book(
        Exchange.COINBASE,
        "BTC-USD",
        bids=[(D(100), D(2))],
        asks=[(D(101), D(2))],
    )
    summary = router.get_liquidity_summary("BTC-USD")
    assert summary["num_exchanges"] == 1
    assert summary["venue_metrics"]["coinbase"]["buy"]["side_depth"] == 2.0


def test_deeper_lower_volatility_venue_can_beat_tiny_price_edge():
    router = LiquidityRoutingSystem(
        {
            "fee_rates": {"coinbase": 0.001, "kraken": 0.001},
            "max_microstructure_penalty_bps": 30,
            "venue_profiles": {
                "coinbase": {"max_participation_rate": 1.0},
                "kraken": {"max_participation_rate": 1.0},
            },
        }
    )

    for bid, ask in [(100, 100.10), (96, 96.10), (104, 104.10), (99, 99.10), (100, 100.10)]:
        router.update_order_book(
            Exchange.COINBASE,
            "BTC-USD",
            bids=[(D(bid), D("0.10"))],
            asks=[(D(ask), D("0.10"))],
        )

    for bid, ask in [(100, 100.12)] * 5:
        router.update_order_book(
            Exchange.KRAKEN,
            "BTC-USD",
            bids=[(D(bid), D("5"))],
            asks=[(D(ask), D("5"))],
        )

    coinbase = router.get_venue_metrics(Exchange.COINBASE, "BTC-USD", "buy", D(1))
    kraken = router.get_venue_metrics(Exchange.KRAKEN, "BTC-USD", "buy", D(1))
    assert kraken["venue_score"] > coinbase["venue_score"]
    assert kraken["realized_volatility_pct"] < coinbase["realized_volatility_pct"]
    assert kraken["side_depth"] > coinbase["side_depth"]

    best = router.get_best_venue("BTC-USD", "buy", D(1))
    assert best["exchange"] == "kraken"

    route = router.find_best_route("BTC-USD", "buy", D(1))
    assert route is not None
    assert route.segments[0].exchange == Exchange.KRAKEN


def test_exchange_specific_profile_override_changes_sensitivity():
    router = LiquidityRoutingSystem(
        {
            "fee_rates": {"coinbase": 0.001, "kraken": 0.001},
            "venue_profiles": {
                "coinbase": {
                    "depth_weight": 0.10,
                    "spread_weight": 0.70,
                    "volatility_weight": 0.10,
                    "fee_weight": 0.10,
                },
                "kraken": {
                    "depth_weight": 0.70,
                    "spread_weight": 0.10,
                    "volatility_weight": 0.10,
                    "fee_weight": 0.10,
                },
            },
        }
    )
    router.update_order_book(
        Exchange.COINBASE,
        "ETH-USD",
        bids=[(D(100), D(1))],
        asks=[(D("100.01"), D(1))],
    )
    router.update_order_book(
        Exchange.KRAKEN,
        "ETH-USD",
        bids=[(D(100), D(10))],
        asks=[(D("100.10"), D(10))],
    )
    cb = router.get_venue_metrics(Exchange.COINBASE, "ETH-USD", "buy", D(5))
    kr = router.get_venue_metrics(Exchange.KRAKEN, "ETH-USD", "buy", D(5))
    assert cb["depth_score"] < kr["depth_score"]
    assert cb["spread_pct"] < kr["spread_pct"]
    assert 0 <= cb["venue_score"] <= 1
    assert 0 <= kr["venue_score"] <= 1


def test_single_venue_keeps_full_participation_capacity():
    router = LiquidityRoutingSystem(
        {"venue_profiles": {"kraken": {"max_participation_rate": 0.10}}}
    )
    router.update_order_book(
        Exchange.KRAKEN,
        "BTC-USD",
        bids=[(D(100), D(10))],
        asks=[(D(101), D(10))],
    )
    route = router.find_best_route("BTC-USD", "buy", D(2))
    assert route is not None
    assert route.total_size == D(2)
