from __future__ import annotations

from bot import runtime_heartbeat_microcap_proof_v341_patch as patch


class _DummyBroker:
    def __init__(self, broker_type: str) -> None:
        self.broker_type = broker_type


class _DummyStrategy:
    def __init__(self, required: float) -> None:
        self.required = required

    def _resolve_heartbeat_trade_amount_usd(self, broker) -> float:
        return self.required


def test_low_capital_coinbase_floor_matches_execution_hardening() -> None:
    floor = patch._execution_hardening_floor("coinbase", 6.57)
    assert floor is not None
    assert floor >= 7.50


def test_microcap_notional_never_drops_below_hardening_floor() -> None:
    resolved = patch._resolve_microcap_heartbeat_notional(
        configured=5.0,
        micro_floor=1.0,
        hardening_floor=7.50,
    )
    assert resolved == 7.50


def test_funding_status_rejects_underfunded_hardened_heartbeat(monkeypatch) -> None:
    monkeypatch.setattr(patch, "_cached_balance", lambda *_args: (6.57, "unit_cache"))
    monkeypatch.setattr(patch, "_buffer_pct", lambda: 0.0)

    funded, key, balance, spendable, required, source = patch._heartbeat_funding_status(
        _DummyStrategy(required=7.50),
        _DummyBroker("coinbase"),
    )

    assert funded is False
    assert key == "coinbase"
    assert balance == 6.57
    assert spendable == 6.57
    assert required == 7.50
    assert source == "unit_cache"


def test_funding_status_accepts_funded_alternate_venue(monkeypatch) -> None:
    monkeypatch.setattr(patch, "_cached_balance", lambda *_args: (63.19, "unit_cache"))
    monkeypatch.setattr(patch, "_buffer_pct", lambda: 0.10)

    funded, key, balance, spendable, required, source = patch._heartbeat_funding_status(
        _DummyStrategy(required=10.0),
        _DummyBroker("kraken"),
    )

    assert funded is True
    assert key == "kraken"
    assert balance == 63.19
    assert spendable > required
    assert required == 10.0
    assert source == "unit_cache"
