"""
Integration Example: Capital Evolution Engine with NIJA Trading System

This example demonstrates how to integrate the Capital Evolution Engine
with the existing NIJA trading system to enable auto-scaling based on capital.

The integration allows:
1. Automatic position limit adjustment based on capital
2. Dynamic risk percentage based on evolution mode
3. Copy trading activation at ADVANCED tier
4. Leverage activation at ELITE tier
5. Seamless transitions as capital grows/shrinks
"""

import logging
from typing import Optional

# Import evolution engine
from bot.capital_evolution_engine import (
    get_evolution_engine,
    get_singleton_evolution_engine,
    EvolutionMode
)

# Import existing NIJA components
try:
    from bot.risk_manager import AdaptiveRiskManager
except ImportError:
    AdaptiveRiskManager = None
    logging.warning("Risk manager not available")

try:
    from bot.tier_config import get_tier_from_balance
except ImportError:
    get_tier_from_balance = None
    logging.warning("Tier config not available")

logger = logging.getLogger("nija.evolution_integration")


class EvolutionIntegratedRiskManager:
    """
    Risk manager that integrates Capital Evolution Engine
    
    Automatically adjusts:
    - Position limits (3, 4, or 6 based on mode)
    - Risk percentages (4% or 5% based on mode)
    - Feature flags (copy trading, leverage)
    """
    
    def __init__(self, initial_balance: float, current_balance: Optional[float] = None):
        """
        Initialize evolution-integrated risk manager
        
        Args:
            initial_balance: Starting balance
            current_balance: Current balance (optional)
        """
        # Initialize evolution engine
        self.evolution_engine = get_evolution_engine(
            initial_capital=initial_balance,
            current_capital=current_balance
        )
        
        # Initialize base risk manager if available
        self.base_risk_manager = None
        if AdaptiveRiskManager:
            self.base_risk_manager = AdaptiveRiskManager(
                pro_mode=True,
                min_free_reserve_pct=0.15
            )
        
        logger.info("✅ Evolution-Integrated Risk Manager initialized")
        logger.info(f"   Mode: {self.evolution_engine.mode_config.get_display_name()}")
        logger.info(f"   Max Positions: {self.evolution_engine.get_max_positions()}")
        logger.info(f"   Risk Per Trade: {self.evolution_engine.get_risk_per_trade_pct()}%")
    
    def update_balance(self, new_balance: float) -> Optional[EvolutionMode]:
        """
        Update balance and check for mode transitions
        
        Args:
            new_balance: New account balance
            
        Returns:
            New mode if transition occurred, None otherwise
        """
        new_mode = self.evolution_engine.update_capital(new_balance)
        
        if new_mode:
            logger.info(f"🚀 Evolution mode changed!")
            logger.info(f"   New Max Positions: {self.evolution_engine.get_max_positions()}")
            logger.info(f"   New Risk %: {self.evolution_engine.get_risk_per_trade_pct()}%")
            logger.info(f"   Copy Trading: {self.evolution_engine.is_copy_trading_enabled()}")
            logger.info(f"   Leverage: {self.evolution_engine.is_leverage_enabled()}")
        
        return new_mode
    
    def get_max_positions(self) -> int:
        """Get maximum positions from evolution engine"""
        return self.evolution_engine.get_max_positions()
    
    def get_risk_per_trade_pct(self) -> float:
        """Get risk percentage from evolution engine"""
        return self.evolution_engine.get_risk_per_trade_pct()
    
    def can_open_position(self, open_position_count: int) -> bool:
        """
        Check if we can open a new position
        
        Args:
            open_position_count: Current number of open positions
            
        Returns:
            True if we can open new position
        """
        max_positions = self.get_max_positions()
        
        if open_position_count >= max_positions:
            logger.info(f"Position limit reached: {open_position_count}/{max_positions} "
                       f"({self.evolution_engine.current_mode.value})")
            return False
        
        return True
    
    def calculate_position_size(self, balance: float, symbol: str = None) -> float:
        """
        Calculate position size using evolution risk percentage
        
        Args:
            balance: Account balance
            symbol: Trading symbol (optional)
            
        Returns:
            Position size in USD
        """
        risk_pct = self.get_risk_per_trade_pct() / 100.0  # Convert to decimal
        position_size = balance * risk_pct
        
        logger.debug(f"Position size: ${position_size:.2f} "
                    f"(${balance:.2f} × {risk_pct*100:.1f}%)")
        
        return position_size
    
    def is_copy_trading_enabled(self) -> bool:
        """Check if copy trading is enabled for current mode"""
        return self.evolution_engine.is_copy_trading_enabled()
    
    def is_leverage_enabled(self) -> bool:
        """Check if leverage is enabled for current mode"""
        return self.evolution_engine.is_leverage_enabled()
    
    def get_status_summary(self) -> str:
        """Get quick status summary"""
        return self.evolution_engine.get_quick_summary()
    
    def get_full_report(self) -> str:
        """Get comprehensive evolution report"""
        return self.evolution_engine.get_evolution_report()


