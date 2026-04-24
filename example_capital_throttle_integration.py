"""
Integration Example: Automated Capital Throttle with Risk Manager

This example demonstrates how to integrate the Automated Capital Throttle
with NIJA's existing risk management system.

Author: NIJA Trading Systems
Date: February 15, 2026
"""

import logging
import sys
import os

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from automated_capital_throttle import AutomatedCapitalThrottle

logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def demonstrate_capital_throttle():
    """Demonstrate capital throttle in action"""
    
    print("\n" + "=" * 70)
    print("AUTOMATED CAPITAL THROTTLE - INTEGRATION EXAMPLE")
    print("=" * 70)
    
    # Initialize with $5k starting capital
    initial_capital = 5000.0
    throttle = AutomatedCapitalThrottle(initial_capital=initial_capital)
    
    print(f"\n📊 Starting Capital: ${initial_capital:,.2f}")
    print(f"Current Tier: ${throttle.state.current_threshold.threshold_amount:,.2f} threshold")
    print(f"Max Position Size: {throttle.state.current_threshold.max_position_size_pct*100}%")
    
    # Simulate trading from $5k to $60k
    print("\n" + "=" * 70)
    print("SIMULATION: Growing from $5k to $60k")
    print("=" * 70)
    
    capital = initial_capital
    trades = []
    
    # Simulate 200 trades with 58% win rate, 1.8 profit factor
    for i in range(200):
        # 58% win rate
        is_winner = (i % 10) < 6
        
        # Position size limited by throttle
        max_pos_pct = throttle.get_max_position_size()
        position_size = capital * max_pos_pct
        
        # Simulate trade
        if is_winner:
            profit = position_size * 0.015  # 1.5% win
        else:
            profit = -position_size * 0.008  # 0.8% loss
        
        capital += profit
        throttle.update_capital(capital)
        throttle.record_trade(is_winner, profit)
        
        trades.append({
            'trade_num': i + 1,
            'capital': capital,
            'profit': profit,
            'is_throttled': throttle.state.is_throttled,
            'max_pos_pct': max_pos_pct * 100
        })
        
        # Report progress at milestones
        if capital >= 10000 and trades[i-1]['capital'] < 10000:
            print(f"\n✨ Milestone: $10,000")
            print(f"   Trade #{i+1}")
            print(f"   Win Rate: {throttle.state.current_win_rate:.2%}")
            print(f"   Profit Factor: {throttle.state.current_profit_factor:.2f}")
            print(f"   Throttled: {throttle.state.is_throttled}")
        
        if capital >= 25000 and trades[i-1]['capital'] < 25000:
            print(f"\n✨ Milestone: $25,000")
            print(f"   Trade #{i+1}")
            print(f"   Win Rate: {throttle.state.current_win_rate:.2%}")
            print(f"   Profit Factor: {throttle.state.current_profit_factor:.2f}")
            print(f"   Throttled: {throttle.state.is_throttled}")
        
        if capital >= 50000 and trades[i-1]['capital'] < 50000:
            print(f"\n✨ Milestone: $50,000 - STRESS TEST REQUIRED")
            print(f"   Trade #{i+1}")
            print(f"   Win Rate: {throttle.state.current_win_rate:.2%}")
            print(f"   Profit Factor: {throttle.state.current_profit_factor:.2f}")
            print(f"   Throttled: {throttle.state.is_throttled}")
            
            # Run stress test
            print("\n🔥 Running 25% Drawdown Stress Test...")
            results = throttle.simulate_drawdown_stress_test(
                drawdown_pct=25.0,
                duration_days=30
            )
            
            if results['passed']:
                print("   ✅ STRESS TEST PASSED - Scaling approved")
            else:
                print(f"   ❌ STRESS TEST FAILED - {results['recovery_probability']:.2%} recovery probability")
                print("   🔒 Capital scaling locked until performance improves")
    
    # Final status
    print("\n" + "=" * 70)
    print("FINAL STATUS")
    print("=" * 70)
    
    status = throttle.get_status_report()
    
    print(f"\n💰 Capital:")
    print(f"   Starting: ${initial_capital:,.2f}")
    print(f"   Final: ${status['capital']['current']:,.2f}")
    print(f"   Peak: ${status['capital']['peak']:,.2f}")
    print(f"   Drawdown: {status['capital']['drawdown_pct']:.2f}%")
    print(f"   Return: {(status['capital']['current']/initial_capital - 1)*100:.2f}%")
    
    print(f"\n📊 Performance:")
    print(f"   Total Trades: {status['performance']['total_trades']}")
    print(f"   Win Rate: {status['performance']['win_rate']:.2%}")
    print(f"   Profit Factor: {status['performance']['profit_factor']:.2f}")
    print(f"   Winning Trades: {status['performance']['winning_trades']}")
    print(f"   Losing Trades: {status['performance']['losing_trades']}")
    
    print(f"\n🎯 Current Threshold:")
    print(f"   Amount: ${status['threshold']['amount']:,.2f}")
    print(f"   Max Position: {status['threshold']['max_position_size_pct']*100}%")
    print(f"   Required Win Rate: {status['threshold']['required_win_rate']:.2%}")
    print(f"   Required PF: {status['threshold']['required_profit_factor']:.2f}")
    
    print(f"\n🎲 Risk Analysis:")
    print(f"   Ruin Probability: {status['risk']['ruin_probability']:.4%}")
    print(f"   Max Acceptable: {status['risk']['max_acceptable']:.4%}")
    
    print(f"\n🔒 Throttle Status:")
    print(f"   Active: {status['throttle']['is_throttled']}")
    if status['throttle']['is_throttled']:
        print(f"   Reason: {status['throttle']['reason']}")
        print(f"   Level: {status['throttle']['level']}")
    print(f"   Max Position: {status['throttle']['max_position_size']*100:.2f}%")
    
    print(f"\n🔥 Stress Test:")
    print(f"   Passed: {status['stress_test']['passed']}")
    if status['stress_test']['last_run']:
        print(f"   Last Run: {status['stress_test']['last_run']}")
        if status['stress_test']['results']:
            print(f"   Recovery Probability: {status['stress_test']['results']['recovery_probability']:.2%}")
    
    print("\n" + "=" * 70)
    
    return throttle


