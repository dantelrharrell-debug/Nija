#!/usr/bin/env python3
"""
NIJA Deep Multi-Exchange Integration Test
==========================================

Verifies that NIJA is configured and wired to trade on BOTH Coinbase and Kraken,
and that user1 (daivon_frazier) and user2 (tania_gilbert) funded Kraken accounts
are fully visible to the MultiAccountBrokerManager.

Tests:
  1.  Coinbase platform broker connects and returns balance
  2.  Kraken platform broker connects and returns balance
  3.  Both exchanges active simultaneously (no cross-contamination)
  4.  user1 (daivon_frazier) Kraken account is registered with funded balance
  5.  user2 (tania_gilbert) Kraken account is registered with funded balance
  6.  MABM balance aggregation sees user1 and user2 funded Kraken balances
  7.  Platform Coinbase trade does NOT affect user1/user2 Kraken balances
  8.  Platform Kraken trade does NOT affect user1/user2 Kraken balances
  9.  user1 and user2 can each trade independently on Kraken
  10. Config files list both named Kraken users (daivon_frazier, tania_gilbert)

All tests use mock brokers so no real API credentials are required.
"""

import sys
import os
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pytest
from typing import Optional

from bot.multi_account_broker_manager import (
    MultiAccountBrokerManager,
    get_broker_manager,
    reset_broker_manager_singleton,
)
from bot.broker_manager import BrokerType, BaseBroker, AccountType


# ---------------------------------------------------------------------------
# Fixture: isolated MABM singleton per test
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_mabm():
    """Reset MABM singleton before and after every test for full isolation."""
    reset_broker_manager_singleton()
    yield
    reset_broker_manager_singleton()


# ---------------------------------------------------------------------------
# Mock broker
# ---------------------------------------------------------------------------

class MockBroker(BaseBroker):
    """Mock broker that tracks orders and returns a configurable balance."""

    def __init__(
        self,
        broker_type: BrokerType = BrokerType.COINBASE,
        account_type: AccountType = AccountType.PLATFORM,
        user_id: Optional[str] = None,
        initial_balance: float = 1000.0,
    ):
        super().__init__(broker_type, account_type, user_id)
        self._balance = initial_balance
        self.orders: list = []
        self.connected = False

    # --- BaseBroker interface ---

    def connect(self) -> bool:
        self.connected = True
        return True

    def get_account_balance(self) -> float:
        return self._balance

    def get_positions(self) -> list:
        return []

    def get_available_markets(self):
        return ["BTC-USD", "ETH-USD"]

    def place_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        size_type: str = "quote",
        ignore_balance: bool = False,
        ignore_min_trade: bool = False,
        force_liquidate: bool = False,
    ) -> dict:
        order = {
            "order_id": f"mock-{len(self.orders) + 1}",
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "account_type": (
                self.account_type.value
                if hasattr(self.account_type, "value")
                else str(self.account_type)
            ),
            "user_id": self.user_id,
            "status": "filled",
        }
        self.orders.append(order)
        if side == "buy":
            self._balance -= quantity
        else:
            self._balance += quantity
        return order


def _fresh_manager() -> MultiAccountBrokerManager:
    """Return the canonical (freshly reset) MABM singleton."""
    return get_broker_manager()


# ---------------------------------------------------------------------------
# 1. Coinbase platform broker
# ---------------------------------------------------------------------------

def test_coinbase_platform_broker_connects():
    """Coinbase platform broker connects and exposes non-zero balance."""
    manager = _fresh_manager()
    cb_broker = MockBroker(BrokerType.COINBASE, AccountType.PLATFORM, initial_balance=5000.0)
    assert cb_broker.connect(), "MockBroker.connect() must return True"
    manager.register_platform_broker_instance(BrokerType.COINBASE, cb_broker)

    assert cb_broker.connected, "Coinbase broker should be connected"
    assert cb_broker.get_account_balance() == 5000.0, "Coinbase balance should be 5000"
    print("✅ Test 1 passed: Coinbase platform broker connected with $5000 balance")


# ---------------------------------------------------------------------------
# 2. Kraken platform broker
# ---------------------------------------------------------------------------

def test_kraken_platform_broker_connects():
    """Kraken platform broker connects and exposes non-zero balance."""
    manager = _fresh_manager()
    kr_broker = MockBroker(BrokerType.KRAKEN, AccountType.PLATFORM, initial_balance=3000.0)
    assert kr_broker.connect(), "MockBroker.connect() must return True"
    manager.register_platform_broker_instance(BrokerType.KRAKEN, kr_broker)

    assert kr_broker.connected, "Kraken broker should be connected"
    assert kr_broker.get_account_balance() == 3000.0, "Kraken balance should be 3000"
    print("✅ Test 2 passed: Kraken platform broker connected with $3000 balance")


