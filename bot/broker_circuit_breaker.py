"""
NIJA Broker Circuit Breaker - API Reliability Layer
====================================================

Implements circuit breaker pattern with exponential backoff for broker API calls.
Prevents cascading failures and tracks broker health state.

Key Features:
- Circuit breaker after X consecutive failures
- Exponential backoff with jitter
- Broker health state tracking (HEALTHY / DEGRADED / OFFLINE)
- Automatic retry coordination with retry_handler
- Hard trading pause when broker is unstable
"""

import time
import logging
import random
from enum import Enum
from typing import Callable, Optional, Any, Dict
from functools import wraps
from datetime import datetime, timedelta

logger = logging.getLogger("nija.circuit_breaker")


class BrokerHealthState(Enum):
    """Broker health states for connection monitoring"""
    HEALTHY = "healthy"      # Normal operation, all API calls working
    DEGRADED = "degraded"    # Some failures but still operational
    OFFLINE = "offline"      # Too many failures, circuit breaker open


class CircuitState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"        # Normal operation
    OPEN = "open"            # Failures exceeded threshold, blocking calls
    HALF_OPEN = "half_open"  # Testing if service recovered


class BrokerCircuitBreaker:
    """
    Circuit breaker for broker API calls with exponential backoff.
    
    Circuit breaker prevents cascading failures by temporarily blocking
    API calls after too many failures, giving the broker time to recover.
    
    State transitions:
    - CLOSED -> OPEN: After failure_threshold consecutive failures
    - OPEN -> HALF_OPEN: After recovery_timeout seconds
    - HALF_OPEN -> CLOSED: On successful call
    - HALF_OPEN -> OPEN: On failed call
    """
    
    def __init__(self,
                 broker_name: str,
                 failure_threshold: int = 5,
                 recovery_timeout: float = 60.0,
                 success_threshold: int = 2,
                 max_retry_delay: float = 30.0):
        """
        Initialize circuit breaker.
        
        Args:
            broker_name: Name of broker for logging
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds to wait before testing recovery (half-open)
            success_threshold: Consecutive successes needed to close circuit from half-open
            max_retry_delay: Maximum delay for exponential backoff (seconds)
        """
        self.broker_name = broker_name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold
        self.max_retry_delay = max_retry_delay
        
        # Circuit state
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.last_state_change: datetime = datetime.now()
        
        # Broker health tracking
        self.health_state = BrokerHealthState.HEALTHY
        self.total_calls = 0
        self.total_failures = 0
        self.last_success_time: Optional[datetime] = None
        
        logger.info(f"🔌 Circuit breaker initialized for {broker_name}")
        logger.info(f"   Failure threshold: {failure_threshold}")
        logger.info(f"   Recovery timeout: {recovery_timeout}s")
    
    def get_health_state(self) -> BrokerHealthState:
        """Get current broker health state."""
        return self.health_state
    
    def is_trading_allowed(self) -> bool:
        """
        Check if trading is allowed based on broker health.
        
        Returns:
            bool: True if trading allowed, False if broker offline
        """
        return self.health_state != BrokerHealthState.OFFLINE
    
    def _update_health_state(self):
        """Update broker health state based on circuit state and metrics."""
        if self.state == CircuitState.OPEN:
            self.health_state = BrokerHealthState.OFFLINE
        elif self.state == CircuitState.HALF_OPEN:
            self.health_state = BrokerHealthState.DEGRADED
        else:  # CLOSED
            # Check recent failure rate only if we have enough calls
            if self.total_calls >= 10:
                failure_rate = self.total_failures / self.total_calls
                if failure_rate > 0.3:  # More than 30% failures
                    self.health_state = BrokerHealthState.DEGRADED
                else:
                    self.health_state = BrokerHealthState.HEALTHY
            else:
                # Not enough data, default to healthy if circuit is closed
                self.health_state = BrokerHealthState.HEALTHY
    
    def _should_allow_request(self) -> bool:
        """
        Check if request should be allowed based on circuit state.
        
        Returns:
            bool: True if request allowed, False if circuit open
        """
        if self.state == CircuitState.CLOSED:
            return True
        
        if self.state == CircuitState.OPEN:
            # Check if recovery timeout has passed
            if self.last_failure_time:
                time_since_failure = (datetime.now() - self.last_failure_time).total_seconds()
                if time_since_failure >= self.recovery_timeout:
                    logger.info(f"🔄 {self.broker_name}: Circuit entering HALF_OPEN (testing recovery)")
                    self.state = CircuitState.HALF_OPEN
                    self.last_state_change = datetime.now()
                    self._update_health_state()
                    return True
            return False
        
        # HALF_OPEN: Allow limited testing
        return True
    
    def _record_success(self):
        """Record successful API call."""
        self.total_calls += 1
        self.failure_count = 0
        self.last_success_time = datetime.now()
        
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            logger.info(f"✅ {self.broker_name}: Success in HALF_OPEN ({self.success_count}/{self.success_threshold})")
            
            if self.success_count >= self.success_threshold:
                logger.info(f"🟢 {self.broker_name}: Circuit CLOSED (service recovered)")
                self.state = CircuitState.CLOSED
                self.success_count = 0
                self.last_state_change = datetime.now()
                # Reset health to healthy when circuit closes
                self.health_state = BrokerHealthState.HEALTHY
        
        # Update health state for all cases
        self._update_health_state()
    
    def _record_failure(self, error: Exception):
        """Record failed API call."""
        self.total_calls += 1
        self.total_failures += 1
        self.failure_count += 1
        self.last_failure_time = datetime.now()
        
        if self.state == CircuitState.HALF_OPEN:
            logger.warning(f"⚠️ {self.broker_name}: Failure in HALF_OPEN, reopening circuit")
            self.state = CircuitState.OPEN
            self.success_count = 0
            self.last_state_change = datetime.now()
        elif self.state == CircuitState.CLOSED:
            if self.failure_count >= self.failure_threshold:
                logger.error(f"🔴 {self.broker_name}: Circuit OPEN ({self.failure_count} consecutive failures)")
                logger.error(f"   Trading PAUSED for {self.recovery_timeout}s to allow recovery")
                self.state = CircuitState.OPEN
                self.last_state_change = datetime.now()
        
        self._update_health_state()
    
    def call_with_circuit_breaker(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with circuit breaker protection.
        
        Args:
            func: Function to call
            *args: Positional arguments for function
            **kwargs: Keyword arguments for function
        
        Returns:
            Result from function
            
        Raises:
            Exception: If circuit is open or call fails
        """
        # Check if request is allowed
        if not self._should_allow_request():
            time_since_failure = (datetime.now() - self.last_failure_time).total_seconds()
            remaining = self.recovery_timeout - time_since_failure
            raise Exception(
                f"Circuit breaker OPEN for {self.broker_name}. "
                f"Trading paused. Recovery in {remaining:.0f}s"
            )
        
        # Execute function with exponential backoff
        delay = 2.0  # Start with 2s delay
        attempt = 0
        max_attempts = 3
        
        while attempt < max_attempts:
            try:
                result = func(*args, **kwargs)
                self._record_success()
                return result
            
            except Exception as e:
                attempt += 1
                self._record_failure(e)
                
                # Check if we should retry
                if attempt < max_attempts and self._is_retryable_error(str(e)):
                    # Add jitter to prevent thundering herd
                    jitter = random.uniform(0, 0.3 * delay)
                    sleep_time = min(delay + jitter, self.max_retry_delay)
                    
                    logger.warning(
                        f"⚠️ {self.broker_name}: API call failed (attempt {attempt}/{max_attempts}): {e}"
                    )
                    logger.info(f"🔄 Retrying in {sleep_time:.1f}s...")
                    time.sleep(sleep_time)
                    
                    # Exponential backoff
                    delay *= 2
                else:
                    # Max attempts reached or non-retryable error
                    raise
        
        raise Exception(f"Failed after {max_attempts} attempts")
    
    def _is_retryable_error(self, error_msg: str) -> bool:
        """
        Determine if error is retryable.
        
        Args:
            error_msg: Error message string
        
        Returns:
            bool: True if error should be retried
        """
        error_msg_lower = error_msg.lower()
        
        # Retryable errors
        retryable_keywords = [
            'timeout',
            'connection',
            'network',
            'rate limit',
            'too many requests',
            'too many errors',
            'service unavailable',
            '503',
            '504',
            '429',
            'temporary',
            'try again'
        ]
        
        for keyword in retryable_keywords:
            if keyword in error_msg_lower:
                return True
        
        return False
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get circuit breaker status.
        
        Returns:
            dict: Current status information
        """
        uptime = (datetime.now() - self.last_state_change).total_seconds()
        
        return {
            'broker': self.broker_name,
            'health_state': self.health_state.value,
            'circuit_state': self.state.value,
            'failure_count': self.failure_count,
            'total_calls': self.total_calls,
            'total_failures': self.total_failures,
            'failure_rate': self.total_failures / self.total_calls if self.total_calls > 0 else 0.0,
            'last_success': self.last_success_time.isoformat() if self.last_success_time else None,
            'last_failure': self.last_failure_time.isoformat() if self.last_failure_time else None,
            'state_uptime_seconds': uptime,
            'trading_allowed': self.is_trading_allowed()
        }
    
    def reset(self):
        """Reset circuit breaker to initial state."""
        logger.info(f"🔄 {self.broker_name}: Circuit breaker reset")
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.health_state = BrokerHealthState.HEALTHY
        self.last_state_change = datetime.now()


# Global registry of circuit breakers per broker
_circuit_breakers: Dict[str, BrokerCircuitBreaker] = {}


def get_circuit_breaker(broker_name: str, **kwargs) -> BrokerCircuitBreaker:
    """
    Get or create circuit breaker for broker.
    
    Args:
        broker_name: Name of broker
        **kwargs: Additional arguments for BrokerCircuitBreaker constructor
    
    Returns:
        BrokerCircuitBreaker instance
    """
    if broker_name not in _circuit_breakers:
        _circuit_breakers[broker_name] = BrokerCircuitBreaker(broker_name, **kwargs)
    return _circuit_breakers[broker_name]


def circuit_breaker(broker_name: str):
    """
    Decorator for broker API methods to add circuit breaker protection.
    
    Args:
        broker_name: Name of broker for circuit breaker
    
    Usage:
        @circuit_breaker("Coinbase")
        def get_balance(self):
            return self.api.get_balance()
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            breaker = get_circuit_breaker(broker_name)
            return breaker.call_with_circuit_breaker(func, *args, **kwargs)
        return wrapper
    return decorator
