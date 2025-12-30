"""
NIJA Optimized Settings Integration
Integrates daily target config, exchange profiles, and capital allocation

This module provides a unified interface for the optimization features:
1. Daily profit target optimization
2. Exchange-specific risk profiles
3. Multi-exchange capital allocation

Author: NIJA Trading Systems
Version: 1.0
Date: December 30, 2025
"""

import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nija.optimized_settings")

# Import optimization modules
try:
    from daily_target_config import (
        get_optimal_settings_for_balance,
        get_scaled_daily_target,
        print_daily_target_summary
    )
    DAILY_TARGET_AVAILABLE = True
except ImportError:
    logger.warning("⚠️ daily_target_config not available")
    DAILY_TARGET_AVAILABLE = False

try:
    from exchange_risk_profiles import (
        get_exchange_risk_profile,
        get_all_exchange_profiles,
        get_best_exchange_for_balance,
        compare_exchange_profiles
    )
    EXCHANGE_PROFILES_AVAILABLE = True
except ImportError:
    logger.warning("⚠️ exchange_risk_profiles not available")
    EXCHANGE_PROFILES_AVAILABLE = False

try:
    from multi_exchange_allocator import (
        MultiExchangeCapitalAllocator,
        AllocationStrategy,
        get_recommended_allocation
    )
    MULTI_EXCHANGE_AVAILABLE = True
except ImportError:
    logger.warning("⚠️ multi_exchange_allocator not available")
    MULTI_EXCHANGE_AVAILABLE = False


# ============================================================================
# UNIFIED OPTIMIZATION ENGINE
# ============================================================================

