import sys
import unittest

sys.path.insert(0, ".")

from bot.always_trade_mode import arm_trading_strategy_force_entry_path


class AlwaysTradeBridgeTests(unittest.TestCase):
    def test_activate_local_force_entry_path_arms_first_trade_force(self):
        strategy = type("StrategyStub", (), {})()
        strategy._first_trade_executed = False
        strategy._first_trade_force_active = False
        strategy._zero_signal_streak = 0

        arm_trading_strategy_force_entry_path(strategy, forced_entry_fallback_cycles=5)

        self.assertTrue(strategy._first_trade_force_active)
        self.assertGreaterEqual(
            strategy._zero_signal_streak,
            5,
        )

    def test_activate_local_force_entry_path_preserves_post_trade_drought_behavior(self):
        strategy = type("StrategyStub", (), {})()
        strategy._first_trade_executed = True
        strategy._first_trade_force_active = False
        strategy._zero_signal_streak = 1

        arm_trading_strategy_force_entry_path(strategy, forced_entry_fallback_cycles=5)

        self.assertFalse(strategy._first_trade_force_active)
        self.assertGreaterEqual(
            strategy._zero_signal_streak,
            5,
        )


if __name__ == "__main__":
    unittest.main()
