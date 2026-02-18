#!/usr/bin/env python3
"""
NIJA Prove Edge CLI Tool
========================

Command-line tool for operators to validate strategy edge BEFORE deploying capital.

Real funds sequence:
1. Prove edge (this tool)
2. Lock entry discipline  
3. Then activate capital scaling

Usage:
    # Validate edge from trade history
    python prove_edge.py --trades trade_history.csv
    
    # Validate with regime labels
    python prove_edge.py --trades trade_history.csv --regimes regime_labels.csv
    
    # Run quick simulation
    python prove_edge.py --simulate --num-trades 500
    
    # Generate HTML report
    python prove_edge.py --trades trade_history.csv --report edge_validation_report.html

Philosophy:
If Sharpe < 1 after realistic costs, you don't scale.

Author: NIJA Trading Systems
Version: 1.0
Date: February 18, 2026
"""

import argparse
import sys
import os
import logging
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Tuple

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

try:
    from alpha_validation_framework import AlphaValidationFramework, AlphaStatus
    from institutional_edge_validator import InstitutionalEdgeValidator, EdgeStatus, SlippageModel
except ImportError:
    print("ERROR: Could not import validation frameworks")
    print("Please ensure bot/alpha_validation_framework.py and bot/institutional_edge_validator.py exist")
    sys.exit(1)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("prove_edge")


def load_trade_history(filepath: str) -> Tuple[List[float], List[float], List[str]]:
    """
    Load trade history from CSV file
    
    Expected columns:
    - return_pct: Trade return as percentage (e.g., 2.5 for 2.5%)
    - pnl: Trade P&L in dollars
    - regime: Market regime (bull/bear/sideways)
    
    Returns:
        Tuple of (returns_list, pnls_list, regimes_list)
    """
    logger.info(f"Loading trade history from {filepath}...")
    
    df = pd.read_csv(filepath)
    
    # Validate required columns
    required = ['return_pct', 'pnl']
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")
    
    # Convert returns from percentage to decimal
    returns = (df['return_pct'] / 100.0).tolist()
    pnls = df['pnl'].tolist()
    
    # Get regimes if available
    if 'regime' in df.columns:
        regimes = df['regime'].tolist()
    else:
        logger.warning("No 'regime' column found, using 'sideways' for all trades")
        regimes = ['sideways'] * len(returns)
    
    logger.info(f"Loaded {len(returns)} trades")
    logger.info(f"Average return: {np.mean(returns) * 100:.2f}%")
    logger.info(f"Total P&L: ${np.sum(pnls):,.2f}")
    
    return returns, pnls, regimes


def simulate_trade_history(
    num_trades: int = 500,
    win_rate: float = 0.55,
    avg_win_pct: float = 2.5,
    avg_loss_pct: float = 1.5,
    initial_capital: float = 100000.0
) -> Tuple[List[float], List[float], List[str]]:
    """
    Simulate trade history for testing
    
    Args:
        num_trades: Number of trades to simulate
        win_rate: Win rate (0-1)
        avg_win_pct: Average winning trade %
        avg_loss_pct: Average losing trade %
        initial_capital: Initial capital for P&L calculation
        
    Returns:
        Tuple of (returns_list, pnls_list, regimes_list)
    """
    logger.info(f"Simulating {num_trades} trades...")
    logger.info(f"  Win rate: {win_rate:.1%}")
    logger.info(f"  Avg win: {avg_win_pct:.2f}%")
    logger.info(f"  Avg loss: {avg_loss_pct:.2f}%")
    
    returns = []
    pnls = []
    regimes = []
    
    capital = initial_capital
    
    # Regime distribution: 40% bull, 30% bear, 30% sideways
    regime_choices = ['bull'] * 40 + ['bear'] * 30 + ['sideways'] * 30
    
    for i in range(num_trades):
        # Determine if win or loss
        is_win = np.random.random() < win_rate
        
        if is_win:
            return_pct = np.random.normal(avg_win_pct, avg_win_pct * 0.3) / 100.0
        else:
            return_pct = -np.random.normal(avg_loss_pct, avg_loss_pct * 0.3) / 100.0
        
        # Calculate P&L (assume 10% of capital per trade)
        position_size = capital * 0.10
        pnl = position_size * return_pct
        
        # Update capital
        capital += pnl
        
        # Select regime
        regime = np.random.choice(regime_choices)
        
        returns.append(return_pct)
        pnls.append(pnl)
        regimes.append(regime)
    
    logger.info(f"Simulation complete:")
    logger.info(f"  Final capital: ${capital:,.2f}")
    logger.info(f"  Total return: {(capital/initial_capital - 1) * 100:.2f}%")
    
    return returns, pnls, regimes


