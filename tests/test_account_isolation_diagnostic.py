"""Tests for account-local isolation without weakening shared execution gates."""
from bot.account_isolation_diagnostic import (
    AccountReadiness, GlobalReadiness, inspect_account_isolation,
)


def account(name, entitled=True):
    return AccountReadiness(name, entitled, True, True, True, True, True, True)


def global_ready():
    return GlobalReadiness(True, True, True)


def test_suspended_user_does_not_block_healthy_account_diagnostic():
    report = inspect_account_isolation({
        "user:suspended:kraken": account("user:suspended:kraken", False),
        "platform:coinbase": account("platform:coinbase"),
    }, global_ready())
    assert not report["accounts"]["user:suspended:kraken"]["diagnostic_ready"]
    assert report["accounts"]["platform:coinbase"]["diagnostic_ready"]
    assert report["authorizes_orders"] is False


def test_global_kill_switch_blocks_all_accounts():
    report = inspect_account_isolation({
        "platform:coinbase": account("platform:coinbase"),
    }, GlobalReadiness(True, False, True))
    assert not report["accounts"]["platform:coinbase"]["diagnostic_ready"]
    assert "kill_switch_clear" in report["global_missing"]


def test_missing_collector_blocks_only_affected_account():
    broken = AccountReadiness("platform:kraken", True, True, True, True, True, True, False)
    report = inspect_account_isolation({
        "platform:kraken": broken,
        "platform:okx": account("platform:okx"),
    }, global_ready())
    assert not report["accounts"]["platform:kraken"]["diagnostic_ready"]
    assert report["accounts"]["platform:okx"]["diagnostic_ready"]


def test_no_diagnostic_grants_order_authority():
    report = inspect_account_isolation({"platform:okx": account("platform:okx")}, global_ready())
    assert report["accounts"]["platform:okx"]["authorizes_orders"] is False
    assert report["canonical_controller_required"] is True
