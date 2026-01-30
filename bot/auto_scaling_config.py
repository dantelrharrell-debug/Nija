"""
NIJA Auto-Scaling Configuration Module
======================================

Automatically upgrades NIJA's configuration as your account balance grows.

Features:
- Real-time balance monitoring
- Automatic configuration scaling at thresholds
- Notification system for upgrades
- State persistence to avoid duplicate notifications
- Seamless integration with micro capital mode

Scaling Thresholds:
- $15-$249: Starter (2 positions, 3% risk)
- $250-$499: Growth (3 positions, 4% risk)
- $500-$999: Advanced (4 positions, 4% risk, copy trading enabled)
- $1000+: Elite (6 positions, 5% risk, leverage enabled)

Author: NIJA Trading Systems
Version: 1.0
Date: January 30, 2026
"""

import os
import json
import logging
from datetime import datetime
from typing import Dict, Optional, Tuple
from pathlib import Path

# Import base micro capital configuration
try:
    from micro_capital_config import (
        get_dynamic_config,
        apply_micro_capital_config,
        MICRO_CAPITAL_CONFIG,
    )
except ImportError:
    from bot.micro_capital_config import (
        get_dynamic_config,
        apply_micro_capital_config,
        MICRO_CAPITAL_CONFIG,
    )

logger = logging.getLogger("nija.auto_scaling")

# ============================================================================
# SCALING TIER DEFINITIONS
# ============================================================================

class ScalingTier:
    """Represents a scaling tier with its thresholds and benefits"""
    
    def __init__(
        self,
        name: str,
        min_equity: float,
        max_equity: Optional[float],
        max_positions: int,
        risk_per_trade: float,
        copy_trading: bool,
        leverage_enabled: bool,
        description: str
    ):
        self.name = name
        self.min_equity = min_equity
        self.max_equity = max_equity
        self.max_positions = max_positions
        self.risk_per_trade = risk_per_trade
        self.copy_trading = copy_trading
        self.leverage_enabled = leverage_enabled
        self.description = description
    
    def matches(self, equity: float) -> bool:
        """Check if equity falls within this tier"""
        if self.max_equity is None:
            return equity >= self.min_equity
        return self.min_equity <= equity < self.max_equity
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'name': self.name,
            'min_equity': self.min_equity,
            'max_equity': self.max_equity,
            'max_positions': self.max_positions,
            'risk_per_trade': self.risk_per_trade,
            'copy_trading': self.copy_trading,
            'leverage_enabled': self.leverage_enabled,
            'description': self.description,
        }


# Define scaling tiers
SCALING_TIERS = [
    ScalingTier(
        name="STARTER",
        min_equity=15.0,
        max_equity=250.0,
        max_positions=2,
        risk_per_trade=3.0,
        copy_trading=False,
        leverage_enabled=False,
        description="Conservative starter configuration for micro capital"
    ),
    ScalingTier(
        name="GROWTH",
        min_equity=250.0,
        max_equity=500.0,
        max_positions=3,
        risk_per_trade=4.0,
        copy_trading=False,
        leverage_enabled=False,
        description="Enhanced position management for growing accounts"
    ),
    ScalingTier(
        name="ADVANCED",
        min_equity=500.0,
        max_equity=1000.0,
        max_positions=4,
        risk_per_trade=4.0,
        copy_trading=True,
        leverage_enabled=False,
        description="Advanced features with copy trading enabled"
    ),
    ScalingTier(
        name="ELITE",
        min_equity=1000.0,
        max_equity=None,
        max_positions=6,
        risk_per_trade=5.0,
        copy_trading=True,
        leverage_enabled=True,
        description="Full feature set with leverage and maximum positions"
    ),
]


# ============================================================================
# AUTO-SCALING STATE MANAGER
# ============================================================================