def generate_html_report(
    alpha_result,
    edge_result,
    output_path: str
) -> None:
    """
    Generate HTML report of validation results
    
    Args:
        alpha_result: AlphaValidationResult
        edge_result: EdgeValidationResult  
        output_path: Path to save HTML report
    """
    logger.info(f"Generating HTML report: {output_path}...")
    
    html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>NIJA Edge Validation Report</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        h1 {{ color: #2c3e50; border-bottom: 3px solid #3498db; padding-bottom: 10px; }}
        h2 {{ color: #34495e; margin-top: 30px; }}
        .status {{ padding: 15px; border-radius: 5px; margin: 20px 0; font-weight: bold; }}
        .status.pass {{ background: #d4edda; color: #155724; border-left: 5px solid #28a745; }}
        .status.fail {{ background: #f8d7da; color: #721c24; border-left: 5px solid #dc3545; }}
        .metric {{ display: inline-block; width: 30%; margin: 10px 1%; padding: 15px; background: #f8f9fa; border-radius: 5px; }}
        .metric-label {{ font-size: 12px; color: #6c757d; text-transform: uppercase; }}
        .metric-value {{ font-size: 24px; font-weight: bold; color: #2c3e50; }}
        .step {{ margin: 20px 0; padding: 15px; background: #f8f9fa; border-radius: 5px; }}
        .step-header {{ font-weight: bold; margin-bottom: 10px; }}
        .pass-icon {{ color: #28a745; }}
        .fail-icon {{ color: #dc3545; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background: #f8f9fa; font-weight: bold; }}
        .footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #ddd; color: #6c757d; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🔬 NIJA Edge Validation Report</h1>
        <p><strong>Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        
        <div class="status {'pass' if alpha_result.ready_for_capital_scaling else 'fail'}">
            {'✅' if alpha_result.ready_for_capital_scaling else '❌'} 
            {alpha_result.validation_message}
        </div>
        
        <h2>📊 Key Metrics</h2>
        <div>
            <div class="metric">
                <div class="metric-label">Sharpe (After Costs)</div>
                <div class="metric-value">{alpha_result.statistical_validation.sharpe_after_costs:.3f}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Win Rate</div>
                <div class="metric-value">{alpha_result.alpha_discovery.win_rate:.1%}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Profit Factor</div>
                <div class="metric-value">{alpha_result.alpha_discovery.profit_factor:.2f}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Total Trades</div>
                <div class="metric-value">{alpha_result.alpha_discovery.total_trades}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Total Return</div>
                <div class="metric-value">{alpha_result.alpha_discovery.total_return * 100:.1f}%</div>
            </div>
            <div class="metric">
                <div class="metric-label">Max Drawdown</div>
                <div class="metric-value">{alpha_result.alpha_discovery.max_drawdown * 100:.1f}%</div>
            </div>
        </div>
        
        <h2>🎯 4-Step Validation</h2>
        
        <div class="step">
            <div class="step-header">
                <span class="{'pass-icon' if alpha_result.step1_passed else 'fail-icon'}">
                    {'✅' if alpha_result.step1_passed else '❌'}
                </span>
                Step 1: Alpha Discovery
            </div>
            <p>Does raw edge exist?</p>
            <ul>
                <li>Win Rate: {alpha_result.alpha_discovery.win_rate:.1%}</li>
                <li>Profit Factor: {alpha_result.alpha_discovery.profit_factor:.2f}</li>
                <li>Expectancy: ${alpha_result.alpha_discovery.expectancy:.2f}/trade</li>
            </ul>
        </div>
        
        <div class="step">
            <div class="step-header">
                <span class="{'pass-icon' if alpha_result.step2_passed else 'fail-icon'}">
                    {'✅' if alpha_result.step2_passed else '❌'}
                </span>
                Step 2: Statistical Validation
            </div>
            <p>Is it statistically significant after costs?</p>
            <ul>
                <li>Sharpe (raw): {alpha_result.statistical_validation.sharpe_raw:.3f}</li>
                <li>Sharpe (after costs): {alpha_result.statistical_validation.sharpe_after_costs:.3f}</li>
                <li>Sortino: {alpha_result.statistical_validation.sortino_ratio:.3f}</li>
                <li>p-value: {alpha_result.statistical_validation.p_value:.4f}</li>
                <li>Net Return: {alpha_result.statistical_validation.net_return_after_costs * 100:.1f}%</li>
            </ul>
        </div>
        
        <div class="step">
            <div class="step-header">
                <span class="{'pass-icon' if alpha_result.step3_passed else 'fail-icon'}">
                    {'✅' if alpha_result.step3_passed else '❌'}
                </span>
                Step 3: Regime Testing
            </div>
            <p>Does it work in all market conditions?</p>
            <table>
                <tr>
                    <th>Regime</th>
                    <th>Sharpe</th>
                    <th>Win Rate</th>
                    <th>Trades</th>
                </tr>
                <tr>
                    <td>Bull Market</td>
                    <td>{alpha_result.regime_testing.bull_sharpe:.2f}</td>
                    <td>{alpha_result.regime_testing.bull_win_rate:.1%}</td>
                    <td>{alpha_result.regime_testing.bull_trades}</td>
                </tr>
                <tr>
                    <td>Bear Market</td>
                    <td>{alpha_result.regime_testing.bear_sharpe:.2f}</td>
                    <td>{alpha_result.regime_testing.bear_win_rate:.1%}</td>
                    <td>{alpha_result.regime_testing.bear_trades}</td>
                </tr>
                <tr>
                    <td>Sideways Market</td>
                    <td>{alpha_result.regime_testing.sideways_sharpe:.2f}</td>
                    <td>{alpha_result.regime_testing.sideways_win_rate:.1%}</td>
                    <td>{alpha_result.regime_testing.sideways_trades}</td>
                </tr>
            </table>
        </div>
        
        <div class="step">
            <div class="step-header">
                <span class="{'pass-icon' if alpha_result.step4_passed else 'fail-icon'}">
                    {'✅' if alpha_result.step4_passed else '❌'}
                </span>
                Step 4: Monte Carlo Stress Testing
            </div>
            <p>Does it survive adverse scenarios?</p>
            <ul>
                <li>Probability of Ruin (&gt;50% loss): {alpha_result.monte_carlo_stress.probability_of_ruin:.2%}</li>
                <li>Probability of 10% Loss: {alpha_result.monte_carlo_stress.probability_of_10pct_loss:.2%}</li>
                <li>5th Percentile Return: {alpha_result.monte_carlo_stress.percentile_5:.1%}</li>
                <li>Median Return: {alpha_result.monte_carlo_stress.median_return:.1%}</li>
                <li>95th Percentile Return: {alpha_result.monte_carlo_stress.percentile_95:.1%}</li>
                <li>Worst Drawdown: {alpha_result.monte_carlo_stress.worst_drawdown:.1%}</li>
            </ul>
        </div>
        
        <h2>📋 Validation Criteria</h2>
        <table>
            <tr>
                <th>Criterion</th>
                <th>Requirement</th>
                <th>Status</th>
            </tr>
            <tr>
                <td>Sharpe Ratio (after costs)</td>
                <td>≥ 1.0</td>
                <td>{'✅' if alpha_result.statistical_validation.sharpe_after_costs >= 1.0 else '❌'} {alpha_result.statistical_validation.sharpe_after_costs:.3f}</td>
            </tr>
            <tr>
                <td>Statistical Significance</td>
                <td>p-value &lt; 0.05</td>
                <td>{'✅' if alpha_result.statistical_validation.p_value < 0.05 else '❌'} {alpha_result.statistical_validation.p_value:.4f}</td>
            </tr>
            <tr>
                <td>Regime Performance</td>
                <td>All regimes positive Sharpe</td>
                <td>{'✅' if alpha_result.step3_passed else '❌'}</td>
            </tr>
            <tr>
                <td>Probability of Ruin</td>
                <td>&lt; 5%</td>
                <td>{'✅' if alpha_result.monte_carlo_stress.probability_of_ruin < 0.05 else '❌'} {alpha_result.monte_carlo_stress.probability_of_ruin:.2%}</td>
            </tr>
        </table>
        
        <div class="footer">
            <p><strong>NIJA Trading Systems</strong> - Institutional Grade Trading Platform</p>
            <p>This report validates strategy edge before capital deployment.</p>
        </div>
    </div>
</body>
</html>
"""
    
    with open(output_path, 'w') as f:
        f.write(html)
    
    logger.info(f"✅ Report saved to {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description='Validate strategy edge before deploying capital',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate from trade history CSV
  python prove_edge.py --trades trade_history.csv
  
  # Generate HTML report
  python prove_edge.py --trades trade_history.csv --report report.html
  
  # Run simulation for testing
  python prove_edge.py --simulate --num-trades 500
  
  # Quick simulation with custom parameters
  python prove_edge.py --simulate --win-rate 0.60 --avg-win 3.0 --avg-loss 1.5
        """
    )
    
    # Input options
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        '--trades',
        type=str,
        help='Path to CSV file with trade history (columns: return_pct, pnl, regime)'
    )
    input_group.add_argument(
        '--simulate',
        action='store_true',
        help='Run simulation instead of loading real data'
    )
    
    # Simulation parameters
    parser.add_argument(
        '--num-trades',
        type=int,
        default=500,
        help='Number of trades to simulate (default: 500)'
    )
    parser.add_argument(
        '--win-rate',
        type=float,
        default=0.55,
        help='Win rate for simulation (default: 0.55)'
    )
    parser.add_argument(
        '--avg-win',
        type=float,
        default=2.5,
        help='Average win percentage for simulation (default: 2.5)'
    )
    parser.add_argument(
        '--avg-loss',
        type=float,
        default=1.5,
        help='Average loss percentage for simulation (default: 1.5)'
    )
    
    # Output options
    parser.add_argument(
        '--report',
        type=str,
        help='Generate HTML report at specified path'
    )
    parser.add_argument(
        '--initial-capital',
        type=float,
        default=100000.0,
        help='Initial capital for analysis (default: 100000)'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Load or simulate trade data
    if args.simulate:
        returns, pnls, regimes = simulate_trade_history(
            num_trades=args.num_trades,
            win_rate=args.win_rate,
            avg_win_pct=args.avg_win,
            avg_loss_pct=args.avg_loss,
            initial_capital=args.initial_capital
        )
    else:
        try:
            returns, pnls, regimes = load_trade_history(args.trades)
        except Exception as e:
            logger.error(f"Failed to load trade history: {e}")
            return 1
    
    # Run alpha validation
    logger.info("\n" + "=" * 80)
    logger.info("RUNNING 4-STEP ALPHA VALIDATION")
    logger.info("=" * 80)
    
    framework = AlphaValidationFramework()
    alpha_result = framework.validate_strategy(
        trade_returns=returns,
        trade_pnls=pnls,
        regime_labels=regimes,
        initial_capital=args.initial_capital
    )
    
    # Run edge validation (alternative framework)
    logger.info("\n" + "=" * 80)
    logger.info("RUNNING INSTITUTIONAL EDGE VALIDATION")
    logger.info("=" * 80)
    
    edge_validator = InstitutionalEdgeValidator()
    edge_result = edge_validator.validate_edge(
        returns=returns,
        regime_labels=regimes
    )
    
    # Generate HTML report if requested
    if args.report:
        try:
            generate_html_report(alpha_result, edge_result, args.report)
        except Exception as e:
            logger.error(f"Failed to generate report: {e}")
    
    # Final verdict
    print("\n" + "=" * 80)
    print("FINAL VERDICT")
    print("=" * 80)
    
    if alpha_result.ready_for_capital_scaling:
        print("✅ EDGE PROVEN - READY FOR CAPITAL SCALING")
        print("")
        print("All 4 validation steps passed:")
        print("  ✅ Step 1: Alpha Discovery")
        print("  ✅ Step 2: Statistical Validation")
        print("  ✅ Step 3: Regime Testing")
        print("  ✅ Step 4: Monte Carlo Stress")
        print("")
        print("You may now activate capital scaling architecture.")
        return 0
    else:
        print("❌ EDGE NOT PROVEN - DO NOT SCALE CAPITAL")
        print("")
        print("Failed validation steps:")
        if not alpha_result.step1_passed:
            print("  ❌ Step 1: Alpha Discovery - No raw alpha detected")
        if not alpha_result.step2_passed:
            print(f"  ❌ Step 2: Statistical Validation - Sharpe {alpha_result.statistical_validation.sharpe_after_costs:.2f} < 1.0")
        if not alpha_result.step3_passed:
            print(f"  ❌ Step 3: Regime Testing - Worst regime Sharpe {alpha_result.regime_testing.worst_regime_sharpe:.2f}")
        if not alpha_result.step4_passed:
            print(f"  ❌ Step 4: Monte Carlo Stress - Probability of ruin {alpha_result.monte_carlo_stress.probability_of_ruin:.2%}")
        print("")
        print("Fix strategy before deploying capital.")
        return 1


if __name__ == '__main__':
    sys.exit(main())
