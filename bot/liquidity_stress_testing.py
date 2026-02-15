"""
NIJA Capital Stress Testing under Liquidity Compression
=======================================================

Institutional-grade stress testing that simulates capital performance under
extreme liquidity conditions:

- Liquidity shocks (bid-ask spread widening)
- Order book depth compression
- Partial fill scenarios
- Delayed execution
- Market impact slippage
- Cascading liquidations

This validates strategy survivability during crisis conditions when
liquidity evaporates.

Author: NIJA Trading Systems
Version: 1.0
Date: February 15, 2026
"""

import logging
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path

logger = logging.getLogger("nija.liquidity_stress")


@dataclass
class LiquidityScenario:
    """Liquidity stress scenario parameters"""
    name: str = "Normal"
    description: str = ""
    
    # Spread parameters
    base_spread_bps: float = 10.0  # Base spread in basis points
    spread_multiplier: float = 1.0  # Multiply base spread by this
    
    # Slippage parameters
    base_slippage_bps: float = 5.0  # Base slippage
    slippage_multiplier: float = 1.0
    
    # Order book depth
    depth_reduction_pct: float = 0.0  # % reduction in available liquidity
    
    # Fill probability
    fill_probability: float = 1.0  # Probability of getting filled
    partial_fill_pct_mean: float = 1.0  # Average fill percentage when partial
    partial_fill_pct_std: float = 0.0  # Std dev of partial fills
    
    # Execution delay
    execution_delay_bars: int = 0  # Bars delayed in execution
    adverse_selection_pct: float = 0.0  # Price moves against during delay
    
    # Cascading effects
    liquidation_cascade_prob: float = 0.0  # Probability of cascade
    cascade_price_impact_pct: float = 0.0  # Price impact during cascade


# Predefined stress scenarios
LIQUIDITY_SCENARIOS = {
    'normal': LiquidityScenario(
        name="Normal Market",
        description="Standard market conditions with good liquidity",
        base_spread_bps=10.0,
        spread_multiplier=1.0,
        base_slippage_bps=5.0,
        slippage_multiplier=1.0,
        fill_probability=1.0,
        partial_fill_pct_mean=1.0
    ),
    
    'moderate_stress': LiquidityScenario(
        name="Moderate Stress",
        description="Elevated volatility, wider spreads",
        base_spread_bps=10.0,
        spread_multiplier=2.0,
        base_slippage_bps=5.0,
        slippage_multiplier=1.5,
        depth_reduction_pct=0.30,
        fill_probability=0.95,
        partial_fill_pct_mean=0.90,
        partial_fill_pct_std=0.10,
        execution_delay_bars=1,
        adverse_selection_pct=0.05
    ),
    
    'high_stress': LiquidityScenario(
        name="High Stress",
        description="Market panic, significant liquidity compression",
        base_spread_bps=10.0,
        spread_multiplier=5.0,
        base_slippage_bps=5.0,
        slippage_multiplier=3.0,
        depth_reduction_pct=0.60,
        fill_probability=0.85,
        partial_fill_pct_mean=0.70,
        partial_fill_pct_std=0.20,
        execution_delay_bars=2,
        adverse_selection_pct=0.15,
        liquidation_cascade_prob=0.10,
        cascade_price_impact_pct=2.0
    ),
    
    'extreme_crisis': LiquidityScenario(
        name="Extreme Crisis",
        description="Flash crash, liquidity vacuum, circuit breakers",
        base_spread_bps=10.0,
        spread_multiplier=10.0,
        base_slippage_bps=5.0,
        slippage_multiplier=5.0,
        depth_reduction_pct=0.90,
        fill_probability=0.60,
        partial_fill_pct_mean=0.40,
        partial_fill_pct_std=0.30,
        execution_delay_bars=5,
        adverse_selection_pct=0.30,
        liquidation_cascade_prob=0.30,
        cascade_price_impact_pct=5.0
    ),
    
    'liquidity_drought': LiquidityScenario(
        name="Liquidity Drought",
        description="Extended period of low liquidity (holidays, Asian hours)",
        base_spread_bps=10.0,
        spread_multiplier=3.0,
        base_slippage_bps=5.0,
        slippage_multiplier=2.0,
        depth_reduction_pct=0.70,
        fill_probability=0.90,
        partial_fill_pct_mean=0.75,
        partial_fill_pct_std=0.15,
        execution_delay_bars=3,
        adverse_selection_pct=0.10
    )
}


