"""
NIJA Signal Ensemble System
============================

Multi-strategy voting and signal aggregation system for high-confidence trade entry.

Features:
- Multi-strategy signal generation
- Weighted voting mechanism
- Confidence-based execution filtering
- Probability estimation per signal
- Signal correlation analysis

Instead of relying on a single strategy, this ensemble system:
1. Collects signals from multiple strategies
2. Weights each signal by historical performance
3. Aggregates into a single confidence score
4. Only executes when confidence threshold is met

This dramatically improves win rate by filtering out low-quality setups.

Author: NIJA Trading Systems
Version: 1.0 (Path 1)
Date: January 30, 2026
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timedelta
import logging
from collections import defaultdict, deque

logger = logging.getLogger("nija.ensemble")


class SignalType(Enum):
    """Trade signal types"""
    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"


class StrategySource(Enum):
    """Strategy sources that generate signals"""
    APEX_RSI = "apex_rsi"  # Dual RSI strategy
    TREND_FOLLOWING = "trend_following"  # Momentum/trend
    MEAN_REVERSION = "mean_reversion"  # Counter-trend
    BREAKOUT = "breakout"  # Volatility expansion
    MOMENTUM = "momentum"  # Pure momentum
    SCALPING = "scalping"  # Quick in-and-out


@dataclass
class TradeSignal:
    """Individual trade signal from a strategy"""
    source: StrategySource
    signal_type: SignalType
    strength: float  # 0.0 to 1.0
    timestamp: datetime
    symbol: str
    price: float
    metadata: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'source': self.source.value,
            'signal_type': self.signal_type.value,
            'strength': self.strength,
            'timestamp': self.timestamp.isoformat(),
            'symbol': self.symbol,
            'price': self.price,
            'metadata': self.metadata
        }


@dataclass
class EnsembleSignal:
    """Aggregated ensemble signal"""
    signal_type: SignalType
    confidence: float  # 0.0 to 1.0
    probability: float  # Estimated win probability 0.0 to 1.0
    vote_count: int
    contributing_signals: List[TradeSignal]
    timestamp: datetime
    symbol: str
    price: float
    
    def should_execute(self, min_confidence: float = 0.65, min_probability: float = 0.60) -> bool:
        """Check if signal meets execution thresholds"""
        return self.confidence >= min_confidence and self.probability >= min_probability
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'signal_type': self.signal_type.value,
            'confidence': self.confidence,
            'probability': self.probability,
            'vote_count': self.vote_count,
            'contributing_signals': [s.to_dict() for s in self.contributing_signals],
            'timestamp': self.timestamp.isoformat(),
            'symbol': self.symbol,
            'price': self.price
        }


@dataclass
class StrategyPerformance:
    """Track performance of a strategy for weighting"""
    source: StrategySource
    total_signals: int = 0
    winning_signals: int = 0
    losing_signals: int = 0
    total_pnl: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    win_rate: float = 0.0
    sharpe_ratio: float = 0.0
    weight: float = 1.0  # Current weight in ensemble
    
    def update_performance(self):
        """Recalculate performance metrics"""
        if self.total_signals > 0:
            self.win_rate = self.winning_signals / self.total_signals
        else:
            self.win_rate = 0.0
        
        # Calculate weight based on win rate and sharpe
        # Higher win rate and sharpe = higher weight
        base_weight = self.win_rate
        sharpe_bonus = min(self.sharpe_ratio / 2.0, 0.5) if self.sharpe_ratio > 0 else 0
        self.weight = max(0.1, min(2.0, base_weight + sharpe_bonus))  # Constrain 0.1-2.0
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'source': self.source.value,
            'total_signals': self.total_signals,
            'winning_signals': self.winning_signals,
            'losing_signals': self.losing_signals,
            'total_pnl': self.total_pnl,
            'avg_win': self.avg_win,
            'avg_loss': self.avg_loss,
            'win_rate': self.win_rate,
            'sharpe_ratio': self.sharpe_ratio,
            'weight': self.weight
        }


class SignalEnsembleSystem:
    """
    Multi-strategy signal ensemble with weighted voting
    
    How it works:
    1. Each strategy generates signals with strength 0.0-1.0
    2. Signals are weighted by strategy historical performance
    3. Weighted votes are aggregated into confidence score
    4. Win probability is estimated based on similar historical signals
    5. Only signals meeting confidence AND probability thresholds execute
    
    Example:
        Strategy A (70% win rate, weight 1.4): LONG signal, strength 0.8
        Strategy B (55% win rate, weight 0.9): LONG signal, strength 0.6
        Strategy C (65% win rate, weight 1.2): SHORT signal, strength 0.7
        
        Weighted LONG votes: (1.4 * 0.8) + (0.9 * 0.6) = 1.66
        Weighted SHORT votes: (1.2 * 0.7) = 0.84
        
        Result: LONG signal with confidence 1.66/(1.66+0.84) = 0.66 (66%)
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize signal ensemble system
        
        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}
        
        # Execution thresholds
        self.min_confidence = self.config.get('min_confidence', 0.65)  # 65%
        self.min_probability = self.config.get('min_probability', 0.60)  # 60%
        self.min_vote_count = self.config.get('min_vote_count', 2)  # At least 2 strategies agree
        
        # Performance tracking
        self.strategy_performance: Dict[StrategySource, StrategyPerformance] = {}
        for source in StrategySource:
            self.strategy_performance[source] = StrategyPerformance(source=source)
        
        # Signal history for probability estimation
        self.signal_history: deque = deque(maxlen=500)  # Last 500 ensemble signals
        
        # Active signals buffer
        self.active_signals: Dict[str, List[TradeSignal]] = defaultdict(list)
        self.signal_timeout_seconds = self.config.get('signal_timeout_seconds', 300)  # 5 minutes
        
        logger.info("SignalEnsembleSystem initialized")
    
    def add_signal(self, signal: TradeSignal):
        """
        Add a signal from a strategy
        
        Args:
            signal: TradeSignal instance
        """
        # Clean expired signals
        self._clean_expired_signals()
        
        # Add to active signals
        self.active_signals[signal.symbol].append(signal)
        
        logger.debug(
            f"Signal added: {signal.source.value} → {signal.signal_type.value} "
            f"on {signal.symbol} (strength: {signal.strength:.2f})"
        )
    
    def generate_ensemble_signal(
        self,
        symbol: str,
        current_price: float,
        current_time: datetime = None
    ) -> Optional[EnsembleSignal]:
        """
        Generate ensemble signal by aggregating active signals
        
        Args:
            symbol: Trading symbol
            current_price: Current market price
            current_time: Optional timestamp
        
        Returns:
            EnsembleSignal if signals exist, None otherwise
        """
        if current_time is None:
            current_time = datetime.now()
        
        # Get active signals for symbol
        signals = self.active_signals.get(symbol, [])
        
        if len(signals) == 0:
            return None
        
        # Clean expired signals
        self._clean_expired_signals()
        signals = self.active_signals.get(symbol, [])
        
        if len(signals) == 0:
            return None
        
        # Aggregate weighted votes
        long_vote = 0.0
        short_vote = 0.0
        neutral_vote = 0.0
        
        for signal in signals:
            perf = self.strategy_performance[signal.source]
            weight = perf.weight
            weighted_strength = signal.strength * weight
            
            if signal.signal_type == SignalType.LONG:
                long_vote += weighted_strength
            elif signal.signal_type == SignalType.SHORT:
                short_vote += weighted_strength
            else:
                neutral_vote += weighted_strength
        
        # Determine majority signal
        total_votes = long_vote + short_vote + neutral_vote
        
        if total_votes == 0:
            return None
        
        if long_vote > short_vote and long_vote > neutral_vote:
            signal_type = SignalType.LONG
            confidence = long_vote / total_votes
        elif short_vote > long_vote and short_vote > neutral_vote:
            signal_type = SignalType.SHORT
            confidence = short_vote / total_votes
        else:
            signal_type = SignalType.NEUTRAL
            confidence = neutral_vote / total_votes
        
        # Filter out neutral signals
        if signal_type == SignalType.NEUTRAL:
            return None
        
        # Count contributing signals (only those voting for majority)
        contributing_signals = [
            s for s in signals
            if s.signal_type == signal_type
        ]
        
        vote_count = len(contributing_signals)
        
        # Estimate win probability based on historical similar signals
        probability = self._estimate_win_probability(
            signal_type=signal_type,
            confidence=confidence,
            vote_count=vote_count,
            contributing_sources=[s.source for s in contributing_signals]
        )
        
        # Create ensemble signal
        ensemble = EnsembleSignal(
            signal_type=signal_type,
            confidence=confidence,
            probability=probability,
            vote_count=vote_count,
            contributing_signals=contributing_signals,
            timestamp=current_time,
            symbol=symbol,
            price=current_price
        )
        
        logger.info(
            f"Ensemble signal: {signal_type.value} {symbol} @ ${current_price:.2f} | "
            f"Confidence: {confidence:.2%} | Probability: {probability:.2%} | "
            f"Votes: {vote_count} | Execute: {ensemble.should_execute(self.min_confidence, self.min_probability)}"
        )
        
        # Store in history
        self.signal_history.append(ensemble)
        
        return ensemble
    
    def should_execute(self, ensemble: EnsembleSignal) -> bool:
        """
        Determine if ensemble signal should be executed
        
        Args:
            ensemble: EnsembleSignal instance
        
        Returns:
            True if signal meets all thresholds
        """
        # Check confidence threshold
        if ensemble.confidence < self.min_confidence:
            logger.debug(f"Signal rejected: confidence {ensemble.confidence:.2%} < {self.min_confidence:.2%}")
            return False
        
        # Check probability threshold
        if ensemble.probability < self.min_probability:
            logger.debug(f"Signal rejected: probability {ensemble.probability:.2%} < {self.min_probability:.2%}")
            return False
        
        # Check minimum vote count
        if ensemble.vote_count < self.min_vote_count:
            logger.debug(f"Signal rejected: vote count {ensemble.vote_count} < {self.min_vote_count}")
            return False
        
        logger.info(
            f"Signal ACCEPTED for execution: {ensemble.signal_type.value} | "
            f"Confidence: {ensemble.confidence:.2%} | Probability: {ensemble.probability:.2%}"
        )
        return True
    
    def _estimate_win_probability(
        self,
        signal_type: SignalType,
        confidence: float,
        vote_count: int,
        contributing_sources: List[StrategySource]
    ) -> float:
        """
        Estimate win probability based on historical similar signals
        
        Args:
            signal_type: Type of signal
            confidence: Signal confidence
            vote_count: Number of votes
            contributing_sources: List of strategy sources
        
        Returns:
            Estimated win probability 0.0-1.0
        """
        # If no history, use conservative estimate
        if len(self.signal_history) == 0:
            return 0.60  # Default 60%
        
        # Find similar signals in history
        similar_signals = []
        
        for hist_signal in self.signal_history:
            # Same signal type
            if hist_signal.signal_type != signal_type:
                continue
            
            # Similar confidence (within 10%)
            if abs(hist_signal.confidence - confidence) > 0.10:
                continue
            
            # Similar vote count (within 2)
            if abs(hist_signal.vote_count - vote_count) > 2:
                continue
            
            similar_signals.append(hist_signal)
        
        # If not enough similar signals, use weighted average of strategy win rates
        if len(similar_signals) < 10:
            total_weight = 0.0
            weighted_win_rate = 0.0
            
            for source in contributing_sources:
                perf = self.strategy_performance[source]
                total_weight += perf.weight
                weighted_win_rate += perf.weight * perf.win_rate
            
            if total_weight > 0:
                estimated_prob = weighted_win_rate / total_weight
            else:
                estimated_prob = 0.60
            
            # Boost probability for high confidence
            if confidence >= 0.80:
                estimated_prob = min(0.95, estimated_prob + 0.10)
            elif confidence >= 0.70:
                estimated_prob = min(0.90, estimated_prob + 0.05)
            
            return max(0.40, min(0.95, estimated_prob))
        
        # Calculate actual win rate from similar signals
        # Note: This requires outcome tracking (not implemented here)
        # For now, return weighted strategy win rate
        total_weight = 0.0
        weighted_win_rate = 0.0
        
        for source in contributing_sources:
            perf = self.strategy_performance[source]
            total_weight += perf.weight
            weighted_win_rate += perf.weight * perf.win_rate
        
        if total_weight > 0:
            estimated_prob = weighted_win_rate / total_weight
        else:
            estimated_prob = 0.60
        
        # Boost for high confidence and vote count
        if confidence >= 0.80 and vote_count >= 4:
            estimated_prob = min(0.95, estimated_prob + 0.15)
        elif confidence >= 0.75 and vote_count >= 3:
            estimated_prob = min(0.90, estimated_prob + 0.10)
        elif confidence >= 0.70:
            estimated_prob = min(0.85, estimated_prob + 0.05)
        
        return max(0.40, min(0.95, estimated_prob))
    
    def _clean_expired_signals(self):
        """Remove signals that have expired"""
        current_time = datetime.now()
        
        for symbol in list(self.active_signals.keys()):
            signals = self.active_signals[symbol]
            
            # Filter out expired signals
            valid_signals = [
                s for s in signals
                if (current_time - s.timestamp).total_seconds() < self.signal_timeout_seconds
            ]
            
            if len(valid_signals) > 0:
                self.active_signals[symbol] = valid_signals
            else:
                del self.active_signals[symbol]
    
    def update_strategy_performance(
        self,
        source: StrategySource,
        won: bool,
        pnl: float
    ):
        """
        Update strategy performance after trade outcome
        
        Args:
            source: Strategy source
            won: Whether trade was profitable
            pnl: Profit/loss amount
        """
        perf = self.strategy_performance[source]
        
        perf.total_signals += 1
        perf.total_pnl += pnl
        
        if won:
            perf.winning_signals += 1
            # Update average win
            old_avg = perf.avg_win
            n = perf.winning_signals
            perf.avg_win = ((old_avg * (n - 1)) + pnl) / n if n > 0 else pnl
        else:
            perf.losing_signals += 1
            # Update average loss
            old_avg = perf.avg_loss
            n = perf.losing_signals
            perf.avg_loss = ((old_avg * (n - 1)) + abs(pnl)) / n if n > 0 else abs(pnl)
        
        # Recalculate performance metrics
        perf.update_performance()
        
        logger.info(
            f"Strategy {source.value} performance updated: "
            f"Win rate: {perf.win_rate:.2%} | Weight: {perf.weight:.2f} | "
            f"Total signals: {perf.total_signals}"
        )
    
    def get_performance_summary(self) -> Dict:
        """Get performance summary for all strategies"""
        return {
            source.value: perf.to_dict()
            for source, perf in self.strategy_performance.items()
        }
    
    def clear_signals(self, symbol: str = None):
        """
        Clear active signals
        
        Args:
            symbol: Optional symbol to clear (clears all if None)
        """
        if symbol:
            if symbol in self.active_signals:
                del self.active_signals[symbol]
        else:
            self.active_signals.clear()


# Global instance
signal_ensemble_system = SignalEnsembleSystem()
