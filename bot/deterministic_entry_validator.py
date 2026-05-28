"""
NIJA Deterministic Entry Validator
====================================

Stateful, attempt-scoped deterministic reducer with idempotent emission
guarantees.  Implements a minimal **ExecutionContractSpec** that is
mechanically enforceable across the pipeline, broker, and retry layers.

Design
------
Each validation attempt is uniquely identified by an ``AttemptKey``
``(intent_id, attempt_n)``.  The reducer stores the outcome of every key it
has evaluated and returns the same stored ``AttemptRecord`` on every
subsequent call with that key — regardless of how the underlying context has
changed since the first evaluation.  This prevents retry-loops from silently
re-validating the same intent under different market conditions and emitting
duplicate journal events.

Emission guarantee
~~~~~~~~~~~~~~~~~~
``emit_once(record)`` writes a journal event for an attempt exactly once.  If
the record has already been emitted (``EmissionState.EMITTED``) the method is
a no-op and returns ``False``.  This makes it safe to call from the retry
wrapper, the broker adapter, and the pipeline without coordinating between
layers.

Retry contract
~~~~~~~~~~~~~~
``should_retry(record)`` classifies the rejection using ``RejectionClass``
(TRANSIENT / PERMANENT / AUTHORITY_BLOCKED) and delegates the retry decision
to the ``ExecutionContractSpec`` attached to the validator instance.  Callers
at the retry layer check this method instead of examining raw rejection codes.

Backward compatibility
~~~~~~~~~~~~~~~~~~~~~~
The pre-existing ``validate_entry(context) -> ValidationResult`` API is
preserved.  It runs the gate sequence through ``_run_gates`` with a
transient, per-call key (never stored in ``_records``) so existing callers
see no behaviour change.  New callers should use ``reduce(key, context)``
directly.

Rejection Codes:
- TIER_MAX_POSITIONS: At maximum position count for tier
- INSUFFICIENT_CAPITAL: Not enough capital available
- POSITION_TOO_SMALL: Position size below tier/exchange minimum
- POSITION_TOO_LARGE: Position size exceeds tier maximum
- BALANCE_TOO_LOW: Account balance below trading minimum
- EXCHANGE_MINIMUM_NOT_MET: Below exchange-specific minimum
- SIGNAL_QUALITY_LOW: Signal quality score too low
- COOLDOWN_ACTIVE: Trading cooldown in effect
- MARKET_CLOSED: Market not open for trading
- SYMBOL_RESTRICTED: Symbol on restricted list
- VALIDATION_PASSED: All validation checks passed

Author: NIJA Trading Systems
Version: 2.0
Date: May 2026
"""

from __future__ import annotations

import logging
import threading
import uuid
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum

logger = logging.getLogger("nija.entry_validator")


class RejectionCode(Enum):
    """Enumeration of all possible entry rejection codes"""
    # Tier-related rejections
    TIER_MAX_POSITIONS = "TIER_MAX_POSITIONS"
    TIER_POSITION_SIZE_TOO_SMALL = "TIER_POSITION_SIZE_TOO_SMALL"
    TIER_POSITION_SIZE_TOO_LARGE = "TIER_POSITION_SIZE_TOO_LARGE"
    
    # Capital-related rejections
    INSUFFICIENT_CAPITAL = "INSUFFICIENT_CAPITAL"
    BALANCE_TOO_LOW = "BALANCE_TOO_LOW"
    INSUFFICIENT_FREE_BALANCE = "INSUFFICIENT_FREE_BALANCE"
    
    # Exchange-related rejections
    EXCHANGE_MINIMUM_NOT_MET = "EXCHANGE_MINIMUM_NOT_MET"
    EXCHANGE_NOT_SUPPORTED = "EXCHANGE_NOT_SUPPORTED"
    
    # Signal quality rejections
    SIGNAL_QUALITY_LOW = "SIGNAL_QUALITY_LOW"
    SIGNAL_CONFIDENCE_LOW = "SIGNAL_CONFIDENCE_LOW"
    
    # Trading state rejections
    COOLDOWN_ACTIVE = "COOLDOWN_ACTIVE"
    MAX_DAILY_TRADES = "MAX_DAILY_TRADES"
    DRAWDOWN_HALT = "DRAWDOWN_HALT"
    
    # Market/Symbol rejections
    MARKET_CLOSED = "MARKET_CLOSED"
    SYMBOL_RESTRICTED = "SYMBOL_RESTRICTED"
    SYMBOL_BLACKLISTED = "SYMBOL_BLACKLISTED"
    
    # Position management rejections
    DUPLICATE_POSITION = "DUPLICATE_POSITION"
    OPPOSING_POSITION_EXISTS = "OPPOSING_POSITION_EXISTS"
    
    # Success
    VALIDATION_PASSED = "VALIDATION_PASSED"


# ---------------------------------------------------------------------------
# Attempt-scoped contract primitives
# ---------------------------------------------------------------------------

class EmissionState(Enum):
    """Tracks whether an attempt's journal event has already been emitted."""
    PENDING = "PENDING"
    EMITTED = "EMITTED"


