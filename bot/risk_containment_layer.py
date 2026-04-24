"""
NIJA Risk Containment Layer

Critical safety layer that ensures position concentration is paired with strict
stop-loss risk controls. Prevents large account drawdowns from concentrated positions.

Problem Solved:
- STARTER tier allows 80% position size
- Without stop loss control: 80% × 10% stop = 8% account loss (DANGEROUS)
- With stop loss control: Risk capped at 3-5% regardless of position size

Risk Formula:
    Max Position Size = (Account Balance × Max Risk %) / Stop Loss %
    
Example:
    Account: $100
    Max Risk: 5%
    Stop Loss: 10%
    Max Position Size = ($100 × 5%) / 10% = $50 (not $80)

This ensures that even with concentrated positions, the actual RISK is limited.

Author: NIJA Trading Systems
Version: 1.0
Date: February 18, 2026
"""

import logging
from typing import Dict, Tuple, Optional
from dataclasses import dataclass

logger = logging.getLogger("nija.risk_containment")


@dataclass
class RiskContainmentConfig:
    """
    Configuration for risk containment by tier.
    
    Attributes:
        tier_name: Name of the tier
        max_risk_per_trade_pct: Maximum risk per trade as % of account (3-5%)
        default_stop_loss_pct: Default stop loss % if not specified
        min_stop_loss_pct: Minimum allowed stop loss %
        max_stop_loss_pct: Maximum allowed stop loss %
        volatility_multiplier: Multiplier for volatile conditions
    """
    tier_name: str
    max_risk_per_trade_pct: float  # 3-5% typically
    default_stop_loss_pct: float   # 5-10% typically
    min_stop_loss_pct: float       # 2% minimum
    max_stop_loss_pct: float       # 15% maximum
    volatility_multiplier: float   # Tighten stops in high volatility


# Risk containment configurations per tier
RISK_CONTAINMENT_CONFIGS = {
    # STARTER: Ultra-tight risk control due to concentration
    # Max risk: 3% (conservative for learning)
    # Tighter stops required due to 80% position sizes
    'STARTER': RiskContainmentConfig(
        tier_name='STARTER',
        max_risk_per_trade_pct=0.03,  # 3% max risk
        default_stop_loss_pct=0.05,    # 5% default stop
        min_stop_loss_pct=0.02,        # 2% min
        max_stop_loss_pct=0.10,        # 10% max (tight for safety)
        volatility_multiplier=0.8      # Tighten by 20% in volatility
    ),
    
    # SAVER: Tight risk control, slightly more room
    # Max risk: 4% (still conservative)
    'SAVER': RiskContainmentConfig(
        tier_name='SAVER',
        max_risk_per_trade_pct=0.04,  # 4% max risk
        default_stop_loss_pct=0.06,    # 6% default stop
        min_stop_loss_pct=0.02,        # 2% min
        max_stop_loss_pct=0.12,        # 12% max
        volatility_multiplier=0.85
    ),
    
    # INVESTOR: Moderate risk control
    # Max risk: 5% (balanced)
    'INVESTOR': RiskContainmentConfig(
        tier_name='INVESTOR',
        max_risk_per_trade_pct=0.05,  # 5% max risk
        default_stop_loss_pct=0.07,    # 7% default stop
        min_stop_loss_pct=0.03,        # 3% min
        max_stop_loss_pct=0.15,        # 15% max
        volatility_multiplier=0.9
    ),
    
    # INCOME: Standard risk control
    # Max risk: 5%
    'INCOME': RiskContainmentConfig(
        tier_name='INCOME',
        max_risk_per_trade_pct=0.05,  # 5% max risk
        default_stop_loss_pct=0.08,    # 8% default stop
        min_stop_loss_pct=0.03,        # 3% min
        max_stop_loss_pct=0.15,        # 15% max
        volatility_multiplier=0.9
    ),
    
    # LIVABLE: Standard risk control with more room
    # Max risk: 5%
    'LIVABLE': RiskContainmentConfig(
        tier_name='LIVABLE',
        max_risk_per_trade_pct=0.05,  # 5% max risk
        default_stop_loss_pct=0.10,    # 10% default stop
        min_stop_loss_pct=0.04,        # 4% min
        max_stop_loss_pct=0.20,        # 20% max
        volatility_multiplier=0.95
    ),
    
    # BALLER: Professional risk control
    # Max risk: 5% but with wider stops
    'BALLER': RiskContainmentConfig(
        tier_name='BALLER',
        max_risk_per_trade_pct=0.05,  # 5% max risk
        default_stop_loss_pct=0.10,    # 10% default stop
        min_stop_loss_pct=0.05,        # 5% min
        max_stop_loss_pct=0.25,        # 25% max (for swing trades)
        volatility_multiplier=1.0      # Full stop distance
    ),
}