class OptimizedSettingsManager:
    """
    Unified manager for all optimization features.
    
    Combines:
    - Daily profit target optimization
    - Exchange-specific risk profiles
    - Multi-exchange capital allocation
    """
    
    def __init__(self, 
                 account_balance: float,
                 available_exchanges: Optional[List[str]] = None,
                 daily_target_usd: float = 25.00,
                 allocation_strategy: str = 'hybrid'):
        """
        Initialize optimized settings manager.
        
        Args:
            account_balance: Current total account balance
            available_exchanges: List of available exchange names
            daily_target_usd: Daily profit target in USD
            allocation_strategy: Capital allocation strategy
        """
        self.account_balance = account_balance
        self.available_exchanges = available_exchanges or ['coinbase']
        self.daily_target_usd = daily_target_usd
        self.allocation_strategy = allocation_strategy
        
        # Initialize components
        self.daily_settings = None
        self.exchange_profiles = {}
        self.capital_allocation = {}
        self.allocator = None
        
        # Load settings
        self._load_settings()
        
        logger.info(f"✅ OptimizedSettingsManager initialized")
        logger.info(f"   Balance: ${account_balance:.2f}")
        logger.info(f"   Exchanges: {', '.join(self.available_exchanges)}")
        logger.info(f"   Daily Target: ${daily_target_usd:.2f}")
    
    def _load_settings(self) -> None:
        """Load all optimization settings"""
        # Load daily target settings
        if DAILY_TARGET_AVAILABLE:
            self.daily_settings = get_optimal_settings_for_balance(self.account_balance)
            logger.info(f"✅ Daily target settings loaded")
        
        # Load exchange profiles
        if EXCHANGE_PROFILES_AVAILABLE:
            for exchange in self.available_exchanges:
                profile = get_exchange_risk_profile(exchange)
                self.exchange_profiles[exchange] = profile
            logger.info(f"✅ Exchange profiles loaded for {len(self.exchange_profiles)} exchanges")
        
        # Calculate capital allocation
        if MULTI_EXCHANGE_AVAILABLE and len(self.available_exchanges) > 1:
            self.allocator = MultiExchangeCapitalAllocator(strategy=self.allocation_strategy)
            self.capital_allocation = self.allocator.calculate_allocation(
                self.account_balance,
                self.available_exchanges
            )
            logger.info(f"✅ Capital allocation calculated")
    
    def get_position_settings_for_exchange(self, exchange: str) -> Dict:
        """
        Get optimized position settings for a specific exchange.
        
        Args:
            exchange: Exchange name
            
        Returns:
            Dict with position sizing and risk parameters
        """
        # Get base settings from exchange profile
        if exchange in self.exchange_profiles:
            profile = self.exchange_profiles[exchange]
        else:
            logger.warning(f"⚠️ No profile for {exchange}, using default")
            if EXCHANGE_PROFILES_AVAILABLE:
                profile = get_exchange_risk_profile(exchange)
            else:
                profile = self._get_default_profile()
        
        # Get allocated capital for this exchange
        exchange_capital = self.capital_allocation.get(exchange, self.account_balance)
        
        # Calculate position size based on exchange capital and profile
        position_size_usd = exchange_capital * profile.get('optimal_position_pct', 0.15)
        
        # Adjust for daily target if available
        if self.daily_settings:
            # Scale position size to help achieve daily target
            target_position = self.daily_settings.get('position_size_usd', position_size_usd)
            # Use smaller of target or exchange-optimal
            position_size_usd = min(position_size_usd, target_position)
        
        return {
            'exchange': exchange,
            'exchange_capital': exchange_capital,
            'position_size_usd': position_size_usd,
            'position_size_pct': position_size_usd / exchange_capital if exchange_capital > 0 else 0,
            'min_profit_target': profile.get('min_profit_target_pct', 0.020),
            'stop_loss_pct': profile.get('stop_loss_pct', 0.012),
            'max_trades_per_day': profile.get('max_trades_per_day', 20),
            'preferred_order_type': profile.get('preferred_order_type', 'limit'),
            'min_signal_strength': profile.get('min_signal_strength', 4),
            'fees': profile.get('fees', {}),
        }
    
    def get_best_exchange_for_trade(self, 
                                    trade_size_usd: Optional[float] = None) -> Tuple[str, Dict]:
        """
        Get best exchange for a trade based on size and settings.
        
        Args:
            trade_size_usd: Desired trade size in USD (optional)
            
        Returns:
            Tuple of (exchange_name, settings_dict)
        """
        if not self.available_exchanges:
            logger.warning("⚠️ No exchanges available")
            return None, {}
        
        # If only one exchange, use it
        if len(self.available_exchanges) == 1:
            exchange = self.available_exchanges[0]
            settings = self.get_position_settings_for_exchange(exchange)
            return exchange, settings
        
        # Get best exchange based on balance
        if EXCHANGE_PROFILES_AVAILABLE:
            best_exchange = get_best_exchange_for_balance(
                self.account_balance,
                self.available_exchanges
            )
        else:
            best_exchange = self.available_exchanges[0]
        
        settings = self.get_position_settings_for_exchange(best_exchange)
        
        # If trade size specified, ensure it fits within exchange allocation
        if trade_size_usd:
            if trade_size_usd > settings['exchange_capital']:
                # Find exchange with enough capital
                for exchange in self.available_exchanges:
                    alt_settings = self.get_position_settings_for_exchange(exchange)
                    if alt_settings['exchange_capital'] >= trade_size_usd:
                        logger.info(f"💡 Routing to {exchange} (sufficient capital)")
                        return exchange, alt_settings
                
                logger.warning(f"⚠️ Trade size ${trade_size_usd:.2f} exceeds all allocations")
        
        return best_exchange, settings
    
    def get_optimization_summary(self) -> str:
        """Get formatted summary of all optimizations"""
        summary = "\n" + "="*80 + "\n"
        summary += "NIJA OPTIMIZED SETTINGS SUMMARY\n"
        summary += "="*80 + "\n\n"
        
        # Account overview
        summary += f"💰 ACCOUNT OVERVIEW:\n"
        summary += f"   Total Balance: ${self.account_balance:.2f}\n"
        summary += f"   Active Exchanges: {', '.join(self.available_exchanges)}\n"
        summary += f"   Daily Target: ${self.daily_target_usd:.2f}\n\n"
        
        # Daily target settings
        if self.daily_settings:
            summary += f"🎯 DAILY TARGET OPTIMIZATION:\n"
            summary += f"   Target: ${self.daily_settings['daily_target_usd']:.2f}/day\n"
            summary += f"   Achievable: {'✅ Yes' if self.daily_settings['achievable'] else '❌ No'}\n"
            summary += f"   Trades Needed: {self.daily_settings['trades_per_day']}/day\n"
            summary += f"   Position Size: ${self.daily_settings['position_size_usd']:.2f} "
            summary += f"({self.daily_settings['position_size_pct']*100:.1f}%)\n"
            summary += f"   Expected P&L: ${self.daily_settings['expected_daily_pnl']:.2f}/day\n\n"
        
        # Capital allocation
        if self.capital_allocation:
            summary += f"💵 CAPITAL ALLOCATION ({self.allocation_strategy.upper()}):\n"
            for exchange, amount in sorted(self.capital_allocation.items(), 
                                          key=lambda x: x[1], reverse=True):
                pct = (amount / self.account_balance) * 100
                summary += f"   {exchange:12} ${amount:>8.2f}  ({pct:>5.1f}%)\n"
            summary += "\n"
        
        # Exchange settings
        if self.exchange_profiles:
            summary += f"🏦 EXCHANGE-SPECIFIC SETTINGS:\n"
            for exchange in self.available_exchanges:
                settings = self.get_position_settings_for_exchange(exchange)
                summary += f"\n   {exchange.upper()}:\n"
                summary += f"      Capital: ${settings['exchange_capital']:.2f}\n"
                summary += f"      Position Size: ${settings['position_size_usd']:.2f}\n"
                summary += f"      Min Profit Target: {settings['min_profit_target']*100:.2f}%\n"
                summary += f"      Max Trades/Day: {settings['max_trades_per_day']}\n"
                summary += f"      Fees (round-trip): {settings['fees'].get('total_round_trip', 0)*100:.2f}%\n"
        
        summary += "\n" + "="*80 + "\n"
        return summary
    
    def _get_default_profile(self) -> Dict:
        """Get default exchange profile"""
        return {
            'optimal_position_pct': 0.15,
            'min_profit_target_pct': 0.020,
            'stop_loss_pct': 0.012,
            'max_trades_per_day': 20,
            'preferred_order_type': 'limit',
            'min_signal_strength': 4,
            'fees': {
                'total_round_trip': 0.012,
                'maker_fee': 0.005,
                'taker_fee': 0.005,
            }
        }
    
    def update_balance(self, new_balance: float) -> None:
        """
        Update account balance and recalculate settings.
        
        Args:
            new_balance: New account balance
        """
        logger.info(f"📊 Updating balance: ${self.account_balance:.2f} → ${new_balance:.2f}")
        self.account_balance = new_balance
        self._load_settings()
    
    def update_exchange_performance(self, exchange: str, trade_result: Dict) -> None:
        """
        Update performance tracking for exchange.
        
        Args:
            exchange: Exchange name
            trade_result: Trade result dict
        """
        if self.allocator:
            self.allocator.update_performance(exchange, trade_result)
            logger.info(f"📊 Performance updated for {exchange}")


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def get_optimized_settings(account_balance: float,
                          available_exchanges: Optional[List[str]] = None,
                          daily_target_usd: float = 25.00) -> OptimizedSettingsManager:
    """
    Get optimized settings manager instance.
    
    Args:
        account_balance: Current account balance
        available_exchanges: List of available exchanges
        daily_target_usd: Daily profit target
        
    Returns:
        OptimizedSettingsManager instance
    """
    return OptimizedSettingsManager(
        account_balance=account_balance,
        available_exchanges=available_exchanges or ['coinbase'],
        daily_target_usd=daily_target_usd
    )


