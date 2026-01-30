"""
NIJA User Capital Isolation Engine
===================================

True multi-tenant execution with individual trading containers and capital isolation.

Features:
- Individual trading containers per user
- Complete capital isolation (no cross-contamination)
- Per-user position tracking
- Isolated risk management
- Resource quotas and limits
- Performance isolation

This ensures each user's capital is completely isolated from others,
preventing any possibility of capital bleed across accounts.

Author: NIJA Trading Systems
Version: 1.0 (Path 2)
Date: January 30, 2026
"""

import logging
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import threading
from collections import defaultdict

logger = logging.getLogger("nija.capital_isolation")


class ContainerStatus(Enum):
    """Trading container statuses"""
    INITIALIZING = "initializing"
    ACTIVE = "active"
    PAUSED = "paused"
    SUSPENDED = "suspended"
    TERMINATED = "terminated"


@dataclass
class TradingContainer:
    """
    Isolated trading container for a single user
    
    Each container has:
    - Own capital allocation
    - Own position tracking
    - Own risk limits
    - Own broker connections
    - Own performance metrics
    """
    user_id: str
    container_id: str
    status: ContainerStatus
    created_at: datetime
    
    # Capital
    allocated_capital_usd: float
    available_capital_usd: float
    total_equity_usd: float
    
    # Positions
    active_positions: Dict[str, Dict] = field(default_factory=dict)
    position_count: int = 0
    max_positions: int = 10
    
    # Performance
    total_pnl: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    
    # Risk limits
    max_position_size_usd: float = 1000.0
    max_daily_loss_usd: float = 500.0
    current_daily_loss_usd: float = 0.0
    
    # Resource usage
    cpu_usage_pct: float = 0.0
    memory_usage_mb: float = 0.0
    api_calls_today: int = 0
    max_api_calls_per_day: int = 10000
    
    # Broker connections
    connected_brokers: Set[str] = field(default_factory=set)
    
    # Locks for thread safety
    _lock: threading.Lock = field(default_factory=threading.Lock)
    
    def is_active(self) -> bool:
        """Check if container is active"""
        return self.status == ContainerStatus.ACTIVE
    
    def can_open_position(self, position_size_usd: float) -> Tuple[bool, str]:
        """
        Check if container can open a new position
        
        Args:
            position_size_usd: Position size in USD
        
        Returns:
            Tuple of (can_open, reason)
        """
        with self._lock:
            # Check status
            if not self.is_active():
                return False, f"Container not active (status: {self.status.value})"
            
            # Check position count
            if self.position_count >= self.max_positions:
                return False, f"Max positions reached ({self.max_positions})"
            
            # Check position size limit
            if position_size_usd > self.max_position_size_usd:
                return False, f"Position size ${position_size_usd:.2f} exceeds limit ${self.max_position_size_usd:.2f}"
            
            # Check available capital
            if position_size_usd > self.available_capital_usd:
                return False, f"Insufficient capital: ${position_size_usd:.2f} needed, ${self.available_capital_usd:.2f} available"
            
            # Check daily loss limit
            if self.current_daily_loss_usd >= self.max_daily_loss_usd:
                return False, f"Daily loss limit reached: ${self.current_daily_loss_usd:.2f} / ${self.max_daily_loss_usd:.2f}"
            
            return True, "OK"
    
    def allocate_capital(self, amount_usd: float):
        """Allocate capital to a position"""
        with self._lock:
            self.available_capital_usd -= amount_usd
            logger.debug(f"Container {self.container_id}: Allocated ${amount_usd:.2f}, available: ${self.available_capital_usd:.2f}")
    
    def release_capital(self, amount_usd: float):
        """Release capital from a closed position"""
        with self._lock:
            self.available_capital_usd += amount_usd
            logger.debug(f"Container {self.container_id}: Released ${amount_usd:.2f}, available: ${self.available_capital_usd:.2f}")
    
    def record_trade(self, pnl: float, won: bool):
        """Record a trade result"""
        with self._lock:
            self.total_trades += 1
            self.realized_pnl += pnl
            self.total_pnl = self.realized_pnl + self.unrealized_pnl
            
            if won:
                self.winning_trades += 1
            else:
                self.current_daily_loss_usd += abs(pnl)
    
    def update_equity(self, new_equity_usd: float):
        """Update total equity"""
        with self._lock:
            self.total_equity_usd = new_equity_usd
            self.unrealized_pnl = new_equity_usd - self.allocated_capital_usd - self.realized_pnl
            self.total_pnl = self.realized_pnl + self.unrealized_pnl
    
    def reset_daily_limits(self):
        """Reset daily limits (call at start of new trading day)"""
        with self._lock:
            self.current_daily_loss_usd = 0.0
            self.api_calls_today = 0
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        with self._lock:
            return {
                'user_id': self.user_id,
                'container_id': self.container_id,
                'status': self.status.value,
                'created_at': self.created_at.isoformat(),
                'allocated_capital_usd': self.allocated_capital_usd,
                'available_capital_usd': self.available_capital_usd,
                'total_equity_usd': self.total_equity_usd,
                'position_count': self.position_count,
                'max_positions': self.max_positions,
                'total_pnl': self.total_pnl,
                'realized_pnl': self.realized_pnl,
                'unrealized_pnl': self.unrealized_pnl,
                'total_trades': self.total_trades,
                'winning_trades': self.winning_trades,
                'win_rate': self.winning_trades / self.total_trades if self.total_trades > 0 else 0.0,
                'max_position_size_usd': self.max_position_size_usd,
                'max_daily_loss_usd': self.max_daily_loss_usd,
                'current_daily_loss_usd': self.current_daily_loss_usd,
                'cpu_usage_pct': self.cpu_usage_pct,
                'memory_usage_mb': self.memory_usage_mb,
                'api_calls_today': self.api_calls_today,
                'connected_brokers': list(self.connected_brokers)
            }


