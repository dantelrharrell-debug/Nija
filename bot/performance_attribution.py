"""
NIJA Performance Attribution System
====================================

Provides comprehensive performance attribution across multiple dimensions:
- Strategy attribution (which strategies contributed to returns)
- Market regime attribution (performance in different market conditions)
- Time period attribution (daily/weekly/monthly breakdown)
- Risk factor attribution (exposure to various risk factors)
- Trade-level attribution (individual trade contributions)

This enables deep understanding of what drives portfolio returns.

Author: NIJA Trading Systems
Version: 1.0
Date: February 12, 2026
"""

import logging
import json
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from enum import Enum
import numpy as np

logger = logging.getLogger("nija.performance_attribution")


class AttributionDimension(Enum):
    """Dimensions along which performance can be attributed"""
    STRATEGY = "strategy"
    MARKET_REGIME = "market_regime"
    TIME_PERIOD = "time_period"
    RISK_FACTOR = "risk_factor"
    ASSET_CLASS = "asset_class"
    TRADE_TYPE = "trade_type"


class MarketRegime(Enum):
    """Market regime classifications"""
    BULL_TRENDING = "bull_trending"
    BEAR_TRENDING = "bear_trending"
    RANGING = "ranging"
    VOLATILE = "volatile"
    CRISIS = "crisis"
    UNKNOWN = "unknown"


@dataclass
class TradeAttribution:
    """Attribution data for a single trade"""
    trade_id: str
    timestamp: datetime
    symbol: str
    strategy: str
    market_regime: str
    
    # Trade details
    entry_price: float
    exit_price: Optional[float]
    position_size: float
    side: str  # 'long' or 'short'
    
    # Performance
    pnl: float
    pnl_pct: float
    fees: float
    net_pnl: float
    
    # Risk metrics
    risk_capital: float  # Capital at risk
    risk_reward_ratio: float
    holding_period_hours: Optional[float]
    
    # Attribution dimensions (optional)
    signal_type: Optional[str] = None  # e.g., 'RSI_oversold', 'momentum_breakout'
    sector: Optional[str] = None  # e.g., 'DeFi', 'Layer1', 'Memecoins'
    asset_class: Optional[str] = None  # e.g., 'crypto', 'forex', 'stocks'
    
    # Attribution factors (optional)
    market_return: Optional[float] = None  # Benchmark return during trade
    alpha: Optional[float] = None  # Excess return vs benchmark
    beta: Optional[float] = None  # Correlation to market
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        d = asdict(self)
        d['timestamp'] = self.timestamp.isoformat()
        return d


@dataclass
class StrategyAttribution:
    """Attribution metrics for a specific strategy"""
    strategy_name: str
    
    # Performance
    total_pnl: float
    total_pnl_pct: float
    contribution_to_total_pnl: float  # % of total portfolio PnL
    
    # Trade stats
    trade_count: int
    win_count: int
    loss_count: int
    win_rate: float
    
    # Risk metrics
    avg_pnl_per_trade: float
    max_win: float
    max_loss: float
    sharpe_ratio: float
    
    # Capital allocation
    avg_capital_allocated: float
    max_capital_allocated: float
    capital_efficiency: float  # PnL per unit of capital


@dataclass
class RegimeAttribution:
    """Attribution metrics for a market regime"""
    regime: str
    
    # Performance
    total_pnl: float
    trade_count: int
    win_rate: float
    avg_pnl_per_trade: float
    
    # Time in regime
    time_in_regime_hours: float
    time_in_regime_pct: float  # % of total trading time


@dataclass
class TimeAttribution:
    """Attribution for a time period"""
    period_start: datetime
    period_end: datetime
    period_type: str  # 'daily', 'weekly', 'monthly'
    
    # Performance
    period_pnl: float
    period_return_pct: float
    
    # Breakdown by strategy
    strategy_contributions: Dict[str, float]
    
    # Risk metrics
    period_sharpe: float
    period_max_drawdown: float


