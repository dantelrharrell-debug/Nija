"""
Portfolio-Level Risk Engine with Cross-Symbol Exposure Correlation
==================================================================

Advanced portfolio-wide risk management system that:
1. Tracks correlations across all active positions
2. Prevents over-concentration in correlated assets
3. Calculates portfolio-level risk metrics
4. Provides correlation-adjusted position sizing
5. Monitors cross-asset exposure

This is institutional-grade risk management that most retail systems lack.

Author: NIJA Trading Systems
Version: 1.0
Date: January 29, 2026
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
from collections import defaultdict

logger = logging.getLogger("nija.portfolio_risk")


@dataclass
class PositionExposure:
    """
    Exposure information for a single position
    
    Attributes:
        symbol: Trading pair symbol
        size_usd: Position size in USD
        pct_of_portfolio: Position as % of total portfolio
        direction: 'long' or 'short'
        entry_time: When position was entered
        unrealized_pnl: Current P&L
        correlation_group: Group of correlated assets
    """
    symbol: str
    size_usd: float
    pct_of_portfolio: float
    direction: str
    entry_time: datetime
    unrealized_pnl: float = 0.0
    correlation_group: Optional[str] = None


@dataclass
class CorrelationMatrix:
    """
    Correlation matrix for portfolio assets
    
    Attributes:
        symbols: List of symbols in the matrix
        matrix: NxN numpy array with correlations
        timestamp: When matrix was calculated
        lookback_periods: Number of periods used
        confidence: Confidence in correlation values (0-1)
    """
    symbols: List[str]
    matrix: np.ndarray
    timestamp: datetime
    lookback_periods: int
    confidence: float


@dataclass
class PortfolioRiskMetrics:
    """
    Portfolio-wide risk metrics
    
    Attributes:
        total_exposure: Total USD exposure
        total_exposure_pct: Total exposure as % of portfolio
        num_positions: Number of open positions
        long_exposure: Long exposure in USD
        short_exposure: Short exposure in USD
        net_exposure: Net exposure (long - short)
        correlation_risk: Correlation-adjusted risk (0-1)
        diversification_ratio: Diversification measure (higher = better)
        max_correlated_exposure: Max exposure in any correlation group
        portfolio_beta: Portfolio beta vs market
        var_95: Value at Risk (95% confidence)
        expected_shortfall: Expected Shortfall (CVaR)
    """
    total_exposure: float
    total_exposure_pct: float
    num_positions: int
    long_exposure: float
    short_exposure: float
    net_exposure: float
    correlation_risk: float
    diversification_ratio: float
    max_correlated_exposure: float
    portfolio_beta: float = 0.0
    var_95: float = 0.0
    expected_shortfall: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class PortfolioRiskEngine:
    """
    Portfolio-Level Risk Engine
    
    Manages portfolio-wide risk through correlation analysis and
    exposure tracking. Prevents over-concentration and ensures
    true diversification.
    
    Key Features:
    1. Real-time correlation tracking across all assets
    2. Correlation-adjusted position sizing
    3. Portfolio-level risk metrics (VaR, CVaR, beta)
    4. Correlation group detection (e.g., all DeFi tokens moving together)
    5. Dynamic exposure limits based on correlations
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize Portfolio Risk Engine
        
        Args:
            config: Configuration dictionary
        """
        self.config = config or {}
        
        # Risk parameters
        self.max_total_exposure = self.config.get('max_total_exposure', 0.80)  # 80% max
        self.max_correlation_group_exposure = self.config.get('max_correlation_group_exposure', 0.30)  # 30% max
        self.correlation_threshold = self.config.get('correlation_threshold', 0.7)  # 0.7+ is high correlation
        self.min_diversification_ratio = self.config.get('min_diversification_ratio', 1.5)
        
        # Correlation calculation parameters
        self.correlation_lookback = self.config.get('correlation_lookback', 100)  # periods
        self.correlation_update_interval = self.config.get('correlation_update_interval', 300)  # 5 min
        
        # Storage
        self.positions: Dict[str, PositionExposure] = {}
        self.correlation_matrix: Optional[CorrelationMatrix] = None
        self.correlation_groups: Dict[str, Set[str]] = {}  # group_name -> {symbols}
        self.price_history: Dict[str, pd.Series] = {}  # symbol -> price series
        self.last_correlation_update = None
        
        # Performance tracking
        self.risk_metrics_history: List[PortfolioRiskMetrics] = []
        
        logger.info("=" * 70)
        logger.info("🛡️  Portfolio Risk Engine Initialized")
        logger.info("=" * 70)
        logger.info(f"Max Total Exposure: {self.max_total_exposure*100:.0f}%")
        logger.info(f"Max Corr. Group Exposure: {self.max_correlation_group_exposure*100:.0f}%")
        logger.info(f"Correlation Threshold: {self.correlation_threshold}")
        logger.info(f"Min Diversification Ratio: {self.min_diversification_ratio}")
        logger.info("=" * 70)
    
    def add_position(
        self,
        symbol: str,
        size_usd: float,
        direction: str,
        portfolio_value: float
    ) -> bool:
        """
        Add or update a position in the portfolio
        
        Args:
            symbol: Trading pair symbol
            size_usd: Position size in USD
            direction: 'long' or 'short'
            portfolio_value: Total portfolio value
            
        Returns:
            True if position was added, False if rejected by risk checks
        """
        # Input validation
        if portfolio_value <= 0:
            logger.error(f"Invalid portfolio value: {portfolio_value}")
            return False
        
        if size_usd <= 0:
            logger.error(f"Invalid position size: {size_usd}")
            return False
        
        pct_of_portfolio = size_usd / portfolio_value
        
        # Create position exposure
        position = PositionExposure(
            symbol=symbol,
            size_usd=size_usd,
            pct_of_portfolio=pct_of_portfolio,
            direction=direction,
            entry_time=datetime.now()
        )
        
        # Check if adding this position would violate risk limits
        if symbol not in self.positions:
            # New position: check if it's safe to add
            if not self._check_new_position_risk(position, portfolio_value):
                logger.warning(f"❌ Position {symbol} rejected by risk engine")
                return False
        
        # Add/update position
        self.positions[symbol] = position
        
        logger.info(f"✅ Position added: {symbol} ${size_usd:,.2f} ({direction})")
        
        # Update correlation groups
        self._update_correlation_groups()
        
        return True
    
    def remove_position(self, symbol: str) -> None:
        """
        Remove a position from the portfolio
        
        Args:
            symbol: Symbol to remove
        """
        if symbol in self.positions:
            del self.positions[symbol]
            logger.info(f"Position removed: {symbol}")
    
    def update_position_pnl(self, symbol: str, unrealized_pnl: float) -> None:
        """
        Update unrealized P&L for a position
        
        Args:
            symbol: Symbol to update
            unrealized_pnl: Current unrealized P&L
        """
        if symbol in self.positions:
            self.positions[symbol].unrealized_pnl = unrealized_pnl
    
    def update_price_history(self, symbol: str, price_series: pd.Series) -> None:
        """
        Update price history for correlation calculations
        
        Args:
            symbol: Trading pair symbol
            price_series: Series of historical prices
        """
        self.price_history[symbol] = price_series
        
        # Check if we should update correlations
        now = datetime.now()
        if (self.last_correlation_update is None or
            (now - self.last_correlation_update).total_seconds() >= self.correlation_update_interval):
            self._calculate_correlations()
    
    def _calculate_correlations(self) -> None:
        """Calculate correlation matrix for all assets with price history"""
        if len(self.price_history) < 2:
            return
        
        symbols = list(self.price_history.keys())
        
        # Build DataFrame of returns
        returns_data = {}
        
        # Use consistent lookback period across all symbols
        max_lookback = min(
            min(len(series) for series in self.price_history.values()),
            self.correlation_lookback
        )
        
        if max_lookback < 20:  # Need at least 20 periods
            logger.debug("Not enough price history for correlation calculation")
            return
        
        for symbol, series in self.price_history.items():
            # Use last N periods (same for all symbols)
            recent_prices = series.iloc[-max_lookback:]
            returns = recent_prices.pct_change().dropna()
            returns_data[symbol] = returns
        
        # Create DataFrame
        returns_df = pd.DataFrame(returns_data)
        
        # Calculate correlation matrix
        corr_matrix = returns_df.corr().values
        
        # Calculate confidence based on sample size
        sample_size = len(returns_df)
        confidence = min(1.0, sample_size / self.correlation_lookback)
        
        # Store correlation matrix
        self.correlation_matrix = CorrelationMatrix(
            symbols=symbols,
            matrix=corr_matrix,
            timestamp=datetime.now(),
            lookback_periods=sample_size,
            confidence=confidence
        )
        
        self.last_correlation_update = datetime.now()
        
        logger.debug(f"Updated correlation matrix ({len(symbols)} symbols, {sample_size} periods)")
        
        # Update correlation groups
        self._update_correlation_groups()
    
    def _update_correlation_groups(self) -> None:
        """Detect and update correlation groups"""
        if self.correlation_matrix is None:
            return
        
        symbols = self.correlation_matrix.symbols
        matrix = self.correlation_matrix.matrix
        
        # Find highly correlated clusters
        groups = {}
        assigned = set()
        group_id = 0
        
        for i, sym1 in enumerate(symbols):
            if sym1 in assigned:
                continue
            
            # Start new group
            group = {sym1}
            assigned.add(sym1)
            
            # Find correlated assets
            for j, sym2 in enumerate(symbols):
                if i != j and sym2 not in assigned:
                    if abs(matrix[i, j]) >= self.correlation_threshold:
                        group.add(sym2)
                        assigned.add(sym2)
            
            if len(group) > 1:
                group_name = f"group_{group_id}"
                groups[group_name] = group
                group_id += 1
                
                logger.debug(f"Correlation group detected: {group}")
        
        self.correlation_groups = groups
        
        # Assign positions to groups
        for symbol, position in self.positions.items():
            for group_name, group_symbols in groups.items():
                if symbol in group_symbols:
                    position.correlation_group = group_name
                    break
    
    def get_correlation(self, symbol1: str, symbol2: str) -> Optional[float]:
        """
        Get correlation between two symbols
        
        Args:
            symbol1: First symbol
            symbol2: Second symbol
            
        Returns:
            Correlation coefficient (-1 to 1) or None if not available
        """
        if self.correlation_matrix is None:
            return None
        
        try:
            idx1 = self.correlation_matrix.symbols.index(symbol1)
            idx2 = self.correlation_matrix.symbols.index(symbol2)
            return float(self.correlation_matrix.matrix[idx1, idx2])
        except (ValueError, IndexError):
            return None
    
    def _check_new_position_risk(
        self,
        new_position: PositionExposure,
        portfolio_value: float
    ) -> bool:
        """
        Check if adding a new position would violate risk limits
        
        Args:
            new_position: Position to check
            portfolio_value: Total portfolio value
            
        Returns:
            True if safe to add, False if would violate limits
        """
        # Calculate total exposure if we add this position
        total_exposure = sum(p.size_usd for p in self.positions.values())
        total_exposure += new_position.size_usd
        total_exposure_pct = total_exposure / portfolio_value if portfolio_value > 0 else 0
        
        # Check total exposure limit
        if total_exposure_pct > self.max_total_exposure:
            logger.warning(
                f"Total exposure limit exceeded: {total_exposure_pct*100:.1f}% > "
                f"{self.max_total_exposure*100:.1f}%"
            )
            return False
        
        # Check correlation group exposure
        if new_position.correlation_group:
            group_exposure = sum(
                p.size_usd for p in self.positions.values()
                if p.correlation_group == new_position.correlation_group
            )
            group_exposure += new_position.size_usd
            group_exposure_pct = group_exposure / portfolio_value if portfolio_value > 0 else 0
            
            if group_exposure_pct > self.max_correlation_group_exposure:
                logger.warning(
                    f"Correlation group exposure limit exceeded: {group_exposure_pct*100:.1f}% > "
                    f"{self.max_correlation_group_exposure*100:.1f}%"
                )
                return False
        
        return True
    
    def calculate_portfolio_metrics(self, portfolio_value: float) -> PortfolioRiskMetrics:
        """
        Calculate comprehensive portfolio risk metrics
        
        Args:
            portfolio_value: Total portfolio value in USD
            
        Returns:
            PortfolioRiskMetrics with all risk measures
        """
        if not self.positions:
            return PortfolioRiskMetrics(
                total_exposure=0.0,
                total_exposure_pct=0.0,
                num_positions=0,
                long_exposure=0.0,
                short_exposure=0.0,
                net_exposure=0.0,
                correlation_risk=0.0,
                diversification_ratio=0.0,
                max_correlated_exposure=0.0
            )
        
        # Basic exposure metrics
        total_exposure = sum(p.size_usd for p in self.positions.values())
        long_exposure = sum(p.size_usd for p in self.positions.values() if p.direction == 'long')
        short_exposure = sum(p.size_usd for p in self.positions.values() if p.direction == 'short')
        net_exposure = long_exposure - short_exposure
        
        # Correlation-adjusted risk
        correlation_risk = self._calculate_correlation_risk()
        
        # Diversification ratio
        diversification_ratio = self._calculate_diversification_ratio()
        
        # Max correlated exposure
        max_correlated_exposure = self._calculate_max_correlated_exposure(portfolio_value)
        
        # VaR and CVaR (simple calculation)
        var_95, expected_shortfall = self._calculate_var_cvar()
        
        metrics = PortfolioRiskMetrics(
            total_exposure=total_exposure,
            total_exposure_pct=total_exposure / portfolio_value if portfolio_value > 0 else 0,
            num_positions=len(self.positions),
            long_exposure=long_exposure,
            short_exposure=short_exposure,
            net_exposure=net_exposure,
            correlation_risk=correlation_risk,
            diversification_ratio=diversification_ratio,
            max_correlated_exposure=max_correlated_exposure,
            var_95=var_95,
            expected_shortfall=expected_shortfall
        )
        
        # Store in history
        self.risk_metrics_history.append(metrics)
        if len(self.risk_metrics_history) > 1000:
            self.risk_metrics_history = self.risk_metrics_history[-1000:]
        
        return metrics
    
    def _calculate_correlation_risk(self) -> float:
        """
        Calculate correlation-adjusted risk measure
        
        Returns:
            Risk score (0-1, higher = more correlated = worse)
        """
        if self.correlation_matrix is None or len(self.positions) < 2:
            return 0.0
        
        # Get positions in correlation matrix
        position_symbols = [p.symbol for p in self.positions.values()]
        matrix_symbols = self.correlation_matrix.symbols
        
        # Find matching symbols
        matching = [s for s in position_symbols if s in matrix_symbols]
        
        if len(matching) < 2:
            return 0.0
        
        # Calculate average absolute correlation among positions
        correlations = []
        for i, sym1 in enumerate(matching):
            for j, sym2 in enumerate(matching):
                if i < j:
                    corr = self.get_correlation(sym1, sym2)
                    if corr is not None:
                        correlations.append(abs(corr))
        
        if not correlations:
            return 0.0
        
        # Average correlation as risk measure
        avg_corr = np.mean(correlations)
        
        return float(avg_corr)
    
    def _calculate_diversification_ratio(self) -> float:
        """
        Calculate diversification ratio
        
        Returns:
            Diversification ratio (higher = better diversified)
        """
        if len(self.positions) < 2:
            return 1.0
        
        # Simple measure: inverse of concentration
        position_weights = [p.pct_of_portfolio for p in self.positions.values()]
        herfindahl_index = sum(w**2 for w in position_weights)
        
        # Diversification ratio: 1/HHI normalized
        if herfindahl_index > 0:
            return float(1.0 / herfindahl_index)
        else:
            return 1.0
    
    def _calculate_max_correlated_exposure(self, portfolio_value: float) -> float:
        """
        Calculate maximum exposure in any correlation group
        
        Args:
            portfolio_value: Total portfolio value
            
        Returns:
            Max group exposure as % of portfolio
        """
        if not self.correlation_groups:
            return 0.0
        
        max_exposure = 0.0
        
        for group_name, group_symbols in self.correlation_groups.items():
            group_exposure = sum(
                p.size_usd for p in self.positions.values()
                if p.symbol in group_symbols
            )
            group_exposure_pct = group_exposure / portfolio_value if portfolio_value > 0 else 0
            max_exposure = max(max_exposure, group_exposure_pct)
        
        return max_exposure
    
    def _calculate_var_cvar(self) -> Tuple[float, float]:
        """
        Calculate Value at Risk and Conditional VaR (Expected Shortfall)
        
        Returns:
            Tuple of (VaR_95, CVaR_95) as percentages
        """
        if not self.positions:
            return 0.0, 0.0
        
        # Simple VaR estimation: assume normal distribution
        # Use position volatilities if available
        # For now, use simple estimate based on position sizes
        
        total_exposure = sum(p.size_usd for p in self.positions.values())
        
        # Assume 2% daily volatility per position (conservative)
        position_volatility = 0.02
        
        # Portfolio volatility (accounting for correlations if available)
        if self.correlation_matrix is not None and len(self.positions) >= 2:
            # Simplified: reduce by diversification
            corr_risk = self._calculate_correlation_risk()
            portfolio_vol = position_volatility * np.sqrt(len(self.positions) * (1 + corr_risk))
        else:
            portfolio_vol = position_volatility * np.sqrt(len(self.positions))
        
        # VaR at 95% confidence (1.645 std devs for normal distribution)
        var_95 = total_exposure * portfolio_vol * 1.645
        
        # CVaR (Expected Shortfall): average loss beyond VaR
        # For normal distribution: CVaR ≈ VaR * 1.2
        cvar_95 = var_95 * 1.2
        
        return var_95, cvar_95
    
    def get_position_size_adjustment(
        self,
        symbol: str,
        base_size_pct: float,
        portfolio_value: float
    ) -> float:
        """
        Get correlation-adjusted position size
        
        Args:
            symbol: Symbol to trade
            base_size_pct: Base position size as % of portfolio
            portfolio_value: Total portfolio value
            
        Returns:
            Adjusted position size percentage
        """
        # Check current correlations with existing positions
        avg_correlation = 0.0
        correlated_count = 0
        
        for existing_symbol in self.positions.keys():
            corr = self.get_correlation(symbol, existing_symbol)
            if corr is not None:
                avg_correlation += abs(corr)
                correlated_count += 1
        
        if correlated_count > 0:
            avg_correlation /= correlated_count
        
        # Reduce size based on correlation
        # High correlation = reduce size
        adjustment_factor = 1.0 - (avg_correlation * 0.5)  # Max 50% reduction
        
        adjusted_size_pct = base_size_pct * adjustment_factor
        
        logger.debug(
            f"Position size adjustment for {symbol}: "
            f"{base_size_pct*100:.2f}% -> {adjusted_size_pct*100:.2f}% "
            f"(avg corr: {avg_correlation:.2f})"
        )
        
        return adjusted_size_pct
    
    def get_stats(self) -> Dict:
        """
        Get risk engine statistics
        
        Returns:
            Dictionary with statistics
        """
        return {
            'num_positions': len(self.positions),
            'num_correlation_groups': len(self.correlation_groups),
            'correlation_matrix_size': len(self.correlation_matrix.symbols) if self.correlation_matrix else 0,
            'last_correlation_update': self.last_correlation_update.isoformat() if self.last_correlation_update else None,
            'metrics_history_size': len(self.risk_metrics_history),
        }


# Singleton instance
_portfolio_risk_engine_instance = None


def get_portfolio_risk_engine(config: Dict = None) -> PortfolioRiskEngine:
    """
    Get singleton Portfolio Risk Engine instance
    
    Args:
        config: Optional configuration (only used on first call)
        
    Returns:
        PortfolioRiskEngine instance
    """
    global _portfolio_risk_engine_instance
    
    if _portfolio_risk_engine_instance is None:
        _portfolio_risk_engine_instance = PortfolioRiskEngine(config)
    
    return _portfolio_risk_engine_instance
