from __future__ import annotations

from types import SimpleNamespace

from bot.execution_account_scope_v421_patch import (
    _patch_pre_trade_capital_base,
    canonical_account_id,
)


def _request(*, broker: str, account_id: str = "default", broker_client=None, account_type="platform"):
    return SimpleNamespace(
        preferred_broker=broker,
        account_id=account_id,
        account_type=account_type,
        metadata={"broker_client": broker_client} if broker_client is not None else {},
    )


def test_same_user_on_two_brokers_gets_distinct_risk_keys():
    kraken = _request(broker="kraken", account_id="user-1", account_type="user")
    coinbase = _request(broker="coinbase", account_id="user-1", account_type="user")

    assert canonical_account_id(kraken) == "kraken:user-1"
    assert canonical_account_id(coinbase) == "coinbase:user-1"


def test_default_account_uses_broker_client_user_identity():
    broker_client = SimpleNamespace(user_id="alice")
    request = _request(
        broker="okx",
        account_id="default",
        broker_client=broker_client,
        account_type="user",
    )
    assert canonical_account_id(request) == "okx:alice"


def test_platform_accounts_are_venue_scoped():
    assert canonical_account_id(_request(broker="kraken")) == "kraken:platform"
    assert canonical_account_id(_request(broker="alpaca")) == "alpaca:platform"


def test_pretrade_cap_base_uses_only_account_cash_plus_account_exposure():
    assert _patch_pre_trade_capital_base() is True
    from bot.pre_trade_risk_engine import PreTradeRiskEngine

    engine = PreTradeRiskEngine()
    cap_base = engine._cap_base_usd(
        available_balance_usd=125.0,
        current_total_exposure=75.0,
    )
    assert cap_base == 200.0