class PerformanceAttribution:
    """
    Comprehensive Performance Attribution System
    
    Tracks and analyzes performance across multiple dimensions:
    - Strategy attribution
    - Market regime attribution
    - Time period attribution
    - Risk factor attribution
    
    Provides deep insights into sources of returns and risk.
    """
    
    def __init__(self, data_dir: str = "./data/attribution"):
        """
        Initialize performance attribution system
        
        Args:
            data_dir: Directory to store attribution data
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True, parents=True)
        
        # Trade-level attribution
        self.trades: List[TradeAttribution] = []
        
        # Aggregated attributions
        self.strategy_attributions: Dict[str, StrategyAttribution] = {}
        self.regime_attributions: Dict[str, RegimeAttribution] = {}
        
        # Configuration
        self.benchmark_symbol: Optional[str] = "BTC-USD"  # Default benchmark
        
        # Load existing data
        self._load_data()
        
        logger.info("=" * 70)
        logger.info("📊 PERFORMANCE ATTRIBUTION SYSTEM INITIALIZED")
        logger.info("=" * 70)
        logger.info(f"   Data directory: {self.data_dir}")
        logger.info(f"   Trades tracked: {len(self.trades)}")
        logger.info(f"   Strategies: {len(self.strategy_attributions)}")
        logger.info("=" * 70)
    
    def record_trade(
        self,
        trade_id: str,
        symbol: str,
        strategy: str,
        market_regime: str,
        entry_price: float,
        exit_price: Optional[float],
        position_size: float,
        side: str,
        pnl: float,
        fees: float,
        risk_capital: float,
        timestamp: Optional[datetime] = None,
        signal_type: Optional[str] = None,
        sector: Optional[str] = None,
        asset_class: Optional[str] = None
    ) -> TradeAttribution:
        """
        Record a trade for attribution analysis
        
        Args:
            trade_id: Unique trade identifier
            symbol: Trading symbol
            strategy: Strategy name that generated the trade
            market_regime: Market regime during trade
            entry_price: Entry price
            exit_price: Exit price (None if still open)
            position_size: Position size
            side: 'long' or 'short'
            pnl: Gross PnL
            fees: Trading fees
            risk_capital: Capital at risk
            timestamp: Trade timestamp (defaults to now)
            signal_type: Type of signal that triggered trade (optional)
            sector: Market sector/category (optional)
            asset_class: Asset class (optional)
        
        Returns:
            TradeAttribution object
        """
        timestamp = timestamp or datetime.now()
        
        # Calculate metrics
        net_pnl = pnl - fees
        pnl_pct = (pnl / (entry_price * position_size)) * 100 if entry_price * position_size > 0 else 0.0
        
        # Calculate risk-reward ratio
        if exit_price and entry_price:
            if side.lower() == 'long':
                risk_reward = abs(exit_price - entry_price) / abs(entry_price - (entry_price * 0.98))  # Assuming 2% stop
            else:
                risk_reward = abs(entry_price - exit_price) / abs(entry_price - (entry_price * 1.02))
        else:
            risk_reward = 0.0
        
        # Calculate holding period
        holding_period_hours = None  # Would need entry/exit timestamps
        
        # Create attribution record
        trade_attr = TradeAttribution(
            trade_id=trade_id,
            timestamp=timestamp,
            symbol=symbol,
            strategy=strategy,
            market_regime=market_regime,
            entry_price=entry_price,
            exit_price=exit_price,
            position_size=position_size,
            side=side,
            pnl=pnl,
            pnl_pct=pnl_pct,
            fees=fees,
            net_pnl=net_pnl,
            risk_capital=risk_capital,
            risk_reward_ratio=risk_reward,
            holding_period_hours=holding_period_hours,
            signal_type=signal_type,
            sector=sector,
            asset_class=asset_class
        )
        
        self.trades.append(trade_attr)
        
        # Update aggregated attributions
        self._update_strategy_attribution(trade_attr)
        self._update_regime_attribution(trade_attr)
        
        # Save data
        self._save_data()
        
        logger.debug(f"📊 Recorded trade attribution: {trade_id} | Strategy: {strategy} | PnL: ${net_pnl:.2f}")
        
        return trade_attr
    
    def _update_strategy_attribution(self, trade: TradeAttribution):
        """Update strategy-level attribution metrics"""
        strategy = trade.strategy
        
        if strategy not in self.strategy_attributions:
            # Initialize strategy attribution
            self.strategy_attributions[strategy] = StrategyAttribution(
                strategy_name=strategy,
                total_pnl=0.0,
                total_pnl_pct=0.0,
                contribution_to_total_pnl=0.0,
                trade_count=0,
                win_count=0,
                loss_count=0,
                win_rate=0.0,
                avg_pnl_per_trade=0.0,
                max_win=0.0,
                max_loss=0.0,
                sharpe_ratio=0.0,
                avg_capital_allocated=0.0,
                max_capital_allocated=0.0,
                capital_efficiency=0.0
            )
        
        attr = self.strategy_attributions[strategy]
        
        # Update metrics
        attr.total_pnl += trade.net_pnl
        attr.trade_count += 1
        
        if trade.net_pnl > 0:
            attr.win_count += 1
            attr.max_win = max(attr.max_win, trade.net_pnl)
        else:
            attr.loss_count += 1
            attr.max_loss = min(attr.max_loss, trade.net_pnl)
        
        # Recalculate derived metrics
        attr.win_rate = (attr.win_count / attr.trade_count * 100) if attr.trade_count > 0 else 0.0
        attr.avg_pnl_per_trade = attr.total_pnl / attr.trade_count if attr.trade_count > 0 else 0.0
        
        # Update capital metrics
        attr.max_capital_allocated = max(attr.max_capital_allocated, trade.risk_capital)
        
        # Calculate average capital (running average)
        prev_avg = attr.avg_capital_allocated
        n = attr.trade_count
        attr.avg_capital_allocated = ((prev_avg * (n - 1)) + trade.risk_capital) / n
        
        # Capital efficiency (return per unit of capital)
        attr.capital_efficiency = (attr.total_pnl / attr.avg_capital_allocated) if attr.avg_capital_allocated > 0 else 0.0
        
        # Calculate Sharpe ratio for strategy
        strategy_trades = [t for t in self.trades if t.strategy == strategy]
        if len(strategy_trades) > 1:
            returns = [t.pnl_pct for t in strategy_trades]
            mean_return = np.mean(returns)
            std_return = np.std(returns)
            attr.sharpe_ratio = (mean_return / std_return * np.sqrt(252)) if std_return > 0 else 0.0
    
    def _update_regime_attribution(self, trade: TradeAttribution):
        """Update market regime attribution metrics"""
        regime = trade.market_regime
        
        if regime not in self.regime_attributions:
            self.regime_attributions[regime] = RegimeAttribution(
                regime=regime,
                total_pnl=0.0,
                trade_count=0,
                win_rate=0.0,
                avg_pnl_per_trade=0.0,
                time_in_regime_hours=0.0,
                time_in_regime_pct=0.0
            )
        
        attr = self.regime_attributions[regime]
        
        # Update metrics
        attr.total_pnl += trade.net_pnl
        attr.trade_count += 1
        
        # Recalculate win rate
        regime_trades = [t for t in self.trades if t.market_regime == regime]
        wins = sum(1 for t in regime_trades if t.net_pnl > 0)
        attr.win_rate = (wins / len(regime_trades) * 100) if regime_trades else 0.0
        attr.avg_pnl_per_trade = attr.total_pnl / attr.trade_count if attr.trade_count > 0 else 0.0
    
    def get_strategy_attribution(self, strategy: Optional[str] = None) -> Dict[str, StrategyAttribution]:
        """
        Get strategy attribution metrics
        
        Args:
            strategy: Specific strategy name (None for all)
        
        Returns:
            Dictionary of strategy attributions
        """
        if strategy:
            return {strategy: self.strategy_attributions.get(strategy)}
        return self.strategy_attributions.copy()
    
    def get_regime_attribution(self, regime: Optional[str] = None) -> Dict[str, RegimeAttribution]:
        """
        Get market regime attribution metrics
        
        Args:
            regime: Specific regime (None for all)
        
        Returns:
            Dictionary of regime attributions
        """
        if regime:
            return {regime: self.regime_attributions.get(regime)}
        return self.regime_attributions.copy()
    
    def get_time_attribution(
        self,
        start_date: datetime,
        end_date: datetime,
        period_type: str = 'daily'
    ) -> List[TimeAttribution]:
        """
        Get time-based attribution
        
        Args:
            start_date: Start of period
            end_date: End of period
            period_type: 'daily', 'weekly', or 'monthly'
        
        Returns:
            List of TimeAttribution objects
        """
        attributions = []
        
        # Filter trades in date range
        period_trades = [
            t for t in self.trades
            if start_date <= t.timestamp <= end_date
        ]
        
        if not period_trades:
            return attributions
        
        # Group by period
        if period_type == 'daily':
            delta = timedelta(days=1)
        elif period_type == 'weekly':
            delta = timedelta(weeks=1)
        elif period_type == 'monthly':
            delta = timedelta(days=30)
        else:
            delta = timedelta(days=1)
        
        current_start = start_date
        while current_start < end_date:
            current_end = min(current_start + delta, end_date)
            
            # Get trades in this period
            period_subset = [
                t for t in period_trades
                if current_start <= t.timestamp < current_end
            ]
            
            if period_subset:
                # Calculate period metrics
                period_pnl = sum(t.net_pnl for t in period_subset)
                
                # Strategy contributions
                strategy_contributions = {}
                for trade in period_subset:
                    if trade.strategy not in strategy_contributions:
                        strategy_contributions[trade.strategy] = 0.0
                    strategy_contributions[trade.strategy] += trade.net_pnl
                
                # Calculate period return %
                total_capital = sum(t.risk_capital for t in period_subset)
                period_return_pct = (period_pnl / total_capital * 100) if total_capital > 0 else 0.0
                
                # Calculate period Sharpe
                returns = [t.pnl_pct for t in period_subset]
                if len(returns) > 1:
                    mean_return = np.mean(returns)
                    std_return = np.std(returns)
                    period_sharpe = (mean_return / std_return) if std_return > 0 else 0.0
                else:
                    period_sharpe = 0.0
                
                # Calculate max drawdown in period
                cumulative_pnl = 0.0
                peak = 0.0
                max_dd = 0.0
                for trade in sorted(period_subset, key=lambda x: x.timestamp):
                    cumulative_pnl += trade.net_pnl
                    peak = max(peak, cumulative_pnl)
                    dd = ((peak - cumulative_pnl) / peak * 100) if peak > 0 else 0.0
                    max_dd = max(max_dd, dd)
                
                # Create attribution
                attr = TimeAttribution(
                    period_start=current_start,
                    period_end=current_end,
                    period_type=period_type,
                    period_pnl=period_pnl,
                    period_return_pct=period_return_pct,
                    strategy_contributions=strategy_contributions,
                    period_sharpe=period_sharpe,
                    period_max_drawdown=max_dd
                )
                
                attributions.append(attr)
            
            current_start = current_end
        
        return attributions
    
    def generate_attribution_report(self) -> str:
        """
        Generate comprehensive attribution report
        
        Returns:
            Formatted attribution report string
        """
        report = [
            "\n" + "=" * 90,
            "PERFORMANCE ATTRIBUTION REPORT",
            "=" * 90,
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Total Trades Analyzed: {len(self.trades)}",
            ""
        ]
        
        # Calculate total PnL
        total_pnl = sum(t.net_pnl for t in self.trades)
        
        # Strategy Attribution
        report.extend([
            "📊 STRATEGY ATTRIBUTION",
            "-" * 90
        ])
        
        if self.strategy_attributions:
            # Sort by total PnL
            sorted_strategies = sorted(
                self.strategy_attributions.items(),
                key=lambda x: x[1].total_pnl,
                reverse=True
            )
            
            for strategy_name, attr in sorted_strategies:
                contribution_pct = (attr.total_pnl / total_pnl * 100) if total_pnl != 0 else 0.0
                
                report.extend([
                    f"\n  Strategy: {strategy_name}",
                    f"    Total PnL:              ${attr.total_pnl:>12,.2f} ({contribution_pct:+.1f}%)",
                    f"    Trades:                 {attr.trade_count:>12}",
                    f"    Win Rate:               {attr.win_rate:>12.1f}%",
                    f"    Avg PnL/Trade:          ${attr.avg_pnl_per_trade:>12,.2f}",
                    f"    Max Win:                ${attr.max_win:>12,.2f}",
                    f"    Max Loss:               ${attr.max_loss:>12,.2f}",
                    f"    Sharpe Ratio:           {attr.sharpe_ratio:>12.2f}",
                    f"    Capital Efficiency:     {attr.capital_efficiency:>12.2%}"
                ])
        else:
            report.append("    No strategy data available")
        
        report.append("")
        
        # Market Regime Attribution
        report.extend([
            "🌐 MARKET REGIME ATTRIBUTION",
            "-" * 90
        ])
        
        if self.regime_attributions:
            sorted_regimes = sorted(
                self.regime_attributions.items(),
                key=lambda x: x[1].total_pnl,
                reverse=True
            )
            
            for regime_name, attr in sorted_regimes:
                contribution_pct = (attr.total_pnl / total_pnl * 100) if total_pnl != 0 else 0.0
                
                report.extend([
                    f"\n  Regime: {regime_name}",
                    f"    Total PnL:              ${attr.total_pnl:>12,.2f} ({contribution_pct:+.1f}%)",
                    f"    Trades:                 {attr.trade_count:>12}",
                    f"    Win Rate:               {attr.win_rate:>12.1f}%",
                    f"    Avg PnL/Trade:          ${attr.avg_pnl_per_trade:>12,.2f}"
                ])
        else:
            report.append("    No regime data available")
        
        report.append("")
        
        # Summary
        report.extend([
            "📈 SUMMARY",
            "-" * 90,
            f"  Total PnL:                ${total_pnl:>12,.2f}",
            f"  Total Trades:             {len(self.trades):>12}",
            f"  Strategies Tracked:       {len(self.strategy_attributions):>12}",
            f"  Regimes Encountered:      {len(self.regime_attributions):>12}",
            ""
        ])
        
        report.append("=" * 90 + "\n")
        
        return "\n".join(report)
    
    def _load_data(self):
        """Load attribution data from disk"""
        trades_file = self.data_dir / "trades.json"
        
        if not trades_file.exists():
            logger.info("No historical attribution data found")
            return
        
        try:
            with open(trades_file, 'r') as f:
                data = json.load(f)
            
            # Reconstruct trades
            for item in data:
                trade = TradeAttribution(
                    trade_id=item['trade_id'],
                    timestamp=datetime.fromisoformat(item['timestamp']),
                    symbol=item['symbol'],
                    strategy=item['strategy'],
                    market_regime=item['market_regime'],
                    entry_price=item['entry_price'],
                    exit_price=item.get('exit_price'),
                    position_size=item['position_size'],
                    side=item['side'],
                    pnl=item['pnl'],
                    pnl_pct=item['pnl_pct'],
                    fees=item['fees'],
                    net_pnl=item['net_pnl'],
                    risk_capital=item['risk_capital'],
                    risk_reward_ratio=item['risk_reward_ratio'],
                    holding_period_hours=item.get('holding_period_hours'),
                    market_return=item.get('market_return'),
                    alpha=item.get('alpha'),
                    beta=item.get('beta')
                )
                
                self.trades.append(trade)
                self._update_strategy_attribution(trade)
                self._update_regime_attribution(trade)
            
            logger.info(f"✅ Loaded {len(self.trades)} attribution records")
        
        except Exception as e:
            logger.error(f"Error loading attribution data: {e}")
    
    def _save_data(self):
        """Save attribution data to disk"""
        trades_file = self.data_dir / "trades.json"
        
        try:
            data = [trade.to_dict() for trade in self.trades]
            
            with open(trades_file, 'w') as f:
                json.dump(data, f, indent=2)
            
            logger.debug(f"Saved {len(self.trades)} attribution records")
        
        except Exception as e:
            logger.error(f"Error saving attribution data: {e}")


# Singleton instance
_performance_attribution: Optional[PerformanceAttribution] = None


def get_performance_attribution(reset: bool = False) -> PerformanceAttribution:
    """
    Get or create the performance attribution singleton
    
    Args:
        reset: Force reset and create new instance
    
    Returns:
        PerformanceAttribution instance
    """
    global _performance_attribution
    
    if _performance_attribution is None or reset:
        _performance_attribution = PerformanceAttribution()
    
    return _performance_attribution


if __name__ == "__main__":
    # Test/demonstration
    import logging
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s - %(message)s'
    )
    
    # Create attribution system
    attribution = get_performance_attribution()
    
    # Simulate some trades
    print("\n📊 Simulating trades for attribution analysis...\n")
    
    # Strategy A - Momentum strategy
    attribution.record_trade(
        trade_id="trade_001",
        symbol="BTC-USD",
        strategy="Momentum_RSI",
        market_regime=MarketRegime.BULL_TRENDING.value,
        entry_price=45000.0,
        exit_price=46000.0,
        position_size=0.1,
        side="long",
        pnl=100.0,
        fees=2.0,
        risk_capital=4500.0
    )
    
    attribution.record_trade(
        trade_id="trade_002",
        symbol="ETH-USD",
        strategy="Momentum_RSI",
        market_regime=MarketRegime.BULL_TRENDING.value,
        entry_price=3000.0,
        exit_price=3100.0,
        position_size=1.0,
        side="long",
        pnl=100.0,
        fees=3.0,
        risk_capital=3000.0
    )
    
    # Strategy B - Mean reversion
    attribution.record_trade(
        trade_id="trade_003",
        symbol="BTC-USD",
        strategy="Mean_Reversion",
        market_regime=MarketRegime.RANGING.value,
        entry_price=44000.0,
        exit_price=44500.0,
        position_size=0.1,
        side="long",
        pnl=50.0,
        fees=2.0,
        risk_capital=4400.0
    )
    
    # Losing trade
    attribution.record_trade(
        trade_id="trade_004",
        symbol="SOL-USD",
        strategy="Momentum_RSI",
        market_regime=MarketRegime.VOLATILE.value,
        entry_price=100.0,
        exit_price=95.0,
        position_size=10.0,
        side="long",
        pnl=-50.0,
        fees=1.5,
        risk_capital=1000.0
    )
    
    # Generate and print report
    print(attribution.generate_attribution_report())
    
    # Test time attribution
    print("\n📅 Time-based attribution (last 7 days):\n")
    time_attrs = attribution.get_time_attribution(
        start_date=datetime.now() - timedelta(days=7),
        end_date=datetime.now(),
        period_type='daily'
    )
    
    for attr in time_attrs:
        print(f"Period: {attr.period_start.date()} to {attr.period_end.date()}")
        print(f"  PnL: ${attr.period_pnl:.2f} ({attr.period_return_pct:+.2f}%)")
        print(f"  Sharpe: {attr.period_sharpe:.2f}")
        print(f"  Max DD: {attr.period_max_drawdown:.2f}%")
        print()
