"""
Cross-Market Correlation Analyzer
==================================

Analyzes correlations between different asset classes to:
- Identify leading/lagging relationships
- Detect correlation regime changes
- Find diversification opportunities
- Enable cross-market signal confirmation
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from datetime import datetime
import logging

from .mmin_config import CORRELATION_CONFIG

logger = logging.getLogger("nija.mmin.correlation")


class CrossMarketCorrelationAnalyzer:
    """
    Analyzes correlations across multiple asset classes

    Features:
    - Rolling correlation analysis
    - Lead-lag relationship detection
    - Correlation regime detection
    - Market clustering
    - Diversification scoring
    """

    def __init__(self, config: Dict = None):
        """
        Initialize correlation analyzer

        Args:
            config: Optional configuration dictionary
        """
        self.config = config or CORRELATION_CONFIG
        self.window_sizes = self.config['window_sizes']
        self.min_correlation = self.config['min_correlation_threshold']

        # Correlation matrices for different windows
        self.correlation_matrices: Dict[int, pd.DataFrame] = {}

        # Lead-lag relationships
        self.lead_lag_relationships: Dict[Tuple[str, str], Dict] = {}

        logger.info("CrossMarketCorrelationAnalyzer initialized")

    def calculate_correlations(self, data: pd.DataFrame) -> Dict[int, pd.DataFrame]:
        """
        Calculate rolling correlations for multiple window sizes

        Args:
            data: DataFrame with symbols as columns, prices as values

        Returns:
            Dictionary mapping window size to correlation matrix
        """
        # Convert prices to returns for proper correlation analysis
        returns = data.pct_change().dropna()

        correlations = {}

        for window in self.window_sizes:
            if len(returns) >= window:
                # Calculate rolling correlation on returns (not prices)
                corr_matrix = returns.rolling(window=window).corr().iloc[-len(returns.columns):]
                correlations[window] = corr_matrix
                self.correlation_matrices[window] = corr_matrix
                logger.debug(f"Calculated {window}-period correlation matrix")

        return correlations

    def find_correlated_pairs(self, corr_matrix: pd.DataFrame,
                             threshold: float = None) -> List[Tuple[str, str, float]]:
        """
        Find significantly correlated pairs

        Args:
            corr_matrix: Correlation matrix
            threshold: Minimum correlation (uses config default if None)

        Returns:
            List of (symbol1, symbol2, correlation) tuples
        """
        if threshold is None:
            threshold = self.min_correlation

        pairs = []
        symbols = corr_matrix.columns.tolist()

        for i, sym1 in enumerate(symbols):
            for j, sym2 in enumerate(symbols):
                if i < j:  # Only upper triangle
                    corr = corr_matrix.loc[sym1, sym2]
                    if abs(corr) >= threshold:
                        pairs.append((sym1, sym2, corr))

        # Sort by absolute correlation strength
        pairs.sort(key=lambda x: abs(x[2]), reverse=True)

        logger.info(f"Found {len(pairs)} significantly correlated pairs (threshold={threshold:.2f})")
        return pairs

    def detect_lead_lag(self, data: pd.DataFrame, sym1: str, sym2: str,
                       max_lag: int = 20) -> Dict:
        """
        Detect lead-lag relationship between two symbols

        Args:
            data: DataFrame with symbols as columns
            sym1: First symbol
            sym2: Second symbol
            max_lag: Maximum lag periods to test

        Returns:
            Dictionary with lead-lag analysis results
        """
        if sym1 not in data.columns or sym2 not in data.columns:
            logger.warning(f"Symbols {sym1} or {sym2} not in data")
            return {}

        series1 = data[sym1].dropna()
        series2 = data[sym2].dropna()

        # Align series
        common_idx = series1.index.intersection(series2.index)
        series1 = series1.loc[common_idx]
        series2 = series2.loc[common_idx]

        # Ensure sufficient data for lead-lag analysis
        min_required_length = max_lag * 3  # Need at least 3x max_lag for robust analysis
        if len(series1) < min_required_length:
            logger.warning(f"Insufficient data for lead-lag analysis: {len(series1)} < {min_required_length}")
            return {}

        # Calculate cross-correlation at different lags
        cross_corr = []
        lags = range(-max_lag, max_lag + 1)

        for lag in lags:
            if lag < 0:
                # sym1 leads sym2
                corr = series1.iloc[:lag].corr(series2.iloc[-lag:])
            elif lag > 0:
                # sym2 leads sym1
                corr = series1.iloc[lag:].corr(series2.iloc[:-lag])
            else:
                # No lag
                corr = series1.corr(series2)

            cross_corr.append((lag, corr))

        # Find maximum correlation and corresponding lag
        max_corr_idx = np.argmax([abs(c[1]) for c in cross_corr])
        optimal_lag, optimal_corr = cross_corr[max_corr_idx]

        result = {
            'symbol1': sym1,
            'symbol2': sym2,
            'optimal_lag': optimal_lag,
            'optimal_correlation': optimal_corr,
            'leader': sym1 if optimal_lag < 0 else sym2 if optimal_lag > 0 else 'simultaneous',
            'lag_strength': abs(optimal_lag),
            'all_correlations': cross_corr,
        }

        self.lead_lag_relationships[(sym1, sym2)] = result

        logger.debug(f"Lead-lag: {result['leader']} leads by {result['lag_strength']} periods (corr={optimal_corr:.3f})")
        return result

    def get_diversification_score(self, portfolio: List[str],
                                  corr_matrix: pd.DataFrame) -> float:
        """
        Calculate diversification score for a portfolio

        Args:
            portfolio: List of symbols in portfolio
            corr_matrix: Correlation matrix

        Returns:
            Diversification score (0-1, higher is better)
        """
        if len(portfolio) < 2:
            return 0.0

        # Get correlation submatrix for portfolio
        portfolio_corr = corr_matrix.loc[portfolio, portfolio]

        # Calculate average absolute correlation (excluding diagonal)
        n = len(portfolio)
        total_corr = 0.0
        count = 0

        for i in range(n):
            for j in range(i + 1, n):
                total_corr += abs(portfolio_corr.iloc[i, j])
                count += 1

        avg_corr = total_corr / count if count > 0 else 0.0

        # Diversification score is inverse of average correlation
        # Score = 1 - avg_correlation
        # Score near 1 = well diversified (low correlations)
        # Score near 0 = poorly diversified (high correlations)
        score = 1.0 - avg_corr

        logger.debug(f"Portfolio diversification score: {score:.3f} (avg corr={avg_corr:.3f})")
        return score

    def cluster_markets(self, corr_matrix: pd.DataFrame,
                       n_clusters: int = 3) -> Dict[int, List[str]]:
        """
        Cluster markets based on correlation patterns

        Args:
            corr_matrix: Correlation matrix
            n_clusters: Number of clusters to create

        Returns:
            Dictionary mapping cluster ID to list of symbols
        """
        # Simple hierarchical clustering based on correlation distance
        # Distance = 1 - abs(correlation)
        distance_matrix = 1.0 - corr_matrix.abs()

        # Simple agglomerative clustering
        symbols = corr_matrix.columns.tolist()
        clusters = {i: [sym] for i, sym in enumerate(symbols)}

        # Merge closest clusters until we have n_clusters
        while len(clusters) > n_clusters:
            min_dist = float('inf')
            merge_pair = None

            cluster_ids = list(clusters.keys())
            for i, c1 in enumerate(cluster_ids):
                for c2 in cluster_ids[i+1:]:
                    # Calculate average distance between clusters
                    avg_dist = self._cluster_distance(clusters[c1], clusters[c2], distance_matrix)
                    if avg_dist < min_dist:
                        min_dist = avg_dist
                        merge_pair = (c1, c2)

            if merge_pair is None:
                break

            # Merge clusters
            c1, c2 = merge_pair
            clusters[c1].extend(clusters[c2])
            del clusters[c2]

        # Renumber clusters 0, 1, 2, ...
        final_clusters = {i: cluster for i, cluster in enumerate(clusters.values())}

        logger.info(f"Clustered {len(symbols)} markets into {len(final_clusters)} clusters")
        return final_clusters

    def _cluster_distance(self, cluster1: List[str], cluster2: List[str],
                         distance_matrix: pd.DataFrame) -> float:
        """Calculate average distance between two clusters"""
        total_dist = 0.0
        count = 0

        for sym1 in cluster1:
            for sym2 in cluster2:
                if sym1 in distance_matrix.index and sym2 in distance_matrix.columns:
                    total_dist += distance_matrix.loc[sym1, sym2]
                    count += 1

        return total_dist / count if count > 0 else float('inf')

    def get_correlation_regime(self, data: pd.DataFrame,
                              short_window: int = 20,
                              long_window: int = 100) -> Dict:
        """
        Detect correlation regime (increasing/decreasing/stable)

        Args:
            data: DataFrame with symbols as columns
            short_window: Short-term correlation window
            long_window: Long-term correlation window

        Returns:
            Dictionary with regime information
        """
        if len(data) < long_window:
            return {'regime': 'unknown', 'reason': 'insufficient_data'}

        # Calculate average correlation for both windows
        short_corr = data.tail(short_window).corr()
        long_corr = data.tail(long_window).corr()

        # Get average correlation (excluding diagonal)
        def avg_corr(corr_matrix):
            n = len(corr_matrix)
            total = 0.0
            count = 0
            for i in range(n):
                for j in range(i + 1, n):
                    total += abs(corr_matrix.iloc[i, j])
                    count += 1
            return total / count if count > 0 else 0.0

        short_avg = avg_corr(short_corr)
        long_avg = avg_corr(long_corr)

        # Determine regime
        threshold = 0.05
        if short_avg > long_avg + threshold:
            regime = 'increasing'
            description = 'Markets becoming more correlated (risk-on or risk-off)'
        elif short_avg < long_avg - threshold:
            regime = 'decreasing'
            description = 'Markets becoming less correlated (diversification opportunity)'
        else:
            regime = 'stable'
            description = 'Correlation regime stable'

        return {
            'regime': regime,
            'description': description,
            'short_avg_correlation': short_avg,
            'long_avg_correlation': long_avg,
            'correlation_change': short_avg - long_avg,
        }