class AutoScalingState:
    """Manages auto-scaling state and persistence"""
    
    def __init__(self, state_file: str = ".auto_scaling_state.json"):
        self.state_file = Path(state_file)
        self.state = self._load_state()
    
    def _load_state(self) -> Dict:
        """Load state from file"""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load auto-scaling state: {e}")
        
        # Default state
        return {
            'current_tier': None,
            'last_equity': 0.0,
            'last_upgrade_time': None,
            'upgrade_history': [],
        }
    
    def _save_state(self):
        """Save state to file"""
        try:
            with open(self.state_file, 'w') as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save auto-scaling state: {e}")
    
    def get_current_tier(self) -> Optional[str]:
        """Get current tier name"""
        return self.state.get('current_tier')
    
    def set_current_tier(self, tier_name: str, equity: float):
        """Set current tier and record upgrade"""
        old_tier = self.state.get('current_tier')
        self.state['current_tier'] = tier_name
        self.state['last_equity'] = equity
        self.state['last_upgrade_time'] = datetime.now().isoformat()
        
        # Record upgrade in history
        if old_tier != tier_name:
            self.state['upgrade_history'].append({
                'from_tier': old_tier,
                'to_tier': tier_name,
                'equity': equity,
                'timestamp': datetime.now().isoformat(),
            })
        
        self._save_state()
    
    def get_upgrade_history(self) -> list:
        """Get upgrade history"""
        return self.state.get('upgrade_history', [])


# ============================================================================
# AUTO-SCALING ENGINE
# ============================================================================