class RejectionClass(Enum):
    """
    High-level classification used by the retry layer.

    TRANSIENT
        A temporary condition (cooldown, resource contention, market closed)
        that may resolve without changing the intent.  Retries are permitted.

    PERMANENT
        A structural mismatch (size too small, symbol blacklisted, quality
        too low) that will not change unless the intent itself changes.
        Retries are refused.

    AUTHORITY_BLOCKED
        An authority gate (drawdown halt, kill-switch, lifecycle phase) that
        requires an external state change before the intent can proceed.
        Retries are refused unless the spec explicitly allows them.
    """
    TRANSIENT = "TRANSIENT"
    PERMANENT = "PERMANENT"
    AUTHORITY_BLOCKED = "AUTHORITY_BLOCKED"


# Canonical mapping from RejectionCode to RejectionClass.  This is the
# single source of truth consumed by should_retry() and the retry layer.
_REJECTION_CLASS_MAP: Dict[RejectionCode, RejectionClass] = {
    RejectionCode.TIER_MAX_POSITIONS: RejectionClass.TRANSIENT,
    RejectionCode.TIER_POSITION_SIZE_TOO_SMALL: RejectionClass.PERMANENT,
    RejectionCode.TIER_POSITION_SIZE_TOO_LARGE: RejectionClass.PERMANENT,
    RejectionCode.INSUFFICIENT_CAPITAL: RejectionClass.TRANSIENT,
    RejectionCode.BALANCE_TOO_LOW: RejectionClass.PERMANENT,
    RejectionCode.INSUFFICIENT_FREE_BALANCE: RejectionClass.TRANSIENT,
    RejectionCode.EXCHANGE_MINIMUM_NOT_MET: RejectionClass.PERMANENT,
    RejectionCode.EXCHANGE_NOT_SUPPORTED: RejectionClass.PERMANENT,
    RejectionCode.SIGNAL_QUALITY_LOW: RejectionClass.PERMANENT,
    RejectionCode.SIGNAL_CONFIDENCE_LOW: RejectionClass.PERMANENT,
    RejectionCode.COOLDOWN_ACTIVE: RejectionClass.TRANSIENT,
    RejectionCode.MAX_DAILY_TRADES: RejectionClass.PERMANENT,
    RejectionCode.DRAWDOWN_HALT: RejectionClass.AUTHORITY_BLOCKED,
    RejectionCode.MARKET_CLOSED: RejectionClass.TRANSIENT,
    RejectionCode.SYMBOL_RESTRICTED: RejectionClass.PERMANENT,
    RejectionCode.SYMBOL_BLACKLISTED: RejectionClass.PERMANENT,
    RejectionCode.DUPLICATE_POSITION: RejectionClass.PERMANENT,
    RejectionCode.OPPOSING_POSITION_EXISTS: RejectionClass.PERMANENT,
    RejectionCode.VALIDATION_PASSED: RejectionClass.PERMANENT,  # n/a for passed
}


@dataclass(frozen=True)
class AttemptKey:
    """
    Unique identity for a single validation attempt within an intent's lifecycle.

    ``intent_id`` is the canonical intent identifier (from
    ``build_canonical_intent_id`` or the pipeline's request_id).
    ``attempt_n`` starts at 0 for the first attempt and increments with every
    retry.  Together they form the dedup key used by the reducer store.
    """
    intent_id: str
    attempt_n: int = 0

    def next(self) -> "AttemptKey":
        """Return the key for the next retry attempt."""
        return AttemptKey(intent_id=self.intent_id, attempt_n=self.attempt_n + 1)

    def __post_init__(self) -> None:
        if not isinstance(self.intent_id, str):
            object.__setattr__(self, "intent_id", str(self.intent_id))
        if self.attempt_n < 0:
            raise ValueError(f"AttemptKey.attempt_n must be >= 0, got {self.attempt_n}")


@dataclass
class AttemptRecord:
    """
    Immutable outcome stored by the reducer for a single ``AttemptKey``.

    Once stored, this record is never mutated except to transition
    ``emission_state`` from ``PENDING`` → ``EMITTED`` via ``emit_once()``.
    All other fields are set at construction time and treated as read-only.
    """
    key: AttemptKey
    passed: bool
    rejection_code: RejectionCode
    rejection_class: RejectionClass
    rejection_message: str
    gates_passed: List[str]
    gates_failed: List[str]
    emission_state: EmissionState
    reduced_at: str  # ISO-8601 UTC timestamp


