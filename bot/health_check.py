"""
Infrastructure-Grade Health Check System for NIJA

This module provides comprehensive health and readiness endpoints for
Kubernetes and other orchestration platforms. It properly distinguishes
between liveness (is the process alive?) and readiness (can it handle traffic?).

Key Features:
- Liveness probe: Process is running and not deadlocked
- Readiness probe: System is fully configured and ready to trade
- Detailed status information for operators
- Configuration error handling (no crashes on misconfig)
"""

import os
import time
import logging
import json
from datetime import datetime
from enum import Enum
from typing import Dict, Optional, Any
from dataclasses import dataclass, asdict

logger = logging.getLogger("nija.health")


class HealthStatus(Enum):
    """Health status states"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class ReadinessStatus(Enum):
    """Readiness status states"""
    READY = "ready"
    NOT_READY = "not_ready"
    CONFIGURATION_ERROR = "configuration_error"


@dataclass
class HealthState:
    """Represents the current health state of the system"""
    # Liveness fields
    is_alive: bool = True
    last_heartbeat: float = 0.0
    uptime_seconds: float = 0.0
    
    # Readiness fields
    is_ready: bool = False
    readiness_status: str = ReadinessStatus.NOT_READY.value
    configuration_valid: bool = False
    exchanges_connected: int = 0
    expected_exchanges: int = 0
    
    # Operational state
    trading_enabled: bool = False
    last_trade_time: Optional[float] = None
    active_positions: int = 0
    
    # Error tracking
    configuration_errors: list = None
    last_error: Optional[str] = None
    error_count: int = 0
    
    # Metrics tracking
    configuration_error_start_time: Optional[float] = None  # When config error first occurred
    configuration_error_duration_seconds: float = 0.0  # Total time in config error state
    total_ready_time_seconds: float = 0.0  # Total time in ready state
    total_not_ready_time_seconds: float = 0.0  # Total time in not-ready state
    readiness_state_changes: int = 0  # Count of readiness state transitions
    
    def __post_init__(self):
        if self.configuration_errors is None:
            self.configuration_errors = []


class HealthCheckManager:
    """
    Manages health and readiness state for the NIJA trading bot.
    
    This class provides a singleton pattern for centralized health management
    across the application. It tracks both liveness (is process alive?) and
    readiness (can it handle requests?) independently.
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self._initialized = True
        self.state = HealthState()
        self.state.last_heartbeat = time.time()
        self._start_time = time.time()
        self._configuration_checked = False
        self._last_readiness_state = None  # Track previous readiness state for transitions
        self._last_state_change_time = time.time()  # Track when state last changed
        
        logger.info("Health check manager initialized")
    
    def heartbeat(self):
        """Update liveness heartbeat and metrics - call this regularly from main loop"""
        current_time = time.time()
        self.state.last_heartbeat = current_time
        self.state.uptime_seconds = current_time - self._start_time
        self.state.is_alive = True
        
        # Update duration metrics based on current state
        time_since_last_update = current_time - self._last_state_change_time
        
        if self.state.readiness_status == ReadinessStatus.CONFIGURATION_ERROR.value:
            # Update configuration error duration
            if self.state.configuration_error_start_time is None:
                self.state.configuration_error_start_time = current_time
            self.state.configuration_error_duration_seconds = (
                current_time - self.state.configuration_error_start_time
            )
        elif self.state.is_ready:
            self.state.total_ready_time_seconds += time_since_last_update
        else:
            self.state.total_not_ready_time_seconds += time_since_last_update
        
        self._last_state_change_time = current_time
    
    def mark_configuration_error(self, error_message: str):
        """
        Mark a configuration error.
        
        This sets readiness to CONFIGURATION_ERROR and prevents the service
        from being considered ready. Container orchestrators will receive
        proper signals to not restart the container.
        
        Args:
            error_message: Description of the configuration error
        """
        # Track state change
        previous_state = self.state.readiness_status
        
        self.state.configuration_valid = False
        self.state.readiness_status = ReadinessStatus.CONFIGURATION_ERROR.value
        self.state.is_ready = False
        self.state.last_error = error_message
        self.state.error_count += 1
        
        # Start tracking configuration error duration
        if self.state.configuration_error_start_time is None:
            self.state.configuration_error_start_time = time.time()
        
        if error_message not in self.state.configuration_errors:
            self.state.configuration_errors.append(error_message)
        
        # Track state transition
        if previous_state != ReadinessStatus.CONFIGURATION_ERROR.value:
            self.state.readiness_state_changes += 1
            logger.error(f"Configuration error marked (transition #{self.state.readiness_state_changes}): {error_message}")
        else:
            logger.error(f"Configuration error marked: {error_message}")
    
    def mark_configuration_valid(self):
        """Mark configuration as valid"""
        previous_state = self.state.readiness_status
        
        self.state.configuration_valid = True
        self._configuration_checked = True
        
        # Clear configuration error tracking if we're resolving it
        if self.state.configuration_error_start_time is not None:
            # Record final duration before clearing
            final_duration = time.time() - self.state.configuration_error_start_time
            logger.info(f"Configuration error resolved after {final_duration:.1f} seconds")
            self.state.configuration_error_start_time = None
        
        # Track state transition if status changed
        if previous_state == ReadinessStatus.CONFIGURATION_ERROR.value:
            self.state.readiness_state_changes += 1
        
        logger.info("Configuration marked as valid")
    
    def update_exchange_status(self, connected: int, expected: int):
        """
        Update the status of exchange connections.
        
        Args:
            connected: Number of exchanges successfully connected
            expected: Number of exchanges expected to connect
        """
        self.state.exchanges_connected = connected
        self.state.expected_exchanges = expected
        
        # Update readiness based on exchange connectivity
        if self.state.configuration_valid:
            if connected > 0:
                self.state.is_ready = True
                self.state.readiness_status = ReadinessStatus.READY.value
            else:
                self.state.is_ready = False
                self.state.readiness_status = ReadinessStatus.NOT_READY.value
        
        logger.info(f"Exchange status updated: {connected}/{expected} connected")
    
    def update_trading_status(self, enabled: bool, active_positions: int = 0):
        """
        Update trading status.
        
        Args:
            enabled: Whether trading is currently enabled
            active_positions: Number of active trading positions
        """
        self.state.trading_enabled = enabled
        self.state.active_positions = active_positions
        
        if enabled:
            self.state.last_trade_time = time.time()
    
    def get_liveness_status(self) -> Dict[str, Any]:
        """
        Get liveness probe status.
        
        Liveness indicates if the process is alive and not deadlocked.
        This should return 200 OK as long as the process is running.
        
        Returns:
            dict: Liveness status information
        """
        self.heartbeat()  # Update heartbeat when checked
        
        return {
            "status": "alive",
            "uptime_seconds": self.state.uptime_seconds,
            "last_heartbeat": datetime.fromtimestamp(self.state.last_heartbeat).isoformat(),
            "timestamp": datetime.utcnow().isoformat()
        }
    
    def get_readiness_status(self) -> tuple[Dict[str, Any], int]:
        """
        Get readiness probe status.
        
        Readiness indicates if the service is ready to handle requests/trades.
        Returns 200 OK only if the service is properly configured and ready.
        Returns 503 Service Unavailable for configuration errors or not ready.
        
        Returns:
            tuple: (status_dict, http_status_code)
        """
        # Determine HTTP status code
        if self.state.readiness_status == ReadinessStatus.CONFIGURATION_ERROR.value:
            # Configuration errors should return 503 but NOT cause restarts
            # The orchestrator should know we're not ready due to config
            http_status = 503
        elif self.state.is_ready:
            http_status = 200
        else:
            http_status = 503
        
        status = {
            "status": self.state.readiness_status,
            "ready": self.state.is_ready,
            "configuration_valid": self.state.configuration_valid,
            "exchanges": {
                "connected": self.state.exchanges_connected,
                "expected": self.state.expected_exchanges
            },
            "trading": {
                "enabled": self.state.trading_enabled,
                "active_positions": self.state.active_positions,
                "last_trade": datetime.fromtimestamp(self.state.last_trade_time).isoformat() if self.state.last_trade_time else None
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Add error information if present
        if self.state.configuration_errors:
            status["configuration_errors"] = self.state.configuration_errors
        
        if self.state.last_error:
            status["last_error"] = self.state.last_error
        
        return status, http_status
    
    def get_detailed_status(self) -> Dict[str, Any]:
        """
        Get comprehensive status for debugging and monitoring.
        
        This combines liveness and readiness information plus additional
        operational details for operators to understand system state.
        
        Returns:
            dict: Detailed status information
        """
        liveness = self.get_liveness_status()
        readiness, _ = self.get_readiness_status()
        
        return {
            "service": "NIJA Trading Bot",
            "version": "7.2.0",
            "liveness": liveness,
            "readiness": readiness,
            "operational_state": {
                "configuration_checked": self._configuration_checked,
                "error_count": self.state.error_count,
                "uptime_seconds": self.state.uptime_seconds
            }
        }
    
    def get_prometheus_metrics(self) -> str:
        """
        Get Prometheus-compatible metrics.
        
        Returns metrics in Prometheus text format for scraping.
        Includes:
        - Health state metrics
        - Configuration error duration
        - Readiness state durations
        - State transition counts
        
        Returns:
            str: Prometheus-formatted metrics
        """
        metrics = []
        
        # Liveness metric
        metrics.append('# HELP nija_up Service is up and running')
        metrics.append('# TYPE nija_up gauge')
        metrics.append(f'nija_up {1 if self.state.is_alive else 0}')
        
        # Readiness metric
        metrics.append('# HELP nija_ready Service is ready to handle traffic')
        metrics.append('# TYPE nija_ready gauge')
        metrics.append(f'nija_ready {1 if self.state.is_ready else 0}')
        
        # Configuration valid metric
        metrics.append('# HELP nija_configuration_valid Configuration is valid')
        metrics.append('# TYPE nija_configuration_valid gauge')
        metrics.append(f'nija_configuration_valid {1 if self.state.configuration_valid else 0}')
        
        # Configuration error duration (critical SLO metric)
        metrics.append('# HELP nija_configuration_error_duration_seconds Time spent in configuration error state')
        metrics.append('# TYPE nija_configuration_error_duration_seconds gauge')
        metrics.append(f'nija_configuration_error_duration_seconds {self.state.configuration_error_duration_seconds}')
        
        # Uptime
        metrics.append('# HELP nija_uptime_seconds Service uptime in seconds')
        metrics.append('# TYPE nija_uptime_seconds gauge')
        metrics.append(f'nija_uptime_seconds {self.state.uptime_seconds}')
        
        # Ready time
        metrics.append('# HELP nija_ready_time_seconds Total time service has been ready')
        metrics.append('# TYPE nija_ready_time_seconds counter')
        metrics.append(f'nija_ready_time_seconds {self.state.total_ready_time_seconds}')
        
        # Not ready time
        metrics.append('# HELP nija_not_ready_time_seconds Total time service has been not ready')
        metrics.append('# TYPE nija_not_ready_time_seconds counter')
        metrics.append(f'nija_not_ready_time_seconds {self.state.total_not_ready_time_seconds}')
        
        # State changes (for tracking flapping)
        metrics.append('# HELP nija_readiness_state_changes_total Number of readiness state transitions')
        metrics.append('# TYPE nija_readiness_state_changes_total counter')
        metrics.append(f'nija_readiness_state_changes_total {self.state.readiness_state_changes}')
        
        # Exchange connectivity
        metrics.append('# HELP nija_exchanges_connected Number of exchanges connected')
        metrics.append('# TYPE nija_exchanges_connected gauge')
        metrics.append(f'nija_exchanges_connected {self.state.exchanges_connected}')
        
        metrics.append('# HELP nija_exchanges_expected Number of exchanges expected to connect')
        metrics.append('# TYPE nija_exchanges_expected gauge')
        metrics.append(f'nija_exchanges_expected {self.state.expected_exchanges}')
        
        # Trading status
        metrics.append('# HELP nija_trading_enabled Trading is enabled')
        metrics.append('# TYPE nija_trading_enabled gauge')
        metrics.append(f'nija_trading_enabled {1 if self.state.trading_enabled else 0}')
        
        metrics.append('# HELP nija_active_positions Number of active trading positions')
        metrics.append('# TYPE nija_active_positions gauge')
        metrics.append(f'nija_active_positions {self.state.active_positions}')
        
        # Error count
        metrics.append('# HELP nija_error_count_total Total number of errors encountered')
        metrics.append('# TYPE nija_error_count_total counter')
        metrics.append(f'nija_error_count_total {self.state.error_count}')
        
        return '\n'.join(metrics) + '\n'


# Singleton accessor
_health_manager = None


def get_health_manager() -> HealthCheckManager:
    """Get the global health check manager instance"""
    global _health_manager
    if _health_manager is None:
        _health_manager = HealthCheckManager()
    return _health_manager
