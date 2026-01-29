"""
NIJA Multi-Asset Correlation Weighting System
==============================================

Dynamically adjusts position weights based on correlation analysis to:
1. Maximize portfolio diversification
2. Reduce correlated risk exposure
3. Identify uncorrelated opportunities
4. Optimize capital allocation across asset classes

Features:
- Real-time correlation matrix updates
- Correlation-based position weighting
- Cluster-based capital allocation
- Anti-correlation opportunity detection
- Dynamic rebalancing based on correlation shifts

Author: NIJA Trading Systems
Version: 1.0
Date: January 29, 2026
"""

import logging
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict

# Import existing correlation analyzer
try:
    from bot.mmin.correlation_analyzer import CrossMarketCorrelationAnalyzer
    CORRELATION_ANALYZER_AVAILABLE = True
except ImportError:
    CORRELATION_ANALYZER_AVAILABLE = False
    logging.warning("CrossMarketCorrelationAnalyzer not available - using simplified correlation analysis")

logger = logging.getLogger("nija.correlation_weighting")


@dataclass
class CorrelationWeight:
    """Correlation-based weight adjustment for a position"""
    symbol: str
    base_weight: float  # Original weight (0-1)
    correlation_factor: float  # Adjustment factor based on correlations (0-2)
    adjusted_weight: float  # Final weight after correlation adjustment
    diversification_score: float  # How well this position diversifies portfolio (0-1)
    cluster_id: int  # Which correlation cluster this belongs to
    reasoning: str  # Explanation of adjustment


@dataclass
class CorrelationWeightingResult:
    """Result of correlation-based weighting calculation"""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    weights: Dict[str, CorrelationWeight] = field(default_factory=dict)
    correlation_matrix: Optional[pd.DataFrame] = None
    clusters: Dict[int, List[str]] = field(default_factory=dict)
    summary: str = ""