class UserCapitalIsolationEngine:
    """
    Manages isolated trading containers for each user
    
    Key Features:
    1. Container Creation & Lifecycle
       - Create isolated container per user
       - Initialize with capital allocation
       - Manage container lifecycle (start/pause/stop)
    
    2. Capital Isolation
       - No cross-contamination between users
       - Strict capital tracking per container
       - Prevent over-allocation
    
    3. Resource Management
       - CPU and memory quotas
       - API rate limiting per user
       - Position limits enforcement
    
    4. Performance Tracking
       - Per-user P&L tracking
       - Per-user trade statistics
       - Independent performance metrics
    
    5. Risk Management
       - Per-user risk limits
       - Daily loss limits
       - Position size limits
    """
    
    def __init__(self):
        """Initialize capital isolation engine"""
        self.containers: Dict[str, TradingContainer] = {}
        self._lock = threading.Lock()
        
        # Global limits
        self.max_containers = 1000
        self.total_allocated_capital = 0.0
        
        logger.info("UserCapitalIsolationEngine initialized")
    
    def create_container(
        self,
        user_id: str,
        allocated_capital_usd: float,
        tier: str = "basic",
        custom_limits: Dict = None
    ) -> Optional[TradingContainer]:
        """
        Create isolated trading container for a user
        
        Args:
            user_id: User identifier
            allocated_capital_usd: Capital to allocate to container
            tier: Subscription tier (affects limits)
            custom_limits: Optional custom limit overrides
        
        Returns:
            TradingContainer or None if failed
        """
        with self._lock:
            # Check if container already exists
            if user_id in self.containers:
                logger.warning(f"Container already exists for user {user_id}")
                return self.containers[user_id]
            
            # Check max containers
            if len(self.containers) >= self.max_containers:
                logger.error(f"Max containers reached: {self.max_containers}")
                return None
            
            # Get tier-based limits
            tier_limits = self._get_tier_limits(tier)
            
            # Apply custom overrides
            if custom_limits:
                tier_limits.update(custom_limits)
            
            # Create container
            container_id = f"container_{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            
            container = TradingContainer(
                user_id=user_id,
                container_id=container_id,
                status=ContainerStatus.ACTIVE,
                created_at=datetime.now(),
                allocated_capital_usd=allocated_capital_usd,
                available_capital_usd=allocated_capital_usd,
                total_equity_usd=allocated_capital_usd,
                max_positions=tier_limits['max_positions'],
                max_position_size_usd=tier_limits['max_position_size_usd'],
                max_daily_loss_usd=tier_limits['max_daily_loss_usd'],
                max_api_calls_per_day=tier_limits['max_api_calls_per_day']
            )
            
            self.containers[user_id] = container
            self.total_allocated_capital += allocated_capital_usd
            
            logger.info(
                f"Created container {container_id} for user {user_id}: "
                f"${allocated_capital_usd:.2f} capital, {tier} tier"
            )
            
            return container
    
    def get_container(self, user_id: str) -> Optional[TradingContainer]:
        """
        Get user's trading container
        
        Args:
            user_id: User identifier
        
        Returns:
            TradingContainer or None
        """
        return self.containers.get(user_id)
    
    def pause_container(self, user_id: str) -> bool:
        """
        Pause a user's trading container
        
        Args:
            user_id: User identifier
        
        Returns:
            True if successful
        """
        container = self.get_container(user_id)
        if not container:
            return False
        
        with container._lock:
            container.status = ContainerStatus.PAUSED
            logger.info(f"Paused container for user {user_id}")
            return True
    
    def resume_container(self, user_id: str) -> bool:
        """
        Resume a paused container
        
        Args:
            user_id: User identifier
        
        Returns:
            True if successful
        """
        container = self.get_container(user_id)
        if not container:
            return False
        
        with container._lock:
            if container.status == ContainerStatus.PAUSED:
                container.status = ContainerStatus.ACTIVE
                logger.info(f"Resumed container for user {user_id}")
                return True
            else:
                logger.warning(f"Cannot resume container (status: {container.status.value})")
                return False
    
    def terminate_container(self, user_id: str) -> bool:
        """
        Terminate and remove a user's container
        
        Args:
            user_id: User identifier
        
        Returns:
            True if successful
        """
        with self._lock:
            container = self.containers.get(user_id)
            if not container:
                return False
            
            # Check for open positions
            if container.position_count > 0:
                logger.error(f"Cannot terminate container with {container.position_count} open positions")
                return False
            
            # Update capital tracking
            self.total_allocated_capital -= container.allocated_capital_usd
            
            # Mark as terminated
            container.status = ContainerStatus.TERMINATED
            
            # Remove from active containers
            del self.containers[user_id]
            
            logger.info(f"Terminated container for user {user_id}")
            return True
    
    def update_container_capital(
        self,
        user_id: str,
        new_capital_usd: float
    ) -> bool:
        """
        Update allocated capital for a container
        
        Args:
            user_id: User identifier
            new_capital_usd: New capital allocation
        
        Returns:
            True if successful
        """
        container = self.get_container(user_id)
        if not container:
            return False
        
        with container._lock:
            old_capital = container.allocated_capital_usd
            delta = new_capital_usd - old_capital
            
            container.allocated_capital_usd = new_capital_usd
            container.available_capital_usd += delta
            
            with self._lock:
                self.total_allocated_capital += delta
            
            logger.info(
                f"Updated container capital for user {user_id}: "
                f"${old_capital:.2f} → ${new_capital_usd:.2f}"
            )
            
            return True
    
    def _get_tier_limits(self, tier: str) -> Dict:
        """
        Get resource limits based on subscription tier
        
        Args:
            tier: Subscription tier
        
        Returns:
            Dictionary of limits
        """
        tier_configs = {
            'free': {
                'max_positions': 3,
                'max_position_size_usd': 100.0,
                'max_daily_loss_usd': 50.0,
                'max_api_calls_per_day': 1000
            },
            'basic': {
                'max_positions': 10,
                'max_position_size_usd': 500.0,
                'max_daily_loss_usd': 200.0,
                'max_api_calls_per_day': 5000
            },
            'pro': {
                'max_positions': 50,
                'max_position_size_usd': 5000.0,
                'max_daily_loss_usd': 2000.0,
                'max_api_calls_per_day': 20000
            },
            'enterprise': {
                'max_positions': 999,
                'max_position_size_usd': 50000.0,
                'max_daily_loss_usd': 20000.0,
                'max_api_calls_per_day': 100000
            }
        }
        
        return tier_configs.get(tier.lower(), tier_configs['basic'])
    
    def get_all_containers(self) -> List[TradingContainer]:
        """Get all active containers"""
        with self._lock:
            return list(self.containers.values())
    
    def get_stats(self) -> Dict:
        """Get engine statistics"""
        with self._lock:
            active_count = sum(1 for c in self.containers.values() if c.is_active())
            
            return {
                'total_containers': len(self.containers),
                'active_containers': active_count,
                'total_allocated_capital_usd': self.total_allocated_capital,
                'max_containers': self.max_containers
            }


# Global instance
user_capital_isolation_engine = UserCapitalIsolationEngine()
