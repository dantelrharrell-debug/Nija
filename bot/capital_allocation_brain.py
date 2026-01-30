"""
NIJA Capital Allocation Brain - Fund Grade
===========================================

AI-powered portfolio management system with dynamic capital allocation.

Features:
1. Dynamic Portfolio Weighting - Allocate capital based on performance
2. Multi-Strategy Allocation - Route capital to best strategies
3. Multi-Broker Allocation - Distribute across brokers optimally
4. Multi-Asset Allocation - Diversify across assets
5. Risk-Based Allocation - Sharpe, Drawdown, Volatility, Correlation

This creates fund-grade, institutional-quality portfolio management.

Expected improvements:
- Better risk-adjusted returns
- Lower portfolio volatility
- Higher Sharpe ratio
- Improved diversification

Author: NIJA Trading Systems
Version: 1.0
Date: January 30, 2026
"""

import logging
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from collections import defaultdict
import json

logger = logging.getLogger("nija.capital_brain")


class AllocationMethod(Enum):
    """Capital allocation methods"""
    EQUAL_WEIGHT = "equal_weight"  # 1/N allocation
    SHARPE_WEIGHTED = "sharpe_weighted"  # Weight by Sharpe ratio
    RISK_PARITY = "risk_parity"  # Equal risk contribution
    KELLY = "kelly"  # Kelly criterion
    MAX_SHARPE = "max_sharpe"  # Maximum Sharpe optimization
    MIN_VARIANCE = "min_variance"  # Minimum variance
    MEAN_VARIANCE = "mean_variance"  # Mean-variance optimization


@dataclass
class AllocationTarget:
    """Represents an allocation target (strategy, broker, asset)"""
    target_id: str
    target_type: str  # 'strategy', 'broker', 'asset'
    
    # Performance metrics
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    profit_factor: float = 1.0
    win_rate: float = 0.5
    avg_return: float = 0.0
    volatility: float = 0.0
    max_drawdown: float = 0.0
    
    # Allocation
    current_capital: float = 0.0
    target_allocation_pct: float = 0.0
    min_allocation_pct: float = 0.0
    max_allocation_pct: float = 1.0
    
    # Constraints
    is_active: bool = True
    allocation_priority: int = 1  # 1=high, 5=low
    
    # Returns history for correlation
    returns_history: List[float] = field(default_factory=list)
    
    last_updated: datetime = field(default_factory=datetime.now)
    
    def update_metrics(self, metrics: Dict):
        """Update performance metrics"""
        self.sharpe_ratio = metrics.get('sharpe_ratio', self.sharpe_ratio)
        self.sortino_ratio = metrics.get('sortino_ratio', self.sortino_ratio)
        self.profit_factor = metrics.get('profit_factor', self.profit_factor)
        self.win_rate = metrics.get('win_rate', self.win_rate)
        self.avg_return = metrics.get('avg_return', self.avg_return)
        self.volatility = metrics.get('volatility', self.volatility)
        self.max_drawdown = metrics.get('max_drawdown', self.max_drawdown)
        
        if 'returns' in metrics:
            self.returns_history.extend(metrics['returns'])
            # Keep only last 100 returns
            self.returns_history = self.returns_history[-100:]
        
        self.last_updated = datetime.now()


@dataclass
class AllocationPlan:
    """Capital allocation plan"""
    timestamp: datetime = field(default_factory=datetime.now)
    total_capital: float = 0.0
    method: AllocationMethod = AllocationMethod.SHARPE_WEIGHTED
    
    # Allocations
    allocations: Dict[str, float] = field(default_factory=dict)  # target_id -> capital
    allocation_pcts: Dict[str, float] = field(default_factory=dict)  # target_id -> percentage
    
    # Portfolio metrics
    expected_return: float = 0.0
    expected_volatility: float = 0.0
    expected_sharpe: float = 0.0
    diversification_score: float = 0.0
    
    # Rebalancing
    rebalancing_actions: List[Dict] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'timestamp': self.timestamp.isoformat(),
            'total_capital': self.total_capital,
            'method': self.method.value,
            'allocations': self.allocations,
            'allocation_pcts': self.allocation_pcts,
            'expected_metrics': {
                'return': self.expected_return,
                'volatility': self.expected_volatility,
                'sharpe': self.expected_sharpe,
                'diversification': self.diversification_score,
            },
            'rebalancing_actions': self.rebalancing_actions,
        }