# ============================================================================
# USAGE EXAMPLES
# ============================================================================

def example_basic_integration():
    """Example: Basic integration with trading bot"""
    print("\n" + "=" * 90)
    print("EXAMPLE 1: BASIC INTEGRATION")
    print("=" * 90 + "\n")
    
    # Initialize with current balance
    initial_balance = 100.0
    risk_manager = EvolutionIntegratedRiskManager(initial_balance)
    
    print(f"Initialized with ${initial_balance:.2f}")
    print(f"Max Positions: {risk_manager.get_max_positions()}")
    print(f"Risk Per Trade: {risk_manager.get_risk_per_trade_pct()}%")
    print()
    
    # Simulate trading and balance growth
    balances = [100, 250, 500, 750, 1000, 2500]
    
    for balance in balances:
        print(f"\nBalance updated to ${balance:.2f}")
        new_mode = risk_manager.update_balance(balance)
        
        if new_mode:
            print(f"  🚀 Transitioned to: {risk_manager.evolution_engine.mode_config.get_display_name()}")
        
        print(f"  Max Positions: {risk_manager.get_max_positions()}")
        print(f"  Risk %: {risk_manager.get_risk_per_trade_pct()}%")
        print(f"  Position size: ${risk_manager.calculate_position_size(balance):.2f}")


def example_position_limit_check():
    """Example: Checking position limits before opening trades"""
    print("\n" + "=" * 90)
    print("EXAMPLE 2: POSITION LIMIT CHECKING")
    print("=" * 90 + "\n")
    
    risk_manager = EvolutionIntegratedRiskManager(initial_balance=500.0)
    
    print(f"Starting with ADVANCED mode: {risk_manager.get_max_positions()} max positions\n")
    
    # Simulate opening positions
    open_positions = 0
    
    for i in range(6):
        can_open = risk_manager.can_open_position(open_positions)
        
        if can_open:
            open_positions += 1
            print(f"✅ Opened position #{open_positions}")
        else:
            print(f"❌ Cannot open position #{open_positions + 1} - limit reached")
            break


def example_mode_features():
    """Example: Checking mode-specific features"""
    print("\n" + "=" * 90)
    print("EXAMPLE 3: MODE-SPECIFIC FEATURES")
    print("=" * 90 + "\n")
    
    test_balances = [100, 500, 1000]
    
    for balance in test_balances:
        risk_manager = EvolutionIntegratedRiskManager(initial_balance=balance)
        mode = risk_manager.evolution_engine.current_mode.value
        
        print(f"\nBalance: ${balance:.2f} ({mode})")
        print(f"  Copy Trading: {'ENABLED ✅' if risk_manager.is_copy_trading_enabled() else 'DISABLED ❌'}")
        print(f"  Leverage: {'ENABLED ✅' if risk_manager.is_leverage_enabled() else 'DISABLED ❌'}")


