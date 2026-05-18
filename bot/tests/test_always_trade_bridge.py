import sys
import unittest

sys.path.insert(0, ".")

from bot.trading_strategy import TradingStrategy, FORCED_ENTRY_FALLBACK_CYCLES


class AlwaysTradeBridgeTests(unittest.TestCase):
    def test_activate_local_force_entry_path_arms_first_trade_force(self):
        strategy = TradingStrategy.__new__(TradingStrategy)
        strategy._first_trade_executed = False
        strategy._first_trade_force_active = False
        strategy._zero_signal_streak = 0

        strategy._activate_local_force_entry_path()

        self.assertTrue(strategy._first_trade_force_active)
        self.assertGreaterEqual(
            strategy._zero_signal_streak,
            FORCED_ENTRY_FALLBACK_CYCLES,
        )

    def test_activate_local_force_entry_path_preserves_post_trade_drought_behavior(self):
        strategy = TradingStrategy.__new__(TradingStrategy)
        strategy._first_trade_executed = True
        strategy._first_trade_force_active = False
        strategy._zero_signal_streak = 1

        strategy._activate_local_force_entry_path()

        self.assertFalse(strategy._first_trade_force_active)
        self.assertGreaterEqual(
            strategy._zero_signal_streak,
            FORCED_ENTRY_FALLBACK_CYCLES,
        )


if __name__ == "__main__":
    unittest.main()
