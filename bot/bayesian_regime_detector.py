"""
NIJA Bayesian Regime Probability Engine
========================================

Uses Bayesian inference to probabilistically classify market regimes:
- Prior probabilities based on historical regime frequencies
- Likelihood based on current market indicators
- Posterior probabilities for each regime
- Confidence scores for regime transitions

This provides more nuanced regime detection than hard thresholds,
allowing the strategy to adapt to regime uncertainty.

Features:
- Probabilistic regime classification (not binary)
- Confidence-weighted strategy parameters
- Regime transition detection
- Prior updating based on observed performance

Author: NIJA Trading Systems
Version: 1.0 - God Mode Edition
Date: January 29, 2026
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
from datetime import datetime
from collections import deque
import logging

# Import existing regime types
try:
    from bot.market_regime_detector import MarketRegime, RegimeDetector
except ImportError:
    from market_regime_detector import MarketRegime, RegimeDetector

logger = logging.getLogger("nija.bayesian_regime")


@dataclass
class RegimeProbabilities:
    """Probability distribution over market regimes"""
    trending: float
    ranging: float
    volatile: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    def most_likely_regime(self) -> MarketRegime:
        """Return the most likely regime"""
        probs = {
            MarketRegime.TRENDING: self.trending,
            MarketRegime.RANGING: self.ranging,
            MarketRegime.VOLATILE: self.volatile,
        }
        return max(probs.items(), key=lambda x: x[1])[0]
    
    def confidence(self) -> float:
        """Return confidence in the most likely regime (0-1)"""
        max_prob = max(self.trending, self.ranging, self.volatile)
        # High confidence if one regime has >70% probability
        # Low confidence if probabilities are evenly distributed
        return max_prob
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for logging/storage"""
        return {
            'trending': self.trending,
            'ranging': self.ranging,
            'volatile': self.volatile,
            'most_likely': self.most_likely_regime().value,
            'confidence': self.confidence(),
            'timestamp': self.timestamp.isoformat(),
        }


@dataclass
class BayesianRegimeResult:
    """Result from Bayesian regime detection"""
    probabilities: RegimeProbabilities
    prior: RegimeProbabilities
    likelihood: Dict[MarketRegime, float]
    evidence: float  # P(indicators)
    regime: MarketRegime
    confidence: float
    transition_detected: bool = False
    previous_regime: Optional[MarketRegime] = None


