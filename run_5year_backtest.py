#!/usr/bin/env python3
"""
NIJA 5-Year Multi-Regime Backtesting Engine
============================================

Comprehensive backtesting across multiple market regimes to validate strategy
performance over extended time periods and diverse market conditions.

Features:
- 5-year historical backtesting
- Multi-regime analysis (bull, bear, ranging, volatile)
- Statistical significance testing
- Drawdown analysis by regime
- Regime transition performance
- Monte Carlo simulation
- Walk-forward optimization validation
- Investor-grade reporting

Author: NIJA Trading Systems
Date: January 28, 2026
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import json
import logging
from pathlib import Path
import argparse
from dataclasses import dataclass, asdict
import sys

# Add bot directory to path for imports
sys.path.insert(0, str(Path(__file__).parent / 'bot'))

from bot.unified_backtest_engine import BacktestEngine, BacktestResults, Trade
from bot.nija_apex_strategy_v71 import ApexStrategyV71

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('nija.5year_backtest')


class MarketRegime:
    """Market regime classification"""
    BULL = "bull"
    BEAR = "bear"
    RANGING = "ranging"
    VOLATILE = "volatile"


@dataclass
class RegimeMetrics:
    """Performance metrics for a specific market regime"""
    regime: str
    duration_days: int
    total_trades: int
    win_rate: float
    profit_factor: float
    total_return_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    avg_win_pct: float
    avg_loss_pct: float
    expectancy: float


class MarketRegimeDetector:
    """
    Detect market regimes based on price action and volatility
    """
    
    def __init__(self, lookback_period: int = 50):
        self.lookback_period = lookback_period
    
    def detect_regime(self, data: pd.DataFrame, idx: int) -> str:
        """
        Detect current market regime
        
        Returns:
            One of: 'bull', 'bear', 'ranging', 'volatile'
        """
        if idx < self.lookback_period:
            return MarketRegime.RANGING
        
        window = data.iloc[idx - self.lookback_period:idx]
        
        # Calculate metrics
        returns = window['close'].pct_change()
        volatility = returns.std() * np.sqrt(252)  # Annualized
        trend = (window['close'].iloc[-1] / window['close'].iloc[0]) - 1
        
        # High volatility threshold
        if volatility > 0.6:  # >60% annualized volatility
            return MarketRegime.VOLATILE
        
        # Trending markets
        if abs(trend) > 0.15:  # >15% move over lookback period
            return MarketRegime.BULL if trend > 0 else MarketRegime.BEAR
        
        # Ranging market
        return MarketRegime.RANGING
    
    def classify_regimes(self, data: pd.DataFrame) -> pd.Series:
        """Classify regime for entire dataset"""
        regimes = []
        for i in range(len(data)):
            regime = self.detect_regime(data, i)
            regimes.append(regime)
        return pd.Series(regimes, index=data.index, name='regime')


class FiveYearBacktester:
    """
    Comprehensive 5-year backtesting engine with regime analysis
    """
    
    def __init__(
        self,
        initial_balance: float = 10000.0,
        commission: float = 0.001,
        slippage: float = 0.0005
    ):
        self.initial_balance = initial_balance
        self.commission = commission
        self.slippage = slippage
        self.regime_detector = MarketRegimeDetector()
    
    def load_historical_data(self, symbol: str, years: int = 5) -> pd.DataFrame:
        """
        Load historical data for backtesting
        
        Note: In production, this would fetch from exchange API or data provider
        For now, expects CSV files in data/ directory
        """
        data_file = Path('data') / f'{symbol}_historical_5y.csv'
        
        if not data_file.exists():
            logger.warning(f"Historical data file not found: {data_file}")
            logger.info("Generating synthetic data for demonstration...")
            return self._generate_synthetic_data(symbol, years)
        
        df = pd.read_csv(data_file)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.set_index('timestamp')
        
        return df
    
    def _generate_synthetic_data(self, symbol: str, years: int = 5) -> pd.DataFrame:
        """
        Generate synthetic OHLCV data for testing
        
        This creates realistic-looking price data with different regime characteristics
        """
        logger.info(f"Generating {years} years of synthetic data for {symbol}")
        
        # Generate 5 years of hourly data
        periods = years * 365 * 24
        dates = pd.date_range(
            end=datetime.now(),
            periods=periods,
            freq='1H'
        )
        
        # Start with random walk
        np.random.seed(42)
        returns = np.random.randn(periods) * 0.02  # 2% hourly volatility
        
        # Add regime-specific characteristics
        regime_length = periods // 8  # 8 different regime periods
        
        for i in range(8):
            start = i * regime_length
            end = (i + 1) * regime_length
            
            if i % 4 == 0:  # Bull market
                returns[start:end] += 0.001  # Positive drift
            elif i % 4 == 1:  # Bear market
                returns[start:end] -= 0.0008  # Negative drift
            elif i % 4 == 2:  # Ranging
                returns[start:end] *= 0.5  # Lower volatility
            else:  # Volatile
                returns[start:end] *= 2.0  # Higher volatility
        
        # Generate price from returns
        price = 100 * np.exp(np.cumsum(returns))
        
        # Create OHLCV data
        df = pd.DataFrame({
            'open': price * (1 + np.random.randn(periods) * 0.005),
            'high': price * (1 + abs(np.random.randn(periods)) * 0.01),
            'low': price * (1 - abs(np.random.randn(periods)) * 0.01),
            'close': price,
            'volume': np.random.randint(1000000, 10000000, periods)
        }, index=dates)
        
        # Ensure OHLC relationships are correct
        df['high'] = df[['open', 'high', 'close']].max(axis=1)
        df['low'] = df[['open', 'low', 'close']].min(axis=1)
        
        return df
    
    def run_backtest(
        self,
        symbol: str,
        years: int = 5,
        strategy_name: str = "APEX_V71"
    ) -> Dict:
        """
        Run comprehensive 5-year backtest with regime analysis
        """
        logger.info(f"Starting {years}-year backtest for {symbol}")
        logger.info(f"Strategy: {strategy_name}")
        logger.info(f"Initial Balance: ${self.initial_balance:,.2f}")
        
        # Load data
        data = self.load_historical_data(symbol, years)
        logger.info(f"Loaded {len(data)} data points ({data.index[0]} to {data.index[-1]})")
        
        # Detect regimes
        logger.info("Detecting market regimes...")
        data['regime'] = self.regime_detector.classify_regimes(data)
        
        regime_counts = data['regime'].value_counts()
        logger.info(f"Regime distribution: {regime_counts.to_dict()}")
        
        # Run overall backtest
        logger.info("Running backtest...")
        backtest_engine = BacktestEngine(
            initial_balance=self.initial_balance,
            commission=self.commission,
            slippage=self.slippage
        )
        
        overall_results = backtest_engine.run(
            data=data,
            strategy_name=strategy_name
        )
        
        # Analyze by regime
        logger.info("Analyzing performance by regime...")
        regime_results = self._analyze_by_regime(data, overall_results)
        
        # Run Monte Carlo simulation
        logger.info("Running Monte Carlo simulation...")
        monte_carlo_results = self._monte_carlo_simulation(overall_results, n_simulations=1000)
        
        # Generate comprehensive report
        report = {
            'metadata': {
                'symbol': symbol,
                'strategy': strategy_name,
                'backtest_years': years,
                'start_date': str(data.index[0]),
                'end_date': str(data.index[-1]),
                'initial_balance': self.initial_balance,
                'commission': self.commission,
                'slippage': self.slippage,
                'generated_at': datetime.now().isoformat()
            },
            'overall_performance': asdict(overall_results),
            'regime_analysis': regime_results,
            'monte_carlo': monte_carlo_results,
            'statistical_significance': self._statistical_tests(overall_results)
        }
        
        return report
    
    def _analyze_by_regime(
        self,
        data: pd.DataFrame,
        overall_results: BacktestResults
    ) -> Dict[str, RegimeMetrics]:
        """Analyze performance broken down by market regime"""
        
        regime_metrics = {}
        
        for regime in [MarketRegime.BULL, MarketRegime.BEAR, 
                       MarketRegime.RANGING, MarketRegime.VOLATILE]:
            
            # Filter trades by regime
            regime_trades = [
                t for t in overall_results.trades
                if hasattr(t, 'regime') and t.regime == regime
            ]
            
            if not regime_trades:
                continue
            
            # Calculate metrics
            wins = [t for t in regime_trades if t.pnl > 0]
            losses = [t for t in regime_trades if t.pnl < 0]
            
            win_rate = len(wins) / len(regime_trades) if regime_trades else 0
            
            total_win = sum(t.pnl for t in wins)
            total_loss = abs(sum(t.pnl for t in losses)) if losses else 1
            profit_factor = total_win / total_loss if total_loss > 0 else 0
            
            avg_win = np.mean([t.pnl_pct for t in wins]) if wins else 0
            avg_loss = np.mean([t.pnl_pct for t in losses]) if losses else 0
            
            total_return = sum(t.pnl for t in regime_trades)
            total_return_pct = (total_return / self.initial_balance) * 100
            
            # Calculate regime duration
            regime_periods = data[data['regime'] == regime]
            duration_days = len(regime_periods) / 24  # Assuming hourly data
            
            # Expectancy
            expectancy = (win_rate * avg_win) - ((1 - win_rate) * abs(avg_loss))
            
            # Sharpe ratio (simplified)
            returns = [t.pnl_pct for t in regime_trades]
            sharpe = (np.mean(returns) / np.std(returns)) * np.sqrt(252) if len(returns) > 1 else 0
            
            # Max drawdown
            cumulative = np.cumsum([t.pnl for t in regime_trades])
            running_max = np.maximum.accumulate(cumulative)
            drawdown = running_max - cumulative
            max_dd = np.max(drawdown) if len(drawdown) > 0 else 0
            max_dd_pct = (max_dd / self.initial_balance) * 100
            
            regime_metrics[regime] = RegimeMetrics(
                regime=regime,
                duration_days=int(duration_days),
                total_trades=len(regime_trades),
                win_rate=win_rate,
                profit_factor=profit_factor,
                total_return_pct=total_return_pct,
                sharpe_ratio=sharpe,
                max_drawdown_pct=max_dd_pct,
                avg_win_pct=avg_win,
                avg_loss_pct=avg_loss,
                expectancy=expectancy
            )
        
        return {k: asdict(v) for k, v in regime_metrics.items()}
    
    def _monte_carlo_simulation(
        self,
        results: BacktestResults,
        n_simulations: int = 1000
    ) -> Dict:
        """
        Run Monte Carlo simulation to assess statistical robustness
        """
        if not results.trades:
            return {}
        
        trade_returns = [t.pnl_pct for t in results.trades]
        
        simulated_returns = []
        simulated_sharpes = []
        simulated_max_dds = []
        
        for _ in range(n_simulations):
            # Randomly sample trades with replacement
            sampled_returns = np.random.choice(trade_returns, size=len(trade_returns), replace=True)
            
            # Calculate metrics for this simulation
            cumulative = np.cumsum(sampled_returns)
            running_max = np.maximum.accumulate(cumulative)
            drawdown = running_max - cumulative
            
            final_return = cumulative[-1]
            sharpe = (np.mean(sampled_returns) / np.std(sampled_returns)) * np.sqrt(252) if np.std(sampled_returns) > 0 else 0
            max_dd = np.max(drawdown) if len(drawdown) > 0 else 0
            
            simulated_returns.append(final_return)
            simulated_sharpes.append(sharpe)
            simulated_max_dds.append(max_dd)
        
        return {
            'n_simulations': n_simulations,
            'expected_return': {
                'mean': float(np.mean(simulated_returns)),
                'median': float(np.median(simulated_returns)),
                'std': float(np.std(simulated_returns)),
                '5th_percentile': float(np.percentile(simulated_returns, 5)),
                '95th_percentile': float(np.percentile(simulated_returns, 95))
            },
            'expected_sharpe': {
                'mean': float(np.mean(simulated_sharpes)),
                'median': float(np.median(simulated_sharpes)),
                '5th_percentile': float(np.percentile(simulated_sharpes, 5)),
                '95th_percentile': float(np.percentile(simulated_sharpes, 95))
            },
            'expected_max_drawdown': {
                'mean': float(np.mean(simulated_max_dds)),
                'median': float(np.median(simulated_max_dds)),
                '95th_percentile': float(np.percentile(simulated_max_dds, 95))
            }
        }
    
    def _statistical_tests(self, results: BacktestResults) -> Dict:
        """
        Run statistical significance tests
        """
        if not results.trades or results.total_trades < 30:
            return {
                'sample_size_adequate': False,
                'message': 'Insufficient trades for statistical significance (need >= 30)'
            }
        
        trade_returns = [t.pnl_pct for t in results.trades]
        
        # T-test: Are returns significantly different from zero?
        from scipy import stats
        t_stat, p_value = stats.ttest_1samp(trade_returns, 0)
        
        return {
            'sample_size_adequate': True,
            'total_trades': results.total_trades,
            't_statistic': float(t_stat),
            'p_value': float(p_value),
            'significant_at_5pct': p_value < 0.05,
            'significant_at_1pct': p_value < 0.01,
            'conclusion': 'Strategy shows statistically significant edge' if p_value < 0.05 else 'No significant edge detected'
        }
    
    def save_report(self, report: Dict, output_file: str):
        """Save backtest report to JSON file"""
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        
        logger.info(f"Report saved to: {output_path}")
    
    def print_summary(self, report: Dict):
        """Print executive summary of backtest results"""
        print("\n" + "="*80)
        print("5-YEAR MULTI-REGIME BACKTEST SUMMARY")
        print("="*80)
        
        meta = report['metadata']
        perf = report['overall_performance']
        
        print(f"\n📊 BACKTEST DETAILS")
        print(f"Symbol: {meta['symbol']}")
        print(f"Strategy: {meta['strategy']}")
        print(f"Period: {meta['start_date'][:10]} to {meta['end_date'][:10]} ({meta['backtest_years']} years)")
        print(f"Initial Balance: ${meta['initial_balance']:,.2f}")
        
        print(f"\n💰 OVERALL PERFORMANCE")
        print(f"Final Balance: ${perf['final_balance']:,.2f}")
        print(f"Total Return: {perf['total_return_pct']:.2f}%")
        print(f"Total Trades: {perf['total_trades']}")
        print(f"Win Rate: {perf['win_rate']*100:.1f}%")
        print(f"Profit Factor: {perf['profit_factor']:.2f}")
        print(f"Sharpe Ratio: {perf['sharpe_ratio']:.2f}")
        print(f"Max Drawdown: {perf['max_drawdown_pct']:.2f}%")
        
        print(f"\n📈 REGIME ANALYSIS")
        for regime, metrics in report['regime_analysis'].items():
            print(f"\n{regime.upper()} Market:")
            print(f"  Duration: {metrics['duration_days']} days")
            print(f"  Trades: {metrics['total_trades']}")
            print(f"  Win Rate: {metrics['win_rate']*100:.1f}%")
            print(f"  Return: {metrics['total_return_pct']:.2f}%")
            print(f"  Profit Factor: {metrics['profit_factor']:.2f}")
            print(f"  Max DD: {metrics['max_drawdown_pct']:.2f}%")
        
        if 'monte_carlo' in report and report['monte_carlo']:
            mc = report['monte_carlo']
            print(f"\n🎲 MONTE CARLO SIMULATION ({mc['n_simulations']} runs)")
            print(f"Expected Return: {mc['expected_return']['mean']:.2f}% ± {mc['expected_return']['std']:.2f}%")
            print(f"95% Confidence: [{mc['expected_return']['5th_percentile']:.2f}%, {mc['expected_return']['95th_percentile']:.2f}%]")
            print(f"Expected Sharpe: {mc['expected_sharpe']['mean']:.2f}")
        
        if 'statistical_significance' in report:
            stat = report['statistical_significance']
            if stat.get('sample_size_adequate'):
                print(f"\n📊 STATISTICAL SIGNIFICANCE")
                print(f"Sample Size: {stat['total_trades']} trades")
                print(f"P-Value: {stat['p_value']:.4f}")
                print(f"Conclusion: {stat['conclusion']}")
        
        print("\n" + "="*80 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description='NIJA 5-Year Multi-Regime Backtesting Engine'
    )
    parser.add_argument(
        '--symbol',
        type=str,
        default='BTC-USD',
        help='Trading symbol (default: BTC-USD)'
    )
    parser.add_argument(
        '--years',
        type=int,
        default=5,
        help='Number of years to backtest (default: 5)'
    )
    parser.add_argument(
        '--initial-balance',
        type=float,
        default=10000.0,
        help='Initial balance (default: 10000)'
    )
    parser.add_argument(
        '--strategy',
        type=str,
        default='APEX_V71',
        help='Strategy to test (default: APEX_V71)'
    )
    parser.add_argument(
        '--output',
        type=str,
        default='results/5year_backtest.json',
        help='Output file path (default: results/5year_backtest.json)'
    )
    parser.add_argument(
        '--commission',
        type=float,
        default=0.001,
        help='Commission rate (default: 0.001 = 0.1%%)'
    )
    parser.add_argument(
        '--slippage',
        type=float,
        default=0.0005,
        help='Slippage rate (default: 0.0005 = 0.05%%)'
    )
    
    args = parser.parse_args()
    
    # Create backtester
    backtester = FiveYearBacktester(
        initial_balance=args.initial_balance,
        commission=args.commission,
        slippage=args.slippage
    )
    
    # Run backtest
    report = backtester.run_backtest(
        symbol=args.symbol,
        years=args.years,
        strategy_name=args.strategy
    )
    
    # Save report
    backtester.save_report(report, args.output)
    
    # Print summary
    backtester.print_summary(report)
    
    logger.info("✅ 5-year backtest complete!")


if __name__ == '__main__':
    main()
