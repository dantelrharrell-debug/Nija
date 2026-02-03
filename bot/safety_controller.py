"""
NIJA Safety Controller - App Store Readiness Module
====================================================

This module implements comprehensive safety controls for App Store compliance:

1. Cold Start Safety - Safe defaults when no credentials configured
2. Kill Switch - Global trading control with immediate effect
3. Failure Mode Handling - Graceful degradation on errors
4. User Control - Clear ON/OFF states with logging
5. Zero-Config Safety - App starts safely without any setup

CRITICAL SAFETY PRINCIPLES:
- Trading is DISABLED by default (must explicitly enable)
- App is safe to install and run with zero configuration
- Clear separation between monitor mode and trading mode
- All state changes are logged for audit trail
- Emergency stop capability (file-based + env var)
"""

import os
import logging
import time
from typing import Tuple, Optional, Dict
from enum import Enum
from datetime import datetime

logger = logging.getLogger("nija.safety")


class TradingMode(Enum):
    """Trading mode states for NIJA bot"""
    DISABLED = "disabled"           # Trading completely disabled (default)
    MONITOR = "monitor"             # Monitor mode - no trades, display data only
    DRY_RUN = "dry_run"            # Simulate trades, no real orders
    HEARTBEAT = "heartbeat"         # Single verification trade, then exit
    LIVE = "live"                   # Live trading with real money


