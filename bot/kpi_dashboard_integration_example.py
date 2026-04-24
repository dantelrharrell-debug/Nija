"""
NIJA KPI Dashboard Integration Example

Demonstrates how to integrate KPI tracking, performance monitoring,
and risk alarms into your trading bot.

Author: NIJA Trading Systems
Date: January 30, 2026
"""

import logging
import time
from datetime import datetime
from typing import List, Dict, Any

# Import KPI components
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from kpi_tracker import get_kpi_tracker
from automated_performance_tracker import get_performance_tracker
from risk_alarm_system import get_risk_alarm_system, RiskAlarm

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TradingBotWithKPI:
    """
    Example trading bot with integrated KPI tracking,
    performance monitoring, and risk alarms
    """
    
    def __init__(self, initial_capital: float = 10000.0):
        """Initialize bot with KPI components"""
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.cash_balance = initial_capital
        self.positions: List[Dict[str, Any]] = []
        self.trades: List[Dict[str, Any]] = []
        
        # Initialize KPI components
        logger.info("🚀 Initializing KPI Dashboard components...")
        
        self.kpi_tracker = get_kpi_tracker(initial_capital=initial_capital)
        self.performance_tracker = get_performance_tracker(
            update_interval=10,   # Update every 10 seconds for demo
            report_interval=60    # Report every minute for demo
        )
        self.alarm_system = get_risk_alarm_system()
        
        # Configure performance tracker callbacks
        self.performance_tracker.set_account_callbacks(
            account_value_fn=self.get_account_value,
            cash_balance_fn=self.get_cash_balance,
            positions_fn=self.get_positions,
            unrealized_pnl_fn=self.get_unrealized_pnl,
            realized_pnl_fn=self.get_realized_pnl
        )
        
        # Register alarm notification callback
        self.alarm_system.add_notification_callback(self.handle_risk_alarm)
        
        # Start automated performance tracking
        self.performance_tracker.start()
        
        logger.info("✅ KPI Dashboard components initialized and started")
    
    # Account state methods (callbacks for performance tracker)
    
    def get_account_value(self) -> float:
        """Get total account value"""
        positions_value = sum(p['value'] for p in self.positions)
        return self.cash_balance + positions_value
    
    def get_cash_balance(self) -> float:
        """Get available cash"""
        return self.cash_balance
    
    def get_positions(self) -> List[Dict[str, Any]]:
        """Get active positions"""
        return self.positions
    
    def get_unrealized_pnl(self) -> float:
        """Get total unrealized P&L"""
        return sum(p.get('unrealized_pnl', 0) for p in self.positions)
    
    def get_realized_pnl(self) -> float:
        """Get total realized P&L"""
        return sum(t.get('pnl', 0) for t in self.trades)
    
    # Trading methods
    
    def execute_trade(
        self,
        symbol: str,
        entry_price: float,
        exit_price: float,
        quantity: float,
        side: str = 'long'
    ):
        """
        Simulate trade execution
        
        Args:
            symbol: Trading pair
            entry_price: Entry price
            exit_price: Exit price
            quantity: Position size
            side: 'long' or 'short'
        """
        # Calculate P&L
        if side == 'long':
            pnl = (exit_price - entry_price) * quantity
        else:
            pnl = (entry_price - exit_price) * quantity
        
        fees = abs(entry_price * quantity * 0.001)  # 0.1% fee
        pnl_after_fees = pnl - fees
        
        # Update account
        self.cash_balance += pnl_after_fees
        
        # Record trade
        trade = {
            'symbol': symbol,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'quantity': quantity,
            'side': side,
            'pnl': pnl_after_fees,
            'fees': fees,
            'entry_time': datetime.now(),
            'exit_time': datetime.now(),
            'timestamp': datetime.now()
        }
        self.trades.append(trade)
        
        # Record in KPI tracker
        self.kpi_tracker.record_trade(
            symbol=symbol,
            entry_price=entry_price,
            exit_price=exit_price,
            quantity=quantity,
            side=side,
            pnl=pnl_after_fees,
            entry_time=trade['entry_time'],
            exit_time=trade['exit_time'],
            fees=fees
        )
        
        # Check risk alarms after trade
        self.alarm_system.check_all_risks()
        
        # Log trade result
        emoji = "✅" if pnl_after_fees > 0 else "❌"
        logger.info(
            f"{emoji} Trade: {symbol} {side} - "
            f"Entry: ${entry_price:,.2f}, Exit: ${exit_price:,.2f}, "
            f"P&L: ${pnl_after_fees:,.2f}"
        )
    
    def handle_risk_alarm(self, alarm: RiskAlarm):
        """
        Handle risk alarm notifications
        
        Args:
            alarm: Risk alarm that triggered
        """
        # Log the alarm
        logger.warning(f"🚨 RISK ALARM: {alarm.message}")
        logger.warning(f"   Level: {alarm.level}")
        logger.warning(f"   Recommended Action: {alarm.recommended_action}")
        
        # Take action based on alarm level
        if alarm.level == 'EMERGENCY':
            logger.critical("⛔ EMERGENCY ALARM - STOPPING ALL TRADING")
            # In real bot, you would stop trading here
            
        elif alarm.level == 'CRITICAL':
            logger.error("⚠️ CRITICAL ALARM - Review positions immediately")
            # In real bot, you might reduce position sizes
    
    def print_kpi_summary(self):
        """Print current KPI summary"""
        summary = self.kpi_tracker.get_kpi_summary()
        
        if summary.get('status') != 'active':
            logger.info("No KPI data available yet")
            return
        
        logger.info("\n" + "="*60)
        logger.info("📊 KPI DASHBOARD SUMMARY")
        logger.info("="*60)
        
        # Returns
        returns = summary.get('returns', {})
        logger.info(f"Total Return:   {returns.get('total', 0):.2f}%")
        logger.info(f"Daily Return:   {returns.get('daily', 0):.2f}%")
        logger.info(f"Monthly Return: {returns.get('monthly', 0):.2f}%")
        
        # Risk metrics
        risk = summary.get('risk_metrics', {})
        logger.info(f"\nSharpe Ratio:    {risk.get('sharpe_ratio', 0):.2f}")
        logger.info(f"Sortino Ratio:   {risk.get('sortino_ratio', 0):.2f}")
        logger.info(f"Max Drawdown:    {risk.get('max_drawdown', 0):.2f}%")
        
        # Trade stats
        trades = summary.get('trade_stats', {})
        logger.info(f"\nTotal Trades:    {trades.get('total_trades', 0)}")
        logger.info(f"Win Rate:        {trades.get('win_rate', 0):.1f}%")
        logger.info(f"Profit Factor:   {trades.get('profit_factor', 0):.2f}")
        
        # Account
        account = summary.get('account', {})
        logger.info(f"\nAccount Value:   ${account.get('value', 0):,.2f}")
        logger.info(f"Cash Balance:    ${account.get('cash', 0):,.2f}")
        
        # Active alarms
        active_alarms = self.alarm_system.get_active_alarms()
        if active_alarms:
            logger.info(f"\n🚨 Active Alarms: {len(active_alarms)}")
            for alarm in active_alarms:
                logger.info(f"   - [{alarm.level}] {alarm.alarm_type}")
        
        logger.info("="*60 + "\n")
    
    def shutdown(self):
        """Shutdown bot and KPI components"""
        logger.info("Shutting down...")
        self.performance_tracker.stop()
        logger.info("✅ Shutdown complete")


