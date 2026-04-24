"""
NIJA KPI Dashboard Integration Example

Demonstrates how to integrate KPI tracking, risk alarms, and performance
monitoring into a trading bot.

This example shows:
1. Initializing all components
2. Recording trades
3. Monitoring alarms
4. Accessing dashboard data
5. Generating reports

Author: NIJA Trading Systems
Date: January 30, 2026
"""

import time
import logging
from datetime import datetime

# Import KPI components
try:
    from kpi_tracker import get_kpi_tracker
    from risk_alarm_system import get_risk_alarm_system
    from performance_tracking_service import get_tracking_service
except ImportError:
    from bot.kpi_tracker import get_kpi_tracker
    from bot.risk_alarm_system import get_risk_alarm_system
    from bot.performance_tracking_service import get_tracking_service

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
TRADING_FEE_RATE = 0.001  # 0.1% trading fee
EXAMPLE_BTC_PRICE = 45000.0  # Simplified BTC price for examples


class TradingBotWithKPI:
    """
    Example trading bot with integrated KPI tracking, risk alarms,
    and performance monitoring.
    """
    
    def __init__(self, initial_capital: float = 1000.0):
        """
        Initialize trading bot with performance tracking.
        
        Args:
            initial_capital: Starting capital
        """
        self.initial_capital = initial_capital
        self.current_balance = initial_capital
        self.current_equity = initial_capital
        
        # Initialize performance tracking service
        self.tracking_service = get_tracking_service(initial_capital=initial_capital)
        
        # Set up data providers for automated tracking
        self.tracking_service.set_balance_provider(self.get_balance)
        self.tracking_service.set_equity_provider(self.get_equity)
        
        # Get direct access to components if needed
        self.kpi_tracker = get_kpi_tracker()
        self.alarm_system = get_risk_alarm_system()
        
        # Set up alarm callback
        self.alarm_system.register_callback(self.on_alarm)
        
        # Trading state
        self.is_trading = True
        self.trades_today = 0
        
        logger.info(f"✅ Trading bot initialized with ${initial_capital:,.2f}")
    
    def get_balance(self) -> float:
        """Get current balance (called by tracking service)"""
        return self.current_balance
    
    def get_equity(self) -> float:
        """Get current equity (called by tracking service)"""
        return self.current_equity
    
    def on_alarm(self, alarm):
        """
        Handle alarm events.
        
        This callback is triggered whenever an alarm is raised.
        
        Args:
            alarm: Alarm object
        """
        logger.warning(f"🚨 ALARM: [{alarm.severity}] {alarm.message}")
        
        # Take action based on alarm
        if alarm.severity == "CRITICAL":
            if alarm.category == "BALANCE":
                logger.critical("⛔ Critical balance - stopping trading!")
                self.is_trading = False
            elif alarm.category == "DRAWDOWN":
                logger.critical("⛔ Critical drawdown - reducing position sizes!")
                # Could reduce position sizes here
        
        elif alarm.severity == "WARNING":
            if alarm.category == "TRADE_PERFORMANCE":
                logger.warning("⚠️ Performance warning - reviewing strategy")
                # Could switch strategies or adjust parameters
    
    def execute_trade(self, symbol: str, strategy: str, direction: str,
                      entry_price: float, position_size: float):
        """
        Simulate executing a trade.
        
        Args:
            symbol: Trading symbol
            strategy: Strategy name
            direction: 'long' or 'short'
            entry_price: Entry price
            position_size: Position size
            
        Returns:
            Trade result dictionary
        """
        if not self.is_trading:
            logger.warning("Trading paused due to alarms")
            return None
        
        # Simulate trade execution
        import random
        
        # Simulate price movement (random for demo)
        price_change_pct = random.uniform(-2, 3)  # Bias towards profit
        exit_price = entry_price * (1 + price_change_pct / 100)
        
        # Calculate profit/loss
        if direction == 'long':
            profit_pct = (exit_price - entry_price) / entry_price
        else:
            profit_pct = (entry_price - exit_price) / entry_price
        
        profit = position_size * entry_price * profit_pct
        fees = position_size * entry_price * TRADING_FEE_RATE
        net_profit = profit - fees
        is_win = net_profit > 0
        
        # Update balance
        self.current_balance += net_profit
        self.current_equity = self.current_balance
        
        # Record trade in tracking service
        self.tracking_service.record_trade(
            symbol=symbol,
            strategy=strategy,
            profit=profit,
            fees=fees,
            is_win=is_win,
            entry_price=entry_price,
            exit_price=exit_price,
            position_size=position_size
        )
        
        self.trades_today += 1
        
        result = {
            'symbol': symbol,
            'strategy': strategy,
            'direction': direction,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'position_size': position_size,
            'profit': profit,
            'fees': fees,
            'net_profit': net_profit,
            'is_win': is_win
        }
        
        logger.info(f"{'🟢' if is_win else '🔴'} Trade: {symbol} {direction} "
                   f"${net_profit:+.2f} (Balance: ${self.current_balance:.2f})")
        
        return result
    
    def get_dashboard_summary(self):
        """Get comprehensive dashboard summary"""
        summary = self.tracking_service.get_current_summary()
        
        print("\n" + "="*70)
        print("TRADING BOT DASHBOARD")
        print("="*70)
        
        # KPIs
        kpis = summary['kpis']
        if 'error' not in kpis:
            print("\n📊 KEY PERFORMANCE INDICATORS")
            print(f"  Total Trades:     {kpis['total_trades']}")
            print(f"  Win Rate:         {kpis['win_rate']:.1f}%")
            print(f"  Profit Factor:    {kpis['profit_factor']:.2f}")
            print(f"  Net Profit:       ${kpis['net_profit']:+.2f}")
            print(f"  ROI:              {kpis['roi_percentage']:+.2f}%")
            print(f"  Sharpe Ratio:     {kpis['sharpe_ratio']:.2f}")
            print(f"  Max Drawdown:     {kpis['max_drawdown']:.1f}%")
            print(f"  Best Strategy:    {kpis['best_strategy']}")
        
        # Alarms
        alarm_summary = summary['alarms']
        print(f"\n🚨 ACTIVE ALARMS: {alarm_summary['total_active']}")
        if alarm_summary['total_active'] > 0:
            for severity, count in alarm_summary['active_by_severity'].items():
                if count > 0:
                    print(f"  {severity}: {count}")
        
        # Service status
        service = summary['service']
        print(f"\n⚙️ SERVICE STATUS")
        print(f"  Running:          {service['running']}")
        print(f"  Updates:          {service['updates_count']}")
        print(f"  KPI Calculations: {service['kpi_calculations_count']}")
        
        print("\n" + "="*70 + "\n")
        
        return summary
    
    def run_simulation(self, num_trades: int = 20):
        """
        Run a trading simulation.
        
        Args:
            num_trades: Number of trades to simulate
        """
        logger.info(f"🚀 Starting trading simulation with {num_trades} trades")
        
        # Start performance tracking service
        self.tracking_service.start()
        
        # Simulate trading
        symbols = ["BTC-USD", "ETH-USD", "SOL-USD", "AVAX-USD"]
        strategies = ["APEX_V71", "DUAL_RSI", "MOMENTUM"]
        
        import random
        
        for i in range(num_trades):
            symbol = random.choice(symbols)
            strategy = random.choice(strategies)
            direction = random.choice(["long", "short"])
            
            # Determine position size based on balance
            position_size_pct = random.uniform(0.02, 0.05)  # 2-5% of balance
            position_size = (self.current_balance * position_size_pct) / EXAMPLE_BTC_PRICE
            
            # Execute trade
            self.execute_trade(
                symbol=symbol,
                strategy=strategy,
                direction=direction,
                entry_price=EXAMPLE_BTC_PRICE,
                position_size=position_size
            )
            
            # Small delay
            time.sleep(0.1)
        
        # Wait a moment for tracking service to process
        time.sleep(2)
        
        # Manually trigger KPI calculation for demonstration
        logger.info("📊 Calculating final KPIs...")
        final_kpis = self.kpi_tracker.calculate_kpis(
            self.current_balance, 
            self.current_equity
        )
        
        # Show dashboard
        self.get_dashboard_summary()
        
        # Export report
        logger.info("📄 Exporting performance report...")
        report_path = self.tracking_service.export_report()
        logger.info(f"✅ Report saved to: {report_path}")
        
        # Stop service
        self.tracking_service.stop()
        
        logger.info("✅ Simulation complete!")


def main():
    """Main entry point"""
    print("="*70)
    print("NIJA KPI Dashboard Integration Example")
    print("="*70)
    print()
    
    # Create trading bot with KPI tracking
    bot = TradingBotWithKPI(initial_capital=1000.0)
    
    # Run simulation
    bot.run_simulation(num_trades=30)
    
    print("\n💡 Next Steps:")
    print("  1. Check the exported report in /tmp/nija_reports/")
    print("  2. Review KPI snapshots in /tmp/nija_kpis/")
    print("  3. Check alarm history in /tmp/nija_alarms/")
    print("  4. Integrate with your actual trading bot")
    print()


if __name__ == "__main__":
    main()