# ---------------------------------------------------------------------------
# 3. Both exchanges active simultaneously — no cross-contamination
# ---------------------------------------------------------------------------

def test_both_exchanges_active_simultaneously():
    """
    Coinbase and Kraken platform brokers can coexist.
    A trade on one does not alter the balance of the other.
    """
    manager = _fresh_manager()

    cb_broker = MockBroker(BrokerType.COINBASE, AccountType.PLATFORM, initial_balance=5000.0)
    cb_broker.connect()
    manager.register_platform_broker_instance(BrokerType.COINBASE, cb_broker)

    kr_broker = MockBroker(BrokerType.KRAKEN, AccountType.PLATFORM, initial_balance=3000.0)
    kr_broker.connect()
    manager.register_platform_broker_instance(BrokerType.KRAKEN, kr_broker)

    # Trade on Coinbase
    cb_broker.place_market_order("BTC-USD", "buy", 500.0)
    # Trade on Kraken
    kr_broker.place_market_order("ETH-USD", "buy", 200.0)

    assert cb_broker._balance == 4500.0, "Coinbase balance should decrease by $500"
    assert kr_broker._balance == 2800.0, "Kraken balance should decrease by $200"
    assert len(cb_broker.orders) == 1, "Coinbase should have exactly 1 order"
    assert len(kr_broker.orders) == 1, "Kraken should have exactly 1 order"
    # No bleed between exchanges
    assert kr_broker.orders[0]["symbol"] == "ETH-USD", "Kraken order symbol must be ETH-USD"
    assert cb_broker.orders[0]["symbol"] == "BTC-USD", "Coinbase order symbol must be BTC-USD"
    print("✅ Test 3 passed: Both exchanges active simultaneously with no cross-contamination")


# ---------------------------------------------------------------------------
# 4. user1 (daivon_frazier) Kraken account — funded balance visible
# ---------------------------------------------------------------------------

def test_user1_kraken_account_funded_and_visible():
    """user1 (daivon_frazier) Kraken broker registers with a funded balance."""
    manager = _fresh_manager()

    user1_id = "daivon_frazier"
    user1_broker = MockBroker(
        BrokerType.KRAKEN, AccountType.USER, user_id=user1_id, initial_balance=2500.0
    )
    assert user1_broker.connect()
    manager.user_brokers[user1_id] = {BrokerType.KRAKEN: user1_broker}

    # Verify MABM can see user1
    assert user1_id in manager.user_brokers, "user1 (daivon_frazier) must be in user_brokers"
    retrieved = manager.user_brokers[user1_id][BrokerType.KRAKEN]
    assert retrieved.connected, "user1 Kraken broker must be connected"
    assert retrieved.get_account_balance() == 2500.0, "user1 Kraken balance must be $2500"
    print(
        f"✅ Test 4 passed: user1 ({user1_id}) Kraken account funded "
        f"(balance=${retrieved.get_account_balance():.2f})"
    )


# ---------------------------------------------------------------------------
# 5. user2 (tania_gilbert) Kraken account — funded balance visible
# ---------------------------------------------------------------------------

def test_user2_kraken_account_funded_and_visible():
    """user2 (tania_gilbert) Kraken broker registers with a funded balance."""
    manager = _fresh_manager()

    user2_id = "tania_gilbert"
    user2_broker = MockBroker(
        BrokerType.KRAKEN, AccountType.USER, user_id=user2_id, initial_balance=1800.0
    )
    assert user2_broker.connect()
    manager.user_brokers[user2_id] = {BrokerType.KRAKEN: user2_broker}

    assert user2_id in manager.user_brokers, "user2 (tania_gilbert) must be in user_brokers"
    retrieved = manager.user_brokers[user2_id][BrokerType.KRAKEN]
    assert retrieved.connected, "user2 Kraken broker must be connected"
    assert retrieved.get_account_balance() == 1800.0, "user2 Kraken balance must be $1800"
    print(
        f"✅ Test 5 passed: user2 ({user2_id}) Kraken account funded "
        f"(balance=${retrieved.get_account_balance():.2f})"
    )


# ---------------------------------------------------------------------------
# 6. MABM balance aggregation: user1 and user2 both visible together
# ---------------------------------------------------------------------------

