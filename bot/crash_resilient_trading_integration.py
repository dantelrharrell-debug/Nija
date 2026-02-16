"""
NIJA Crash-Resilient Trading Integration
=========================================

Integration layer that connects the institutional infrastructure coordinator
with the main trading strategy to create crash-resilient trading operations.

This module provides:
- Pre-trade validation with all institutional checks
- Post-trade monitoring and adjustment
- Automatic position sizing based on regime and liquidity
- Emergency response to market stress
- Continuous crash resilience validation

Usage:
    from crash_resilient_trading_integration import CrashResilientTrader
    
    trader = CrashResilientTrader(broker_client, config)
    can_trade, reason, params = trader.validate_trade(symbol, side, value, market_data)
    if can_trade:
        # Execute trade with adjusted params
        pass

Author: NIJA Trading Systems
Version: 1.0
Date: February 2026
"""

import logging
from typing import Dict, Optional, Tuple, List, Any
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger("nija.crash_resilient_trading")


@dataclass
class TradeValidationResult:
    """Result of trade validation through institutional infrastructure"""
    approved: bool
    reason: str
    adjusted_params: Dict
    warnings: List[str]
    regime: Optional[str] = None
    liquidity_score: Optional[float] = None
    sector_exposure: Optional[float] = None
    portfolio_state: Optional[str] = None


