"""
Broker Strategy Selector

Automatically selects the appropriate trading strategy configuration
based on the broker being used. Each broker has unique characteristics:

- Coinbase: High fees (1.4%), buy-focused, crypto only
- Kraken: Low fees (0.36%), bidirectional, crypto + futures/options
- Binance: Very low fees (0.28%), bidirectional, high-frequency scalp
- Alpaca: Stock trading, different dynamics
- Others: Conservative defaults

This module provides the routing logic to apply broker-specific strategies.
It integrates with BROKER_PROFILES from broker_strategy_router to ensure
every selection is consistent with the fee-aware trade-filtering layer.
"""

import logging
from typing import Optional, Dict, Any

logger = logging.getLogger("nija.strategy_selector")

try:
    from .coinbase_config import COINBASE_CONFIG, CoinbaseConfig
    from .kraken_config import KRAKEN_CONFIG, KrakenConfig
    from .binance_config import BINANCE_CONFIG, BinanceConfig
    from .default_config import DEFAULT_CONFIG, DefaultConfig
except ImportError:
    # Fallback if not yet available
    COINBASE_CONFIG = None
    KRAKEN_CONFIG = None
    BINANCE_CONFIG = None
    DEFAULT_CONFIG = None
    CoinbaseConfig = None
    KrakenConfig = None
    BinanceConfig = None
    DefaultConfig = None

# Pull BROKER_PROFILES so callers can inspect per-broker characteristics
# without importing broker_strategy_router directly.
try:
    from bot.broker_strategy_router import BROKER_PROFILES
except ImportError:
    try:
        from broker_strategy_router import BROKER_PROFILES
    except ImportError:
        BROKER_PROFILES = {}


