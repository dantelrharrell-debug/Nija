"""
NIJA Institutional Integration Layer

Integrates the three-tier enhancement system with existing NIJA infrastructure:
1. Entry Audit System → Strategy and Validator
2. Position Architecture → Execution Engine and Position Manager  
3. Capital Tier Scaling → Risk Manager and Position Sizing

This module provides a unified interface for institutional-grade trading.

Author: NIJA Trading Systems
Version: 1.0
Date: February 18, 2026
"""

import logging
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger("nija.institutional")

# Import the three core systems
try:
    from entry_audit_system import (
        get_entry_audit_system,
        EntryAuditRecord,
        EntryTrigger,
        EntryQuality,
        SignalHierarchy,
        EntryValidationStep,
        LiquidityCheck,
        SlippageEstimate,
        RejectionCategory
    )
    ENTRY_AUDIT_AVAILABLE = True
except ImportError:
    try:
        from bot.entry_audit_system import (
            get_entry_audit_system,
            EntryAuditRecord,
            EntryTrigger,
            EntryQuality,
            SignalHierarchy,
            EntryValidationStep,
            LiquidityCheck,
            SlippageEstimate,
            RejectionCategory
        )
        ENTRY_AUDIT_AVAILABLE = True
    except ImportError:
        ENTRY_AUDIT_AVAILABLE = False
        logger.warning("⚠️ Entry Audit System not available")

try:
    from position_architecture import (
        get_position_architecture,
        PositionArchitecture,
        ExposureLimits,
        DrawdownLock,
        PositionState
    )
    POSITION_ARCHITECTURE_AVAILABLE = True
except ImportError:
    try:
        from bot.position_architecture import (
            get_position_architecture,
            PositionArchitecture,
            ExposureLimits,
            DrawdownLock,
            PositionState
        )
        POSITION_ARCHITECTURE_AVAILABLE = True
    except ImportError:
        POSITION_ARCHITECTURE_AVAILABLE = False
        logger.warning("⚠️ Position Architecture not available")

try:
    from capital_tier_scaling import (
        get_capital_tier_system,
        CapitalTierSystem,
        TierLevel,
        TierConfiguration
    )
    CAPITAL_TIER_AVAILABLE = True
except ImportError:
    try:
        from bot.capital_tier_scaling import (
            get_capital_tier_system,
            CapitalTierSystem,
            TierLevel,
            TierConfiguration
        )
        CAPITAL_TIER_AVAILABLE = True
    except ImportError:
        CAPITAL_TIER_AVAILABLE = False
        logger.warning("⚠️ Capital Tier Scaling not available")


@dataclass
class InstitutionalContext:
    """
    Unified context for institutional trading decisions.
    Combines all three systems into a single decision-making context.
    """
    # Account state
    account_balance: float
    available_capital: float
    
    # Tier information
    tier_level: str
    tier_config: Dict
    
    # Position state
    current_positions: int
    max_positions: int
    total_exposure_pct: float
    
    # Locks and restrictions
    drawdown_locked: bool
    drawdown_reason: Optional[str]
    
    # Entry requirements
    min_confidence: float
    min_quality: float
    require_high_confidence: bool
    prioritize_stability: bool