def example_trading_loop_integration():
    """Example: Integration in a trading loop"""
    print("\n" + "=" * 90)
    print("EXAMPLE 4: TRADING LOOP INTEGRATION")
    print("=" * 90 + "\n")
    
    # Initialize
    initial_balance = 100.0
    balance = initial_balance
    risk_manager = EvolutionIntegratedRiskManager(initial_balance)
    
    print(f"Starting trading with ${balance:.2f}\n")
    
    # Simulate trades
    trades = [
        ("BTC-USD", True, 15.0),   # Win
        ("ETH-USD", True, 12.0),   # Win
        ("SOL-USD", False, -8.0),  # Loss
        ("BTC-USD", True, 20.0),   # Win
        ("ETH-USD", True, 400.0),  # Big win - triggers mode change
    ]
    
    open_positions = 0
    
    for symbol, is_win, pnl in trades:
        # Check if we can open position
        if not risk_manager.can_open_position(open_positions):
            print(f"⚠️  Skipping {symbol} - position limit reached\n")
            continue
        
        # Calculate position size
        position_size = risk_manager.calculate_position_size(balance)
        
        # Execute trade (simulated)
        balance += pnl
        open_positions += 1 if is_win else 0  # Simplified
        
        # Update balance and check for mode transition
        new_mode = risk_manager.update_balance(balance)
        
        result = "WIN ✅" if is_win else "LOSS ❌"
        print(f"{symbol}: {result} | P/L: ${pnl:+.2f} | Balance: ${balance:.2f} | "
              f"Pos Size: ${position_size:.2f}")
        
        if new_mode:
            print(f"  🚀 MODE TRANSITION: {risk_manager.evolution_engine.mode_config.get_display_name()}\n")
    
    # Final summary
    print("\n" + "=" * 90)
    print("FINAL STATUS")
    print("=" * 90)
    print(risk_manager.get_status_summary())


def example_singleton_pattern():
    """Example: Using singleton pattern for global access"""
    print("\n" + "=" * 90)
    print("EXAMPLE 5: SINGLETON PATTERN")
    print("=" * 90 + "\n")
    
    # Initialize singleton
    from bot.capital_evolution_engine import get_singleton_evolution_engine
    
    initial_balance = 100.0
    engine = get_singleton_evolution_engine(
        initial_capital=initial_balance,
        current_capital=initial_balance
    )
    
    print(f"Singleton initialized with ${initial_balance:.2f}")
    print(f"Mode: {engine.mode_config.get_display_name()}\n")
    
    # Access from different parts of code
    def module_a():
        engine = get_singleton_evolution_engine()
        print(f"Module A: Max positions = {engine.get_max_positions()}")
    
    def module_b():
        engine = get_singleton_evolution_engine()
        print(f"Module B: Risk % = {engine.get_risk_per_trade_pct()}%")
    
    def module_c():
        engine = get_singleton_evolution_engine()
        engine.update_capital(500.0)
        print(f"Module C: Updated balance to $500")
    
    module_a()
    module_b()
    module_c()
    
    # All modules see the same instance
    def module_d():
        engine = get_singleton_evolution_engine()
        print(f"Module D: Mode is now {engine.current_mode.value}")
    
    module_d()


if __name__ == "__main__":
    """Run all examples"""
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s - %(message)s'
    )
    
    print("\n" + "=" * 90)
    print("🔥 CAPITAL EVOLUTION ENGINE - INTEGRATION EXAMPLES 🔥")
    print("=" * 90)
    
    example_basic_integration()
    example_position_limit_check()
    example_mode_features()
    example_trading_loop_integration()
    example_singleton_pattern()
    
    print("\n" + "=" * 90)
    print("✅ ALL EXAMPLES COMPLETE")
    print("=" * 90 + "\n")