class CrashResilientTrader:
    """
    Crash-resilient trading integration that uses institutional infrastructure
    to validate and adjust trades for maximum safety and performance.
    """
    
    def __init__(self, broker_client=None, config: Optional[Dict] = None):
        """
        Initialize crash-resilient trader
        
        Args:
            broker_client: Broker client for trade execution
            config: Optional configuration dictionary
        """
        self.broker_client = broker_client
        self.config = config or {}
        
        # Initialize institutional coordinator
        try:
            from institutional_infrastructure_coordinator import get_institutional_coordinator
            self.coordinator = get_institutional_coordinator(self.config)
            self.enabled = True
            logger.info("✅ Crash-resilient trading integration enabled")
        except ImportError:
            try:
                from bot.institutional_infrastructure_coordinator import get_institutional_coordinator
                self.coordinator = get_institutional_coordinator(self.config)
                self.enabled = True
                logger.info("✅ Crash-resilient trading integration enabled")
            except ImportError:
                self.coordinator = None
                self.enabled = False
                logger.warning("⚠️ Institutional coordinator not available - crash resilience disabled")
        
        # Track validation history
        self.validation_history = []
        self.last_crash_validation = None
        self.crash_validation_interval_hours = self.config.get('crash_validation_interval_hours', 24)
        
        # Emergency settings
        self.emergency_mode = False
        self.emergency_reason = None
        
    def validate_trade(
        self,
        symbol: str,
        side: str,
        position_value: float,
        market_data: Dict,
        indicators: Optional[Dict] = None,
        portfolio_state: Optional[Dict] = None
    ) -> TradeValidationResult:
        """
        Validate trade through all institutional checks
        
        Args:
            symbol: Trading symbol (e.g., 'BTC-USD')
            side: 'buy' or 'sell'
            position_value: USD value of position
            market_data: Market price data
            indicators: Technical indicators (optional)
            portfolio_state: Current portfolio state (optional)
            
        Returns:
            TradeValidationResult with approval status and adjusted parameters
        """
        # Check if in emergency mode
        if self.emergency_mode:
            return TradeValidationResult(
                approved=False,
                reason=f"Emergency mode active: {self.emergency_reason}",
                adjusted_params={},
                warnings=[f"Trading halted: {self.emergency_reason}"]
            )
        
        # If coordinator not available, approve with warning
        if not self.enabled or not self.coordinator:
            return TradeValidationResult(
                approved=True,
                reason="Institutional checks disabled",
                adjusted_params={},
                warnings=["Crash resilience checks not active"]
            )
        
        # Default portfolio state if not provided
        if portfolio_state is None:
            portfolio_state = {
                'total_value': position_value * 20,  # Assume 5% position size
                'cash_reserve': position_value * 10,
            }
        
        # Run validation through coordinator
        try:
            can_enter, reason, adjusted_params = self.coordinator.can_enter_position(
                symbol=symbol,
                side=side,
                position_value=position_value,
                market_data=market_data,
                indicators=indicators or {},
                portfolio_state=portfolio_state
            )
            
            # Get current metrics for context
            metrics = self.coordinator.get_metrics()
            
            # Build result
            result = TradeValidationResult(
                approved=can_enter,
                reason=reason,
                adjusted_params=adjusted_params,
                warnings=metrics.active_warnings[:],
                regime=metrics.market_regime,
                liquidity_score=metrics.avg_liquidity_score,
                sector_exposure=metrics.max_sector_exposure_pct,
                portfolio_state=metrics.portfolio_state
            )
            
            # Log validation
            self._log_validation(result, symbol, side, position_value)
            
            # Add to history
            self.validation_history.append({
                'timestamp': datetime.now().isoformat(),
                'symbol': symbol,
                'approved': can_enter,
                'reason': reason,
                'regime': metrics.market_regime,
            })
            
            # Keep only last 1000 validations
            if len(self.validation_history) > 1000:
                self.validation_history = self.validation_history[-1000:]
            
            return result
            
        except Exception as e:
            logger.error(f"Error validating trade: {e}")
            return TradeValidationResult(
                approved=False,
                reason=f"Validation error: {str(e)}",
                adjusted_params={},
                warnings=[f"Validation system error: {str(e)}"]
            )
    
    def _log_validation(
        self,
        result: TradeValidationResult,
        symbol: str,
        side: str,
        value: float
    ):
        """Log validation result"""
        status_icon = "✅" if result.approved else "❌"
        
        logger.info(f"{status_icon} Trade Validation: {symbol} {side.upper()} ${value:.2f}")
        logger.info(f"   Status: {result.reason}")
        
        if result.regime:
            logger.info(f"   Market Regime: {result.regime}")
        
        if result.liquidity_score is not None:
            logger.info(f"   Liquidity Score: {result.liquidity_score:.2f}")
        
        if result.portfolio_state:
            logger.info(f"   Portfolio State: {result.portfolio_state}")
        
        if result.adjusted_params:
            logger.info(f"   Adjusted Parameters: {result.adjusted_params}")
        
        if result.warnings:
            for warning in result.warnings:
                logger.warning(f"   ⚠️ {warning}")
    
    def adjust_position_size(
        self,
        base_position_value: float,
        validation_result: TradeValidationResult
    ) -> float:
        """
        Adjust position size based on validation result
        
        Args:
            base_position_value: Original position value
            validation_result: Result from validate_trade
            
        Returns:
            Adjusted position value
        """
        if not validation_result.approved:
            return 0.0
        
        adjusted_value = base_position_value
        
        # Apply regime multiplier
        if 'position_size_multiplier' in validation_result.adjusted_params:
            multiplier = validation_result.adjusted_params['position_size_multiplier']
            adjusted_value *= multiplier
            logger.info(f"   Position adjusted by regime: {base_position_value:.2f} -> {adjusted_value:.2f} (x{multiplier})")
        
        # Apply liquidity adjustment
        if 'adjusted_value' in validation_result.adjusted_params:
            adjusted_value = validation_result.adjusted_params['adjusted_value']
            logger.info(f"   Position adjusted by liquidity: {base_position_value:.2f} -> {adjusted_value:.2f}")
        
        return adjusted_value
    
    def get_regime_adjusted_entry_score(
        self,
        base_min_score: int,
        validation_result: TradeValidationResult
    ) -> int:
        """
        Get regime-adjusted minimum entry score
        
        Args:
            base_min_score: Base minimum entry score (e.g., 3)
            validation_result: Result from validate_trade
            
        Returns:
            Adjusted minimum entry score
        """
        if not validation_result.approved:
            return 999  # Impossibly high score
        
        # Use regime-adjusted score if available
        if 'min_entry_score' in validation_result.adjusted_params:
            return validation_result.adjusted_params['min_entry_score']
        
        return base_min_score
    
    def should_run_crash_validation(self) -> bool:
        """Check if it's time to run crash validation"""
        if self.last_crash_validation is None:
            return True
        
        hours_since_last = (datetime.now() - self.last_crash_validation).total_seconds() / 3600
        return hours_since_last >= self.crash_validation_interval_hours
    
    def run_crash_validation(
        self,
        portfolio_state: Dict,
        stress_level: str = "moderate"
    ) -> Tuple[bool, Dict]:
        """
        Run crash simulation validation
        
        Args:
            portfolio_state: Current portfolio state
            stress_level: 'mild', 'moderate', or 'severe'
            
        Returns:
            Tuple of (passed, results)
        """
        if not self.enabled or not self.coordinator:
            logger.warning("Crash validation skipped - coordinator not available")
            return True, {'status': 'skipped'}
        
        logger.info(f"🔍 Running crash resilience validation ({stress_level})...")
        
        passed, results = self.coordinator.validate_crash_resilience(
            portfolio_state, stress_level
        )
        
        self.last_crash_validation = datetime.now()
        
        if not passed:
            logger.warning("⚠️ Crash validation FAILED - consider increasing safety margins")
            # Don't activate emergency mode, just warn
        else:
            logger.info("✅ Crash validation PASSED - system is resilient")
        
        return passed, results
    
    def activate_emergency_mode(self, reason: str):
        """
        Activate emergency trading halt
        
        Args:
            reason: Reason for emergency mode
        """
        self.emergency_mode = True
        self.emergency_reason = reason
        logger.critical(f"🚨 EMERGENCY MODE ACTIVATED: {reason}")
        logger.critical("   All trading halted until manually cleared")
    
    def deactivate_emergency_mode(self):
        """Deactivate emergency mode and resume normal operations"""
        if self.emergency_mode:
            logger.info(f"✅ Emergency mode deactivated (was: {self.emergency_reason})")
            self.emergency_mode = False
            self.emergency_reason = None
    
    def get_infrastructure_status(self) -> Dict:
        """Get current infrastructure status"""
        if not self.enabled or not self.coordinator:
            return {
                'enabled': False,
                'status': 'unavailable',
                'message': 'Institutional infrastructure not available'
            }
        
        status = self.coordinator.get_status_summary()
        status['emergency_mode'] = self.emergency_mode
        status['emergency_reason'] = self.emergency_reason
        status['last_crash_validation'] = (
            self.last_crash_validation.isoformat() 
            if self.last_crash_validation else None
        )
        
        return status
    
    def get_validation_statistics(self) -> Dict:
        """Get statistics on trade validations"""
        if not self.validation_history:
            return {
                'total_validations': 0,
                'approved_count': 0,
                'rejected_count': 0,
                'approval_rate': 0.0,
            }
        
        total = len(self.validation_history)
        approved = sum(1 for v in self.validation_history if v['approved'])
        rejected = total - approved
        
        return {
            'total_validations': total,
            'approved_count': approved,
            'rejected_count': rejected,
            'approval_rate': (approved / total * 100) if total > 0 else 0.0,
            'recent_validations': self.validation_history[-10:],
        }