class CapitalAllocationBrain:
    """
    AI-Powered Capital Allocation Brain
    
    Fund-grade portfolio management with dynamic allocation across:
    - Multiple strategies
    - Multiple brokers
    - Multiple assets
    
    Optimizes based on:
    - Sharpe ratio
    - Drawdown
    - Volatility
    - Correlation
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize capital allocation brain
        
        Args:
            config: Configuration dictionary
        """
        self.config = config or {}
        
        # Allocation parameters
        self.total_capital = self.config.get('total_capital', 10000.0)
        self.reserve_pct = self.config.get('reserve_pct', 0.1)  # 10% reserve
        self.rebalance_threshold = self.config.get('rebalance_threshold', 0.05)  # 5%
        self.rebalance_frequency_hours = self.config.get('rebalance_frequency_hours', 24)
        
        # Default allocation method
        self.default_method = AllocationMethod(
            self.config.get('default_method', 'sharpe_weighted')
        )
        
        # Risk parameters
        self.max_position_pct = self.config.get('max_position_pct', 0.25)  # 25% max
        self.min_position_pct = self.config.get('min_position_pct', 0.02)  # 2% min
        self.target_volatility = self.config.get('target_volatility', 0.15)  # 15% annual
        
        # Allocation targets
        self.targets: Dict[str, AllocationTarget] = {}
        
        # Current allocation plan
        self.current_plan: Optional[AllocationPlan] = None
        self.last_rebalance: Optional[datetime] = None
        
        # Performance tracking
        self.allocation_history: List[AllocationPlan] = []
        self.performance_history: List[Dict] = []
        
        logger.info(
            f"🧠 Capital Allocation Brain initialized: "
            f"capital=${self.total_capital:,.2f}, "
            f"method={self.default_method.value}"
        )
    
    def add_target(
        self,
        target_id: str,
        target_type: str,
        initial_metrics: Dict = None
    ):
        """
        Add allocation target (strategy, broker, or asset)
        
        Args:
            target_id: Unique identifier
            target_type: 'strategy', 'broker', or 'asset'
            initial_metrics: Initial performance metrics
        """
        target = AllocationTarget(
            target_id=target_id,
            target_type=target_type
        )
        
        if initial_metrics:
            target.update_metrics(initial_metrics)
        
        self.targets[target_id] = target
        logger.info(f"➕ Added allocation target: {target_id} ({target_type})")
    
    def update_target_performance(
        self,
        target_id: str,
        metrics: Dict
    ):
        """
        Update performance metrics for a target
        
        Args:
            target_id: Target identifier
            metrics: Performance metrics
        """
        if target_id not in self.targets:
            logger.warning(f"Target {target_id} not found, adding it")
            self.add_target(target_id, metrics.get('type', 'strategy'), metrics)
            return
        
        self.targets[target_id].update_metrics(metrics)
    
    def calculate_correlation_matrix(
        self,
        target_ids: List[str]
    ) -> np.ndarray:
        """
        Calculate correlation matrix for targets
        
        Args:
            target_ids: List of target IDs
        
        Returns:
            Correlation matrix
        """
        # Collect returns histories
        returns_data = []
        
        for target_id in target_ids:
            if target_id in self.targets:
                returns = self.targets[target_id].returns_history
                if len(returns) >= 10:  # Minimum data points
                    returns_data.append(returns)
                else:
                    # Pad with zeros if insufficient data
                    returns_data.append([0.0] * 10)
            else:
                returns_data.append([0.0] * 10)
        
        if not returns_data:
            return np.eye(len(target_ids))
        
        # Ensure all have same length (use minimum)
        min_length = min(len(r) for r in returns_data)
        returns_data = [r[-min_length:] for r in returns_data]
        
        # Calculate correlation
        if min_length >= 2:
            returns_df = pd.DataFrame(returns_data).T
            corr_matrix = returns_df.corr().values
            
            # Handle NaN values
            corr_matrix = np.nan_to_num(corr_matrix, nan=0.0)
            
            # Ensure valid correlation matrix
            np.fill_diagonal(corr_matrix, 1.0)
        else:
            # Default to identity matrix
            corr_matrix = np.eye(len(target_ids))
        
        return corr_matrix
    
    def allocate_equal_weight(
        self,
        target_ids: List[str],
        available_capital: float
    ) -> Dict[str, float]:
        """
        Equal weight allocation (1/N)
        
        Args:
            target_ids: List of target IDs
            available_capital: Capital to allocate
        
        Returns:
            Dictionary of allocations
        """
        n = len(target_ids)
        if n == 0:
            return {}
        
        allocation_per_target = available_capital / n
        
        return {
            target_id: allocation_per_target
            for target_id in target_ids
        }
    
    def allocate_sharpe_weighted(
        self,
        target_ids: List[str],
        available_capital: float
    ) -> Dict[str, float]:
        """
        Sharpe ratio weighted allocation
        
        Args:
            target_ids: List of target IDs
            available_capital: Capital to allocate
        
        Returns:
            Dictionary of allocations
        """
        # Get Sharpe ratios
        sharpes = []
        valid_targets = []
        
        for target_id in target_ids:
            if target_id in self.targets:
                target = self.targets[target_id]
                if target.is_active and target.sharpe_ratio > 0:
                    sharpes.append(max(0.1, target.sharpe_ratio))  # Floor at 0.1
                    valid_targets.append(target_id)
        
        if not valid_targets:
            # Fall back to equal weight
            return self.allocate_equal_weight(target_ids, available_capital)
        
        # Calculate weights proportional to Sharpe
        total_sharpe = sum(sharpes)
        weights = [s / total_sharpe for s in sharpes]
        
        # Apply min/max constraints
        allocations = {}
        for target_id, weight in zip(valid_targets, weights):
            target = self.targets[target_id]
            
            # Apply constraints
            weight = max(target.min_allocation_pct, weight)
            weight = min(target.max_allocation_pct, weight)
            
            allocations[target_id] = available_capital * weight
        
        # Normalize to ensure we use all capital
        total_allocated = sum(allocations.values())
        if total_allocated > 0:
            scale = available_capital / total_allocated
            allocations = {k: v * scale for k, v in allocations.items()}
        
        return allocations
    
    def allocate_risk_parity(
        self,
        target_ids: List[str],
        available_capital: float
    ) -> Dict[str, float]:
        """
        Risk parity allocation (equal risk contribution)
        
        Args:
            target_ids: List of target IDs
            available_capital: Capital to allocate
        
        Returns:
            Dictionary of allocations
        """
        # Get volatilities
        volatilities = []
        valid_targets = []
        
        for target_id in target_ids:
            if target_id in self.targets:
                target = self.targets[target_id]
                if target.is_active and target.volatility > 0:
                    volatilities.append(target.volatility)
                    valid_targets.append(target_id)
        
        if not valid_targets:
            return self.allocate_equal_weight(target_ids, available_capital)
        
        # Weight inversely proportional to volatility
        inv_vols = [1.0 / v for v in volatilities]
        total_inv_vol = sum(inv_vols)
        weights = [iv / total_inv_vol for iv in inv_vols]
        
        # Create allocations
        allocations = {}
        for target_id, weight in zip(valid_targets, weights):
            target = self.targets[target_id]
            
            # Apply constraints
            weight = max(target.min_allocation_pct, weight)
            weight = min(target.max_allocation_pct, weight)
            
            allocations[target_id] = available_capital * weight
        
        # Normalize
        total_allocated = sum(allocations.values())
        if total_allocated > 0:
            scale = available_capital / total_allocated
            allocations = {k: v * scale for k, v in allocations.items()}
        
        return allocations
    
    def allocate_kelly(
        self,
        target_ids: List[str],
        available_capital: float
    ) -> Dict[str, float]:
        """
        Kelly criterion allocation
        
        Args:
            target_ids: List of target IDs
            available_capital: Capital to allocate
        
        Returns:
            Dictionary of allocations
        """
        kelly_fractions = []
        valid_targets = []
        
        for target_id in target_ids:
            if target_id in self.targets:
                target = self.targets[target_id]
                if target.is_active:
                    # Kelly = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win
                    # Simplified: use Sharpe as proxy
                    kelly = min(0.25, max(0.01, target.sharpe_ratio / 10.0))
                    kelly_fractions.append(kelly)
                    valid_targets.append(target_id)
        
        if not valid_targets:
            return self.allocate_equal_weight(target_ids, available_capital)
        
        # Normalize Kelly fractions
        total_kelly = sum(kelly_fractions)
        if total_kelly > 1.0:
            kelly_fractions = [k / total_kelly for k in kelly_fractions]
        
        # Create allocations
        allocations = {}
        for target_id, kelly in zip(valid_targets, kelly_fractions):
            allocations[target_id] = available_capital * kelly
        
        return allocations
    
    def calculate_portfolio_metrics(
        self,
        allocations: Dict[str, float],
        target_ids: List[str]
    ) -> Tuple[float, float, float]:
        """
        Calculate expected portfolio metrics
        
        Args:
            allocations: Capital allocations
            target_ids: List of target IDs
        
        Returns:
            Tuple of (expected_return, expected_volatility, expected_sharpe)
        """
        # Collect weights, returns, and volatilities
        weights = []
        returns = []
        volatilities = []
        
        total_capital = sum(allocations.values())
        
        for target_id in target_ids:
            if target_id in allocations and target_id in self.targets:
                target = self.targets[target_id]
                weight = allocations[target_id] / total_capital if total_capital > 0 else 0
                
                weights.append(weight)
                returns.append(target.avg_return)
                volatilities.append(target.volatility)
        
        if not weights:
            return 0.0, 0.0, 0.0
        
        weights = np.array(weights)
        returns_arr = np.array(returns)
        vols_arr = np.array(volatilities)
        
        # Expected return
        expected_return = np.dot(weights, returns_arr)
        
        # Expected volatility (simplified - assumes no correlation)
        # For full accuracy, would need covariance matrix
        expected_volatility = np.sqrt(np.dot(weights**2, vols_arr**2))
        
        # Expected Sharpe
        expected_sharpe = expected_return / expected_volatility if expected_volatility > 0 else 0.0
        
        return expected_return, expected_volatility, expected_sharpe
    
    def calculate_diversification_score(
        self,
        allocations: Dict[str, float],
        target_ids: List[str]
    ) -> float:
        """
        Calculate portfolio diversification score (0-1)
        
        Uses correlation matrix and Herfindahl index.
        
        Args:
            allocations: Capital allocations
            target_ids: List of target IDs
        
        Returns:
            Diversification score (higher is better)
        """
        if len(target_ids) <= 1:
            return 0.0
        
        total_capital = sum(allocations.values())
        if total_capital == 0:
            return 0.0
        
        # Herfindahl index (concentration measure)
        weights = np.array([
            allocations.get(tid, 0) / total_capital
            for tid in target_ids
        ])
        herfindahl = np.sum(weights ** 2)
        
        # Diversification from Herfindahl (1/N is maximum diversification)
        max_diversification = 1.0 / len(target_ids)
        diversification = (1.0 - herfindahl) / (1.0 - max_diversification) if max_diversification < 1.0 else 0.0
        
        # Get correlation matrix
        corr_matrix = self.calculate_correlation_matrix(target_ids)
        
        # Average correlation (excluding diagonal)
        n = len(target_ids)
        if n > 1:
            avg_corr = (np.sum(corr_matrix) - n) / (n * (n - 1))
            
            # Adjust diversification by correlation
            # Lower correlation = better diversification
            diversification *= (1.0 - avg_corr)
        
        return max(0.0, min(1.0, diversification))
    
    def create_allocation_plan(
        self,
        method: AllocationMethod = None,
        target_filter: Dict = None
    ) -> AllocationPlan:
        """
        Create capital allocation plan
        
        Args:
            method: Allocation method (uses default if None)
            target_filter: Filter targets (e.g., {'type': 'strategy'})
        
        Returns:
            AllocationPlan
        """
        method = method or self.default_method
        
        # Filter targets
        target_ids = []
        for target_id, target in self.targets.items():
            if not target.is_active:
                continue
            
            if target_filter:
                if 'type' in target_filter and target.target_type != target_filter['type']:
                    continue
                # Add more filter conditions as needed
            
            target_ids.append(target_id)
        
        if not target_ids:
            logger.warning("No active targets for allocation")
            return AllocationPlan(
                total_capital=self.total_capital,
                method=method
            )
        
        # Calculate available capital (after reserve)
        available_capital = self.total_capital * (1.0 - self.reserve_pct)
        
        # Allocate based on method
        if method == AllocationMethod.EQUAL_WEIGHT:
            allocations = self.allocate_equal_weight(target_ids, available_capital)
        elif method == AllocationMethod.SHARPE_WEIGHTED:
            allocations = self.allocate_sharpe_weighted(target_ids, available_capital)
        elif method == AllocationMethod.RISK_PARITY:
            allocations = self.allocate_risk_parity(target_ids, available_capital)
        elif method == AllocationMethod.KELLY:
            allocations = self.allocate_kelly(target_ids, available_capital)
        else:
            # Default to Sharpe weighted
            allocations = self.allocate_sharpe_weighted(target_ids, available_capital)
        
        # Calculate allocation percentages
        allocation_pcts = {
            target_id: (capital / self.total_capital)
            for target_id, capital in allocations.items()
        }
        
        # Calculate portfolio metrics
        expected_return, expected_vol, expected_sharpe = self.calculate_portfolio_metrics(
            allocations, target_ids
        )
        
        # Calculate diversification
        diversification = self.calculate_diversification_score(allocations, target_ids)
        
        # Create plan
        plan = AllocationPlan(
            total_capital=self.total_capital,
            method=method,
            allocations=allocations,
            allocation_pcts=allocation_pcts,
            expected_return=expected_return,
            expected_volatility=expected_vol,
            expected_sharpe=expected_sharpe,
            diversification_score=diversification,
        )
        
        # Calculate rebalancing actions if we have a current plan
        if self.current_plan:
            plan.rebalancing_actions = self._calculate_rebalancing_actions(plan)
        
        return plan
    
    def _calculate_rebalancing_actions(
        self,
        new_plan: AllocationPlan
    ) -> List[Dict]:
        """
        Calculate rebalancing actions
        
        Args:
            new_plan: New allocation plan
        
        Returns:
            List of rebalancing actions
        """
        actions = []
        
        for target_id in set(self.current_plan.allocations.keys()) | set(new_plan.allocations.keys()):
            current_allocation = self.current_plan.allocations.get(target_id, 0.0)
            new_allocation = new_plan.allocations.get(target_id, 0.0)
            
            diff = new_allocation - current_allocation
            diff_pct = abs(diff) / self.total_capital if self.total_capital > 0 else 0
            
            # Only create action if difference exceeds threshold
            if diff_pct >= self.rebalance_threshold:
                action = {
                    'target_id': target_id,
                    'action': 'increase' if diff > 0 else 'decrease',
                    'current_capital': current_allocation,
                    'target_capital': new_allocation,
                    'change': diff,
                    'change_pct': (diff / self.total_capital) if self.total_capital > 0 else 0,
                }
                actions.append(action)
        
        return actions
    
    def should_rebalance(self) -> bool:
        """
        Check if portfolio should be rebalanced
        
        Returns:
            True if rebalancing is needed
        """
        # No current plan
        if self.current_plan is None:
            return True
        
        # Time-based rebalancing
        if self.last_rebalance is None:
            return True
        
        hours_since_rebalance = (
            datetime.now() - self.last_rebalance
        ).total_seconds() / 3600
        
        if hours_since_rebalance >= self.rebalance_frequency_hours:
            return True
        
        # Threshold-based rebalancing
        # Check if any allocation drifted significantly
        for target_id, target in self.targets.items():
            if not target.is_active:
                continue
            
            current_pct = self.current_plan.allocation_pcts.get(target_id, 0.0)
            target_pct = target.target_allocation_pct
            
            if abs(current_pct - target_pct) >= self.rebalance_threshold:
                return True
        
        return False
    
    def execute_rebalancing(self, plan: AllocationPlan):
        """
        Execute rebalancing plan
        
        Args:
            plan: Allocation plan to execute
        """
        logger.info(
            f"💰 Executing rebalancing: "
            f"{len(plan.rebalancing_actions)} actions, "
            f"expected Sharpe={plan.expected_sharpe:.2f}"
        )
        
        # Log actions
        for action in plan.rebalancing_actions:
            logger.info(
                f"  {action['action'].upper()} {action['target_id']}: "
                f"${action['current_capital']:.2f} → ${action['target_capital']:.2f} "
                f"({action['change_pct']*100:+.1f}%)"
            )
        
        # Update current plan
        self.current_plan = plan
        self.last_rebalance = datetime.now()
        
        # Store in history
        self.allocation_history.append(plan)
        
        # Update target allocations
        for target_id, allocation in plan.allocations.items():
            if target_id in self.targets:
                self.targets[target_id].current_capital = allocation
                self.targets[target_id].target_allocation_pct = plan.allocation_pcts[target_id]
    
    def get_allocation_summary(self) -> Dict:
        """
        Get comprehensive allocation summary
        
        Returns:
            Summary dictionary
        """
        if self.current_plan is None:
            return {'status': 'no_plan'}
        
        return {
            'total_capital': self.total_capital,
            'allocated_capital': sum(self.current_plan.allocations.values()),
            'reserve_capital': self.total_capital * self.reserve_pct,
            'method': self.current_plan.method.value,
            'num_targets': len(self.current_plan.allocations),
            'allocations': self.current_plan.allocations,
            'allocation_pcts': self.current_plan.allocation_pcts,
            'expected_metrics': {
                'return': self.current_plan.expected_return,
                'volatility': self.current_plan.expected_volatility,
                'sharpe': self.current_plan.expected_sharpe,
                'diversification': self.current_plan.diversification_score,
            },
            'last_rebalance': self.last_rebalance.isoformat() if self.last_rebalance else None,
            'rebalancing_needed': self.should_rebalance(),
        }
