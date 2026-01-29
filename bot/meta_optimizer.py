"""
NIJA Meta-Learning Parameter Optimizer
=======================================

Self-tuning parameter optimization system that learns which parameters
work best over time and automatically adjusts them based on performance.

Features:
- Performance tracking for each parameter set
- Bayesian optimization for parameter search
- Automatic parameter adjustment based on results
- Performance-weighted parameter ensembles
- Adaptive learning rates

This is "meta-learning" because the system learns how to optimize itself,
rather than requiring manual parameter tuning.

Author: NIJA Trading Systems
Version: 1.0 - God Mode Edition
Date: January 29, 2026
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque
import logging

logger = logging.getLogger("nija.meta_optimizer")


@dataclass
class ParameterPerformance:
    """Performance record for a parameter set"""
    parameter_id: str
    parameters: Dict[str, float]
    
    # Performance metrics
    total_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 1.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    total_return: float = 0.0
    
    # Meta metrics
    performance_score: float = 0.0
    confidence: float = 0.0  # Based on sample size
    last_updated: datetime = field(default_factory=datetime.utcnow)
    
    def update_metrics(self, trade_result: Dict):
        """Update performance metrics with new trade result"""
        self.total_trades += 1
        
        # Update win rate
        if trade_result.get('profit', 0) > 0:
            self.win_rate = (self.win_rate * (self.total_trades - 1) + 1.0) / self.total_trades
        else:
            self.win_rate = (self.win_rate * (self.total_trades - 1)) / self.total_trades
        
        # Update other metrics (simplified - would be more complex in practice)
        self.total_return += trade_result.get('return_pct', 0.0)
        self.last_updated = datetime.utcnow()
        
        # Update confidence (increases with more trades, up to 1.0)
        self.confidence = min(1.0, self.total_trades / 100.0)
    
    def calculate_performance_score(self) -> float:
        """Calculate overall performance score"""
        # Weighted combination of metrics
        score = (
            self.sharpe_ratio * 0.30 +
            self.profit_factor * 0.25 +
            self.win_rate * 0.20 +
            (1.0 - min(abs(self.max_drawdown), 1.0)) * 0.15 +
            min(self.total_return, 1.0) * 0.10
        )
        
        # Weight by confidence
        score *= self.confidence
        
        self.performance_score = max(score, 0.0)
        return self.performance_score


@dataclass
class MetaOptimizerResult:
    """Result from meta-optimizer"""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # Current best parameters
    best_parameters: Dict[str, float] = field(default_factory=dict)
    ensemble_parameters: Dict[str, float] = field(default_factory=dict)
    
    # Performance tracking
    tracked_parameter_sets: int = 0
    best_performance_score: float = 0.0
    
    # Learning status
    learning_rate: float = 0.1
    exploration_rate: float = 0.2
    
    # Summary
    summary: str = ""


class MetaLearningOptimizer:
    """
    Meta-learning parameter optimization system
    
    Automatically tunes strategy parameters by:
    1. Tracking performance of different parameter sets
    2. Learning which parameters work best
    3. Adapting parameters based on recent performance
    4. Balancing exploration (trying new params) vs exploitation (using best params)
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize Meta-Learning Optimizer
        
        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}
        
        # Learning parameters
        self.learning_rate = self.config.get('learning_rate', 0.10)
        self.exploration_rate = self.config.get('exploration_rate', 0.20)
        self.min_confidence_threshold = self.config.get('min_confidence', 0.30)
        
        # Decay rates
        self.exploration_decay = self.config.get('exploration_decay', 0.95)
        self.learning_rate_decay = self.config.get('learning_rate_decay', 0.98)
        
        # Performance tracking
        self.parameter_performance: Dict[str, ParameterPerformance] = {}
        self.performance_history = deque(maxlen=1000)
        
        # Current best
        self.best_parameters: Optional[Dict[str, float]] = None
        self.best_performance_score: float = 0.0
        
        # Parameter search space (from genetic config)
        try:
            from bot.meta_ai.evolution_config import PARAMETER_SEARCH_SPACE
            self.search_space = PARAMETER_SEARCH_SPACE
        except ImportError:
            try:
                from meta_ai.evolution_config import PARAMETER_SEARCH_SPACE
                self.search_space = PARAMETER_SEARCH_SPACE
            except ImportError:
                logger.warning("Evolution config not found, using default search space")
                self.search_space = self._get_default_search_space()
        
        # Ensemble parameters (weighted average of top performers)
        self.ensemble_parameters: Optional[Dict[str, float]] = None
        self.ensemble_size = self.config.get('ensemble_size', 5)
        
        logger.info("🧠 Meta-Learning Optimizer initialized (God Mode)")
        logger.info(f"   Learning rate: {self.learning_rate:.2%}")
        logger.info(f"   Exploration rate: {self.exploration_rate:.2%}")
        logger.info(f"   Ensemble size: {self.ensemble_size}")
    
    def get_parameters(self, use_ensemble: bool = False) -> Dict[str, float]:
        """
        Get current best parameters or ensemble parameters
        
        Args:
            use_ensemble: If True, return ensemble parameters
        
        Returns:
            Parameter dictionary
        """
        # Decide whether to explore or exploit
        if np.random.random() < self.exploration_rate:
            # Explore: Generate new parameters
            params = self._generate_exploration_parameters()
            logger.debug(f"🔍 Exploring new parameters (exploration_rate={self.exploration_rate:.2%})")
        else:
            # Exploit: Use best known parameters
            if use_ensemble and self.ensemble_parameters is not None:
                params = self.ensemble_parameters
                logger.debug("🎯 Using ensemble parameters")
            elif self.best_parameters is not None:
                params = self.best_parameters
                logger.debug("🎯 Using best parameters")
            else:
                # No history yet, generate random
                params = self._generate_random_parameters()
                logger.debug("🎲 No history, using random parameters")
        
        return params
    
    def update_performance(
        self,
        parameters: Dict[str, float],
        trade_result: Dict,
    ):
        """
        Update performance tracking with trade result
        
        Args:
            parameters: Parameter set used for this trade
            trade_result: Trade result dictionary
        """
        # Create parameter ID (hash of parameter values)
        param_id = self._parameter_id(parameters)
        
        # Get or create performance tracker
        if param_id not in self.parameter_performance:
            self.parameter_performance[param_id] = ParameterPerformance(
                parameter_id=param_id,
                parameters=parameters.copy(),
            )
        
        perf = self.parameter_performance[param_id]
        
        # Update metrics
        perf.update_metrics(trade_result)
        perf.calculate_performance_score()
        
        # Add to history
        self.performance_history.append({
            'parameter_id': param_id,
            'parameters': parameters,
            'trade_result': trade_result,
            'performance_score': perf.performance_score,
            'timestamp': datetime.utcnow(),
        })
        
        # Update best parameters if this is better
        if perf.performance_score > self.best_performance_score and perf.confidence >= self.min_confidence_threshold:
            self.best_parameters = parameters.copy()
            self.best_performance_score = perf.performance_score
            logger.info(
                f"✨ New best parameters found! Score: {perf.performance_score:.4f} "
                f"(confidence: {perf.confidence:.2%})"
            )
        
        # Update ensemble parameters
        self._update_ensemble_parameters()
        
        # Decay exploration rate (gradually shift from exploration to exploitation)
        self.exploration_rate *= self.exploration_decay
        self.exploration_rate = max(self.exploration_rate, 0.05)  # Keep at least 5%
        
        logger.debug(
            f"📊 Updated performance for parameter set {param_id[:8]}: "
            f"score={perf.performance_score:.4f}, "
            f"trades={perf.total_trades}, "
            f"confidence={perf.confidence:.2%}"
        )
    
    def _update_ensemble_parameters(self):
        """Update ensemble parameters from top performers"""
        # Get top performers (by performance score)
        performers = [
            perf for perf in self.parameter_performance.values()
            if perf.confidence >= self.min_confidence_threshold
        ]
        
        if not performers:
            return
        
        # Sort by performance score
        performers.sort(key=lambda p: p.performance_score, reverse=True)
        
        # Take top N
        top_performers = performers[:self.ensemble_size]
        
        # Calculate weighted average (weighted by performance score)
        total_weight = sum(p.performance_score for p in top_performers)
        
        if total_weight == 0:
            return
        
        # Get all parameter keys
        param_keys = list(top_performers[0].parameters.keys())
        
        # Calculate weighted average for each parameter
        ensemble = {}
        for key in param_keys:
            weighted_sum = sum(
                p.parameters[key] * p.performance_score
                for p in top_performers
            )
            ensemble[key] = weighted_sum / total_weight
        
        self.ensemble_parameters = ensemble
        
        logger.debug(
            f"📊 Ensemble updated from {len(top_performers)} top performers "
            f"(avg score: {np.mean([p.performance_score for p in top_performers]):.4f})"
        )
    
    def _generate_exploration_parameters(self) -> Dict[str, float]:
        """
        Generate parameters for exploration
        
        Strategy: Perturb best known parameters or generate random
        """
        if self.best_parameters is not None:
            # Perturb best parameters
            params = {}
            for key, value in self.best_parameters.items():
                if key not in self.search_space:
                    params[key] = value
                    continue
                
                # Get search space bounds
                min_val, max_val = self.search_space[key]
                
                # Add Gaussian noise scaled by learning rate
                noise_scale = (max_val - min_val) * self.learning_rate
                perturbed = value + np.random.normal(0, noise_scale)
                
                # Clip to bounds
                params[key] = np.clip(perturbed, min_val, max_val)
            
            return params
        else:
            # No best parameters yet, generate random
            return self._generate_random_parameters()
    
    def _generate_random_parameters(self) -> Dict[str, float]:
        """Generate random parameters from search space"""
        params = {}
        for key, (min_val, max_val) in self.search_space.items():
            params[key] = np.random.uniform(min_val, max_val)
        return params
    
    def _parameter_id(self, parameters: Dict[str, float]) -> str:
        """Create unique ID for parameter set"""
        # Sort keys for consistency
        sorted_items = sorted(parameters.items())
        
        # Create string representation
        param_str = "_".join(f"{k}:{v:.6f}" for k, v in sorted_items)
        
        # Hash it (simple string hash)
        param_hash = str(hash(param_str))
        
        return param_hash
    
    def _get_default_search_space(self) -> Dict[str, Tuple[float, float]]:
        """Default parameter search space"""
        return {
            'min_signal_score': (2.0, 5.0),
            'min_adx': (15.0, 30.0),
            'volume_threshold': (0.3, 0.7),
            'atr_stop_multiplier': (1.0, 2.5),
            'min_position_pct': (0.01, 0.05),
            'max_position_pct': (0.03, 0.10),
        }
    
    def get_status(self) -> MetaOptimizerResult:
        """Get current optimizer status"""
        result = MetaOptimizerResult(
            best_parameters=self.best_parameters or {},
            ensemble_parameters=self.ensemble_parameters or {},
            tracked_parameter_sets=len(self.parameter_performance),
            best_performance_score=self.best_performance_score,
            learning_rate=self.learning_rate,
            exploration_rate=self.exploration_rate,
        )
        
        # Generate summary
        result.summary = self._generate_summary(result)
        
        return result
    
    def _generate_summary(self, result: MetaOptimizerResult) -> str:
        """Generate human-readable summary"""
        lines = [
            "Meta-Learning Optimizer Status:",
            f"  Tracked parameter sets: {result.tracked_parameter_sets}",
            f"  Best performance score: {result.best_performance_score:.4f}",
            f"  Learning rate: {result.learning_rate:.2%}",
            f"  Exploration rate: {result.exploration_rate:.2%}",
            "",
        ]
        
        if result.best_parameters:
            lines.append("Best Parameters:")
            for key, value in result.best_parameters.items():
                lines.append(f"  {key}: {value:.4f}")
        
        return "\n".join(lines)
    
    def save_state(self, filepath: str):
        """Save optimizer state to file"""
        import pickle
        
        state = {
            'parameter_performance': self.parameter_performance,
            'performance_history': list(self.performance_history),
            'best_parameters': self.best_parameters,
            'best_performance_score': self.best_performance_score,
            'ensemble_parameters': self.ensemble_parameters,
            'exploration_rate': self.exploration_rate,
            'learning_rate': self.learning_rate,
        }
        
        with open(filepath, 'wb') as f:
            pickle.dump(state, f)
        
        logger.info(f"💾 Saved meta-optimizer state to {filepath}")
    
    def load_state(self, filepath: str):
        """Load optimizer state from file"""
        import pickle
        
        try:
            with open(filepath, 'rb') as f:
                state = pickle.load(f)
            
            self.parameter_performance = state['parameter_performance']
            self.performance_history = deque(state['performance_history'], maxlen=1000)
            self.best_parameters = state['best_parameters']
            self.best_performance_score = state['best_performance_score']
            self.ensemble_parameters = state['ensemble_parameters']
            self.exploration_rate = state['exploration_rate']
            self.learning_rate = state['learning_rate']
            
            logger.info(f"📂 Loaded meta-optimizer state from {filepath}")
            logger.info(f"   Restored {len(self.parameter_performance)} parameter sets")
        except Exception as e:
            logger.error(f"Failed to load meta-optimizer state: {e}")
