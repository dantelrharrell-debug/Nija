"""
NIJA Tier-Based Execution Router

Routes trades to appropriate execution infrastructure based on user tier:

User Tier → Strategy Pool → Risk Limits → Execution Priority

Tier Routing Table:
┌──────────┬─────────────────┬────────────────┬──────────────────┐
│ Tier     │ Strategy Pool   │ Infrastructure │ Execution        │
├──────────┼─────────────────┼────────────────┼──────────────────┤
│ STARTER  │ Safe copy       │ Shared         │ Normal           │
│ SAVER    │ Capital protect │ Shared         │ Normal           │
│ INVESTOR │ Full AI         │ Priority       │ High             │
│ INCOME   │ Full AI         │ Priority       │ High             │
│ LIVABLE  │ Pro AI          │ Priority nodes │ Very High        │
│ BALLER   │ Custom AI       │ Dedicated      │ Ultra High       │
└──────────┴─────────────────┴────────────────┴──────────────────┘

Author: NIJA Trading Systems
Version: 1.0
Date: January 27, 2026
"""

import logging
from enum import Enum
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime
import queue
import threading

logger = logging.getLogger("nija.execution_router")


class ExecutionPriority(Enum):
    """Execution priority levels."""
    NORMAL = 1
    HIGH = 2
    VERY_HIGH = 3
    ULTRA_HIGH = 4


class InfrastructureType(Enum):
    """Infrastructure allocation types."""
    SHARED = "shared"              # Shared execution infrastructure
    PRIORITY = "priority"          # Priority execution nodes
    PRIORITY_NODES = "priority_nodes"  # Dedicated priority nodes
    DEDICATED = "dedicated"        # Dedicated servers


@dataclass
class ExecutionConfig:
    """Configuration for tier-based execution."""
    tier: str
    strategy_pool: str
    infrastructure: InfrastructureType
    priority: ExecutionPriority
    max_latency_ms: int  # Maximum acceptable latency
    retry_limit: int     # Maximum retries for failed orders


