from __future__ import annotations

from types import ModuleType, SimpleNamespace

from bot import execution_route_metadata_consistency_patch as patch


def test_okx_reroute_stamps_coinbase_fallback_and_symbol(monkeypatch):
    monkeypatch.setenv("NIJA_ALLOWED_EXECUTION_BROKERS", "coinbase,kraken")
    monkeypatch.delenv("NIJA_DISABLED_BROKERS", raising=False)
    module = ModuleType("bot.broker_native_quote_routing_patch")

    request = SimpleNamespace(
        symbol="ATOM-USDT",
        preferred_broker="okx",
        metadata={
            "broker_name": "okx",
            "selected_broker": "okx",
            "execution_broker": "okx",
            "dispatch_broker": "okx",
            "broker_client": object(),
        },
    )

    repaired = patch._strict_reroute(module, request, "ATOM-USDT", "okx_quote_balance_unknown_for_usdt_usdc_buy")

    assert repaired.symbol == "ATOM-USD"
    assert repaired.preferred_broker == "coinbase"
    assert repaired.metadata["broker_name"] == "coinbase"
    assert repaired.metadata["selected_broker"] == "coinbase"
    assert repaired.metadata["execution_broker"] == "coinbase"
    assert repaired.metadata["dispatch_broker"] == "coinbase"
    assert repaired.metadata["route_consistency_marker"] == "20260709ar"
    assert "broker_client" not in repaired.metadata


def test_okx_reroute_respects_allowed_fallback_order(monkeypatch):
    monkeypatch.setenv("NIJA_ALLOWED_EXECUTION_BROKERS", "kraken")
    monkeypatch.setenv("NIJA_OKX_REROUTE_FALLBACK_BROKERS", "coinbase,kraken")
    module = ModuleType("bot.broker_native_quote_routing_patch")
    request = SimpleNamespace(symbol="ADA-USDC", preferred_broker="okx", metadata={"broker_name": "okx"})

    repaired = patch._strict_reroute(module, request, "ADA-USDC", "okx_quote_balance_unknown")

    assert repaired.symbol == "ADA-USD"
    assert repaired.preferred_broker == "kraken"
    assert repaired.metadata["broker_name"] == "kraken"
    assert repaired.metadata["selected_broker"] == "kraken"


def test_patch_replaces_broker_native_reroute_function(monkeypatch):
    monkeypatch.setenv("NIJA_ALLOWED_EXECUTION_BROKERS", "coinbase,kraken")
    module = ModuleType("bot.broker_native_quote_routing_patch")

    def old_reroute(request, symbol, reason):
        request.metadata = {"old": True}
        return request

    module._reroute_away_from_okx = old_reroute

    assert patch._patch_broker_native_quote_module(module) is True

    request = SimpleNamespace(symbol="BAND-USD", preferred_broker="okx", metadata={"broker_name": "okx"})
    repaired = module._reroute_away_from_okx(request, "BAND-USD", "okx_quote_balance_unknown_for_usdt_usdc_buy")

    assert repaired.preferred_broker == "coinbase"
    assert repaired.metadata["execution_broker"] == "coinbase"
    assert repaired.metadata["okx_reroute_original_symbol"] == "BAND-USD"
    assert repaired.metadata["okx_reroute_symbol"] == "BAND-USD"