@dataclass
class RiskCalculation:
    """
    Result of risk-adjusted position sizing calculation.
    
    Attributes:
        tier_name: Tier name
        account_balance: Account balance
        requested_position_size: Originally requested size
        stop_loss_pct: Stop loss percentage
        max_risk_dollars: Maximum risk in dollars
        max_risk_pct: Maximum risk as % of account
        risk_adjusted_size: Position size adjusted for risk
        actual_risk_dollars: Actual risk with adjusted size
        actual_risk_pct: Actual risk % with adjusted size
        size_reduced: Whether size was reduced
        reduction_reason: Why size was reduced (if applicable)
    """
    tier_name: str
    account_balance: float
    requested_position_size: float
    stop_loss_pct: float
    max_risk_dollars: float
    max_risk_pct: float
    risk_adjusted_size: float
    actual_risk_dollars: float
    actual_risk_pct: float
    size_reduced: bool
    reduction_reason: Optional[str]
    
    def __repr__(self):
        return (f"RiskCalculation(tier={self.tier_name}, "
                f"requested=${self.requested_position_size:.2f}, "
                f"adjusted=${self.risk_adjusted_size:.2f}, "
                f"risk={self.actual_risk_pct*100:.2f}%)")


class RiskContainmentLayer:
    """
    Risk containment layer that ensures position concentration is paired
    with strict stop-loss risk controls.
    
    Key Function:
        Adjusts position sizes to ensure max risk per trade is 3-5% of account,
        regardless of tier concentration strategy.
    
    Safety Rules:
    1. Max risk per trade: 3-5% of account (tier-dependent)
    2. Stop loss validation: 2-25% range (tier-dependent)
    3. Volatility adjustment: Tighten stops in high volatility
    4. Position size adjustment: Reduce size if risk exceeds max
    
    Example:
        STARTER tier wants 80% position ($80 on $100 account)
        Stop loss: 10%
        Risk without control: 80% × 10% = 8% ❌
        Max risk allowed: 3%
        Adjusted position size: $100 × 3% / 10% = $30 ✅
        Actual risk: $30 × 10% = $3 (3%) ✅
    """
    
    def __init__(self):
        """Initialize the risk containment layer"""
        self.configs = RISK_CONTAINMENT_CONFIGS
        logger.info("🛡️ Risk Containment Layer initialized - Stop-loss risk control active")
    
    def calculate_risk_adjusted_position_size(
        self,
        balance: float,
        tier_name: str,
        requested_size: float,
        stop_loss_pct: Optional[float] = None,
        volatility_pct: Optional[float] = None
    ) -> RiskCalculation:
        """
        Calculate risk-adjusted position size with stop-loss control.
        
        Args:
            balance: Account balance
            tier_name: Tier name (STARTER, SAVER, etc.)
            requested_size: Requested position size in USD
            stop_loss_pct: Stop loss as decimal (0.05 = 5%)
            volatility_pct: Current volatility as decimal (optional)
            
        Returns:
            RiskCalculation with adjusted position size
        """
        # Get tier config
        config = self.configs.get(tier_name, self.configs['INCOME'])
        
        # Use default stop loss if not provided
        if stop_loss_pct is None:
            stop_loss_pct = config.default_stop_loss_pct
        
        # Validate stop loss range
        stop_loss_pct = max(config.min_stop_loss_pct, min(stop_loss_pct, config.max_stop_loss_pct))
        
        # Adjust stop loss for volatility if provided
        if volatility_pct is not None and volatility_pct > 0.02:  # High volatility > 2%
            stop_loss_pct = stop_loss_pct * config.volatility_multiplier
            logger.debug(f"Volatility adjustment: stop loss tightened to {stop_loss_pct*100:.1f}%")
        
        # Calculate max risk in dollars
        max_risk_dollars = balance * config.max_risk_per_trade_pct
        
        # Calculate max position size based on risk
        max_position_size = max_risk_dollars / stop_loss_pct if stop_loss_pct > 0 else requested_size
        
        # Check if requested size exceeds risk-adjusted max
        size_reduced = requested_size > max_position_size
        risk_adjusted_size = min(requested_size, max_position_size)
        
        # Calculate actual risk with adjusted size
        actual_risk_dollars = risk_adjusted_size * stop_loss_pct
        actual_risk_pct = actual_risk_dollars / balance if balance > 0 else 0
        
        # Determine reduction reason
        reduction_reason = None
        if size_reduced:
            reduction_reason = (f"Risk exceeds max {config.max_risk_per_trade_pct*100:.1f}% - "
                              f"reduced from ${requested_size:.2f} to ${risk_adjusted_size:.2f}")
            logger.warning(f"⚠️ RISK CONTAINMENT: {reduction_reason}")
        
        return RiskCalculation(
            tier_name=tier_name,
            account_balance=balance,
            requested_position_size=requested_size,
            stop_loss_pct=stop_loss_pct,
            max_risk_dollars=max_risk_dollars,
            max_risk_pct=config.max_risk_per_trade_pct,
            risk_adjusted_size=risk_adjusted_size,
            actual_risk_dollars=actual_risk_dollars,
            actual_risk_pct=actual_risk_pct,
            size_reduced=size_reduced,
            reduction_reason=reduction_reason
        )
    
    def calculate_stop_loss_price(
        self,
        entry_price: float,
        signal_type: str,
        stop_loss_pct: float
    ) -> float:
        """
        Calculate stop loss price based on entry price and stop %.
        
        Args:
            entry_price: Entry price
            signal_type: LONG or SHORT
            stop_loss_pct: Stop loss as decimal (0.05 = 5%)
            
        Returns:
            Stop loss price
        """
        if signal_type == 'LONG':
            stop_price = entry_price * (1 - stop_loss_pct)
        else:  # SHORT
            stop_price = entry_price * (1 + stop_loss_pct)
        
        return stop_price
    
    def validate_risk_reward(
        self,
        risk_pct: float,
        reward_pct: float,
        min_risk_reward_ratio: float = 2.0
    ) -> Tuple[bool, str]:
        """
        Validate risk/reward ratio meets minimum threshold.
        
        Args:
            risk_pct: Risk as decimal (0.05 = 5%)
            reward_pct: Potential reward as decimal (0.10 = 10%)
            min_risk_reward_ratio: Minimum R:R ratio (default 2:1)
            
        Returns:
            Tuple of (is_valid, message)
        """
        if risk_pct <= 0:
            return (False, "Invalid risk percentage")
        
        risk_reward_ratio = reward_pct / risk_pct
        
        if risk_reward_ratio < min_risk_reward_ratio:
            return (False, f"Risk/Reward {risk_reward_ratio:.2f}:1 below minimum {min_risk_reward_ratio:.2f}:1")
        
        return (True, f"Risk/Reward {risk_reward_ratio:.2f}:1 acceptable")
    
    def get_tier_risk_limits(self, tier_name: str) -> Dict:
        """Get risk limits for a tier"""
        config = self.configs.get(tier_name, self.configs['INCOME'])
        
        return {
            'tier': tier_name,
            'max_risk_per_trade_pct': config.max_risk_per_trade_pct * 100,
            'default_stop_loss_pct': config.default_stop_loss_pct * 100,
            'min_stop_loss_pct': config.min_stop_loss_pct * 100,
            'max_stop_loss_pct': config.max_stop_loss_pct * 100
        }
    
    def log_risk_summary(self, calculation: RiskCalculation) -> None:
        """Log risk calculation summary"""
        logger.info("="*70)
        logger.info(f"RISK CONTAINMENT - Tier: {calculation.tier_name}")
        logger.info(f"Account Balance: ${calculation.account_balance:.2f}")
        logger.info(f"Requested Size: ${calculation.requested_position_size:.2f}")
        logger.info(f"Stop Loss: {calculation.stop_loss_pct*100:.2f}%")
        logger.info(f"Max Risk Allowed: {calculation.max_risk_pct*100:.1f}% (${calculation.max_risk_dollars:.2f})")
        logger.info("-"*70)
        
        if calculation.size_reduced:
            logger.info(f"⚠️ SIZE REDUCED: {calculation.reduction_reason}")
        
        logger.info(f"Adjusted Size: ${calculation.risk_adjusted_size:.2f}")
        logger.info(f"Actual Risk: {calculation.actual_risk_pct*100:.2f}% (${calculation.actual_risk_dollars:.2f})")
        logger.info("="*70)


