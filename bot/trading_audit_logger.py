"""
NIJA Audit Logger System
=========================

Implements tamper-evident, audit-proof logging for all critical trading operations.
Logs are structured, timestamped, and include cryptographic checksums for integrity.

Audit Log Features:
- Standardized JSON format
- Cryptographic checksums (SHA-256)
- Immutable append-only log
- Trade lifecycle tracking (entry → exits → final P&L)
- Position limit validations
- Profit proven milestone tracking
- Risk control decisions

Log files are designed to be:
1. Machine-readable (structured JSON)
2. Tamper-evident (checksums)
3. Audit-compliant (complete trail)
4. Queryable (indexed by trade_id, timestamp, event_type)

Author: NIJA Trading Systems
Version: 1.0
Date: February 6, 2026
"""

import logging
import json
import hashlib
from typing import Dict, Optional, Any, List
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, asdict, field
from enum import Enum
import threading

logger = logging.getLogger("nija.audit_logger")


class AuditEventType(Enum):
    """Types of auditable events"""
    # Trade lifecycle events
    TRADE_ENTRY = "trade_entry"
    TRADE_PARTIAL_EXIT = "trade_partial_exit"
    TRADE_FULL_EXIT = "trade_full_exit"
    TRADE_STOP_LOSS = "trade_stop_loss"
    TRADE_TAKE_PROFIT = "trade_take_profit"
    
    # Position and risk events
    POSITION_SIZE_VALIDATION = "position_size_validation"
    POSITION_SIZE_REJECTED = "position_size_rejected"
    POSITION_LIMIT_ENFORCED = "position_limit_enforced"
    MAX_POSITION_OVERRIDE_BLOCKED = "max_position_override_blocked"
    
    # Profit proven events
    PROFIT_PROVEN_CHECK = "profit_proven_check"
    PROFIT_PROVEN_ACHIEVED = "profit_proven_achieved"
    PROFIT_PROVEN_FAILED = "profit_proven_failed"
    
    # Risk control events
    KILL_SWITCH_TRIGGERED = "kill_switch_triggered"
    KILL_SWITCH_RESET = "kill_switch_reset"
    DAILY_LOSS_LIMIT_HIT = "daily_loss_limit_hit"
    DAILY_TRADE_LIMIT_HIT = "daily_trade_limit_hit"
    
    # System events
    TRADING_SESSION_START = "trading_session_start"
    TRADING_SESSION_END = "trading_session_end"
    EMERGENCY_SHUTDOWN = "emergency_shutdown"


