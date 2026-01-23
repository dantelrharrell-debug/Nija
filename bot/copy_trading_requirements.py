"""
NIJA Copy Trading Requirements Validator
==========================================

This module enforces the mandatory requirements for copy trading to function.
Copy trading will NOT work unless ALL requirements are met for both master and users.

CRITICAL REQUIREMENTS (non-negotiable):

MASTER Requirements (ALL must be true):
1. PRO_MODE=true
2. LIVE_TRADING=true  
3. MASTER_BROKER=KRAKEN (connected)
4. MASTER_CONNECTED=true

USER Requirements (ALL must be true):
1. PRO_MODE=true
2. COPY_TRADING=true (COPY_TRADING_MODE=MASTER_FOLLOW)
3. STANDALONE=false (user must be in copy trading mode, not independent)
4. TIER >= STARTER ($50 minimum balance)
5. INITIAL_CAPITAL >= 100 (for tiers above STARTER)

If ANY requirement is not met, copy trading will be disabled with clear logging.

Author: NIJA Trading Systems
Date: January 23, 2026
"""

import os
import logging
from typing import Dict, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger('nija.copy_requirements')


@dataclass
class MasterRequirements:
    """Requirements for master account to enable copy trading."""
    pro_mode: bool
    live_trading: bool
    master_broker_kraken: bool
    master_connected: bool
    
    def all_met(self) -> bool:
        """Check if all master requirements are met."""
        return (
            self.pro_mode and
            self.live_trading and
            self.master_broker_kraken and
            self.master_connected
        )
    
    def get_unmet_requirements(self) -> list:
        """Get list of unmet requirements."""
        unmet = []
        if not self.pro_mode:
            unmet.append("MASTER PRO_MODE=true")
        if not self.live_trading:
            unmet.append("LIVE_TRADING=true")
        if not self.master_broker_kraken:
            unmet.append("MASTER_BROKER=KRAKEN")
        if not self.master_connected:
            unmet.append("MASTER_CONNECTED=true")
        return unmet


@dataclass
class UserRequirements:
    """Requirements for user account to receive copy trades."""
    user_id: str
    pro_mode: bool
    copy_trading_enabled: bool
    standalone: bool  # Should be False for copy trading
    tier_sufficient: bool  # Balance >= STARTER tier minimum ($50)
    initial_capital_sufficient: bool  # Balance >= 100 for non-STARTER tiers
    
    def all_met(self) -> bool:
        """Check if all user requirements are met."""
        return (
            self.pro_mode and
            self.copy_trading_enabled and
            not self.standalone and  # Must NOT be standalone
            self.tier_sufficient and
            self.initial_capital_sufficient
        )
    
    def get_unmet_requirements(self) -> list:
        """Get list of unmet requirements."""
        unmet = []
        if not self.pro_mode:
            unmet.append(f"{self.user_id}: PRO_MODE=true")
        if not self.copy_trading_enabled:
            unmet.append(f"{self.user_id}: COPY_TRADING=true")
        if self.standalone:
            unmet.append(f"{self.user_id}: STANDALONE=false")
        if not self.tier_sufficient:
            unmet.append(f"{self.user_id}: TIER >= STARTER")
        if not self.initial_capital_sufficient:
            unmet.append(f"{self.user_id}: INITIAL_CAPITAL >= 100")
        return unmet