def main():
    """Main demo function"""
    logger.info("🚀 Starting NIJA KPI Dashboard Demo")
    logger.info("="*60)
    
    # Create bot with KPI tracking
    bot = TradingBotWithKPI(initial_capital=10000.0)
    
    # Simulate some trades
    logger.info("\n📈 Simulating trades...")
    
    # Winning trades
    bot.execute_trade('BTC-USD', 50000, 51000, 0.1, 'long')   # Win
    time.sleep(1)
    
    bot.execute_trade('ETH-USD', 3000, 3100, 1.0, 'long')     # Win
    time.sleep(1)
    
    bot.execute_trade('BTC-USD', 51000, 50500, 0.1, 'short')  # Loss
    time.sleep(1)
    
    bot.execute_trade('ETH-USD', 3100, 3200, 1.0, 'long')     # Win
    time.sleep(1)
    
    # Print KPI summary
    logger.info("\n" + "="*60)
    bot.print_kpi_summary()
    
    # Let performance tracker run for a bit
    logger.info("⏱️ Running performance tracker for 30 seconds...")
    logger.info("(You should see periodic updates)")
    
    for i in range(6):
        time.sleep(5)
        
        # Get current status
        status = bot.performance_tracker.get_status()
        logger.info(
            f"Update #{status['update_count']}: "
            f"Last: {status.get('last_update', 'N/A')}"
        )
    
    # Final summary
    bot.print_kpi_summary()
    
    # Shutdown
    bot.shutdown()
    
    logger.info("\n✅ Demo complete!")


if __name__ == "__main__":
    main()
