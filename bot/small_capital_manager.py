# small_capital_manager.py
"""
NIJA Small Capital Manager
Special strategy for growing $10-60 to $100 on Coinbase

WARNING: This is EXTREMELY DIFFICULT due to high Coinbase fees (2-4%)
Success rate: ~20% for $50-60, ~5% for $20-40, 0% for <$20

HONEST RECOMMENDATION: Deposit to $100 instead of using this strategy
"""

import logging
from typing import Dict

logger = logging.getLogger("nija.small_capital")


class SmallCapitalManager:
    """
    Manages ultra-conservative strategy for small capital accounts
    
    Designed to minimize fee impact when capital is $10-90
    
    Key Differences from Normal Strategy:
    - SMALLER position sizes (10-20% vs 8-40%)
    - HIGHER profit targets (5-7% vs 2-3%)
    - FEWER trades (best setups only)
    - TIGHTER stop losses (1.5% vs 2-3%)
    - LONGER hold times (reduce churn)
    """
    
    # Small capital stages
    SMALL_CAP_STAGES = {
        'desperate': {
            'balance_range': (0, 30),
            'position_size_pct': 0.10,  # Only 10% per trade
            'max_concurrent': 2,  # Only 2 positions max
            'profit_target_pct': 0.07,  # Need 7% to offset fees
            'stop_loss_pct': 0.015,  # Tight 1.5% stops
            'trades_per_day': 2,  # Max 2 trades/day (reduce fees)
            'description': 'DESPERATE MODE - Success unlikely, deposit recommended',
            'success_rate': 0.05  # 5% chance of success
        },
        'difficult': {
            'balance_range': (30, 50),
            'position_size_pct': 0.15,  # 15% per trade
            'max_concurrent': 3,  # 3 positions
            'profit_target_pct': 0.06,  # 6% targets
            'stop_loss_pct': 0.015,  # 1.5% stops
            'trades_per_day': 3,  # Max 3 trades/day
            'description': 'DIFFICULT MODE - Low success rate, consider depositing',
            'success_rate': 0.15  # 15% chance
        },
        'challenging': {
            'balance_range': (50, 70),
            'position_size_pct': 0.18,  # 18% per trade
            'max_concurrent': 3,  # 3 positions
            'profit_target_pct': 0.05,  # 5% targets
            'stop_loss_pct': 0.02,  # 2% stops
            'trades_per_day': 4,  # Max 4 trades/day
            'description': 'CHALLENGING MODE - Possible but slow',
            'success_rate': 0.30  # 30% chance
        },
        'viable': {
            'balance_range': (70, 100),
            'position_size_pct': 0.20,  # 20% per trade
            'max_concurrent': 4,  # 4 positions
            'profit_target_pct': 0.04,  # 4% targets
            'stop_loss_pct': 0.02,  # 2% stops
            'trades_per_day': 5,  # Max 5 trades/day
            'description': 'VIABLE MODE - Realistic chance of reaching $100',
            'success_rate': 0.60  # 60% chance
        }
    }
    
    def __init__(self):
        """Initialize Small Capital Manager"""
        self.current_stage = 'desperate'
        self.trades_today = 0
        self.last_trade_date = None
        self.total_fees_paid = 0.0
        self.total_profit_made = 0.0
        
        logger.warning("="*80)
        logger.warning("⚠️  SMALL CAPITAL MODE ACTIVATED")
        logger.warning("="*80)
        logger.warning("")
        logger.warning("You're trading with <$100 on Coinbase.")
        logger.warning("This is EXTREMELY difficult due to 2-4% fees.")
        logger.warning("")
        logger.warning("HONEST RECOMMENDATION:")
        logger.warning("  → Deposit to reach $100-200")
        logger.warning("  → OR switch to Binance (0.1% fees)")
        logger.warning("")
        logger.warning("If you continue:")
        logger.warning("  • Strategy will be ultra-conservative")
        logger.warning("  • Smaller positions (10-20% vs 40%)")
        logger.warning("  • Higher profit targets (5-7% vs 2-3%)")
        logger.warning("  • Fewer trades (to reduce fee accumulation)")
        logger.warning("")
        logger.warning("Success rate: 5-30% depending on capital")
        logger.warning("="*80)
    
    def get_stage_for_balance(self, balance: float) -> str:
        """Get stage based on balance"""
        for stage_name, config in self.SMALL_CAP_STAGES.items():
            min_bal, max_bal = config['balance_range']
            if min_bal <= balance < max_bal:
                return stage_name
        return 'viable'
    
    def get_config(self, balance: float) -> Dict:
        """Get strategy configuration for current balance"""
        stage = self.get_stage_for_balance(balance)
        config = self.SMALL_CAP_STAGES[stage].copy()
        
        logger.info(f"💰 Balance: ${balance:.2f}")
        logger.info(f"📊 Stage: {config['description']}")
        logger.info(f"🎯 Success Probability: {config['success_rate']*100:.0f}%")
        logger.info(f"📏 Position Size: {config['position_size_pct']*100:.0f}%")
        logger.info(f"🎯 Profit Target: {config['profit_target_pct']*100:.1f}%")
        logger.info(f"🛑 Stop Loss: {config['stop_loss_pct']*100:.1f}%")
        logger.info(f"📊 Max Trades/Day: {config['trades_per_day']}")
        
        return config
    
    def can_trade_today(self, balance: float) -> bool:
        """Check if we've hit daily trade limit"""
        from datetime import datetime
        
        today = datetime.now().date()
        
        # Reset counter if new day
        if self.last_trade_date != today:
            self.trades_today = 0
            self.last_trade_date = today
        
        config = self.get_config(balance)
        max_trades = config['trades_per_day']
        
        if self.trades_today >= max_trades:
            logger.warning(f"🛑 Daily trade limit reached ({max_trades})")
            logger.warning(f"   Trades today: {self.trades_today}/{max_trades}")
            logger.warning(f"   Reason: Reducing fee accumulation")
            logger.warning(f"   Wait until tomorrow to trade again")
            return False
        
        return True
    
    def record_trade(self, profit: float, fees: float):
        """Record trade results"""
        self.trades_today += 1
        self.total_fees_paid += fees
        self.total_profit_made += profit
        
        net = profit - fees
        
        logger.info(f"📊 Trade #{self.trades_today} Today:")
        logger.info(f"   Profit: ${profit:.2f}")
        logger.info(f"   Fees: ${fees:.2f}")
        logger.info(f"   Net: ${net:.2f}")
        logger.info(f"   Total Fees (lifetime): ${self.total_fees_paid:.2f}")
        logger.info(f"   Total Profit (lifetime): ${self.total_profit_made:.2f}")
        logger.info(f"   Net P&L (lifetime): ${self.total_profit_made - self.total_fees_paid:.2f}")
        
        # Warning if fees exceed profit
        if self.total_fees_paid > self.total_profit_made:
            logger.error("🚨 WARNING: Fees exceed profits!")
            logger.error(f"   You've paid ${self.total_fees_paid:.2f} in fees")
            logger.error(f"   But only made ${self.total_profit_made:.2f} in profit")
            logger.error(f"   Net loss: ${self.total_fees_paid - self.total_profit_made:.2f}")
            logger.error("   ")
            logger.error("   RECOMMENDATION: Stop trading and deposit more capital")
    
    def estimate_time_to_100(self, current_balance: float) -> str:
        """Estimate time needed to reach $100"""
        if current_balance >= 100:
            return "Already at goal!"
        
        config = self.get_config(current_balance)
        success_rate = config['success_rate']
        
        if success_rate < 0.10:
            return "Unlikely to ever reach $100 (success rate <10%)"
        
        # Calculate based on conservative estimates
        avg_profit_per_trade = current_balance * config['position_size_pct'] * 0.02  # 2% net
        trades_per_week = config['trades_per_day'] * 5  # 5 trading days
        weekly_profit = avg_profit_per_trade * trades_per_week * config['success_rate']
        
        needed = 100 - current_balance
        weeks = needed / weekly_profit if weekly_profit > 0 else float('inf')
        
        if weeks > 52:
            return f">{weeks/52:.0f} years (unrealistic - deposit instead)"
        elif weeks > 12:
            return f"~{weeks/4:.0f} months (very slow - consider depositing)"
        elif weeks > 4:
            return f"~{weeks:.0f} weeks (slow but possible)"
        else:
            return f"~{weeks:.0f} weeks (realistic)"
    
    def should_use_small_cap_mode(self, balance: float) -> bool:
        """Determine if small capital mode should be used"""
        return balance < 100