class ExecutionRouter:
    """
    Routes trades to appropriate execution infrastructure based on tier.
    
    Features:
    - Priority-based queue management
    - Tier-specific execution rules
    - Latency monitoring
    - Automatic retry logic
    """
    
    # Tier-specific execution configurations
    TIER_EXECUTION_CONFIGS = {
        "STARTER": ExecutionConfig(
            tier="STARTER",
            strategy_pool="Safe Copy Trading",
            infrastructure=InfrastructureType.SHARED,
            priority=ExecutionPriority.NORMAL,
            max_latency_ms=5000,  # 5 seconds
            retry_limit=2
        ),
        "SAVER": ExecutionConfig(
            tier="SAVER",
            strategy_pool="Capital Protection",
            infrastructure=InfrastructureType.SHARED,
            priority=ExecutionPriority.NORMAL,
            max_latency_ms=5000,
            retry_limit=2
        ),
        "INVESTOR": ExecutionConfig(
            tier="INVESTOR",
            strategy_pool="Full AI",
            infrastructure=InfrastructureType.PRIORITY,
            priority=ExecutionPriority.HIGH,
            max_latency_ms=3000,  # 3 seconds
            retry_limit=3
        ),
        "INCOME": ExecutionConfig(
            tier="INCOME",
            strategy_pool="Full AI",
            infrastructure=InfrastructureType.PRIORITY,
            priority=ExecutionPriority.HIGH,
            max_latency_ms=3000,
            retry_limit=3
        ),
        "LIVABLE": ExecutionConfig(
            tier="LIVABLE",
            strategy_pool="Pro AI",
            infrastructure=InfrastructureType.PRIORITY_NODES,
            priority=ExecutionPriority.VERY_HIGH,
            max_latency_ms=1500,  # 1.5 seconds
            retry_limit=4
        ),
        "BALLER": ExecutionConfig(
            tier="BALLER",
            strategy_pool="Custom AI",
            infrastructure=InfrastructureType.DEDICATED,
            priority=ExecutionPriority.ULTRA_HIGH,
            max_latency_ms=500,   # 500ms
            retry_limit=5
        )
    }
    
    def __init__(self):
        """Initialize execution router with priority queues."""
        # Priority queues for each priority level
        self.queues = {
            ExecutionPriority.NORMAL: queue.PriorityQueue(),
            ExecutionPriority.HIGH: queue.PriorityQueue(),
            ExecutionPriority.VERY_HIGH: queue.PriorityQueue(),
            ExecutionPriority.ULTRA_HIGH: queue.PriorityQueue()
        }
        
        # Execution metrics
        self.execution_stats = {
            "total_orders": 0,
            "successful_orders": 0,
            "failed_orders": 0,
            "average_latency_ms": 0.0,
            "by_tier": {}
        }
        
        # Lock for thread safety
        self.lock = threading.Lock()
        
        logger.info("ExecutionRouter initialized")
    
    def route_order(
        self,
        user_tier: str,
        order: Dict,
        timestamp: Optional[datetime] = None
    ) -> Dict:
        """
        Route order to appropriate execution infrastructure.
        
        Args:
            user_tier: User's subscription tier
            order: Order details (pair, side, size, etc.)
            timestamp: Order timestamp (optional)
            
        Returns:
            Dictionary with routing information
        """
        tier = user_tier.upper()
        config = self.TIER_EXECUTION_CONFIGS.get(
            tier,
            self.TIER_EXECUTION_CONFIGS["SAVER"]  # Default to SAVER
        )
        
        # Create execution request
        execution_request = {
            "order": order,
            "tier": tier,
            "priority": config.priority,
            "infrastructure": config.infrastructure,
            "max_latency_ms": config.max_latency_ms,
            "retry_limit": config.retry_limit,
            "timestamp": timestamp or datetime.now(),
            "attempts": 0
        }
        
        # Add to appropriate priority queue
        priority_value = config.priority.value
        self.queues[config.priority].put((priority_value, execution_request))
        
        logger.info(
            f"Order routed: tier={tier}, priority={config.priority.name}, "
            f"infrastructure={config.infrastructure.value}"
        )
        
        return {
            "routed": True,
            "tier": tier,
            "priority": config.priority.name,
            "infrastructure": config.infrastructure.value,
            "max_latency_ms": config.max_latency_ms,
            "queue_size": self.queues[config.priority].qsize()
        }
    
    def get_next_order(self) -> Optional[Dict]:
        """
        Get next order from highest priority queue.
        
        Returns:
            Next execution request or None if all queues empty
        """
        # Check queues in priority order (ULTRA_HIGH to NORMAL)
        for priority in [
            ExecutionPriority.ULTRA_HIGH,
            ExecutionPriority.VERY_HIGH,
            ExecutionPriority.HIGH,
            ExecutionPriority.NORMAL
        ]:
            try:
                if not self.queues[priority].empty():
                    _, execution_request = self.queues[priority].get_nowait()
                    return execution_request
            except queue.Empty:
                continue
        
        return None
    
    def record_execution(
        self,
        tier: str,
        success: bool,
        latency_ms: float,
        error: Optional[str] = None
    ):
        """
        Record execution metrics.
        
        Args:
            tier: User tier
            success: Whether execution succeeded
            latency_ms: Execution latency in milliseconds
            error: Error message if failed
        """
        with self.lock:
            self.execution_stats["total_orders"] += 1
            
            if success:
                self.execution_stats["successful_orders"] += 1
            else:
                self.execution_stats["failed_orders"] += 1
            
            # Update average latency (moving average)
            total = self.execution_stats["total_orders"]
            current_avg = self.execution_stats["average_latency_ms"]
            self.execution_stats["average_latency_ms"] = (
                (current_avg * (total - 1) + latency_ms) / total
            )
            
            # Per-tier stats
            if tier not in self.execution_stats["by_tier"]:
                self.execution_stats["by_tier"][tier] = {
                    "total": 0,
                    "successful": 0,
                    "failed": 0,
                    "avg_latency_ms": 0.0
                }
            
            tier_stats = self.execution_stats["by_tier"][tier]
            tier_stats["total"] += 1
            
            if success:
                tier_stats["successful"] += 1
            else:
                tier_stats["failed"] += 1
            
            # Update tier average latency
            tier_total = tier_stats["total"]
            tier_avg = tier_stats["avg_latency_ms"]
            tier_stats["avg_latency_ms"] = (
                (tier_avg * (tier_total - 1) + latency_ms) / tier_total
            )
    
    def get_queue_status(self) -> Dict:
        """
        Get current queue status.
        
        Returns:
            Dictionary with queue sizes by priority
        """
        return {
            "ULTRA_HIGH": self.queues[ExecutionPriority.ULTRA_HIGH].qsize(),
            "VERY_HIGH": self.queues[ExecutionPriority.VERY_HIGH].qsize(),
            "HIGH": self.queues[ExecutionPriority.HIGH].qsize(),
            "NORMAL": self.queues[ExecutionPriority.NORMAL].qsize(),
            "total": sum(q.qsize() for q in self.queues.values())
        }
    
    def get_execution_stats(self) -> Dict:
        """
        Get execution statistics.
        
        Returns:
            Dictionary with execution metrics
        """
        with self.lock:
            return self.execution_stats.copy()
    
    def get_tier_config(self, tier: str) -> ExecutionConfig:
        """
        Get execution configuration for a tier.
        
        Args:
            tier: User tier name
            
        Returns:
            ExecutionConfig for the tier
        """
        return self.TIER_EXECUTION_CONFIGS.get(
            tier.upper(),
            self.TIER_EXECUTION_CONFIGS["SAVER"]
        )
    
    def clear_queues(self):
        """Clear all execution queues (use with caution)."""
        for priority_queue in self.queues.values():
            while not priority_queue.empty():
                try:
                    priority_queue.get_nowait()
                except queue.Empty:
                    break
        logger.warning("All execution queues cleared")