class InstitutionalIntegration:
    """
    Unified institutional trading integration.
    
    Provides a single interface for:
    - Entry validation and audit logging
    - Position architecture enforcement
    - Capital tier scaling
    """
    
    def __init__(self, initial_balance: float, broker_name: str = "coinbase"):
        """
        Initialize institutional integration.
        
        Args:
            initial_balance: Starting account balance
            broker_name: Broker/exchange name
        """
        self.broker_name = broker_name
        
        # Initialize systems
        self.entry_audit = None
        self.position_arch = None
        self.capital_tier = None
        
        if ENTRY_AUDIT_AVAILABLE:
            self.entry_audit = get_entry_audit_system()
            logger.info("✅ Entry Audit System connected")
        
        if CAPITAL_TIER_AVAILABLE:
            self.capital_tier = get_capital_tier_system(initial_balance)
            logger.info("✅ Capital Tier System connected")
        
        if POSITION_ARCHITECTURE_AVAILABLE and self.capital_tier:
            tier_config = self.capital_tier.get_config()
            max_positions = tier_config.max_positions[1]  # Use max from range
            self.position_arch = get_position_architecture(
                self.capital_tier.current_tier.value,
                initial_balance,
                max_positions
            )
            logger.info("✅ Position Architecture connected")
        
        self.all_systems_active = (
            ENTRY_AUDIT_AVAILABLE and 
            POSITION_ARCHITECTURE_AVAILABLE and 
            CAPITAL_TIER_AVAILABLE
        )
        
        if self.all_systems_active:
            logger.info("🏛️ Institutional Integration ACTIVE - All systems online")
        else:
            logger.warning("⚠️ Institutional Integration PARTIAL - Some systems unavailable")
    
    def update_balance(self, new_balance: float):
        """Update account balance across all systems"""
        if self.capital_tier:
            old_tier = self.capital_tier.current_tier
            self.capital_tier.update_balance(new_balance)
            new_tier = self.capital_tier.current_tier
            
            # If tier changed, update position architecture
            if self.position_arch and old_tier != new_tier:
                tier_config = self.capital_tier.get_config()
                max_positions = tier_config.max_positions[1]
                self.position_arch = get_position_architecture(
                    new_tier.value,
                    new_balance,
                    max_positions
                )
                logger.info(f"🔄 Position architecture updated for new tier: {new_tier.value}")
    
    def get_context(self) -> Optional[InstitutionalContext]:
        """Get unified institutional context"""
        if not self.all_systems_active:
            return None
        
        tier_info = self.capital_tier.get_tier_info()
        tier_config = self.capital_tier.get_config()
        arch_status = self.position_arch.get_architecture_status()
        
        is_locked, lock_reason = self.position_arch.drawdown_lock.is_locked()
        
        return InstitutionalContext(
            account_balance=self.capital_tier.current_balance,
            available_capital=self.capital_tier.current_balance * (1.0 - arch_status['exposure']['total_pct']),
            tier_level=tier_info['tier'],
            tier_config=tier_info['config'],
            current_positions=arch_status['positions']['current'],
            max_positions=arch_status['positions']['max'],
            total_exposure_pct=arch_status['exposure']['total_pct'],
            drawdown_locked=is_locked,
            drawdown_reason=lock_reason,
            min_confidence=0.65 if tier_config.require_high_confidence else 0.50,
            min_quality=75.0 if tier_config.prioritize_stability else 60.0,
            require_high_confidence=tier_config.require_high_confidence,
            prioritize_stability=tier_config.prioritize_stability
        )
    
    def validate_entry_comprehensive(
        self,
        symbol: str,
        signal_type: str,
        entry_score: float,
        confidence: float,
        signal_contributions: Dict[str, float],
        primary_trigger: str,
        price: float,
        proposed_size_usd: float,
        stop_loss_price: float,
        adx: Optional[float] = None,
        rsi: Optional[float] = None,
        volume_24h: Optional[float] = None
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Comprehensive entry validation using all three systems.
        
        Args:
            symbol: Trading symbol
            signal_type: LONG or SHORT
            entry_score: Entry score (0-5)
            confidence: Confidence score (0-1)
            signal_contributions: Dict of indicator contributions
            primary_trigger: Primary entry trigger
            price: Current price
            proposed_size_usd: Proposed position size
            stop_loss_price: Stop loss price
            adx, rsi, volume_24h: Market indicators
            
        Returns:
            (allowed, reason, audit_id) - audit_id for outcome tracking
        """
        if not self.all_systems_active:
            return True, "Institutional integration not active - allowing entry", None
        
        context = self.get_context()
        audit_id = str(uuid.uuid4())
        
        # Build signal hierarchy
        signal_hierarchy = SignalHierarchy(
            primary_trigger=self._map_trigger(primary_trigger),
            rsi_contribution=signal_contributions.get('rsi', 0.0),
            vwap_contribution=signal_contributions.get('vwap', 0.0),
            macd_contribution=signal_contributions.get('macd', 0.0),
            ema_contribution=signal_contributions.get('ema', 0.0),
            volume_contribution=signal_contributions.get('volume', 0.0),
            adx_contribution=signal_contributions.get('adx', 0.0),
            bollinger_contribution=signal_contributions.get('bollinger', 0.0)
        )
        
        # Determine entry quality
        entry_quality = self._classify_quality(confidence)
        
        # Validation steps
        validation_steps = []
        
        # Step 1: Check duplicate entry
        if self.entry_audit.check_duplicate_entry(symbol, lookback_minutes=5):
            return self._reject_entry(
                audit_id, symbol, signal_type, entry_score, confidence,
                signal_hierarchy, entry_quality, proposed_size_usd,
                price, stop_loss_price, context, adx, rsi, volume_24h,
                "DUPLICATE_ENTRY", RejectionCategory.RISK_MANAGEMENT,
                "Duplicate entry detected within 5 minutes", validation_steps
            )
        
        validation_steps.append(EntryValidationStep(
            step_name="Duplicate Check",
            passed=True,
            value=None,
            threshold=None,
            reason="No duplicate entry",
            timestamp=datetime.now()
        ))
        
        # Step 2: Check drawdown lock
        if context.drawdown_locked:
            return self._reject_entry(
                audit_id, symbol, signal_type, entry_score, confidence,
                signal_hierarchy, entry_quality, proposed_size_usd,
                price, stop_loss_price, context, adx, rsi, volume_24h,
                "DRAWDOWN_LOCK", RejectionCategory.RISK_MANAGEMENT,
                f"Drawdown lock active: {context.drawdown_reason}", validation_steps
            )
        
        validation_steps.append(EntryValidationStep(
            step_name="Drawdown Lock",
            passed=True,
            value=None,
            threshold=None,
            reason="No drawdown lock",
            timestamp=datetime.now()
        ))
        
        # Step 3: Check tier-based signal requirements
        tier_accept, tier_reason = self.capital_tier.should_accept_signal(confidence, entry_score)
        if not tier_accept:
            return self._reject_entry(
                audit_id, symbol, signal_type, entry_score, confidence,
                signal_hierarchy, entry_quality, proposed_size_usd,
                price, stop_loss_price, context, adx, rsi, volume_24h,
                "TIER_REQUIREMENTS", RejectionCategory.SIGNAL_QUALITY,
                tier_reason, validation_steps
            )
        
        validation_steps.append(EntryValidationStep(
            step_name="Tier Requirements",
            passed=True,
            value=confidence,
            threshold=context.min_confidence,
            reason="Signal meets tier requirements",
            timestamp=datetime.now()
        ))
        
        # Step 4: Check position architecture limits
        can_open, arch_reason = self.position_arch.can_open_position(symbol, proposed_size_usd)
        if not can_open:
            return self._reject_entry(
                audit_id, symbol, signal_type, entry_score, confidence,
                signal_hierarchy, entry_quality, proposed_size_usd,
                price, stop_loss_price, context, adx, rsi, volume_24h,
                "POSITION_LIMIT", RejectionCategory.POSITION_LIMIT,
                arch_reason, validation_steps
            )
        
        validation_steps.append(EntryValidationStep(
            step_name="Position Architecture",
            passed=True,
            value=context.current_positions,
            threshold=float(context.max_positions),
            reason="Position limits OK",
            timestamp=datetime.now()
        ))
        
        # All validations passed - log approved entry
        self._approve_entry(
            audit_id, symbol, signal_type, entry_score, confidence,
            signal_hierarchy, entry_quality, proposed_size_usd,
            price, stop_loss_price, context, adx, rsi, volume_24h,
            validation_steps
        )
        
        return True, "Entry approved by institutional validation", audit_id
    
    def register_position_opened(self, symbol: str, size_usd: float, 
                                entry_price: float, side: str, stop_loss: float,
                                audit_id: Optional[str] = None):
        """Register that a position was opened"""
        if self.position_arch:
            self.position_arch.register_position(symbol, size_usd, entry_price, side, stop_loss)
        
        if self.entry_audit and audit_id:
            # Update audit record with execution details
            for record in self.entry_audit.recent_audits:
                if record.audit_id == audit_id:
                    record.executed = True
                    record.execution_price = entry_price
                    record.execution_timestamp = datetime.now()
                    record.actual_slippage_pct = 0.0  # Would calculate from expected vs actual
                    break
    
    def update_position_price(self, symbol: str, current_price: float):
        """Update position with current price"""
        if self.position_arch:
            self.position_arch.update_position(symbol, current_price)
    
    def register_position_closed(self, symbol: str, exit_price: float, 
                                pnl_usd: float, audit_id: Optional[str] = None):
        """Register that a position was closed"""
        if self.position_arch:
            self.position_arch.close_position(symbol, exit_price, pnl_usd)
        
        if self.entry_audit and audit_id:
            self.entry_audit.update_outcome(audit_id, exit_price, pnl_usd, datetime.now())
    
    def get_positions_to_force_close(self) -> List[str]:
        """Get list of positions that should be force-closed"""
        if self.position_arch:
            return self.position_arch.get_positions_to_force_close()
        return []
    
    def should_reduce_positions(self) -> Tuple[bool, int]:
        """Check if positions should be reduced due to volatility"""
        if self.position_arch:
            return self.position_arch.should_reduce_positions()
        return False, 0
    
    def calculate_position_size(self, signal_confidence: float) -> float:
        """Calculate position size based on tier and confidence"""
        if not self.capital_tier:
            return 0.0
        
        context = self.get_context()
        if not context:
            return 0.0
        
        return self.capital_tier.calculate_position_size(
            signal_confidence,
            context.available_capital
        )
    
    def print_daily_summary(self):
        """Print daily summary from all systems"""
        if self.entry_audit:
            self.entry_audit.print_daily_summary()
        
        if self.position_arch:
            self.position_arch.print_status()
        
        if self.capital_tier:
            self.capital_tier.print_status()
    
    def _map_trigger(self, trigger_str: str) -> EntryTrigger:
        """Map trigger string to EntryTrigger enum"""
        trigger_map = {
            'rsi': EntryTrigger.RSI_OVERSOLD,
            'vwap': EntryTrigger.VWAP_PULLBACK,
            'macd': EntryTrigger.MACD_CROSS,
            'ema': EntryTrigger.EMA_PULLBACK,
            'volume': EntryTrigger.VOLUME_SPIKE,
            'bollinger': EntryTrigger.BOLLINGER_BOUNCE,
            'adx': EntryTrigger.ADX_TREND,
            'multi': EntryTrigger.MULTI_FACTOR,
        }
        return trigger_map.get(trigger_str.lower(), EntryTrigger.UNKNOWN)
    
    def _classify_quality(self, confidence: float) -> EntryQuality:
        """Classify entry quality based on confidence"""
        if confidence >= 0.90:
            return EntryQuality.EXCELLENT
        elif confidence >= 0.75:
            return EntryQuality.GOOD
        elif confidence >= 0.60:
            return EntryQuality.ACCEPTABLE
        elif confidence >= 0.50:
            return EntryQuality.MARGINAL
        else:
            return EntryQuality.POOR
    
    def _reject_entry(self, audit_id: str, symbol: str, signal_type: str,
                     entry_score: float, confidence: float,
                     signal_hierarchy: SignalHierarchy, entry_quality: EntryQuality,
                     proposed_size_usd: float, price: float, stop_loss_price: float,
                     context: InstitutionalContext, adx: Optional[float],
                     rsi: Optional[float], volume_24h: Optional[float],
                     rejection_code: str, rejection_category: RejectionCategory,
                     rejection_message: str, validation_steps: List) -> Tuple[bool, str, None]:
        """Helper to reject entry and log audit record"""
        
        stop_loss_pct = abs(price - stop_loss_price) / price if stop_loss_price else None
        
        record = EntryAuditRecord(
            audit_id=audit_id,
            timestamp=datetime.now(),
            symbol=symbol,
            signal_type=signal_type,
            entry_allowed=False,
            rejection_code=rejection_code,
            rejection_category=rejection_category,
            rejection_message=rejection_message,
            signal_hierarchy=signal_hierarchy,
            entry_quality=entry_quality,
            confidence_score=confidence,
            entry_score=entry_score,
            validation_steps=validation_steps,
            proposed_size_usd=proposed_size_usd,
            risk_per_trade_pct=proposed_size_usd / context.account_balance,
            stop_loss_price=stop_loss_price,
            stop_loss_pct=stop_loss_pct,
            liquidity_check=None,
            slippage_estimate=None,
            price=price,
            adx=adx,
            rsi=rsi,
            volume_24h=volume_24h,
            account_balance=context.account_balance,
            tier_name=context.tier_level,
            position_count=context.current_positions,
            max_positions=context.max_positions
        )
        
        if self.entry_audit:
            self.entry_audit.log_entry_decision(record)
        
        return False, rejection_message, None
    
    def _approve_entry(self, audit_id: str, symbol: str, signal_type: str,
                      entry_score: float, confidence: float,
                      signal_hierarchy: SignalHierarchy, entry_quality: EntryQuality,
                      proposed_size_usd: float, price: float, stop_loss_price: float,
                      context: InstitutionalContext, adx: Optional[float],
                      rsi: Optional[float], volume_24h: Optional[float],
                      validation_steps: List):
        """Helper to approve entry and log audit record"""
        
        stop_loss_pct = abs(price - stop_loss_price) / price if stop_loss_price else None
        
        record = EntryAuditRecord(
            audit_id=audit_id,
            timestamp=datetime.now(),
            symbol=symbol,
            signal_type=signal_type,
            entry_allowed=True,
            rejection_code=None,
            rejection_category=None,
            rejection_message=None,
            signal_hierarchy=signal_hierarchy,
            entry_quality=entry_quality,
            confidence_score=confidence,
            entry_score=entry_score,
            validation_steps=validation_steps,
            proposed_size_usd=proposed_size_usd,
            risk_per_trade_pct=proposed_size_usd / context.account_balance,
            stop_loss_price=stop_loss_price,
            stop_loss_pct=stop_loss_pct,
            liquidity_check=None,
            slippage_estimate=None,
            price=price,
            adx=adx,
            rsi=rsi,
            volume_24h=volume_24h,
            account_balance=context.account_balance,
            tier_name=context.tier_level,
            position_count=context.current_positions,
            max_positions=context.max_positions
        )
        
        if self.entry_audit:
            self.entry_audit.log_entry_decision(record)


# Global instance
_institutional_integration = None


def get_institutional_integration(balance: float, broker_name: str = "coinbase") -> InstitutionalIntegration:
    """Get or create institutional integration instance"""
    global _institutional_integration
    if _institutional_integration is None:
        _institutional_integration = InstitutionalIntegration(balance, broker_name)
    else:
        _institutional_integration.update_balance(balance)
    return _institutional_integration


def is_institutional_mode_available() -> bool:
    """Check if all institutional systems are available"""
    return ENTRY_AUDIT_AVAILABLE and POSITION_ARCHITECTURE_AVAILABLE and CAPITAL_TIER_AVAILABLE
