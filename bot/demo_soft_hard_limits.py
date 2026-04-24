"""
Integration Test: Soft + Hard Limit Enforcement
================================================

Demonstrates how the soft/hard limit enforcement works in practice
with realistic trading scenarios.

Author: NIJA Trading Systems
Date: February 12, 2026
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from risk_manager import AdaptiveRiskManager
from portfolio_risk_engine import PortfolioRiskEngine

def demo_position_enforcement():
    """Demonstrate position-level enforcement"""
    print("\n" + "=" * 70)
    print("DEMO 1: Position-Level Soft + Hard Enforcement")
    print("=" * 70)
    
    # Initialize with default soft/hard limits
    risk_mgr = AdaptiveRiskManager()
    
    print(f"\nConfiguration:")
    print(f"  Soft Limit: {risk_mgr.soft_position_limit_pct*100:.0f}% (warning + 50% reduction)")
    print(f"  Hard Limit: {risk_mgr.hard_position_limit_pct*100:.0f}% (block)")
    
    scenarios = [
        (0.03, "3% position - within limits"),
        (0.045, "4.5% position - triggers soft limit"),
        (0.06, "6% position - triggers hard limit"),
    ]
    
    for pct, description in scenarios:
        print(f"\n{description}:")
        allowed, adjusted_pct, info = risk_mgr.check_position_limits(pct)
        
        if info['hard_limit_triggered']:
            print(f"  ❌ BLOCKED - Exceeds hard limit")
        elif info['soft_limit_triggered']:
            print(f"  ⚠️ REDUCED - {pct*100:.1f}% → {adjusted_pct*100:.1f}%")
        else:
            print(f"  ✅ ALLOWED - {pct*100:.1f}%")


def demo_sector_enforcement():
    """Demonstrate sector-level enforcement"""
    print("\n" + "=" * 70)
    print("DEMO 2: Sector-Level Soft + Hard Enforcement")
    print("=" * 70)
    
    # Initialize portfolio risk engine
    portfolio_risk = PortfolioRiskEngine({
        'soft_sector_limit_pct': 0.15,
        'hard_sector_limit_pct': 0.20
    })
    
    print(f"\nConfiguration:")
    print(f"  Soft Limit: {portfolio_risk.soft_sector_limit_pct*100:.0f}% (warning + 50% reduction)")
    print(f"  Hard Limit: {portfolio_risk.hard_sector_limit_pct*100:.0f}% (block)")
    
    portfolio_value = 10000.0
    
    # Add some existing positions
    print(f"\nPortfolio: ${portfolio_value:,.2f}")
    print(f"\nExisting Positions:")
    
    # Add Layer-1 positions
    portfolio_risk.add_position("SOL-USD", 800.0, "long", portfolio_value)
    print(f"  SOL-USD: $800 (8%)")
    
    portfolio_risk.add_position("ADA-USD", 600.0, "long", portfolio_value)
    print(f"  ADA-USD: $600 (6%)")
    
    # Try to add more Layer-1
    print(f"\nTrying to add more Layer-1 positions:")
    
    # This should trigger soft limit
    print(f"\n  AVAX-USD $400 (4%) - Would bring Layer-1 to 18%")
    allowed, adjusted, info = portfolio_risk.check_sector_limits(
        "AVAX-USD", 400.0, portfolio_value
    )
    if info['soft_limit_triggered']:
        print(f"  ⚠️ SOFT LIMIT - Reduced to ${adjusted:.2f}")
    
    # This should trigger hard limit (simulate 19% already in sector)
    from datetime import datetime
    from portfolio_risk_engine import PositionExposure
    portfolio_risk.positions["NEAR-USD"] = PositionExposure(
        symbol="NEAR-USD",
        size_usd=500.0,
        pct_of_portfolio=0.05,
        direction="long",
        entry_time=datetime.now()
    )
    
    print(f"\n  (Added NEAR-USD $500 manually)")
    print(f"  DOT-USD $200 (2%) - Would bring Layer-1 to 21%")
    allowed, adjusted, info = portfolio_risk.check_sector_limits(
        "DOT-USD", 200.0, portfolio_value
    )
    if info['hard_limit_triggered']:
        print(f"  🚫 HARD LIMIT - BLOCKED")


def demo_realistic_workflow():
    """Demonstrate realistic trading workflow"""
    print("\n" + "=" * 70)
    print("DEMO 3: Realistic Trading Workflow")
    print("=" * 70)
    
    account_balance = 5000.0
    print(f"\nAccount Balance: ${account_balance:,.2f}")
    
    # Initialize risk manager
    risk_mgr = AdaptiveRiskManager(
        soft_position_limit_pct=0.04,  # 4%
        hard_position_limit_pct=0.05,  # 5%
    )
    
    # Calculate position size for a trade
    print(f"\nCalculating position size for BTC-USD:")
    print(f"  ADX: 35 (strong trend)")
    print(f"  Signal Strength: 4 (strong)")
    print(f"  AI Confidence: 0.8 (high)")
    
    position_size, breakdown = risk_mgr.calculate_position_size(
        account_balance=account_balance,
        adx=35,
        signal_strength=4,
        ai_confidence=0.8,
        volatility_pct=0.015
    )
    
    print(f"\nCalculated Position Size:")
    print(f"  Base %: {breakdown.get('base_pct', 0)*100:.1f}%")
    print(f"  Final %: {breakdown.get('final_pct', 0)*100:.1f}%")
    print(f"  Position Size: ${position_size:,.2f}")
    
    if 'soft_limit_applied' in breakdown:
        print(f"  ⚠️ Soft limit was applied - size reduced")
    
    if 'position_blocked' in breakdown:
        print(f"  🚫 Position was blocked by hard limit")
    
    print("\n✅ Workflow demonstrates proper limit enforcement")


if __name__ == "__main__":
    demo_position_enforcement()
    demo_sector_enforcement()
    demo_realistic_workflow()
    
    print("\n" + "=" * 70)
    print("DEMO COMPLETE")
    print("=" * 70)
    print("\nKey Takeaways:")
    print("1. Soft limits provide flexibility by reducing position size")
    print("2. Hard limits provide discipline by blocking risky trades")
    print("3. Sector limits prevent over-concentration in correlated assets")
    print("4. System integrates seamlessly into existing workflow")
    print("=" * 70 + "\n")
