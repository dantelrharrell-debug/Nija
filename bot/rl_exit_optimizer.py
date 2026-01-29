"""
Reinforcement Learning Exit Optimizer
======================================

Adaptive TP tuning via reward maximization using Q-learning.

This module learns optimal exit strategies based on market conditions:
- State: Current profit %, volatility, trend strength, time in trade
- Action: Exit percentage (partial or full exit)
- Reward: Realized profit minus opportunity cost
- Learning: Update Q-values to maximize long-term rewards

Integrates with existing NIJA strategy for intelligent profit-taking.

Author: NIJA Trading Systems
Version: 1.0
Date: January 29, 2026
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
from collections import deque
from datetime import datetime
import logging
import json

logger = logging.getLogger("nija.rl_exit")


@dataclass
class ExitState:
    """
    Represents current state for exit decision-making
    
    Attributes:
        profit_pct: Current unrealized profit percentage
        volatility: Current market volatility (0-1 normalized)
        trend_strength: ADX-based trend strength (0-1 normalized)
        time_in_trade: Minutes since entry (bucketed)
        position_size_pct: Position size as % of portfolio
    """
    profit_pct: float
    volatility: float
    trend_strength: float
    time_in_trade: int
    position_size_pct: float
    
    def to_tuple(self) -> Tuple:
        """Convert to hashable tuple for Q-table"""
        # Discretize continuous values for Q-table indexing
        profit_bucket = min(int(self.profit_pct * 100), 20)  # 0-20% profit buckets
        vol_bucket = min(int(self.volatility * 10), 10)  # 0-10 volatility levels
        trend_bucket = min(int(self.trend_strength * 10), 10)  # 0-10 trend levels
        time_bucket = min(self.time_in_trade // 30, 20)  # 30-min buckets, max 20
        size_bucket = min(int(self.position_size_pct * 20), 10)  # Position size buckets
        
        return (profit_bucket, vol_bucket, trend_bucket, time_bucket, size_bucket)


@dataclass
class ExitAction:
    """
    Exit action recommendation
    
    Attributes:
        exit_pct: Percentage of position to exit (0.0-1.0)
        action_type: Type of exit ('partial', 'full', 'hold')
        expected_value: Expected value of this action
    """
    exit_pct: float
    action_type: str
    expected_value: float


@dataclass
class ExitExperience:
    """
    Experience tuple for replay buffer
    
    Attributes:
        state: Market state at exit decision
        action_idx: Index of action taken
        reward: Realized reward
        next_state: State after action (or None if trade closed)
        done: Whether trade is closed
        timestamp: When this happened
    """
    state: ExitState
    action_idx: int
    reward: float
    next_state: Optional[ExitState]
    done: bool
    timestamp: datetime


class RLExitOptimizer:
    """
    Reinforcement Learning Exit Optimizer
    
    Uses Q-learning to learn optimal exit strategies that maximize
    realized profits while minimizing opportunity cost.
    
    Key Features:
    1. Adaptive profit targets based on market conditions
    2. Learns from historical trade outcomes
    3. Balances between locking profits and riding trends
    4. Considers opportunity cost (could capital do better elsewhere?)
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize RL Exit Optimizer
        
        Args:
            config: Configuration dictionary with parameters
        """
        self.config = config or {}
        
        # Define possible exit actions
        # Actions: percentage of position to exit
        self.actions = [
            0.0,   # Hold (no exit)
            0.25,  # Exit 25%
            0.50,  # Exit 50%
            0.75,  # Exit 75%
            1.0,   # Exit 100% (full close)
        ]
        self.num_actions = len(self.actions)
        
        # Q-table: state -> action -> Q-value
        self.q_table: Dict[Tuple, np.ndarray] = {}
        
        # Experience replay buffer
        max_buffer_size = self.config.get('replay_buffer_size', 10000)
        self.replay_buffer = deque(maxlen=max_buffer_size)
        
        # Learning parameters
        self.learning_rate = self.config.get('learning_rate', 0.1)
        self.discount_factor = self.config.get('discount_factor', 0.95)
        self.epsilon = self.config.get('exploration_rate', 0.2)
        self.epsilon_decay = self.config.get('exploration_decay', 0.9995)
        self.min_epsilon = self.config.get('min_exploration', 0.05)
        
        # Reward shaping parameters
        self.profit_reward_scale = self.config.get('profit_reward_scale', 10.0)
        self.opportunity_cost_penalty = self.config.get('opportunity_cost_penalty', 0.5)
        self.early_exit_penalty = self.config.get('early_exit_penalty', 0.1)
        
        # Training tracking
        self.total_episodes = 0
        self.total_updates = 0
        self.performance_history = []
        
        logger.info("=" * 70)
        logger.info("🧠 RL Exit Optimizer Initialized")
        logger.info("=" * 70)
        logger.info(f"Actions: {self.actions}")
        logger.info(f"Learning Rate: {self.learning_rate}")
        logger.info(f"Discount Factor: {self.discount_factor}")
        logger.info(f"Exploration Rate: {self.epsilon} (decays to {self.min_epsilon})")
        logger.info(f"Replay Buffer Size: {max_buffer_size}")
        logger.info("=" * 70)
    
    def _get_q_values(self, state: ExitState) -> np.ndarray:
        """
        Get Q-values for a given state
        
        Args:
            state: Current exit state
            
        Returns:
            Array of Q-values for each action
        """
        state_tuple = state.to_tuple()
        
        if state_tuple not in self.q_table:
            # Initialize with small random values
            self.q_table[state_tuple] = np.random.randn(self.num_actions) * 0.01
        
        return self.q_table[state_tuple]
    
    def select_action(self, state: ExitState, training: bool = False) -> ExitAction:
        """
        Select exit action based on current state
        
        Args:
            state: Current exit state
            training: If True, uses epsilon-greedy exploration
            
        Returns:
            ExitAction recommendation
        """
        q_values = self._get_q_values(state)
        
        # Epsilon-greedy action selection during training
        if training and np.random.random() < self.epsilon:
            action_idx = np.random.randint(self.num_actions)
            logger.debug(f"Exploring: random action {action_idx}")
        else:
            action_idx = int(np.argmax(q_values))
            logger.debug(f"Exploiting: best action {action_idx} (Q={q_values[action_idx]:.3f})")
        
        exit_pct = self.actions[action_idx]
        
        # Determine action type
        if exit_pct == 0.0:
            action_type = 'hold'
        elif exit_pct == 1.0:
            action_type = 'full'
        else:
            action_type = 'partial'
        
        return ExitAction(
            exit_pct=exit_pct,
            action_type=action_type,
            expected_value=float(q_values[action_idx])
        )
    
    def calculate_reward(
        self,
        state: ExitState,
        action_idx: int,
        realized_profit_pct: float,
        opportunity_cost_pct: float = 0.0
    ) -> float:
        """
        Calculate reward for a state-action pair
        
        Args:
            state: Exit state when action was taken
            action_idx: Index of action taken
            realized_profit_pct: Actual profit realized from exit
            opportunity_cost_pct: Profit that could have been made if held longer
            
        Returns:
            Reward value (can be negative)
        """
        # Base reward: scaled realized profit
        reward = realized_profit_pct * self.profit_reward_scale
        
        # Penalty for opportunity cost (if we exited too early)
        if opportunity_cost_pct > 0:
            reward -= opportunity_cost_pct * self.opportunity_cost_penalty
        
        # Small penalty for very early exits (encourage letting winners run a bit)
        if state.time_in_trade < 30 and self.actions[action_idx] > 0.5:
            reward -= self.early_exit_penalty
        
        # Bonus for exiting before losses (if we had profit and market turned)
        if realized_profit_pct > 0 and opportunity_cost_pct < -0.01:
            reward += 0.5  # Bonus for avoiding loss
        
        return reward
    
    def update_q_value(
        self,
        state: ExitState,
        action_idx: int,
        reward: float,
        next_state: Optional[ExitState],
        done: bool
    ) -> None:
        """
        Update Q-value using Q-learning update rule
        
        Args:
            state: Current state
            action_idx: Action taken
            reward: Reward received
            next_state: Next state (None if terminal)
            done: Whether episode is done
        """
        current_q = self._get_q_values(state)[action_idx]
        
        if done or next_state is None:
            # Terminal state: no future rewards
            target_q = reward
        else:
            # Non-terminal: consider future rewards
            next_q_values = self._get_q_values(next_state)
            max_next_q = np.max(next_q_values)
            target_q = reward + self.discount_factor * max_next_q
        
        # Q-learning update
        new_q = current_q + self.learning_rate * (target_q - current_q)
        
        # Update Q-table
        state_tuple = state.to_tuple()
        self.q_table[state_tuple][action_idx] = new_q
        
        self.total_updates += 1
        
        logger.debug(
            f"Q-update: state={state_tuple[:2]}, action={action_idx}, "
            f"Q: {current_q:.3f} -> {new_q:.3f}, reward={reward:.3f}"
        )
    
    def add_experience(
        self,
        state: ExitState,
        action_idx: int,
        reward: float,
        next_state: Optional[ExitState],
        done: bool
    ) -> None:
        """
        Add experience to replay buffer
        
        Args:
            state: State at decision time
            action_idx: Action taken
            reward: Reward received
            next_state: Resulting state (None if done)
            done: Whether episode ended
        """
        experience = ExitExperience(
            state=state,
            action_idx=action_idx,
            reward=reward,
            next_state=next_state,
            done=done,
            timestamp=datetime.now()
        )
        
        self.replay_buffer.append(experience)
        
        # Immediate update with this experience
        self.update_q_value(state, action_idx, reward, next_state, done)
    
    def replay_batch(self, batch_size: int = 32) -> None:
        """
        Train on a random batch of experiences from replay buffer
        
        Args:
            batch_size: Number of experiences to sample
        """
        if len(self.replay_buffer) < batch_size:
            return
        
        # Sample random batch
        indices = np.random.choice(len(self.replay_buffer), batch_size, replace=False)
        batch = [self.replay_buffer[i] for i in indices]
        
        # Update Q-values for batch
        for exp in batch:
            self.update_q_value(
                exp.state,
                exp.action_idx,
                exp.reward,
                exp.next_state,
                exp.done
            )
        
        logger.debug(f"Replayed batch of {batch_size} experiences")
    
    def decay_exploration(self) -> None:
        """Decay exploration rate (epsilon)"""
        if self.epsilon > self.min_epsilon:
            self.epsilon *= self.epsilon_decay
            logger.debug(f"Epsilon decayed to {self.epsilon:.4f}")
    
    def get_stats(self) -> Dict:
        """
        Get optimizer statistics
        
        Returns:
            Dictionary with statistics
        """
        return {
            'total_episodes': self.total_episodes,
            'total_updates': self.total_updates,
            'q_table_size': len(self.q_table),
            'replay_buffer_size': len(self.replay_buffer),
            'epsilon': self.epsilon,
            'avg_q_value': float(np.mean([np.mean(q) for q in self.q_table.values()])) if self.q_table else 0.0,
        }
    
    def save_model(self, filepath: str) -> None:
        """
        Save Q-table and parameters to file
        
        Args:
            filepath: Path to save file
        """
        model_data = {
            'q_table': {str(k): v.tolist() for k, v in self.q_table.items()},
            'epsilon': self.epsilon,
            'total_episodes': self.total_episodes,
            'total_updates': self.total_updates,
            'config': self.config,
        }
        
        with open(filepath, 'w') as f:
            json.dump(model_data, f, indent=2)
        
        logger.info(f"RL model saved to {filepath}")
    
    def load_model(self, filepath: str) -> None:
        """
        Load Q-table and parameters from file
        
        Args:
            filepath: Path to saved model file
        """
        with open(filepath, 'r') as f:
            model_data = json.load(f)
        
        # Restore Q-table (convert string keys back to tuples)
        import ast
        self.q_table = {}
        for k_str, v in model_data['q_table'].items():
            k_tuple = ast.literal_eval(k_str)  # Safely convert string to tuple
            self.q_table[k_tuple] = np.array(v)
        
        self.epsilon = model_data['epsilon']
        self.total_episodes = model_data['total_episodes']
        self.total_updates = model_data['total_updates']
        
        logger.info(f"RL model loaded from {filepath}")
        logger.info(f"  Q-table states: {len(self.q_table)}")
        logger.info(f"  Total episodes: {self.total_episodes}")
        logger.info(f"  Epsilon: {self.epsilon:.4f}")


# Singleton instance
_rl_exit_optimizer_instance = None


def get_rl_exit_optimizer(config: Dict = None) -> RLExitOptimizer:
    """
    Get singleton RL Exit Optimizer instance
    
    Args:
        config: Optional configuration (only used on first call)
        
    Returns:
        RLExitOptimizer instance
    """
    global _rl_exit_optimizer_instance
    
    if _rl_exit_optimizer_instance is None:
        _rl_exit_optimizer_instance = RLExitOptimizer(config)
    
    return _rl_exit_optimizer_instance
