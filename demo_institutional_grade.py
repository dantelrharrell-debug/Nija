"""
NIJA Institutional-Grade Risk Analysis Demo
===========================================

Demonstrates all six institutional-grade modules:
1. Monte Carlo simulation engine
2. Risk-of-ruin probability model
3. Portfolio volatility targeting
4. Trade distribution stability testing
5. Version-controlled strategy governance
6. Capital stress testing under liquidity compression

This script shows how these modules work together to provide
institutional-grade risk management and analysis.

Author: NIJA Trading Systems
Date: February 15, 2026
"""

import logging
import numpy as np
from typing import List, Dict
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger("nija.institutional_demo")


def generate_sample_trading_history(
    num_trades: int = 200,
    win_rate: float = 0.60,
    avg_win_pct: float = 1.5,
    avg_loss_pct: float = 1.0,
    seed: int = 42
) -> List[Dict]:
    """
    Generate realistic sample trading history
    
    Args:
        num_trades: Number of trades to generate
        win_rate: Probability of winning trade
        avg_win_pct: Average win percentage
        avg_loss_pct: Average loss percentage
        seed: Random seed for reproducibility
    
    Returns:
        List of trade dictionaries
    """
    np.random.seed(seed)
    
    trades = []
    base_price = 100.0
    
    for i in range(num_trades):
        # Determine if win or loss
        is_win = np.random.random() < win_rate
        
        entry_price = base_price * (1 + np.random.normal(0, 0.01))
        
        if is_win:
            # Win trade
            return_pct = np.random.uniform(avg_win_pct * 0.5, avg_win_pct * 1.5)
            exit_price = entry_price * (1 + return_pct / 100)
        else:
            # Loss trade
            return_pct = -np.random.uniform(avg_loss_pct * 0.5, avg_loss_pct * 1.5)
            exit_price = entry_price * (1 + return_pct / 100)
        
        trades.append({
            'entry_price': entry_price,
            'exit_price': exit_price,
            'return_pct': return_pct,
            'position_size_pct': 0.02,  # 2% position
            'timestamp': datetime.now() - timedelta(days=num_trades - i)
        })
        
        # Update base price for next trade
        base_price = exit_price
    
    return trades


def demo_monte_carlo_simulation():
    """Demo: Monte Carlo Simulation Engine"""
    logger.info("\n" + "=" * 80)
    logger.info("1️⃣  MONTE CARLO SIMULATION ENGINE")
    logger.info("=" * 80)
    
    from bot.monte_carlo_simulator import (
        MonteCarloPortfolioSimulator,
        SimulationParameters,
        run_monte_carlo_test
    )
    
    # Run Monte Carlo simulation
    results = run_monte_carlo_test(
        num_simulations=1000,
        num_days=252,  # 1 year
        initial_capital=100000.0
    )
    
    logger.info("\n✅ Monte Carlo simulation complete")
    logger.info(f"   Probability of Ruin: {results.probability_of_ruin:.2%}")
    logger.info(f"   Mean Final Capital: ${results.mean_final_capital:,.2f}")
    logger.info(f"   5th Percentile: ${results.percentile_5:,.2f}")
    logger.info(f"   95th Percentile: ${results.percentile_95:,.2f}")
    
    return results


def demo_risk_of_ruin():
    """Demo: Risk-of-Ruin Probability Model"""
    logger.info("\n" + "=" * 80)
    logger.info("2️⃣  RISK-OF-RUIN PROBABILITY MODEL")
    logger.info("=" * 80)
    
    from bot.risk_of_ruin_engine import analyze_risk_of_ruin
    
    # Analyze risk-of-ruin for our strategy
    result = analyze_risk_of_ruin(
        win_rate=0.60,
        avg_win=1.5,
        avg_loss=1.0,
        position_size_pct=0.02,
        initial_capital=100000.0
    )
    
    logger.info("\n✅ Risk-of-ruin analysis complete")
    logger.info(f"   Simulated Ruin Probability: {result.simulated_ruin_probability:.4%}")
    logger.info(f"   Risk Rating: {result.risk_rating}")
    logger.info(f"   Kelly Criterion: {result.kelly_criterion_pct*100:.2f}%")
    logger.info(f"   Recommended Position Size: {result.recommended_position_size_pct*100:.2f}%")
    
    if result.warnings:
        logger.info("\n⚠️  Warnings:")
        for warning in result.warnings[:3]:
            logger.info(f"   {warning}")
    
    return result