def demonstrate_integration_with_risk_manager():
    """Show how to use throttle with risk_manager.py"""
    
    print("\n" + "=" * 70)
    print("INTEGRATION WITH RISK MANAGER")
    print("=" * 70)
    
    # Simulate a trading scenario
    current_balance = 30000.0
    throttle = AutomatedCapitalThrottle(initial_capital=current_balance)
    
    # Build some trade history
    for i in range(60):
        is_winner = (i % 3) != 0  # ~67% win rate
        throttle.record_trade(is_winner, 200.0 if is_winner else -100.0)
    
    throttle.update_capital(current_balance)
    
    print(f"\n💰 Current Balance: ${current_balance:,.2f}")
    print(f"📊 Win Rate: {throttle.state.current_win_rate:.2%}")
    print(f"📊 Profit Factor: {throttle.state.current_profit_factor:.2f}")
    
    # Get throttled position size
    throttle_max_pos = throttle.get_max_position_size()
    
    # In real code, you would also get risk manager's recommendation
    # risk_mgr_max_pos = risk_manager.calculate_position_size(...)
    risk_mgr_max_pos = 0.04  # Assume risk manager allows 4%
    
    # Use the more conservative limit
    final_pos_pct = min(throttle_max_pos, risk_mgr_max_pos)
    final_pos_dollars = current_balance * final_pos_pct
    
    print(f"\n🎯 Position Sizing:")
    print(f"   Throttle Limit: {throttle_max_pos*100:.2f}%")
    print(f"   Risk Manager Limit: {risk_mgr_max_pos*100:.2f}%")
    print(f"   Final Position Size: {final_pos_pct*100:.2f}% (${final_pos_dollars:,.2f})")
    
    if throttle.state.is_throttled:
        print(f"\n⚠️  THROTTLE ACTIVE: {throttle.state.throttle_reason}")
        print(f"   Position size reduced to {throttle_max_pos*100:.2f}%")
    else:
        print("\n✅ No throttle active - normal operations")
    
    print("\n" + "=" * 70)


def demonstrate_stress_test_scenarios():
    """Demonstrate different stress test scenarios"""
    
    print("\n" + "=" * 70)
    print("STRESS TEST SCENARIOS")
    print("=" * 70)
    
    scenarios = [
        {
            'name': 'Strong Performance (65% WR, 2.0 PF)',
            'wins': 65,
            'losses': 35,
            'win_amount': 200,
            'loss_amount': 100
        },
        {
            'name': 'Marginal Performance (52% WR, 1.3 PF)',
            'wins': 52,
            'losses': 48,
            'win_amount': 130,
            'loss_amount': 100
        },
        {
            'name': 'Weak Performance (48% WR, 1.1 PF)',
            'wins': 48,
            'losses': 52,
            'win_amount': 110,
            'loss_amount': 100
        }
    ]
    
    for scenario in scenarios:
        print(f"\n{'='*70}")
        print(f"Scenario: {scenario['name']}")
        print(f"{'='*70}")
        
        throttle = AutomatedCapitalThrottle(initial_capital=50000.0)
        
        # Build performance history
        for i in range(scenario['wins']):
            throttle.record_trade(True, scenario['win_amount'])
        for i in range(scenario['losses']):
            throttle.record_trade(False, -scenario['loss_amount'])
        
        throttle.update_capital(50000.0)
        
        print(f"Win Rate: {throttle.state.current_win_rate:.2%}")
        print(f"Profit Factor: {throttle.state.current_profit_factor:.2f}")
        
        # Run stress test
        results = throttle.simulate_drawdown_stress_test(
            drawdown_pct=25.0,
            duration_days=30
        )
        
        print(f"\nStress Test Result: {'✅ PASSED' if results['passed'] else '❌ FAILED'}")
        print(f"Recovery Probability: {results['recovery_probability']:.2%}")
        print(f"Required: {results['required_probability']:.2%}")


if __name__ == "__main__":
    # Run demonstrations
    demonstrate_capital_throttle()
    demonstrate_integration_with_risk_manager()
    demonstrate_stress_test_scenarios()
    
    print("\n" + "=" * 70)
    print("DEMONSTRATION COMPLETE")
    print("=" * 70)
    print("\nSee AUTOMATED_CAPITAL_THROTTLE.md for full documentation")
    print("=" * 70 + "\n")