class BrokerStrategySelector:
    """
    Select and manage broker-specific trading strategies.

    This class acts as a router that:
    1. Identifies the broker being used
    2. Loads the appropriate configuration (driven by BROKER_PROFILES)
    3. Provides broker-specific trading logic
    """

    def __init__(self):
        """Initialize strategy selector"""
        self.configs = {
            'coinbase': COINBASE_CONFIG,
            'kraken': KRAKEN_CONFIG,
            'binance': BINANCE_CONFIG,
            'default': DEFAULT_CONFIG,
        }
        self.current_broker = None
        self.current_config = None

    def select_strategy(self, broker_type: str):
        """
        Select trading strategy for specified broker.

        Args:
            broker_type: Broker type string ('coinbase', 'kraken', 'binance', etc.)

        Returns:
            Broker configuration object
        """
        broker_type_lower = broker_type.lower() if broker_type else 'default'

        # Get config for broker
        config = self.configs.get(broker_type_lower, self.configs.get('default'))

        if config is None:
            logger.warning(f"No configuration available for {broker_type}, using hardcoded defaults")
            # Build conservative defaults from BROKER_PROFILES if available
            profile = BROKER_PROFILES.get(broker_type_lower, BROKER_PROFILES.get('default', {}))
            round_trip = profile.get('fee', 0.014)
            min_move = profile.get('min_move', 0.015)
            return {
                'broker_name': broker_type_lower,
                'round_trip_cost': round_trip,
                'profit_targets': [(min_move * 1.5, f"{min_move * 150:.1f}%"),
                                   (min_move * 2.5, f"{min_move * 250:.1f}%"),
                                   (min_move * 4.0, f"{min_move * 400:.1f}%")],
                'stop_loss': -(min_move * 0.8),
                'max_hold_hours': 12.0,
                'min_move': min_move,
                'style': profile.get('style', 'swing'),
                'speed': profile.get('speed', 'slow'),
            }

        self.current_broker = broker_type_lower
        self.current_config = config

        profile = BROKER_PROFILES.get(broker_type_lower, {})
        logger.info(f"📊 Selected {config.broker_display_name} strategy")
        logger.info(f"   Fees: {config.round_trip_cost*100:.2f}% round-trip")
        logger.info(f"   Strategy: {'BIDIRECTIONAL' if config.bidirectional else 'BUY-FOCUSED'}")
        logger.info(f"   Profit targets: {', '.join([f'{t[0]*100:.1f}%' for t in config.profit_targets])}")
        if profile:
            logger.info(
                f"   Profile: style={profile.get('style','?')}  "
                f"min_move={profile.get('min_move', 0)*100:.1f}%  "
                f"speed={profile.get('speed','?')}"
            )

        return config

    def get_current_config(self):
        """Get currently active configuration"""
        return self.current_config

    def should_enter_long(self, broker_type: str, rsi: float, price: float,
                          ema9: float, ema21: float) -> bool:
        """
        Determine if should enter LONG position.

        Args:
            broker_type: Broker type
            rsi: RSI value
            price: Current price
            ema9: EMA9 value
            ema21: EMA21 value

        Returns:
            True if should enter long
        """
        config = self.configs.get(broker_type.lower(), self.configs.get('default'))

        if config and hasattr(config, 'should_buy'):
            return config.should_buy(rsi, price, ema9, ema21)

        # Fallback logic
        return 30 <= rsi <= 50 and price > ema9 and price > ema21

    def should_enter_short(self, broker_type: str, rsi: float, price: float,
                           ema9: float, ema21: float) -> bool:
        """
        Determine if should enter SHORT position.

        Args:
            broker_type: Broker type
            rsi: RSI value
            price: Current price
            ema9: EMA9 value
            ema21: EMA21 value

        Returns:
            True if should enter short (only on brokers where it's profitable)
        """
        config = self.configs.get(broker_type.lower(), self.configs.get('default'))

        # Only allow shorting on bidirectional brokers (Kraken)
        if config and config.bidirectional and hasattr(config, 'should_short'):
            return config.should_short(rsi, price, ema9, ema21)

        # Don't short on high-fee exchanges (Coinbase)
        return False

    def should_exit_position(self, broker_type: str, rsi: float, price: float,
                            ema9: float, ema21: float) -> bool:
        """
        Determine if should exit current position.

        Args:
            broker_type: Broker type
            rsi: RSI value
            price: Current price
            ema9: EMA9 value
            ema21: EMA21 value

        Returns:
            True if should exit
        """
        config = self.configs.get(broker_type.lower(), self.configs.get('default'))

        if config and hasattr(config, 'should_sell'):
            return config.should_sell(rsi, price, ema9, ema21)

        # Fallback logic
        return rsi > 60 or price < ema9

    def calculate_position_size(self, broker_type: str, account_balance: float,
                               signal_strength: float = 1.0) -> float:
        """
        Calculate position size for broker.

        Args:
            broker_type: Broker type
            account_balance: Available balance
            signal_strength: Signal quality (0.0 to 1.0)

        Returns:
            Position size in USD
        """
        config = self.configs.get(broker_type.lower(), self.configs.get('default'))

        if config and hasattr(config, 'calculate_position_size'):
            return config.calculate_position_size(account_balance, signal_strength)

        # Fallback
        base_size = account_balance * 0.20  # 20% default
        return max(base_size * signal_strength, 10.0)

    def get_profit_targets(self, broker_type: str) -> list:
        """Get profit targets for broker"""
        config = self.configs.get(broker_type.lower(), self.configs.get('default'))

        if config and hasattr(config, 'profit_targets'):
            return config.profit_targets

        # Fallback
        return [(0.015, "1.5%"), (0.012, "1.2%"), (0.010, "1.0%")]

    def get_stop_loss(self, broker_type: str) -> float:
        """Get stop loss percentage for broker"""
        config = self.configs.get(broker_type.lower(), self.configs.get('default'))

        if config and hasattr(config, 'stop_loss'):
            return config.stop_loss

        # Fallback
        return -0.010  # -1.0%

    def get_max_hold_hours(self, broker_type: str) -> float:
        """Get maximum hold time for broker"""
        config = self.configs.get(broker_type.lower(), self.configs.get('default'))

        if config and hasattr(config, 'max_hold_hours'):
            return config.max_hold_hours

        # Fallback
        return 12.0

    def print_strategy_comparison(self):
        """Print comparison of all broker strategies"""
        print("\n" + "="*80)
        print("BROKER STRATEGY COMPARISON".center(80))
        print("="*80)

        coinbase = self.configs.get('coinbase')
        kraken = self.configs.get('kraken')

        if coinbase:
            print("\n🔵 COINBASE (High-Fee Exchange)")
            print("-" * 80)
            print(coinbase.get_config_summary())

        if kraken:
            print("\n🟣 KRAKEN (Low-Fee Exchange)")
            print("-" * 80)
            print(kraken.get_config_summary())

        # Calculate comparisons from actual config values
        if coinbase and kraken:
            fee_ratio = coinbase.round_trip_cost / kraken.round_trip_cost
            hold_ratio = kraken.max_hold_hours / coinbase.max_hold_hours
            min_pos_ratio = coinbase.min_position_usd / kraken.min_position_usd

            print("\n" + "="*80)
            print("KEY DIFFERENCES:".center(80))
            print("="*80)
            print(f"""
Coinbase vs Kraken:
  Fees:         {coinbase.round_trip_cost*100:.2f}% vs {kraken.round_trip_cost*100:.2f}% (Kraken is {fee_ratio:.1f}x cheaper!)
  Strategy:     {'Buy-only' if not coinbase.bidirectional else 'Bidirectional'} vs {'Bidirectional' if kraken.bidirectional else 'Buy-only'}
  Profit Target: {coinbase.profit_targets[0][0]*100:.1f}% vs {kraken.profit_targets[0][0]*100:.1f}%
  Stop Loss:    {coinbase.stop_loss*100:.1f}% vs {kraken.stop_loss*100:.1f}%
  Max Hold:     {coinbase.max_hold_hours:.0f}h vs {kraken.max_hold_hours:.0f}h (Kraken {hold_ratio:.1f}x longer)
  Min Position: ${coinbase.min_position_usd:.0f} vs ${kraken.min_position_usd:.0f} (Kraken {min_pos_ratio:.1f}x smaller)
  Short Selling: {'Unprofitable' if not coinbase.sell_preferred else 'Profitable'} vs {'PROFITABLE' if kraken.sell_preferred else 'Unprofitable'}

CONCLUSION: Kraken is superior for:
  ✅ More trading opportunities (bidirectional)
  ✅ Lower fees = higher profitability
  ✅ Smaller positions viable
  ✅ Longer hold times possible
  ✅ More trades per day allowed
  ✅ Futures and options support
""")


# Create global selector instance
STRATEGY_SELECTOR = BrokerStrategySelector()

# Convenience functions
def get_strategy_for_broker(broker_type: str):
    """Get strategy configuration for broker"""
    return STRATEGY_SELECTOR.select_strategy(broker_type)


if __name__ == "__main__":
    # Print comparison when run directly
    STRATEGY_SELECTOR.print_strategy_comparison()
