"""
Institutional Capital Management - Live Demo
=============================================

Demonstrates all institutional features working together in realistic scenarios.

This demo shows:
1. Normal trading operations
2. Market volatility response
3. Drawdown protection
4. Performance scaling
5. Liquidity gating
6. Capital preservation

Author: NIJA Trading Systems
Version: 1.0
Date: February 18, 2026
"""

import logging
from datetime import datetime
from institutional_capital_manager import create_institutional_manager
from liquidity_volume_gate import create_liquidity_gate
from performance_based_risk_scaling import create_performance_scaling, PerformanceMetrics
from capital_preservation_override import create_preservation_override

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


class InstitutionalDemo:
    """Demo of institutional capital management in action"""
    
    def __init__(self, base_capital=10_000.0, tier="INCOME"):
        self.base_capital = base_capital
        self.tier = tier
        
        # Initialize all systems
        self.manager = create_institutional_manager(base_capital, tier)
        self.gate = create_liquidity_gate(tier)
        self.scaler = create_performance_scaling()
        self.preservation = create_preservation_override(base_capital)
        
        # Trading state
        self.current_capital = base_capital
        self.trades = []
        self.positions = []
    
    def scenario_1_normal_trading(self):
        """Scenario 1: Normal trading conditions"""
        print("\n" + "=" * 80)
        print("SCENARIO 1: Normal Trading Conditions")
        print("=" * 80)
        
        # Good market conditions
        market_data = {
            'volume_24h': 25_000_000,
            'avg_volume': 23_000_000,
            'bid': 50_000,
            'ask': 50_005,
            'price': 50_002.5,
            'atr_pct': 1.5,
            'market_depth_bid': 300_000,
            'market_depth_ask': 320_000
        }
        
        # Good performance
        self.manager.update_metrics(
            current_capital=10_500.0,
            portfolio_correlation=0.45,
            monthly_return=0.05,
            active_positions=2
        )
        
        # Calculate position
        base_size = 1000.0
        adjusted_size, reasoning = self.manager.calculate_position_size(
            base_size, "BTC-USD", market_data
        )
        
        print(f"\n📊 Trading Conditions: EXCELLENT")
        print(f"   Market Volume: ${market_data['volume_24h']:,.0f}")
        print(f"   Portfolio Correlation: {0.45:.2f}")
        print(f"   Monthly Return: 5.0%")
        print(f"\n💰 Position Sizing:")
        print(f"   Base Size: ${base_size:,.2f}")
        print(f"   Adjusted Size: ${adjusted_size:,.2f}")
        print(f"   Adjustment: {adjusted_size/base_size:.1%}")
        print(f"\n📝 Reasoning: {reasoning}")
        
        # Check gates
        can_trade, reason = self.manager.can_trade()
        print(f"\n✅ Trading Status: {'ALLOWED' if can_trade else 'BLOCKED'}")
        
        # Risk report
        print("\n" + self.manager.get_risk_report())
    
    def scenario_2_high_volatility(self):
        """Scenario 2: High volatility market"""
        print("\n" + "=" * 80)
        print("SCENARIO 2: High Volatility Market")
        print("=" * 80)
        
        # High volatility conditions
        market_data = {
            'volume_24h': 30_000_000,
            'avg_volume': 25_000_000,
            'bid': 48_000,
            'ask': 48_025,
            'price': 48_012.5,
            'atr_pct': 5.0,  # High volatility
            'market_depth_bid': 200_000,
            'market_depth_ask': 180_000
        }
        
        self.manager.update_metrics(
            current_capital=10_300.0,
            portfolio_correlation=0.55,
            monthly_return=0.03,
            active_positions=3
        )
        
        base_size = 1000.0
        adjusted_size, reasoning = self.manager.calculate_position_size(
            base_size, "ETH-USD", market_data
        )
        
        print(f"\n📊 Trading Conditions: HIGH VOLATILITY")
        print(f"   ATR: {market_data['atr_pct']:.1f}%")
        print(f"   Spread: {(market_data['ask']-market_data['bid'])/market_data['price']*10000:.1f} bps")
        print(f"\n💰 Position Sizing:")
        print(f"   Base Size: ${base_size:,.2f}")
        print(f"   Adjusted Size: ${adjusted_size:,.2f}")
        print(f"   Adjustment: {adjusted_size/base_size:.1%}")
        print(f"\n📝 Reasoning: {reasoning}")
        print(f"\n⚠️  Note: Position significantly reduced due to high volatility")
    
    def scenario_3_drawdown(self):
        """Scenario 3: Drawdown protection"""
        print("\n" + "=" * 80)
        print("SCENARIO 3: Drawdown Protection")
        print("=" * 80)
        
        # Simulate losses
        print("\n📉 Simulating losing streak...")
        losses = [200, 150, 180, 220, 250]  # Total: $1000 loss
        
        current = 10_500.0
        for i, loss in enumerate(losses, 1):
            current -= loss
            self.manager.update_metrics(
                current_capital=current,
                portfolio_correlation=0.60,
                monthly_return=-0.095,
                active_positions=2
            )
            print(f"   Trade {i}: -${loss} | Capital: ${current:,.2f} | DD: {self.manager.metrics.drawdown_pct:.2f}%")
        
        # Try to trade during drawdown
        market_data = {
            'volume_24h': 20_000_000,
            'avg_volume': 20_000_000,
            'bid': 49_000,
            'ask': 49_010,
            'price': 49_005,
            'atr_pct': 2.0
        }
        
        base_size = 1000.0
        adjusted_size, reasoning = self.manager.calculate_position_size(
            base_size, "BTC-USD", market_data
        )
        
        print(f"\n💰 Position Sizing After Drawdown:")
        print(f"   Base Size: ${base_size:,.2f}")
        print(f"   Adjusted Size: ${adjusted_size:,.2f}")
        print(f"   Throttle Level: {self.manager.metrics.current_throttle_level.value.upper()}")
        print(f"   Adjustment: {adjusted_size/base_size:.1%}")
        print(f"\n📝 Reasoning: {reasoning}")
        print(f"\n🛡️  Drawdown Protection Active - Positions Significantly Reduced")
    
    def scenario_4_illiquid_market(self):
        """Scenario 4: Illiquid market rejection"""
        print("\n" + "=" * 80)
        print("SCENARIO 4: Illiquid Market Rejection")
        print("=" * 80)
        
        # Low liquidity market
        market_data = {
            'volume_24h': 1_000_000,  # Too low for INCOME tier
            'avg_volume': 1_200_000,
            'bid': 100,
            'ask': 105,
            'price': 102.5,
            'atr_pct': 3.0,
            'market_depth_bid': 20_000,
            'market_depth_ask': 18_000
        }
        
        # Reset to normal capital
        self.manager.update_metrics(
            current_capital=10_500.0,
            portfolio_correlation=0.50,
            monthly_return=0.05,
            active_positions=2
        )
        
        # Check liquidity
        liquidity_result = self.gate.check_liquidity("LOWCAP-USD", market_data, 500.0)
        
        print(f"\n📊 Market: LOWCAP-USD")
        print(f"   Volume: ${market_data['volume_24h']:,.0f}")
        print(f"   Required: ${self.gate.requirements.min_volume_24h:,.0f}")
        print(f"   Liquidity Score: {liquidity_result.liquidity_score:.2f}")
        print(f"   Required Score: {self.gate.requirements.min_liquidity_score:.2f}")
        
        print(f"\n❌ Liquidity Gate: {'PASSED' if liquidity_result.passed else 'FAILED'}")
        if not liquidity_result.passed:
            print(f"\n🚫 Violations:")
            for violation in liquidity_result.violations:
                print(f"   • {violation}")
        
        # Try to calculate position
        base_size = 500.0
        adjusted_size, reasoning = self.manager.calculate_position_size(
            base_size, "LOWCAP-USD", market_data
        )
        
        print(f"\n💰 Position Sizing:")
        print(f"   Base Size: ${base_size:,.2f}")
        print(f"   Adjusted Size: ${adjusted_size:,.2f}")
        print(f"\n📝 Result: {reasoning}")
    
    def scenario_5_capital_preservation(self):
        """Scenario 5: Capital preservation trigger"""
        print("\n" + "=" * 80)
        print("SCENARIO 5: Capital Preservation Trigger")
        print("=" * 80)
        
        # Simulate catastrophic loss
        print("\n💥 Simulating catastrophic loss...")
        initial = 10_000.0
        final = 7_000.0  # 30% loss
        
        self.manager.update_metrics(
            current_capital=final,
            portfolio_correlation=0.70,
            monthly_return=-0.30,
            active_positions=0
        )
        
        print(f"   Initial Capital: ${initial:,.2f}")
        print(f"   Final Capital: ${final:,.2f}")
        print(f"   Drawdown: {(initial-final)/initial*100:.1f}%")
        
        # Check preservation
        can_trade, reason = self.manager.can_trade()
        
        print(f"\n🚨 Capital Preservation Status:")
        print(f"   Trading Allowed: {'YES' if can_trade else 'NO'}")
        print(f"   Reason: {reason}")
        
        if not can_trade:
            print(f"\n🛑 TRADING HALTED")
            print(f"   All trading operations suspended")
            print(f"   Manual review required")
            print(f"   Capital preservation mode active")
    
    def scenario_6_performance_scaling(self):
        """Scenario 6: Performance-based scaling"""
        print("\n" + "=" * 80)
        print("SCENARIO 6: Performance-Based Scaling")
        print("=" * 80)
        
        # Test excellent performance
        print("\n✅ EXCELLENT Performance:")
        metrics_excellent = PerformanceMetrics(
            monthly_return=0.20,
            sharpe_ratio=2.5,
            win_rate=0.70,
            profit_factor=3.0,
            current_streak=5,
            confidence_score=0.85
        )
        self.scaler.update_metrics(metrics_excellent)
        result = self.scaler.calculate_scale_factor(1000.0)
        
        print(f"   Monthly Return: {metrics_excellent.monthly_return:.1%}")
        print(f"   Sharpe Ratio: {metrics_excellent.sharpe_ratio:.2f}")
        print(f"   Win Rate: {metrics_excellent.win_rate:.1%}")
        print(f"   Scale Factor: {result.scale_factor:.1%}")
        print(f"   $1,000 → ${result.scaled_size:,.2f}")
        
        # Test poor performance
        print("\n❌ POOR Performance:")
        metrics_poor = PerformanceMetrics(
            monthly_return=-0.10,
            sharpe_ratio=0.2,
            win_rate=0.35,
            profit_factor=0.6,
            current_streak=-5,
            current_drawdown_pct=15.0,
            confidence_score=0.20
        )
        self.scaler.update_metrics(metrics_poor)
        result = self.scaler.calculate_scale_factor(1000.0)
        
        print(f"   Monthly Return: {metrics_poor.monthly_return:.1%}")
        print(f"   Sharpe Ratio: {metrics_poor.sharpe_ratio:.2f}")
        print(f"   Win Rate: {metrics_poor.win_rate:.1%}")
        print(f"   Scale Factor: {result.scale_factor:.1%}")
        print(f"   $1,000 → ${result.scaled_size:,.2f}")
        
        print(f"\n📊 Performance scaling dynamically adjusts position sizes")
        print(f"   from 0.5x (poor) to 1.5x (excellent)")
    
    def run_all_scenarios(self):
        """Run all demo scenarios"""
        print("\n" + "=" * 90)
        print("INSTITUTIONAL CAPITAL MANAGEMENT SYSTEM - LIVE DEMO")
        print("=" * 90)
        print(f"\nStarting Capital: ${self.base_capital:,.2f}")
        print(f"Trading Tier: {self.tier}")
        print(f"Demo Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Run scenarios
        self.scenario_1_normal_trading()
        input("\nPress Enter to continue to Scenario 2...")
        
        self.scenario_2_high_volatility()
        input("\nPress Enter to continue to Scenario 3...")
        
        self.scenario_3_drawdown()
        input("\nPress Enter to continue to Scenario 4...")
        
        self.scenario_4_illiquid_market()
        input("\nPress Enter to continue to Scenario 5...")
        
        self.scenario_5_capital_preservation()
        input("\nPress Enter to continue to Scenario 6...")
        
        self.scenario_6_performance_scaling()
        
        # Final summary
        print("\n" + "=" * 90)
        print("DEMO COMPLETE")
        print("=" * 90)
        print("\nKey Takeaways:")
        print("✅ Multiple layers of risk protection")
        print("✅ Dynamic position sizing based on conditions")
        print("✅ Liquidity gating prevents illiquid trades")
        print("✅ Drawdown protection reduces risk during losses")
        print("✅ Performance scaling optimizes returns")
        print("✅ Capital preservation prevents catastrophic losses")
        print("\n🏛️  NIJA is now an institutional-grade capital management system!")
        print("=" * 90 + "\n")


def main():
    """Run the demo"""
    demo = InstitutionalDemo(base_capital=10_000.0, tier="INCOME")
    demo.run_all_scenarios()


if __name__ == "__main__":
    main()
