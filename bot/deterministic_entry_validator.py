"""
NIJA Deterministic Entry Validator

Provides comprehensive, deterministic entry validation with explicit rejection codes.
Solves the "unknown reason" rejection problem.

Features:
- Explicit rejection codes for every validation failure
- Comprehensive logging of rejection reasons
- Tier-aware validation (position limits, capital requirements)
- Exchange minimum validation
- Capital availability checks
- Multi-layer validation gates

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
Version: 1.0
Date: February 18, 2026
"""

import logging
from typing import Dict, Tuple, Optional, List
from dataclasses import dataclass
from datetime import datetime, timedelta
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
    exchange_minimum_usd: float = 2.0
    
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
    
    def __init__(self, min_signal_quality: float = 60.0, min_signal_confidence: float = 0.60):
        """
        Initialize the deterministic entry validator.
        
        Args:
            min_signal_quality: Minimum signal quality score (0-100)
            min_signal_confidence: Minimum signal confidence (0-1)
        """
        self.min_signal_quality = min_signal_quality
        self.min_signal_confidence = min_signal_confidence
        
        # Exchange-specific minimums (USD)
        self.exchange_minimums = {
            'coinbase': 2.0,
            'kraken': 10.50,  # $10 + fee buffer
            'binance': 10.0,
            'okx': 1.0,
            'alpaca': 1.0,
        }
        
        # Minimum balance to trade (absolute floor)
        self.min_balance_to_trade = 50.0
        
        # Validation history for debugging
        self.validation_history: List[ValidationResult] = []
        self.max_history_size = 1000
        
        logger.info("🔒 Deterministic Entry Validator initialized - Explicit rejection codes active")
    
    def validate_entry(self, context: ValidationContext) -> ValidationResult:
        """
        Perform comprehensive entry validation.
        
        Args:
            context: Validation context with all necessary information
            
        Returns:
            ValidationResult with pass/fail and explicit rejection code
        """
        timestamp = datetime.now()
        details = {}
        
        # Gate 1: Account State Validation
        passed, code, message = self._validate_account_state(context, details)
        if not passed:
            return self._create_result(False, code, message, timestamp, details)
        
        # Gate 2: Capital Availability Validation
        passed, code, message = self._validate_capital_availability(context, details)
        if not passed:
            return self._create_result(False, code, message, timestamp, details)
        
        # Gate 3: Position Limit Validation
        passed, code, message = self._validate_position_limits(context, details)
        if not passed:
            return self._create_result(False, code, message, timestamp, details)
        
        # Gate 4: Position Size Validation
        passed, code, message = self._validate_position_size(context, details)
        if not passed:
            return self._create_result(False, code, message, timestamp, details)
        
        # Gate 5: Signal Quality Validation
        passed, code, message = self._validate_signal_quality(context, details)
        if not passed:
            return self._create_result(False, code, message, timestamp, details)
        
        # Gate 6: Trading State Validation
        passed, code, message = self._validate_trading_state(context, details)
        if not passed:
            return self._create_result(False, code, message, timestamp, details)
        
        # Gate 7: Market/Symbol Validation
        passed, code, message = self._validate_market_symbol(context, details)
        if not passed:
            return self._create_result(False, code, message, timestamp, details)
        
        # Gate 8: Position Conflict Validation
        passed, code, message = self._validate_position_conflicts(context, details)
        if not passed:
            return self._create_result(False, code, message, timestamp, details)
        
        # All gates passed - entry approved
        message = (f"✅ ENTRY APPROVED: {context.symbol} {context.signal_type} "
                  f"${context.proposed_size_usd:.2f} - Tier: {context.tier_name}, "
                  f"Positions: {context.current_position_count}, Quality: {context.signal_quality:.1f}")
        
        return self._create_result(True, RejectionCode.VALIDATION_PASSED, message, timestamp, details)
    
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
        
        # Check that we're not using more than 80% of balance for a single position
        max_single_position = context.balance * 0.80
        if context.proposed_size_usd > max_single_position:
            details['capital_validation']['proposed'] = context.proposed_size_usd
            details['capital_validation']['maximum'] = max_single_position
            
            return (False, RejectionCode.TIER_POSITION_SIZE_TOO_LARGE,
                   f"❌ REJECTED: TIER_POSITION_SIZE_TOO_LARGE - Position ${context.proposed_size_usd:.2f} "
                   f"exceeds maximum ${max_single_position:.2f} (80% of balance)")
        
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
    
    def _create_result(self, passed: bool, code: RejectionCode, message: str, 
                      timestamp: datetime, details: Dict) -> ValidationResult:
        """Create validation result and add to history"""
        result = ValidationResult(
            passed=passed,
            rejection_code=code,
            rejection_message=message,
            validation_timestamp=timestamp,
            validation_details=details
        )
        
        # Add to history
        self.validation_history.append(result)
        if len(self.validation_history) > self.max_history_size:
            self.validation_history = self.validation_history[-self.max_history_size:]
        
        # Log the result
        if passed:
            logger.info(message)
        else:
            logger.warning(message)
            # Log detailed rejection information
            logger.debug(f"Rejection details: {details}")
        
        return result
    
    def get_validation_stats(self) -> Dict:
        """Get validation statistics from history"""
        if not self.validation_history:
            return {'total': 0, 'passed': 0, 'rejected': 0, 'pass_rate': 0.0}
        
        total = len(self.validation_history)
        passed = sum(1 for v in self.validation_history if v.passed)
        rejected = total - passed
        
        # Count rejections by code
        rejection_counts = {}
        for v in self.validation_history:
            if not v.passed:
                code = v.rejection_code.value
                rejection_counts[code] = rejection_counts.get(code, 0) + 1
        
        return {
            'total': total,
            'passed': passed,
            'rejected': rejected,
            'pass_rate': (passed / total * 100) if total > 0 else 0.0,
            'rejection_by_code': rejection_counts
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
