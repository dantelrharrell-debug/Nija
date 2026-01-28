"""
Reinforcement Learning Strategy Selector
=========================================

Uses Q-learning to select optimal strategies based on market conditions:
- State: Market regime, volatility, trend strength
- Action: Select which strategy to use
- Reward: Strategy performance (profit factor, Sharpe, etc.)
- Learning: Update Q-values based on outcomes

Author: NIJA Trading Systems
"""

import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from collections import deque
from datetime import datetime
import logging
import json

from .evolution_config import RL_CONFIG

logger = logging.getLogger("nija.meta_ai.rl")


@dataclass
class MarketState:
    """
    Represents current market state for RL decision-making
    """
    volatility: float  # 0-1 (low to high)
    trend_strength: float  # 0-1 (ranging to strong trend)
    volume_regime: float  # 0-1 (low to high volume)
    momentum: float  # -1 to 1 (bearish to bullish)
    time_of_day: int  # 0-23 hour
    day_of_week: int  # 0-6 (Monday to Sunday)
    
    def to_tuple(self) -> Tuple:
        """Convert to hashable tuple for Q-table"""
        # Discretize continuous values
        vol_bucket = int(self.volatility * 5)  # 0-5
        trend_bucket = int(self.trend_strength * 5)  # 0-5
        volume_bucket = int(self.volume_regime * 3)  # 0-3
        momentum_bucket = int((self.momentum + 1) * 2.5)  # 0-5 (mapped from -1 to 1)
        
        return (
            vol_bucket,
            trend_bucket,
            volume_bucket,
            momentum_bucket,
            self.time_of_day,
            self.day_of_week,
        )


@dataclass
class Experience:
    """
    Experience tuple for replay buffer
    """
    state: MarketState
    action: int  # Strategy index
    reward: float
    next_state: MarketState
    done: bool
    timestamp: datetime


