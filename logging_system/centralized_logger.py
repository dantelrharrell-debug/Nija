"""
NIJA Centralized Logging System

Structured logging with correlation IDs, log aggregation, and query capabilities.

Features:
- Structured JSON logging
- Correlation ID tracking for request tracing
- Log level filtering
- Log rotation and retention
- Query API for log retrieval
- Integration with monitoring dashboard

Author: NIJA Trading Systems
Version: 1.0
Date: January 27, 2026
"""

import logging
import json
import os
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from pathlib import Path
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from dataclasses import dataclass, asdict
import threading
from collections import deque

# Thread-local storage for correlation IDs
_thread_local = threading.local()


@dataclass
class LogEntry:
    """Structured log entry"""
    timestamp: str
    level: str
    logger_name: str
    message: str
    correlation_id: Optional[str] = None
    user_id: Optional[str] = None
    account_id: Optional[str] = None
    module: Optional[str] = None
    function: Optional[str] = None
    line_number: Optional[int] = None
    extra: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return asdict(self)

    def to_json(self) -> str:
        """Convert to JSON string"""
        return json.dumps(self.to_dict())


class StructuredFormatter(logging.Formatter):
    """JSON formatter for structured logging"""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON"""
        # Get correlation ID from thread-local storage
        correlation_id = getattr(_thread_local, 'correlation_id', None)
        user_id = getattr(_thread_local, 'user_id', None)
        account_id = getattr(_thread_local, 'account_id', None)

        # Build log entry
        log_entry = LogEntry(
            timestamp=datetime.utcnow().isoformat() + 'Z',
            level=record.levelname,
            logger_name=record.name,
            message=record.getMessage(),
            correlation_id=correlation_id,
            user_id=user_id,
            account_id=account_id,
            module=record.module,
            function=record.funcName,
            line_number=record.lineno,
            extra=getattr(record, 'extra', None)
        )

        return log_entry.to_json()


class LogAggregator:
    """In-memory log aggregator for recent logs"""

    def __init__(self, max_entries: int = 10000):
        """
        Initialize log aggregator

        Args:
            max_entries: Maximum number of log entries to keep in memory
        """
        self.max_entries = max_entries
        self._logs = deque(maxlen=max_entries)
        self._lock = threading.Lock()

    def add_log(self, log_entry: LogEntry) -> None:
        """Add log entry to aggregator"""
        with self._lock:
            self._logs.append(log_entry)

    def query_logs(
        self,
        level: Optional[str] = None,
        logger_name: Optional[str] = None,
        correlation_id: Optional[str] = None,
        user_id: Optional[str] = None,
        account_id: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 100
    ) -> List[LogEntry]:
        """
        Query logs with filters

        Args:
            level: Filter by log level
            logger_name: Filter by logger name
            correlation_id: Filter by correlation ID
            user_id: Filter by user ID
            account_id: Filter by account ID
            since: Filter logs since this timestamp
            limit: Maximum number of results

        Returns:
            List of matching log entries
        """
        with self._lock:
            results = []

            for log_entry in reversed(self._logs):
                # Apply filters
                if level and log_entry.level != level:
                    continue
                if logger_name and log_entry.logger_name != logger_name:
                    continue
                if correlation_id and log_entry.correlation_id != correlation_id:
                    continue
                if user_id and log_entry.user_id != user_id:
                    continue
                if account_id and log_entry.account_id != account_id:
                    continue
                if since:
                    try:
                        log_time = datetime.fromisoformat(log_entry.timestamp.replace('Z', ''))
                        # Make since timezone-naive for comparison
                        if log_time < since.replace(tzinfo=None):
                            continue
                    except:
                        # Skip if timestamp parsing fails
                        continue

                results.append(log_entry)

                if len(results) >= limit:
                    break

            return results

    def get_recent_logs(self, count: int = 100) -> List[LogEntry]:
        """Get most recent log entries"""
        with self._lock:
            return list(reversed(self._logs))[:count]

    def clear(self) -> None:
        """Clear all logs"""
        with self._lock:
            self._logs.clear()


class AggregatorHandler(logging.Handler):
    """Logging handler that sends logs to aggregator"""

    def __init__(self, aggregator: LogAggregator):
        super().__init__()
        self.aggregator = aggregator

    def emit(self, record: logging.LogRecord) -> None:
        """Emit log record to aggregator"""
        try:
            # Parse JSON log entry
            msg = self.format(record)
            log_data = json.loads(msg)

            # Create LogEntry object
            log_entry = LogEntry(**log_data)

            # Add to aggregator
            self.aggregator.add_log(log_entry)

        except (json.JSONDecodeError, TypeError, ValueError) as e:
            self.handleError(record)


# Global log aggregator
_global_aggregator: Optional[LogAggregator] = None
_aggregator_lock = threading.Lock()


def get_log_aggregator() -> LogAggregator:
    """Get or create global log aggregator"""
    global _global_aggregator

    with _aggregator_lock:
        if _global_aggregator is None:
            _global_aggregator = LogAggregator(max_entries=10000)
        return _global_aggregator


def setup_centralized_logging(
    log_dir: str = "logs",
    log_level: str = "INFO",
    enable_console: bool = True,
    enable_file: bool = True,
    enable_aggregator: bool = True,
    max_file_size: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 10,
    rotation_when: str = "midnight",
    rotation_interval: int = 1
) -> None:
    """
    Setup centralized logging system

    Args:
        log_dir: Directory for log files
        log_level: Minimum log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        enable_console: Enable console logging
        enable_file: Enable file logging
        enable_aggregator: Enable in-memory log aggregation
        max_file_size: Maximum log file size before rotation
        backup_count: Number of backup files to keep
        rotation_when: When to rotate logs ('midnight', 'H', 'D', etc.)
        rotation_interval: Rotation interval
    """
    # Create log directory
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # Remove existing handlers
    root_logger.handlers.clear()

    # Create formatter
    formatter = StructuredFormatter()

    # Console handler
    if enable_console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    # File handlers
    if enable_file:
        # Main log file with size-based rotation
        main_log_file = log_path / "nija.log"
        file_handler = RotatingFileHandler(
            main_log_file,
            maxBytes=max_file_size,
            backupCount=backup_count
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

        # Error log file (errors only)
        error_log_file = log_path / "nija_errors.log"
        error_handler = RotatingFileHandler(
            error_log_file,
            maxBytes=max_file_size,
            backupCount=backup_count
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(formatter)
        root_logger.addHandler(error_handler)

        # Time-based rotation (daily)
        daily_log_file = log_path / "nija_daily.log"
        daily_handler = TimedRotatingFileHandler(
            daily_log_file,
            when=rotation_when,
            interval=rotation_interval,
            backupCount=backup_count
        )
        daily_handler.setFormatter(formatter)
        root_logger.addHandler(daily_handler)

    # Aggregator handler
    if enable_aggregator:
        aggregator = get_log_aggregator()
        aggregator_handler = AggregatorHandler(aggregator)
        aggregator_handler.setFormatter(formatter)
        root_logger.addHandler(aggregator_handler)

    logging.info("✅ Centralized logging system initialized")
    logging.info(f"   Log directory: {log_path.absolute()}")
    logging.info(f"   Log level: {log_level}")
    logging.info(f"   Console logging: {enable_console}")
    logging.info(f"   File logging: {enable_file}")
    logging.info(f"   Log aggregation: {enable_aggregator}")


def set_correlation_id(correlation_id: Optional[str] = None) -> str:
    """
    Set correlation ID for current thread

    Args:
        correlation_id: Correlation ID (generates new UUID if None)

    Returns:
        Correlation ID
    """
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())

    _thread_local.correlation_id = correlation_id
    return correlation_id


def get_correlation_id() -> Optional[str]:
    """Get correlation ID for current thread"""
    return getattr(_thread_local, 'correlation_id', None)


def clear_correlation_id() -> None:
    """Clear correlation ID for current thread"""
    if hasattr(_thread_local, 'correlation_id'):
        delattr(_thread_local, 'correlation_id')


def set_user_context(user_id: Optional[str] = None,
                     account_id: Optional[str] = None) -> None:
    """
    Set user context for logging

    Args:
        user_id: User identifier
        account_id: Account identifier
    """
    if user_id:
        _thread_local.user_id = user_id
    if account_id:
        _thread_local.account_id = account_id


def clear_user_context() -> None:
    """Clear user context"""
    if hasattr(_thread_local, 'user_id'):
        delattr(_thread_local, 'user_id')
    if hasattr(_thread_local, 'account_id'):
        delattr(_thread_local, 'account_id')


def log_with_context(logger: logging.Logger, level: str, message: str,
                    extra: Optional[Dict[str, Any]] = None,
                    **kwargs) -> None:
    """
    Log message with additional context

    Args:
        logger: Logger instance
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        message: Log message
        extra: Extra data to include in log
        **kwargs: Additional context (user_id, account_id, etc.)
    """
    # Set context from kwargs
    if 'user_id' in kwargs:
        set_user_context(user_id=kwargs['user_id'])
    if 'account_id' in kwargs:
        set_user_context(account_id=kwargs['account_id'])
    if 'correlation_id' in kwargs:
        set_correlation_id(kwargs['correlation_id'])

    # Create log record with extra data
    log_method = getattr(logger, level.lower())
    log_method(message, extra={'extra': extra} if extra else None)


def query_logs(
    level: Optional[str] = None,
    logger_name: Optional[str] = None,
    correlation_id: Optional[str] = None,
    user_id: Optional[str] = None,
    account_id: Optional[str] = None,
    hours: int = 24,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """
    Query logs from aggregator

    Args:
        level: Filter by log level
        logger_name: Filter by logger name
        correlation_id: Filter by correlation ID
        user_id: Filter by user ID
        account_id: Filter by account ID
        hours: Hours to look back
        limit: Maximum results

    Returns:
        List of log entries as dictionaries
    """
    aggregator = get_log_aggregator()
    since = datetime.utcnow() - timedelta(hours=hours)

    logs = aggregator.query_logs(
        level=level,
        logger_name=logger_name,
        correlation_id=correlation_id,
        user_id=user_id,
        account_id=account_id,
        since=since,
        limit=limit
    )

    return [log.to_dict() for log in logs]


def get_recent_logs(count: int = 100) -> List[Dict[str, Any]]:
    """
    Get recent log entries

    Args:
        count: Number of logs to retrieve

    Returns:
        List of log entries as dictionaries
    """
    aggregator = get_log_aggregator()
    logs = aggregator.get_recent_logs(count=count)
    return [log.to_dict() for log in logs]