class AutoScalingEngine:
    """
    Auto-scaling engine that monitors balance and applies scaled configuration.
    """
    
    def __init__(self, state_file: str = ".auto_scaling_state.json"):
        self.state_manager = AutoScalingState(state_file)
        self.current_tier: Optional[ScalingTier] = None
        self.current_equity: float = 0.0
        logger.info("Auto-scaling engine initialized")
    
    def get_tier_for_equity(self, equity: float) -> Optional[ScalingTier]:
        """Get the appropriate tier for given equity"""
        for tier in SCALING_TIERS:
            if tier.matches(equity):
                return tier
        return None
    
    def check_and_scale(self, equity: float, force: bool = False) -> Tuple[bool, Optional[ScalingTier], Optional[ScalingTier]]:
        """
        Check if scaling is needed and apply if necessary.
        
        Args:
            equity: Current account equity
            force: Force scaling even if tier hasn't changed
            
        Returns:
            Tuple of (scaled, old_tier, new_tier)
        """
        old_tier = self.current_tier
        new_tier = self.get_tier_for_equity(equity)
        
        if new_tier is None:
            logger.warning(f"No tier found for equity ${equity:.2f}")
            return False, old_tier, None
        
        # Check if tier has changed or force is enabled
        tier_changed = (old_tier is None or old_tier.name != new_tier.name)
        
        if tier_changed or force:
            self._apply_scaling(new_tier, equity, tier_changed)
            return True, old_tier, new_tier
        
        # Update equity but no tier change
        self.current_equity = equity
        return False, old_tier, new_tier
    
    def _apply_scaling(self, tier: ScalingTier, equity: float, tier_changed: bool):
        """Apply scaling configuration"""
        self.current_tier = tier
        self.current_equity = equity
        
        # Save state
        self.state_manager.set_current_tier(tier.name, equity)
        
        # Log the scaling event
        if tier_changed:
            logger.info(f"🔥 AUTO-SCALING UPGRADE: ${equity:.2f} → {tier.name} tier")
            logger.info(f"   Max Positions: {tier.max_positions}")
            logger.info(f"   Risk Per Trade: {tier.risk_per_trade}%")
            logger.info(f"   Copy Trading: {tier.copy_trading}")
            logger.info(f"   Leverage: {tier.leverage_enabled}")
        
        # Apply dynamic configuration
        config = apply_micro_capital_config(equity=equity, set_env_vars=True)
        
        logger.info(f"Configuration applied for {tier.name} tier at ${equity:.2f}")
    
    def get_current_config(self) -> Dict:
        """Get current configuration including tier information"""
        if self.current_tier is None:
            return {
                'tier': None,
                'equity': self.current_equity,
                'config': MICRO_CAPITAL_CONFIG,
            }
        
        dynamic_config = get_dynamic_config(self.current_equity)
        
        return {
            'tier': self.current_tier.to_dict(),
            'equity': self.current_equity,
            'base_config': MICRO_CAPITAL_CONFIG,
            'dynamic_config': dynamic_config,
        }
    
    def get_next_tier(self) -> Optional[ScalingTier]:
        """Get the next tier above current"""
        if self.current_tier is None:
            return SCALING_TIERS[0] if SCALING_TIERS else None
        
        current_index = next(
            (i for i, tier in enumerate(SCALING_TIERS) if tier.name == self.current_tier.name),
            None
        )
        
        if current_index is None or current_index >= len(SCALING_TIERS) - 1:
            return None
        
        return SCALING_TIERS[current_index + 1]
    
    def get_progress_to_next_tier(self) -> Optional[Dict]:
        """Get progress towards next tier"""
        next_tier = self.get_next_tier()
        
        if next_tier is None or self.current_equity == 0:
            return None
        
        equity_needed = next_tier.min_equity - self.current_equity
        progress_pct = (self.current_equity / next_tier.min_equity) * 100 if next_tier.min_equity > 0 else 100
        
        return {
            'current_equity': self.current_equity,
            'next_tier': next_tier.to_dict(),
            'equity_needed': equity_needed,
            'progress_pct': min(progress_pct, 100.0),
        }
    
    def get_scaling_summary(self) -> str:
        """Get human-readable scaling summary"""
        if self.current_tier is None:
            return "Auto-scaling not initialized. Run check_and_scale() with your current equity."
        
        tier = self.current_tier
        next_tier = self.get_next_tier()
        progress = self.get_progress_to_next_tier()
        
        summary = f"""
╔══════════════════════════════════════════════════════════════════════════╗
║                     NIJA AUTO-SCALING STATUS                             ║
╚══════════════════════════════════════════════════════════════════════════╝

💰 CURRENT EQUITY: ${self.current_equity:.2f}

🎯 CURRENT TIER: {tier.name}
   • {tier.description}
   • Max Positions: {tier.max_positions}
   • Risk Per Trade: {tier.risk_per_trade}%
   • Copy Trading: {'✅ Enabled' if tier.copy_trading else '❌ Disabled'}
   • Leverage: {'✅ Enabled' if tier.leverage_enabled else '❌ Disabled'}
"""
        
        if next_tier and progress:
            summary += f"""
📈 NEXT TIER: {next_tier.name}
   • Unlocks at: ${next_tier.min_equity:.2f}
   • Progress: {progress['progress_pct']:.1f}%
   • Equity needed: ${progress['equity_needed']:.2f}
   
   Upcoming Benefits:
   • Max Positions: {tier.max_positions} → {next_tier.max_positions}
   • Risk Per Trade: {tier.risk_per_trade}% → {next_tier.risk_per_trade}%
"""
            if not tier.copy_trading and next_tier.copy_trading:
                summary += f"   • Copy Trading: ❌ → ✅ ENABLED\n"
            if not tier.leverage_enabled and next_tier.leverage_enabled:
                summary += f"   • Leverage: ❌ → ✅ ENABLED\n"
        else:
            summary += f"""
🏆 MAXIMUM TIER ACHIEVED!
   • You are at the highest tier
   • All features unlocked
   • Keep growing! 🚀
"""
        
        # Show upgrade history
        history = self.state_manager.get_upgrade_history()
        if history:
            summary += f"""
📊 UPGRADE HISTORY:
"""
            for upgrade in history[-5:]:  # Show last 5 upgrades
                from_tier = upgrade['from_tier'] or 'None'
                to_tier = upgrade['to_tier']
                equity = upgrade['equity']
                timestamp = upgrade['timestamp'].split('T')[0]  # Date only
                summary += f"   • {timestamp}: {from_tier} → {to_tier} (${equity:.2f})\n"
        
        summary += f"""
═══════════════════════════════════════════════════════════════════════════
"""
        
        return summary


# ============================================================================
# GLOBAL AUTO-SCALING ENGINE INSTANCE
# ============================================================================