class RLStrategySelector:
    """
    Reinforcement Learning Strategy Selector
    
    Uses Q-learning to learn which strategy performs best
    in different market conditions.
    """
    
    def __init__(self, num_strategies: int, config: Dict = None):
        """
        Initialize RL strategy selector
        
        Args:
            num_strategies: Number of available strategies
            config: Configuration dictionary (uses RL_CONFIG if None)
        """
        self.config = config or RL_CONFIG
        self.num_strategies = num_strategies
        
        # Q-table: state -> action -> Q-value
        self.q_table: Dict[Tuple, np.ndarray] = {}
        
        # Experience replay buffer
        self.replay_buffer = deque(maxlen=self.config['replay_buffer_size'])
        
        # Learning parameters
        self.learning_rate = self.config['learning_rate']
        self.discount_factor = self.config['discount_factor']
        self.epsilon = self.config['exploration_rate']
        self.epsilon_decay = self.config['exploration_decay']
        self.min_epsilon = self.config['min_exploration']
        
        # Training stats
        self.episodes = 0
        self.total_steps = 0
        self.cumulative_reward = 0.0
        self.episode_rewards: List[float] = []
        
        logger.info(
            f"🤖 RL Strategy Selector initialized: "
            f"{num_strategies} strategies, "
            f"lr={self.learning_rate}, "
            f"gamma={self.discount_factor}"
        )
    
    def get_q_values(self, state: MarketState) -> np.ndarray:
        """
        Get Q-values for a state
        
        Args:
            state: Current market state
            
        Returns:
            Array of Q-values for each action (strategy)
        """
        state_key = state.to_tuple()
        
        if state_key not in self.q_table:
            # Initialize with small random values
            self.q_table[state_key] = np.random.randn(self.num_strategies) * 0.01
        
        return self.q_table[state_key]
    
    def select_strategy(
        self,
        state: MarketState,
        explore: bool = True
    ) -> int:
        """
        Select strategy using epsilon-greedy policy
        
        Args:
            state: Current market state
            explore: Whether to use exploration (False for production)
            
        Returns:
            Strategy index to use
        """
        if explore and np.random.random() < self.epsilon:
            # Explore: random strategy
            action = np.random.randint(0, self.num_strategies)
            logger.debug(f"🔍 Exploring: selected strategy {action}")
        else:
            # Exploit: best known strategy
            q_values = self.get_q_values(state)
            action = int(np.argmax(q_values))
            logger.debug(
                f"🎯 Exploiting: selected strategy {action} "
                f"(Q={q_values[action]:.4f})"
            )
        
        return action
    
    def update_q_value(
        self,
        state: MarketState,
        action: int,
        reward: float,
        next_state: MarketState,
        done: bool = False
    ):
        """
        Update Q-value using Q-learning update rule
        
        Q(s,a) = Q(s,a) + α * (r + γ * max(Q(s',a')) - Q(s,a))
        
        Args:
            state: Current state
            action: Action taken
            reward: Reward received
            next_state: Next state
            done: Whether episode is done
        """
        current_q = self.get_q_values(state)[action]
        
        if done:
            # Terminal state
            target_q = reward
        else:
            # Bootstrap from next state
            next_q_values = self.get_q_values(next_state)
            max_next_q = np.max(next_q_values)
            target_q = reward + self.discount_factor * max_next_q
        
        # Q-learning update
        new_q = current_q + self.learning_rate * (target_q - current_q)
        
        # Update Q-table
        state_key = state.to_tuple()
        self.q_table[state_key][action] = new_q
        
        logger.debug(
            f"📊 Q-update: state={state_key}, action={action}, "
            f"reward={reward:.4f}, Q: {current_q:.4f} -> {new_q:.4f}"
        )
    
    def add_experience(
        self,
        state: MarketState,
        action: int,
        reward: float,
        next_state: MarketState,
        done: bool = False
    ):
        """
        Add experience to replay buffer
        
        Args:
            state: Current state
            action: Action taken
            reward: Reward received
            next_state: Next state
            done: Whether episode is done
        """
        experience = Experience(
            state=state,
            action=action,
            reward=reward,
            next_state=next_state,
            done=done,
            timestamp=datetime.utcnow(),
        )
        
        self.replay_buffer.append(experience)
        self.total_steps += 1
        self.cumulative_reward += reward
    
    def replay_train(self, batch_size: int = None):
        """
        Train on random batch from replay buffer
        
        Args:
            batch_size: Size of training batch (uses config if None)
        """
        batch_size = batch_size or self.config['batch_size']
        
        if len(self.replay_buffer) < batch_size:
            return  # Not enough experiences yet
        
        # Sample random batch
        indices = np.random.choice(len(self.replay_buffer), batch_size, replace=False)
        batch = [self.replay_buffer[i] for i in indices]
        
        # Train on batch
        for exp in batch:
            self.update_q_value(
                exp.state,
                exp.action,
                exp.reward,
                exp.next_state,
                exp.done
            )
        
        logger.debug(f"🎓 Trained on batch of {batch_size} experiences")
    
    def end_episode(self):
        """
        Called at end of episode to update exploration and stats
        """
        self.episodes += 1
        self.episode_rewards.append(self.cumulative_reward)
        
        # Decay exploration rate
        self.epsilon = max(
            self.min_epsilon,
            self.epsilon * self.epsilon_decay
        )
        
        logger.info(
            f"📈 Episode {self.episodes} ended: "
            f"reward={self.cumulative_reward:.4f}, "
            f"epsilon={self.epsilon:.4f}, "
            f"steps={self.total_steps}"
        )
        
        self.cumulative_reward = 0.0
    
    def get_strategy_preferences(self) -> Dict[int, float]:
        """
        Get average Q-value for each strategy across all states
        
        Returns:
            Dict mapping strategy index to average Q-value
        """
        if not self.q_table:
            return {i: 0.0 for i in range(self.num_strategies)}
        
        strategy_q_values = {i: [] for i in range(self.num_strategies)}
        
        for state_key, q_values in self.q_table.items():
            for strategy_idx, q_val in enumerate(q_values):
                strategy_q_values[strategy_idx].append(q_val)
        
        # Average Q-value per strategy
        preferences = {
            strategy_idx: np.mean(q_vals) if q_vals else 0.0
            for strategy_idx, q_vals in strategy_q_values.items()
        }
        
        return preferences
    
    def get_stats(self) -> Dict:
        """
        Get training statistics
        
        Returns:
            Dictionary with training stats
        """
        recent_rewards = self.episode_rewards[-10:] if self.episode_rewards else []
        
        return {
            'episodes': self.episodes,
            'total_steps': self.total_steps,
            'epsilon': self.epsilon,
            'q_table_size': len(self.q_table),
            'replay_buffer_size': len(self.replay_buffer),
            'avg_reward_last_10': np.mean(recent_rewards) if recent_rewards else 0.0,
            'strategy_preferences': self.get_strategy_preferences(),
        }
    
    def save_model(self, filepath: str):
        """
        Save Q-table and config to file
        
        Args:
            filepath: Path to save model
        """
        # Convert Q-table to serializable format
        q_table_serializable = {
            str(state): q_values.tolist()
            for state, q_values in self.q_table.items()
        }
        
        model_data = {
            'q_table': q_table_serializable,
            'num_strategies': self.num_strategies,
            'episodes': self.episodes,
            'total_steps': self.total_steps,
            'epsilon': self.epsilon,
            'config': self.config,
        }
        
        with open(filepath, 'w') as f:
            json.dump(model_data, f, indent=2)
        
        logger.info(f"💾 RL model saved to {filepath}")
    
    def load_model(self, filepath: str):
        """
        Load Q-table and config from file
        
        Args:
            filepath: Path to load model from
        """
        import ast
        
        with open(filepath, 'r') as f:
            model_data = json.load(f)
        
        # Restore Q-table
        self.q_table = {}
        for state_str, q_values in model_data['q_table'].items():
            # Convert string back to tuple safely
            state_tuple = ast.literal_eval(state_str)
            self.q_table[state_tuple] = np.array(q_values)
        
        # Restore stats
        self.episodes = model_data['episodes']
        self.total_steps = model_data['total_steps']
        self.epsilon = model_data['epsilon']
        
        logger.info(
            f"📂 RL model loaded from {filepath}: "
            f"{len(self.q_table)} states, "
            f"{self.episodes} episodes"
        )
