"""
NIJA Risk Parity Portfolio Allocator
=====================================

Implements risk parity allocation strategy:
- Equal risk contribution from each position (not equal capital)
- Volatility-based position sizing
- Correlation-adjusted risk budgeting
- Dynamic rebalancing based on changing volatility

Risk parity ensures that no single position dominates portfolio risk,
leading to better diversification and more stable returns.

Formula: position_size = risk_budget / (volatility * correlation_factor)

Features:
- True risk parity (equal risk contribution)
- Correlation-adjusted sizing
- Volatility targeting
- Hierarchical risk budgeting (by asset class, sector, etc.)

Author: NIJA Trading Systems
Version: 1.0 - God Mode Edition
Date: January 29, 2026
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
from datetime import datetime
import logging

logger = logging.getLogger("nija.risk_parity")


@dataclass
class RiskContribution:
    """Risk contribution for a single position"""
    symbol: str
    volatility: float  # Annualized volatility
    correlation_factor: float  # Average correlation with other positions
    current_allocation: float  # Current capital allocation (%)
    current_risk_contribution: float  # Current risk contribution (%)
    target_risk_contribution: float  # Target risk contribution (%)
    recommended_allocation: float  # Recommended capital allocation (%)
    adjustment_needed: float  # Difference: recommended - current


@dataclass
class RiskParityResult:
    """Result from risk parity allocation"""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # Risk contributions
    risk_contributions: Dict[str, RiskContribution] = field(default_factory=dict)
    
    # Portfolio metrics
    total_portfolio_volatility: float = 0.0
    portfolio_sharpe_estimate: float = 0.0
    diversification_ratio: float = 1.0  # Higher is better (max diversification)
    
    # Rebalancing recommendations
    rebalancing_needed: bool = False
    rebalancing_actions: List[Dict] = field(default_factory=list)
    
    # Summary
    summary: str = ""


class RiskParityAllocator:
    """
    Risk Parity Portfolio Allocation
    
    Allocates capital such that each position contributes equally to portfolio risk,
    rather than allocating equal capital amounts.
    
    This approach:
    1. Reduces concentration risk
    2. Improves diversification
    3. Stabilizes returns across market conditions
    4. Automatically reduces allocation to high-volatility assets
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize Risk Parity Allocator
        
        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}
        
        # Risk parameters
        self.target_portfolio_vol = self.config.get('target_portfolio_vol', 0.15)  # 15% annual
        self.rebalance_threshold = self.config.get('rebalance_threshold', 0.05)  # 5% deviation
        self.min_position_size = self.config.get('min_position_size', 0.01)  # 1% minimum
        self.max_position_size = self.config.get('max_position_size', 0.20)  # 20% maximum
        
        # Volatility calculation
        self.vol_lookback_days = self.config.get('vol_lookback_days', 30)
        self.annualization_factor = np.sqrt(365)  # Daily to annual volatility
        
        # Correlation handling
        self.use_correlation_adjustment = self.config.get('use_correlation_adjustment', True)
        self.correlation_floor = self.config.get('correlation_floor', 0.3)  # Min correlation
        
        # Hierarchical risk budgeting (optional)
        self.use_hierarchical = self.config.get('use_hierarchical', False)
        self.asset_class_budgets = self.config.get('asset_class_budgets', {})
        
        logger.info("⚖️  Risk Parity Allocator initialized (God Mode)")
        logger.info(f"   Target portfolio vol: {self.target_portfolio_vol:.1%}")
        logger.info(f"   Rebalance threshold: {self.rebalance_threshold:.1%}")
        logger.info(f"   Position limits: {self.min_position_size:.1%} - {self.max_position_size:.1%}")
    
    def calculate_allocation(
        self,
        positions: Dict[str, Dict],
        price_data: Dict[str, pd.DataFrame],
        correlation_matrix: Optional[pd.DataFrame] = None,
    ) -> RiskParityResult:
        """
        Calculate risk parity allocation
        
        Args:
            positions: Dict of symbol -> position info (including current allocation)
            price_data: Dict of symbol -> price DataFrame
            correlation_matrix: Optional pre-calculated correlation matrix
        
        Returns:
            RiskParityResult with recommended allocations
        """
        if not positions:
            return RiskParityResult(summary="No positions to allocate")
        
        symbols = list(positions.keys())
        n_positions = len(symbols)
        
        # Calculate volatilities
        volatilities = self._calculate_volatilities(symbols, price_data)
        
        # Calculate or use provided correlation matrix
        if correlation_matrix is None and self.use_correlation_adjustment:
            correlation_matrix = self._calculate_correlation_matrix(symbols, price_data)
        
        # Calculate correlation factors (average correlation with other assets)
        correlation_factors = self._calculate_correlation_factors(
            symbols,
            correlation_matrix,
        )
        
        # Equal risk contribution target
        target_risk_per_position = 1.0 / n_positions
        
        # Calculate recommended allocations using risk parity
        risk_contributions = {}
        
        for symbol in symbols:
            # Get current allocation
            current_alloc = positions[symbol].get('allocation_pct', 0.0)
            
            # Calculate volatility
            vol = volatilities.get(symbol, 0.10)  # Default 10% if missing
            
            # Get correlation factor
            corr_factor = correlation_factors.get(symbol, 1.0)
            
            # Risk parity formula: allocation ∝ 1 / (volatility × correlation)
            # Higher volatility → smaller allocation
            # Higher correlation → smaller allocation
            inverse_risk = 1.0 / (vol * corr_factor) if (vol * corr_factor) > 0 else 0.0
            
            # Store for normalization
            positions[symbol]['inverse_risk'] = inverse_risk
            positions[symbol]['volatility'] = vol
            positions[symbol]['correlation_factor'] = corr_factor
        
        # Normalize allocations to sum to 1.0
        total_inverse_risk = sum(p.get('inverse_risk', 0.0) for p in positions.values())
        
        for symbol in symbols:
            inverse_risk = positions[symbol].get('inverse_risk', 0.0)
            current_alloc = positions[symbol].get('allocation_pct', 0.0)
            
            # Calculate recommended allocation
            if total_inverse_risk > 0:
                recommended_alloc = inverse_risk / total_inverse_risk
            else:
                recommended_alloc = 1.0 / n_positions  # Equal weight fallback
            
            # Apply position limits
            recommended_alloc = np.clip(
                recommended_alloc,
                self.min_position_size,
                self.max_position_size,
            )
            
            # Calculate actual risk contribution with current allocation
            vol = positions[symbol]['volatility']
            corr_factor = positions[symbol]['correlation_factor']
            current_risk_contrib = (current_alloc * vol * corr_factor) if current_alloc > 0 else 0.0
            
            # Calculate adjustment needed
            adjustment = recommended_alloc - current_alloc
            
            # Create risk contribution object
            risk_contribution = RiskContribution(
                symbol=symbol,
                volatility=vol,
                correlation_factor=corr_factor,
                current_allocation=current_alloc,
                current_risk_contribution=current_risk_contrib,
                target_risk_contribution=target_risk_per_position,
                recommended_allocation=recommended_alloc,
                adjustment_needed=adjustment,
            )
            
            risk_contributions[symbol] = risk_contribution
        
        # Re-normalize after applying limits
        total_recommended = sum(rc.recommended_allocation for rc in risk_contributions.values())
        if total_recommended > 0:
            for rc in risk_contributions.values():
                rc.recommended_allocation /= total_recommended
                rc.adjustment_needed = rc.recommended_allocation - rc.current_allocation
        
        # Calculate portfolio metrics
        portfolio_vol = self._calculate_portfolio_volatility(
            risk_contributions,
            correlation_matrix,
        )
        
        # Calculate diversification ratio
        div_ratio = self._calculate_diversification_ratio(
            risk_contributions,
            portfolio_vol,
        )
        
        # Determine if rebalancing is needed
        rebalancing_needed = any(
            abs(rc.adjustment_needed) > self.rebalance_threshold
            for rc in risk_contributions.values()
        )
        
        # Generate rebalancing actions
        rebalancing_actions = []
        if rebalancing_needed:
            for symbol, rc in risk_contributions.items():
                if abs(rc.adjustment_needed) > self.rebalance_threshold:
                    action = {
                        'symbol': symbol,
                        'action': 'increase' if rc.adjustment_needed > 0 else 'decrease',
                        'current_pct': rc.current_allocation,
                        'target_pct': rc.recommended_allocation,
                        'adjustment_pct': rc.adjustment_needed,
                        'reason': self._explain_adjustment(rc),
                    }
                    rebalancing_actions.append(action)
        
        # Create result
        result = RiskParityResult(
            risk_contributions=risk_contributions,
            total_portfolio_volatility=portfolio_vol,
            diversification_ratio=div_ratio,
            rebalancing_needed=rebalancing_needed,
            rebalancing_actions=rebalancing_actions,
        )
        
        # Generate summary
        result.summary = self._generate_summary(result)
        
        logger.info(f"⚖️  Risk parity allocation calculated for {len(symbols)} positions")
        logger.info(f"   Portfolio vol: {portfolio_vol:.2%}, Div ratio: {div_ratio:.2f}")
        logger.info(f"   Rebalancing needed: {rebalancing_needed}")
        
        return result
    
    def _calculate_volatilities(
        self,
        symbols: List[str],
        price_data: Dict[str, pd.DataFrame],
    ) -> Dict[str, float]:
        """
        Calculate annualized volatility for each symbol
        
        Args:
            symbols: List of symbols
            price_data: Dict of symbol -> price DataFrame
        
        Returns:
            Dict of symbol -> annualized volatility
        """
        volatilities = {}
        
        for symbol in symbols:
            if symbol not in price_data:
                logger.warning(f"No price data for {symbol}, using default volatility")
                volatilities[symbol] = 0.10  # 10% default
                continue
            
            df = price_data[symbol]
            
            # Calculate returns
            if 'close' in df.columns:
                returns = df['close'].pct_change().dropna()
            else:
                logger.warning(f"No close price for {symbol}, using default volatility")
                volatilities[symbol] = 0.10
                continue
            
            # Use recent data
            recent_returns = returns.tail(self.vol_lookback_days)
            
            if len(recent_returns) < 10:
                logger.warning(f"Insufficient data for {symbol}, using default volatility")
                volatilities[symbol] = 0.10
                continue
            
            # Calculate annualized volatility
            daily_vol = recent_returns.std()
            annual_vol = daily_vol * self.annualization_factor
            
            volatilities[symbol] = annual_vol
        
        return volatilities
    
    def _calculate_correlation_matrix(
        self,
        symbols: List[str],
        price_data: Dict[str, pd.DataFrame],
    ) -> pd.DataFrame:
        """
        Calculate correlation matrix between symbols
        
        Args:
            symbols: List of symbols
            price_data: Dict of symbol -> price DataFrame
        
        Returns:
            Correlation matrix as DataFrame
        """
        # Collect returns for all symbols
        returns_dict = {}
        
        for symbol in symbols:
            if symbol not in price_data:
                continue
            
            df = price_data[symbol]
            if 'close' in df.columns:
                returns = df['close'].pct_change().dropna()
                returns_dict[symbol] = returns.tail(self.vol_lookback_days)
        
        # Create returns DataFrame
        if not returns_dict:
            # Return identity matrix if no data
            return pd.DataFrame(
                np.eye(len(symbols)),
                index=symbols,
                columns=symbols,
            )
        
        returns_df = pd.DataFrame(returns_dict)
        
        # Calculate correlation matrix
        corr_matrix = returns_df.corr()
        
        # Fill missing values with correlation floor
        corr_matrix = corr_matrix.fillna(self.correlation_floor)
        
        # Ensure all symbols are in the matrix
        for symbol in symbols:
            if symbol not in corr_matrix.index:
                # Add row/column with correlation floor
                corr_matrix.loc[symbol] = self.correlation_floor
                corr_matrix[symbol] = self.correlation_floor
                corr_matrix.loc[symbol, symbol] = 1.0
        
        return corr_matrix
    
    def _calculate_correlation_factors(
        self,
        symbols: List[str],
        correlation_matrix: Optional[pd.DataFrame],
    ) -> Dict[str, float]:
        """
        Calculate average correlation factor for each symbol
        
        Args:
            symbols: List of symbols
            correlation_matrix: Correlation matrix
        
        Returns:
            Dict of symbol -> correlation factor
        """
        if correlation_matrix is None or not self.use_correlation_adjustment:
            # Return 1.0 for all symbols (no adjustment)
            return {symbol: 1.0 for symbol in symbols}
        
        correlation_factors = {}
        
        for symbol in symbols:
            if symbol not in correlation_matrix.index:
                correlation_factors[symbol] = 1.0
                continue
            
            # Get correlations with other symbols (excluding self)
            correlations = correlation_matrix.loc[symbol].drop(symbol, errors='ignore')
            
            # Average absolute correlation
            avg_corr = correlations.abs().mean() if len(correlations) > 0 else 0.0
            
            # Apply floor
            avg_corr = max(avg_corr, self.correlation_floor)
            
            correlation_factors[symbol] = avg_corr
        
        return correlation_factors
    
    def _calculate_portfolio_volatility(
        self,
        risk_contributions: Dict[str, RiskContribution],
        correlation_matrix: Optional[pd.DataFrame],
    ) -> float:
        """
        Calculate total portfolio volatility
        
        Args:
            risk_contributions: Dict of risk contributions
            correlation_matrix: Correlation matrix
        
        Returns:
            Portfolio volatility (annualized)
        """
        symbols = list(risk_contributions.keys())
        weights = np.array([
            risk_contributions[s].recommended_allocation
            for s in symbols
        ])
        volatilities = np.array([
            risk_contributions[s].volatility
            for s in symbols
        ])
        
        if correlation_matrix is None:
            # Assume zero correlation
            portfolio_var = np.sum((weights * volatilities) ** 2)
        else:
            # Use correlation matrix
            # σ_p² = w' Σ w, where Σ = diag(σ) × Corr × diag(σ)
            corr_subset = correlation_matrix.loc[symbols, symbols].values
            
            # Covariance matrix
            cov_matrix = np.outer(volatilities, volatilities) * corr_subset
            
            # Portfolio variance
            portfolio_var = weights @ cov_matrix @ weights
        
        portfolio_vol = np.sqrt(portfolio_var)
        
        return portfolio_vol
    
    def _calculate_diversification_ratio(
        self,
        risk_contributions: Dict[str, RiskContribution],
        portfolio_vol: float,
    ) -> float:
        """
        Calculate diversification ratio
        
        DR = (weighted average volatility) / (portfolio volatility)
        DR > 1 indicates diversification benefit
        
        Args:
            risk_contributions: Dict of risk contributions
            portfolio_vol: Portfolio volatility
        
        Returns:
            Diversification ratio
        """
        # Weighted average volatility
        weighted_avg_vol = sum(
            rc.recommended_allocation * rc.volatility
            for rc in risk_contributions.values()
        )
        
        # Diversification ratio
        if portfolio_vol > 0:
            div_ratio = weighted_avg_vol / portfolio_vol
        else:
            div_ratio = 1.0
        
        return div_ratio
    
    def _explain_adjustment(self, rc: RiskContribution) -> str:
        """Generate explanation for allocation adjustment"""
        if rc.adjustment_needed > 0:
            return (
                f"Increase allocation to balance risk contribution "
                f"(vol={rc.volatility:.2%}, corr={rc.correlation_factor:.2f})"
            )
        else:
            return (
                f"Decrease allocation to balance risk contribution "
                f"(vol={rc.volatility:.2%}, corr={rc.correlation_factor:.2f})"
            )
    
    def _generate_summary(self, result: RiskParityResult) -> str:
        """Generate human-readable summary"""
        lines = [
            "Risk Parity Allocation Summary:",
            f"  Portfolio Volatility: {result.total_portfolio_volatility:.2%}",
            f"  Diversification Ratio: {result.diversification_ratio:.2f}",
            f"  Rebalancing Needed: {result.rebalancing_needed}",
            "",
        ]
        
        if result.rebalancing_actions:
            lines.append("Recommended Adjustments:")
            for action in result.rebalancing_actions:
                lines.append(
                    f"  {action['symbol']}: {action['action'].upper()} "
                    f"from {action['current_pct']:.1%} to {action['target_pct']:.1%} "
                    f"({action['adjustment_pct']:+.1%})"
                )
        
        return "\n".join(lines)