@dataclass
class StressTestResult:
    """Result from a single stress test scenario"""
    scenario_name: str
    scenario: LiquidityScenario
    
    # Performance metrics
    total_trades: int = 0
    successful_fills: int = 0
    partial_fills: int = 0
    failed_fills: int = 0
    fill_rate: float = 0.0
    
    # Cost metrics
    total_spread_cost_bps: float = 0.0
    total_slippage_cost_bps: float = 0.0
    total_execution_cost_bps: float = 0.0
    avg_cost_per_trade_bps: float = 0.0
    
    # Capital impact
    initial_capital: float = 0.0
    final_capital: float = 0.0
    total_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    
    # Liquidity events
    cascade_events: int = 0
    cascade_cost_bps: float = 0.0
    
    # Performance degradation
    ideal_return_pct: float = 0.0  # Return without liquidity constraints
    degradation_pct: float = 0.0  # Performance loss due to liquidity


@dataclass
class LiquidityStressTestReport:
    """Complete liquidity stress test report"""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # Test parameters
    num_trades: int = 0
    initial_capital: float = 0.0
    
    # Scenario results
    scenario_results: Dict[str, StressTestResult] = field(default_factory=dict)
    
    # Comparative analysis
    best_case_return: float = 0.0  # Normal scenario
    worst_case_return: float = 0.0  # Extreme crisis
    return_range_pct: float = 0.0  # Difference between best and worst
    
    # Risk metrics
    capital_at_risk_extreme: float = 0.0  # Capital loss in extreme scenario
    liquidity_resilience_score: float = 0.0  # 0-1, higher = more resilient
    
    # Recommendations
    warnings: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)