# ============================================================================
# GLOBAL INSTANCE
# ============================================================================
_risk_containment_instance: Optional[RiskContainmentLayer] = None


def get_risk_containment_layer() -> RiskContainmentLayer:
    """Get or create the global RiskContainmentLayer instance"""
    global _risk_containment_instance
    if _risk_containment_instance is None:
        _risk_containment_instance = RiskContainmentLayer()
    return _risk_containment_instance


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def apply_risk_containment(balance: float, tier_name: str, 
                          requested_size: float, stop_loss_pct: float) -> float:
    """
    Apply risk containment and return adjusted position size.
    
    Args:
        balance: Account balance
        tier_name: Tier name
        requested_size: Requested position size
        stop_loss_pct: Stop loss as decimal
        
    Returns:
        Risk-adjusted position size
    """
    layer = get_risk_containment_layer()
    calculation = layer.calculate_risk_adjusted_position_size(
        balance, tier_name, requested_size, stop_loss_pct
    )
    return calculation.risk_adjusted_size


if __name__ == "__main__":
    # Demo: Risk containment for STARTER tier
    import logging
    logging.basicConfig(level=logging.INFO)
    
    layer = RiskContainmentLayer()
    
    print("\n" + "="*100)
    print("RISK CONTAINMENT LAYER - Demo")
    print("="*100 + "\n")
    
    # Example: STARTER tier with 80% concentration
    print("EXAMPLE: STARTER tier wants 80% position (DANGEROUS without risk control)")
    print("-" * 100)
    
    balance = 100.0
    tier = 'STARTER'
    requested_size = 80.0  # 80% concentration
    stop_loss_pct = 0.10   # 10% stop loss
    
    print(f"Account Balance: ${balance:.2f}")
    print(f"Tier: {tier}")
    print(f"Requested Position: ${requested_size:.2f} ({requested_size/balance*100:.0f}%)")
    print(f"Stop Loss: {stop_loss_pct*100:.0f}%")
    print(f"\nWithout risk control: {requested_size} × {stop_loss_pct*100:.0f}% = ${requested_size*stop_loss_pct:.2f} risk ({requested_size*stop_loss_pct/balance*100:.0f}% of account) ❌")
    
    # Apply risk containment
    calculation = layer.calculate_risk_adjusted_position_size(
        balance=balance,
        tier_name=tier,
        requested_size=requested_size,
        stop_loss_pct=stop_loss_pct
    )
    
    print(f"\n{'='*100}")
    print("RISK CONTAINMENT APPLIED:")
    print(f"{'='*100}")
    print(f"Max Risk Allowed: {calculation.max_risk_pct*100:.0f}% (${calculation.max_risk_dollars:.2f})")
    print(f"Risk-Adjusted Size: ${calculation.risk_adjusted_size:.2f} ({calculation.risk_adjusted_size/balance*100:.0f}%)")
    print(f"Actual Risk: {calculation.actual_risk_pct*100:.1f}% (${calculation.actual_risk_dollars:.2f}) ✅")
    
    if calculation.size_reduced:
        print(f"\n⚠️  Position size reduced by ${calculation.requested_position_size - calculation.risk_adjusted_size:.2f}")
        print(f"   Reason: {calculation.reduction_reason}")
    
    # Test all tiers
    print("\n\n" + "="*100)
    print("RISK LIMITS BY TIER")
    print("="*100 + "\n")
    
    print(f"{'Tier':>12} | {'Max Risk':>10} | {'Default Stop':>14} | {'Stop Range':>15}")
    print("-" * 100)
    
    for tier_name in ['STARTER', 'SAVER', 'INVESTOR', 'INCOME', 'LIVABLE', 'BALLER']:
        limits = layer.get_tier_risk_limits(tier_name)
        print(f"{tier_name:>12} | {limits['max_risk_per_trade_pct']:>9.1f}% | "
              f"{limits['default_stop_loss_pct']:>13.1f}% | "
              f"{limits['min_stop_loss_pct']:>5.1f}% - {limits['max_stop_loss_pct']:>5.1f}%")
    
    print("\n" + "="*100)
    print("✅ Risk containment ensures concentration is paired with safety")
    print("="*100 + "\n")
