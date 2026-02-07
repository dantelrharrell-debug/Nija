#!/usr/bin/env python3
"""
Demo: Paper Trading Analytics System

Demonstrates the 3-phase process with simulated trades:
1. Collect 100-300 trades with analytics
2. Identify and kill underperformers
3. Validate profit-ready criteria

This script generates realistic simulated trades to show how the system works.

Author: NIJA Trading Systems
Version: 1.0
Date: February 2026
"""

import sys
from pathlib import Path
import random
from datetime import datetime, timedelta
import numpy as np

# Add bot directory to path
sys.path.insert(0, str(Path(__file__).parent))

from bot.paper_trading_analytics import (
    PaperTradingAnalytics,
    TradeAnalytics,
    SignalType,
    ExitReason,
    ProfitReadyCriteria
)


class PaperTradingSimulator:
    """Simulates paper trading with realistic performance characteristics"""
    
    def __init__(self, analytics: PaperTradingAnalytics):
        """
        Initialize simulator
        
        Args:
            analytics: PaperTradingAnalytics instance
        """
        self.analytics = analytics
        
        # Signal performance profiles (realistic win rates and profit factors)
        self.signal_profiles = {
            SignalType.DUAL_RSI.value: {'win_rate': 0.55, 'avg_win': 50, 'avg_loss': -35},
            SignalType.RSI_OVERSOLD.value: {'win_rate': 0.48, 'avg_win': 45, 'avg_loss': -40},
            SignalType.BREAKOUT.value: {'win_rate': 0.42, 'avg_win': 60, 'avg_loss': -30},
            SignalType.TREND_FOLLOWING.value: {'win_rate': 0.52, 'avg_win': 55, 'avg_loss': -32},
            SignalType.MEAN_REVERSION.value: {'win_rate': 0.38, 'avg_win': 40, 'avg_loss': -45},  # Underperformer
            SignalType.VOLATILITY_EXPANSION.value: {'win_rate': 0.60, 'avg_win': 70, 'avg_loss': -35},
            SignalType.WEBHOOK.value: {'win_rate': 0.35, 'avg_win': 50, 'avg_loss': -55},  # Underperformer
        }
        
        # Exit performance profiles
        self.exit_profiles = {
            ExitReason.PROFIT_TARGET.value: {'win_rate': 0.65, 'avg_pnl': 45},
            ExitReason.STOP_LOSS.value: {'win_rate': 0.0, 'avg_pnl': -40},
            ExitReason.TRAILING_STOP.value: {'win_rate': 0.58, 'avg_pnl': 35},
            ExitReason.PARTIAL_PROFIT.value: {'win_rate': 0.70, 'avg_pnl': 25},
            ExitReason.TIME_EXIT.value: {'win_rate': 0.30, 'avg_pnl': -15},  # Underperformer
            ExitReason.SIGNAL_REVERSAL.value: {'win_rate': 0.45, 'avg_pnl': 10},
        }
        
        self.start_time = datetime.now()
        self.crypto_symbols = [
            'BTC-USD', 'ETH-USD', 'SOL-USD', 'AVAX-USD', 'MATIC-USD',
            'LINK-USD', 'UNI-USD', 'AAVE-USD', 'DOT-USD', 'ATOM-USD'
        ]
    
    def generate_trade(self, trade_number: int) -> TradeAnalytics:
        """
        Generate a realistic simulated trade
        
        Args:
            trade_number: Sequential trade number
        
        Returns:
            TradeAnalytics object
        """
        # Random signal type (weighted towards better performers)
        signal_type = random.choice([
            SignalType.DUAL_RSI.value,
            SignalType.DUAL_RSI.value,  # More likely
            SignalType.RSI_OVERSOLD.value,
            SignalType.BREAKOUT.value,
            SignalType.TREND_FOLLOWING.value,
            SignalType.TREND_FOLLOWING.value,  # More likely
            SignalType.MEAN_REVERSION.value,
            SignalType.VOLATILITY_EXPANSION.value,
            SignalType.VOLATILITY_EXPANSION.value,  # More likely
            SignalType.WEBHOOK.value,
        ])
        
        # Get signal profile
        profile = self.signal_profiles[signal_type]
        
        # Determine if win or loss based on profile
        is_win = random.random() < profile['win_rate']
        
        # Generate P&L
        if is_win:
            base_pnl = profile['avg_win']
            pnl = np.random.normal(base_pnl, base_pnl * 0.3)  # 30% std dev
        else:
            base_pnl = profile['avg_loss']
            pnl = np.random.normal(base_pnl, abs(base_pnl) * 0.3)
        
        # Entry details
        symbol = random.choice(self.crypto_symbols)
        entry_price = random.uniform(0.5, 50000)  # Varies by crypto
        entry_size_usd = random.uniform(100, 500)
        
        # Exit details - choose based on performance
        if is_win:
            # Winners more likely to hit profit targets
            exit_reason = random.choice([
                ExitReason.PROFIT_TARGET.value,
                ExitReason.PROFIT_TARGET.value,
                ExitReason.TRAILING_STOP.value,
                ExitReason.PARTIAL_PROFIT.value,
            ])
        else:
            # Losers more likely to hit stops
            exit_reason = random.choice([
                ExitReason.STOP_LOSS.value,
                ExitReason.STOP_LOSS.value,
                ExitReason.TIME_EXIT.value,
                ExitReason.SIGNAL_REVERSAL.value,
            ])
        
        # Calculate exit price from P&L
        pnl_pct = (pnl / entry_size_usd) * 100
        exit_price = entry_price * (1 + pnl_pct / 100)
        
        # Timing
        trade_time = self.start_time + timedelta(hours=trade_number * 2)
        duration_minutes = random.uniform(15, 240)  # 15 min to 4 hours
        
        # Risk metrics
        mfe = abs(pnl) * random.uniform(1.2, 2.0) if is_win else abs(pnl) * random.uniform(0.3, 0.8)
        mae = abs(pnl) * random.uniform(0.3, 0.8) if is_win else abs(pnl) * random.uniform(1.0, 1.5)
        
        # Create trade
        trade = TradeAnalytics(
            trade_id=f"TRADE-{trade_number:04d}",
            timestamp=trade_time.isoformat(),
            symbol=symbol,
            signal_type=signal_type,
            entry_price=entry_price,
            entry_size_usd=entry_size_usd,
            entry_time=trade_time.isoformat(),
            exit_reason=exit_reason,
            exit_price=exit_price,
            exit_time=(trade_time + timedelta(minutes=duration_minutes)).isoformat(),
            gross_pnl=pnl,
            net_pnl=pnl * 0.988,  # Account for fees (~1.2% total)
            pnl_pct=pnl_pct,
            duration_minutes=duration_minutes,
            max_favorable_excursion=mfe,
            max_adverse_excursion=mae,
            risk_reward_ratio=abs(mfe / mae) if mae != 0 else 1.0,
            market_regime=random.choice(['trending', 'ranging', 'volatile']),
            scan_time_seconds=random.uniform(5, 25),
            rsi_9=random.uniform(20, 80),
            rsi_14=random.uniform(25, 75),
            volatility=random.uniform(0.5, 3.0)
        )
        
        return trade
    
    def run_simulation(self, num_trades: int = 150) -> None:
        """
        Run paper trading simulation
        
        Args:
            num_trades: Number of trades to simulate
        """
        print(f"\n🎬 Starting Paper Trading Simulation")
        print(f"   Generating {num_trades} trades with realistic performance profiles...")
        print(f"   This demonstrates the 3-phase optimization process\n")
        
        for i in range(num_trades):
            trade = self.generate_trade(i + 1)
            self.analytics.record_trade(trade)
            
            # Progress indicator
            if (i + 1) % 25 == 0:
                print(f"   ✅ Generated {i + 1}/{num_trades} trades")
        
        print(f"\n✅ Simulation complete! {num_trades} trades recorded")
        print(f"   Data saved to: {self.analytics.data_dir}")


