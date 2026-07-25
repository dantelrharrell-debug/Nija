from __future__ import annotations

import bot.multi_account_broker_manager as manager


def test_user_capital_aggregation_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("NIJA_AGGREGATE_USER_CAPITAL_IN_AUTHORITY", raising=False)

    assert manager._aggregate_user_capital_enabled() is False


def test_user_capital_aggregation_requires_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("NIJA_AGGREGATE_USER_CAPITAL_IN_AUTHORITY", "true")

    assert manager._aggregate_user_capital_enabled() is True
