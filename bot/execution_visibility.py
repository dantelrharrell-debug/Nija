"""
Execution Visibility Module

Provides comprehensive trading execution logging with these features:
1. Throttled balance logging - only logs when balance changes or on time intervals
2. Execution visibility - logs strategy_ready, signal, can_trade decisions
3. Loop state indicator - tracks and logs system phase (WAITING_FOR_SIGNAL, READY_TO_TRADE, EXECUTING_ORDER)
4. Minimum order size validation - checks broker minimums (especially Kraken $5-$10)
5. Trade readiness checklist - logs critical conditions before execution

Usage:
    from execution_visibility import ExecutionVisibility
    
    visibility = ExecutionVisibility(broker_name="kraken")
    
    # Log state transition
    visibility.log_state("WAITING_FOR_SIGNAL")
    
    # Log balance (throttled)
    visibility.log_balance(current_balance=1234.56, force=False)
    
    # Log signal analysis
    visibility.log_signal_analysis(
        symbol="BTC-USD",
        rsi_9=45.5,
        rsi_14=44.2,
        signal="BUY",
        confidence=0.65
    )
    
    # Check minimum order size
    result = visibility.validate_order_size(
        symbol="BTC-USD",
        proposed_size_usd=103.00,
        broker_min_usd=5.0
    )
    
    # Log execution readiness
    visibility.log_execution_readiness(
        symbol="BTC-USD",
        strategy_ready=True,
        signal="BUY",
        can_trade=True,
        reason="All conditions met"
    )
"""

import logging
import time
from typing import Optional, Dict, Any
from enum import Enum
from dataclasses import dataclass, field

logger = logging.getLogger("nija")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# BROKER-SPECIFIC MINIMUM ORDER SIZES (USD)
# Updated as of Jan 2026 - these are the minimum notional values per exchange
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BROKER_MIN_ORDER_USD: Dict[str, float] = {
    'coinbase': 5.0,    # Coinbase stable ($5 minimum)
    'kraken':   5.0,    # Kraken floor ($5 minimum; some pairs may require $10)
    'binance':  10.0,   # Binance typical minimum
    'okx':      10.0,   # OKX typical minimum
    'alpaca':   1.0,    # Alpaca crypto minimum
}

# Kraken specific minimum per pair (some pairs have higher minimums)
KRAKEN_PAIR_MINIMUMS: Dict[str, float] = {
    'BTC-USD': 10.0,   # Bitcoin typically $10 minimum
    'ETH-USD': 5.0,    # Ethereum typically $5-$10
    'SOL-USD': 5.0,    # Solana typically $5
    'LINK-USD': 5.0,   # Chainlink typically $5
}