class BayesianRegimeDetector:
    """
    Bayesian approach to market regime detection
    
    Uses Bayes' theorem: P(regime|indicators) = P(indicators|regime) * P(regime) / P(indicators)
    
    Components:
    - Prior P(regime): Historical frequency of each regime
    - Likelihood P(indicators|regime): How likely are current indicators given a regime
    - Posterior P(regime|indicators): Updated probability of regime given indicators
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize Bayesian Regime Detector
        
        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}
        
        # Initialize traditional regime detector for indicator calculation
        self.regime_detector = RegimeDetector(self.config)
        
        # Prior probabilities (will be updated based on observed frequencies)
        # Start with uniform prior
        self.prior = RegimeProbabilities(
            trending=self.config.get('prior_trending', 0.33),
            ranging=self.config.get('prior_ranging', 0.33),
            volatile=self.config.get('prior_volatile', 0.34),
        )
        
        # Likelihood parameters for each regime
        # These define what indicator values are "typical" for each regime
        self.likelihood_params = {
            MarketRegime.TRENDING: {
                'adx_mean': 30.0,
                'adx_std': 5.0,
                'atr_ratio_mean': 0.025,
                'atr_ratio_std': 0.010,
                'volume_mean': 0.6,
                'volume_std': 0.2,
            },
            MarketRegime.RANGING: {
                'adx_mean': 15.0,
                'adx_std': 5.0,
                'atr_ratio_mean': 0.015,
                'atr_ratio_std': 0.005,
                'volume_mean': 0.4,
                'volume_std': 0.15,
            },
            MarketRegime.VOLATILE: {
                'adx_mean': 22.5,
                'adx_std': 5.0,
                'atr_ratio_mean': 0.04,
                'atr_ratio_std': 0.015,
                'volume_mean': 0.7,
                'volume_std': 0.25,
            },
        }
        
        # Track regime history for prior updates
        self.regime_history = deque(maxlen=self.config.get('history_size', 1000))
        
        # Current regime (for transition detection)
        self.current_regime: Optional[MarketRegime] = None
        self.current_probabilities: Optional[RegimeProbabilities] = None
        
        # Performance tracking for adaptive priors
        self.regime_performance = {
            MarketRegime.TRENDING: [],
            MarketRegime.RANGING: [],
            MarketRegime.VOLATILE: [],
        }
        
        # Transition detection parameters
        self.transition_threshold = self.config.get('transition_threshold', 0.20)  # 20% prob change
        
        logger.info("🎲 Bayesian Regime Detector initialized (God Mode)")
        logger.info(f"   Prior: Trending={self.prior.trending:.2f}, "
                   f"Ranging={self.prior.ranging:.2f}, "
                   f"Volatile={self.prior.volatile:.2f}")
        logger.info(f"   Transition threshold: {self.transition_threshold:.2%}")
    
    def _calculate_likelihood(
        self,
        regime: MarketRegime,
        adx: float,
        atr_ratio: float,
        volume_ratio: float,
    ) -> float:
        """
        Calculate P(indicators|regime) using Gaussian likelihood
        
        Args:
            regime: The regime to calculate likelihood for
            adx: ADX indicator value
            atr_ratio: ATR/price ratio
            volume_ratio: Volume relative to average
        
        Returns:
            Likelihood score (0-1, normalized)
        """
        params = self.likelihood_params[regime]
        
        # Calculate Gaussian probability for each indicator
        def gaussian_prob(x: float, mean: float, std: float) -> float:
            """Gaussian probability density (normalized)"""
            return np.exp(-0.5 * ((x - mean) / std) ** 2)
        
        # Calculate individual likelihoods
        adx_likelihood = gaussian_prob(adx, params['adx_mean'], params['adx_std'])
        atr_likelihood = gaussian_prob(atr_ratio, params['atr_ratio_mean'], params['atr_ratio_std'])
        volume_likelihood = gaussian_prob(volume_ratio, params['volume_mean'], params['volume_std'])
        
        # Combined likelihood (assuming independence)
        combined = adx_likelihood * atr_likelihood * volume_likelihood
        
        return combined
    
    def _calculate_posterior(
        self,
        likelihoods: Dict[MarketRegime, float],
    ) -> RegimeProbabilities:
        """
        Calculate posterior probabilities using Bayes' theorem
        
        P(regime|indicators) = P(indicators|regime) * P(regime) / P(indicators)
        
        Args:
            likelihoods: Likelihood for each regime
        
        Returns:
            Posterior probabilities
        """
        # Calculate unnormalized posteriors
        unnormalized = {
            MarketRegime.TRENDING: likelihoods[MarketRegime.TRENDING] * self.prior.trending,
            MarketRegime.RANGING: likelihoods[MarketRegime.RANGING] * self.prior.ranging,
            MarketRegime.VOLATILE: likelihoods[MarketRegime.VOLATILE] * self.prior.volatile,
        }
        
        # Evidence P(indicators) = sum of all unnormalized posteriors
        evidence = sum(unnormalized.values())
        
        # Avoid division by zero
        if evidence < 1e-10:
            # If all likelihoods are near zero, fall back to prior
            return self.prior
        
        # Normalize to get posterior probabilities
        posterior = RegimeProbabilities(
            trending=unnormalized[MarketRegime.TRENDING] / evidence,
            ranging=unnormalized[MarketRegime.RANGING] / evidence,
            volatile=unnormalized[MarketRegime.VOLATILE] / evidence,
        )
        
        return posterior
    
    def detect_regime(
        self,
        df: pd.DataFrame,
        indicators: Dict,
    ) -> BayesianRegimeResult:
        """
        Detect market regime using Bayesian inference
        
        Args:
            df: Price dataframe with OHLCV data
            indicators: Dictionary of technical indicators
        
        Returns:
            BayesianRegimeResult with probabilities and regime
        """
        # Extract indicators
        adx = indicators.get('adx', 20.0)
        atr = indicators.get('atr', 0.0)
        current_price = df['close'].iloc[-1] if len(df) > 0 else 1.0
        atr_ratio = atr / current_price if current_price > 0 else 0.02
        volume_ratio = indicators.get('volume_ratio', 0.5)
        
        # Calculate likelihoods for each regime
        likelihoods = {
            regime: self._calculate_likelihood(regime, adx, atr_ratio, volume_ratio)
            for regime in MarketRegime
        }
        
        # Calculate posterior probabilities
        posterior = self._calculate_posterior(likelihoods)
        
        # Determine most likely regime and confidence
        regime = posterior.most_likely_regime()
        confidence = posterior.confidence()
        
        # Detect regime transitions
        transition_detected = False
        previous_regime = self.current_regime
        
        if self.current_probabilities is not None:
            # Check if probabilities have shifted significantly
            prob_change = abs(
                getattr(posterior, regime.value) - 
                getattr(self.current_probabilities, regime.value)
            )
            if prob_change > self.transition_threshold:
                transition_detected = True
                logger.info(
                    f"🔄 Regime transition detected: {previous_regime} -> {regime} "
                    f"(Δp={prob_change:.2%}, confidence={confidence:.2%})"
                )
        
        # Update current state
        self.current_regime = regime
        self.current_probabilities = posterior
        
        # Add to history
        self.regime_history.append({
            'regime': regime,
            'probabilities': posterior,
            'timestamp': datetime.utcnow(),
        })
        
        # Create result
        result = BayesianRegimeResult(
            probabilities=posterior,
            prior=self.prior,
            likelihood=likelihoods,
            evidence=sum(
                likelihoods[r] * getattr(self.prior, r.value)
                for r in MarketRegime
            ),
            regime=regime,
            confidence=confidence,
            transition_detected=transition_detected,
            previous_regime=previous_regime,
        )
        
        logger.debug(
            f"Bayesian regime: {regime.value} "
            f"(P={confidence:.2%}, probs={posterior.to_dict()})"
        )
        
        return result
    
    def update_prior(self, performance_multiplier: float = None):
        """
        Update prior probabilities based on observed regime frequencies
        
        Args:
            performance_multiplier: Optional performance-based adjustment
        """
        if len(self.regime_history) < 50:
            # Not enough data to update prior
            return
        
        # Count regime frequencies
        regime_counts = {
            MarketRegime.TRENDING: 0,
            MarketRegime.RANGING: 0,
            MarketRegime.VOLATILE: 0,
        }
        
        for entry in self.regime_history:
            regime_counts[entry['regime']] += 1
        
        # Calculate empirical frequencies
        total = sum(regime_counts.values())
        empirical_prior = RegimeProbabilities(
            trending=regime_counts[MarketRegime.TRENDING] / total,
            ranging=regime_counts[MarketRegime.RANGING] / total,
            volatile=regime_counts[MarketRegime.VOLATILE] / total,
        )
        
        # Smooth update: blend old prior with empirical (80% old, 20% new)
        alpha = self.config.get('prior_update_rate', 0.20)
        
        self.prior = RegimeProbabilities(
            trending=(1 - alpha) * self.prior.trending + alpha * empirical_prior.trending,
            ranging=(1 - alpha) * self.prior.ranging + alpha * empirical_prior.ranging,
            volatile=(1 - alpha) * self.prior.volatile + alpha * empirical_prior.volatile,
        )
        
        logger.info(
            f"📊 Prior updated based on {total} observations: "
            f"Trending={self.prior.trending:.2%}, "
            f"Ranging={self.prior.ranging:.2%}, "
            f"Volatile={self.prior.volatile:.2%}"
        )
    
    def get_regime_weighted_params(self, param_sets: Dict[MarketRegime, Dict]) -> Dict:
        """
        Get strategy parameters weighted by regime probabilities
        
        Args:
            param_sets: Dictionary mapping regimes to parameter sets
        
        Returns:
            Weighted combination of parameters
        """
        if self.current_probabilities is None:
            # No regime detected yet, use uniform weights
            probs = self.prior
        else:
            probs = self.current_probabilities
        
        # Weight each parameter by regime probability
        weighted_params = {}
        
        # Get all parameter keys from any regime
        all_keys = set()
        for params in param_sets.values():
            all_keys.update(params.keys())
        
        # Calculate weighted average for each parameter
        for key in all_keys:
            weighted_value = 0.0
            for regime, prob in [
                (MarketRegime.TRENDING, probs.trending),
                (MarketRegime.RANGING, probs.ranging),
                (MarketRegime.VOLATILE, probs.volatile),
            ]:
                if key in param_sets.get(regime, {}):
                    weighted_value += param_sets[regime][key] * prob
            
            weighted_params[key] = weighted_value
        
        return weighted_params