class ExecutionOrchestrator:
    """
    Orchestrates trade execution across multiple infrastructure types.
    
    This is the main coordinator that:
    - Pulls orders from priority queues
    - Routes to appropriate execution backend
    - Handles retries and failures
    - Monitors performance
    """
    
    def __init__(self, router: ExecutionRouter):
        """
        Initialize execution orchestrator.
        
        Args:
            router: ExecutionRouter instance
        """
        self.router = router
        self.running = False
        self.worker_thread = None
        
    def start(self):
        """Start execution worker thread."""
        if not self.running:
            self.running = True
            self.worker_thread = threading.Thread(target=self._execution_worker, daemon=True)
            self.worker_thread.start()
            logger.info("ExecutionOrchestrator started")
    
    def stop(self):
        """Stop execution worker thread."""
        if self.running:
            self.running = False
            if self.worker_thread:
                self.worker_thread.join(timeout=5.0)
            logger.info("ExecutionOrchestrator stopped")
    
    def _execution_worker(self):
        """
        Worker thread that processes orders from queues.
        
        This runs continuously and processes orders based on priority.
        """
        import time
        
        while self.running:
            try:
                # Get next order
                request = self.router.get_next_order()
                
                if request is None:
                    # No orders, sleep briefly
                    time.sleep(0.1)
                    continue
                
                # Execute order
                start_time = datetime.now()
                success = self._execute_order(request)
                latency_ms = (datetime.now() - start_time).total_seconds() * 1000
                
                # Record metrics
                self.router.record_execution(
                    tier=request["tier"],
                    success=success,
                    latency_ms=latency_ms
                )
                
                logger.info(
                    f"Order executed: tier={request['tier']}, "
                    f"success={success}, latency={latency_ms:.1f}ms"
                )
                
            except Exception as e:
                logger.error(f"Error in execution worker: {e}")
                time.sleep(1.0)  # Back off on error
    
    def _execute_order(self, request: Dict) -> bool:
        """
        Execute a single order.
        
        Args:
            request: Execution request
            
        Returns:
            True if successful, False otherwise
        """
        # TODO: Implement actual order execution
        # This will interface with:
        # - bot/broker_integration.py for crypto
        # - Stock broker APIs for equities
        # - Derivatives broker APIs for futures/options
        
        order = request["order"]
        tier = request["tier"]
        infrastructure = request["infrastructure"]
        
        logger.info(
            f"Executing order on {infrastructure.value} infrastructure: "
            f"tier={tier}, order={order}"
        )
        
        # Placeholder - actual execution to be implemented
        return True