# Broker-specific minimum position sizes (in USD)
BROKER_MIN_POSITION_USD: Dict[str, float] = {
    'coinbase': 2.0,    # Absolute minimum for Coinbase
    'kraken':   5.0,    # Kraken $5-$10 minimum
    'binance':  5.0,    # Binance $5 typical
    'okx':      5.0,    # OKX $5 typical
    'alpaca':   1.0,    # Alpaca $1 typical
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# LOOP STATE ENUMS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class LoopState(Enum):
    """Trading loop state for visibility."""
    WAITING_FOR_SIGNAL = "WAITING_FOR_SIGNAL"
    SIGNAL_DETECTED = "SIGNAL_DETECTED"
    READY_TO_TRADE = "READY_TO_TRADE"
    EXECUTING_ORDER = "EXECUTING_ORDER"
    ORDER_COMPLETE = "ORDER_COMPLETE"
    POSITION_MANAGEMENT = "POSITION_MANAGEMENT"
    ERROR = "ERROR"


class ExecutionPhase(Enum):
    """Detailed execution phase for granular visibility."""
    BALANCE_CHECK = "BALANCE_CHECK"
    MARKET_SCAN = "MARKET_SCAN"
    SIGNAL_ANALYSIS = "SIGNAL_ANALYSIS"
    CONDITIONS_CHECK = "CONDITIONS_CHECK"
    ORDER_SIZING = "ORDER_SIZING"
    POSITION_LIMIT_CHECK = "POSITION_LIMIT_CHECK"
    RISK_CHECK = "RISK_CHECK"
    ORDER_PLACEMENT = "ORDER_PLACEMENT"
    ORDER_CONFIRMATION = "ORDER_CONFIRMATION"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ORDER SIZE VALIDATION RESULT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@dataclass
class OrderSizeValidation:
    """Result of order size validation against broker minimum."""
    valid: bool
    symbol: str
    proposed_size_usd: float
    broker_min_usd: float
    reason: str
    meets_minimum: bool
    exceeds_by_pct: float = 0.0  # How much above minimum (0-100%)
    recommended_action: str = ""  # What to do if invalid


@dataclass
class ExecutionReadiness:
    """Execution readiness check result."""
    ready: bool
    symbol: str
    timestamp: float = field(default_factory=time.time)
    strategy_ready: bool = False
    signal_strength: float = 0.0  # 0.0 to 1.0
    signal_type: str = ""  # BUY, SELL, HOLD
    can_trade: bool = False
    balance_ok: bool = False
    position_limit_ok: bool = False
    risk_ok: bool = False
    veto_reasons: list = field(default_factory=list)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# EXECUTION VISIBILITY CLASS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class ExecutionVisibility:
    """
    Comprehensive trading execution visibility and monitoring.
    
    Provides:
    - Throttled balance logging
    - Execution decision logging
    - Loop state tracking
    - Minimum order size validation
    - Trade readiness checklist
    """

    def __init__(self, broker_name: str = "coinbase"):
        """Initialize execution visibility module.
        
        Args:
            broker_name: Name of the broker (coinbase, kraken, binance, etc.)
        """
        self.broker_name = broker_name.lower()
        self.broker_min_order_usd = BROKER_MIN_ORDER_USD.get(
            self.broker_name, 5.0
        )
        
        # Balance tracking for throttled logging
        self.last_logged_balance: Optional[float] = None
        self.last_balance_log_time: float = time.time()
        self.balance_log_interval_seconds = 60  # Log balance every 60 seconds OR on change
        self.balance_change_threshold = 1.0  # Log if balance changes by more than $1
        
        # State tracking
        self.current_state = LoopState.WAITING_FOR_SIGNAL
        self.current_phase = ExecutionPhase.BALANCE_CHECK
        self.last_state_change_time = time.time()
        self.state_transition_history: list = []
        
        # Signal tracking
        self.last_signal: Optional[str] = None
        self.last_signal_symbol: Optional[str] = None
        self.last_signal_time: float = time.time()
        self.signal_count = 0
        
        # Execution tracking
        self.last_execution_time: float = 0.0
        self.execution_count = 0
        self.failed_execution_count = 0
        
        logger.info(f"✅ ExecutionVisibility initialized for broker={self.broker_name}")
        logger.info(f"   Minimum order size: ${self.broker_min_order_usd:.2f}")

    # ────────────────────────────────────────────────────────────────────────────
    # STATE MANAGEMENT
    # ────────────────────────────────────────────────────────────────────────────

    def set_state(self, state: LoopState, reason: str = "") -> None:
        """Update the trading loop state.
        
        Args:
            state: New loop state
            reason: Optional reason for state change
        """
        if state == self.current_state:
            return  # No change needed
        
        old_state = self.current_state
        self.current_state = state
        self.last_state_change_time = time.time()
        
        # Record state transition
        self.state_transition_history.append({
            'from': old_state.value,
            'to': state.value,
            'reason': reason,
            'timestamp': self.last_state_change_time,
        })
        
        # Limit history to last 100 transitions
        if len(self.state_transition_history) > 100:
            self.state_transition_history = self.state_transition_history[-100:]

    def log_state(self, state: LoopState, reason: str = "") -> None:
        """Log a state change with visibility.
        
        Args:
            state: New loop state
            reason: Reason for state change
        """
        self.set_state(state, reason)
        
        # Format state display
        state_display = f"STATE: {state.value}"
        if reason:
            state_display += f" ({reason})"
        
        logger.info(f"🔄 {state_display}")

    # ────────────────────────────────────────────────────────────────────────────
    # BALANCE LOGGING (THROTTLED)
    # ────────────────────────────────────────────────────────────────────────────

    def log_balance(
        self,
        current_balance: float,
        force: bool = False,
        label: str = "Account Balance"
    ) -> bool:
        """Log balance with throttling - only logs on change or time interval.
        
        Args:
            current_balance: Current account balance in USD
            force: Force logging even if not due
            label: Label for balance log message
            
        Returns:
            True if balance was logged, False if throttled
        """
        current_time = time.time()
        time_since_last_log = current_time - self.last_balance_log_time
        
        # Check if we should log
        should_log = force
        log_reason = "forced" if force else ""
        
        if self.last_logged_balance is None:
            should_log = True
            log_reason = "first_log"
        elif time_since_last_log >= self.balance_log_interval_seconds:
            should_log = True
            log_reason = f"interval ({self.balance_log_interval_seconds}s)"
        elif abs(current_balance - self.last_logged_balance) >= self.balance_change_threshold:
            should_log = True
            balance_change = current_balance - self.last_logged_balance
            log_reason = f"change (+${balance_change:.2f})"
        
        if should_log:
            logger.info(f"💰 {label}: ${current_balance:.2f} [{log_reason}]")
            self.last_logged_balance = current_balance
            self.last_balance_log_time = current_time
            return True
        
        return False

    # ────────────────────────────────────────────────────────────────────────────
    # EXECUTION VISIBILITY
    # ────────────────────────────────────────────────────────────────────────────

    def log_signal_analysis(
        self,
        symbol: str,
        rsi_9: float,
        rsi_14: float,
        signal: str,
        confidence: float = 0.0,
        extra_info: Optional[Dict[str, Any]] = None
    ) -> None:
        """Log signal analysis for a symbol.
        
        Args:
            symbol: Trading pair (e.g., BTC-USD)
            rsi_9: RSI(9) value
            rsi_14: RSI(14) value
            signal: Signal type (BUY, SELL, HOLD)
            confidence: Confidence score (0.0 to 1.0)
            extra_info: Additional information to log
        """
        self.last_signal = signal
        self.last_signal_symbol = symbol
        self.last_signal_time = time.time()
        
        if signal != "HOLD":
            self.signal_count += 1
        
        # Format signal log
        signal_emoji = "🟢" if signal == "BUY" else "🔴" if signal == "SELL" else "⚪"
        conf_pct = confidence * 100 if confidence > 0 else 0
        
        log_msg = (
            f"{signal_emoji} Signal: {symbol} → {signal} "
            f"| RSI9={rsi_9:.1f} RSI14={rsi_14:.1f} "
            f"| Confidence={conf_pct:.0f}%"
        )
        
        if extra_info:
            # Add extra info as additional fields
            extra_str = " | ".join(
                f"{k}={v}" for k, v in extra_info.items()
            )
            log_msg += f" | {extra_str}"
        
        logger.info(f"📊 {log_msg}")

    def log_execution_readiness(
        self,
        symbol: str,
        strategy_ready: bool,
        signal: str,
        can_trade: bool,
        reason: str = "",
        extra_checks: Optional[Dict[str, bool]] = None
    ) -> None:
        """Log trade execution readiness checklist.
        
        Args:
            symbol: Trading pair
            strategy_ready: Is strategy ready to trade
            signal: Current signal (BUY, SELL, HOLD)
            can_trade: Can the trade be executed
            reason: Reason if cannot trade
            extra_checks: Additional boolean checks {name: bool}
        """
        # Log the critical execution decision
        status = "✅ READY" if can_trade else "❌ BLOCKED"
        
        log_msg = f"{status} | Symbol={symbol} | Signal={signal} | Strategy={strategy_ready}"
        
        if extra_checks:
            checks_str = " | ".join(
                f"{k}={'✅' if v else '❌'}" for k, v in extra_checks.items()
            )
            log_msg += f" | {checks_str}"
        
        if reason:
            log_msg += f" | Reason: {reason}"
        
        logger.info(f"🎯 Execution Readiness: {log_msg}")

    # ────────────────────────────────────────────────────────────────────────────
    # MINIMUM ORDER SIZE VALIDATION
    # ────────────────────────────────────────────────────────────────────────────

    def validate_order_size(
        self,
        symbol: str,
        proposed_size_usd: float,
        broker_min_usd: Optional[float] = None
    ) -> OrderSizeValidation:
        """Validate order size against broker minimum.
        
        Args:
            symbol: Trading pair (e.g., BTC-USD)
            proposed_size_usd: Proposed order size in USD
            broker_min_usd: Override broker minimum (uses default if None)
            
        Returns:
            OrderSizeValidation with validity and recommendation
        """
        # Use provided minimum or broker default
        if broker_min_usd is None:
            broker_min_usd = self.broker_min_order_usd
            
            # Check for Kraken pair-specific minimums
            if self.broker_name == 'kraken' and symbol in KRAKEN_PAIR_MINIMUMS:
                broker_min_usd = KRAKEN_PAIR_MINIMUMS[symbol]
        
        meets_minimum = proposed_size_usd >= broker_min_usd
        exceeds_by_pct = ((proposed_size_usd - broker_min_usd) / broker_min_usd * 100) if broker_min_usd > 0 else 0
        
        if meets_minimum:
            reason = f"Order size ${proposed_size_usd:.2f} meets minimum ${broker_min_usd:.2f}"
            recommended_action = "PROCEED"
        else:
            shortfall = broker_min_usd - proposed_size_usd
            reason = (
                f"Order size ${proposed_size_usd:.2f} BELOW minimum ${broker_min_usd:.2f} "
                f"(short by ${shortfall:.2f})"
            )
            recommended_action = f"INCREASE to ${broker_min_usd:.2f} or SKIP"
        
        result = OrderSizeValidation(
            valid=meets_minimum,
            symbol=symbol,
            proposed_size_usd=proposed_size_usd,
            broker_min_usd=broker_min_usd,
            reason=reason,
            meets_minimum=meets_minimum,
            exceeds_by_pct=exceeds_by_pct,
            recommended_action=recommended_action
        )
        
        # Log validation result
        status = "✅" if meets_minimum else "❌"
        logger.info(f"{status} Order Size Validation: {symbol} ${proposed_size_usd:.2f} vs min ${broker_min_usd:.2f}")
        
        if not meets_minimum:
            logger.warning(f"   ⚠️  {reason}")
            logger.warning(f"   Action: {recommended_action}")
        
        return result

    def get_minimum_order_size(self, symbol: str) -> float:
        """Get the minimum order size for a symbol on this broker.
        
        Args:
            symbol: Trading pair
            
        Returns:
            Minimum order size in USD
        """
        if self.broker_name == 'kraken' and symbol in KRAKEN_PAIR_MINIMUMS:
            return KRAKEN_PAIR_MINIMUMS[symbol]
        
        return self.broker_min_order_usd

    # ────────────────────────────────────────────────────────────────────────────
    # LOOP PHASE TRACKING
    # ────────────────────────────────────────────────────────────────────────────

    def set_phase(self, phase: ExecutionPhase) -> None:
        """Update the execution phase.
        
        Args:
            phase: New execution phase
        """
        self.current_phase = phase

    def log_phase(self, phase: ExecutionPhase, detail: str = "") -> None:
        """Log execution phase transition.
        
        Args:
            phase: New execution phase
            detail: Optional detail message
        """
        self.set_phase(phase)
        
        phase_display = f"PHASE: {phase.value}"
        if detail:
            phase_display += f" - {detail}"
        
        logger.debug(f"📍 {phase_display}")

    # ────────────────────────────────────────────────────────────────────────────
    # STATISTICS & REPORTING
    # ────────────────────────────────────────────────────────────────────────────

    def get_execution_stats(self) -> Dict[str, Any]:
        """Get execution statistics.
        
        Returns:
            Dictionary with execution metrics
        """
        success_rate = 0.0
        total_executions = self.execution_count
        if total_executions > 0:
            success_rate = (
                (total_executions - self.failed_execution_count) / total_executions * 100
            )
        
        return {
            'broker': self.broker_name,
            'min_order_size_usd': self.broker_min_order_usd,
            'current_state': self.current_state.value,
            'current_phase': self.current_phase.value,
            'execution_count': self.execution_count,
            'failed_execution_count': self.failed_execution_count,
            'success_rate_pct': success_rate,
            'signal_count': self.signal_count,
            'last_signal': self.last_signal,
            'last_signal_symbol': self.last_signal_symbol,
        }

    def log_stats(self) -> None:
        """Log execution statistics."""
        stats = self.get_execution_stats()
        
        logger.info("═" * 70)
        logger.info("📊 EXECUTION VISIBILITY STATISTICS")
        logger.info("═" * 70)
        logger.info(f"   Broker: {stats['broker'].upper()}")
        logger.info(f"   Minimum order size: ${stats['min_order_size_usd']:.2f}")
        logger.info(f"   Current state: {stats['current_state']}")
        logger.info(f"   Current phase: {stats['current_phase']}")
        logger.info(f"   Total executions: {stats['execution_count']}")
        logger.info(f"   Failed executions: {stats['failed_execution_count']}")
        logger.info(f"   Success rate: {stats['success_rate_pct']:.1f}%")
        logger.info(f"   Total signals generated: {stats['signal_count']}")
        if stats['last_signal']:
            logger.info(f"   Last signal: {stats['last_signal']} on {stats['last_signal_symbol']}")
        logger.info("═" * 70)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MODULE-LEVEL SINGLETON (optional)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_global_visibility: Optional[ExecutionVisibility] = None


def get_execution_visibility(broker_name: str = "coinbase") -> ExecutionVisibility:
    """Get or create the global execution visibility instance.
    
    Args:
        broker_name: Name of the broker to initialize with
        
    Returns:
        ExecutionVisibility singleton instance
    """
    global _global_visibility
    
    if _global_visibility is None:
        _global_visibility = ExecutionVisibility(broker_name=broker_name)
    
    return _global_visibility
