"""
NIJA Broker Fee Optimizer
=========================

FIX 6: Coinbase Fee Optimization for Small Balances

Problem:
- Coinbase fees: ~1.4% round trip (0.6% taker fee x2 + 0.2% spread)
- Sub-1% profit targets = guaranteed loss
- Small positions = fees eat all profits

Solution:
- For balances under $50: Disable Coinbase, route to Kraken only
- Alternative: Increase profit target to ≥2% for small Coinbase positions

This module provides intelligent broker routing based on account size
and fee structures.
"""

import logging
from typing import Dict, Optional, List
from enum import Enum

logger = logging.getLogger('nija.fee_optimizer')


class BrokerFeeProfile:
    """Fee profile for a broker."""
    
    def __init__(self, broker_name: str, taker_fee_pct: float, 
                 maker_fee_pct: float, spread_pct: float = 0.002):
        """
        Initialize broker fee profile.
        
        Args:
            broker_name: Name of the broker
            taker_fee_pct: Taker fee percentage (e.g., 0.006 for 0.6%)
            maker_fee_pct: Maker fee percentage (e.g., 0.004 for 0.4%)
            spread_pct: Typical spread percentage (e.g., 0.002 for 0.2%)
        """
        self.broker_name = broker_name
        self.taker_fee_pct = taker_fee_pct
        self.maker_fee_pct = maker_fee_pct
        self.spread_pct = spread_pct
        
    @property
    def market_order_round_trip(self) -> float:
        """
        Calculate round-trip cost for market orders.
        
        Market orders = taker fee both ways + spread
        """
        return (self.taker_fee_pct * 2) + self.spread_pct
    
    @property
    def min_profitable_target_pct(self) -> float:
        """
        Minimum profit target to be profitable after fees.
        
        Returns profit target that yields >0% net profit.
        """
        # Need to beat round-trip fees + small buffer (0.2%)
        return self.market_order_round_trip + 0.002


# Broker fee profiles (updated Jan 2026)
BROKER_FEE_PROFILES = {
    'coinbase': BrokerFeeProfile(
        broker_name='coinbase',
        taker_fee_pct=0.006,   # 0.6% taker fee
        maker_fee_pct=0.004,   # 0.4% maker fee
        spread_pct=0.002       # ~0.2% typical spread
    ),
    'kraken': BrokerFeeProfile(
        broker_name='kraken',
        taker_fee_pct=0.0026,  # 0.26% taker fee
        maker_fee_pct=0.0016,  # 0.16% maker fee
        spread_pct=0.001       # ~0.1% typical spread
    ),
    'alpaca': BrokerFeeProfile(
        broker_name='alpaca',
        taker_fee_pct=0.0,     # Commission-free trading
        maker_fee_pct=0.0,
        spread_pct=0.001       # ~0.1% typical spread
    ),
}