def check_master_requirements(multi_account_manager) -> MasterRequirements:
    """
    Check if master account meets all requirements for copy trading.
    
    Args:
        multi_account_manager: MultiAccountBrokerManager instance
        
    Returns:
        MasterRequirements dataclass with status of each requirement
    """
    # Check PRO_MODE
    pro_mode = os.getenv('PRO_MODE', 'false').lower() in ('true', '1', 'yes')
    
    # Check LIVE_TRADING
    live_trading = os.getenv('LIVE_TRADING', '0') in ('1', 'true', 'True', 'yes')
    
    # Check if Kraken master is configured and connected
    master_broker_kraken = False
    master_connected = False
    
    try:
        from bot.broker_manager import BrokerType
    except ImportError:
        from broker_manager import BrokerType
    
    if multi_account_manager:
        # Check if Kraken master broker exists and is connected
        if BrokerType.KRAKEN in multi_account_manager.master_brokers:
            master_broker_kraken = True
            kraken_master = multi_account_manager.master_brokers[BrokerType.KRAKEN]
            if kraken_master and hasattr(kraken_master, 'connected'):
                master_connected = kraken_master.connected
    
    return MasterRequirements(
        pro_mode=pro_mode,
        live_trading=live_trading,
        master_broker_kraken=master_broker_kraken,
        master_connected=master_connected
    )


def check_user_requirements(
    user_id: str,
    user_balance: float,
    user_broker,
    copy_from_master: bool = True
) -> UserRequirements:
    """
    Check if user account meets all requirements for copy trading.
    
    Args:
        user_id: User identifier
        user_balance: User's current balance in USD
        user_broker: User's broker instance
        copy_from_master: Whether user has copy_from_master enabled in config
        
    Returns:
        UserRequirements dataclass with status of each requirement
    """
    # Check PRO_MODE (global setting applies to all users)
    pro_mode = os.getenv('PRO_MODE', 'false').lower() in ('true', '1', 'yes')
    
    # Check COPY_TRADING via COPY_TRADING_MODE
    copy_trading_mode = os.getenv('COPY_TRADING_MODE', 'INDEPENDENT').upper()
    copy_trading_enabled = (copy_trading_mode == 'MASTER_FOLLOW') and copy_from_master
    
    # Check STANDALONE (opposite of copy trading)
    # User is standalone if they are NOT in copy trading mode
    standalone = not copy_trading_enabled
    
    # Check TIER >= STARTER (balance >= $50)
    try:
        from bot.tier_config import TIER_CONFIGS, TradingTier
    except ImportError:
        from tier_config import TIER_CONFIGS, TradingTier
    
    starter_min = TIER_CONFIGS[TradingTier.STARTER].capital_min
    tier_sufficient = user_balance >= starter_min
    
    # Check INITIAL_CAPITAL >= 100 (for non-STARTER tiers)
    # STARTER tier ($50-$99) doesn't need $100 minimum
    # All other tiers need $100 minimum
    saver_min = TIER_CONFIGS[TradingTier.SAVER].capital_min  # $100
    if user_balance < saver_min:
        # User is in STARTER tier, capital requirement is waived
        initial_capital_sufficient = True
    else:
        # User is in SAVER+ tier, needs at least $100
        initial_capital_sufficient = user_balance >= 100.0
    
    return UserRequirements(
        user_id=user_id,
        pro_mode=pro_mode,
        copy_trading_enabled=copy_trading_enabled,
        standalone=standalone,
        tier_sufficient=tier_sufficient,
        initial_capital_sufficient=initial_capital_sufficient
    )