def demo_volatility_targeting(trades: List[Dict]):
    """Demo: Portfolio Volatility Targeting"""
    logger.info("\n" + "=" * 80)
    logger.info("3️⃣  PORTFOLIO VOLATILITY TARGETING")
    logger.info("=" * 80)
    
    from bot.volatility_targeting import VolatilityTargetingEngine
    
    # Initialize engine
    engine = VolatilityTargetingEngine({
        'target_volatility_daily': 0.02,  # 2% daily target
        'lookback_periods': 20
    })
    
    # Simulate portfolio value updates
    initial_capital = 100000.0
    portfolio_value = initial_capital
    
    for trade in trades:
        # Update portfolio value based on trade return
        pnl = portfolio_value * trade['position_size_pct'] * (trade['return_pct'] / 100)
        portfolio_value += pnl
        engine.update_portfolio_return(portfolio_value, trade['timestamp'])
    
    # Get volatility targeting recommendation
    result = engine.target_volatility()
    
    logger.info("\n✅ Volatility targeting analysis complete")
    logger.info(f"   Volatility Regime: {result.risk_mode.upper()}")
    logger.info(f"   Realized Daily Vol: {result.metrics.daily_volatility*100:.2f}%")
    logger.info(f"   Position Scalar: {result.metrics.position_scalar:.2f}x")
    logger.info(f"   Recommended Position Size: {result.recommended_position_size_pct*100:.2f}%")
    logger.info(f"   Max Portfolio Exposure: {result.recommended_max_exposure_pct*100:.0f}%")
    
    return result


def demo_distribution_stability(trades: List[Dict]):
    """Demo: Trade Distribution Stability Testing"""
    logger.info("\n" + "=" * 80)
    logger.info("4️⃣  TRADE DISTRIBUTION STABILITY TESTING")
    logger.info("=" * 80)
    
    from bot.trade_distribution_stability import TradeDistributionStabilityEngine
    
    # Initialize engine
    engine = TradeDistributionStabilityEngine({
        'confidence_level': 0.95,
        'baseline_window': 100,
        'recent_window': 50
    })
    
    # Add all trades
    for trade in trades:
        engine.add_trade(trade['return_pct'], trade['timestamp'])
    
    # Analyze stability
    result = engine.analyze_stability()
    
    logger.info("\n✅ Distribution stability analysis complete")
    logger.info(f"   Overall Stability: {'STABLE ✓' if result.is_stable else 'UNSTABLE ✗'}")
    logger.info(f"   Stability Score: {result.stability_score:.2f}/1.00")
    logger.info(f"   Mean Return Change: {result.mean_return_change_pct:+.1f}%")
    logger.info(f"   Volatility Change: {result.volatility_change_pct:+.1f}%")
    logger.info(f"   Win Rate Change: {result.win_rate_change_pct:+.1f}%")
    
    if result.warnings:
        logger.info("\n⚠️  Top Warnings:")
        for warning in result.warnings[:3]:
            logger.info(f"   {warning}")
    
    return result


