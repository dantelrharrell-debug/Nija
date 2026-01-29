"""
NIJA Apex Strategy v7.1 - Live Trading Integration
====================================================

This module shows how to integrate Apex Strategy v7.1 with the
existing NIJA trading bot infrastructure for live trading.
"""

import sys
import os
import time
import logging
from datetime import datetime

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from apex_strategy_v7 import ApexStrategyV7
from apex_config import EXECUTION
from broker_manager import BrokerManager, CoinbaseBroker, AlpacaBroker, BinanceBroker, KrakenBroker, OKXBroker
import pandas as pd

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger("nija.apex.live")


class ApexLiveTrader:
    """
    Live trading bot using Apex Strategy v7.1
    """

    def __init__(
        self,
        broker_manager: BrokerManager,
        trading_pairs: list,
        timeframe: str = '5m',
        enable_ai: bool = False
    ):
        """
        Initialize live trader

        Args:
            broker_manager: Configured broker manager
            trading_pairs: List of symbols to trade
            timeframe: Candle timeframe (default 5m)
            enable_ai: Enable AI momentum engine
        """
        self.broker_manager = broker_manager
        self.trading_pairs = trading_pairs
        self.timeframe = timeframe

        # Get account balance
        balance = self.broker_manager.get_total_balance()
        logger.info(f"Account balance: ${balance:,.2f}")

        # Initialize Apex strategy
        self.strategy = ApexStrategyV7(
            account_balance=balance,
            enable_ai=enable_ai
        )

        # Track open positions
        self.open_positions = {}

        logger.info(f"Apex Live Trader initialized")
        logger.info(f"Trading pairs: {', '.join(trading_pairs)}")
        logger.info(f"Timeframe: {timeframe}")

    def fetch_candles(self, symbol: str, count: int = None) -> pd.DataFrame:
        """
        Fetch candles for a symbol

        Args:
            symbol: Trading symbol
            count: Number of candles to fetch (default from config)

        Returns:
            DataFrame with OHLCV data
        """
        if count is None:
            count = EXECUTION['min_candles_required']

        broker = self.broker_manager.get_broker_for_symbol(symbol)

        if not broker:
            logger.error(f"No broker available for {symbol}")
            return None

        candles = broker.get_candles(symbol, self.timeframe, count)

        if not candles:
            logger.warning(f"No candle data for {symbol}")
            return None

        # Convert to DataFrame
        df = pd.DataFrame(candles)

        # Ensure we have required columns
        required_cols = ['open', 'high', 'low', 'close', 'volume']
        if not all(col in df.columns for col in required_cols):
            logger.error(f"Missing required columns for {symbol}")
            return None

        return df

    def scan_for_entries(self):
        """Scan all trading pairs for entry opportunities"""
        logger.info("Scanning for entry opportunities...")

        for symbol in self.trading_pairs:
            # Skip if we already have a position
            if symbol in self.open_positions:
                continue

            # Fetch candles
            df = self.fetch_candles(symbol)
            min_candles = EXECUTION['min_candles_required']
            if df is None or len(df) < min_candles:
                continue

            # Analyze entry opportunity
            analysis = self.strategy.analyze_entry_opportunity(df, symbol)

            if analysis['should_enter']:
                logger.info(f"✅ Entry signal: {symbol}")
                logger.info(f"   Side: {analysis['side']}")
                logger.info(f"   Entry: ${analysis['entry_price']:,.4f}")
                logger.info(f"   Stop: ${analysis['stop_loss']:,.4f}")
                logger.info(f"   Size: ${analysis['position_size_usd']:,.2f}")
                logger.info(f"   Trend: {analysis['trend_quality']}")

                # Execute entry
                self.execute_entry(symbol, analysis)
            else:
                logger.debug(f"No entry for {symbol}: {analysis['reason']}")

    def execute_entry(self, symbol: str, analysis: dict):
        """
        Execute entry order

        Args:
            symbol: Trading symbol
            analysis: Entry analysis from strategy
        """
        try:
            # Place order
            result = self.broker_manager.place_order(
                symbol=symbol,
                side='buy' if analysis['side'] == 'long' else 'sell',
                quantity=analysis['position_size_usd']
            )

            if result['status'] == 'filled' or result['status'] == 'submitted':
                # Track position
                self.open_positions[symbol] = {
                    'id': f"{symbol}_{int(time.time())}",
                    'symbol': symbol,
                    'side': analysis['side'],
                    'entry_price': analysis['entry_price'],
                    'stop_loss': analysis['stop_loss'],
                    'take_profit_levels': analysis['take_profit_levels'],
                    'size_usd': analysis['position_size_usd'],
                    'entry_time': datetime.now(),
                }

                logger.info(f"✅ Position opened: {symbol}")
            else:
                logger.error(f"❌ Order failed: {result.get('error', 'Unknown error')}")

        except Exception as e:
            logger.error(f"Error executing entry for {symbol}: {e}")

    def update_positions(self):
        """Update all open positions"""
        if not self.open_positions:
            return

        logger.info(f"Updating {len(self.open_positions)} open positions...")

        positions_to_close = []

        for symbol, position in self.open_positions.items():
            # Fetch current candles
            df = self.fetch_candles(symbol)
            if df is None:
                continue

            current_price = df['close'].iloc[-1]

            # PRIORITY 1: Check stepped profit exits (fee-aware gradual profit-taking)
            profit_exit = self._check_stepped_profit_exits(symbol, position, current_price)
            if profit_exit:
                logger.info(f"✅ Stepped profit exit for {symbol}: {profit_exit['reason']}")
                self.close_position(symbol, profit_exit['exit_pct'])

                # Update position size after partial exit
                if profit_exit['exit_pct'] < 1.0:
                    position['size'] *= (1.0 - profit_exit['exit_pct'])
                    position['remaining_pct'] = position.get('remaining_pct', 1.0) * (1.0 - profit_exit['exit_pct'])
                else:
                    positions_to_close.append(symbol)
                continue

            # Update position
            update_result = self.strategy.update_position(
                position['id'],
                df,
                position
            )

            if update_result['action'] == 'exit':
                # Close position
                logger.info(f"Exit signal for {symbol}: {update_result['reason']}")
                self.close_position(
                    symbol,
                    update_result['exit_percentage']
                )

                if update_result['exit_percentage'] >= 1.0:
                    positions_to_close.append(symbol)

            elif update_result['action'] == 'update_stop':
                # Update stop loss
                old_stop = position['stop_loss']
                new_stop = update_result['new_stop']

                if new_stop != old_stop:
                    position['stop_loss'] = new_stop
                    logger.info(f"Updated stop for {symbol}: "
                              f"${old_stop:,.4f} → ${new_stop:,.4f}")

        # Remove closed positions
        for symbol in positions_to_close:
            del self.open_positions[symbol]

    def _check_stepped_profit_exits(self, symbol: str, position: dict, current_price: float) -> dict:
        """
        Check if position should execute stepped profit-taking exits

        Fee-Aware Profitability Mode - Stepped exits adjusted for exchange fees

        Exit Schedule (assuming ~1.4% round-trip fees for Coinbase):
        - Exit 10% at 2.0% gross profit → ~0.6% NET profit after fees (PROFITABLE)
        - Exit 15% at 2.5% gross profit → ~1.1% NET profit after fees (PROFITABLE)
        - Exit 25% at 3.0% gross profit → ~1.6% NET profit after fees (PROFITABLE)
        - Exit 50% at 4.0% gross profit → ~2.6% NET profit after fees (PROFITABLE)

        This dramatically reduces average hold time while ensuring ALL exits are NET PROFITABLE.

        Args:
            symbol: Trading symbol
            position: Position dictionary
            current_price: Current market price

        Returns:
            Dictionary with exit details if triggered, None otherwise
        """
        entry_price = position.get('entry_price')
        side = position.get('side')

        if not entry_price or not side:
            return None

        # Calculate GROSS profit percentage (before fees)
        if side == 'long':
            gross_profit_pct = (current_price - entry_price) / entry_price
        else:  # short
            gross_profit_pct = (entry_price - current_price) / entry_price

        # Only take profits on winning positions
        if gross_profit_pct <= 0:
            return None

        # Default round-trip fee (Coinbase: ~0.6% entry + ~0.6% exit + ~0.2% spread = ~1.4%)
        DEFAULT_ROUND_TRIP_FEE = 0.014

        # FEE-AWARE profit thresholds (GROSS profit needed for NET profitability)
        # Each threshold ensures NET profit after round-trip fees
        exit_levels = [
            (0.020, 0.10, 'tp_exit_2.0pct'),   # Exit 10% at 2.0% gross → ~0.6% NET
            (0.025, 0.15, 'tp_exit_2.5pct'),   # Exit 15% at 2.5% gross → ~1.1% NET
            (0.030, 0.25, 'tp_exit_3.0pct'),   # Exit 25% at 3.0% gross → ~1.6% NET
            (0.040, 0.50, 'tp_exit_4.0pct'),   # Exit 50% at 4.0% gross → ~2.6% NET
        ]

        for gross_threshold, exit_pct, exit_flag in exit_levels:
            # Skip if already executed
            if position.get(exit_flag, False):
                continue

            # Check if GROSS profit target hit (net will be profitable)
            if gross_profit_pct >= gross_threshold:
                # Mark as executed
                position[exit_flag] = True

                # Calculate expected NET profit for this exit
                expected_net_pct = gross_threshold - DEFAULT_ROUND_TRIP_FEE

                logger.info(f"✅ FEE-AWARE profit exit triggered: {symbol} {side}")
                logger.info(f"  Gross profit: {gross_profit_pct*100:.2f}% ≥ {gross_threshold*100:.1f}% threshold")
                logger.info(f"  Est. fees: {DEFAULT_ROUND_TRIP_FEE*100:.1f}%")
                logger.info(f"  NET profit: ~{expected_net_pct*100:.1f}% (PROFITABLE)")
                logger.info(f"  Exiting: {exit_pct*100:.0f}% of position")

                remaining_pct = position.get('remaining_pct', 1.0) * (1.0 - exit_pct)
                logger.info(f"  Remaining: {remaining_pct*100:.0f}% for trailing stop")

                return {
                    'exit_pct': exit_pct,
                    'profit_level': f"{gross_threshold*100:.1f}%",
                    'gross_profit_pct': gross_profit_pct,
                    'net_profit_pct': expected_net_pct,
                    'reason': f"Stepped profit exit at {gross_threshold*100:.1f}% (NET: {expected_net_pct*100:.1f}%)"
                }

        return None

    def close_position(self, symbol: str, exit_percentage: float):
        """
        Close a position

        Args:
            symbol: Trading symbol
            exit_percentage: Percentage to close (1.0 = 100%)
        """
        if symbol not in self.open_positions:
            return

        position = self.open_positions[symbol]

        try:
            # Calculate exit size
            exit_size = position['size_usd'] * exit_percentage

            # Place order
            result = self.broker_manager.place_order(
                symbol=symbol,
                side='sell' if position['side'] == 'long' else 'buy',
                quantity=exit_size
            )

            if result['status'] == 'filled' or result['status'] == 'submitted':
                logger.info(f"✅ Closed {exit_percentage*100:.0f}% of {symbol} position")
            else:
                logger.error(f"❌ Close order failed: {result.get('error', 'Unknown error')}")

        except Exception as e:
            logger.error(f"Error closing position for {symbol}: {e}")

    def run(self, scan_interval: int = 300):
        """
        Run the trading bot

        Args:
            scan_interval: Seconds between scans (default 300 = 5 minutes)
        """
        logger.info("="*60)
        logger.info("APEX LIVE TRADER STARTED")
        logger.info("="*60)

        try:
            while True:
                # Update balance
                balance = self.broker_manager.get_total_balance()
                self.strategy.update_balance(balance)

                # Update existing positions
                self.update_positions()

                # Scan for new entries
                self.scan_for_entries()

                # Log status
                logger.info(f"Status: Balance=${balance:,.2f}, "
                          f"Positions={len(self.open_positions)}")

                # Wait for next cycle
                logger.info(f"Waiting {scan_interval}s until next scan...")
                time.sleep(scan_interval)

        except KeyboardInterrupt:
            logger.info("\n⚠️ Shutting down gracefully...")
            logger.info(f"Open positions: {len(self.open_positions)}")
            if self.open_positions:
                logger.warning("⚠️ You have open positions!")
                for symbol, pos in self.open_positions.items():
                    logger.warning(f"  - {symbol}: {pos['side']} @ ${pos['entry_price']:,.4f}")
        except Exception as e:
            logger.error(f"Fatal error: {e}")
            raise