@dataclass
class AuditLogEntry:
    """
    Standardized audit log entry.
    
    Every audit event follows this exact format for consistency and auditability.
    """
    # Core metadata
    event_id: str  # Unique event ID
    event_type: str  # AuditEventType value
    timestamp: str  # ISO 8601 format with milliseconds
    
    # User/account context
    user_id: str
    account_id: Optional[str] = None
    broker: Optional[str] = None
    
    # Trade context (if applicable)
    trade_id: Optional[str] = None
    symbol: Optional[str] = None
    
    # Event data
    event_data: Dict[str, Any] = field(default_factory=dict)
    
    # Validation/risk data
    validation_result: Optional[bool] = None
    validation_reason: Optional[str] = None
    
    # Financial data
    amount_usd: Optional[float] = None
    position_size_usd: Optional[float] = None
    account_balance_usd: Optional[float] = None
    
    # Checksum for tamper detection
    checksum: Optional[str] = None
    
    def calculate_checksum(self) -> str:
        """
        Calculate SHA-256 checksum of entry data.
        
        Returns:
            Hex-encoded SHA-256 hash
        """
        # Create deterministic representation
        data = {
            'event_id': self.event_id,
            'event_type': self.event_type,
            'timestamp': self.timestamp,
            'user_id': self.user_id,
            'account_id': self.account_id,
            'broker': self.broker,
            'trade_id': self.trade_id,
            'symbol': self.symbol,
            'event_data': self.event_data,
            'validation_result': self.validation_result,
            'validation_reason': self.validation_reason,
            'amount_usd': self.amount_usd,
            'position_size_usd': self.position_size_usd,
            'account_balance_usd': self.account_balance_usd,
        }
        
        # Convert to canonical JSON string
        json_str = json.dumps(data, sort_keys=True, ensure_ascii=True)
        
        # Calculate SHA-256 hash
        hash_obj = hashlib.sha256(json_str.encode('utf-8'))
        return hash_obj.hexdigest()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return asdict(self)
    
    def to_json(self) -> str:
        """Convert to JSON string"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
    
    def verify_checksum(self) -> bool:
        """
        Verify entry checksum.
        
        Returns:
            True if checksum is valid
        """
        if self.checksum is None:
            return False
        
        expected = self.calculate_checksum()
        return self.checksum == expected


class AuditLogger:
    """
    Manages audit logging with tamper-evident records.
    
    Writes append-only log files with cryptographic checksums.
    Each log entry is self-contained and verifiable.
    """
    
    def __init__(self, log_dir: str = "./data/audit_logs"):
        """
        Initialize audit logger.
        
        Args:
            log_dir: Directory for audit log files
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Separate log files by event category
        self.trade_log_file = self.log_dir / "trades.jsonl"
        self.position_log_file = self.log_dir / "positions.jsonl"
        self.profit_proven_log_file = self.log_dir / "profit_proven.jsonl"
        self.risk_control_log_file = self.log_dir / "risk_control.jsonl"
        self.system_log_file = self.log_dir / "system.jsonl"
        
        # Thread safety
        self._lock = threading.Lock()
        
        # Event counter for unique IDs
        self._event_counter = 0
        
        logger.info("✅ Audit Logger initialized")
        logger.info(f"   Log directory: {self.log_dir.absolute()}")
    
    def _get_log_file(self, event_type: AuditEventType) -> Path:
        """Get appropriate log file for event type"""
        if event_type.value.startswith("trade_"):
            return self.trade_log_file
        elif event_type.value.startswith("position_"):
            return self.position_log_file
        elif event_type.value.startswith("profit_proven_"):
            return self.profit_proven_log_file
        elif event_type.value in ["kill_switch_triggered", "kill_switch_reset",
                                    "daily_loss_limit_hit", "daily_trade_limit_hit"]:
            return self.risk_control_log_file
        else:
            return self.system_log_file
    
    def _generate_event_id(self) -> str:
        """Generate unique event ID"""
        with self._lock:
            self._event_counter += 1
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
            return f"AE-{timestamp}-{self._event_counter:06d}"
    
    def log_event(
        self,
        event_type: AuditEventType,
        user_id: str,
        event_data: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> AuditLogEntry:
        """
        Log an audit event.
        
        Args:
            event_type: Type of event
            user_id: User identifier
            event_data: Event-specific data
            **kwargs: Additional fields (trade_id, symbol, account_id, etc.)
        
        Returns:
            Created audit log entry
        """
        # Create entry
        entry = AuditLogEntry(
            event_id=self._generate_event_id(),
            event_type=event_type.value,
            timestamp=datetime.now().isoformat() + 'Z',
            user_id=user_id,
            event_data=event_data or {},
            **kwargs
        )
        
        # Calculate and set checksum
        entry.checksum = entry.calculate_checksum()
        
        # Write to appropriate log file
        log_file = self._get_log_file(event_type)
        
        with self._lock:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(entry.to_json() + '\n')
        
        # Also log to standard logger for immediate visibility
        logger.info(f"AUDIT [{event_type.value}] {user_id}: {entry.event_id}")
        
        return entry
    
    def log_trade_entry(
        self,
        user_id: str,
        trade_id: str,
        symbol: str,
        side: str,
        entry_price: float,
        position_size_usd: float,
        stop_loss: float,
        take_profit: float,
        account_balance_usd: float,
        broker: str,
        **extra_data
    ) -> AuditLogEntry:
        """
        Log trade entry event.
        
        Args:
            user_id: User identifier
            trade_id: Trade identifier
            symbol: Trading symbol
            side: 'long' or 'short'
            entry_price: Entry price
            position_size_usd: Position size in USD
            stop_loss: Stop loss price
            take_profit: Take profit price
            account_balance_usd: Account balance at entry
            broker: Broker name
            **extra_data: Additional event data
        
        Returns:
            Audit log entry
        """
        event_data = {
            'side': side,
            'entry_price': entry_price,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            **extra_data
        }
        
        return self.log_event(
            AuditEventType.TRADE_ENTRY,
            user_id=user_id,
            trade_id=trade_id,
            symbol=symbol,
            broker=broker,
            position_size_usd=position_size_usd,
            account_balance_usd=account_balance_usd,
            event_data=event_data
        )
    
    def log_trade_exit(
        self,
        user_id: str,
        trade_id: str,
        symbol: str,
        exit_type: str,  # 'partial', 'full', 'stop_loss', 'take_profit'
        exit_price: float,
        exit_size_pct: float,
        gross_pnl_usd: float,
        fees_usd: float,
        net_pnl_usd: float,
        account_balance_usd: float,
        exit_reason: str,
        **extra_data
    ) -> AuditLogEntry:
        """
        Log trade exit event.
        
        Args:
            user_id: User identifier
            trade_id: Trade identifier
            symbol: Trading symbol
            exit_type: Type of exit
            exit_price: Exit price
            exit_size_pct: Percentage of position exited
            gross_pnl_usd: Gross P&L
            fees_usd: Trading fees
            net_pnl_usd: Net P&L after fees
            account_balance_usd: Account balance after exit
            exit_reason: Reason for exit
            **extra_data: Additional event data
        
        Returns:
            Audit log entry
        """
        event_data = {
            'exit_price': exit_price,
            'exit_size_pct': exit_size_pct,
            'gross_pnl_usd': gross_pnl_usd,
            'fees_usd': fees_usd,
            'exit_reason': exit_reason,
            **extra_data
        }
        
        # Select appropriate event type
        if exit_type == 'stop_loss':
            event_type = AuditEventType.TRADE_STOP_LOSS
        elif exit_type == 'take_profit':
            event_type = AuditEventType.TRADE_TAKE_PROFIT
        elif exit_type == 'partial':
            event_type = AuditEventType.TRADE_PARTIAL_EXIT
        else:
            event_type = AuditEventType.TRADE_FULL_EXIT
        
        return self.log_event(
            event_type,
            user_id=user_id,
            trade_id=trade_id,
            symbol=symbol,
            amount_usd=net_pnl_usd,
            account_balance_usd=account_balance_usd,
            event_data=event_data
        )
    
    def log_position_validation(
        self,
        user_id: str,
        symbol: str,
        requested_size_usd: float,
        account_balance_usd: float,
        is_approved: bool,
        rejection_reason: Optional[str] = None,
        enforced_limit: Optional[str] = None,
        **extra_data
    ) -> AuditLogEntry:
        """
        Log position size validation.
        
        Args:
            user_id: User identifier
            symbol: Trading symbol
            requested_size_usd: Requested position size
            account_balance_usd: Account balance
            is_approved: Whether validation passed
            rejection_reason: Reason if rejected
            enforced_limit: Which limit was enforced
            **extra_data: Additional event data
        
        Returns:
            Audit log entry
        """
        event_data = {
            'requested_size_usd': requested_size_usd,
            'requested_size_pct': (requested_size_usd / account_balance_usd * 100) if account_balance_usd > 0 else 0,
            'enforced_limit': enforced_limit,
            **extra_data
        }
        
        event_type = (AuditEventType.POSITION_SIZE_VALIDATION if is_approved
                     else AuditEventType.POSITION_SIZE_REJECTED)
        
        return self.log_event(
            event_type,
            user_id=user_id,
            symbol=symbol,
            position_size_usd=requested_size_usd,
            account_balance_usd=account_balance_usd,
            validation_result=is_approved,
            validation_reason=rejection_reason,
            event_data=event_data
        )
    
    def log_profit_proven_check(
        self,
        user_id: str,
        is_proven: bool,
        metrics: Dict[str, Any],
        criteria: Dict[str, Any],
        **extra_data
    ) -> AuditLogEntry:
        """
        Log profit proven status check.
        
        Args:
            user_id: User identifier
            is_proven: Whether profit proven status achieved
            metrics: Performance metrics
            criteria: Profit proven criteria
            **extra_data: Additional event data
        
        Returns:
            Audit log entry
        """
        event_data = {
            'metrics': metrics,
            'criteria': criteria,
            **extra_data
        }
        
        if is_proven:
            event_type = AuditEventType.PROFIT_PROVEN_ACHIEVED
        elif metrics.get('status') == 'failed':
            event_type = AuditEventType.PROFIT_PROVEN_FAILED
        else:
            event_type = AuditEventType.PROFIT_PROVEN_CHECK
        
        return self.log_event(
            event_type,
            user_id=user_id,
            validation_result=is_proven,
            event_data=event_data
        )
    
    def query_events(
        self,
        event_type: Optional[AuditEventType] = None,
        user_id: Optional[str] = None,
        trade_id: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 100
    ) -> List[AuditLogEntry]:
        """
        Query audit events.
        
        Args:
            event_type: Filter by event type
            user_id: Filter by user ID
            trade_id: Filter by trade ID
            since: Filter by timestamp
            limit: Maximum results
        
        Returns:
            List of matching audit log entries
        """
        results = []
        
        # Determine which log files to search
        if event_type:
            log_files = [self._get_log_file(event_type)]
        else:
            log_files = [
                self.trade_log_file,
                self.position_log_file,
                self.profit_proven_log_file,
                self.risk_control_log_file,
                self.system_log_file,
            ]
        
        # Search log files
        for log_file in log_files:
            if not log_file.exists():
                continue
            
            with open(log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        entry_dict = json.loads(line)
                        entry = AuditLogEntry(**entry_dict)
                        
                        # Apply filters
                        if event_type and entry.event_type != event_type.value:
                            continue
                        if user_id and entry.user_id != user_id:
                            continue
                        if trade_id and entry.trade_id != trade_id:
                            continue
                        if since:
                            entry_time = datetime.fromisoformat(entry.timestamp.replace('Z', ''))
                            if entry_time < since:
                                continue
                        
                        results.append(entry)
                        
                        if len(results) >= limit:
                            return results
                    
                    except (json.JSONDecodeError, TypeError):
                        logger.warning(f"Failed to parse audit log entry in {log_file}")
                        continue
        
        return results


# Global audit logger instance
_global_audit_logger: Optional[AuditLogger] = None
_audit_logger_lock = threading.Lock()


def get_audit_logger(log_dir: Optional[str] = None) -> AuditLogger:
    """
    Get or create global audit logger.
    
    Args:
        log_dir: Log directory (only used on first creation)
    
    Returns:
        Global audit logger instance
    """
    global _global_audit_logger
    
    with _audit_logger_lock:
        if _global_audit_logger is None:
            _global_audit_logger = AuditLogger(log_dir or "./data/audit_logs")
        return _global_audit_logger


__all__ = [
    'AuditEventType',
    'AuditLogEntry',
    'AuditLogger',
    'get_audit_logger',
]
