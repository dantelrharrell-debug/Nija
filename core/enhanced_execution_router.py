"""
Enhanced Execution Router - Load Balancing & Fault Tolerance

This is the Money Engine that routes trades with:
- Load control and balancing
- Fault tolerance with circuit breaker
- Broker health monitoring
- Latency optimization
- Request queuing for load control
"""

import logging
import time
import threading
from enum import Enum
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
import queue

logger = logging.getLogger("nija.enhanced_router")


class BrokerHealth(Enum):
    """Broker health status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    CIRCUIT_OPEN = "circuit_open"


@dataclass
class BrokerMetrics:
    """Metrics for a single broker."""
    broker_name: str
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_latency_ms: float = 0.0
    last_error: Optional[str] = None
    last_error_time: Optional[datetime] = None
    health_status: BrokerHealth = BrokerHealth.HEALTHY
    circuit_open_until: Optional[datetime] = None

    @property
    def success_rate(self) -> float:
        """Calculate success rate."""
        if self.total_requests == 0:
            return 0.0
        return (self.successful_requests / self.total_requests) * 100

    @property
    def average_latency_ms(self) -> float:
        """Calculate average latency."""
        if self.successful_requests == 0:
            return 0.0
        return self.total_latency_ms / self.successful_requests


class CircuitBreaker:
    """
    Circuit breaker pattern for broker fault tolerance.

    States:
    - CLOSED: Normal operation
    - OPEN: Broker is failing, stop sending requests
    - HALF_OPEN: Test if broker has recovered
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout_seconds: int = 60,
        success_threshold: int = 2
    ):
        """
        Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout_seconds: Time to wait before testing recovery
            success_threshold: Successes needed to close circuit
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = timedelta(seconds=recovery_timeout_seconds)
        self.success_threshold = success_threshold

        self.failure_count = 0
        self.success_count = 0
        self.state = "CLOSED"
        self.opened_at: Optional[datetime] = None

        logger.info(f"Circuit breaker initialized (threshold={failure_threshold})")

    def call(self, func: Callable, *args, **kwargs):
        """Execute function with circuit breaker protection."""
        if self.state == "OPEN":
            # Check if we should try recovery
            if self.opened_at and datetime.now() - self.opened_at > self.recovery_timeout:
                logger.info("Circuit breaker: entering HALF_OPEN state")
                self.state = "HALF_OPEN"
                self.success_count = 0
            else:
                raise Exception("Circuit breaker is OPEN - broker unavailable")

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise e

    def _on_success(self):
        """Handle successful execution."""
        self.failure_count = 0

        if self.state == "HALF_OPEN":
            self.success_count += 1
            if self.success_count >= self.success_threshold:
                logger.info("Circuit breaker: CLOSED (broker recovered)")
                self.state = "CLOSED"
                self.opened_at = None

    def _on_failure(self):
        """Handle failed execution."""
        self.failure_count += 1

        if self.state == "HALF_OPEN":
            logger.warning("Circuit breaker: reopening due to failure in HALF_OPEN")
            self.state = "OPEN"
            self.opened_at = datetime.now()
            self.failure_count = 0
        elif self.failure_count >= self.failure_threshold:
            logger.error(f"Circuit breaker: OPEN after {self.failure_count} failures")
            self.state = "OPEN"
            self.opened_at = datetime.now()


class EnhancedExecutionRouter:
    """
    Enhanced execution router with load balancing and fault tolerance.

    Features:
    - Multi-broker load balancing
    - Health monitoring and circuit breakers
    - Latency tracking and optimization
    - Automatic failover
    - Request queuing and throttling
    """

    def __init__(
        self,
        max_queue_size: int = 1000,
        worker_threads: int = 4
    ):
        """
        Initialize enhanced execution router.

        Args:
            max_queue_size: Maximum pending requests in queue
            worker_threads: Number of worker threads for processing
        """
        self.max_queue_size = max_queue_size
        self.worker_threads = worker_threads

        # Broker management
        self.broker_metrics: Dict[str, BrokerMetrics] = {}
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
        self.broker_pools: Dict[str, List[str]] = {}  # user_id -> [broker_names]

        # Request queue
        self.request_queue = queue.Queue(maxsize=max_queue_size)

        # Thread management
        self.workers = []
        self.running = False
        self.lock = threading.Lock()

        logger.info(f"Enhanced execution router initialized (queue={max_queue_size}, workers={worker_threads})")

    def register_broker(self, broker_name: str):
        """Register a new broker for routing."""
        with self.lock:
            if broker_name not in self.broker_metrics:
                self.broker_metrics[broker_name] = BrokerMetrics(broker_name)
                self.circuit_breakers[broker_name] = CircuitBreaker()
                logger.info(f"Registered broker: {broker_name}")

    def get_broker_health(self, broker_name: str) -> BrokerHealth:
        """Get current health status of a broker."""
        if broker_name not in self.broker_metrics:
            return BrokerHealth.UNHEALTHY

        metrics = self.broker_metrics[broker_name]
        circuit = self.circuit_breakers[broker_name]

        # Check circuit breaker state
        if circuit.state == "OPEN":
            return BrokerHealth.CIRCUIT_OPEN

        # Check success rate
        if metrics.total_requests > 10:
            if metrics.success_rate < 50:
                return BrokerHealth.UNHEALTHY
            elif metrics.success_rate < 80:
                return BrokerHealth.DEGRADED

        return BrokerHealth.HEALTHY

    def select_best_broker(
        self,
        user_id: str,
        available_brokers: Optional[List[str]] = None
    ) -> Optional[str]:
        """
        Select the best broker for routing based on health and latency.

        Args:
            user_id: User identifier
            available_brokers: List of available brokers (None = all)

        Returns:
            str: Selected broker name or None if none available
        """
        if available_brokers is None:
            available_brokers = list(self.broker_metrics.keys())

        if not available_brokers:
            return None

        # Filter healthy brokers
        healthy_brokers = []
        for broker in available_brokers:
            health = self.get_broker_health(broker)
            if health in [BrokerHealth.HEALTHY, BrokerHealth.DEGRADED]:
                healthy_brokers.append(broker)

        if not healthy_brokers:
            logger.warning(f"No healthy brokers available for user {user_id}")
            return None

        # Select broker with best latency
        best_broker = min(
            healthy_brokers,
            key=lambda b: self.broker_metrics[b].average_latency_ms
        )

        return best_broker

    def record_execution(
        self,
        broker_name: str,
        success: bool,
        latency_ms: float,
        error: Optional[str] = None
    ):
        """Record execution metrics for a broker."""
        with self.lock:
            if broker_name not in self.broker_metrics:
                self.register_broker(broker_name)

            metrics = self.broker_metrics[broker_name]
            metrics.total_requests += 1

            if success:
                metrics.successful_requests += 1
                metrics.total_latency_ms += latency_ms
            else:
                metrics.failed_requests += 1
                metrics.last_error = error
                metrics.last_error_time = datetime.now()

            # Update health status
            metrics.health_status = self.get_broker_health(broker_name)

    def execute_with_failover(
        self,
        user_id: str,
        brokers: List[str],
        execute_func: Callable,
        *args,
        **kwargs
    ):
        """
        Execute trade with automatic failover to backup brokers.

        Args:
            user_id: User identifier
            brokers: List of brokers to try (in order)
            execute_func: Function to execute
            *args, **kwargs: Arguments for execute_func

        Returns:
            Execution result

        Raises:
            Exception: If all brokers fail
        """
        last_error = None

        for broker in brokers:
            try:
                circuit = self.circuit_breakers.get(broker)
                if not circuit:
                    self.register_broker(broker)
                    circuit = self.circuit_breakers[broker]

                # Execute with circuit breaker protection
                start_time = time.time()
                result = circuit.call(execute_func, broker, *args, **kwargs)
                latency_ms = (time.time() - start_time) * 1000

                # Record success
                self.record_execution(broker, True, latency_ms)
                logger.info(f"✅ Executed on {broker} for user {user_id} ({latency_ms:.0f}ms)")

                return result

            except Exception as e:
                last_error = str(e)
                self.record_execution(broker, False, 0, last_error)
                logger.warning(f"❌ Failed on {broker}: {last_error}")
                continue

        # All brokers failed
        raise Exception(f"All brokers failed. Last error: {last_error}")

    def get_broker_stats(self) -> Dict:
        """Get statistics for all brokers."""
        with self.lock:
            return {
                broker: {
                    'total_requests': metrics.total_requests,
                    'success_rate': round(metrics.success_rate, 2),
                    'average_latency_ms': round(metrics.average_latency_ms, 2),
                    'health': metrics.health_status.value,
                    'circuit_state': self.circuit_breakers[broker].state
                }
                for broker, metrics in self.broker_metrics.items()
            }


# Global router instance
_router = None


def get_enhanced_router() -> EnhancedExecutionRouter:
    """Get global enhanced execution router instance."""
    global _router
    if _router is None:
        _router = EnhancedExecutionRouter()
    return _router


__all__ = [
    'EnhancedExecutionRouter',
    'BrokerHealth',
    'CircuitBreaker',
    'get_enhanced_router',
]