def main():
    """
    Main entry point for live trading

    This is an example. You would customize this for your needs.
    """
    print("\n" + "="*60)
    print("NIJA APEX STRATEGY v7.1 - LIVE TRADING")
    print("="*60 + "\n")

    # Initialize broker manager
    broker_manager = BrokerManager()

    # Add Coinbase (primary for crypto)
    coinbase = CoinbaseBroker()
    if coinbase.connect():
        broker_manager.add_broker(coinbase)

    # Optional: Add Binance for crypto
    # binance = BinanceBroker()
    # if binance.connect():
    #     broker_manager.add_broker(binance)

    # Optional: Add Kraken Pro for crypto
    # kraken = KrakenBroker()
    # if kraken.connect():
    #     broker_manager.add_broker(kraken)

    # Optional: Add OKX for crypto
    # okx = OKXBroker()
    # if okx.connect():
    #     broker_manager.add_broker(okx)

    # Optional: Add Alpaca for stocks
    # alpaca = AlpacaBroker()
    # if alpaca.connect():
    #     broker_manager.add_broker(alpaca)

    # Check if we have any connected brokers
    connected = broker_manager.get_connected_brokers()
    if not connected:
        print("❌ No brokers connected. Please configure your API credentials.")
        print("\nFor Coinbase, set:")
        print("  export COINBASE_API_KEY='your_key'")
        print("  export COINBASE_API_SECRET='your_secret'")
        return

    print(f"✅ Connected brokers: {', '.join(connected)}\n")

    # Define trading pairs
    trading_pairs = ['BTC-USD', 'ETH-USD', 'SOL-USD']

    # Initialize live trader
    trader = ApexLiveTrader(
        broker_manager=broker_manager,
        trading_pairs=trading_pairs,
        timeframe='5m',
        enable_ai=False  # Set to True if AI model available
    )

    # Run the bot
    trader.run(scan_interval=300)  # Scan every 5 minutes


if __name__ == "__main__":
    # NOTE: This is just an example.
    # In production, you would:
    # 1. Test thoroughly in paper mode first
    # 2. Start with small position sizes
    # 3. Monitor continuously
    # 4. Have proper error handling and alerts

    print("\n⚠️  WARNING: This will trade with REAL MONEY!")
    print("Make sure you:")
    print("  1. Have tested in paper/backtest mode")
    print("  2. Understand the strategy")
    print("  3. Are comfortable with the risks")
    print("  4. Have proper API credentials set")
    print("\nPress Ctrl+C to cancel, or wait 5 seconds to continue...\n")

    try:
        time.sleep(5)
        main()
    except KeyboardInterrupt:
        print("\n✅ Cancelled by user\n")