# Singleton instance
_trader_instance = None


def get_crash_resilient_trader(broker_client=None, config: Optional[Dict] = None) -> CrashResilientTrader:
    """Get singleton instance of crash-resilient trader"""
    global _trader_instance
    if _trader_instance is None:
        _trader_instance = CrashResilientTrader(broker_client, config)
    return _trader_instance


if __name__ == "__main__":
    # Demo usage
    logging.basicConfig(level=logging.INFO)
    
    trader = get_crash_resilient_trader()
    
    print("\n" + "="*80)
    print("NIJA CRASH-RESILIENT TRADING - DEMO")
    print("="*80)
    
    # Simulate trade validation
    market_data = {
        'close': 50000,
        'bid': 49990,
        'ask': 50010,
        'volume': 1000000,
        'avg_volume': 900000,
    }
    
    result = trader.validate_trade(
        symbol='BTC-USD',
        side='buy',
        position_value=1000,
        market_data=market_data
    )
    
    print(f"\n📊 Validation Result:")
    print(f"   Approved: {result.approved}")
    print(f"   Reason: {result.reason}")
    print(f"   Market Regime: {result.regime}")
    print(f"   Liquidity Score: {result.liquidity_score}")
    print(f"   Portfolio State: {result.portfolio_state}")
    
    if result.warnings:
        print(f"\n⚠️ Warnings:")
        for warning in result.warnings:
            print(f"   • {warning}")
    
    # Show infrastructure status
    print(f"\n🏛️ Infrastructure Status:")
    status = trader.get_infrastructure_status()
    print(f"   Health: {status.get('health', 'unknown')}")
    print(f"   Emergency Mode: {status.get('emergency_mode', False)}")
    
    print("\n" + "="*80)