class CorrelationWeightingSystem:
    """
    Multi-asset correlation weighting system
    
    Adjusts position sizes based on correlation analysis to maximize
    diversification and reduce concentrated risk.
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize Correlation Weighting System
        
        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}
        
        # Weighting parameters
        self.max_correlation = self.config.get('max_correlation', 0.70)  # Max acceptable correlation
        self.correlation_penalty = self.config.get('correlation_penalty', 0.5)  # Weight reduction for correlated assets
        self.diversification_bonus = self.config.get('diversification_bonus', 1.5)  # Weight increase for uncorrelated
        self.min_weight = self.config.get('min_weight', 0.02)  # 2% minimum
        self.max_weight = self.config.get('max_weight', 0.25)  # 25% maximum
        
        # Correlation analysis settings
        self.correlation_window = self.config.get('correlation_window', 50)  # Rolling window
        self.min_data_points = self.config.get('min_data_points', 20)  # Minimum for correlation calc
        
        # Cluster settings
        self.max_clusters = self.config.get('max_clusters', 5)  # Maximum correlation clusters
        self.max_weight_per_cluster = self.config.get('max_weight_per_cluster', 0.40)  # 40% max per cluster
        
        # Initialize correlation analyzer if available
        if CORRELATION_ANALYZER_AVAILABLE:
            self.correlation_analyzer = CrossMarketCorrelationAnalyzer({
                'window_sizes': [self.correlation_window],
                'min_correlation_threshold': 0.5,
            })
        else:
            self.correlation_analyzer = None
        
        # Historical price data for correlation calculation
        self.price_history: Dict[str, pd.Series] = {}
        
        logger.info("=" * 70)
        logger.info("🔗 Correlation Weighting System Initialized")
        logger.info("=" * 70)
        logger.info(f"Max Correlation Threshold: {self.max_correlation:.2f}")
        logger.info(f"Correlation Penalty: {self.correlation_penalty:.2f}x")
        logger.info(f"Diversification Bonus: {self.diversification_bonus:.2f}x")
        logger.info(f"Weight Range: {self.min_weight*100:.0f}%-{self.max_weight*100:.0f}%")
        logger.info(f"Max Weight Per Cluster: {self.max_weight_per_cluster*100:.0f}%")
        logger.info("=" * 70)
    
    def update_price_history(self, symbol: str, prices: pd.Series):
        """
        Update price history for correlation calculation
        
        Args:
            symbol: Trading pair symbol
            prices: Price series (pandas Series with timestamps)
        """
        self.price_history[symbol] = prices
        logger.debug(f"Updated price history for {symbol}: {len(prices)} data points")
    
    def calculate_correlation_matrix(self, symbols: List[str]) -> Optional[pd.DataFrame]:
        """
        Calculate correlation matrix for given symbols
        
        Args:
            symbols: List of trading pair symbols
            
        Returns:
            Correlation matrix (pandas DataFrame) or None if insufficient data
        """
        # Build price DataFrame from history
        price_data = {}
        for symbol in symbols:
            if symbol in self.price_history:
                price_data[symbol] = self.price_history[symbol]
        
        if len(price_data) < 2:
            logger.warning("Need at least 2 symbols for correlation analysis")
            return None
        
        # Create DataFrame
        df = pd.DataFrame(price_data)
        
        # Align to common index (timestamps)
        df = df.dropna()
        
        if len(df) < self.min_data_points:
            logger.warning(f"Insufficient data for correlation: {len(df)} < {self.min_data_points}")
            return None
        
        # Calculate returns (correlation on returns, not prices)
        returns = df.pct_change().dropna()
        
        # Calculate correlation matrix
        if len(returns) >= self.min_data_points:
            corr_matrix = returns.corr()
            logger.info(f"Calculated correlation matrix for {len(symbols)} symbols")
            return corr_matrix
        else:
            logger.warning("Insufficient return data for correlation")
            return None
    
    def calculate_diversification_score(
        self,
        symbol: str,
        correlation_matrix: pd.DataFrame,
        existing_portfolio: List[str]
    ) -> float:
        """
        Calculate how well a symbol diversifies the existing portfolio
        
        Args:
            symbol: Symbol to evaluate
            correlation_matrix: Correlation matrix
            existing_portfolio: List of symbols already in portfolio
            
        Returns:
            Diversification score (0-1, higher is better)
        """
        if symbol not in correlation_matrix.index:
            return 0.5  # Neutral if no data
        
        if not existing_portfolio:
            return 1.0  # First position is perfectly diversifying
        
        # Calculate average correlation with existing positions
        correlations = []
        for existing_symbol in existing_portfolio:
            if existing_symbol in correlation_matrix.columns and existing_symbol != symbol:
                corr = abs(correlation_matrix.loc[symbol, existing_symbol])
                correlations.append(corr)
        
        if not correlations:
            return 1.0  # No correlations = perfect diversification
        
        avg_correlation = np.mean(correlations)
        
        # Score is inverse of average correlation
        # 0 correlation = score 1.0 (perfect)
        # 1 correlation = score 0.0 (no diversification)
        score = 1.0 - avg_correlation
        
        return max(0.0, min(1.0, score))
    
    def cluster_by_correlation(
        self,
        symbols: List[str],
        correlation_matrix: pd.DataFrame
    ) -> Dict[int, List[str]]:
        """
        Cluster symbols by correlation patterns
        
        Args:
            symbols: List of symbols to cluster
            correlation_matrix: Correlation matrix
            
        Returns:
            Dictionary mapping cluster_id -> list of symbols
        """
        if self.correlation_analyzer:
            # Use existing clustering from analyzer
            return self.correlation_analyzer.cluster_markets(correlation_matrix, self.max_clusters)
        else:
            # Simple clustering based on correlation threshold
            clusters = {}
            cluster_id = 0
            assigned = set()
            
            for symbol in symbols:
                if symbol in assigned:
                    continue
                
                # Start new cluster
                cluster = [symbol]
                assigned.add(symbol)
                
                # Find correlated symbols
                for other_symbol in symbols:
                    if other_symbol in assigned or other_symbol == symbol:
                        continue
                    
                    if symbol in correlation_matrix.index and other_symbol in correlation_matrix.columns:
                        corr = abs(correlation_matrix.loc[symbol, other_symbol])
                        if corr >= self.max_correlation:
                            cluster.append(other_symbol)
                            assigned.add(other_symbol)
                
                clusters[cluster_id] = cluster
                cluster_id += 1
            
            logger.info(f"Clustered {len(symbols)} symbols into {len(clusters)} clusters")
            return clusters
    
    def calculate_correlation_weights(
        self,
        positions: List[Dict],
        base_weights: Dict[str, float],
        correlation_matrix: Optional[pd.DataFrame] = None
    ) -> CorrelationWeightingResult:
        """
        Calculate correlation-adjusted weights for positions
        
        Args:
            positions: List of position dictionaries
            base_weights: Dictionary of symbol -> base weight (before correlation adjustment)
            correlation_matrix: Optional pre-calculated correlation matrix
            
        Returns:
            CorrelationWeightingResult with adjusted weights
        """
        logger.info("=" * 70)
        logger.info("🔗 Calculating Correlation-Adjusted Weights")
        logger.info("=" * 70)
        
        symbols = [pos.get('symbol') for pos in positions]
        
        # Calculate correlation matrix if not provided
        if correlation_matrix is None:
            correlation_matrix = self.calculate_correlation_matrix(symbols)
        
        if correlation_matrix is None:
            # No correlation data - return base weights
            logger.warning("No correlation data available - using base weights")
            weights = {
                symbol: CorrelationWeight(
                    symbol=symbol,
                    base_weight=base_weights.get(symbol, 1.0/len(symbols)),
                    correlation_factor=1.0,
                    adjusted_weight=base_weights.get(symbol, 1.0/len(symbols)),
                    diversification_score=0.5,
                    cluster_id=0,
                    reasoning="No correlation data available"
                )
                for symbol in symbols
            }
            return CorrelationWeightingResult(weights=weights, summary="No correlation adjustments (insufficient data)")
        
        # Cluster symbols by correlation
        clusters = self.cluster_by_correlation(symbols, correlation_matrix)
        
        # Create symbol -> cluster_id mapping
        symbol_to_cluster = {}
        for cluster_id, cluster_symbols in clusters.items():
            for symbol in cluster_symbols:
                symbol_to_cluster[symbol] = cluster_id
        
        # Calculate adjusted weights
        weights = {}
        existing_portfolio = []
        
        for symbol in symbols:
            base_weight = base_weights.get(symbol, 1.0/len(symbols))
            
            # Calculate diversification score
            div_score = self.calculate_diversification_score(
                symbol, correlation_matrix, existing_portfolio
            )
            
            # Calculate correlation factor
            if div_score >= 0.7:
                # Good diversification - bonus
                correlation_factor = self.diversification_bonus
                reasoning = f"Low correlation with portfolio (div score: {div_score:.2f}) - weight increased"
            elif div_score >= 0.4:
                # Moderate diversification - neutral
                correlation_factor = 1.0
                reasoning = f"Moderate diversification (div score: {div_score:.2f}) - weight unchanged"
            else:
                # High correlation - penalty
                correlation_factor = self.correlation_penalty
                reasoning = f"High correlation with portfolio (div score: {div_score:.2f}) - weight reduced"
            
            # Apply adjustment
            adjusted_weight = base_weight * correlation_factor
            
            # Apply min/max constraints
            adjusted_weight = max(self.min_weight, min(self.max_weight, adjusted_weight))
            
            # Get cluster ID
            cluster_id = symbol_to_cluster.get(symbol, 0)
            
            weights[symbol] = CorrelationWeight(
                symbol=symbol,
                base_weight=base_weight,
                correlation_factor=correlation_factor,
                adjusted_weight=adjusted_weight,
                diversification_score=div_score,
                cluster_id=cluster_id,
                reasoning=reasoning
            )
            
            existing_portfolio.append(symbol)
            
            logger.info(
                f"{symbol:12s} | Base: {base_weight*100:5.1f}% | "
                f"Adjusted: {adjusted_weight*100:5.1f}% | "
                f"Div Score: {div_score:.2f} | Cluster: {cluster_id} | {reasoning}"
            )
        
        # Normalize weights to sum to 1.0
        total_weight = sum(w.adjusted_weight for w in weights.values())
        if total_weight > 0:
            for symbol in weights:
                weights[symbol].adjusted_weight /= total_weight
        
        # Check cluster constraints
        cluster_weights = defaultdict(float)
        for symbol, weight in weights.items():
            cluster_weights[weight.cluster_id] += weight.adjusted_weight
        
        # Apply cluster constraints
        for cluster_id, total_cluster_weight in cluster_weights.items():
            if total_cluster_weight > self.max_weight_per_cluster:
                # Scale down this cluster
                scale_factor = self.max_weight_per_cluster / total_cluster_weight
                logger.warning(
                    f"Cluster {cluster_id} exceeds max weight ({total_cluster_weight*100:.1f}% > "
                    f"{self.max_weight_per_cluster*100:.0f}%) - scaling down by {scale_factor:.2f}x"
                )
                
                for symbol in weights:
                    if weights[symbol].cluster_id == cluster_id:
                        weights[symbol].adjusted_weight *= scale_factor
        
        # Final normalization
        total_weight = sum(w.adjusted_weight for w in weights.values())
        if total_weight > 0:
            for symbol in weights:
                weights[symbol].adjusted_weight /= total_weight
        
        # Generate summary
        summary = self._generate_summary(weights, clusters, cluster_weights)
        
        logger.info("=" * 70)
        logger.info(summary)
        logger.info("=" * 70)
        
        return CorrelationWeightingResult(
            weights=weights,
            correlation_matrix=correlation_matrix,
            clusters=clusters,
            summary=summary
        )
    
    def _generate_summary(
        self,
        weights: Dict[str, CorrelationWeight],
        clusters: Dict[int, List[str]],
        cluster_weights: Dict[int, float]
    ) -> str:
        """Generate human-readable summary"""
        lines = [
            "\n🔗 CORRELATION WEIGHTING SUMMARY",
            "=" * 70,
            f"Total Positions: {len(weights)}",
            f"Correlation Clusters: {len(clusters)}",
            "",
            "Cluster Allocation:",
        ]
        
        for cluster_id in sorted(clusters.keys()):
            cluster_symbols = clusters[cluster_id]
            cluster_weight = cluster_weights.get(cluster_id, 0)
            lines.append(
                f"  Cluster {cluster_id}: {cluster_weight*100:5.1f}% "
                f"({len(cluster_symbols)} positions) - {', '.join(cluster_symbols[:3])}"
                f"{'...' if len(cluster_symbols) > 3 else ''}"
            )
        
        lines.append("")
        lines.append("Weight Adjustments:")
        
        # Show positions with significant adjustments
        significant_adjustments = [
            (symbol, weight) for symbol, weight in weights.items()
            if abs(weight.adjusted_weight - weight.base_weight) / weight.base_weight > 0.1  # >10% change
        ]
        
        if significant_adjustments:
            for symbol, weight in sorted(significant_adjustments, key=lambda x: abs(x[1].adjusted_weight - x[1].base_weight), reverse=True)[:5]:
                change_pct = ((weight.adjusted_weight - weight.base_weight) / weight.base_weight) * 100
                lines.append(
                    f"  {symbol}: {weight.base_weight*100:.1f}% → {weight.adjusted_weight*100:.1f}% "
                    f"({change_pct:+.1f}%) - {weight.reasoning}"
                )
        else:
            lines.append("  No significant weight adjustments")
        
        return "\n".join(lines)
    
    def get_recommended_allocation(
        self,
        weights: Dict[str, CorrelationWeight],
        total_capital: float
    ) -> Dict[str, float]:
        """
        Get recommended capital allocation in USD
        
        Args:
            weights: Correlation-adjusted weights
            total_capital: Total capital to allocate
            
        Returns:
            Dictionary mapping symbol -> USD amount
        """
        allocation = {}
        for symbol, weight in weights.items():
            allocation[symbol] = weight.adjusted_weight * total_capital
        
        return allocation


def create_correlation_weighting_system(config: Dict = None) -> CorrelationWeightingSystem:
    """
    Factory function to create CorrelationWeightingSystem instance
    
    Args:
        config: Optional configuration
        
    Returns:
        CorrelationWeightingSystem instance
    """
    return CorrelationWeightingSystem(config)


# Example usage
if __name__ == "__main__":
    import logging
    
    logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
    
    # Create system
    system = create_correlation_weighting_system()
    
    # Add some price history
    dates = pd.date_range('2024-01-01', periods=100, freq='1H')
    
    # BTC and ETH are correlated
    btc_prices = pd.Series(np.random.randn(100).cumsum() + 40000, index=dates)
    eth_prices = pd.Series((np.random.randn(100).cumsum() + btc_prices/20).values, index=dates)
    
    # SOL less correlated
    sol_prices = pd.Series(np.random.randn(100).cumsum() + 100, index=dates)
    
    system.update_price_history('BTC-USD', btc_prices)
    system.update_price_history('ETH-USD', eth_prices)
    system.update_price_history('SOL-USD', sol_prices)
    
    # Mock positions
    positions = [
        {'symbol': 'BTC-USD', 'market_value': 10000},
        {'symbol': 'ETH-USD', 'market_value': 8000},
        {'symbol': 'SOL-USD', 'market_value': 5000},
    ]
    
    # Base weights (equal)
    base_weights = {
        'BTC-USD': 0.33,
        'ETH-USD': 0.33,
        'SOL-USD': 0.34,
    }
    
    # Calculate correlation-adjusted weights
    result = system.calculate_correlation_weights(positions, base_weights)
    
    print(result.summary)
    
    # Get recommended allocation
    allocation = system.get_recommended_allocation(result.weights, 50000)
    print("\nRecommended Allocation:")
    for symbol, amount in allocation.items():
        print(f"  {symbol}: ${amount:,.2f}")
