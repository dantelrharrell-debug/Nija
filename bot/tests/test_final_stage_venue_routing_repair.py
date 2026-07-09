from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from bot import final_stage_venue_routing_repair_patch as patch


@dataclass
class FakeRequest:
    symbol: str = "BASED-USD"
    side: str = "buy"
    size_usd: float = 23.10
    preferred_broker: str | None = "kraken"
    metadata: dict[str, Any] = field(default_factory=dict)


class FakeKrakenBroker:
    connected = True
    NAME = "kraken"

    def get_account_balance(self):
        return 333.43

    def place_market_order(self, symbol, side, quantity, size_type="quote"):
        return {"status": "filled", "order_id": "KRAKEN-1", "price": 1.0, "filled_size_usd": quantity}


class FakeRouter:
    kraken = FakeKrakenBroker()


def test_compliance_error_detection():
    assert patch._is_compliance_error("OKX_ORDER_REJECTED code=1 raw={'sCode':'51155'}")
    assert patch._is_compliance_error("You can't trade this pair due to local compliance restrictions")
    assert not patch._is_compliance_error("insufficient funds")


def test_compliance_route_quarantine_and_skip():
    patch._COMPLIANCE_DISABLED.clear()
    patch._disable_compliance_route("okx", "AVAX-USDC", "51155")
    assert patch._is_disabled("okx", "AVAX-USDC") is True
    assert patch._is_disabled("coinbase", "AVAX-USDC") is False


def test_bind_preferred_live_client(monkeypatch):
    router = FakeRouter()
    req = FakeRequest(preferred_broker="kraken", metadata={})

    monkeypatch.setattr(patch, "_resolve_live_client", lambda _router, target: router.kraken if target == "kraken" else None)
    repaired = patch._bind_preferred_live_client(router, req, reason="test")

    assert repaired.metadata["broker_client"] is router.kraken
    assert repaired.metadata["broker_name"] == "kraken"
    assert repaired.metadata["preferred_broker"] == "kraken"


def test_disabled_preferred_route_clears_preferred():
    patch._COMPLIANCE_DISABLED.clear()
    patch._disable_compliance_route("okx", "AVAX-USDC", "51155")
    req = FakeRequest(symbol="AVAX-USDC", preferred_broker="okx", metadata={"broker_client": object(), "broker_name": "okx"})

    repaired = patch._bind_preferred_live_client(FakeRouter(), req, reason="test")

    assert repaired.preferred_broker is None
    assert "broker_client" not in repaired.metadata
    assert repaired.metadata["disabled_broker_route"] == "okx"