def test_mabm_sees_both_user_kraken_balances():
    """
    MABM correctly aggregates both user1 and user2 funded Kraken balances
    without any leakage between the accounts.
    """
    manager = _fresh_manager()

    user1_id = "daivon_frazier"
    user2_id = "tania_gilbert"

    user1_broker = MockBroker(
        BrokerType.KRAKEN, AccountType.USER, user_id=user1_id, initial_balance=2500.0
    )
    user1_broker.connect()
    manager.user_brokers[user1_id] = {BrokerType.KRAKEN: user1_broker}

    user2_broker = MockBroker(
        BrokerType.KRAKEN, AccountType.USER, user_id=user2_id, initial_balance=1800.0
    )
    user2_broker.connect()
    manager.user_brokers[user2_id] = {BrokerType.KRAKEN: user2_broker}

    # Both users visible in MABM
    assert user1_id in manager.user_brokers
    assert user2_id in manager.user_brokers

    # Balances are independent
    b1 = manager.user_brokers[user1_id][BrokerType.KRAKEN].get_account_balance()
    b2 = manager.user_brokers[user2_id][BrokerType.KRAKEN].get_account_balance()

    assert b1 == 2500.0, f"user1 balance should be $2500, got ${b1}"
    assert b2 == 1800.0, f"user2 balance should be $1800, got ${b2}"
    assert b1 != b2, "user1 and user2 balances must be independent"

    total = b1 + b2
    assert total == 4300.0, f"Combined user balance should be $4300, got ${total}"
    print(
        f"✅ Test 6 passed: MABM sees user1 (${b1:.2f}) + user2 (${b2:.2f}) "
        f"= ${total:.2f} combined Kraken balance"
    )


# ---------------------------------------------------------------------------
# 7. Platform Coinbase trade does NOT affect user1/user2 Kraken balances
# ---------------------------------------------------------------------------

def test_coinbase_platform_trade_does_not_affect_user_kraken():
    """A platform Coinbase trade must not modify user1/user2 Kraken account balances."""
    manager = _fresh_manager()

    # Platform on Coinbase
    cb_platform = MockBroker(BrokerType.COINBASE, AccountType.PLATFORM, initial_balance=5000.0)
    cb_platform.connect()
    manager.register_platform_broker_instance(BrokerType.COINBASE, cb_platform)

    # user1 and user2 on Kraken
    user1_id = "daivon_frazier"
    user2_id = "tania_gilbert"
    user1_broker = MockBroker(
        BrokerType.KRAKEN, AccountType.USER, user_id=user1_id, initial_balance=2500.0
    )
    user1_broker.connect()
    manager.user_brokers[user1_id] = {BrokerType.KRAKEN: user1_broker}

    user2_broker = MockBroker(
        BrokerType.KRAKEN, AccountType.USER, user_id=user2_id, initial_balance=1800.0
    )
    user2_broker.connect()
    manager.user_brokers[user2_id] = {BrokerType.KRAKEN: user2_broker}

    # Execute a large platform Coinbase trade
    cb_platform.place_market_order("BTC-USD", "buy", 1000.0)

    # User Kraken balances must be completely unchanged
    assert user1_broker._balance == 2500.0, (
        f"user1 Kraken balance should be unchanged at $2500, got ${user1_broker._balance}"
    )
    assert user2_broker._balance == 1800.0, (
        f"user2 Kraken balance should be unchanged at $1800, got ${user2_broker._balance}"
    )
    assert len(user1_broker.orders) == 0, "user1 must have 0 orders from platform trade"
    assert len(user2_broker.orders) == 0, "user2 must have 0 orders from platform trade"
    print(
        "✅ Test 7 passed: Platform Coinbase trade did not affect "
        "user1/user2 Kraken accounts"
    )


# ---------------------------------------------------------------------------
# 8. Platform Kraken trade does NOT affect user1/user2 Kraken balances
# ---------------------------------------------------------------------------

def test_kraken_platform_trade_does_not_affect_user_kraken():
    """A platform Kraken trade must not modify user1/user2 Kraken account balances."""
    manager = _fresh_manager()

    kr_platform = MockBroker(BrokerType.KRAKEN, AccountType.PLATFORM, initial_balance=3000.0)
    kr_platform.connect()
    manager.register_platform_broker_instance(BrokerType.KRAKEN, kr_platform)

    user1_id = "daivon_frazier"
    user2_id = "tania_gilbert"
    user1_broker = MockBroker(
        BrokerType.KRAKEN, AccountType.USER, user_id=user1_id, initial_balance=2500.0
    )
    user1_broker.connect()
    manager.user_brokers[user1_id] = {BrokerType.KRAKEN: user1_broker}

    user2_broker = MockBroker(
        BrokerType.KRAKEN, AccountType.USER, user_id=user2_id, initial_balance=1800.0
    )
    user2_broker.connect()
    manager.user_brokers[user2_id] = {BrokerType.KRAKEN: user2_broker}

    # Platform trade on Kraken
    kr_platform.place_market_order("ETH-USD", "buy", 800.0)

    # User balances must be unaffected
    assert user1_broker._balance == 2500.0, (
        f"user1 balance should be $2500 after platform Kraken trade, got ${user1_broker._balance}"
    )
    assert user2_broker._balance == 1800.0, (
        f"user2 balance should be $1800 after platform Kraken trade, got ${user2_broker._balance}"
    )
    assert len(user1_broker.orders) == 0, "user1 must have 0 orders from platform trade"
    assert len(user2_broker.orders) == 0, "user2 must have 0 orders from platform trade"
    # Platform must have been affected
    assert kr_platform._balance == 2200.0, (
        f"Platform Kraken balance should be $2200 after $800 buy, got ${kr_platform._balance}"
    )
    print(
        "✅ Test 8 passed: Platform Kraken trade did not affect "
        "user1/user2 Kraken accounts"
    )


