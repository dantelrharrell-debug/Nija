"""
NIJA Multi-Asset Strategy Router

This is the core brain that routes capital between asset classes:
- Crypto (BTC, ETH, altcoins)
- Equities (stocks, ETFs)
- Derivatives (futures, options - Phase 2)

The router reads global market conditions and intelligently shifts capital
to maximize returns while managing risk across all asset classes.

Architecture:
                 ┌───────────────┐
                 │   NIJA AI      │
                 │  CORE BRAIN    │
                 └───────────────┘
                          ↓
        ┌─────────────────────────────────────┐
        │   Multi-Asset Strategy Router        │
        └─────────────────────────────────────┘
         ↓                ↓                 ↓
   Crypto Engine     Equity Engine     Derivatives Engine
         ↓                ↓                 ↓
   Crypto Exchanges    Stock Brokers     Futures / Options

Author: NIJA Trading Systems
Version: 1.0
Date: January 27, 2026
"""

import logging
from enum import Enum
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger("nija.multi_asset_router")


class AssetClass(Enum):
    """Supported asset classes for trading."""
    CRYPTO = "crypto"
    EQUITY = "equity"
    DERIVATIVES = "derivatives"
    CASH = "cash"  # Risk-off protection mode


class MarketRegime(Enum):
    """Market regime detection for adaptive strategy selection."""
    TRENDING_UP = "trending_up"        # Strong uptrend
    TRENDING_DOWN = "trending_down"    # Strong downtrend
    RANGING = "ranging"                # Sideways/choppy
    HIGH_VOLATILITY = "high_volatility"  # VIX spike
    LOW_VOLATILITY = "low_volatility"    # Calm markets
    RISK_OFF = "risk_off"              # Flight to safety


@dataclass
class AssetAllocation:
    """Capital allocation across asset classes."""
    crypto_pct: float = 0.0
    equity_pct: float = 0.0
    derivatives_pct: float = 0.0
    cash_pct: float = 0.0
    
    def validate(self) -> bool:
        """Ensure allocations sum to 100%."""
        total = self.crypto_pct + self.equity_pct + self.derivatives_pct + self.cash_pct
        return abs(total - 100.0) < 0.01  # Allow for floating point errors
    
    def to_dict(self) -> Dict[str, float]:
        """Convert to dictionary."""
        return {
            "crypto": self.crypto_pct,
            "equity": self.equity_pct,
            "derivatives": self.derivatives_pct,
            "cash": self.cash_pct
        }


@dataclass
class MarketConditions:
    """Global market conditions for routing decisions."""
    crypto_volatility: float  # 0-100 scale
    equity_volatility: float  # 0-100 scale (VIX)
    crypto_momentum: float    # -100 to +100
    equity_momentum: float    # -100 to +100
    liquidity_score: float    # 0-100 (higher = more liquid)
    regime: MarketRegime
    
    @classmethod
    def get_current(cls) -> 'MarketConditions':
        """
        Fetch current market conditions from data sources.
        
        TODO: Implement real market data fetching
        For now, returns default conditions.
        """
        return cls(
            crypto_volatility=50.0,
            equity_volatility=20.0,
            crypto_momentum=25.0,
            equity_momentum=10.0,
            liquidity_score=75.0,
            regime=MarketRegime.RANGING
        )


