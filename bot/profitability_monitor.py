"""
NIJA Continuous Profitability Monitor - Runtime Profitability Tracking

CRITICAL TRUST MODULE - Monitors profitability in real-time and stops unprofitable trading.

This module:
    ✅ Recalculates expectancy every X trades
    ✅ Alerts on performance degradation
    ✅ Auto-downgrades to DRY_RUN if profitability violated
    ✅ Tracks win rate, average win/loss, expectancy
    ✅ Prevents sustained losses

Works with profitability_assertion.py (pre-trade check) to provide
comprehensive profitability protection.

Author: NIJA Trading Systems
Version: 1.0
Date: February 2026
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from enum import Enum

logger = logging.getLogger("nija.profitability_monitor")


class PerformanceStatus(Enum):
    """Performance status levels"""
    EXCELLENT = "EXCELLENT"  # Exceeding expectations
    GOOD = "GOOD"  # Meeting expectations
    ACCEPTABLE = "ACCEPTABLE"  # Within acceptable range
    WARNING = "WARNING"  # Degrading performance
    CRITICAL = "CRITICAL"  # Below minimum threshold
    FAILING = "FAILING"  # Sustained losses, auto-stop


@dataclass
class TradeRecord:
    """Record of a single trade"""
    trade_id: str
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    pnl_percent: float
    fees: float
    net_pnl: float
    timestamp: str
    was_winner: bool
    

@dataclass
class PerformanceMetrics:
    """Performance metrics calculated from trade history"""
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    average_win: float
    average_loss: float
    avg_win_loss_ratio: float
    expectancy: float
    profit_factor: float
    total_pnl: float
    total_fees: float
    net_pnl: float
    sharpe_ratio: Optional[float] = None
    max_drawdown: Optional[float] = None
    

@dataclass
class PerformanceAlert:
    """Performance alert"""
    alert_type: str
    severity: str
    message: str
    metrics: Dict[str, Any]
    timestamp: str
    action_taken: Optional[str] = None
    

class ProfitabilityMonitor:
    """
    Continuous profitability monitoring and enforcement.
    
    CRITICAL: Prevents sustained unprofitable trading.
    """
    
    # Monitoring configuration
    EVALUATION_FREQUENCY = 10  # Evaluate every N trades
    MIN_TRADES_FOR_EVALUATION = 20  # Minimum trades before evaluation
    
    # Performance thresholds
    MIN_WIN_RATE = 0.35  # 35% minimum win rate
    MIN_EXPECTANCY = 0.0  # Minimum expectancy (break-even)
    MIN_PROFIT_FACTOR = 1.0  # Minimum profit factor (break-even)
    WARNING_WIN_RATE = 0.40  # Warning threshold
    
    # Auto-downgrade thresholds
    MAX_CONSECUTIVE_LOSSES = 10
    MAX_DRAWDOWN_PERCENT = 20.0  # 20% max drawdown before auto-stop
    
    def __init__(self):
        """Initialize profitability monitor"""
        self._trade_history: List[TradeRecord] = []
        self._alerts: List[PerformanceAlert] = []
        self._last_evaluation_trade_count = 0
        self._consecutive_losses = 0
        self._peak_equity = 0.0
        self._is_monitoring_active = True
        
        logger.info("📊 Profitability Monitor initialized")
        
    def record_trade(
        self,
        trade_id: str,
        symbol: str,
        side: str,
        entry_price: float,
        exit_price: float,
        quantity: float,
        fees: float
    ) -> TradeRecord:
        """
        Record a completed trade.
        
        Args:
            trade_id: Unique trade identifier
            symbol: Trading pair
            side: 'buy' or 'sell' (entry side)
            entry_price: Entry price
            exit_price: Exit price
            quantity: Trade quantity
            fees: Total fees paid
            
        Returns:
            Trade record
        """
        # Calculate PnL
        if side == 'buy':
            # Long trade: profit when exit > entry
            pnl = (exit_price - entry_price) * quantity
        else:
            # Short trade: profit when exit < entry
            pnl = (entry_price - exit_price) * quantity
            
        pnl_percent = (pnl / (entry_price * quantity)) * 100
        net_pnl = pnl - fees
        was_winner = net_pnl > 0
        
        # Create trade record
        trade = TradeRecord(
            trade_id=trade_id,
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            exit_price=exit_price,
            quantity=quantity,
            pnl=pnl,
            pnl_percent=pnl_percent,
            fees=fees,
            net_pnl=net_pnl,
            timestamp=datetime.utcnow().isoformat(),
            was_winner=was_winner
        )
        
        # Store trade
        self._trade_history.append(trade)
        
        # Update consecutive losses
        if was_winner:
            self._consecutive_losses = 0
        else:
            self._consecutive_losses += 1
            
        # Log trade
        status = "✅ WIN" if was_winner else "❌ LOSS"
        logger.info(f"{status}: {symbol} {side.upper()} - Net P&L: {net_pnl:+.2f} ({pnl_percent:+.2f}%)")
        
        # Check if evaluation needed
        if self._should_evaluate():
            self._evaluate_performance()
            
        # Check for critical conditions
        self._check_critical_conditions()
        
        return trade
        
    def _should_evaluate(self) -> bool:
        """Check if performance evaluation is needed"""
        if len(self._trade_history) < self.MIN_TRADES_FOR_EVALUATION:
            return False
            
        trades_since_last = len(self._trade_history) - self._last_evaluation_trade_count
        return trades_since_last >= self.EVALUATION_FREQUENCY
        
    def _evaluate_performance(self):
        """Evaluate current performance"""
        logger.info("=" * 80)
        logger.info("📊 PERFORMANCE EVALUATION")
        logger.info("=" * 80)
        
        metrics = self.calculate_metrics()
        self._last_evaluation_trade_count = len(self._trade_history)
        
        # Calculate max drawdown specifically for last 100 trades
        metrics_100 = self.calculate_metrics(lookback=100)
        
        # Determine status
        status = self._determine_status(metrics)
        
        # Log metrics
        logger.info(f"   Total Trades: {metrics.total_trades}")
        logger.info(f"   Win Rate: {metrics.win_rate:.1f}%")
        logger.info(f"   Expectancy: {metrics.expectancy:.2f}")
        logger.info(f"   Max Drawdown (last 100 trades): ${metrics_100.max_drawdown:.2f}")
        logger.info(f"   Profit Factor: {metrics.profit_factor:.2f}")
        logger.info(f"   Avg Win/Loss Ratio: {metrics.avg_win_loss_ratio:.2f}")
        logger.info(f"   Net P&L: {metrics.net_pnl:+.2f}")
        logger.info(f"   Status: {status.value}")
        logger.info("=" * 80)
        
        # Check thresholds and alert
        if status in [PerformanceStatus.WARNING, PerformanceStatus.CRITICAL, PerformanceStatus.FAILING]:
            self._create_alert(status, metrics)
            
    def calculate_metrics(self, lookback: Optional[int] = None) -> PerformanceMetrics:
        """
        Calculate performance metrics.
        
        Args:
            lookback: Number of recent trades to analyze (None = all trades)
            
        Returns:
            Performance metrics
        """
        trades = self._trade_history[-lookback:] if lookback else self._trade_history
        
        if not trades:
            return PerformanceMetrics(
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate=0.0,
                average_win=0.0,
                average_loss=0.0,
                avg_win_loss_ratio=0.0,
                expectancy=0.0,
                profit_factor=0.0,
                total_pnl=0.0,
                total_fees=0.0,
                net_pnl=0.0
            )
            
        # Calculate basic stats
        total_trades = len(trades)
        winning_trades = sum(1 for t in trades if t.was_winner)
        losing_trades = total_trades - winning_trades
        win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0
        
        # Calculate average win/loss
        wins = [t.net_pnl for t in trades if t.was_winner]
        losses = [abs(t.net_pnl) for t in trades if not t.was_winner]
        
        average_win = sum(wins) / len(wins) if wins else 0
        average_loss = sum(losses) / len(losses) if losses else 0
        
        # Win/Loss ratio
        avg_win_loss_ratio = average_win / average_loss if average_loss > 0 else 0
        
        # Expectancy
        win_rate_decimal = win_rate / 100
        expectancy = (win_rate_decimal * average_win) - ((1 - win_rate_decimal) * average_loss)
        
        # Profit factor
        total_wins = sum(wins)
        total_losses = sum(losses)
        profit_factor = total_wins / total_losses if total_losses > 0 else float('inf')
        
        # Totals
        total_pnl = sum(t.pnl for t in trades)
        total_fees = sum(t.fees for t in trades)
        net_pnl = sum(t.net_pnl for t in trades)
        
        # Calculate Maximum Drawdown in dollars
        # Track cumulative P&L and find worst peak-to-trough decline
        max_drawdown = 0.0
        if trades:
            cumulative_pnl = 0.0
            peak = 0.0
            
            for trade in trades:
                cumulative_pnl += trade.net_pnl
                
                # Update peak if we've reached a new high
                if cumulative_pnl > peak:
                    peak = cumulative_pnl
                
                # Calculate current drawdown from peak (in dollars)
                drawdown = peak - cumulative_pnl
                
                # Track maximum drawdown
                if drawdown > max_drawdown:
                    max_drawdown = drawdown
        
        return PerformanceMetrics(
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            average_win=average_win,
            average_loss=average_loss,
            avg_win_loss_ratio=avg_win_loss_ratio,
            expectancy=expectancy,
            profit_factor=profit_factor,
            total_pnl=total_pnl,
            total_fees=total_fees,
            net_pnl=net_pnl,
            max_drawdown=max_drawdown
        )
        
    def _determine_status(self, metrics: PerformanceMetrics) -> PerformanceStatus:
        """Determine performance status from metrics"""
        # Failing: Negative expectancy and low win rate
        if metrics.expectancy < self.MIN_EXPECTANCY and metrics.win_rate < self.MIN_WIN_RATE:
            return PerformanceStatus.FAILING
            
        # Critical: Below minimum thresholds
        if metrics.profit_factor < self.MIN_PROFIT_FACTOR:
            return PerformanceStatus.CRITICAL
            
        # Warning: Approaching thresholds
        if metrics.win_rate < self.WARNING_WIN_RATE:
            return PerformanceStatus.WARNING
            
        # Good: Meeting expectations
        if metrics.expectancy > 0 and metrics.profit_factor > 1.2:
            return PerformanceStatus.GOOD
            
        # Excellent: Exceeding expectations
        if metrics.expectancy > 1.0 and metrics.profit_factor > 2.0 and metrics.win_rate > 50:
            return PerformanceStatus.EXCELLENT
            
        # Default: Acceptable
        return PerformanceStatus.ACCEPTABLE
        
    def _create_alert(self, status: PerformanceStatus, metrics: PerformanceMetrics):
        """Create performance alert"""
        if status == PerformanceStatus.FAILING:
            message = (
                f"CRITICAL: Strategy is failing. "
                f"Win rate: {metrics.win_rate:.1f}%, "
                f"Expectancy: {metrics.expectancy:.2f}. "
                f"Auto-downgrading to DRY_RUN mode."
            )
            severity = "CRITICAL"
            action = "AUTO_DOWNGRADE_TO_DRY_RUN"
            
        elif status == PerformanceStatus.CRITICAL:
            message = (
                f"CRITICAL: Profit factor below minimum. "
                f"Profit factor: {metrics.profit_factor:.2f} "
                f"(minimum: {self.MIN_PROFIT_FACTOR})"
            )
            severity = "CRITICAL"
            action = "MANUAL_REVIEW_REQUIRED"
            
        elif status == PerformanceStatus.WARNING:
            message = (
                f"WARNING: Performance degradation detected. "
                f"Win rate: {metrics.win_rate:.1f}% "
                f"(threshold: {self.WARNING_WIN_RATE*100:.1f}%)"
            )
            severity = "WARNING"
            action = "MONITOR_CLOSELY"
            
        else:
            return  # No alert needed
            
        alert = PerformanceAlert(
            alert_type=status.value,
            severity=severity,
            message=message,
            metrics=asdict(metrics),
            timestamp=datetime.utcnow().isoformat(),
            action_taken=action
        )
        
        self._alerts.append(alert)
        
        # Log alert prominently
        logger.error("=" * 80)
        logger.error(f"🚨 PERFORMANCE ALERT: {severity}")
        logger.error("=" * 80)
        logger.error(f"   {message}")
        logger.error(f"   Action: {action}")
        logger.error("=" * 80)
        
        # Execute action
        if action == "AUTO_DOWNGRADE_TO_DRY_RUN":
            self._auto_downgrade_to_dry_run(alert)
            
    def _check_critical_conditions(self):
        """Check for critical conditions that require immediate action"""
        # Check consecutive losses
        if self._consecutive_losses >= self.MAX_CONSECUTIVE_LOSSES:
            logger.error(f"🚨 MAX CONSECUTIVE LOSSES REACHED: {self._consecutive_losses}")
            
            alert = PerformanceAlert(
                alert_type="CONSECUTIVE_LOSSES",
                severity="CRITICAL",
                message=f"Reached {self._consecutive_losses} consecutive losses",
                metrics={'consecutive_losses': self._consecutive_losses},
                timestamp=datetime.utcnow().isoformat(),
                action_taken="AUTO_DOWNGRADE_TO_DRY_RUN"
            )
            self._alerts.append(alert)
            self._auto_downgrade_to_dry_run(alert)
            
    def _auto_downgrade_to_dry_run(self, alert: PerformanceAlert):
        """Automatically downgrade to DRY_RUN mode due to poor performance"""
        logger.critical("=" * 80)
        logger.critical("🚨 AUTO-DOWNGRADING TO DRY_RUN MODE")
        logger.critical("=" * 80)
        logger.critical(f"   Reason: {alert.message}")
        logger.critical("   Live trading will be paused to protect capital")
        logger.critical("=" * 80)
        
        try:
            from bot.trading_state_machine import get_state_machine, TradingState
            state_machine = get_state_machine()
            
            if state_machine.is_live_trading_active():
                state_machine.transition_to(
                    TradingState.DRY_RUN,
                    f"Auto-downgrade due to poor performance: {alert.alert_type}"
                )
                logger.critical("✅ Successfully downgraded to DRY_RUN mode")
            else:
                logger.warning("⚠️  Already in non-live mode, no downgrade needed")
                
        except Exception as e:
            logger.error(f"❌ Error downgrading to DRY_RUN: {e}")
            logger.error("   Manual intervention required!")
            
    def get_recent_performance(self, lookback: int = 50) -> PerformanceMetrics:
        """Get recent performance metrics"""
        return self.calculate_metrics(lookback=lookback)
        
    def get_alerts(self, limit: int = 10) -> List[PerformanceAlert]:
        """Get recent alerts"""
        return self._alerts[-limit:] if self._alerts else []
        
    def is_performance_acceptable(self) -> bool:
        """Check if current performance is acceptable"""
        if len(self._trade_history) < self.MIN_TRADES_FOR_EVALUATION:
            return True  # Not enough data yet
            
        metrics = self.calculate_metrics()
        status = self._determine_status(metrics)
        
        return status not in [PerformanceStatus.FAILING, PerformanceStatus.CRITICAL]
        
    def reset_monitoring(self):
        """Reset monitoring (use with caution)"""
        logger.warning("⚠️  Resetting profitability monitoring")
        self._trade_history.clear()
        self._alerts.clear()
        self._consecutive_losses = 0
        self._last_evaluation_trade_count = 0


# Global singleton instance
_profitability_monitor: Optional[ProfitabilityMonitor] = None


def get_profitability_monitor() -> ProfitabilityMonitor:
    """Get the global profitability monitor instance (singleton)"""
    global _profitability_monitor
    
    if _profitability_monitor is None:
        _profitability_monitor = ProfitabilityMonitor()
        
    return _profitability_monitor


# Example usage and testing
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("\n=== Profitability Monitor Test ===\n")
    
    monitor = get_profitability_monitor()
    
    # Simulate some trades
    print("--- Simulating trades ---")
    
    # Some winners
    for i in range(5):
        monitor.record_trade(
            trade_id=f"trade_{i}",
            symbol="BTC-USD",
            side="buy",
            entry_price=45000.0,
            exit_price=45500.0,  # Winner
            quantity=0.1,
            fees=5.0
        )
        
    # Some losers
    for i in range(5, 8):
        monitor.record_trade(
            trade_id=f"trade_{i}",
            symbol="BTC-USD",
            side="buy",
            entry_price=45000.0,
            exit_price=44700.0,  # Loser
            quantity=0.1,
            fees=5.0
        )
        
    # Get metrics
    print("\n--- Performance Metrics ---")
    metrics = monitor.calculate_metrics()
    print(f"  Win Rate: {metrics.win_rate:.1f}%")
    print(f"  Expectancy: {metrics.expectancy:.2f}")
    print(f"  Profit Factor: {metrics.profit_factor:.2f}")
    print(f"  Net P&L: {metrics.net_pnl:+.2f}")