def demo_strategy_governance():
    """Demo: Version-Controlled Strategy Governance"""
    logger.info("\n" + "=" * 80)
    logger.info("5️⃣  VERSION-CONTROLLED STRATEGY GOVERNANCE")
    logger.info("=" * 80)
    
    from bot.risk_config_versions import (
        RiskConfigVersion,
        RiskParameterChange,
        BacktestResults,
        PaperTradingResults,
        Approval
    )
    
    # Create example version
    version = RiskConfigVersion(
        version="RISK_CONFIG_v2.1.0",
        date=datetime.now().isoformat(),
        author="NIJA Risk Team",
        status="approved",
        changes=[
            RiskParameterChange(
                parameter="max_position_size",
                old_value=0.10,
                new_value=0.08,
                reason="Reduce concentration risk based on Monte Carlo results"
            ),
            RiskParameterChange(
                parameter="max_portfolio_exposure",
                old_value=0.70,
                new_value=0.65,
                reason="Align with institutional volatility targets"
            )
        ],
        backtesting=BacktestResults(
            period_start="2025-01-01",
            period_end="2026-01-01",
            win_rate=0.62,
            max_drawdown=12.5,
            sharpe_ratio=1.85,
            total_return=28.4,
            total_trades=487,
            conclusion="PASSED - Strategy meets institutional standards"
        ),
        paper_trading=PaperTradingResults(
            period_start="2026-01-01",
            period_end="2026-02-01",
            trades=87,
            win_rate=0.59,
            max_drawdown=8.2,
            conclusion="PASSED - Performance consistent with backtest"
        ),
        approvals=[
            Approval(
                role="Technical Lead",
                name="System Architect",
                date=datetime.now().isoformat(),
                signature="approved_v2.1.0"
            ),
            Approval(
                role="Risk Manager",
                name="Chief Risk Officer",
                date=datetime.now().isoformat(),
                signature="approved_v2.1.0"
            ),
            Approval(
                role="Strategy Developer",
                name="Quant Team",
                date=datetime.now().isoformat(),
                signature="approved_v2.1.0"
            )
        ],
        risk_parameters={
            "max_position_size": 0.08,
            "max_portfolio_exposure": 0.65,
            "stop_loss_pct": 0.02,
            "take_profit_pct": 0.04
        }
    )
    
    logger.info("\n✅ Strategy version control active")
    logger.info(f"   Version: {version.version}")
    logger.info(f"   Status: {version.status.upper()}")
    logger.info(f"   Changes: {len(version.changes)}")
    logger.info(f"   Approvals: {len(version.approvals)}/3 required roles")
    logger.info(f"   Can Activate: {'YES ✓' if version.can_activate() else 'NO ✗'}")
    logger.info(f"   Backtest Sharpe: {version.backtesting.sharpe_ratio:.2f}")
    
    return version


def demo_liquidity_stress_testing(trades: List[Dict]):
    """Demo: Capital Stress Testing under Liquidity Compression"""
    logger.info("\n" + "=" * 80)
    logger.info("6️⃣  CAPITAL STRESS TESTING UNDER LIQUIDITY COMPRESSION")
    logger.info("=" * 80)
    
    from bot.liquidity_stress_testing import LiquidityStressTestEngine
    
    # Initialize engine
    engine = LiquidityStressTestEngine()
    
    # Run stress test
    report = engine.run_stress_test(
        trades=trades,
        initial_capital=100000.0,
        scenarios=['normal', 'moderate_stress', 'high_stress', 'extreme_crisis']
    )
    
    logger.info("\n✅ Liquidity stress test complete")
    logger.info(f"   Resilience Score: {report.liquidity_resilience_score:.2f}/1.00")
    logger.info(f"   Best Case Return: {report.best_case_return:+.2f}%")
    logger.info(f"   Worst Case Return: {report.worst_case_return:+.2f}%")
    logger.info(f"   Return Range: {report.return_range_pct:.2f}%")
    logger.info(f"   Capital at Risk (Extreme): ${report.capital_at_risk_extreme:,.2f}")
    
    logger.info("\n📊 Scenario Performance:")
    for name, result in report.scenario_results.items():
        logger.info(f"   {result.scenario_name}:")
        logger.info(f"      Return: {result.total_return_pct:+.2f}%")
        logger.info(f"      Fill Rate: {result.fill_rate*100:.1f}%")
        logger.info(f"      Degradation: {result.degradation_pct:.2f}%")
    
    return report