class MultiAssetRouter:
    """
    Core routing engine that allocates capital across asset classes
    based on market conditions, risk parameters, and tier settings.
    """
    
    def __init__(
        self,
        user_tier: str = "SAVER",
        total_capital: float = 100.0,
        risk_tolerance: str = "moderate"
    ):
        """
        Initialize multi-asset router.
        
        Args:
            user_tier: User's subscription tier (STARTER, SAVER, INVESTOR, etc.)
            total_capital: Total available capital across all asset classes
            risk_tolerance: conservative, moderate, aggressive
        """
        self.user_tier = user_tier
        self.total_capital = total_capital
        self.risk_tolerance = risk_tolerance
        
        # Default allocation (100% crypto for backward compatibility)
        self.default_allocation = AssetAllocation(
            crypto_pct=100.0,
            equity_pct=0.0,
            derivatives_pct=0.0,
            cash_pct=0.0
        )
        
        logger.info(f"Initialized MultiAssetRouter: tier={user_tier}, capital=${total_capital:.2f}")
    
    def route_capital(
        self,
        market_conditions: Optional[MarketConditions] = None
    ) -> AssetAllocation:
        """
        Determine optimal capital allocation across asset classes.
        
        This is the core intelligence that decides:
        - High crypto volatility → Shift capital → Crypto scalping
        - Low crypto volatility → Shift → Stock momentum
        - Risk-off macro → Shift → ETFs / cash protection
        - High liquidity → Futures → leverage
        
        Args:
            market_conditions: Current market state (if None, will fetch)
            
        Returns:
            AssetAllocation with percentage splits
        """
        if market_conditions is None:
            market_conditions = MarketConditions.get_current()
        
        # Get regime-based allocation
        allocation = self._get_regime_allocation(market_conditions)
        
        # Apply tier-specific constraints
        allocation = self._apply_tier_constraints(allocation)
        
        # Validate and normalize
        if not allocation.validate():
            logger.warning(f"Invalid allocation {allocation.to_dict()}, using default")
            allocation = self.default_allocation
        
        logger.info(f"Capital allocation: {allocation.to_dict()}")
        return allocation
    
    def _get_regime_allocation(self, conditions: MarketConditions) -> AssetAllocation:
        """
        Determine allocation based on market regime.
        
        Routing Logic:
        - TRENDING_UP (crypto): 80% crypto, 20% equity
        - TRENDING_DOWN: 40% crypto, 40% equity shorts, 20% cash
        - HIGH_VOLATILITY: 90% crypto (scalping opportunities)
        - LOW_VOLATILITY: 60% equity, 40% crypto
        - RISK_OFF: 20% crypto, 30% equity, 50% cash
        - RANGING: 50% crypto, 50% equity
        """
        regime = conditions.regime
        
        if regime == MarketRegime.TRENDING_UP:
            # Strong uptrend - favor crypto
            return AssetAllocation(
                crypto_pct=80.0,
                equity_pct=20.0,
                derivatives_pct=0.0,
                cash_pct=0.0
            )
        
        elif regime == MarketRegime.HIGH_VOLATILITY:
            # High volatility - crypto scalping dominates
            if conditions.crypto_volatility > 70:
                return AssetAllocation(
                    crypto_pct=90.0,
                    equity_pct=10.0,
                    derivatives_pct=0.0,
                    cash_pct=0.0
                )
            else:
                return AssetAllocation(
                    crypto_pct=70.0,
                    equity_pct=30.0,
                    derivatives_pct=0.0,
                    cash_pct=0.0
                )
        
        elif regime == MarketRegime.LOW_VOLATILITY:
            # Low volatility - shift to stock momentum
            return AssetAllocation(
                crypto_pct=40.0,
                equity_pct=60.0,
                derivatives_pct=0.0,
                cash_pct=0.0
            )
        
        elif regime == MarketRegime.RISK_OFF:
            # Risk-off - capital preservation
            return AssetAllocation(
                crypto_pct=20.0,
                equity_pct=30.0,
                derivatives_pct=0.0,
                cash_pct=50.0
            )
        
        elif regime == MarketRegime.RANGING:
            # Sideways market - balanced approach
            return AssetAllocation(
                crypto_pct=50.0,
                equity_pct=50.0,
                derivatives_pct=0.0,
                cash_pct=0.0
            )
        
        else:
            # Default: trending_down or unknown
            return AssetAllocation(
                crypto_pct=40.0,
                equity_pct=40.0,
                derivatives_pct=0.0,
                cash_pct=20.0
            )
    
    def _apply_tier_constraints(self, allocation: AssetAllocation) -> AssetAllocation:
        """
        Apply tier-specific constraints to allocation.
        
        Tier Constraints:
        - STARTER: Crypto only (no multi-asset)
        - SAVER: Crypto only (no multi-asset)
        - INVESTOR: Crypto + Equity
        - INCOME: Full AI (all asset classes)
        - LIVABLE: Full AI (all asset classes)
        - BALLER: Custom AI (all asset classes + derivatives)
        """
        tier = self.user_tier.upper()
        
        # STARTER and SAVER: Crypto only
        if tier in ["STARTER", "SAVER"]:
            return AssetAllocation(
                crypto_pct=100.0,
                equity_pct=0.0,
                derivatives_pct=0.0,
                cash_pct=0.0
            )
        
        # INVESTOR: Crypto + Equity (no derivatives)
        elif tier == "INVESTOR":
            total_active = allocation.crypto_pct + allocation.equity_pct
            if total_active > 0:
                # Redistribute derivatives to crypto/equity proportionally
                if allocation.derivatives_pct > 0:
                    crypto_ratio = allocation.crypto_pct / total_active if total_active > 0 else 0.5
                    equity_ratio = allocation.equity_pct / total_active if total_active > 0 else 0.5
                    
                    new_crypto = allocation.crypto_pct + (allocation.derivatives_pct * crypto_ratio)
                    new_equity = allocation.equity_pct + (allocation.derivatives_pct * equity_ratio)
                    
                    return AssetAllocation(
                        crypto_pct=new_crypto,
                        equity_pct=new_equity,
                        derivatives_pct=0.0,
                        cash_pct=allocation.cash_pct
                    )
            return allocation
        
        # INCOME and LIVABLE: All asset classes except derivatives
        elif tier in ["INCOME", "LIVABLE"]:
            # Redistribute derivatives to crypto/equity
            if allocation.derivatives_pct > 0:
                total_active = allocation.crypto_pct + allocation.equity_pct
                if total_active > 0:
                    crypto_ratio = allocation.crypto_pct / total_active
                    equity_ratio = allocation.equity_pct / total_active
                    
                    new_crypto = allocation.crypto_pct + (allocation.derivatives_pct * crypto_ratio)
                    new_equity = allocation.equity_pct + (allocation.derivatives_pct * equity_ratio)
                    
                    return AssetAllocation(
                        crypto_pct=new_crypto,
                        equity_pct=new_equity,
                        derivatives_pct=0.0,
                        cash_pct=allocation.cash_pct
                    )
            return allocation
        
        # BALLER: Full access to all asset classes
        elif tier == "BALLER":
            return allocation
        
        # Unknown tier: default to crypto only
        else:
            logger.warning(f"Unknown tier {tier}, defaulting to crypto only")
            return AssetAllocation(
                crypto_pct=100.0,
                equity_pct=0.0,
                derivatives_pct=0.0,
                cash_pct=0.0
            )
    
    def get_capital_by_asset_class(
        self,
        allocation: AssetAllocation
    ) -> Dict[AssetClass, float]:
        """
        Convert percentage allocation to dollar amounts.
        
        Args:
            allocation: Percentage allocation across assets
            
        Returns:
            Dictionary mapping AssetClass to dollar amount
        """
        return {
            AssetClass.CRYPTO: self.total_capital * (allocation.crypto_pct / 100.0),
            AssetClass.EQUITY: self.total_capital * (allocation.equity_pct / 100.0),
            AssetClass.DERIVATIVES: self.total_capital * (allocation.derivatives_pct / 100.0),
            AssetClass.CASH: self.total_capital * (allocation.cash_pct / 100.0)
        }
    
    def should_trade_asset_class(
        self,
        asset_class: AssetClass,
        allocation: AssetAllocation
    ) -> bool:
        """
        Determine if a specific asset class should be traded.
        
        Args:
            asset_class: Asset class to check
            allocation: Current allocation
            
        Returns:
            True if asset class has non-zero allocation
        """
        capital = self.get_capital_by_asset_class(allocation)
        return capital[asset_class] > 0.0