def print_full_optimization_report(account_balance: float,
                                   available_exchanges: Optional[List[str]] = None,
                                   daily_target_usd: float = 25.00) -> None:
    """
    Print complete optimization report.
    
    Args:
        account_balance: Current account balance
        available_exchanges: List of available exchanges
        daily_target_usd: Daily profit target
    """
    manager = get_optimized_settings(account_balance, available_exchanges, daily_target_usd)
    print(manager.get_optimization_summary())
    
    # Print individual component details
    if DAILY_TARGET_AVAILABLE:
        print("\nDETAILED DAILY TARGET ANALYSIS:")
        print_daily_target_summary(account_balance)
    
    if EXCHANGE_PROFILES_AVAILABLE and len(manager.available_exchanges) > 1:
        print("\nEXCHANGE PROFILE COMPARISON:")
        compare_exchange_profiles()


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    # Test with realistic scenarios
    
    print("\n" + "="*80)
    print("SCENARIO 1: Small Account ($50) - Single Exchange (Coinbase)")
    print("="*80)
    print_full_optimization_report(50.00, ['coinbase'], 25.00)
    
    print("\n" + "="*80)
    print("SCENARIO 2: Medium Account ($200) - Multi-Exchange (Coinbase, OKX, Kraken)")
    print("="*80)
    print_full_optimization_report(200.00, ['coinbase', 'okx', 'kraken'], 25.00)
    
    print("\n" + "="*80)
    print("SCENARIO 3: Large Account ($1000) - Multi-Exchange")
    print("="*80)
    print_full_optimization_report(1000.00, ['coinbase', 'okx', 'kraken'], 25.00)