class BrokerFeeOptimizer:
    """
    FIX 6: Intelligent broker routing based on account size and fees.
    
    Routes trades to the most cost-effective broker based on:
    - Account balance
    - Broker fee structure
    - Position size
    """
    
    # Balance threshold for Coinbase disqualification
    COINBASE_MIN_BALANCE = 50.0  # $50 minimum for Coinbase profitability
    
    def __init__(self):
        """Initialize broker fee optimizer."""
        logger.info("Broker Fee Optimizer initialized")
        logger.info(f"   Coinbase minimum balance: ${self.COINBASE_MIN_BALANCE:.2f}")
        
        # Log fee profiles
        for broker_name, profile in BROKER_FEE_PROFILES.items():
            logger.info(f"   {broker_name.title()}: {profile.market_order_round_trip*100:.2f}% round-trip, "
                       f"min target: {profile.min_profitable_target_pct*100:.2f}%")
    
    def should_disable_coinbase(self, balance_usd: float) -> bool:
        """
        Check if Coinbase should be disabled due to small balance.
        
        FIX 6: For balances under $50, disable Coinbase.
        
        Args:
            balance_usd: Account balance in USD
            
        Returns:
            True if Coinbase should be disabled
        """
        if balance_usd < self.COINBASE_MIN_BALANCE:
            logger.warning(
                f"⚠️ Coinbase DISABLED for account balance ${balance_usd:.2f} "
                f"(minimum: ${self.COINBASE_MIN_BALANCE:.2f})"
            )
            logger.warning(
                f"   Reason: Coinbase fees (~1.4% round-trip) will eat profits "
                f"on small positions"
            )
            logger.warning(f"   Solution: Routing trades to Kraken (lower fees)")
            return True
        
        return False
    
    def get_optimal_broker(self, balance_usd: float, 
                          available_brokers: List[str]) -> Optional[str]:
        """
        Select the optimal broker for trading based on balance and fees.
        
        FIX 6: Route small balances away from Coinbase to Kraken.
        
        Args:
            balance_usd: Account balance in USD
            available_brokers: List of connected broker names
            
        Returns:
            Optimal broker name, or None if no suitable broker
        """
        if not available_brokers:
            logger.error("No brokers available for trading")
            return None
        
        # Filter out Coinbase if balance is too small
        eligible_brokers = []
        for broker in available_brokers:
            broker_lower = broker.lower()
            
            if broker_lower == 'coinbase':
                if self.should_disable_coinbase(balance_usd):
                    # Skip Coinbase for small balances
                    continue
            
            eligible_brokers.append(broker)
        
        if not eligible_brokers:
            logger.error(
                f"No eligible brokers for balance ${balance_usd:.2f}. "
                f"Available: {available_brokers}"
            )
            return None
        
        # Prioritize by fee structure
        # 1. Alpaca (free trading)
        # 2. Kraken (low fees)
        # 3. Coinbase (high fees, only if balance is sufficient)
        
        priority_order = ['alpaca', 'kraken', 'coinbase']
        
        for preferred_broker in priority_order:
            for broker in eligible_brokers:
                if broker.lower() == preferred_broker:
                    logger.info(f"✅ Selected broker: {broker.title()} "
                               f"(balance: ${balance_usd:.2f})")
                    return broker
        
        # Fallback: return first eligible broker
        selected = eligible_brokers[0]
        logger.info(f"✅ Selected broker: {selected.title()} (fallback)")
        return selected
    
    def get_minimum_profit_target(self, broker_name: str) -> float:
        """
        Get minimum profit target for a broker to be profitable after fees.
        
        Args:
            broker_name: Name of the broker
            
        Returns:
            Minimum profit target percentage (e.g., 0.02 for 2%)
        """
        broker_lower = broker_name.lower()
        
        if broker_lower in BROKER_FEE_PROFILES:
            profile = BROKER_FEE_PROFILES[broker_lower]
            return profile.min_profitable_target_pct
        
        # Conservative default
        logger.warning(f"Unknown broker {broker_name}, using conservative 2% target")
        return 0.02
    
    def adjust_profit_target_for_fees(self, broker_name: str, 
                                     balance_usd: float,
                                     base_target_pct: float = 0.01) -> float:
        """
        Adjust profit target based on broker fees and account size.
        
        FIX 6 Alternative: Increase profit target to ≥2% for small Coinbase positions.
        
        Args:
            broker_name: Name of the broker
            balance_usd: Account balance
            base_target_pct: Base profit target (e.g., 0.01 for 1%)
            
        Returns:
            Adjusted profit target percentage
        """
        broker_lower = broker_name.lower()
        
        # Get broker fee profile
        if broker_lower not in BROKER_FEE_PROFILES:
            logger.warning(f"Unknown broker {broker_name}, using base target")
            return base_target_pct
        
        profile = BROKER_FEE_PROFILES[broker_lower]
        min_target = profile.min_profitable_target_pct
        
        # If Coinbase with small balance, enforce higher target
        if broker_lower == 'coinbase' and balance_usd < self.COINBASE_MIN_BALANCE:
            # Enforce minimum 2% target for small Coinbase accounts
            adjusted = max(min_target, 0.02)
            
            logger.warning(
                f"⚠️ Small Coinbase account (${balance_usd:.2f}): "
                f"Increasing profit target from {base_target_pct*100:.1f}% "
                f"to {adjusted*100:.1f}%"
            )
            
            return adjusted
        
        # Otherwise, ensure target beats fees
        adjusted = max(base_target_pct, min_target)
        
        if adjusted > base_target_pct:
            logger.info(
                f"Adjusted profit target for {broker_name}: "
                f"{base_target_pct*100:.1f}% → {adjusted*100:.1f}% "
                f"(to beat {profile.market_order_round_trip*100:.2f}% fees)"
            )
        
        return adjusted


__all__ = [
    'BrokerFeeProfile',
    'BrokerFeeOptimizer',
    'BROKER_FEE_PROFILES'
]
