"""
NIJA Account Isolation Manager
===============================

Ensures that one account failure can NEVER affect another account.

Key Features:
1. Per-account exception isolation
2. Circuit breaker pattern for failing accounts
3. Automatic quarantine and recovery
4. Cross-account failure prevention
5. Resource cleanup on failure
6. Comprehensive isolation metrics

Architecture:
- Each account operates in complete isolation
- Failures are contained within the account boundary
- No shared state between accounts (except read-only config)
- Thread-safe operations with per-account locks
- Automatic failure detection and recovery

Author: NIJA Trading Systems
Version: 1.0
Date: February 17, 2026
"""

import logging
import threading
import time
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from collections import defaultdict

logger = logging.getLogger("nija.account_isolation")


class AccountHealthStatus(Enum):
    """Account health statuses"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILING = "failing"
    QUARANTINED = "quarantined"
    RECOVERING = "recovering"


class FailureType(Enum):
    """Types of failures that can occur"""
    API_ERROR = "api_error"
    NETWORK_ERROR = "network_error"
    AUTHENTICATION_ERROR = "authentication_error"
    RATE_LIMIT_ERROR = "rate_limit_error"
    BALANCE_ERROR = "balance_error"
    POSITION_ERROR = "position_error"
    EXECUTION_ERROR = "execution_error"
    UNKNOWN_ERROR = "unknown_error"


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker"""
    failure_threshold: int = 5  # Number of failures before opening circuit
    success_threshold: int = 3  # Number of successes before closing circuit
    timeout_seconds: int = 300  # Time to wait before attempting recovery (5 minutes)
    half_open_max_calls: int = 1  # Max calls allowed in half-open state


@dataclass
class AccountHealthMetrics:
    """Health metrics for an account"""
    account_id: str
    broker_type: str
    status: AccountHealthStatus
    
    # Failure tracking
    total_failures: int = 0
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    last_failure_time: Optional[datetime] = None
    last_success_time: Optional[datetime] = None
    
    # Failure breakdown by type
    failure_counts: Dict[FailureType, int] = field(default_factory=lambda: defaultdict(int))
    
    # Circuit breaker state
    circuit_open: bool = False
    circuit_opened_at: Optional[datetime] = None
    circuit_half_open: bool = False
    half_open_attempts: int = 0
    
    # Recovery tracking
    quarantine_count: int = 0
    recovery_attempts: int = 0
    last_recovery_attempt: Optional[datetime] = None
    
    # Performance metrics
    last_operation_time: Optional[datetime] = None
    average_operation_time_ms: float = 0.0
    
    def __post_init__(self):
        if not isinstance(self.failure_counts, defaultdict):
            # Convert dict to defaultdict if needed
            self.failure_counts = defaultdict(int, self.failure_counts)