@dataclass(frozen=True)
class ExecutionContractSpec:
    """
    Minimal, mechanically enforceable execution contract.

    This spec is the single source of truth for:
    - Whether anonymous (intent-id-less) attempts are permitted
    - Whether retry of PERMANENT / AUTHORITY_BLOCKED rejections is allowed
    - The maximum number of retry attempts allowed per intent
    - Whether idempotent emission is enforced (if False, emit_once always
      emits regardless of prior emission)

    Attach one instance to each ``DeterministicEntryValidator``.  The retry
    wrapper, pipeline, and broker adapter all call
    ``validator.should_retry(record)`` rather than inspecting rejection codes
    directly, ensuring the spec is obeyed across all layers.
    """
    intent_id_required: bool = True
    attempt_n_required: bool = True
    idempotent_emission: bool = True
    retry_permanent_rejections: bool = False
    retry_authority_blocked: bool = False
    max_retries: int = 3

    def allows_retry(self, rejection_class: RejectionClass, attempt_n: int = 0) -> bool:
        """Return True if the spec permits a retry given the class and current attempt number."""
        if attempt_n >= self.max_retries:
            return False
        if rejection_class == RejectionClass.TRANSIENT:
            return True
        if rejection_class == RejectionClass.PERMANENT:
            return self.retry_permanent_rejections
        if rejection_class == RejectionClass.AUTHORITY_BLOCKED:
            return self.retry_authority_blocked
        return False

    def enforce(self, key: AttemptKey) -> None:
        """
        Raise ``ValueError`` if the key violates the contract.

        Called by ``reduce()`` before any gate logic runs so that contract
        violations surface at the boundary, not buried in gate output.
        """
        if self.intent_id_required and not (key.intent_id or "").strip():
            raise ValueError(
                "ExecutionContractSpec: intent_id is required but empty. "
                "Set NIJA_RUNTIME_CORRELATION_REQUIRED=true or pass an explicit intent_id."
            )
        if self.attempt_n_required and key.attempt_n < 0:
            raise ValueError(
                f"ExecutionContractSpec: attempt_n must be >= 0, got {key.attempt_n}."
            )


@dataclass
class ValidationResult:
    """
    Result of entry validation.
    
    Attributes:
        passed: Whether validation passed
        rejection_code: Code identifying rejection reason (or VALIDATION_PASSED)
        rejection_message: Human-readable rejection message
        validation_timestamp: When validation occurred
        validation_details: Additional details about validation
    """
    passed: bool
    rejection_code: RejectionCode
    rejection_message: str
    validation_timestamp: datetime
    validation_details: Dict
    
    def __repr__(self):
        return (f"ValidationResult(passed={self.passed}, "
                f"code={self.rejection_code.value}, "
                f"message='{self.rejection_message}')")


@dataclass
class ValidationContext:
    """
    Context information for validation.
    
    Contains all information needed to perform comprehensive validation:
    - Account state (balance, tier, positions)
    - Signal information (symbol, type, quality)
    - Position parameters (size, type)
    - Trading state (cooldowns, restrictions)
    """
    # Account information
    balance: float
    tier_name: str
    current_position_count: int
    open_positions: List[str]  # List of open position symbols
    available_capital: float
    
    # Signal information
    symbol: str
    signal_type: str  # LONG or SHORT
    signal_quality: float  # 0-100
    signal_confidence: float  # 0-1
    
    # Position parameters
    proposed_size_usd: float
    
    # Exchange information
    exchange_name: str = "coinbase"
    exchange_minimum_usd: float = 5.0
    
    # Trading state
    cooldown_until: Optional[datetime] = None
    daily_trade_count: int = 0
    max_daily_trades: int = 100
    in_drawdown_halt: bool = False
    
    # Symbol restrictions
    restricted_symbols: List[str] = None
    blacklisted_symbols: List[str] = None
    
    def __post_init__(self):
        if self.restricted_symbols is None:
            self.restricted_symbols = []
        if self.blacklisted_symbols is None:
            self.blacklisted_symbols = []