_auto_scaling_engine: Optional[AutoScalingEngine] = None


def get_auto_scaling_engine() -> AutoScalingEngine:
    """Get global auto-scaling engine instance"""
    global _auto_scaling_engine
    
    if _auto_scaling_engine is None:
        _auto_scaling_engine = AutoScalingEngine()
    
    return _auto_scaling_engine


def auto_scale(equity: float, force: bool = False) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Convenience function to check and apply auto-scaling.
    
    Args:
        equity: Current account equity
        force: Force scaling even if tier hasn't changed
        
    Returns:
        Tuple of (scaled, old_tier_name, new_tier_name)
    """
    engine = get_auto_scaling_engine()
    scaled, old_tier, new_tier = engine.check_and_scale(equity, force)
    
    old_tier_name = old_tier.name if old_tier else None
    new_tier_name = new_tier.name if new_tier else None
    
    return scaled, old_tier_name, new_tier_name


def get_current_tier_info() -> Optional[Dict]:
    """Get current tier information"""
    engine = get_auto_scaling_engine()
    return engine.get_current_config()


def get_scaling_summary() -> str:
    """Get scaling status summary"""
    engine = get_auto_scaling_engine()
    return engine.get_scaling_summary()


# ============================================================================
# INTEGRATION HELPERS
# ============================================================================

def integrate_with_broker_manager(broker_manager) -> bool:
    """
    Integrate auto-scaling with broker manager.
    
    Args:
        broker_manager: Instance of BrokerManager
        
    Returns:
        bool: True if integration successful
    """
    try:
        # Get total balance across all brokers
        total_balance = 0.0
        
        if hasattr(broker_manager, 'get_total_balance'):
            total_balance = broker_manager.get_total_balance()
        elif hasattr(broker_manager, 'brokers'):
            for broker in broker_manager.brokers.values():
                if hasattr(broker, 'get_balance'):
                    balance = broker.get_balance()
                    if balance:
                        total_balance += balance
        
        if total_balance > 0:
            scaled, old_tier, new_tier = auto_scale(total_balance)
            
            if scaled and old_tier != new_tier:
                logger.info(f"🔥 Auto-scaling triggered: {old_tier} → {new_tier}")
            
            return True
        
        return False
        
    except Exception as e:
        logger.error(f"Failed to integrate auto-scaling with broker manager: {e}")
        return False


# ============================================================================
# CLI INTERFACE
# ============================================================================

if __name__ == "__main__":
    import sys
    
    print("="*80)
    print("NIJA AUTO-SCALING CONFIGURATION MODULE")
    print("="*80)
    print()
    
    # Test auto-scaling at different equity levels
    test_equities = [15, 100, 250, 500, 750, 1000, 5000]
    
    engine = get_auto_scaling_engine()
    
    print("Testing auto-scaling at different equity levels:\n")
    
    for equity in test_equities:
        scaled, old_tier, new_tier = engine.check_and_scale(equity, force=True)
        
        if scaled and new_tier:
            print(f"${equity:>6.2f}: {new_tier.name:>8} tier "
                  f"({new_tier.max_positions} pos, {new_tier.risk_per_trade}% risk)")
    
    print("\n" + "="*80)
    print("SCALING SUMMARY FOR $750 EQUITY")
    print("="*80)
    
    # Set to specific equity and show summary
    engine.check_and_scale(750.0)
    print(get_scaling_summary())
    
    print("\n" + "="*80)
    print("TIER DEFINITIONS")
    print("="*80)
    
    for tier in SCALING_TIERS:
        max_eq = f"${tier.max_equity:.0f}" if tier.max_equity else "∞"
        print(f"\n{tier.name}:")
        print(f"  Range: ${tier.min_equity:.0f} - {max_eq}")
        print(f"  Positions: {tier.max_positions}")
        print(f"  Risk: {tier.risk_per_trade}%")
        print(f"  Copy Trading: {tier.copy_trading}")
        print(f"  Leverage: {tier.leverage_enabled}")
        print(f"  {tier.description}")