def validate_copy_trading_requirements(
    multi_account_manager,
    user_id: Optional[str] = None,
    user_balance: Optional[float] = None,
    user_broker=None,
    copy_from_master: bool = True,
    log_results: bool = True
) -> Tuple[bool, str]:
    """
    Validate all copy trading requirements for master and optionally a specific user.
    
    Args:
        multi_account_manager: MultiAccountBrokerManager instance
        user_id: Optional user ID to check (if None, only checks master)
        user_balance: User's balance (required if user_id provided)
        user_broker: User's broker instance (required if user_id provided)
        copy_from_master: Whether user has copy_from_master enabled
        log_results: Whether to log the validation results
        
    Returns:
        Tuple of (all_requirements_met: bool, reason: str)
    """
    # Check master requirements first
    master_reqs = check_master_requirements(multi_account_manager)
    
    if not master_reqs.all_met():
        unmet = master_reqs.get_unmet_requirements()
        reason = f"Master requirements not met: {', '.join(unmet)}"
        
        if log_results:
            logger.warning("=" * 70)
            logger.warning("❌ COPY TRADING DISABLED - MASTER REQUIREMENTS NOT MET")
            logger.warning("=" * 70)
            for req in unmet:
                logger.warning(f"   ❌ {req}")
            logger.warning("")
            logger.warning("🔧 FIX: Set these environment variables:")
            logger.warning("   PRO_MODE=true")
            logger.warning("   LIVE_TRADING=1")
            logger.warning("   KRAKEN_MASTER_API_KEY=<your-key>")
            logger.warning("   KRAKEN_MASTER_API_SECRET=<your-secret>")
            logger.warning("=" * 70)
        
        return False, reason
    
    # If checking a specific user, validate user requirements
    if user_id is not None:
        if user_balance is None or user_broker is None:
            return False, f"User {user_id}: Missing balance or broker for validation"
        
        user_reqs = check_user_requirements(user_id, user_balance, user_broker, copy_from_master)
        
        if not user_reqs.all_met():
            unmet = user_reqs.get_unmet_requirements()
            reason = f"User requirements not met: {', '.join(unmet)}"
            
            if log_results:
                logger.warning("=" * 70)
                logger.warning(f"❌ COPY TRADING DISABLED FOR {user_id.upper()}")
                logger.warning("=" * 70)
                for req in unmet:
                    logger.warning(f"   ❌ {req}")
                logger.warning("")
                logger.warning("🔧 FIX:")
                logger.warning("   1. Ensure PRO_MODE=true in environment")
                logger.warning("   2. Ensure COPY_TRADING_MODE=MASTER_FOLLOW")
                logger.warning(f"   3. Ensure account balance >= $50 (current: ${user_balance:.2f})")
                logger.warning("=" * 70)
            
            return False, reason
    
    # All requirements met
    if log_results and user_id:
        logger.info("=" * 70)
        logger.info(f"✅ COPY TRADING ENABLED FOR {user_id.upper()}")
        logger.info("=" * 70)
        logger.info("   ✅ Master PRO_MODE=true")
        logger.info("   ✅ LIVE_TRADING=true")
        logger.info("   ✅ MASTER_BROKER=KRAKEN (connected)")
        logger.info("   ✅ MASTER_CONNECTED=true")
        logger.info(f"   ✅ User PRO_MODE=true")
        logger.info(f"   ✅ COPY_TRADING=true")
        logger.info(f"   ✅ STANDALONE=false")
        logger.info(f"   ✅ TIER >= STARTER (balance: ${user_balance:.2f})")
        logger.info("=" * 70)
    
    return True, "All requirements met"


def log_copy_trading_status(multi_account_manager):
    """
    Log comprehensive copy trading status showing which requirements are met.
    
    Args:
        multi_account_manager: MultiAccountBrokerManager instance
    """
    logger.info("=" * 70)
    logger.info("📋 COPY TRADING REQUIREMENTS STATUS")
    logger.info("=" * 70)
    
    # Check master requirements
    master_reqs = check_master_requirements(multi_account_manager)
    
    logger.info("MASTER REQUIREMENTS:")
    logger.info(f"   {'✅' if master_reqs.pro_mode else '❌'} PRO_MODE=true")
    logger.info(f"   {'✅' if master_reqs.live_trading else '❌'} LIVE_TRADING=true")
    logger.info(f"   {'✅' if master_reqs.master_broker_kraken else '❌'} MASTER_BROKER=KRAKEN")
    logger.info(f"   {'✅' if master_reqs.master_connected else '❌'} MASTER_CONNECTED=true")
    logger.info("")
    
    if master_reqs.all_met():
        logger.info("✅ Master: ALL REQUIREMENTS MET - Copy trading enabled")
    else:
        logger.warning("❌ Master: REQUIREMENTS NOT MET - Copy trading disabled")
        unmet = master_reqs.get_unmet_requirements()
        logger.warning(f"   Missing: {', '.join(unmet)}")
    
    logger.info("=" * 70)
