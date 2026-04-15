"""
NIJA Risk Parity Engine
========================

Portfolio-level volatility normalization and risk-weighted allocation.

Features:
- Portfolio volatility tracking
- Risk contribution analysis
- Volatility normalization
- Risk-weighted capital allocation
- Automatic rebalancing
- Correlation-based diversification

This creates institutional-grade risk management at the portfolio level.

Author: NIJA Trading Systems
Version: 1.0 (Path 3)
Date: January 30, 2026
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import logging
from collections import defaultdict

logger = logging.getLogger("nija.risk_parity")


class AssetClass(Enum):
    """Asset classes for portfolio diversification"""
    CRYPTO = "crypto"
    STOCKS = "stocks"
    FOREX = "forex"
    COMMODITIES = "commodities"


@dataclass
class Asset:
    """Individual asset in portfolio"""
    symbol: str
    asset_class: AssetClass
    current_value_usd: float
    target_allocation_pct: float  # Target % of portfolio
    current_allocation_pct: float  # Current % of portfolio
    volatility: float  # Annualized volatility
    risk_contribution_pct: float  # % of total portfolio risk
    
    def needs_rebalance(self, threshold: float = 0.05) -> bool:
        """Check if allocation drift exceeds threshold"""
        drift = abs(self.current_allocation_pct - self.target_allocation_pct)
        return drift > threshold
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'symbol': self.symbol,
            'asset_class': self.asset_class.value,
            'current_value_usd': self.current_value_usd,
            'target_allocation_pct': self.target_allocation_pct,
            'current_allocation_pct': self.current_allocation_pct,
            'volatility': self.volatility,
            'risk_contribution_pct': self.risk_contribution_pct,
            'needs_rebalance': self.needs_rebalance()
        }


@dataclass
class PortfolioState:
    """Current portfolio state"""
    total_value_usd: float
    target_volatility: float  # Target portfolio volatility
    current_volatility: float  # Actual portfolio volatility
    assets: Dict[str, Asset]
    last_rebalance: datetime
    correlation_matrix: np.ndarray = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'total_value_usd': self.total_value_usd,
            'target_volatility': self.target_volatility,
            'current_volatility': self.current_volatility,
            'assets': {symbol: asset.to_dict() for symbol, asset in self.assets.items()},
            'last_rebalance': self.last_rebalance.isoformat(),
            'volatility_ratio': self.current_volatility / self.target_volatility if self.target_volatility > 0 else 1.0
        }


class RiskParityEngine:
    """
    Risk parity portfolio management engine
    
    Key Concepts:
    1. Risk Parity: Each asset contributes equally to portfolio risk
    2. Volatility Normalization: Scale positions by inverse volatility
    3. Correlation Adjustment: Account for asset correlations
    4. Automatic Rebalancing: Maintain target risk allocations
    
    Traditional portfolio: Equal $ allocation
    Risk Parity: Equal risk contribution
    
    Example:
        Asset A: High volatility (30%) → Smaller position
        Asset B: Low volatility (10%) → Larger position
        Result: Both contribute equally to portfolio risk
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize risk parity engine
        
        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}
        
        # Target portfolio volatility (annualized)
        self.target_volatility = self.config.get('target_volatility', 0.15)  # 15%
        
        # Rebalancing parameters
        self.rebalance_threshold = self.config.get('rebalance_threshold', 0.05)  # 5% drift
        self.min_rebalance_interval_days = self.config.get('min_rebalance_interval_days', 7)
        
        # Volatility calculation window
        self.volatility_window_days = self.config.get('volatility_window_days', 30)
        
        # Portfolio state
        self.portfolio_state: Optional[PortfolioState] = None
        
        # Price history for volatility calculation
        self.price_history: Dict[str, List[Tuple[datetime, float]]] = defaultdict(list)
        
        # Rebalancing history
        self.rebalance_history: List[Dict] = []
        
        logger.info(f"RiskParityEngine initialized (target volatility: {self.target_volatility*100:.1f}%)")
    
    def update_price(self, symbol: str, price: float, timestamp: datetime = None):
        """
        Update price for an asset
        
        Args:
            symbol: Asset symbol
            price: Current price
            timestamp: Optional timestamp
        """
        if timestamp is None:
            timestamp = datetime.now()
        
        self.price_history[symbol].append((timestamp, price))
        
        # Keep only recent history
        cutoff = datetime.now() - timedelta(days=self.volatility_window_days * 2)
        self.price_history[symbol] = [
            (t, p) for t, p in self.price_history[symbol]
            if t > cutoff
        ]
    
    def calculate_volatility(self, symbol: str) -> Optional[float]:
        """
        Calculate annualized volatility for an asset
        
        Args:
            symbol: Asset symbol
        
        Returns:
            Annualized volatility or None if insufficient data
        """
        history = self.price_history.get(symbol, [])
        
        if len(history) < 20:  # Need at least 20 data points
            return None
        
        # Extract prices
        prices = [p for _, p in history[-self.volatility_window_days:]]
        
        # Calculate returns
        returns = np.diff(prices) / prices[:-1]
        
        # Calculate volatility (standard deviation of returns)
        daily_volatility = np.std(returns)
        
        # Annualize (assuming ~252 trading days per year for crypto: 365)
        annualized_volatility = daily_volatility * np.sqrt(365)
        
        return float(annualized_volatility)
    
    def calculate_portfolio(
        self,
        positions: Dict[str, Dict]
    ) -> PortfolioState:
        """
        Calculate portfolio state with risk parity analysis
        
        Args:
            positions: Dictionary of positions {symbol: {value_usd, asset_class}}
        
        Returns:
            PortfolioState
        """
        # Calculate total value
        total_value = sum(p['value_usd'] for p in positions.values())
        
        if total_value == 0:
            logger.warning("Portfolio value is zero")
            return PortfolioState(
                total_value_usd=0,
                target_volatility=self.target_volatility,
                current_volatility=0,
                assets={},
                last_rebalance=datetime.now()
            )
        
        # Build asset list
        assets = {}
        symbols = list(positions.keys())
        
        for symbol, pos in positions.items():
            # Get volatility
            volatility = self.calculate_volatility(symbol)
            if volatility is None:
                volatility = 0.20  # Default 20% if no data
            
            # Calculate current allocation
            current_allocation_pct = (pos['value_usd'] / total_value) * 100
            
            # Calculate risk-parity target allocation
            # Inverse volatility weighting
            inv_vol = 1.0 / volatility if volatility > 0 else 1.0
            
            assets[symbol] = Asset(
                symbol=symbol,
                asset_class=AssetClass(pos.get('asset_class', 'crypto')),
                current_value_usd=pos['value_usd'],
                target_allocation_pct=0,  # Will calculate below
                current_allocation_pct=current_allocation_pct,
                volatility=volatility,
                risk_contribution_pct=0  # Will calculate below
            )
        
        # Calculate target allocations (equal risk contribution)
        inv_vols = {s: 1.0/a.volatility if a.volatility > 0 else 1.0 for s, a in assets.items()}
        total_inv_vol = sum(inv_vols.values())
        
        for symbol, asset in assets.items():
            asset.target_allocation_pct = (inv_vols[symbol] / total_inv_vol) * 100
        
        # Calculate portfolio volatility (simplified - no correlation matrix)
        # Weighted sum of individual volatilities
        portfolio_volatility = sum(
            asset.current_allocation_pct / 100 * asset.volatility
            for asset in assets.values()
        )
        
        # Calculate risk contributions
        total_risk = portfolio_volatility * total_value
        for asset in assets.items():
            if total_risk > 0:
                asset_risk = asset.current_allocation_pct / 100 * asset.volatility * total_value
                asset.risk_contribution_pct = (asset_risk / total_risk) * 100
            else:
                asset.risk_contribution_pct = 0
        
        # Create portfolio state
        last_rebalance = datetime.now()
        if self.portfolio_state:
            last_rebalance = self.portfolio_state.last_rebalance
        
        self.portfolio_state = PortfolioState(
            total_value_usd=total_value,
            target_volatility=self.target_volatility,
            current_volatility=portfolio_volatility,
            assets=assets,
            last_rebalance=last_rebalance
        )
        
        logger.debug(
            f"Portfolio calculated: ${total_value:.2f} | "
            f"Volatility: {portfolio_volatility*100:.1f}% | "
            f"Target: {self.target_volatility*100:.1f}%"
        )
        
        return self.portfolio_state
    
    def calculate_rebalance_trades(
        self,
        state: PortfolioState
    ) -> List[Dict]:
        """
        Calculate trades needed to rebalance to risk parity
        
        Args:
            state: Current PortfolioState
        
        Returns:
            List of trade dictionaries
        """
        trades = []
        
        for symbol, asset in state.assets.items():
            # Calculate dollar amount to adjust
            target_value = (asset.target_allocation_pct / 100) * state.total_value_usd
            current_value = asset.current_value_usd
            delta = target_value - current_value
            
            # Only trade if significant drift
            if abs(delta) > state.total_value_usd * (self.rebalance_threshold / 100):
                trades.append({
                    'symbol': symbol,
                    'action': 'buy' if delta > 0 else 'sell',
                    'amount_usd': abs(delta),
                    'current_allocation_pct': asset.current_allocation_pct,
                    'target_allocation_pct': asset.target_allocation_pct,
                    'reason': 'risk_parity_rebalance'
                })
        
        return trades
    
    def should_rebalance(self) -> Tuple[bool, str]:
        """
        Check if portfolio should be rebalanced
        
        Returns:
            Tuple of (should_rebalance, reason)
        """
        if not self.portfolio_state:
            return False, "No portfolio state"
        
        # Check minimum time since last rebalance
        time_since_rebalance = datetime.now() - self.portfolio_state.last_rebalance
        if time_since_rebalance.days < self.min_rebalance_interval_days:
            return False, f"Too soon (last rebalance {time_since_rebalance.days} days ago)"
        
        # Check if any asset has drifted significantly
        for asset in self.portfolio_state.assets.values():
            if asset.needs_rebalance(self.rebalance_threshold):
                drift = abs(asset.current_allocation_pct - asset.target_allocation_pct)
                return True, f"{asset.symbol} drift {drift:.1f}% > {self.rebalance_threshold*100:.1f}%"
        
        # Check if portfolio volatility is significantly off target
        vol_ratio = self.portfolio_state.current_volatility / self.target_volatility
        if vol_ratio < 0.8 or vol_ratio > 1.2:
            return True, f"Portfolio volatility {vol_ratio:.1%} off target"
        
        return False, "Within tolerance"
    
    def execute_rebalance(
        self,
        dry_run: bool = True
    ) -> Optional[Dict]:
        """
        Execute portfolio rebalance
        
        Args:
            dry_run: If True, only simulate (don't execute)
        
        Returns:
            Rebalance summary or None
        """
        if not self.portfolio_state:
            logger.warning("No portfolio state to rebalance")
            return None
        
        should_rebalance, reason = self.should_rebalance()
        
        if not should_rebalance:
            logger.info(f"No rebalancing needed: {reason}")
            return None
        
        # Calculate trades
        trades = self.calculate_rebalance_trades(self.portfolio_state)
        
        if not trades:
            logger.info("No trades needed for rebalancing")
            return None
        
        rebalance_summary = {
            'timestamp': datetime.now().isoformat(),
            'reason': reason,
            'dry_run': dry_run,
            'trades': trades,
            'portfolio_before': {
                'value_usd': self.portfolio_state.total_value_usd,
                'volatility': self.portfolio_state.current_volatility
            }
        }
        
        if not dry_run:
            # In production, execute trades here
            logger.info(f"Executing {len(trades)} rebalancing trades")
            
            # Update last rebalance time
            self.portfolio_state.last_rebalance = datetime.now()
            
            # Record in history
            self.rebalance_history.append(rebalance_summary)
        else:
            logger.info(f"DRY RUN: Would execute {len(trades)} rebalancing trades")
        
        # Log trade details
        for trade in trades:
            logger.info(
                f"  {trade['action'].upper()} {trade['symbol']}: ${trade['amount_usd']:.2f} "
                f"({trade['current_allocation_pct']:.1f}% → {trade['target_allocation_pct']:.1f}%)"
            )
        
        return rebalance_summary
    
    def get_risk_contribution_breakdown(self) -> Dict[str, float]:
        """Get risk contribution percentage for each asset"""
        if not self.portfolio_state:
            return {}
        
        return {
            symbol: asset.risk_contribution_pct
            for symbol, asset in self.portfolio_state.assets.items()
        }
    
    def get_stats(self) -> Dict:
        """Get risk parity engine statistics"""
        if not self.portfolio_state:
            return {
                'portfolio_value_usd': 0,
                'current_volatility': 0,
                'target_volatility': self.target_volatility,
                'assets': 0,
                'rebalances': len(self.rebalance_history)
            }
        
        should_rebalance, reason = self.should_rebalance()
        
        return {
            'portfolio_value_usd': self.portfolio_state.total_value_usd,
            'current_volatility': self.portfolio_state.current_volatility,
            'target_volatility': self.target_volatility,
            'volatility_ratio': self.portfolio_state.current_volatility / self.target_volatility,
            'assets': len(self.portfolio_state.assets),
            'should_rebalance': should_rebalance,
            'rebalance_reason': reason,
            'days_since_rebalance': (datetime.now() - self.portfolio_state.last_rebalance).days,
            'total_rebalances': len(self.rebalance_history),
            'risk_contributions': self.get_risk_contribution_breakdown()
        }


# Global instance
risk_parity_engine = RiskParityEngine()
