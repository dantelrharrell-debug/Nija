from __future__ import annotations

from types import SimpleNamespace

from bot import pipeline_order_submitter as submitter


class _KrakenBroker:
    broker_type = SimpleNamespace(value="kraken")
    account_identifier = "platform"
    min_trade_size = 23.0


def test_heartbeat_minimum_above_risk_cap_defers_before_pipeline(monkeypatch) -> None:
    broker = _KrakenBroker()
    pipeline_calls = {"getter": 0}

    class _Request:
        pass

    def _pipeline_getter():
        pipeline_calls["getter"] += 1
        raise AssertionError("pipeline must not be reached for impossible heartbeat size")

    monkeypatch.setattr(
        submitter,
        "_resolve_execution_pipeline_dependencies",
        lambda: (_Request, _pipeline_getter),
    )
    monkeypatch.setattr(submitter, "assert_distributed_writer_authority", lambda: None)
    monkeypatch.setattr(
        submitter,
        "_resolve_available_balance",
        lambda *_args, **_kwargs: 63.20,
    )

    result = submitter.submit_market_order_via_pipeline(
        broker=broker,
        symbol="ETH-USD",
        side="buy",
        quantity=28.75,
        size_type="quote",
        strategy="HEARTBEAT_TRADE",
    )

    assert result["status"] == "error"
    assert result["error"] == "heartbeat_min_notional_exceeds_risk_cap"
    assert result["v2_pre_submit_proven"] is True
    assert result["broker_dispatch"] is False
    assert pipeline_calls["getter"] == 0


def test_heartbeat_size_helper_returns_none_when_constraints_conflict(monkeypatch) -> None:
    monkeypatch.delenv("NIJA_HEARTBEAT_RISK_FRACTION", raising=False)
    broker = _KrakenBroker()

    # 23% of $63.20 is about $14.54, below the $23.23 safe minimum.
    result = submitter._risk_bounded_heartbeat_size(
        broker,
        requested_usd=28.75,
        available_balance_usd=63.20,
    )

    assert result is None


def test_heartbeat_size_helper_keeps_valid_risk_bounded_notional(monkeypatch) -> None:
    monkeypatch.delenv("NIJA_HEARTBEAT_RISK_FRACTION", raising=False)
    broker = _KrakenBroker()

    # With sufficient balance, both the risk cap and broker minimum can hold.
    result = submitter._risk_bounded_heartbeat_size(
        broker,
        requested_usd=50.0,
        available_balance_usd=200.0,
    )

    assert result is not None
    assert result >= 23.23
    assert result <= 46.0


def test_internal_dispatch_contract_classifies_local_heartbeat_minimum_rejects() -> None:
    from bot.execution_dispatch_contract import is_internal_dispatch_failure

    assert is_internal_dispatch_failure(
        "heartbeat_min_notional_exceeds_risk_cap"
    )
    assert is_internal_dispatch_failure(
        "INTERNAL_DISPATCH_FAILURE: pre-dispatch:VOLUME_TOO_SMALL"
    )
    # A bare venue rejection must remain exchange-originated.
    assert not is_internal_dispatch_failure("VOLUME_TOO_SMALL")