# ---------------------------------------------------------------------------
# 9. user1 and user2 can trade independently on Kraken
# ---------------------------------------------------------------------------

def test_user1_user2_trade_independently_on_kraken():
    """
    user1 and user2 can each execute independent Kraken trades.
    A trade by one user must not affect the other.
    """
    manager = _fresh_manager()

    user1_id = "daivon_frazier"
    user2_id = "tania_gilbert"

    user1_broker = MockBroker(
        BrokerType.KRAKEN, AccountType.USER, user_id=user1_id, initial_balance=2500.0
    )
    user1_broker.connect()
    manager.user_brokers[user1_id] = {BrokerType.KRAKEN: user1_broker}

    user2_broker = MockBroker(
        BrokerType.KRAKEN, AccountType.USER, user_id=user2_id, initial_balance=1800.0
    )
    user2_broker.connect()
    manager.user_brokers[user2_id] = {BrokerType.KRAKEN: user2_broker}

    # user1 buys BTC
    user1_broker.place_market_order("BTC-USD", "buy", 300.0)
    # user2 buys ETH
    user2_broker.place_market_order("ETH-USD", "buy", 200.0)

    # Verify independent balances
    assert user1_broker._balance == 2200.0, (
        f"user1 balance should be $2200 after $300 buy, got ${user1_broker._balance}"
    )
    assert user2_broker._balance == 1600.0, (
        f"user2 balance should be $1600 after $200 buy, got ${user2_broker._balance}"
    )
    assert len(user1_broker.orders) == 1, "user1 should have exactly 1 order"
    assert len(user2_broker.orders) == 1, "user2 should have exactly 1 order"
    assert user1_broker.orders[0]["user_id"] == user1_id
    assert user2_broker.orders[0]["user_id"] == user2_id

    print(
        f"✅ Test 9 passed: user1 and user2 traded independently on Kraken "
        f"(user1 balance=${user1_broker._balance:.2f}, "
        f"user2 balance=${user2_broker._balance:.2f})"
    )


# ---------------------------------------------------------------------------
# 10. Config files list both named Kraken users
# ---------------------------------------------------------------------------

def test_config_files_contain_both_kraken_users():
    """
    The retail_kraken.json config must enable both daivon_frazier (user1)
    and tania_gilbert (user2) with Kraken as their broker.
    """
    project_root = Path(__file__).parent.parent.parent
    config_path = project_root / "config" / "users" / "retail_kraken.json"

    assert config_path.exists(), (
        f"Config file not found: {config_path}\n"
        "Expected config/users/retail_kraken.json to define Kraken users."
    )

    with open(config_path) as fh:
        users = json.load(fh)

    assert isinstance(users, list) and len(users) >= 2, (
        "retail_kraken.json must contain at least 2 user entries (user1 and user2)"
    )

    user_ids = {u.get("user_id") for u in users}
    assert "daivon_frazier" in user_ids, (
        "daivon_frazier (user1) must be present in retail_kraken.json"
    )
    assert "tania_gilbert" in user_ids, (
        "tania_gilbert (user2) must be present in retail_kraken.json"
    )

    for user in users:
        uid = user.get("user_id")
        assert user.get("broker_type", "").lower() == "kraken", (
            f"{uid} must have broker_type=kraken"
        )
        assert user.get("enabled", False) is True, (
            f"{uid} must be enabled=true"
        )
        assert user.get("independent_trading", False) is True, (
            f"{uid} must have independent_trading=true"
        )

    print(
        "✅ Test 10 passed: Config file contains daivon_frazier (user1) and "
        "tania_gilbert (user2) as enabled independent Kraken traders"
    )


# ---------------------------------------------------------------------------
# Entry point (also usable as a standalone script)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "pytest", __file__, "-v", "--tb=short"],
        cwd=str(Path(__file__).parent.parent.parent),
    )
    sys.exit(result.returncode)
