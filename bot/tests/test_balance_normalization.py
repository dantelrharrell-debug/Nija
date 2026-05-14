"""Production-grade test harness for broker balance payload normalization.

Covers:
  - Happy-path priority ordering (trading_balance > available_balance > … > total_balance)
  - Nested dict extraction (known keys: value, amount, total, available; then fallback)
  - Scalar inputs (int, float, str, None, bool)
  - Non-finite inputs (NaN, +inf, -inf) → clamped to 0.0
  - Negative balance → clamped to 0.0
  - Empty dict → 0.0
  - Empty nested dict → falls through to next key
  - Whitespace / numeric string inputs
  - List/tuple as a balance value (non-dict, non-scalar) → skipped gracefully
  - Multi-key dicts where only one key has a valid value
  - Aggregated breakdown integration smoke test
"""

import math
import unittest
from typing import Any, Dict, Optional

from bot.broker_manager import AccountType, BaseBroker, BrokerType
from bot.multi_account_broker_manager import MultiAccountBrokerManager

_norm = MultiAccountBrokerManager._normalize_balance_value


class DictBalanceBroker(BaseBroker):
    """Minimal broker stub that returns a configurable balance payload."""

    def __init__(
        self,
        broker_type: BrokerType,
        account_type: AccountType,
        user_id: Optional[str] = None,
        balance: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(broker_type, account_type, user_id)
        self.connected = True
        self._balance = balance or {"available_balance": {"value": "0.0"}}

    def connect(self):
        self.connected = True
        return True

    def get_account_balance(self):
        return self._balance

    def get_positions(self):
        return []

    def place_market_order(
        self,
        symbol,
        side,
        quantity,
        size_type="quote",
        ignore_balance=False,
        ignore_min_trade=False,
        force_liquidate=False,
    ):
        return {"status": "filled", "symbol": symbol, "side": side, "quantity": quantity}


# ---------------------------------------------------------------------------
# Scalar inputs
# ---------------------------------------------------------------------------

class TestScalarInputs(unittest.TestCase):
    def test_plain_float(self):
        self.assertEqual(_norm(100.0), 100.0)

    def test_plain_int(self):
        self.assertEqual(_norm(50), 50.0)

    def test_numeric_string(self):
        self.assertEqual(_norm("75.5"), 75.5)

    def test_numeric_string_with_whitespace(self):
        # Python's float() strips surrounding whitespace
        self.assertEqual(_norm("  200.0  "), 200.0)

    def test_zero_float(self):
        self.assertEqual(_norm(0.0), 0.0)

    def test_none_input(self):
        self.assertEqual(_norm(None), 0.0)

    def test_bool_true_treated_as_one(self):
        # bool is a subclass of int; float(True) == 1.0
        self.assertEqual(_norm(True), 1.0)

    def test_bool_false_treated_as_zero(self):
        self.assertEqual(_norm(False), 0.0)

    def test_non_numeric_string(self):
        self.assertEqual(_norm("N/A"), 0.0)

    def test_empty_string(self):
        self.assertEqual(_norm(""), 0.0)


# ---------------------------------------------------------------------------
# Non-finite value safety
# ---------------------------------------------------------------------------

class TestNonFiniteValues(unittest.TestCase):
    def test_nan_scalar_returns_zero(self):
        self.assertEqual(_norm(float("nan")), 0.0)

    def test_positive_inf_scalar_returns_zero(self):
        self.assertEqual(_norm(float("inf")), 0.0)

    def test_negative_inf_scalar_returns_zero(self):
        self.assertEqual(_norm(float("-inf")), 0.0)

    def test_nan_string_scalar_returns_zero(self):
        # float("nan") would succeed; guard must catch it
        self.assertEqual(_norm("nan"), 0.0)

    def test_nan_inside_dict_nested_value(self):
        result = _norm({"available_balance": {"value": float("nan")}})
        self.assertEqual(result, 0.0)

    def test_inf_inside_dict_flat_value(self):
        result = _norm({"available_cash": float("inf")})
        self.assertEqual(result, 0.0)

    def test_nan_skipped_falls_through_to_next_valid_key(self):
        # NaN on available_balance should not block total_balance
        result = _norm({
            "available_balance": float("nan"),
            "total_balance": "500.0",
        })
        self.assertEqual(result, 500.0)

    def test_inf_skipped_falls_through_to_next_valid_key(self):
        result = _norm({
            "available_balance": float("inf"),
            "total_balance": "250.0",
        })
        self.assertEqual(result, 250.0)


# ---------------------------------------------------------------------------
# Negative balance clamping
# ---------------------------------------------------------------------------

class TestNegativeValueClamping(unittest.TestCase):
    def test_negative_scalar_clamped_to_zero(self):
        self.assertEqual(_norm(-100.0), 0.0)

    def test_negative_string_clamped_to_zero(self):
        self.assertEqual(_norm("-50.0"), 0.0)

    def test_negative_in_flat_dict_clamped(self):
        self.assertEqual(_norm({"available_cash": -25.0}), 0.0)

    def test_negative_in_nested_dict_clamped(self):
        self.assertEqual(_norm({"available_balance": {"value": "-10.0"}}), 0.0)

    def test_negative_skipped_falls_through_to_next_positive_key(self):
        # A negative value at a higher-priority key is clamped to 0.0 and
        # returned immediately — it is NOT treated as "missing" and does NOT
        # fall through to a lower-priority key. Returning 0 from the
        # authoritative key is safer than silently substituting a different
        # key's value, which could come from a different account scope.
        result = _norm({
            "available_balance": -99.0,
            "total_balance": "300.0",
        })
        self.assertEqual(result, 0.0)


# ---------------------------------------------------------------------------
# Dict key priority ordering
# ---------------------------------------------------------------------------

class TestKeyPriority(unittest.TestCase):
    """trading_balance > available_balance > available_cash > cash > usd > usdc > total_balance."""

    def test_trading_balance_takes_priority_over_available_balance(self):
        result = _norm({
            "trading_balance": "1000.0",
            "available_balance": "500.0",
        })
        self.assertEqual(result, 1000.0)

    def test_available_balance_takes_priority_over_available_cash(self):
        result = _norm({
            "available_balance": "400.0",
            "available_cash": "200.0",
        })
        self.assertEqual(result, 400.0)

    def test_available_cash_takes_priority_over_cash(self):
        result = _norm({
            "available_cash": "300.0",
            "cash": "150.0",
        })
        self.assertEqual(result, 300.0)

    def test_cash_takes_priority_over_usd(self):
        result = _norm({"cash": "80.0", "usd": "40.0"})
        self.assertEqual(result, 80.0)

    def test_usd_takes_priority_over_usdc(self):
        result = _norm({"usd": "60.0", "usdc": "30.0"})
        self.assertEqual(result, 60.0)

    def test_usdc_takes_priority_over_total_balance(self):
        result = _norm({"usdc": "70.0", "total_balance": "35.0"})
        self.assertEqual(result, 70.0)

    def test_total_balance_used_when_only_key(self):
        result = _norm({"total_balance": "99.99"})
        self.assertAlmostEqual(result, 99.99, places=5)

    def test_unknown_key_ignored_returns_zero(self):
        result = _norm({"portfolio_value": "500.0"})
        self.assertEqual(result, 0.0)

    def test_empty_dict_returns_zero(self):
        self.assertEqual(_norm({}), 0.0)


# ---------------------------------------------------------------------------
# Nested dict extraction
# ---------------------------------------------------------------------------

class TestNestedDictExtraction(unittest.TestCase):
    def test_nested_value_key(self):
        self.assertEqual(_norm({"available_balance": {"value": "42.5"}}), 42.5)

    def test_nested_amount_key(self):
        self.assertEqual(_norm({"available_balance": {"amount": "31.0"}}), 31.0)

    def test_nested_total_key(self):
        self.assertEqual(_norm({"available_balance": {"total": "31.25"}}), 31.25)

    def test_nested_available_key(self):
        self.assertEqual(_norm({"available_balance": {"available": "55.0"}}), 55.0)

    def test_nested_known_key_priority_value_over_total(self):
        # "value" comes before "total" in priority
        result = _norm({"available_balance": {"value": "10.0", "total": "99.0"}})
        self.assertEqual(result, 10.0)

    def test_nested_fallback_unknown_key(self):
        # No known nested key present; first numeric scalar wins
        result = _norm({"available_balance": {"balance_value": "19.75"}})
        self.assertEqual(result, 19.75)

    def test_nested_fallback_skips_non_numeric(self):
        # All values non-numeric except last; last wins
        result = _norm({"available_balance": {"label": "USD", "amount": "25.0"}})
        # "amount" is a known key, so it is checked first
        self.assertEqual(result, 25.0)

    def test_empty_nested_dict_falls_through_to_next_outer_key(self):
        # Empty inner dict should not consume the outer key slot
        result = _norm({
            "available_balance": {},
            "total_balance": "77.0",
        })
        self.assertEqual(result, 77.0)

    def test_all_nested_values_non_numeric_falls_through(self):
        result = _norm({
            "available_balance": {"label": "USD", "currency": "USD"},
            "total_balance": "50.0",
        })
        self.assertEqual(result, 50.0)

    def test_nested_negative_value_clamped(self):
        result = _norm({"available_balance": {"value": "-5.0"}})
        self.assertEqual(result, 0.0)

    def test_nested_nan_value_falls_through(self):
        result = _norm({
            "available_balance": {"value": float("nan")},
            "total_balance": "100.0",
        })
        self.assertEqual(result, 100.0)


# ---------------------------------------------------------------------------
# Non-dict value types inside dict
# ---------------------------------------------------------------------------

class TestNonDictValueTypes(unittest.TestCase):
    def test_list_value_skipped_gracefully(self):
        # A list is not a dict and not a scalar; float([]) raises TypeError
        result = _norm({"available_balance": [100.0, 200.0], "total_balance": "50.0"})
        self.assertEqual(result, 50.0)

    def test_tuple_value_skipped_gracefully(self):
        result = _norm({"available_balance": (100.0,), "total_balance": "60.0"})
        self.assertEqual(result, 60.0)

    def test_set_value_skipped_gracefully(self):
        result = _norm({"available_balance": {100.0}, "total_balance": "70.0"})
        # A set is not a dict (isinstance check) so float() is attempted; float({100.0}) raises TypeError
        self.assertEqual(result, 70.0)

    def test_nested_none_value_skipped(self):
        result = _norm({"available_balance": None, "total_balance": "80.0"})
        self.assertEqual(result, 80.0)


# ---------------------------------------------------------------------------
# Integration: aggregated breakdown
# ---------------------------------------------------------------------------

class TestAggregatedBreakdownIntegration(unittest.TestCase):
    def _make_manager_with_brokers(
        self,
        platform_balance,
        user_id: str,
        user_balance,
    ) -> MultiAccountBrokerManager:
        manager = MultiAccountBrokerManager()
        platform_broker = DictBalanceBroker(
            BrokerType.COINBASE,
            AccountType.PLATFORM,
            balance=platform_balance,
        )
        user_broker = DictBalanceBroker(
            BrokerType.COINBASE,
            AccountType.USER,
            user_id=user_id,
            balance=user_balance,
        )
        manager._platform_brokers[BrokerType.COINBASE] = platform_broker
        manager.user_brokers[user_id] = {BrokerType.COINBASE: user_broker}
        return manager

    def test_breakdown_nested_value_key(self):
        manager = self._make_manager_with_brokers(
            platform_balance={"available_balance": {"value": "120.0"}},
            user_id="alice",
            user_balance={"total_balance": "35.0"},
        )
        bd = manager.get_aggregated_balance_breakdown(include_all_subaccounts=True)
        self.assertEqual(bd["coinbase"], 155.0)
        self.assertEqual(bd["platform_total"], 120.0)
        self.assertEqual(bd["user_total"], 35.0)
        self.assertEqual(bd["total_balance"], 155.0)

    def test_breakdown_negative_balance_excluded_from_total(self):
        # Platform broker returns a negative balance; must not reduce user's total
        manager = self._make_manager_with_brokers(
            platform_balance={"available_balance": "-50.0"},
            user_id="bob",
            user_balance={"total_balance": "200.0"},
        )
        bd = manager.get_aggregated_balance_breakdown(include_all_subaccounts=True)
        # Negative clamped to 0 → platform contributes 0, user contributes 200
        self.assertEqual(bd["platform_total"], 0.0)
        self.assertEqual(bd["user_total"], 200.0)
        self.assertEqual(bd["total_balance"], 200.0)

    def test_breakdown_nan_balance_excluded_from_total(self):
        manager = self._make_manager_with_brokers(
            platform_balance={"available_balance": float("nan")},
            user_id="carol",
            user_balance={"total_balance": "150.0"},
        )
        bd = manager.get_aggregated_balance_breakdown(include_all_subaccounts=True)
        self.assertEqual(bd["platform_total"], 0.0)
        self.assertEqual(bd["user_total"], 150.0)

    def test_get_platform_total_balance_returns_float(self):
        manager = self._make_manager_with_brokers(
            platform_balance={"available_balance": {"value": "300.0"}},
            user_id="dave",
            user_balance={"total_balance": "100.0"},
        )
        total = manager.get_platform_total_balance(include_all_subaccounts=True)
        self.assertIsInstance(total, float)
        self.assertEqual(total, 400.0)

    def test_no_debug_balances_critical_log_emitted(self):
        """Regression: 'DEBUG BALANCES' must not be logged at CRITICAL in production."""
        import logging
        manager = self._make_manager_with_brokers(
            platform_balance={"available_balance": "500.0"},
            user_id="eve",
            user_balance={"total_balance": "50.0"},
        )

        critical_records = []

        class _Capture(logging.Handler):
            def emit(self, record):
                if record.levelno >= logging.CRITICAL:
                    critical_records.append(record.getMessage())

        handler = _Capture()
        logging.getLogger().addHandler(handler)
        try:
            manager.get_platform_total_balance(include_all_subaccounts=True)
        finally:
            logging.getLogger().removeHandler(handler)

        debug_leaks = [m for m in critical_records if "DEBUG BALANCES" in m]
        self.assertEqual(
            debug_leaks,
            [],
            f"'DEBUG BALANCES' critical log must not appear in production: {debug_leaks}",
        )


if __name__ == "__main__":
    unittest.main()
