from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from bot import pipeline_order_submitter as submitter


class _Broker:
    broker_type = "coinbase"

    def __init__(self, account_identifier: str, balance: float) -> None:
        self.account_identifier = account_identifier
        self._balance = float(balance)

    def get_account_balance(self):
        return {"equity": self._balance, "available_balance": self._balance}

    def get_current_price(self, _symbol: str) -> float:
        return 10.0


class _Pipeline:
    def __init__(self) -> None:
        self.calls = 0
        self.request = None

    def execute(self, request):
        self.calls += 1
        self.request = request
        return SimpleNamespace(
            success=False,
            error="rejected before dispatch",
            order_id="",
            fill_price=0.0,
            filled_size_usd=0.0,
            broker=getattr(request, "preferred_broker", "coinbase"),
        )


def _submit(broker, pipeline, *, side="buy", quantity=10.0, size_type="quote"):
    with patch.object(
        submitter,
        "_resolve_execution_pipeline_dependencies",
        return_value=(SimpleNamespace, lambda: pipeline),
    ), patch.object(
        submitter,
        "assert_distributed_writer_authority",
        return_value=None,
    ):
        return submitter.submit_market_order_via_pipeline(
            broker=broker,
            symbol="BTC-USD",
            side=side,
            quantity=quantity,
            size_type=size_type,
            strategy="capital-floor-integration-test",
        )


def test_platform_entry_blocks_before_coinbase_reserve() -> None:
    broker = _Broker("platform", 350.0)
    pipeline = _Pipeline()

    result = _submit(broker, pipeline, side="buy", quantity=10.0)

    assert result["status"] == "error"
    assert result["broker_dispatch"] is False
    assert result["capital_floor_guard_scope"] == "platform"
    assert result["capital_floor_required_usd"] == 400.0
    assert result["error"].startswith("broker_capital_floor_blocked:")
    assert pipeline.calls == 0


def test_user_entry_does_not_inherit_nija_platform_reserve() -> None:
    broker = _Broker("user:customer-1", 100.0)
    pipeline = _Pipeline()

    result = _submit(broker, pipeline, side="buy", quantity=10.0)

    assert result["status"] == "error"
    assert result["error"] == "rejected before dispatch"
    assert pipeline.calls == 1
    assert pipeline.request.metadata["capital_floor_guard_scope"] == "user"
    assert pipeline.request.metadata["capital_floor_required_usd"] == 0.0


def test_owned_crypto_base_sell_is_treated_as_risk_reducing_exit() -> None:
    broker = _Broker("platform", 100.0)
    pipeline = _Pipeline()

    result = _submit(
        broker,
        pipeline,
        side="sell",
        quantity=1.0,
        size_type="base",
    )

    assert result["status"] == "error"
    assert result["error"] == "rejected before dispatch"
    assert pipeline.calls == 1
    assert pipeline.request.intent_type == "exit"
    assert pipeline.request.position_effect == "close"
    assert pipeline.request.metadata["closing_position"] is True
    assert pipeline.request.metadata["capital_floor_guard_state"] == "EXIT_ONLY"
