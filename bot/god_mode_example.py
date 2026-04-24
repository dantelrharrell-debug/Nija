"""
NIJA God Mode Example Usage
============================

Demonstrates how to use the God Mode Engine in live trading.

This example shows:
1. Initializing God Mode Engine
2. Getting trading recommendations
3. Recording trade entries/exits for learning
4. State persistence

Author: NIJA Trading Systems
Version: 1.0 - God Mode Edition
Date: January 29, 2026
"""

import pandas as pd
import numpy as np
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Import God Mode components
from bot.god_mode_engine import GodModeEngine, GodModeConfig
from bot.god_mode_config import GOD_MODE_CONFIG

logger = logging.getLogger("nija.god_mode_example")


def create_sample_market_data():
    """Create sample market data for demonstration"""
    # Generate sample OHLCV data
    dates = pd.date_range(start='2025-01-01', periods=100, freq='1H')
    
    df = pd.DataFrame({
        'timestamp': dates,
        'open': np.random.randn(100).cumsum() + 100,
        'high': np.random.randn(100).cumsum() + 102,
        'low': np.random.randn(100).cumsum() + 98,
        'close': np.random.randn(100).cumsum() + 100,
        'volume': np.random.randint(1000, 10000, 100),
    })
    
    df.set_index('timestamp', inplace=True)
    return df


def create_sample_indicators():
    """Create sample indicators for demonstration"""
    return {
        'rsi_9': 45.0,
        'rsi_14': 52.0,
        'adx': 28.5,
        'atr': 2.5,
        'volume_ratio': 0.65,
        'macd': 1.2,
        'macd_signal': 0.8,
        'bb_upper': 105.0,
        'bb_lower': 95.0,
    }


def example_basic_usage():
    """Example 1: Basic God Mode usage"""
    logger.info("=" * 70)
    logger.info("EXAMPLE 1: Basic God Mode Usage")
    logger.info("=" * 70)
    
    # Initialize God Mode with default config
    config = GodModeConfig(**GOD_MODE_CONFIG)
    god_mode = GodModeEngine(config)
    
    # Create sample data
    market_data = create_sample_market_data()
    indicators = create_sample_indicators()
    
    # Get recommendation
    recommendation = god_mode.get_recommendation(
        market_data=market_data,
        indicators=indicators,
    )
    
    logger.info("\n" + recommendation.summary)
    logger.info(f"\nRecommended Parameters: {recommendation.recommended_parameters}")
    
    return god_mode


def example_with_positions():
    """Example 2: God Mode with position sizing"""
    logger.info("\n" + "=" * 70)
    logger.info("EXAMPLE 2: God Mode with Risk Parity Position Sizing")
    logger.info("=" * 70)
    
    # Initialize God Mode
    config = GodModeConfig(**GOD_MODE_CONFIG)
    god_mode = GodModeEngine(config)
    
    # Sample current positions
    current_positions = {
        'BTC-USD': {
            'allocation_pct': 0.30,
            'quantity': 0.5,
            'entry_price': 45000,
        },
        'ETH-USD': {
            'allocation_pct': 0.25,
            'quantity': 10,
            'entry_price': 2500,
        },
        'SOL-USD': {
            'allocation_pct': 0.20,
            'quantity': 100,
            'entry_price': 100,
        },
    }
    
    # Sample price history for correlation analysis
    price_history = {
        'BTC-USD': create_sample_market_data(),
        'ETH-USD': create_sample_market_data(),
        'SOL-USD': create_sample_market_data(),
    }
    
    # Get recommendation with position sizing
    market_data = create_sample_market_data()
    indicators = create_sample_indicators()
    
    recommendation = god_mode.get_recommendation(
        market_data=market_data,
        indicators=indicators,
        current_positions=current_positions,
        price_history=price_history,
    )
    
    logger.info("\n" + recommendation.summary)
    
    if recommendation.recommended_position_sizes:
        logger.info("\nRecommended Position Sizes (Risk Parity):")
        for symbol, size in recommendation.recommended_position_sizes.items():
            current_size = current_positions[symbol]['allocation_pct']
            logger.info(f"  {symbol}: {size:.1%} (current: {current_size:.1%})")
    
    return god_mode