class LiquidityStressTestEngine:
    """
    Capital stress testing under liquidity compression
    
    Simulates strategy performance under various liquidity crisis scenarios
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize Liquidity Stress Test Engine
        
        Args:
            config: Configuration dictionary
        """
        self.config = config or {}
        
        # Load scenarios
        self.scenarios = LIQUIDITY_SCENARIOS.copy()
        
        # Add custom scenarios from config
        custom_scenarios = self.config.get('custom_scenarios', {})
        self.scenarios.update(custom_scenarios)
        
        logger.info("=" * 70)
        logger.info("💧 Liquidity Stress Test Engine Initialized")
        logger.info("=" * 70)
        logger.info(f"Available Scenarios: {len(self.scenarios)}")
        for name in self.scenarios.keys():
            logger.info(f"   • {name}")
        logger.info("=" * 70)
    
    def simulate_trade_execution(
        self,
        ideal_entry_price: float,
        ideal_exit_price: float,
        position_size_pct: float,
        capital: float,
        scenario: LiquidityScenario
    ) -> Tuple[float, float, float, bool, bool]:
        """
        Simulate trade execution under liquidity scenario
        
        Args:
            ideal_entry_price: Ideal entry price
            ideal_exit_price: Ideal exit price
            position_size_pct: Position size as % of capital
            capital: Available capital
            scenario: Liquidity scenario
        
        Returns:
            Tuple of (actual_entry, actual_exit, fill_pct, was_filled, cascade_occurred)
        """
        # Check if we get filled at all
        was_filled = np.random.random() < scenario.fill_probability
        
        if not was_filled:
            return 0.0, 0.0, 0.0, False, False
        
        # Determine fill percentage
        if scenario.fill_probability < 1.0:
            # Potential partial fill
            fill_pct = np.random.normal(
                scenario.partial_fill_pct_mean,
                scenario.partial_fill_pct_std
            )
            fill_pct = max(0.1, min(1.0, fill_pct))  # Constrain to 10-100%
        else:
            fill_pct = 1.0
        
        # Calculate spread cost
        spread_bps = scenario.base_spread_bps * scenario.spread_multiplier
        spread_cost_pct = spread_bps / 10000
        
        # Calculate slippage
        slippage_bps = scenario.base_slippage_bps * scenario.slippage_multiplier
        slippage_cost_pct = slippage_bps / 10000
        
        # Execution delay adverse selection
        delay_cost_pct = scenario.adverse_selection_pct if scenario.execution_delay_bars > 0 else 0.0
        
        # Check for liquidation cascade
        cascade_occurred = np.random.random() < scenario.liquidation_cascade_prob
        cascade_cost_pct = scenario.cascade_price_impact_pct / 100 if cascade_occurred else 0.0
        
        # Total entry cost
        total_entry_cost_pct = spread_cost_pct + slippage_cost_pct + delay_cost_pct + cascade_cost_pct
        
        # Actual entry price (worse than ideal)
        direction = 1 if ideal_exit_price > ideal_entry_price else -1
        actual_entry = ideal_entry_price * (1 + direction * total_entry_cost_pct)
        
        # Exit costs (similar but potentially different due to market conditions)
        exit_spread_cost_pct = spread_cost_pct
        exit_slippage_cost_pct = slippage_cost_pct * 0.8  # Slightly better on exit
        total_exit_cost_pct = exit_spread_cost_pct + exit_slippage_cost_pct
        
        # Actual exit price (worse than ideal)
        actual_exit = ideal_exit_price * (1 - direction * total_exit_cost_pct)
        
        return actual_entry, actual_exit, fill_pct, True, cascade_occurred
    
    def run_scenario_test(
        self,
        scenario_name: str,
        trades: List[Dict],
        initial_capital: float = 100000.0
    ) -> StressTestResult:
        """
        Run stress test for a specific scenario
        
        Args:
            scenario_name: Name of scenario to test
            trades: List of ideal trades (dict with entry, exit, position_pct)
            initial_capital: Starting capital
        
        Returns:
            StressTestResult
        """
        scenario = self.scenarios[scenario_name]
        
        logger.info(f"\n🧪 Testing scenario: {scenario.name}")
        logger.info(f"   {scenario.description}")
        
        capital = initial_capital
        peak_capital = capital
        max_drawdown = 0.0
        
        # Tracking metrics
        total_trades = len(trades)
        successful_fills = 0
        partial_fills = 0
        failed_fills = 0
        
        total_spread_cost = 0.0
        total_slippage_cost = 0.0
        total_execution_cost = 0.0
        
        cascade_events = 0
        cascade_cost = 0.0
        
        ideal_capital = initial_capital
        
        for trade in trades:
            ideal_entry = trade['entry_price']
            ideal_exit = trade['exit_price']
            position_pct = trade['position_size_pct']
            
            # Calculate ideal return
            ideal_return_pct = ((ideal_exit - ideal_entry) / ideal_entry) * 100
            ideal_pnl = ideal_capital * position_pct * (ideal_return_pct / 100)
            ideal_capital += ideal_pnl
            
            # Simulate actual execution
            actual_entry, actual_exit, fill_pct, was_filled, cascade = self.simulate_trade_execution(
                ideal_entry, ideal_exit, position_pct, capital, scenario
            )
            
            if not was_filled:
                failed_fills += 1
                continue
            
            if fill_pct < 1.0:
                partial_fills += 1
            else:
                successful_fills += 1
            
            # Calculate actual return with liquidity costs
            if actual_entry > 0:
                actual_return_pct = ((actual_exit - actual_entry) / actual_entry) * 100
                
                # Adjust position size by fill percentage
                adjusted_position_pct = position_pct * fill_pct
                
                actual_pnl = capital * adjusted_position_pct * (actual_return_pct / 100)
                capital += actual_pnl
                
                # Track costs
                spread_cost_bps = scenario.base_spread_bps * scenario.spread_multiplier
                slippage_cost_bps = scenario.base_slippage_bps * scenario.slippage_multiplier
                
                total_spread_cost += spread_cost_bps
                total_slippage_cost += slippage_cost_bps
                total_execution_cost += spread_cost_bps + slippage_cost_bps
                
                if cascade:
                    cascade_events += 1
                    cascade_cost += scenario.cascade_price_impact_pct
            
            # Track drawdown
            if capital > peak_capital:
                peak_capital = capital
            
            drawdown = (peak_capital - capital) / peak_capital * 100
            max_drawdown = max(max_drawdown, drawdown)
        
        # Calculate summary metrics
        fills = successful_fills + partial_fills
        fill_rate = fills / total_trades if total_trades > 0 else 0.0
        
        avg_cost_per_trade = total_execution_cost / fills if fills > 0 else 0.0
        
        total_return = ((capital - initial_capital) / initial_capital) * 100
        ideal_return = ((ideal_capital - initial_capital) / initial_capital) * 100
        degradation = ideal_return - total_return
        
        result = StressTestResult(
            scenario_name=scenario.name,
            scenario=scenario,
            total_trades=total_trades,
            successful_fills=successful_fills,
            partial_fills=partial_fills,
            failed_fills=failed_fills,
            fill_rate=fill_rate,
            total_spread_cost_bps=total_spread_cost,
            total_slippage_cost_bps=total_slippage_cost,
            total_execution_cost_bps=total_execution_cost,
            avg_cost_per_trade_bps=avg_cost_per_trade,
            initial_capital=initial_capital,
            final_capital=capital,
            total_return_pct=total_return,
            max_drawdown_pct=max_drawdown,
            cascade_events=cascade_events,
            cascade_cost_bps=cascade_cost,
            ideal_return_pct=ideal_return,
            degradation_pct=degradation
        )
        
        logger.info(f"   Fill Rate: {fill_rate*100:.1f}%")
        logger.info(f"   Total Return: {total_return:+.2f}% (ideal: {ideal_return:+.2f}%)")
        logger.info(f"   Degradation: {degradation:.2f}%")
        logger.info(f"   Avg Cost: {avg_cost_per_trade:.1f} bps/trade")
        
        return result
    
    def run_stress_test(
        self,
        trades: List[Dict],
        initial_capital: float = 100000.0,
        scenarios: Optional[List[str]] = None
    ) -> LiquidityStressTestReport:
        """
        Run comprehensive stress test across scenarios
        
        Args:
            trades: List of ideal trades
            initial_capital: Starting capital
            scenarios: List of scenario names (None = all scenarios)
        
        Returns:
            LiquidityStressTestReport
        """
        logger.info("\n" + "=" * 70)
        logger.info("💧 LIQUIDITY STRESS TEST")
        logger.info("=" * 70)
        logger.info(f"Trades to simulate: {len(trades)}")
        logger.info(f"Initial capital: ${initial_capital:,.2f}")
        
        # Determine which scenarios to test
        if scenarios is None:
            scenarios = list(self.scenarios.keys())
        
        # Run tests
        scenario_results = {}
        
        for scenario_name in scenarios:
            result = self.run_scenario_test(scenario_name, trades, initial_capital)
            scenario_results[scenario_name] = result
        
        # Analyze results
        returns = [r.total_return_pct for r in scenario_results.values()]
        best_case = max(returns) if returns else 0.0
        worst_case = min(returns) if returns else 0.0
        return_range = best_case - worst_case
        
        # Capital at risk
        worst_result = min(scenario_results.values(), key=lambda x: x.total_return_pct)
        capital_at_risk = initial_capital - worst_result.final_capital
        
        # Resilience score (based on how well strategy performs under stress)
        # Higher score = less degradation under stress
        degradations = [r.degradation_pct for r in scenario_results.values()]
        avg_degradation = np.mean(degradations) if degradations else 0.0
        
        # Score: 1.0 = no degradation, 0.0 = complete failure
        resilience_score = max(0.0, min(1.0, 1.0 - (avg_degradation / 50.0)))  # Normalize to 50% max degradation, cap at 1.0
        
        # Build report
        report = LiquidityStressTestReport(
            num_trades=len(trades),
            initial_capital=initial_capital,
            scenario_results=scenario_results,
            best_case_return=best_case,
            worst_case_return=worst_case,
            return_range_pct=return_range,
            capital_at_risk_extreme=capital_at_risk,
            liquidity_resilience_score=resilience_score
        )
        
        # Generate warnings and recommendations
        report.warnings, report.recommendations = self._generate_warnings_and_recommendations(report)
        
        # Log report
        self._log_report(report)
        
        return report
    
    def _generate_warnings_and_recommendations(
        self,
        report: LiquidityStressTestReport
    ) -> Tuple[List[str], List[str]]:
        """Generate warnings and recommendations"""
        warnings = []
        recommendations = []
        
        # Check resilience score
        if report.liquidity_resilience_score < 0.50:
            warnings.append(f"⚠️ LOW liquidity resilience: {report.liquidity_resilience_score:.2f}")
            recommendations.append("Reduce position sizes during low liquidity periods")
            recommendations.append("Implement stricter liquidity filters")
        elif report.liquidity_resilience_score < 0.75:
            warnings.append(f"⚠️ MODERATE liquidity resilience: {report.liquidity_resilience_score:.2f}")
            recommendations.append("Monitor liquidity conditions closely")
        
        # Check capital at risk
        risk_pct = (report.capital_at_risk_extreme / report.initial_capital) * 100
        if risk_pct > 30:
            warnings.append(f"🚨 HIGH capital at risk: {risk_pct:.1f}% in extreme scenario")
            recommendations.append("Consider liquidity-aware position sizing")
            recommendations.append("Implement crisis exit protocols")
        elif risk_pct > 15:
            warnings.append(f"⚠️ Moderate capital at risk: {risk_pct:.1f}% in extreme scenario")
        
        # Check return range
        if report.return_range_pct > 50:
            warnings.append(f"⚠️ High return variance: {report.return_range_pct:.1f}% between best/worst")
            recommendations.append("Strategy highly sensitive to liquidity conditions")
        
        # Check extreme scenario
        if 'extreme_crisis' in report.scenario_results:
            extreme = report.scenario_results['extreme_crisis']
            if extreme.fill_rate < 0.70:
                warnings.append(f"⚠️ Poor fill rate in crisis: {extreme.fill_rate*100:.1f}%")
                recommendations.append("Diversify across multiple exchanges/liquidity sources")
        
        return warnings, recommendations
    
    def _log_report(self, report: LiquidityStressTestReport) -> None:
        """Log stress test report"""
        logger.info("\n" + "=" * 70)
        logger.info("📊 LIQUIDITY STRESS TEST REPORT")
        logger.info("=" * 70)
        
        logger.info(f"\n💰 Capital Analysis:")
        logger.info(f"   Initial Capital: ${report.initial_capital:,.2f}")
        logger.info(f"   Best Case Return: {report.best_case_return:+.2f}%")
        logger.info(f"   Worst Case Return: {report.worst_case_return:+.2f}%")
        logger.info(f"   Return Range: {report.return_range_pct:.2f}%")
        logger.info(f"   Capital at Risk (Extreme): ${report.capital_at_risk_extreme:,.2f}")
        
        logger.info(f"\n🛡️  Liquidity Resilience:")
        logger.info(f"   Resilience Score: {report.liquidity_resilience_score:.2f}/1.00")
        
        logger.info(f"\n📊 Scenario Results:")
        for name, result in report.scenario_results.items():
            logger.info(f"\n   {result.scenario_name}:")
            logger.info(f"      Fill Rate: {result.fill_rate*100:.1f}%")
            logger.info(f"      Final Capital: ${result.final_capital:,.2f}")
            logger.info(f"      Total Return: {result.total_return_pct:+.2f}%")
            logger.info(f"      Max Drawdown: {result.max_drawdown_pct:.2f}%")
            logger.info(f"      Avg Cost/Trade: {result.avg_cost_per_trade_bps:.1f} bps")
            logger.info(f"      Degradation: {result.degradation_pct:.2f}%")
            if result.cascade_events > 0:
                logger.info(f"      Cascade Events: {result.cascade_events}")
        
        if report.warnings:
            logger.info("\n⚠️  WARNINGS:")
            for warning in report.warnings:
                logger.info(f"   {warning}")
        
        if report.recommendations:
            logger.info("\n💡 RECOMMENDATIONS:")
            for rec in report.recommendations:
                logger.info(f"   {rec}")
        
        logger.info("=" * 70)
    
    def export_report(
        self,
        report: LiquidityStressTestReport,
        output_dir: str = "./data/liquidity_stress"
    ) -> str:
        """
        Export report to JSON
        
        Args:
            report: LiquidityStressTestReport
            output_dir: Output directory
        
        Returns:
            Path to exported file
        """
        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True, parents=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"liquidity_stress_test_{timestamp}.json"
        filepath = output_path / filename
        
        # Prepare export data
        export_data = {
            'timestamp': report.timestamp,
            'summary': {
                'num_trades': report.num_trades,
                'initial_capital': report.initial_capital,
                'best_case_return': report.best_case_return,
                'worst_case_return': report.worst_case_return,
                'capital_at_risk': report.capital_at_risk_extreme,
                'resilience_score': report.liquidity_resilience_score
            },
            'scenarios': {
                name: {
                    'fill_rate': result.fill_rate,
                    'total_return_pct': result.total_return_pct,
                    'degradation_pct': result.degradation_pct,
                    'max_drawdown_pct': result.max_drawdown_pct
                }
                for name, result in report.scenario_results.items()
            },
            'warnings': report.warnings,
            'recommendations': report.recommendations
        }
        
        with open(filepath, 'w') as f:
            json.dump(export_data, f, indent=2)
        
        logger.info(f"📄 Report exported to: {filepath}")
        
        return str(filepath)


