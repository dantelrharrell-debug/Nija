from __future__ import annotations

import math

from bot import runtime_all_in_profitability_authority_v324_patch as v324
from bot import runtime_execution_cost_routing_v327_patch as v327


def test_current_public_spot_fee_fallbacks_match_canonical_us_economics():
    assert v324._current_base_fees("coinbase", "BTC-USD")[:2] == (0.0040, 0.0060)
    assert v324._current_base_fees("kraken", "BTC-USD")[:2] == (0.0040, 0.0080)
    assert v324._current_base_fees("okx", "BTC-USDT")[:2] == (0.0020, 0.0035)


def test_router_taker_bps_come_from_canonical_fee_authority():
    assert math.isclose(v327._fallback_taker_bps("coinbase"), 60.0, abs_tol=1e-12)
    assert math.isclose(v327._fallback_taker_bps("kraken"), 80.0, abs_tol=1e-12)
    assert math.isclose(v327._fallback_taker_bps("okx"), 35.0, abs_tol=1e-12)
    assert v327._fallback_taker_bps("alpaca") is None


def test_default_router_profiles_no_longer_use_legacy_optimistic_fees():
    assert v327.install_import_hook()

    from bot.multi_broker_execution_router import MultiBrokerExecutionRouter

    router = MultiBrokerExecutionRouter()
    assert math.isclose(router._brokers["coinbase"].fee_bps, 60.0, abs_tol=1e-12)
    assert math.isclose(router._brokers["kraken"].fee_bps, 80.0, abs_tol=1e-12)
    # Binance is intentionally untouched; v327 does not enable, disable, or
    # invent jurisdiction/account economics for a venue outside the authority.
    assert math.isclose(router._brokers["binance"].fee_bps, 10.0, abs_tol=1e-12)


def test_late_okx_registration_is_normalized_to_us_regular_fallback():
    assert v327.install_import_hook()

    from bot.multi_broker_execution_router import (
        AssetClass,
        BrokerProfile,
        MultiBrokerExecutionRouter,
    )

    router = MultiBrokerExecutionRouter()
    router.register_broker(
        BrokerProfile(
            name="okx",
            asset_classes=[AssetClass.CRYPTO],
            priority=3,
            available=False,
            fee_bps=10.0,
        )
    )
    assert math.isclose(router._brokers["okx"].fee_bps, 35.0, abs_tol=1e-12)
    # Fee normalization must not make an unavailable venue eligible.
    assert router._brokers["okx"].available is False