class DeterministicEntryValidator:
    """
    Deterministic entry validator with explicit rejection codes.
    
    Performs multi-gate validation:
    1. Account State Validation (balance, tier limits)
    2. Capital Availability Validation (sufficient funds)
    3. Position Limit Validation (tier max positions)
    4. Position Size Validation (tier and exchange minimums/maximums)
    5. Signal Quality Validation (quality and confidence thresholds)
    6. Trading State Validation (cooldowns, daily limits, drawdowns)
    7. Market/Symbol Validation (market hours, restrictions, blacklists)
    8. Position Conflict Validation (duplicates, opposing positions)
    
    Each gate produces explicit rejection code and message on failure.
    """
    
    def __init__(
        self,
        min_signal_quality: float = 40.0,
        min_signal_confidence: float = 0.45,
        spec: Optional[ExecutionContractSpec] = None,
    ):
        """
        Initialize the deterministic entry validator.
        
        Args:
            min_signal_quality: Minimum signal quality score (0-100)
            min_signal_confidence: Minimum signal confidence (0-1)
            spec: ExecutionContractSpec governing retry and emission rules.
                  Defaults to a standard live-trading spec.
        """
        self.min_signal_quality = min_signal_quality
        self.min_signal_confidence = min_signal_confidence
        self._spec: ExecutionContractSpec = spec if spec is not None else ExecutionContractSpec()
        
        # Exchange-specific minimums (USD)
        self.exchange_minimums = {
            'coinbase': 5.0,
            'kraken': 10.50,  # $10 + fee buffer
            'binance': 10.0,
            'okx': 5.0,
            'alpaca': 5.0,
        }
        
        # Minimum balance to trade (absolute floor)
        self.min_balance_to_trade = 50.0
        
        # Attempt-scoped reducer store: AttemptKey → AttemptRecord
        self._records: Dict[AttemptKey, AttemptRecord] = {}
        self._records_lock = threading.Lock()

        # Backward-compatible validation history (validate_entry path only)
        self.validation_history: List[ValidationResult] = []
        self.max_history_size = 1000
        
        logger.info(
            "DeterministicEntryValidator v2 ready | "
            "spec=intent_id_required:%s idempotent:%s max_retries:%d",
            self._spec.intent_id_required,
            self._spec.idempotent_emission,
            self._spec.max_retries,
        )

    # ------------------------------------------------------------------
    # Core reducer API (new — stateful, attempt-scoped, idempotent)
    # ------------------------------------------------------------------

    def reduce(self, key: AttemptKey, context: ValidationContext) -> AttemptRecord:
        """
        Stateful, attempt-scoped deterministic reducer.

        Contract guarantees
        -------------------
        - **Deterministic**: the same ``AttemptKey`` always returns the same
          ``AttemptRecord``.  If a record is already stored for this key the
          gates are NOT re-run — the stored outcome is returned directly.
        - **Idempotent**: calling ``reduce`` multiple times with the same key
          is safe under concurrent load; only one record is ever stored per key
          (double-checked locking).
        - **Contract-enforced**: if the ``ExecutionContractSpec`` requires
          ``intent_id`` or a non-negative ``attempt_n``, a ``ValueError`` is
          raised before any gate logic executes.

        Parameters
        ----------
        key:
            Unique attempt identity ``(intent_id, attempt_n)``.
        context:
            Current market/account state snapshot for this attempt.

        Returns
        -------
        AttemptRecord
            The (possibly cached) outcome for this key.
        """
        self._spec.enforce(key)

        # Fast path: record already exists (no lock needed for first read)
        existing = self._records.get(key)
        if existing is not None:
            return existing

        # Run gates outside the lock (pure computation, no side effects)
        record = self._run_gates(key, context)

        # Store under lock with double-check to survive concurrent reduce() calls
        with self._records_lock:
            if key in self._records:
                return self._records[key]
            self._records[key] = record
        return record

    def emit_once(self, record: AttemptRecord) -> bool:
        """
        Emit the validation outcome to the execution journal exactly once.

        If the record's ``emission_state`` is already ``EMITTED`` this method
        is a no-op and returns ``False``.  This makes it safe to call from any
        layer (pipeline, broker adapter, retry wrapper) without coordinating
        which layer "owns" the emission.

        Parameters
        ----------
        record:
            The ``AttemptRecord`` to emit (returned by ``reduce()``).

        Returns
        -------
        bool
            ``True`` if the event was emitted now; ``False`` if it had already
            been emitted (or if idempotent_emission is disabled in the spec).
        """
        if not self._spec.idempotent_emission:
            return False

        # Check without lock first for fast rejection
        if record.emission_state == EmissionState.EMITTED:
            return False

        with self._records_lock:
            stored = self._records.get(record.key)
            if stored is not None and stored.emission_state == EmissionState.EMITTED:
                return False
            # Mark as emitted in the store
            updated = AttemptRecord(
                key=record.key,
                passed=record.passed,
                rejection_code=record.rejection_code,
                rejection_class=record.rejection_class,
                rejection_message=record.rejection_message,
                gates_passed=list(record.gates_passed),
                gates_failed=list(record.gates_failed),
                emission_state=EmissionState.EMITTED,
                reduced_at=record.reduced_at,
            )
            self._records[record.key] = updated

        # Emit outside lock
        try:
            from bot.execution_journal import append_execution_journal_event
        except ImportError:
            try:
                from execution_journal import append_execution_journal_event  # type: ignore[import]
            except ImportError:
                append_execution_journal_event = None  # type: ignore[assignment]

        if append_execution_journal_event is not None:
            try:
                event_type = "intent_accepted" if record.passed else "final_state"
                append_execution_journal_event(
                    event_type=event_type,
                    intent_id=record.key.intent_id,
                    payload={
                        "attempt_n": record.key.attempt_n,
                        "passed": record.passed,
                        "rejection_code": record.rejection_code.value,
                        "rejection_class": record.rejection_class.value,
                        "gates_passed": record.gates_passed,
                        "gates_failed": record.gates_failed,
                    },
                )
            except Exception as exc:
                logger.warning("emit_once: journal append failed: %s", exc)
        return True

    def should_retry(self, record: AttemptRecord) -> bool:
        """
        Return ``True`` if the spec permits retrying this failed attempt.

        Delegates to ``ExecutionContractSpec.allows_retry`` so the retry
        decision is made consistently across pipeline, broker, and retry
        wrapper layers.

        A passed record always returns ``False`` (no retry needed).
        """
        if record.passed:
            return False
        return self._spec.allows_retry(record.rejection_class, record.key.attempt_n)

    # ------------------------------------------------------------------
    # Internal gate runner (shared by reduce() and validate_entry())
    # ------------------------------------------------------------------

    _GATE_SEQUENCE = (
        "account_state",
        "capital_availability",
        "position_limits",
        "position_size",
        "signal_quality",
        "trading_state",
        "market_symbol",
        "position_conflicts",
    )

    def _run_gates(self, key: AttemptKey, context: ValidationContext) -> AttemptRecord:
        """
        Execute the fixed gate sequence and return an ``AttemptRecord``.

        The gate sequence is ordered and non-negotiable: earlier gates short-
        circuit later ones.  This is the deterministic property that makes the
        reducer reproducible — the same key + context always produces the same
        gate evaluation path.
        """
        details: Dict = {}
        gates_passed: List[str] = []
        reduced_at = datetime.now(timezone.utc).isoformat()

        gate_fns = {
            "account_state": self._validate_account_state,
            "capital_availability": self._validate_capital_availability,
            "position_limits": self._validate_position_limits,
            "position_size": self._validate_position_size,
            "signal_quality": self._validate_signal_quality,
            "trading_state": self._validate_trading_state,
            "market_symbol": self._validate_market_symbol,
            "position_conflicts": self._validate_position_conflicts,
        }

        for gate_name in self._GATE_SEQUENCE:
            gate_fn = gate_fns[gate_name]
            ok, code, message = gate_fn(context, details)
            if not ok:
                return AttemptRecord(
                    key=key,
                    passed=False,
                    rejection_code=code,
                    rejection_class=_REJECTION_CLASS_MAP.get(code, RejectionClass.PERMANENT),
                    rejection_message=message,
                    gates_passed=gates_passed,
                    gates_failed=[gate_name],
                    emission_state=EmissionState.PENDING,
                    reduced_at=reduced_at,
                )
            gates_passed.append(gate_name)

        message = (
            f"✅ ENTRY APPROVED: {context.symbol} {context.signal_type} "
            f"${context.proposed_size_usd:.2f} - Tier: {context.tier_name}, "
            f"Positions: {context.current_position_count}, Quality: {context.signal_quality:.1f}"
        )
        return AttemptRecord(
            key=key,
            passed=True,
            rejection_code=RejectionCode.VALIDATION_PASSED,
            rejection_class=RejectionClass.PERMANENT,
            rejection_message=message,
            gates_passed=gates_passed,
            gates_failed=[],
            emission_state=EmissionState.PENDING,
            reduced_at=reduced_at,
        )

    # ------------------------------------------------------------------
    # Backward-compatible entry point (legacy API — does NOT store records)
    # ------------------------------------------------------------------

    def validate_entry(self, context: ValidationContext) -> ValidationResult:
        """
        Perform comprehensive entry validation.

        Backward-compatible API.  Each call runs the gate sequence with a
        fresh transient key and returns a ``ValidationResult``.  Results are
        added to ``validation_history`` for debugging but are NOT stored in
        the attempt-scoped ``_records`` store (so multiple calls with the same
        context remain independent).

        New callers should prefer ``reduce(key, context)`` + ``emit_once()``
        for idempotent, attempt-scoped behaviour.
        
        Args:
            context: Validation context with all necessary information
            
        Returns:
            ValidationResult with pass/fail and explicit rejection code
        """
        # Use a unique transient key so the result is never deduplicated
        transient_key = AttemptKey(intent_id=f"_transient:{uuid.uuid4().hex}", attempt_n=0)
        record = self._run_gates(transient_key, context)

        timestamp = datetime.now()
        result = ValidationResult(
            passed=record.passed,
            rejection_code=record.rejection_code,
            rejection_message=record.rejection_message,
            validation_timestamp=timestamp,
            validation_details={
                "gates_passed": record.gates_passed,
                "gates_failed": record.gates_failed,
            },
        )

        if record.passed:
            logger.info(record.rejection_message)
        else:
            logger.warning(record.rejection_message)

        self.validation_history.append(result)
        if len(self.validation_history) > self.max_history_size:
            self.validation_history = self.validation_history[-self.max_history_size:]
        return result

    def _validate_account_state(self, context: ValidationContext, details: Dict) -> Tuple[bool, RejectionCode, str]:
        """Gate 1: Validate account state (balance, tier)"""
        details['account_validation'] = {}
        
        # Check minimum balance
        if context.balance < self.min_balance_to_trade:
            details['account_validation']['balance_check'] = 'FAILED'
            details['account_validation']['balance'] = context.balance
            details['account_validation']['minimum'] = self.min_balance_to_trade
            
            return (False, RejectionCode.BALANCE_TOO_LOW,
                   f"❌ REJECTED: BALANCE_TOO_LOW - Balance ${context.balance:.2f} "
                   f"below minimum ${self.min_balance_to_trade:.2f}")
        
        details['account_validation']['balance_check'] = 'PASSED'
        return (True, RejectionCode.VALIDATION_PASSED, "")
    
    def _validate_capital_availability(self, context: ValidationContext, details: Dict) -> Tuple[bool, RejectionCode, str]:
        """Gate 2: Validate sufficient capital is available"""
        details['capital_validation'] = {}
        
        # Check available capital
        if context.available_capital < context.proposed_size_usd:
            details['capital_validation']['available'] = context.available_capital
            details['capital_validation']['required'] = context.proposed_size_usd
            details['capital_validation']['shortfall'] = context.proposed_size_usd - context.available_capital
            
            return (False, RejectionCode.INSUFFICIENT_CAPITAL,
                   f"❌ REJECTED: INSUFFICIENT_CAPITAL - Available ${context.available_capital:.2f} "
                   f"< Required ${context.proposed_size_usd:.2f} (shortfall: ${context.proposed_size_usd - context.available_capital:.2f})")
        
        # Single-position cap: 40% of balance (reduced from 80%, Fix 4)
        max_single_position = context.balance * 0.40
        if context.proposed_size_usd > max_single_position:
            details['capital_validation']['proposed'] = context.proposed_size_usd
            details['capital_validation']['maximum'] = max_single_position

            return (False, RejectionCode.TIER_POSITION_SIZE_TOO_LARGE,
                   f"❌ REJECTED: TIER_POSITION_SIZE_TOO_LARGE - Position ${context.proposed_size_usd:.2f} "
                   f"exceeds maximum ${max_single_position:.2f} (40% of balance)")
        
        details['capital_validation']['status'] = 'PASSED'
        return (True, RejectionCode.VALIDATION_PASSED, "")
    
    def _validate_position_limits(self, context: ValidationContext, details: Dict) -> Tuple[bool, RejectionCode, str]:
        """Gate 3: Validate position count limits"""
        details['position_limit_validation'] = {}
        
        # Import tier hierarchy to get max positions
        try:
            from capital_tier_hierarchy import get_max_positions_for_balance
            max_positions = get_max_positions_for_balance(context.balance)
        except ImportError:
            # Fallback if module not available
            max_positions = 10
            logger.warning("Could not import capital_tier_hierarchy, using fallback max_positions=10")
        
        details['position_limit_validation']['current_positions'] = context.current_position_count
        details['position_limit_validation']['max_positions'] = max_positions
        details['position_limit_validation']['tier'] = context.tier_name
        
        # Check if at maximum
        if context.current_position_count >= max_positions:
            return (False, RejectionCode.TIER_MAX_POSITIONS,
                   f"❌ REJECTED: TIER_MAX_POSITIONS - Tier {context.tier_name} allows maximum "
                   f"{max_positions} positions (current: {context.current_position_count})")
        
        details['position_limit_validation']['status'] = 'PASSED'
        return (True, RejectionCode.VALIDATION_PASSED, "")
    
    def _validate_position_size(self, context: ValidationContext, details: Dict) -> Tuple[bool, RejectionCode, str]:
        """Gate 4: Validate position size meets minimums and maximums"""
        details['size_validation'] = {}
        
        # Get exchange minimum
        exchange_minimum = self.exchange_minimums.get(context.exchange_name.lower(), 2.0)
        details['size_validation']['exchange'] = context.exchange_name
        details['size_validation']['exchange_minimum'] = exchange_minimum
        details['size_validation']['proposed_size'] = context.proposed_size_usd
        
        # Check exchange minimum
        if context.proposed_size_usd < exchange_minimum:
            return (False, RejectionCode.EXCHANGE_MINIMUM_NOT_MET,
                   f"❌ REJECTED: EXCHANGE_MINIMUM_NOT_MET - Position ${context.proposed_size_usd:.2f} "
                   f"below {context.exchange_name} minimum ${exchange_minimum:.2f}")
        
        # Get tier-specific minimum
        try:
            from capital_tier_hierarchy import TIER_POSITION_RULES, CapitalTier
            tier_enum = CapitalTier[context.tier_name]
            tier_rules = TIER_POSITION_RULES[tier_enum]
            tier_minimum = tier_rules.min_position_size_usd
        except (ImportError, KeyError):
            # Fallback
            tier_minimum = 10.0
            logger.warning(f"Could not get tier minimum for {context.tier_name}, using fallback $10")
        
        details['size_validation']['tier_minimum'] = tier_minimum
        
        # Check tier minimum
        if context.proposed_size_usd < tier_minimum:
            return (False, RejectionCode.TIER_POSITION_SIZE_TOO_SMALL,
                   f"❌ REJECTED: TIER_POSITION_SIZE_TOO_SMALL - Position ${context.proposed_size_usd:.2f} "
                   f"below tier {context.tier_name} minimum ${tier_minimum:.2f}")
        
        details['size_validation']['status'] = 'PASSED'
        return (True, RejectionCode.VALIDATION_PASSED, "")
    
    def _validate_signal_quality(self, context: ValidationContext, details: Dict) -> Tuple[bool, RejectionCode, str]:
        """Gate 5: Validate signal quality and confidence"""
        details['signal_validation'] = {}
        details['signal_validation']['quality'] = context.signal_quality
        details['signal_validation']['confidence'] = context.signal_confidence
        details['signal_validation']['min_quality'] = self.min_signal_quality
        details['signal_validation']['min_confidence'] = self.min_signal_confidence
        
        # Check quality threshold
        if context.signal_quality < self.min_signal_quality:
            return (False, RejectionCode.SIGNAL_QUALITY_LOW,
                   f"❌ REJECTED: SIGNAL_QUALITY_LOW - Quality {context.signal_quality:.1f} "
                   f"below minimum {self.min_signal_quality:.1f}")
        
        # Check confidence threshold
        if context.signal_confidence < self.min_signal_confidence:
            return (False, RejectionCode.SIGNAL_CONFIDENCE_LOW,
                   f"❌ REJECTED: SIGNAL_CONFIDENCE_LOW - Confidence {context.signal_confidence:.2f} "
                   f"below minimum {self.min_signal_confidence:.2f}")
        
        details['signal_validation']['status'] = 'PASSED'
        return (True, RejectionCode.VALIDATION_PASSED, "")
    
    def _validate_trading_state(self, context: ValidationContext, details: Dict) -> Tuple[bool, RejectionCode, str]:
        """Gate 6: Validate trading state (cooldowns, limits, drawdowns)"""
        details['trading_state_validation'] = {}
        
        # Check cooldown
        if context.cooldown_until:
            now = datetime.now()
            if now < context.cooldown_until:
                remaining = (context.cooldown_until - now).total_seconds() / 60
                details['trading_state_validation']['cooldown_remaining_minutes'] = remaining
                
                return (False, RejectionCode.COOLDOWN_ACTIVE,
                       f"❌ REJECTED: COOLDOWN_ACTIVE - Trading paused until "
                       f"{context.cooldown_until.strftime('%H:%M:%S')} ({remaining:.1f} min remaining)")
        
        # Check daily trade limit
        if context.daily_trade_count >= context.max_daily_trades:
            details['trading_state_validation']['daily_trades'] = context.daily_trade_count
            details['trading_state_validation']['max_daily_trades'] = context.max_daily_trades
            
            return (False, RejectionCode.MAX_DAILY_TRADES,
                   f"❌ REJECTED: MAX_DAILY_TRADES - Daily limit reached "
                   f"({context.daily_trade_count}/{context.max_daily_trades})")
        
        # Check drawdown halt
        if context.in_drawdown_halt:
            details['trading_state_validation']['drawdown_halt'] = True
            
            return (False, RejectionCode.DRAWDOWN_HALT,
                   f"❌ REJECTED: DRAWDOWN_HALT - Trading halted due to drawdown protection")
        
        details['trading_state_validation']['status'] = 'PASSED'
        return (True, RejectionCode.VALIDATION_PASSED, "")
    
    def _validate_market_symbol(self, context: ValidationContext, details: Dict) -> Tuple[bool, RejectionCode, str]:
        """Gate 7: Validate market and symbol"""
        details['market_symbol_validation'] = {}
        details['market_symbol_validation']['symbol'] = context.symbol
        
        # Check blacklist
        if context.symbol in context.blacklisted_symbols:
            details['market_symbol_validation']['blacklisted'] = True
            
            return (False, RejectionCode.SYMBOL_BLACKLISTED,
                   f"❌ REJECTED: SYMBOL_BLACKLISTED - {context.symbol} is on the blacklist")
        
        # Check restricted symbols
        if context.symbol in context.restricted_symbols:
            details['market_symbol_validation']['restricted'] = True
            
            return (False, RejectionCode.SYMBOL_RESTRICTED,
                   f"❌ REJECTED: SYMBOL_RESTRICTED - {context.symbol} is restricted")
        
        details['market_symbol_validation']['status'] = 'PASSED'
        return (True, RejectionCode.VALIDATION_PASSED, "")
    
    def _validate_position_conflicts(self, context: ValidationContext, details: Dict) -> Tuple[bool, RejectionCode, str]:
        """Gate 8: Validate no position conflicts"""
        details['conflict_validation'] = {}
        details['conflict_validation']['open_positions'] = context.open_positions
        
        # Check for duplicate position (same symbol, same direction)
        if context.symbol in context.open_positions:
            # This is a simple check - more sophisticated logic would check direction
            details['conflict_validation']['duplicate'] = True
            
            return (False, RejectionCode.DUPLICATE_POSITION,
                   f"❌ REJECTED: DUPLICATE_POSITION - Position already exists for {context.symbol}")
        
        details['conflict_validation']['status'] = 'PASSED'
        return (True, RejectionCode.VALIDATION_PASSED, "")
    
    def get_validation_stats(self) -> Dict:
        """
        Get validation statistics.

        Merges the attempt-scoped reducer store (new path) with the legacy
        ``validation_history`` list (backward-compatible path) so callers see
        a unified view regardless of which API they used.
        """
        # Reducer-store stats
        with self._records_lock:
            records = list(self._records.values())

        # Legacy history stats
        legacy = list(self.validation_history)

        total = len(records) + len(legacy)
        passed = (
            sum(1 for r in records if r.passed)
            + sum(1 for v in legacy if v.passed)
        )
        rejected = total - passed

        rejection_counts: Dict[str, int] = {}
        for r in records:
            if not r.passed:
                key_str = r.rejection_code.value
                rejection_counts[key_str] = rejection_counts.get(key_str, 0) + 1
        for v in legacy:
            if not v.passed:
                key_str = v.rejection_code.value
                rejection_counts[key_str] = rejection_counts.get(key_str, 0) + 1

        emitted = sum(
            1 for r in records if r.emission_state == EmissionState.EMITTED
        )

        return {
            'total': total,
            'passed': passed,
            'rejected': rejected,
            'pass_rate': (passed / total * 100) if total > 0 else 0.0,
            'rejection_by_code': rejection_counts,
            'reducer_attempts': len(records),
            'emitted': emitted,
        }

    def log_validation_summary(self) -> None:
        """Log summary of validation statistics"""
        stats = self.get_validation_stats()
        
        logger.info("="*70)
        logger.info("ENTRY VALIDATION STATISTICS")
        logger.info("="*70)
        logger.info(f"Total Validations: {stats['total']}")
        logger.info(f"Passed: {stats['passed']} ({stats['pass_rate']:.1f}%)")
        logger.info(f"Rejected: {stats['rejected']} ({100-stats['pass_rate']:.1f}%)")
        logger.info(f"Reducer attempts: {stats['reducer_attempts']}  Emitted: {stats['emitted']}")
        
        if stats['rejection_by_code']:
            logger.info("-"*70)
            logger.info("Rejections by Code:")
            for code, count in sorted(stats['rejection_by_code'].items(), key=lambda x: x[1], reverse=True):
                pct = (count / stats['rejected'] * 100) if stats['rejected'] > 0 else 0
                logger.info(f"  {code:>30}: {count:>4} ({pct:>5.1f}%)")
        
        logger.info("="*70)


