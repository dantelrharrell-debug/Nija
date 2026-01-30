"""
NIJA Live Validation Framework - Data Models

Defines the core data structures for the live validation framework.

Author: NIJA Trading Systems
Date: January 30, 2026
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any, List
from datetime import datetime


class ValidationLevel(Enum):
    """Severity level of validation result"""
    PASS = "pass"           # Validation passed
    INFO = "info"           # Informational, no action needed
    WARNING = "warning"     # Warning, but can proceed
    ERROR = "error"         # Error, should not proceed
    CRITICAL = "critical"   # Critical error, halt trading


class ValidationCategory(Enum):
    """Category of validation check"""
    PRE_TRADE = "pre_trade"                     # Before order submission
    ORDER_EXECUTION = "order_execution"         # During order execution
    POST_TRADE = "post_trade"                   # After order execution
    REAL_TIME_MONITORING = "real_time_monitoring"  # Continuous monitoring
    RISK = "risk"                               # Risk-related validation
    DATA_INTEGRITY = "data_integrity"           # Data quality validation
    POSITION_RECONCILIATION = "position_reconciliation"  # Position state validation
    FEE_VALIDATION = "fee_validation"           # Fee and cost validation
    CIRCUIT_BREAKER = "circuit_breaker"         # Emergency validation


@dataclass
class ValidationResult:
    """Result of a validation check"""
    
    # Core fields
    level: ValidationLevel
    category: ValidationCategory
    validator_name: str
    message: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    # Optional context
    symbol: Optional[str] = None
    account_id: Optional[str] = None
    broker: Optional[str] = None
    order_id: Optional[str] = None
    
    # Detailed info
    details: Dict[str, Any] = field(default_factory=dict)
    metrics: Dict[str, float] = field(default_factory=dict)
    
    # Recommendations
    recommended_action: Optional[str] = None
    can_proceed: bool = True
    
    def is_blocking(self) -> bool:
        """Check if this validation result should block trading"""
        return self.level in [ValidationLevel.ERROR, ValidationLevel.CRITICAL]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/API"""
        return {
            'level': self.level.value,
            'category': self.category.value,
            'validator_name': self.validator_name,
            'message': self.message,
            'timestamp': self.timestamp.isoformat(),
            'symbol': self.symbol,
            'account_id': self.account_id,
            'broker': self.broker,
            'order_id': self.order_id,
            'details': self.details,
            'metrics': self.metrics,
            'recommended_action': self.recommended_action,
            'can_proceed': self.can_proceed,
            'is_blocking': self.is_blocking()
        }
    
    def __str__(self) -> str:
        """String representation for logging"""
        parts = [
            f"[{self.level.value.upper()}]",
            f"[{self.category.value}]",
            f"{self.validator_name}:",
            self.message
        ]
        
        if self.symbol:
            parts.insert(3, f"[{self.symbol}]")
        
        if self.broker:
            parts.insert(3, f"[{self.broker}]")
            
        return " ".join(parts)


@dataclass
class ValidationContext:
    """Context information for validation"""
    
    # Trade information
    symbol: str
    side: str
    size: float
    price: Optional[float] = None
    
    # Account information
    account_id: str = "default"
    broker: str = "unknown"
    
    # Risk information
    account_balance: Optional[float] = None
    open_positions: Optional[int] = None
    daily_pnl: Optional[float] = None
    
    # Order information
    order_id: Optional[str] = None
    order_type: str = "market"
    
    # Timing
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    # Additional context
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'symbol': self.symbol,
            'side': self.side,
            'size': self.size,
            'price': self.price,
            'account_id': self.account_id,
            'broker': self.broker,
            'account_balance': self.account_balance,
            'open_positions': self.open_positions,
            'daily_pnl': self.daily_pnl,
            'order_id': self.order_id,
            'order_type': self.order_type,
            'timestamp': self.timestamp.isoformat(),
            'metadata': self.metadata
        }


@dataclass
class ValidationMetrics:
    """Aggregated validation metrics"""
    
    # Counters
    total_validations: int = 0
    passed: int = 0
    warnings: int = 0
    errors: int = 0
    critical: int = 0
    
    # By category
    by_category: Dict[str, int] = field(default_factory=dict)
    
    # Timing
    avg_validation_time_ms: float = 0.0
    max_validation_time_ms: float = 0.0
    
    # Recent failures
    recent_failures: List[str] = field(default_factory=list)
    
    # Uptime
    start_time: datetime = field(default_factory=datetime.utcnow)
    last_validation_time: Optional[datetime] = None
    
    def record_validation(self, result: ValidationResult, duration_ms: float):
        """Record a validation result"""
        self.total_validations += 1
        
        if result.level == ValidationLevel.PASS:
            self.passed += 1
        elif result.level == ValidationLevel.WARNING:
            self.warnings += 1
        elif result.level == ValidationLevel.ERROR:
            self.errors += 1
            self.recent_failures.append(str(result))
        elif result.level == ValidationLevel.CRITICAL:
            self.critical += 1
            self.recent_failures.append(str(result))
        
        # Update category counter
        category_key = result.category.value
        self.by_category[category_key] = self.by_category.get(category_key, 0) + 1
        
        # Update timing
        self.avg_validation_time_ms = (
            (self.avg_validation_time_ms * (self.total_validations - 1) + duration_ms) 
            / self.total_validations
        )
        self.max_validation_time_ms = max(self.max_validation_time_ms, duration_ms)
        self.last_validation_time = datetime.utcnow()
        
        # Keep only last 10 failures
        if len(self.recent_failures) > 10:
            self.recent_failures = self.recent_failures[-10:]
    
    def get_pass_rate(self) -> float:
        """Calculate validation pass rate"""
        if self.total_validations == 0:
            return 0.0
        return (self.passed / self.total_validations) * 100
    
    def get_error_rate(self) -> float:
        """Calculate error rate"""
        if self.total_validations == 0:
            return 0.0
        return ((self.errors + self.critical) / self.total_validations) * 100
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'total_validations': self.total_validations,
            'passed': self.passed,
            'warnings': self.warnings,
            'errors': self.errors,
            'critical': self.critical,
            'pass_rate_pct': round(self.get_pass_rate(), 2),
            'error_rate_pct': round(self.get_error_rate(), 2),
            'by_category': self.by_category,
            'avg_validation_time_ms': round(self.avg_validation_time_ms, 2),
            'max_validation_time_ms': round(self.max_validation_time_ms, 2),
            'recent_failures': self.recent_failures,
            'uptime_seconds': (datetime.utcnow() - self.start_time).total_seconds(),
            'last_validation_time': self.last_validation_time.isoformat() if self.last_validation_time else None
        }