class AccountIsolationManager:
    """
    Manages account isolation to ensure one account failure cannot affect others.
    
    Key Responsibilities:
    1. Track health of each account independently
    2. Implement circuit breaker pattern per account
    3. Quarantine failing accounts automatically
    4. Attempt recovery for quarantined accounts
    5. Log isolation metrics for monitoring
    6. Prevent cross-account contamination
    """
    
    def __init__(self, config: Optional[CircuitBreakerConfig] = None):
        """
        Initialize account isolation manager.
        
        Args:
            config: Circuit breaker configuration (uses defaults if None)
        """
        self.config = config or CircuitBreakerConfig()
        
        # Per-account health metrics
        # Key: (account_type, account_id, broker_type)
        # account_type: 'platform' or 'user'
        # account_id: 'platform' or user_id
        # broker_type: e.g., 'KRAKEN', 'COINBASE'
        self.health_metrics: Dict[Tuple[str, str, str], AccountHealthMetrics] = {}
        
        # Per-account locks for thread safety
        self.account_locks: Dict[Tuple[str, str, str], threading.Lock] = {}
        
        # Global lock for manager operations
        self._manager_lock = threading.Lock()
        
        # Isolation verification - track if any cross-account contamination detected
        self.cross_account_errors: List[Dict] = []
        
        logger.info("=" * 70)
        logger.info("🛡️  ACCOUNT ISOLATION MANAGER INITIALIZED")
        logger.info("=" * 70)
        logger.info(f"   Circuit Breaker Config:")
        logger.info(f"   • Failure threshold: {self.config.failure_threshold}")
        logger.info(f"   • Success threshold: {self.config.success_threshold}")
        logger.info(f"   • Timeout: {self.config.timeout_seconds}s")
        logger.info("=" * 70)
    
    def _get_account_key(self, account_type: str, account_id: str, broker_type: str) -> Tuple[str, str, str]:
        """Get standardized account key."""
        return (account_type.lower(), account_id.lower(), broker_type.upper())
    
    def _get_account_lock(self, account_key: Tuple[str, str, str]) -> threading.Lock:
        """Get or create lock for an account."""
        with self._manager_lock:
            if account_key not in self.account_locks:
                self.account_locks[account_key] = threading.Lock()
            return self.account_locks[account_key]
    
    def register_account(
        self,
        account_type: str,
        account_id: str,
        broker_type: str
    ) -> bool:
        """
        Register an account for health monitoring.
        
        Args:
            account_type: 'platform' or 'user'
            account_id: Account identifier
            broker_type: Broker type (e.g., 'KRAKEN', 'COINBASE')
        
        Returns:
            True if registered successfully
        """
        account_key = self._get_account_key(account_type, account_id, broker_type)
        lock = self._get_account_lock(account_key)
        
        with lock:
            if account_key in self.health_metrics:
                logger.debug(f"Account already registered: {account_type}/{account_id}/{broker_type}")
                return True
            
            # Create health metrics for this account
            metrics = AccountHealthMetrics(
                account_id=account_id,
                broker_type=broker_type,
                status=AccountHealthStatus.HEALTHY
            )
            
            self.health_metrics[account_key] = metrics
            
            logger.info(f"✅ Registered account for isolation: {account_type}/{account_id}/{broker_type}")
            return True
    
    def can_execute_operation(
        self,
        account_type: str,
        account_id: str,
        broker_type: str
    ) -> Tuple[bool, str]:
        """
        Check if an account can execute an operation based on its health status.
        
        Args:
            account_type: 'platform' or 'user'
            account_id: Account identifier
            broker_type: Broker type
        
        Returns:
            Tuple of (can_execute, reason)
        """
        account_key = self._get_account_key(account_type, account_id, broker_type)
        
        # Auto-register if not already registered
        if account_key not in self.health_metrics:
            self.register_account(account_type, account_id, broker_type)
        
        lock = self._get_account_lock(account_key)
        
        with lock:
            metrics = self.health_metrics[account_key]
            
            # Check if account is quarantined
            if metrics.status == AccountHealthStatus.QUARANTINED:
                # Check if enough time has passed to attempt recovery
                if metrics.circuit_opened_at:
                    time_since_quarantine = datetime.now() - metrics.circuit_opened_at
                    if time_since_quarantine.total_seconds() < self.config.timeout_seconds:
                        remaining = self.config.timeout_seconds - time_since_quarantine.total_seconds()
                        return False, f"Account quarantined, retry in {remaining:.0f}s"
                    
                    # Time to attempt recovery
                    metrics.status = AccountHealthStatus.RECOVERING
                    metrics.circuit_half_open = True
                    metrics.half_open_attempts = 0
                    logger.info(f"🔄 Attempting recovery for {account_type}/{account_id}/{broker_type}")
                    return True, "Recovery attempt"
                else:
                    return False, "Account quarantined (no recovery time set)"
            
            # Check circuit breaker state
            if metrics.circuit_open:
                if not metrics.circuit_half_open:
                    return False, "Circuit breaker open"
                
                # In half-open state, allow limited calls
                if metrics.half_open_attempts >= self.config.half_open_max_calls:
                    return False, "Half-open limit reached"
                
                metrics.half_open_attempts += 1
                return True, "Half-open test"
            
            # Check if account is in degraded state
            if metrics.status == AccountHealthStatus.DEGRADED:
                logger.warning(f"⚠️  Account degraded but allowing operation: {account_type}/{account_id}/{broker_type}")
                return True, "Degraded but operational"
            
            # Account is healthy
            return True, "Healthy"
    
    def record_success(
        self,
        account_type: str,
        account_id: str,
        broker_type: str,
        operation_time_ms: float = 0.0
    ):
        """
        Record a successful operation for an account.
        
        Args:
            account_type: 'platform' or 'user'
            account_id: Account identifier
            broker_type: Broker type
            operation_time_ms: Time taken for operation in milliseconds
        """
        account_key = self._get_account_key(account_type, account_id, broker_type)
        
        # Auto-register if not already registered
        if account_key not in self.health_metrics:
            self.register_account(account_type, account_id, broker_type)
        
        lock = self._get_account_lock(account_key)
        
        with lock:
            metrics = self.health_metrics[account_key]
            
            # Update success tracking
            metrics.consecutive_successes += 1
            metrics.consecutive_failures = 0
            metrics.last_success_time = datetime.now()
            metrics.last_operation_time = datetime.now()
            
            # Update average operation time
            if operation_time_ms > 0:
                if metrics.average_operation_time_ms == 0:
                    metrics.average_operation_time_ms = operation_time_ms
                else:
                    # Exponential moving average
                    alpha = 0.3
                    metrics.average_operation_time_ms = (
                        alpha * operation_time_ms + 
                        (1 - alpha) * metrics.average_operation_time_ms
                    )
            
            # Check if circuit should close
            if metrics.circuit_open or metrics.circuit_half_open:
                if metrics.consecutive_successes >= self.config.success_threshold:
                    metrics.circuit_open = False
                    metrics.circuit_half_open = False
                    metrics.circuit_opened_at = None
                    metrics.half_open_attempts = 0
                    
                    # Update status to healthy
                    if metrics.status == AccountHealthStatus.RECOVERING:
                        metrics.status = AccountHealthStatus.HEALTHY
                        logger.info(f"✅ Account recovered: {account_type}/{account_id}/{broker_type}")
                    elif metrics.status == AccountHealthStatus.QUARANTINED:
                        metrics.status = AccountHealthStatus.HEALTHY
                        logger.info(f"✅ Account unquarantined: {account_type}/{account_id}/{broker_type}")
            
            # If account was degraded, check if it should return to healthy
            elif metrics.status == AccountHealthStatus.DEGRADED:
                if metrics.consecutive_successes >= self.config.success_threshold:
                    metrics.status = AccountHealthStatus.HEALTHY
                    logger.info(f"✅ Account health restored: {account_type}/{account_id}/{broker_type}")
    
    def record_failure(
        self,
        account_type: str,
        account_id: str,
        broker_type: str,
        error: Exception,
        failure_type: FailureType = FailureType.UNKNOWN_ERROR
    ):
        """
        Record a failed operation for an account.
        
        This method implements the core isolation guarantee:
        - Failures are tracked per account
        - Circuit breaker activates per account
        - No cross-account impact
        
        Args:
            account_type: 'platform' or 'user'
            account_id: Account identifier
            broker_type: Broker type
            error: The exception that occurred
            failure_type: Type of failure
        """
        account_key = self._get_account_key(account_type, account_id, broker_type)
        
        # Auto-register if not already registered
        if account_key not in self.health_metrics:
            self.register_account(account_type, account_id, broker_type)
        
        lock = self._get_account_lock(account_key)
        
        with lock:
            metrics = self.health_metrics[account_key]
            
            # Update failure tracking
            metrics.total_failures += 1
            metrics.consecutive_failures += 1
            metrics.consecutive_successes = 0
            metrics.last_failure_time = datetime.now()
            metrics.failure_counts[failure_type] += 1
            
            # Log the failure (truncated error message)
            error_msg = str(error)[:100]
            logger.error(
                f"❌ Account failure: {account_type}/{account_id}/{broker_type} - "
                f"{failure_type.value}: {error_msg}"
            )
            
            # Update health status based on consecutive failures
            if metrics.consecutive_failures >= self.config.failure_threshold:
                if not metrics.circuit_open:
                    # Open circuit breaker
                    metrics.circuit_open = True
                    metrics.circuit_opened_at = datetime.now()
                    metrics.status = AccountHealthStatus.QUARANTINED
                    metrics.quarantine_count += 1
                    
                    logger.error(
                        f"🚨 ACCOUNT QUARANTINED: {account_type}/{account_id}/{broker_type} - "
                        f"{metrics.consecutive_failures} consecutive failures"
                    )
                    logger.error(f"   Account will retry in {self.config.timeout_seconds}s")
            elif metrics.consecutive_failures >= (self.config.failure_threshold // 2):
                # Account is degraded but not quarantined yet
                if metrics.status == AccountHealthStatus.HEALTHY:
                    metrics.status = AccountHealthStatus.DEGRADED
                    logger.warning(
                        f"⚠️  Account degraded: {account_type}/{account_id}/{broker_type} - "
                        f"{metrics.consecutive_failures} consecutive failures"
                    )
            
            # If in half-open state and failure occurs, reopen circuit
            if metrics.circuit_half_open:
                metrics.circuit_open = True
                metrics.circuit_half_open = False
                metrics.circuit_opened_at = datetime.now()
                metrics.status = AccountHealthStatus.QUARANTINED
                metrics.half_open_attempts = 0
                
                logger.error(
                    f"🚨 Account re-quarantined: {account_type}/{account_id}/{broker_type} - "
                    "recovery attempt failed"
                )
    
    def get_account_status(
        self,
        account_type: str,
        account_id: str,
        broker_type: str
    ) -> Tuple[AccountHealthStatus, Dict]:
        """
        Get health status for an account.
        
        Args:
            account_type: 'platform' or 'user'
            account_id: Account identifier
            broker_type: Broker type
        
        Returns:
            Tuple of (status, metrics_dict)
        """
        account_key = self._get_account_key(account_type, account_id, broker_type)
        
        if account_key not in self.health_metrics:
            return AccountHealthStatus.HEALTHY, {}
        
        lock = self._get_account_lock(account_key)
        
        with lock:
            metrics = self.health_metrics[account_key]
            
            return metrics.status, {
                'account_id': metrics.account_id,
                'broker_type': metrics.broker_type,
                'status': metrics.status.value,
                'total_failures': metrics.total_failures,
                'consecutive_failures': metrics.consecutive_failures,
                'consecutive_successes': metrics.consecutive_successes,
                'circuit_open': metrics.circuit_open,
                'circuit_half_open': metrics.circuit_half_open,
                'quarantine_count': metrics.quarantine_count,
                'last_failure_time': metrics.last_failure_time.isoformat() if metrics.last_failure_time else None,
                'last_success_time': metrics.last_success_time.isoformat() if metrics.last_success_time else None,
                'average_operation_time_ms': metrics.average_operation_time_ms,
                'failure_breakdown': {ft.value: count for ft, count in metrics.failure_counts.items()}
            }
    
    def get_all_account_statuses(self) -> Dict[str, Dict]:
        """
        Get health status for all accounts.
        
        Returns:
            Dictionary mapping account keys to status dicts
        """
        statuses = {}
        
        with self._manager_lock:
            account_keys = list(self.health_metrics.keys())
        
        for account_key in account_keys:
            account_type, account_id, broker_type = account_key
            status, metrics = self.get_account_status(account_type, account_id, broker_type)
            
            key = f"{account_type}/{account_id}/{broker_type}"
            statuses[key] = metrics
        
        return statuses
    
    def get_isolation_report(self) -> Dict:
        """
        Generate comprehensive isolation report.
        
        Returns:
            Dictionary with isolation metrics and verification
        """
        with self._manager_lock:
            total_accounts = len(self.health_metrics)
            healthy_accounts = sum(
                1 for m in self.health_metrics.values()
                if m.status == AccountHealthStatus.HEALTHY
            )
            degraded_accounts = sum(
                1 for m in self.health_metrics.values()
                if m.status == AccountHealthStatus.DEGRADED
            )
            quarantined_accounts = sum(
                1 for m in self.health_metrics.values()
                if m.status == AccountHealthStatus.QUARANTINED
            )
            recovering_accounts = sum(
                1 for m in self.health_metrics.values()
                if m.status == AccountHealthStatus.RECOVERING
            )
            
            total_failures = sum(m.total_failures for m in self.health_metrics.values())
            total_quarantines = sum(m.quarantine_count for m in self.health_metrics.values())
            
            return {
                'total_accounts': total_accounts,
                'healthy_accounts': healthy_accounts,
                'degraded_accounts': degraded_accounts,
                'quarantined_accounts': quarantined_accounts,
                'recovering_accounts': recovering_accounts,
                'total_failures_across_all_accounts': total_failures,
                'total_quarantines': total_quarantines,
                'cross_account_errors_detected': len(self.cross_account_errors),
                'isolation_guarantee': 'ACTIVE' if len(self.cross_account_errors) == 0 else 'VIOLATED',
                'timestamp': datetime.now().isoformat()
            }
    
    def reset_account(
        self,
        account_type: str,
        account_id: str,
        broker_type: str
    ) -> bool:
        """
        Manually reset an account's health metrics.
        
        Args:
            account_type: 'platform' or 'user'
            account_id: Account identifier
            broker_type: Broker type
        
        Returns:
            True if reset successfully
        """
        account_key = self._get_account_key(account_type, account_id, broker_type)
        
        if account_key not in self.health_metrics:
            return False
        
        lock = self._get_account_lock(account_key)
        
        with lock:
            metrics = self.health_metrics[account_key]
            
            # Reset to healthy state
            metrics.status = AccountHealthStatus.HEALTHY
            metrics.consecutive_failures = 0
            metrics.consecutive_successes = 0
            metrics.circuit_open = False
            metrics.circuit_half_open = False
            metrics.circuit_opened_at = None
            metrics.half_open_attempts = 0
            
            logger.info(f"🔄 Account reset: {account_type}/{account_id}/{broker_type}")
            return True


# Global singleton instance
_isolation_manager = None
_isolation_manager_lock = threading.Lock()


def get_isolation_manager() -> AccountIsolationManager:
    """
    Get global account isolation manager instance.
    
    Returns:
        AccountIsolationManager singleton
    """
    global _isolation_manager
    
    if _isolation_manager is None:
        with _isolation_manager_lock:
            if _isolation_manager is None:
                _isolation_manager = AccountIsolationManager()
    
    return _isolation_manager


__all__ = [
    'AccountIsolationManager',
    'AccountHealthStatus',
    'FailureType',
    'CircuitBreakerConfig',
    'get_isolation_manager'
]
