"""
NIJA Live Reinforcement Learning Feedback Loop
===============================================

Real-time reinforcement learning system that learns from live trading:
- Observes market states and trading decisions
- Receives rewards based on trade outcomes
- Updates Q-values to improve future decisions
- Adapts strategy selection based on performance

This creates a continuous learning loop where the bot improves
over time based on real market feedback.

Key Components:
- State representation (market conditions)
- Action selection (which strategy to use)
- Reward calculation (trade performance)
- Q-learning update (policy improvement)

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

# Import RL components
try:
    from bot.meta_ai.reinforcement_learning import (
        RLStrategySelector,
        MarketState,
        Experience,
    )
except ImportError:
    try:
        from meta_ai.reinforcement_learning import (
            RLStrategySelector,
            MarketState,
            Experience,
        )
    except ImportError:
        raise ImportError("Reinforcement learning module not found")

logger = logging.getLogger("nija.live_rl")


@dataclass
class LiveTradeExperience:
    """Experience from a live trade"""
    entry_state: MarketState
    strategy_used: int  # Strategy index
    entry_time: datetime
    entry_price: float
    
    # Exit info (filled when trade closes)
    exit_state: Optional[MarketState] = None
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    
    # Performance
    profit_loss: float = 0.0
    return_pct: float = 0.0
    reward: float = 0.0
    
    # Status
    is_closed: bool = False


@dataclass
class RLFeedbackResult:
    """Result from RL feedback loop"""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # Current state
    current_state: Optional[MarketState] = None
    recommended_strategy: int = 0
    confidence: float = 0.0
    
    # Learning metrics
    total_experiences: int = 0
    avg_reward: float = 0.0
    exploration_rate: float = 0.1
    
    # Q-value statistics
    avg_q_value: float = 0.0
    max_q_value: float = 0.0
    
    # Summary
    summary: str = ""


class LiveRLFeedbackLoop:
    """
    Live reinforcement learning feedback system
    
    Continuously learns from live trading by:
    1. Observing market state when entering trades
    2. Recording which strategy was used
    3. Calculating rewards when trades close
    4. Updating Q-values to improve future decisions
    5. Selecting strategies that maximize expected reward
    """
    
    def __init__(self, num_strategies: int, config: Dict = None):
        """
        Initialize Live RL Feedback Loop
        
        Args:
            num_strategies: Number of available trading strategies
            config: Optional configuration dictionary
        """
        self.config = config or {}
        self.num_strategies = num_strategies
        
        # Initialize RL strategy selector
        rl_config = self.config.get('rl_config', {})
        self.rl_selector = RLStrategySelector(num_strategies, rl_config)
        
        # Experience tracking
        self.open_trades: Dict[str, LiveTradeExperience] = {}
        self.closed_trades: deque = deque(maxlen=1000)
        
        # Reward calculation parameters
        self.reward_scale = self.config.get('reward_scale', 1.0)
        self.penalty_per_day = self.config.get('penalty_per_day', 0.001)  # Small penalty for holding time
        self.min_reward = self.config.get('min_reward', -1.0)
        self.max_reward = self.config.get('max_reward', 1.0)
        
        # Learning parameters
        self.update_frequency = self.config.get('update_frequency', 1)  # Update every N trades
        self.batch_size = self.config.get('batch_size', 10)  # Batch learning
        
        # Performance tracking
        self.total_updates = 0
        self.cumulative_reward = 0.0
        
        # Strategy performance
        self.strategy_stats = {
            i: {'trades': 0, 'total_reward': 0.0, 'avg_reward': 0.0}
            for i in range(num_strategies)
        }
        
        logger.info("🤖 Live RL Feedback Loop initialized (God Mode)")
        logger.info(f"   Number of strategies: {num_strategies}")
        logger.info(f"   Reward scale: {self.reward_scale}")
        logger.info(f"   Update frequency: every {self.update_frequency} trades")
    
    def select_strategy(
        self,
        market_state: MarketState,
        force_exploration: bool = False,
    ) -> Tuple[int, float]:
        """
        Select best strategy for current market state
        
        Args:
            market_state: Current market state
            force_exploration: Force exploratory action
        
        Returns:
            (strategy_index, confidence)
        """
        # Get Q-values for this state
        q_values = self.rl_selector.get_q_values(market_state)
        
        # Select action (strategy)
        if force_exploration or np.random.random() < self.rl_selector.epsilon:
            # Explore: Random strategy
            strategy_idx = np.random.randint(0, self.num_strategies)
            confidence = 0.0
            logger.debug(f"🎲 Exploring: selected strategy {strategy_idx}")
        else:
            # Exploit: Best strategy
            strategy_idx = np.argmax(q_values)
            
            # Confidence = how much better best strategy is vs average
            max_q = q_values[strategy_idx]
            avg_q = np.mean(q_values)
            confidence = (max_q - avg_q) / (abs(avg_q) + 1e-6) if avg_q != 0 else 0.0
            confidence = np.clip(confidence, 0.0, 1.0)
            
            logger.debug(
                f"🎯 Exploiting: selected strategy {strategy_idx} "
                f"(Q={max_q:.4f}, confidence={confidence:.2%})"
            )
        
        return strategy_idx, confidence
    
    def record_trade_entry(
        self,
        trade_id: str,
        market_state: MarketState,
        strategy_used: int,
        entry_price: float,
    ):
        """
        Record trade entry for later reward calculation
        
        Args:
            trade_id: Unique trade identifier
            market_state: Market state at entry
            strategy_used: Strategy index used for this trade
            entry_price: Entry price
        """
        experience = LiveTradeExperience(
            entry_state=market_state,
            strategy_used=strategy_used,
            entry_time=datetime.utcnow(),
            entry_price=entry_price,
        )
        
        self.open_trades[trade_id] = experience
        
        logger.debug(
            f"📝 Recorded trade entry: {trade_id} "
            f"(strategy={strategy_used}, price={entry_price:.4f})"
        )
    
    def record_trade_exit(
        self,
        trade_id: str,
        market_state: MarketState,
        exit_price: float,
        profit_loss: float,
    ):
        """
        Record trade exit and calculate reward
        
        Args:
            trade_id: Unique trade identifier
            market_state: Market state at exit
            exit_price: Exit price
            profit_loss: Profit/loss in dollars
        """
        if trade_id not in self.open_trades:
            logger.warning(f"Trade {trade_id} not found in open trades")
            return
        
        experience = self.open_trades[trade_id]
        
        # Fill in exit information
        experience.exit_state = market_state
        experience.exit_time = datetime.utcnow()
        experience.exit_price = exit_price
        experience.profit_loss = profit_loss
        
        # Calculate return percentage
        if experience.entry_price > 0:
            experience.return_pct = (exit_price - experience.entry_price) / experience.entry_price
        else:
            experience.return_pct = 0.0
        
        # Calculate reward
        experience.reward = self._calculate_reward(experience)
        experience.is_closed = True
        
        # Update RL model
        self._update_rl_model(experience)
        
        # Move to closed trades
        self.closed_trades.append(experience)
        del self.open_trades[trade_id]
        
        # Update strategy stats
        strategy_idx = experience.strategy_used
        self.strategy_stats[strategy_idx]['trades'] += 1
        self.strategy_stats[strategy_idx]['total_reward'] += experience.reward
        self.strategy_stats[strategy_idx]['avg_reward'] = (
            self.strategy_stats[strategy_idx]['total_reward'] /
            self.strategy_stats[strategy_idx]['trades']
        )
        
        logger.info(
            f"✅ Trade closed: {trade_id} "
            f"(return={experience.return_pct:.2%}, reward={experience.reward:.4f}, "
            f"strategy={strategy_idx})"
        )
    
    def _calculate_reward(self, experience: LiveTradeExperience) -> float:
        """
        Calculate reward from trade experience
        
        Reward function:
        - Positive for profitable trades (scaled by return %)
        - Negative for losing trades
        - Small penalty for holding time (opportunity cost)
        
        Args:
            experience: Trade experience
        
        Returns:
            Reward value (typically -1 to +1)
        """
        # Base reward from return percentage
        reward = experience.return_pct * self.reward_scale
        
        # Time penalty (small penalty per day held)
        if experience.exit_time and experience.entry_time:
            holding_days = (experience.exit_time - experience.entry_time).total_seconds() / 86400
            time_penalty = holding_days * self.penalty_per_day
            reward -= time_penalty
        
        # Clip reward to bounds
        reward = np.clip(reward, self.min_reward, self.max_reward)
        
        return reward
    
    def _update_rl_model(self, experience: LiveTradeExperience):
        """
        Update RL model with trade experience
        
        Args:
            experience: Completed trade experience
        """
        # Create experience tuple
        rl_experience = Experience(
            state=experience.entry_state,
            action=experience.strategy_used,
            reward=experience.reward,
            next_state=experience.exit_state,
            done=True,
            timestamp=experience.exit_time,
        )
        
        # Add to RL selector's replay buffer
        self.rl_selector.add_experience(rl_experience)
        
        # Update Q-values
        self.rl_selector.update(rl_experience)
        
        # Track updates
        self.total_updates += 1
        self.cumulative_reward += experience.reward
        
        # Batch learning (update multiple times every N trades)
        if self.total_updates % self.update_frequency == 0:
            logger.info(
                f"🔄 RL model updated (update #{self.total_updates}, "
                f"avg reward={self.cumulative_reward / self.total_updates:.4f})"
            )
            
            # Decay exploration rate
            self.rl_selector.decay_epsilon()
    
    def get_status(self, market_state: Optional[MarketState] = None) -> RLFeedbackResult:
        """
        Get current status of RL feedback loop
        
        Args:
            market_state: Optional current market state
        
        Returns:
            RLFeedbackResult with current status
        """
        # Get recommended strategy if market state provided
        recommended_strategy = 0
        confidence = 0.0
        if market_state is not None:
            recommended_strategy, confidence = self.select_strategy(market_state)
        
        # Calculate average reward
        total_closed = len(self.closed_trades)
        avg_reward = (
            sum(exp.reward for exp in self.closed_trades) / total_closed
            if total_closed > 0 else 0.0
        )
        
        # Q-value statistics (sample from Q-table)
        q_values = []
        if market_state is not None:
            q_values = self.rl_selector.get_q_values(market_state)
        
        result = RLFeedbackResult(
            current_state=market_state,
            recommended_strategy=recommended_strategy,
            confidence=confidence,
            total_experiences=total_closed,
            avg_reward=avg_reward,
            exploration_rate=self.rl_selector.epsilon,
            avg_q_value=np.mean(q_values) if q_values else 0.0,
            max_q_value=np.max(q_values) if q_values else 0.0,
        )
        
        # Generate summary
        result.summary = self._generate_summary(result)
        
        return result
    
    def _generate_summary(self, result: RLFeedbackResult) -> str:
        """Generate human-readable summary"""
        lines = [
            "Live RL Feedback Loop Status:",
            f"  Total experiences: {result.total_experiences}",
            f"  Average reward: {result.avg_reward:.4f}",
            f"  Exploration rate: {result.exploration_rate:.2%}",
            f"  Current recommended strategy: {result.recommended_strategy}",
            f"  Confidence: {result.confidence:.2%}",
            "",
            "Strategy Performance:",
        ]
        
        for idx, stats in self.strategy_stats.items():
            if stats['trades'] > 0:
                lines.append(
                    f"  Strategy {idx}: "
                    f"{stats['trades']} trades, "
                    f"avg reward={stats['avg_reward']:.4f}"
                )
        
        return "\n".join(lines)
    
    def save_state(self, filepath: str):
        """Save RL state to file"""
        import pickle
        
        state = {
            'rl_selector': self.rl_selector,
            'closed_trades': list(self.closed_trades),
            'strategy_stats': self.strategy_stats,
            'total_updates': self.total_updates,
            'cumulative_reward': self.cumulative_reward,
        }
        
        with open(filepath, 'wb') as f:
            pickle.dump(state, f)
        
        logger.info(f"💾 Saved RL state to {filepath}")
    
    def load_state(self, filepath: str):
        """Load RL state from file"""
        import pickle
        
        try:
            with open(filepath, 'rb') as f:
                state = pickle.load(f)
            
            self.rl_selector = state['rl_selector']
            self.closed_trades = deque(state['closed_trades'], maxlen=1000)
            self.strategy_stats = state['strategy_stats']
            self.total_updates = state['total_updates']
            self.cumulative_reward = state['cumulative_reward']
            
            logger.info(f"📂 Loaded RL state from {filepath}")
            logger.info(f"   Restored {len(self.closed_trades)} experiences")
        except Exception as e:
            logger.error(f"Failed to load RL state: {e}")
