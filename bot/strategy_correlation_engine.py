"""
NIJA Strategy Correlation Engine

Prevents strategy crowding and hidden risk stacking through:
- Strategy return correlation analysis
- Correlation-based weight adjustment
- Hidden risk detection

This creates true portfolio intelligence.

Author: NIJA Trading Systems
Version: 1.0
Date: January 29, 2026
"""

import logging
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger("nija.strategy_correlation")


@dataclass
class CorrelationAnalysis:
    """Strategy correlation analysis results"""
    correlation_matrix: np.ndarray
    avg_correlations: Dict[str, float]
    adjusted_weights: Dict[str, float]
    crowding_score: float  # 0-100, higher = more crowding
    risk_stacking_detected: bool


class StrategyCorrelationEngine:
    """
    Analyze strategy correlations and adjust weights to prevent crowding
    
    Key Function:
    strategy_weight = base_weight * (1 - avg_corr)
    
    This prevents:
    - Strategy crowding (multiple strategies doing same thing)
    - Hidden risk stacking (correlated strategies amplify risk)
    """
    
    def __init__(self, correlation_threshold: float = 0.7):
        """
        Initialize correlation engine
        
        Args:
            correlation_threshold: Threshold for detecting high correlation (default: 0.7)
        """
        self.correlation_threshold = correlation_threshold
        
        logger.info(f"✅ Strategy Correlation Engine initialized (threshold: {correlation_threshold})")
    
    def calculate_strategy_correlations(self, 
                                       strategy_returns: Dict[str, List[float]]) -> np.ndarray:
        """
        Calculate correlation matrix between strategies
        
        Args:
            strategy_returns: Dictionary mapping strategy names to return arrays
        
        Returns:
            Correlation matrix
        """
        if len(strategy_returns) < 2:
            return np.array([[1.0]])
        
        # Build returns matrix
        strategy_names = list(strategy_returns.keys())
        max_len = max(len(returns) for returns in strategy_returns.values())
        
        # Align all return arrays to same length (pad with zeros)
        aligned_returns = []
        for name in strategy_names:
            returns = strategy_returns[name]
            padded = returns + [0.0] * (max_len - len(returns))
            aligned_returns.append(padded)
        
        returns_matrix = np.array(aligned_returns)
        
        # Calculate correlation
        if returns_matrix.shape[0] > 1 and returns_matrix.shape[1] > 1:
            correlation_matrix = np.corrcoef(returns_matrix)
        else:
            correlation_matrix = np.eye(len(strategy_names))
        
        logger.debug(f"Calculated correlation matrix for {len(strategy_names)} strategies")
        
        return correlation_matrix
    
    def calculate_average_correlations(self,
                                       correlation_matrix: np.ndarray,
                                       strategy_names: List[str]) -> Dict[str, float]:
        """
        Calculate average correlation for each strategy
        
        Args:
            correlation_matrix: Correlation matrix
            strategy_names: List of strategy names
        
        Returns:
            Dictionary mapping strategy names to average correlation
        """
        avg_correlations = {}
        
        n = len(strategy_names)
        for i, name in enumerate(strategy_names):
            # Get correlations with other strategies (exclude self-correlation)
            correlations = []
            for j in range(n):
                if i != j:
                    correlations.append(abs(correlation_matrix[i, j]))
            
            avg_corr = np.mean(correlations) if correlations else 0.0
            avg_correlations[name] = avg_corr
        
        return avg_correlations
    
    def adjust_weights_for_correlation(self,
                                       base_weights: Dict[str, float],
                                       avg_correlations: Dict[str, float]) -> Dict[str, float]:
        """
        Adjust strategy weights based on correlation
        
        Formula: adjusted_weight = base_weight * (1 - avg_corr)
        
        This penalizes highly correlated strategies.
        
        Args:
            base_weights: Base strategy weights
            avg_correlations: Average correlations per strategy
        
        Returns:
            Adjusted weights
        """
        adjusted_weights = {}
        
        for name, base_weight in base_weights.items():
            avg_corr = avg_correlations.get(name, 0.0)
            
            # Apply correlation penalty
            correlation_penalty = 1 - avg_corr
            adjusted_weight = base_weight * correlation_penalty
            
            adjusted_weights[name] = adjusted_weight
            
            logger.debug(f"{name}: {base_weight:.2f} * (1 - {avg_corr:.2f}) = {adjusted_weight:.2f}")
        
        # Renormalize to maintain total weight
        total_adjusted = sum(adjusted_weights.values())
        if total_adjusted > 0:
            adjusted_weights = {
                name: (weight / total_adjusted) * sum(base_weights.values())
                for name, weight in adjusted_weights.items()
            }
        
        return adjusted_weights
    
    def detect_crowding(self,
                       correlation_matrix: np.ndarray,
                       strategy_names: List[str]) -> Tuple[float, bool]:
        """
        Detect strategy crowding and risk stacking
        
        Args:
            correlation_matrix: Correlation matrix
            strategy_names: List of strategy names
        
        Returns:
            Tuple of (crowding_score, risk_stacking_detected)
        """
        if len(strategy_names) < 2:
            return 0.0, False
        
        # Get all pairwise correlations (excluding diagonal)
        n = len(strategy_names)
        correlations = []
        for i in range(n):
            for j in range(i + 1, n):
                correlations.append(abs(correlation_matrix[i, j]))
        
        # Calculate crowding score (0-100)
        avg_correlation = np.mean(correlations) if correlations else 0.0
        crowding_score = avg_correlation * 100
        
        # Detect risk stacking (high correlations)
        high_correlations = [c for c in correlations if c > self.correlation_threshold]
        risk_stacking = len(high_correlations) > 0
        
        if risk_stacking:
            logger.warning(f"⚠️  Risk Stacking Detected: {len(high_correlations)} pairs with correlation > {self.correlation_threshold}")
            for i in range(n):
                for j in range(i + 1, n):
                    corr = abs(correlation_matrix[i, j])
                    if corr > self.correlation_threshold:
                        logger.warning(f"   {strategy_names[i]} ↔ {strategy_names[j]}: {corr:.2f}")
        
        return crowding_score, risk_stacking
    
    def analyze(self,
               strategy_returns: Dict[str, List[float]],
               base_weights: Dict[str, float]) -> CorrelationAnalysis:
        """
        Perform complete correlation analysis
        
        Args:
            strategy_returns: Strategy return histories
            base_weights: Base strategy weights
        
        Returns:
            CorrelationAnalysis with all results
        """
        strategy_names = list(strategy_returns.keys())
        
        # Calculate correlations
        correlation_matrix = self.calculate_strategy_correlations(strategy_returns)
        
        # Calculate average correlations
        avg_correlations = self.calculate_average_correlations(correlation_matrix, strategy_names)
        
        # Adjust weights
        adjusted_weights = self.adjust_weights_for_correlation(base_weights, avg_correlations)
        
        # Detect crowding
        crowding_score, risk_stacking = self.detect_crowding(correlation_matrix, strategy_names)
        
        logger.info(f"📊 Correlation Analysis Complete:")
        logger.info(f"   Crowding Score: {crowding_score:.1f}/100")
        logger.info(f"   Risk Stacking: {'YES ⚠️' if risk_stacking else 'NO ✅'}")
        logger.info(f"   Adjusted Weights:")
        for name, weight in sorted(adjusted_weights.items(), key=lambda x: x[1], reverse=True):
            base = base_weights.get(name, 0)
            change = ((weight - base) / base * 100) if base > 0 else 0
            logger.info(f"      {name}: {weight:.2f} ({change:+.1f}% from base)")
        
        return CorrelationAnalysis(
            correlation_matrix=correlation_matrix,
            avg_correlations=avg_correlations,
            adjusted_weights=adjusted_weights,
            crowding_score=crowding_score,
            risk_stacking_detected=risk_stacking
        )


# Singleton instance
_correlation_engine: Optional[StrategyCorrelationEngine] = None


def get_correlation_engine(correlation_threshold: float = 0.7,
                           reset: bool = False) -> StrategyCorrelationEngine:
    """
    Get or create correlation engine singleton
    
    Args:
        correlation_threshold: Correlation threshold
        reset: Force reset
    
    Returns:
        StrategyCorrelationEngine instance
    """
    global _correlation_engine
    
    if _correlation_engine is None or reset:
        _correlation_engine = StrategyCorrelationEngine(correlation_threshold)
    
    return _correlation_engine