def example_learning_loop():
    """Example 3: Complete learning loop with trade tracking"""
    logger.info("\n" + "=" * 70)
    logger.info("EXAMPLE 3: Complete Learning Loop")
    logger.info("=" * 70)
    
    # Initialize God Mode
    config = GodModeConfig(**GOD_MODE_CONFIG)
    god_mode = GodModeEngine(config)
    
    # Simulate 5 trades
    for i in range(5):
        logger.info(f"\n--- Trade {i+1} ---")
        
        # Get recommendation
        market_data = create_sample_market_data()
        indicators = create_sample_indicators()
        
        recommendation = god_mode.get_recommendation(
            market_data=market_data,
            indicators=indicators,
        )
        
        # Simulate trade entry
        trade_id = f"trade_{i+1}"
        entry_price = 100 + np.random.randn() * 5
        strategy_used = recommendation.recommended_strategy_id
        parameters_used = recommendation.recommended_parameters
        
        god_mode.record_trade_entry(
            trade_id=trade_id,
            market_data=market_data,
            indicators=indicators,
            strategy_used=strategy_used,
            entry_price=entry_price,
            parameters_used=parameters_used,
        )
        
        logger.info(f"Entered trade {trade_id} at ${entry_price:.2f}")
        
        # Simulate some time passing and exit
        exit_price = entry_price + np.random.randn() * 3
        profit_loss = (exit_price - entry_price) * 10  # Simulate 10 units
        
        god_mode.record_trade_exit(
            trade_id=trade_id,
            market_data=create_sample_market_data(),
            indicators=create_sample_indicators(),
            exit_price=exit_price,
            profit_loss=profit_loss,
            parameters_used=parameters_used,
        )
        
        logger.info(f"Exited trade {trade_id} at ${exit_price:.2f}")
        logger.info(f"P&L: ${profit_loss:.2f}")
    
    # Get final status
    if god_mode.meta_optimizer:
        status = god_mode.meta_optimizer.get_status()
        logger.info("\n" + status.summary)
    
    if god_mode.live_rl:
        rl_status = god_mode.live_rl.get_status()
        logger.info("\n" + rl_status.summary)
    
    return god_mode


def example_state_persistence():
    """Example 4: Saving and loading state"""
    logger.info("\n" + "=" * 70)
    logger.info("EXAMPLE 4: State Persistence")
    logger.info("=" * 70)
    
    # Initialize and run some trades
    config = GodModeConfig(**GOD_MODE_CONFIG)
    god_mode = GodModeEngine(config)
    
    # Simulate trades
    for i in range(3):
        market_data = create_sample_market_data()
        indicators = create_sample_indicators()
        recommendation = god_mode.get_recommendation(market_data, indicators)
        
        trade_id = f"test_trade_{i}"
        god_mode.record_trade_entry(
            trade_id,
            market_data,
            indicators,
            recommendation.recommended_strategy_id,
            100.0,
            recommendation.recommended_parameters,
        )
        god_mode.record_trade_exit(
            trade_id,
            market_data,
            indicators,
            105.0,
            50.0,
            recommendation.recommended_parameters,
        )
    
    # Save state
    logger.info("Saving God Mode state...")
    god_mode.save_state()
    
    # Create new instance and load state
    logger.info("Creating new God Mode instance...")
    new_god_mode = GodModeEngine(config)
    
    logger.info("Loading saved state...")
    new_god_mode.load_state()
    
    logger.info("✅ State successfully saved and loaded!")
    
    return new_god_mode


def main():
    """Run all examples"""
    logger.info("🔥" * 35)
    logger.info("NIJA GOD MODE - EXAMPLE USAGE")
    logger.info("🔥" * 35)
    
    try:
        # Example 1: Basic usage
        example_basic_usage()
        
        # Example 2: With position sizing
        example_with_positions()
        
        # Example 3: Complete learning loop
        example_learning_loop()
        
        # Example 4: State persistence
        example_state_persistence()
        
        logger.info("\n" + "=" * 70)
        logger.info("✅ ALL EXAMPLES COMPLETED SUCCESSFULLY!")
        logger.info("=" * 70)
        
    except Exception as e:
        logger.error(f"Error in examples: {e}", exc_info=True)


if __name__ == "__main__":
    main()