class SafetyController:
    """
    Central safety controller for NIJA trading bot.
    
    Implements all safety controls required for App Store compliance.
    This is the single source of truth for whether trading is allowed.
    """
    
    def __init__(self):
        """Initialize safety controller with safe defaults"""
        self._mode = TradingMode.DISABLED
        self._last_state_change = None
        self._state_change_history = []
        self._emergency_stop_active = False
        self._credentials_configured = False
        self._load_safety_configuration()
        
    def _load_safety_configuration(self):
        """
        Load and validate safety configuration from environment.
        
        This method determines the trading mode based on:
        1. Emergency stop file check (highest priority)
        2. Environment variable flags
        3. Credential validation
        4. Safe defaults
        """
        # Check #1: Emergency stop file (highest priority - overrides everything)
        emergency_file = 'EMERGENCY_STOP'
        if os.path.exists(emergency_file):
            self._emergency_stop_active = True
            self._mode = TradingMode.DISABLED
            logger.warning("=" * 70)
            logger.warning("🚨 EMERGENCY STOP ACTIVE")
            logger.warning("=" * 70)
            logger.warning("   Trading is DISABLED by emergency stop file")
            logger.warning(f"   Delete {emergency_file} file to resume")
            logger.warning("=" * 70)
            self._log_state_change("EMERGENCY_STOP file detected - trading disabled")
            return
            
        # Check #2: Dry-run simulator mode (for App Store reviewers)
        dry_run_mode = os.getenv('DRY_RUN_MODE', 'false').lower() in ('true', '1', 'yes')
        if dry_run_mode:
            self._mode = TradingMode.DRY_RUN
            logger.info("=" * 70)
            logger.info("🎭 DRY-RUN SIMULATOR MODE ACTIVE")
            logger.info("=" * 70)
            logger.info("   FOR APP STORE REVIEW ONLY")
            logger.info("   All trades are simulated - NO REAL ORDERS PLACED")
            logger.info("   Broker API calls return mock data")
            logger.info("=" * 70)
            self._log_state_change("DRY_RUN_MODE enabled - simulated trading only")
            return
            
        # Check #3: Heartbeat verification mode (single test trade)
        heartbeat_mode = os.getenv('HEARTBEAT_TRADE', 'false').lower() in ('true', '1', 'yes')
        if heartbeat_mode:
            self._mode = TradingMode.HEARTBEAT
            logger.info("=" * 70)
            logger.info("💓 HEARTBEAT TRADE MODE ACTIVATED")
            logger.info("=" * 70)
            logger.info("   Single verification trade will be executed")
            logger.info("   Bot will auto-disable after heartbeat completes")
            logger.info("=" * 70)
            self._log_state_change("HEARTBEAT_TRADE enabled - verification mode")
            return
            
        # Check #4: Live capital verification (required for real trading)
        live_capital_verified = os.getenv('LIVE_CAPITAL_VERIFIED', 'false').lower() in ('true', '1', 'yes')
        
        # Check #5: Credential validation
        self._credentials_configured = self._check_credentials()
        
        # Determine final mode
        if live_capital_verified and self._credentials_configured:
            self._mode = TradingMode.LIVE
            logger.info("=" * 70)
            logger.info("🟢 LIVE TRADING MODE ACTIVE")
            logger.info("=" * 70)
            logger.info("   REAL MONEY TRADING ENABLED")
            logger.info("   LIVE_CAPITAL_VERIFIED: ✅ TRUE")
            logger.info("   Credentials: ✅ CONFIGURED")
            logger.info("=" * 70)
            self._log_state_change("LIVE trading mode activated")
        elif self._credentials_configured and not live_capital_verified:
            # Credentials exist but safety lock is on
            self._mode = TradingMode.MONITOR
            logger.info("=" * 70)
            logger.info("📊 MONITOR MODE - TRADING DISABLED")
            logger.info("=" * 70)
            logger.info("   Credentials: ✅ CONFIGURED")
            logger.info("   LIVE_CAPITAL_VERIFIED: ❌ FALSE (safety lock enabled)")
            logger.info("")
            logger.info("   📡 Bot will connect to exchanges and show data")
            logger.info("   🚫 NO TRADES will be executed (safety lock)")
            logger.info("")
            logger.info("   To enable live trading:")
            logger.info("   1. Set LIVE_CAPITAL_VERIFIED=true in .env")
            logger.info("   2. Restart the bot")
            logger.info("=" * 70)
            self._log_state_change("MONITOR mode - credentials exist but LIVE_CAPITAL_VERIFIED=false")
        else:
            # No credentials configured - completely safe state
            self._mode = TradingMode.DISABLED
            logger.info("=" * 70)
            logger.info("⚪ SAFE MODE - NO CREDENTIALS CONFIGURED")
            logger.info("=" * 70)
            logger.info("   Trading is DISABLED (default safe state)")
            logger.info("   No exchange credentials found")
            logger.info("")
            logger.info("   This app is safe to run - no trading will occur")
            logger.info("   Configure exchange credentials to enable trading")
            logger.info("")
            logger.info("   See .env.example for setup instructions")
            logger.info("=" * 70)
            self._log_state_change("DISABLED mode - no credentials configured (safe)")
            
    def _check_credentials(self) -> bool:
        """
        Check if any exchange credentials are configured.
        
        Returns:
            bool: True if at least one exchange has credentials
        """
        # Check Kraken (primary broker)
        if os.getenv("KRAKEN_PLATFORM_API_KEY") and os.getenv("KRAKEN_PLATFORM_API_SECRET"):
            return True
            
        # Check Coinbase (disabled but still check)
        if os.getenv("COINBASE_API_KEY") and os.getenv("COINBASE_API_SECRET"):
            return True
            
        # Check OKX
        if os.getenv("OKX_API_KEY") and os.getenv("OKX_API_SECRET") and os.getenv("OKX_PASSPHRASE"):
            return True
            
        # Check Binance
        if os.getenv("BINANCE_API_KEY") and os.getenv("BINANCE_API_SECRET"):
            return True
            
        # Check Alpaca
        if os.getenv("ALPACA_API_KEY") and os.getenv("ALPACA_API_SECRET"):
            return True
            
        return False
        
    def _log_state_change(self, reason: str):
        """
        Log a state change with timestamp and reason.
        
        Args:
            reason: Human-readable reason for the state change
        """
        timestamp = datetime.utcnow().isoformat()
        self._last_state_change = timestamp
        self._state_change_history.append({
            'timestamp': timestamp,
            'mode': self._mode.value,
            'reason': reason
        })
        logger.info(f"🔄 Safety state change: {self._mode.value} - {reason}")
        
    def is_trading_allowed(self) -> Tuple[bool, str]:
        """
        Check if trading is currently allowed.
        
        This is the SINGLE SOURCE OF TRUTH for trading permission.
        All trading operations must call this method first.
        
        Returns:
            Tuple[bool, str]: (allowed, reason)
                - allowed: True if trading is permitted
                - reason: Human-readable explanation
        """
        # Emergency stop overrides everything
        if self._emergency_stop_active:
            return False, "Emergency stop is active - delete EMERGENCY_STOP file to resume"
            
        # Check mode
        if self._mode == TradingMode.DISABLED:
            return False, "Trading is disabled - no credentials configured or explicitly disabled"
            
        if self._mode == TradingMode.MONITOR:
            return False, "Monitor mode - set LIVE_CAPITAL_VERIFIED=true to enable trading"
            
        if self._mode == TradingMode.DRY_RUN:
            return True, "Dry-run mode - simulated trades only (no real orders)"
            
        if self._mode == TradingMode.HEARTBEAT:
            return True, "Heartbeat mode - single verification trade allowed"
            
        if self._mode == TradingMode.LIVE:
            return True, "Live trading is enabled"
            
        # Fallback: deny by default (fail-safe)
        return False, "Unknown trading mode - defaulting to safe (disabled)"
        
    def get_current_mode(self) -> TradingMode:
        """Get current trading mode"""
        return self._mode
        
    def activate_emergency_stop(self, reason: str = "Manual activation"):
        """
        Activate emergency stop - halts ALL trading immediately.
        
        This creates the EMERGENCY_STOP file which is checked on every cycle.
        
        Args:
            reason: Reason for emergency stop (logged for audit)
        """
        emergency_file = 'EMERGENCY_STOP'
        try:
            with open(emergency_file, 'w') as f:
                f.write(f"Emergency stop activated at {datetime.utcnow().isoformat()}\n")
                f.write(f"Reason: {reason}\n")
                f.write("\nDelete this file to resume trading.\n")
                
            self._emergency_stop_active = True
            self._mode = TradingMode.DISABLED
            
            logger.error("=" * 70)
            logger.error("🚨 EMERGENCY STOP ACTIVATED")
            logger.error("=" * 70)
            logger.error(f"   Reason: {reason}")
            logger.error("   All trading has been halted")
            logger.error(f"   Delete {emergency_file} file to resume")
            logger.error("=" * 70)
            
            self._log_state_change(f"Emergency stop activated - {reason}")
            
        except Exception as e:
            logger.error(f"❌ Failed to create emergency stop file: {e}")
            
    def deactivate_emergency_stop(self):
        """
        Deactivate emergency stop - allows bot to resume normal operation.
        
        Note: This only removes the emergency stop. The bot will still need
        proper configuration (credentials, LIVE_CAPITAL_VERIFIED) to trade.
        """
        emergency_file = 'EMERGENCY_STOP'
        try:
            if os.path.exists(emergency_file):
                os.remove(emergency_file)
                logger.info("✅ Emergency stop deactivated - file removed")
                
            self._emergency_stop_active = False
            # Reload configuration to determine new mode
            self._load_safety_configuration()
            
        except Exception as e:
            logger.error(f"❌ Failed to remove emergency stop file: {e}")
            
    def get_status_summary(self) -> Dict:
        """
        Get comprehensive status summary for display/logging.
        
        Returns:
            Dict with current status information
        """
        allowed, reason = self.is_trading_allowed()
        
        return {
            'mode': self._mode.value,
            'trading_allowed': allowed,
            'reason': reason,
            'emergency_stop_active': self._emergency_stop_active,
            'credentials_configured': self._credentials_configured,
            'last_state_change': self._last_state_change,
            'state_change_count': len(self._state_change_history)
        }
        
    def log_status(self):
        """Log current safety status to logger"""
        status = self.get_status_summary()
        
        logger.info("=" * 70)
        logger.info("🛡️  SAFETY CONTROLLER STATUS")
        logger.info("=" * 70)
        logger.info(f"   Mode: {status['mode'].upper()}")
        logger.info(f"   Trading Allowed: {'✅ YES' if status['trading_allowed'] else '❌ NO'}")
        logger.info(f"   Reason: {status['reason']}")
        logger.info(f"   Emergency Stop: {'🚨 ACTIVE' if status['emergency_stop_active'] else '✅ INACTIVE'}")
        logger.info(f"   Credentials: {'✅ CONFIGURED' if status['credentials_configured'] else '❌ NOT CONFIGURED'}")
        if status['last_state_change']:
            logger.info(f"   Last Change: {status['last_state_change']}")
        logger.info("=" * 70)


# Global singleton instance
_safety_controller = None


def get_safety_controller() -> SafetyController:
    """
    Get the global safety controller instance.
    
    Returns:
        SafetyController: Global singleton instance
    """
    global _safety_controller
    if _safety_controller is None:
        _safety_controller = SafetyController()
    return _safety_controller


def is_trading_allowed() -> Tuple[bool, str]:
    """
    Convenience function to check if trading is allowed.
    
    Returns:
        Tuple[bool, str]: (allowed, reason)
    """
    controller = get_safety_controller()
    return controller.is_trading_allowed()
