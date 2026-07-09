from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from bot import broker_native_quote_routing_patch as patch


@dataclass
class FakeRequest:
    symbol: str
    side: str = "buy"
    size_usd: float = 10.12
    preferred_broker: str | None = "okx"
    metadata: dict[str, Any] = field(default_factory=dict)


class FakeOkxBroker:
    def __init__(self, payload: dict[str, Any] | None = None):
        self.broker_type = "okx"
        self.NAME = "OKX"
        self._balance_cache = payload or {}


def test_okx_usd_buy_reroutes_when_no_spendable_usdt_or_usdc():
    request = FakeRequest(
        symbol="APT-USD",
        metadata={"broker_client": FakeOkxBroker({"data": [{"details": [{"ccy": "USD", "availBal": "146.26"}]}]}), "broker_name": "okx"},
    )

    repaired, symbol = patch._maybe_route_okx_buy_by_spendable_quote(request, "APT-USD", "APT-USDT", "buy")

    assert symbol == "APT-USD"
    assert repaired.preferred_broker is None
    assert "broker_client" not in repaired.metadata
    assert repaired.metadata["okx_quote_reroute_reason"] in {
        "okx_no_spendable_usdt_or_usdc_for_buy",
        "okx_spendable_quote_below_required_notional",
    }


def test_okx_usd_buy_uses_usdt_when_spendable_usdt_available():
    request = FakeRequest(
        symbol="APT-USD",
        metadata={"broker_client": FakeOkxBroker({"data": [{"details": [{"ccy": "USDT", "availBal": "25.00"}]}]}), "broker_name": "okx"},
    )

    repaired, symbol = patch._maybe_route_okx_buy_by_spendable_quote(request, "APT-USD", "APT-USDT", "buy")

    assert symbol == "APT-USDT"
    assert repaired.symbol == "APT-USDT"
    assert repaired.preferred_broker == "okx"
    assert "broker_client" in repaired.metadata


def test_okx_usd_buy_uses_usdc_when_usdt_missing_but_usdc_available():
    request = FakeRequest(
        symbol="APT-USD",
        metadata={"broker_client": FakeOkxBroker({"data": [{"details": [{"ccy": "USDC", "availBal": "25.00"}]}]}), "broker_name": "okx"},
    )

    repaired, symbol = patch._maybe_route_okx_buy_by_spendable_quote(request, "APT-USD", "APT-USDT", "buy")

    assert symbol == "APT-USDC"
    assert repaired.symbol == "APT-USDC"
    assert repaired.preferred_broker == "okx"