def run_liquidity_stress_test(
    trades: List[Dict],
    initial_capital: float = 100000.0
) -> LiquidityStressTestReport:
    """
    Convenience function to run liquidity stress test
    
    Args:
        trades: List of ideal trades
        initial_capital: Starting capital
    
    Returns:
        LiquidityStressTestReport
    """
    engine = LiquidityStressTestEngine()
    report = engine.run_stress_test(trades, initial_capital)
    engine.export_report(report)
    
    return report


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
    
    # Generate sample trades
    np.random.seed(42)
    
    trades = []
    base_price = 100.0
    
    for i in range(100):
        # Random entry/exit with positive expectancy
        entry = base_price * (1 + np.random.normal(0, 0.02))
        direction = 1 if np.random.random() > 0.45 else -1  # 55% win rate
        
        if direction > 0:
            exit_price = entry * (1 + np.random.uniform(0.01, 0.03))  # 1-3% win
        else:
            exit_price = entry * (1 - np.random.uniform(0.005, 0.015))  # 0.5-1.5% loss
        
        trades.append({
            'entry_price': entry,
            'exit_price': exit_price,
            'position_size_pct': 0.02  # 2% position
        })
        
        base_price = exit_price
    
    print("\n" + "=" * 70)
    print("EXAMPLE: Liquidity Stress Testing")
    print("=" * 70)
    
    report = run_liquidity_stress_test(trades, initial_capital=100000.0)
