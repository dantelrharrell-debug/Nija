#!/usr/bin/env python3
"""
Example usage of NIJA Apex Strategy v7.1

This script demonstrates how to:
1. Initialize the strategy
2. Analyze market data
3. Execute trades based on signals
4. Manage positions
"""

import sys
import os
import pandas as pd
from datetime import datetime

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from nija_apex_strategy_v71 import NIJAApexStrategyV71


def create_sample_data():
    """Create sample price data for demonstration"""
    # In production, this would come from your broker API
    dates = pd.date_range(start='2025-01-01', periods=100, freq='5T')
    
    # Simulated price data
    data = {
        'open': [100 + i * 0.1 for i in range(100)],
        'high': [101 + i * 0.1 for i in range(100)],
        'low': [99 + i * 0.1 for i in range(100)],
        'close': [100.5 + i * 0.1 for i in range(100)],
        'volume': [1000 + i * 10 for i in range(100)]
    }
    
    df = pd.DataFrame(data, index=dates)
    return df


def main():
    """Main demonstration function"""
    
    print("=" * 80)
    print("NIJA APEX STRATEGY v7.1 - DEMONSTRATION")
    print("=" * 80)
    print()
    
    # 1. Initialize strategy
    print("1. Initializing strategy...")
    
    # Configuration (optional)
    config = {
        'min_adx': 20,
        'volume_threshold': 0.5,
        'volume_min_threshold': 0.3,
        'candle_exclusion_seconds': 6,
        'news_buffer_minutes': 5,
        'min_position_pct': 0.02,
        'max_position_pct': 0.10,
        'ai_momentum_enabled': False  # Set to True to enable AI scoring
    }
    
    # Initialize strategy (without broker for demo)
    strategy = NIJAApexStrategyV71(broker_client=None, config=config)
    print("   ✓ Strategy initialized")
    print()
    
    # 2. Load market data
    print("2. Loading market data...")
    df = create_sample_data()
    print(f"   ✓ Loaded {len(df)} candles")
    print(f"   ✓ Timeframe: {df.index[0]} to {df.index[-1]}")
    print()
    
    # 3. Analyze market
    print("3. Analyzing market conditions...")
    symbol = "BTC-USD"
    account_balance = 10000.0  # $10,000 example balance
    
    analysis = strategy.analyze_market(df, symbol, account_balance)
    
    print(f"   Action: {analysis['action']}")
    print(f"   Reason: {analysis['reason']}")
    
    if analysis['action'] in ['enter_long', 'enter_short']:
        print()
        print("   ENTRY SIGNAL DETECTED!")
        print(f"   Entry Price: ${analysis['entry_price']:.2f}")
        print(f"   Position Size: ${analysis['position_size']:.2f}")
        print(f"   Stop Loss: ${analysis['stop_loss']:.2f}")
        print(f"   TP1 (1R): ${analysis['take_profit']['tp1']:.2f}")
        print(f"   TP2 (2R): ${analysis['take_profit']['tp2']:.2f}")
        print(f"   TP3 (3R): ${analysis['take_profit']['tp3']:.2f}")
        print(f"   Risk: ${analysis['take_profit']['risk']:.2f}/share")
        print(f"   Signal Score: {analysis['score']}/5")
        print(f"   ADX: {analysis['adx']:.1f}")
    
    print()
    
    # 4. Show strategy features
    print("4. Strategy Features:")
    print("   ✓ Market Filter (VWAP, EMA9/21/50, MACD, ADX>20, Volume)")
    print("   ✓ Entry Logic (Pullback to EMA21/VWAP, RSI, Candlestick, MACD, Volume)")
    print("   ✓ Dynamic Risk (ADX-based position sizing 2-10%)")
    print("   ✓ Stop Loss (Swing low/high + ATR*0.5 buffer)")
    print("   ✓ Take Profit (TP1=1R with B/E, TP2=2R, TP3=3R)")
    print("   ✓ Trailing Stop (ATR*1.5 after TP1)")
    print("   ✓ Exit Logic (Opposite signal, trailing stop, EMA9/21 cross)")
    print("   ✓ Smart Filters (News stub, volume <30%, first 6s candle)")
    print("   ✓ AI Momentum Scoring (skeleton for future ML integration)")
    print()
    
    # 5. Broker integration examples
    print("5. Broker Integration (Extensible):")
    print("   Supported brokers:")
    print("   • Coinbase Advanced Trade (implemented)")
    print("   • Alpaca (implemented)")
    print("   • Binance (skeleton - ready for implementation)")
    print("   • Interactive Brokers (skeleton)")
    print("   • Any broker via BaseBroker interface")
    print()
    
    print("=" * 80)
    print("DEMONSTRATION COMPLETE")
    print("=" * 80)
    print()
    print("Next steps:")
    print("1. Connect to your broker API (see bot/broker_manager.py)")
    print("2. Run live trading with: python bot/live_trading.py")
    print("3. Or integrate into existing bot: from nija_apex_strategy_v71 import NIJAApexStrategyV71")
    print()


if __name__ == "__main__":
    main()