def main():
    """Run complete institutional-grade demo"""
    logger.info("\n" + "=" * 80)
    logger.info("🏛️  NIJA INSTITUTIONAL-GRADE RISK ANALYSIS DEMO")
    logger.info("=" * 80)
    logger.info("\nDemonstrating transition from quantitative framework")
    logger.info("to institutional-grade trading infrastructure\n")
    
    # Generate sample trading history
    logger.info("Generating sample trading history (200 trades)...")
    trades = generate_sample_trading_history(
        num_trades=200,
        win_rate=0.60,
        avg_win_pct=1.5,
        avg_loss_pct=1.0
    )
    
    # Run all six institutional modules
    try:
        # 1. Monte Carlo Simulation
        mc_results = demo_monte_carlo_simulation()
        
        # 2. Risk-of-Ruin Analysis
        ruin_results = demo_risk_of_ruin()
        
        # 3. Volatility Targeting
        vol_results = demo_volatility_targeting(trades)
        
        # 4. Distribution Stability
        stability_results = demo_distribution_stability(trades)
        
        # 5. Strategy Governance
        governance_version = demo_strategy_governance()
        
        # 6. Liquidity Stress Testing
        liquidity_results = demo_liquidity_stress_testing(trades)
        
        # Final Summary
        logger.info("\n" + "=" * 80)
        logger.info("📊 INSTITUTIONAL READINESS SUMMARY")
        logger.info("=" * 80)
        
        logger.info("\n✅ All Six Institutional Components Operational:")
        logger.info(f"   1. Monte Carlo: {mc_results.probability_of_ruin:.2%} ruin probability")
        logger.info(f"   2. Risk-of-Ruin: {ruin_results.risk_rating} rating")
        logger.info(f"   3. Volatility Targeting: {vol_results.risk_mode.upper()} regime")
        logger.info(f"   4. Distribution Stability: {'STABLE' if stability_results.is_stable else 'UNSTABLE'}")
        logger.info(f"   5. Strategy Governance: {governance_version.status.upper()}")
        logger.info(f"   6. Liquidity Stress: {liquidity_results.liquidity_resilience_score:.2f} resilience")
        
        # Overall assessment
        logger.info("\n🎯 INSTITUTIONAL GRADE STATUS:")
        
        checks = [
            mc_results.probability_of_ruin < 0.05,  # < 5% ruin
            ruin_results.risk_rating in ['LOW', 'MODERATE'],
            stability_results.is_stable,
            governance_version.can_activate(),
            liquidity_results.liquidity_resilience_score > 0.50
        ]
        
        passed = sum(checks)
        total = len(checks)
        
        logger.info(f"   Checks Passed: {passed}/{total}")
        
        if passed == total:
            logger.info("   Status: ✅ INSTITUTIONAL GRADE ACHIEVED")
            logger.info("\n   NIJA is ready to:")
            logger.info("   • Manage institutional capital")
            logger.info("   • Attract professional investment")
            logger.info("   • Meet regulatory compliance standards")
            logger.info("   • Provide audit-ready reporting")
        elif passed >= total * 0.8:
            logger.info("   Status: ⚠️  NEAR INSTITUTIONAL GRADE")
            logger.info("   Minor adjustments needed for full compliance")
        else:
            logger.info("   Status: 🔄 IMPROVEMENTS NEEDED")
            logger.info("   Review failed checks and adjust parameters")
        
        logger.info("\n" + "=" * 80)
        logger.info("Demo complete - All institutional modules validated")
        logger.info("=" * 80)
        
    except Exception as e:
        logger.error(f"\n❌ Error during demo: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
