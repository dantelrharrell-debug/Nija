"""
NIJA Command Center Metrics

Comprehensive metrics tracking for the NIJA Command Center dashboard.
Calculates and tracks all 8 key performance indicators:
1. Equity Curve
2. Risk Heat
3. Trade Quality Score
4. Signal Accuracy
5. Slippage
6. Fee Impact
7. Strategy Efficiency
8. Capital Growth Velocity

Author: NIJA Trading Systems
Version: 1.0
Date: January 30, 2026
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from collections import deque
import statistics
import threading

logger = logging.getLogger(__name__)


@dataclass
class CommandCenterSnapshot:
    """Complete Command Center metrics snapshot"""
    timestamp: str
    
    # 1. Equity Curve
    equity: float
    equity_peak: float
    equity_change_24h: float
    equity_change_pct_24h: float
    
    # 2. Risk Heat (0-100 scale)
    risk_heat: float
    risk_level: str  # "LOW", "MODERATE", "HIGH", "CRITICAL"
    max_drawdown_pct: float
    current_drawdown_pct: float
    position_concentration: float
    
    # 3. Trade Quality Score (0-100 scale)
    trade_quality_score: float
    trade_quality_grade: str  # "A+", "A", "B", "C", "D", "F"
    win_rate: float
    profit_factor: float
    avg_win_loss_ratio: float
    
    # 4. Signal Accuracy (0-100 scale)
    signal_accuracy: float
    signals_total: int
    signals_successful: int
    signals_failed: int
    false_positive_rate: float
    
    # 5. Slippage (in basis points and dollars)
    avg_slippage_bps: float
    avg_slippage_usd: float
    total_slippage_cost: float
    slippage_impact_pct: float
    
    # 6. Fee Impact
    total_fees: float
    fees_pct_of_profit: float
    avg_fee_per_trade: float
    fee_efficiency_score: float  # Lower is better, 0-100
    
    # 7. Strategy Efficiency (0-100 scale)
    strategy_efficiency: float
    trades_per_day: float
    win_rate_efficiency: float
    capital_utilization: float
    
    # 8. Capital Growth Velocity (annualized % growth rate)
    growth_velocity: float
    daily_growth_rate: float
    monthly_growth_rate: float
    annualized_growth_rate: float


class CommandCenterMetrics:
    """
    Command Center metrics tracker.
    
    Tracks all 8 key metrics for the NIJA Command Center dashboard:
    1. Equity Curve - Portfolio value over time
    2. Risk Heat - Overall risk exposure level
    3. Trade Quality Score - Quality of trading decisions
    4. Signal Accuracy - Accuracy of trading signals
    5. Slippage - Cost of execution slippage
    6. Fee Impact - Impact of trading fees
    7. Strategy Efficiency - Efficiency of strategy execution
    8. Capital Growth Velocity - Rate of capital growth
    """
    
    def __init__(self, initial_capital: float = 1000.0, lookback_days: int = 30):
        """
        Initialize Command Center metrics tracker.
        
        Args:
            initial_capital: Starting capital
            lookback_days: Days to keep in history
        """
        self.initial_capital = initial_capital
        self.lookback_days = lookback_days
        
        # Current state
        self.current_equity = initial_capital
        self.current_cash = initial_capital
        self.current_positions_value = 0.0
        
        # Equity curve tracking
        self.equity_history: deque = deque(maxlen=lookback_days * 24)  # Hourly snapshots
        self.equity_peak = initial_capital
        
        # Trade tracking
        self.trades: List[Dict] = []
        self.winning_trades = 0
        self.losing_trades = 0
        self.total_profit = 0.0
        self.total_loss = 0.0
        
        # Signal tracking
        self.signals_total = 0
        self.signals_successful = 0
        self.signals_failed = 0
        
        # Slippage tracking
        self.slippage_data: List[Dict] = []
        
        # Fee tracking
        self.total_fees = 0.0
        self.fees_per_trade: List[float] = []
        
        # Risk tracking
        self.position_sizes: List[float] = []
        self.drawdown_history: deque = deque(maxlen=lookback_days * 24)
        
        # Strategy efficiency
        self.trade_timestamps: List[datetime] = []
        
        # Thread safety
        self.lock = threading.Lock()
        
        # Persistence
        self.data_file = Path("./data/command_center_metrics.json")
        self._load_state()
        
        logger.info(f"✅ Command Center Metrics initialized with ${initial_capital:,.2f}")
    
    def update_equity(self, equity: float, cash: float, positions_value: float):
        """
        Update equity curve.
        
        Args:
            equity: Total portfolio equity
            cash: Available cash
            positions_value: Market value of positions
        """
        with self.lock:
            self.current_equity = equity
            self.current_cash = cash
            self.current_positions_value = positions_value
            
            # Update peak
            if equity > self.equity_peak:
                self.equity_peak = equity
            
            # Add to history
            snapshot = {
                'timestamp': datetime.now().isoformat(),
                'equity': equity,
                'cash': cash,
                'positions_value': positions_value
            }
            self.equity_history.append(snapshot)
    
    def record_trade(self, symbol: str, side: str, entry_price: float, exit_price: float,
                    size: float, fees: float, slippage: Optional[float] = None):
        """
        Record a completed trade.
        
        Args:
            symbol: Trading symbol
            side: 'long' or 'short'
            entry_price: Entry price
            exit_price: Exit price
            size: Position size in USD
            fees: Total fees paid
            slippage: Slippage in USD (optional)
        """
        with self.lock:
            # Calculate P&L
            if side == 'long':
                pnl = (exit_price - entry_price) / entry_price * size
            else:
                pnl = (entry_price - exit_price) / entry_price * size
            
            net_pnl = pnl - fees
            
            # Record trade
            trade = {
                'timestamp': datetime.now().isoformat(),
                'symbol': symbol,
                'side': side,
                'entry_price': entry_price,
                'exit_price': exit_price,
                'size': size,
                'pnl': pnl,
                'fees': fees,
                'net_pnl': net_pnl,
                'slippage': slippage or 0.0
            }
            self.trades.append(trade)
            self.trade_timestamps.append(datetime.now())
            
            # Update counters
            if net_pnl > 0:
                self.winning_trades += 1
                self.total_profit += net_pnl
            else:
                self.losing_trades += 1
                self.total_loss += abs(net_pnl)
            
            # Update fees
            self.total_fees += fees
            self.fees_per_trade.append(fees)
            
            # Update slippage
            if slippage:
                self.slippage_data.append({
                    'timestamp': datetime.now().isoformat(),
                    'symbol': symbol,
                    'slippage_usd': slippage,
                    'slippage_bps': (slippage / size) * 10000 if size > 0 else 0
                })
            
            # Auto-save state after trades (every 10 trades to avoid excessive I/O)
            if len(self.trades) % 10 == 0:
                self._save_state()
    
    def record_signal(self, success: bool):
        """
        Record a trading signal outcome.
        
        Args:
            success: Whether signal led to successful trade
        """
        with self.lock:
            self.signals_total += 1
            if success:
                self.signals_successful += 1
            else:
                self.signals_failed += 1
    
    def calculate_equity_curve_metrics(self) -> Dict[str, float]:
        """
        Calculate equity curve metrics.
        
        Returns:
            Dictionary with equity curve metrics
        """
        if not self.equity_history:
            return {
                'equity': self.initial_capital,
                'equity_peak': self.initial_capital,
                'equity_change_24h': 0.0,
                'equity_change_pct_24h': 0.0
            }
        
        current = self.equity_history[-1]
        
        # Find equity 24 hours ago
        now = datetime.now()
        yesterday = now - timedelta(days=1)
        equity_24h_ago = self.initial_capital
        
        for snapshot in self.equity_history:
            snapshot_time = datetime.fromisoformat(snapshot['timestamp'])
            if snapshot_time >= yesterday:
                equity_24h_ago = snapshot['equity']
                break
        
        change_24h = current['equity'] - equity_24h_ago
        change_pct_24h = (change_24h / equity_24h_ago * 100) if equity_24h_ago > 0 else 0.0
        
        return {
            'equity': current['equity'],
            'equity_peak': self.equity_peak,
            'equity_change_24h': change_24h,
            'equity_change_pct_24h': change_pct_24h
        }
    
    def calculate_risk_heat(self) -> Dict[str, Any]:
        """
        Calculate risk heat (0-100 scale).
        
        Risk heat considers:
        - Current drawdown (weighted 2x - primary risk indicator)
        - Position concentration (weighted 0.5x - secondary risk indicator)
        
        Formula: min(100, (current_dd_pct * 2) + (concentration * 0.5))
        - A 25% drawdown alone yields 50 points (MODERATE risk)
        - 100% position concentration adds 50 points
        - Combined, both maxed would exceed 100 (capped at 100)
        
        Risk Levels:
        - LOW (0-25): Safe trading conditions
        - MODERATE (25-50): Normal risk levels
        - HIGH (50-75): Elevated risk, caution advised
        - CRITICAL (75-100): Dangerous levels, reduce exposure
        
        Returns:
            Dictionary with risk heat metrics
        """
        # Calculate current drawdown
        current_dd_pct = 0.0
        if self.equity_peak > 0:
            current_dd_pct = ((self.equity_peak - self.current_equity) / self.equity_peak) * 100
        
        # Calculate max drawdown
        max_dd_pct = 0.0
        if self.equity_history:
            peak = self.equity_history[0]['equity']
            for snapshot in self.equity_history:
                equity = snapshot['equity']
                if equity > peak:
                    peak = equity
                dd = ((peak - equity) / peak) * 100
                if dd > max_dd_pct:
                    max_dd_pct = dd
        
        # Calculate position concentration (0-100)
        concentration = 0.0
        if self.current_equity > 0:
            concentration = (self.current_positions_value / self.current_equity) * 100
        
        # Calculate risk heat score (0-100)
        # Higher drawdown = higher risk
        # Higher concentration = higher risk
        risk_score = min(100, (current_dd_pct * 2) + (concentration * 0.5))
        
        # Determine risk level
        if risk_score < 25:
            risk_level = "LOW"
        elif risk_score < 50:
            risk_level = "MODERATE"
        elif risk_score < 75:
            risk_level = "HIGH"
        else:
            risk_level = "CRITICAL"
        
        return {
            'risk_heat': risk_score,
            'risk_level': risk_level,
            'max_drawdown_pct': max_dd_pct,
            'current_drawdown_pct': current_dd_pct,
            'position_concentration': concentration
        }
    
    def calculate_trade_quality_score(self) -> Dict[str, Any]:
        """
        Calculate trade quality score (0-100 scale).
        
        Trade quality considers:
        - Win rate (weighted 40%, scaled 1.5x)
          * 66.7% win rate = perfect 100 score component
        - Profit factor (weighted 40%, scaled 30x)
          * 3.33 profit factor = perfect 100 score component
        - Win/loss ratio (weighted 20%, scaled 40x)
          * 2.5 win/loss ratio = perfect 100 score component
        
        Grading Scale:
        - A+ (95-100): Exceptional trading
        - A  (90-94):  Excellent trading
        - B  (80-89):  Good trading
        - C  (70-79):  Average trading
        - D  (60-69):  Below average trading
        - F  (<60):    Poor trading
        
        Returns:
            Dictionary with trade quality metrics
        """
        total_trades = self.winning_trades + self.losing_trades
        
        if total_trades == 0:
            return {
                'trade_quality_score': 50.0,
                'trade_quality_grade': 'C',
                'win_rate': 0.0,
                'profit_factor': 0.0,
                'avg_win_loss_ratio': 0.0
            }
        
        # Win rate
        win_rate = (self.winning_trades / total_trades) * 100
        
        # Profit factor
        profit_factor = self.total_profit / self.total_loss if self.total_loss > 0 else 0.0
        
        # Average win/loss ratio
        avg_win = self.total_profit / self.winning_trades if self.winning_trades > 0 else 0.0
        avg_loss = self.total_loss / self.losing_trades if self.losing_trades > 0 else 0.0
        avg_win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0.0
        
        # Calculate quality score (0-100)
        # Weight: 40% win rate, 40% profit factor, 20% win/loss ratio
        win_rate_score = min(100, win_rate * 1.5)  # Scale win rate
        profit_factor_score = min(100, profit_factor * 30)  # Scale profit factor
        ratio_score = min(100, avg_win_loss_ratio * 40)  # Scale ratio
        
        quality_score = (
            win_rate_score * 0.4 +
            profit_factor_score * 0.4 +
            ratio_score * 0.2
        )
        
        # Assign grade
        if quality_score >= 95:
            grade = "A+"
        elif quality_score >= 90:
            grade = "A"
        elif quality_score >= 80:
            grade = "B"
        elif quality_score >= 70:
            grade = "C"
        elif quality_score >= 60:
            grade = "D"
        else:
            grade = "F"
        
        return {
            'trade_quality_score': quality_score,
            'trade_quality_grade': grade,
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'avg_win_loss_ratio': avg_win_loss_ratio
        }
    
    def calculate_signal_accuracy(self) -> Dict[str, float]:
        """
        Calculate signal accuracy metrics.
        
        Returns:
            Dictionary with signal accuracy metrics
        """
        if self.signals_total == 0:
            return {
                'signal_accuracy': 0.0,
                'signals_total': 0,
                'signals_successful': 0,
                'signals_failed': 0,
                'false_positive_rate': 0.0
            }
        
        accuracy = (self.signals_successful / self.signals_total) * 100
        false_positive_rate = (self.signals_failed / self.signals_total) * 100
        
        return {
            'signal_accuracy': accuracy,
            'signals_total': self.signals_total,
            'signals_successful': self.signals_successful,
            'signals_failed': self.signals_failed,
            'false_positive_rate': false_positive_rate
        }
    
    def calculate_slippage_metrics(self) -> Dict[str, float]:
        """
        Calculate slippage metrics.
        
        Returns:
            Dictionary with slippage metrics
        """
        if not self.slippage_data:
            return {
                'avg_slippage_bps': 0.0,
                'avg_slippage_usd': 0.0,
                'total_slippage_cost': 0.0,
                'slippage_impact_pct': 0.0
            }
        
        total_slippage = sum(s['slippage_usd'] for s in self.slippage_data)
        avg_slippage_usd = total_slippage / len(self.slippage_data)
        avg_slippage_bps = sum(s['slippage_bps'] for s in self.slippage_data) / len(self.slippage_data)
        
        # Calculate impact as % of total profit
        impact_pct = 0.0
        if self.total_profit > 0:
            impact_pct = (total_slippage / self.total_profit) * 100
        
        return {
            'avg_slippage_bps': avg_slippage_bps,
            'avg_slippage_usd': avg_slippage_usd,
            'total_slippage_cost': total_slippage,
            'slippage_impact_pct': impact_pct
        }
    
    def calculate_fee_impact(self) -> Dict[str, float]:
        """
        Calculate fee impact metrics.
        
        Returns:
            Dictionary with fee impact metrics
        """
        total_trades = len(self.trades)
        
        if total_trades == 0:
            return {
                'total_fees': 0.0,
                'fees_pct_of_profit': 0.0,
                'avg_fee_per_trade': 0.0,
                'fee_efficiency_score': 100.0
            }
        
        avg_fee = self.total_fees / total_trades
        
        # Calculate fees as % of profit
        fees_pct = 0.0
        if self.total_profit > 0:
            fees_pct = (self.total_fees / self.total_profit) * 100
        
        # Fee efficiency score (0-100, lower fees = higher score)
        # Penalize high fee ratios
        efficiency_score = max(0, 100 - fees_pct)
        
        return {
            'total_fees': self.total_fees,
            'fees_pct_of_profit': fees_pct,
            'avg_fee_per_trade': avg_fee,
            'fee_efficiency_score': efficiency_score
        }
    
    def calculate_strategy_efficiency(self) -> Dict[str, float]:
        """
        Calculate strategy efficiency (0-100 scale).
        
        Efficiency considers:
        - Trade frequency (30% weight, scaled 10x)
          * 10 trades/day = optimal activity level = 100 score component
        - Win rate (50% weight, direct)
          * Higher win rate directly improves efficiency
        - Capital utilization (20% weight, direct %)
          * Percentage of capital actively deployed in trades
        
        Formula: min(100, (
            min(100, trades_per_day * 10) * 0.3 +
            win_rate * 0.5 +
            min(100, capital_utilization) * 0.2
        ))
        
        Note: The 10 trades/day target may need adjustment based on
        trading strategy (day trading vs swing trading vs position trading).
        
        Returns:
            Dictionary with strategy efficiency metrics
        """
        total_trades = len(self.trades)
        
        if total_trades == 0:
            return {
                'strategy_efficiency': 50.0,
                'trades_per_day': 0.0,
                'win_rate_efficiency': 0.0,
                'capital_utilization': 0.0
            }
        
        # Calculate trades per day
        if self.trade_timestamps:
            days_active = (datetime.now() - self.trade_timestamps[0]).days
            days_active = max(1, days_active)
            trades_per_day = total_trades / days_active
        else:
            trades_per_day = 0.0
        
        # Win rate efficiency
        win_rate = (self.winning_trades / total_trades) * 100 if total_trades > 0 else 0
        
        # Capital utilization (avg position size as % of equity)
        if self.trades:
            avg_position_size = sum(t['size'] for t in self.trades) / len(self.trades)
            capital_utilization = (avg_position_size / self.current_equity) * 100 if self.current_equity > 0 else 0
        else:
            capital_utilization = 0.0
        
        # Overall efficiency score
        # Balance between activity and profitability
        efficiency = min(100, (
            min(100, trades_per_day * 10) * 0.3 +  # 30% weight on activity
            win_rate * 0.5 +  # 50% weight on win rate
            min(100, capital_utilization) * 0.2  # 20% weight on utilization
        ))
        
        return {
            'strategy_efficiency': efficiency,
            'trades_per_day': trades_per_day,
            'win_rate_efficiency': win_rate,
            'capital_utilization': capital_utilization
        }
    
    def calculate_growth_velocity(self) -> Dict[str, float]:
        """
        Calculate capital growth velocity (annualized growth rate).
        
        Uses compound growth formula for accurate annualization.
        
        Returns:
            Dictionary with growth velocity metrics
        """
        if not self.equity_history or len(self.equity_history) < 2:
            return {
                'growth_velocity': 0.0,
                'daily_growth_rate': 0.0,
                'monthly_growth_rate': 0.0,
                'annualized_growth_rate': 0.0
            }
        
        # Get first and last equity values
        first_equity = self.equity_history[0]['equity']
        last_equity = self.equity_history[-1]['equity']
        
        # Calculate time period
        first_time = datetime.fromisoformat(self.equity_history[0]['timestamp'])
        last_time = datetime.fromisoformat(self.equity_history[-1]['timestamp'])
        days_elapsed = (last_time - first_time).days
        days_elapsed = max(1, days_elapsed)
        
        # Total return
        total_return = ((last_equity - first_equity) / first_equity) if first_equity > 0 else 0
        
        # Daily growth rate (simple)
        daily_rate = (total_return / days_elapsed) * 100
        
        # Monthly growth rate (30 days)
        monthly_rate = daily_rate * 30
        
        # Annualized growth rate using compound formula
        # Formula: ((final/initial)^(365/days) - 1) * 100
        if first_equity > 0 and last_equity > 0:
            annualized_rate = ((last_equity / first_equity) ** (365 / days_elapsed) - 1) * 100
        else:
            annualized_rate = 0.0
        
        return {
            'growth_velocity': annualized_rate,
            'daily_growth_rate': daily_rate,
            'monthly_growth_rate': monthly_rate,
            'annualized_growth_rate': annualized_rate
        }
    
    def get_snapshot(self) -> CommandCenterSnapshot:
        """
        Get complete Command Center metrics snapshot.
        
        Returns:
            CommandCenterSnapshot with all metrics
        """
        with self.lock:
            # Calculate all metrics
            equity_metrics = self.calculate_equity_curve_metrics()
            risk_metrics = self.calculate_risk_heat()
            quality_metrics = self.calculate_trade_quality_score()
            signal_metrics = self.calculate_signal_accuracy()
            slippage_metrics = self.calculate_slippage_metrics()
            fee_metrics = self.calculate_fee_impact()
            efficiency_metrics = self.calculate_strategy_efficiency()
            growth_metrics = self.calculate_growth_velocity()
            
            return CommandCenterSnapshot(
                timestamp=datetime.now().isoformat(),
                # Equity curve
                equity=equity_metrics['equity'],
                equity_peak=equity_metrics['equity_peak'],
                equity_change_24h=equity_metrics['equity_change_24h'],
                equity_change_pct_24h=equity_metrics['equity_change_pct_24h'],
                # Risk heat
                risk_heat=risk_metrics['risk_heat'],
                risk_level=risk_metrics['risk_level'],
                max_drawdown_pct=risk_metrics['max_drawdown_pct'],
                current_drawdown_pct=risk_metrics['current_drawdown_pct'],
                position_concentration=risk_metrics['position_concentration'],
                # Trade quality
                trade_quality_score=quality_metrics['trade_quality_score'],
                trade_quality_grade=quality_metrics['trade_quality_grade'],
                win_rate=quality_metrics['win_rate'],
                profit_factor=quality_metrics['profit_factor'],
                avg_win_loss_ratio=quality_metrics['avg_win_loss_ratio'],
                # Signal accuracy
                signal_accuracy=signal_metrics['signal_accuracy'],
                signals_total=signal_metrics['signals_total'],
                signals_successful=signal_metrics['signals_successful'],
                signals_failed=signal_metrics['signals_failed'],
                false_positive_rate=signal_metrics['false_positive_rate'],
                # Slippage
                avg_slippage_bps=slippage_metrics['avg_slippage_bps'],
                avg_slippage_usd=slippage_metrics['avg_slippage_usd'],
                total_slippage_cost=slippage_metrics['total_slippage_cost'],
                slippage_impact_pct=slippage_metrics['slippage_impact_pct'],
                # Fee impact
                total_fees=fee_metrics['total_fees'],
                fees_pct_of_profit=fee_metrics['fees_pct_of_profit'],
                avg_fee_per_trade=fee_metrics['avg_fee_per_trade'],
                fee_efficiency_score=fee_metrics['fee_efficiency_score'],
                # Strategy efficiency
                strategy_efficiency=efficiency_metrics['strategy_efficiency'],
                trades_per_day=efficiency_metrics['trades_per_day'],
                win_rate_efficiency=efficiency_metrics['win_rate_efficiency'],
                capital_utilization=efficiency_metrics['capital_utilization'],
                # Growth velocity
                growth_velocity=growth_metrics['growth_velocity'],
                daily_growth_rate=growth_metrics['daily_growth_rate'],
                monthly_growth_rate=growth_metrics['monthly_growth_rate'],
                annualized_growth_rate=growth_metrics['annualized_growth_rate']
            )
    
    def get_equity_curve_data(self, hours: int = 24) -> List[Dict[str, Any]]:
        """
        Get equity curve data for charting.
        
        Args:
            hours: Number of hours of data to return
            
        Returns:
            List of data points with timestamp and equity
        """
        cutoff_time = datetime.now() - timedelta(hours=hours)
        
        result = []
        for snapshot in self.equity_history:
            timestamp = datetime.fromisoformat(snapshot['timestamp'])
            if timestamp >= cutoff_time:
                result.append({
                    'timestamp': snapshot['timestamp'],
                    'equity': snapshot['equity'],
                    'cash': snapshot['cash'],
                    'positions_value': snapshot['positions_value']
                })
        
        return result
    
    def _save_state(self):
        """Save metrics state to disk"""
        try:
            self.data_file.parent.mkdir(parents=True, exist_ok=True)
            
            state = {
                'initial_capital': self.initial_capital,
                'current_equity': self.current_equity,
                'equity_peak': self.equity_peak,
                'winning_trades': self.winning_trades,
                'losing_trades': self.losing_trades,
                'total_profit': self.total_profit,
                'total_loss': self.total_loss,
                'total_fees': self.total_fees,
                'signals_total': self.signals_total,
                'signals_successful': self.signals_successful,
                'signals_failed': self.signals_failed,
                'equity_history': list(self.equity_history),
                'trades': self.trades[-100:],  # Keep last 100 trades
                'slippage_data': self.slippage_data[-100:],  # Keep last 100
                'updated_at': datetime.now().isoformat()
            }
            
            with open(self.data_file, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save Command Center state: {e}")
    
    def _load_state(self):
        """Load metrics state from disk"""
        try:
            if self.data_file.exists():
                with open(self.data_file, 'r') as f:
                    state = json.load(f)
                
                # Validate and load with defaults
                self.initial_capital = max(0.0, state.get('initial_capital', self.initial_capital))
                self.current_equity = max(0.0, state.get('current_equity', self.current_equity))
                self.equity_peak = max(0.0, state.get('equity_peak', self.equity_peak))
                
                # Ensure peak >= current
                if self.equity_peak < self.current_equity:
                    self.equity_peak = self.current_equity
                
                # Load counts with validation
                self.winning_trades = max(0, state.get('winning_trades', 0))
                self.losing_trades = max(0, state.get('losing_trades', 0))
                self.total_profit = max(0.0, state.get('total_profit', 0.0))
                self.total_loss = max(0.0, state.get('total_loss', 0.0))
                self.total_fees = max(0.0, state.get('total_fees', 0.0))
                self.signals_total = max(0, state.get('signals_total', 0))
                self.signals_successful = max(0, state.get('signals_successful', 0))
                self.signals_failed = max(0, state.get('signals_failed', 0))
                
                # Load history with validation
                equity_history = state.get('equity_history', [])
                if isinstance(equity_history, list):
                    self.equity_history = deque(equity_history, maxlen=self.lookback_days * 24)
                
                trades = state.get('trades', [])
                if isinstance(trades, list):
                    self.trades = trades
                
                slippage_data = state.get('slippage_data', [])
                if isinstance(slippage_data, list):
                    self.slippage_data = slippage_data
                
                logger.info("✅ Loaded Command Center state from disk")
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Command Center state (corrupted JSON): {e}")
            logger.warning("Starting with fresh state")
        except Exception as e:
            logger.warning(f"Could not load Command Center state: {e}")


# Singleton instance
_command_center_metrics: Optional[CommandCenterMetrics] = None
_metrics_lock = threading.Lock()


def get_command_center_metrics(initial_capital: float = 1000.0, reset: bool = False) -> CommandCenterMetrics:
    """
    Get or create Command Center metrics singleton.
    
    Args:
        initial_capital: Initial capital (only used on first creation)
        reset: Force reset and create new instance
        
    Returns:
        CommandCenterMetrics instance
    """
    global _command_center_metrics
    
    with _metrics_lock:
        if _command_center_metrics is None or reset:
            _command_center_metrics = CommandCenterMetrics(initial_capital)
        
        return _command_center_metrics