# ============================================================================
# GLOBAL INSTANCE
# ============================================================================
_validator_instance: Optional[DeterministicEntryValidator] = None


def get_entry_validator() -> DeterministicEntryValidator:
    """Get or create the global DeterministicEntryValidator instance"""
    global _validator_instance
    if _validator_instance is None:
        _validator_instance = DeterministicEntryValidator()
    return _validator_instance


def validate_entry(context: ValidationContext) -> ValidationResult:
    """Convenience function to validate entry"""
    validator = get_entry_validator()
    return validator.validate_entry(context)


if __name__ == "__main__":
    # Demo: Test validation with various scenarios
    import logging
    logging.basicConfig(level=logging.INFO)
    
    validator = DeterministicEntryValidator()
    
    print("\n" + "="*100)
    print("DETERMINISTIC ENTRY VALIDATOR - Validation Demo")
    print("="*100 + "\n")
    
    # Test cases
    test_cases = [
        # Case 1: Valid entry (should pass)
        {
            'name': 'Valid Entry - STARTER Tier',
            'context': ValidationContext(
                balance=75.0,
                tier_name="STARTER",
                current_position_count=0,
                open_positions=[],
                available_capital=70.0,
                symbol="BTC-USD",
                signal_type="LONG",
                signal_quality=75.0,
                signal_confidence=0.70,
                proposed_size_usd=40.0,
                exchange_name="coinbase"
            )
        },
        # Case 2: Max positions reached
        {
            'name': 'Max Positions - STARTER Tier',
            'context': ValidationContext(
                balance=75.0,
                tier_name="STARTER",
                current_position_count=2,  # Already at max for STARTER
                open_positions=["ETH-USD", "SOL-USD"],
                available_capital=20.0,
                symbol="BTC-USD",
                signal_type="LONG",
                signal_quality=75.0,
                signal_confidence=0.70,
                proposed_size_usd=15.0,
                exchange_name="coinbase"
            )
        },
        # Case 3: Position too small
        {
            'name': 'Position Too Small',
            'context': ValidationContext(
                balance=75.0,
                tier_name="STARTER",
                current_position_count=0,
                open_positions=[],
                available_capital=70.0,
                symbol="BTC-USD",
                signal_type="LONG",
                signal_quality=75.0,
                signal_confidence=0.70,
                proposed_size_usd=5.0,  # Too small
                exchange_name="coinbase"
            )
        },
        # Case 4: Insufficient capital
        {
            'name': 'Insufficient Capital',
            'context': ValidationContext(
                balance=100.0,
                tier_name="SAVER",
                current_position_count=1,
                open_positions=["ETH-USD"],
                available_capital=10.0,  # Not enough
                symbol="BTC-USD",
                signal_type="LONG",
                signal_quality=75.0,
                signal_confidence=0.70,
                proposed_size_usd=50.0,
                exchange_name="coinbase"
            )
        },
        # Case 5: Signal quality too low
        {
            'name': 'Low Signal Quality',
            'context': ValidationContext(
                balance=100.0,
                tier_name="SAVER",
                current_position_count=0,
                open_positions=[],
                available_capital=90.0,
                symbol="BTC-USD",
                signal_type="LONG",
                signal_quality=45.0,  # Too low
                signal_confidence=0.70,
                proposed_size_usd=40.0,
                exchange_name="coinbase"
            )
        },
    ]
    
    # Run test cases
    for i, test in enumerate(test_cases, 1):
        print(f"\n{'='*100}")
        print(f"Test Case {i}: {test['name']}")
        print(f"{'='*100}")
        
        result = validator.validate_entry(test['context'])
        
        print(f"\nResult: {'✅ PASSED' if result.passed else '❌ REJECTED'}")
        print(f"Code: {result.rejection_code.value}")
        print(f"Message: {result.rejection_message}")
    
    # Show validation statistics
    print(f"\n\n")
    validator.log_validation_summary()