def main():
    """Run the demo"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Demo: Paper Trading Analytics System'
    )
    parser.add_argument('--trades', type=int, default=150,
                       help='Number of trades to simulate (default: 150)')
    parser.add_argument('--data-dir', type=str, default='./data/demo_paper_analytics',
                       help='Data directory for demo (default: ./data/demo_paper_analytics)')
    
    args = parser.parse_args()
    
    print("="*80)
    print("📊 NIJA Paper Trading Analytics - DEMO")
    print("="*80)
    print("\nThis demo simulates the 3-phase optimization process:")
    print("  1️⃣  Collect 100-300 trades with analytics ON")
    print("  2️⃣  Identify and kill underperformers (bottom 25%)")
    print("  3️⃣  Validate profit-ready criteria")
    print("="*80)
    
    # Create analytics instance
    analytics = PaperTradingAnalytics(data_dir=args.data_dir)
    
    # Run simulation
    simulator = PaperTradingSimulator(analytics)
    simulator.run_simulation(num_trades=args.trades)
    
    # Show next steps
    print("\n" + "="*80)
    print("📋 NEXT STEPS")
    print("="*80)
    print(f"\n1️⃣  View the analytics report:")
    print(f"   python paper_trading_manager.py --data-dir {args.data_dir} --report")
    
    print(f"\n2️⃣  Analyze top and bottom performers:")
    print(f"   python paper_trading_manager.py --data-dir {args.data_dir} --analyze")
    
    print(f"\n3️⃣  Kill underperformers:")
    print(f"   python paper_trading_manager.py --data-dir {args.data_dir} --kill-losers")
    
    print(f"\n4️⃣  Check profit-ready status:")
    print(f"   python paper_trading_manager.py --data-dir {args.data_dir} --check-ready")
    
    print("\n" + "="*80 + "\n")


if __name__ == '__main__':
    main()
