#!/usr/bin/env python3
"""
NIJA Bootstrap Diagnostic Tool
================================

Diagnoses why the bot is stuck at BROKER_REGISTRY phase gate.

Usage:
    python BOOTSTRAP_DIAGNOSTIC.py
"""

import os
import sys
import logging
import time

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s'
)
logger = logging.getLogger("diagnostic")

def check_credentials():
    """Verify all required credentials are present."""
    logger.info("=" * 80)
    logger.info("1. CHECKING CREDENTIALS")
    logger.info("=" * 80)
    
    checks = {
        "KRAKEN_PLATFORM_API_KEY": os.getenv("KRAKEN_PLATFORM_API_KEY") is not None,
        "KRAKEN_PLATFORM_API_SECRET": os.getenv("KRAKEN_PLATFORM_API_SECRET") is not None,
        "COINBASE_API_KEY": os.getenv("COINBASE_API_KEY") is not None,
        "COINBASE_API_SECRET": os.getenv("COINBASE_API_SECRET") is not None,
        "LIVE_CAPITAL_VERIFIED": os.getenv("LIVE_CAPITAL_VERIFIED") == "true",
    }
    
    for key, present in checks.items():
        status = "✅" if present else "❌"
        logger.info(f"{status} {key}: {present}")
    
    return all(checks.values())

def check_broker_connection():
    """Test broker connections independently."""
    logger.info("\n" + "=" * 80)
    logger.info("2. TESTING BROKER CONNECTIONS")
    logger.info("=" * 80)
    
    try:
        from bot.broker_manager import KrakenBroker, CoinbaseBroker, AccountType
        
        # Test Kraken Platform
        logger.info("\n[Kraken PLATFORM]")
        try:
            kraken = KrakenBroker(account_type=AccountType.PLATFORM)
            ok = kraken.connect()
            logger.info(f"✅ Connection successful: {ok}")
            if ok:
                logger.info(f"   Connected: {getattr(kraken, 'connected', 'N/A')}")
            return ok
        except Exception as e:
            logger.error(f"❌ Connection failed: {type(e).__name__}: {e}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Broker module import failed: {e}")
        return False

def check_bootstrap_state():
    """Check current bootstrap state machine state."""
    logger.info("\n" + "=" * 80)
    logger.info("3. CHECKING BOOTSTRAP STATE MACHINE")
    logger.info("=" * 80)
    
    try:
        from bot.bootstrap_state_machine import get_bootstrap_fsm, BootstrapState
        
        fsm = get_bootstrap_fsm()
        logger.info(f"Current state: {fsm.state.value}")
        logger.info(f"Boot complete: {fsm.boot_complete}")
        logger.info(f"Execution authority: {fsm.execution_authority}")
        
        history = fsm.get_history(limit=10)
        if history:
            logger.info("\nRecent transitions:")
            for record in history:
                logger.info(f"  {record['from']} → {record['to']} ({record['reason']})")
        
        return fsm
    except Exception as e:
        logger.error(f"❌ FSM check failed: {e}")
        return None

def check_phase_gate():
    """Check current phase gate state."""
    logger.info("\n" + "=" * 80)
    logger.info("4. CHECKING PHASE GATE")
    logger.info("=" * 80)
    
    try:
        from bot.startup_phase_gate import get_phase_gate, Phase
        
        gate = get_phase_gate()
        logger.info(f"Current phase: {gate.current.name}({gate.current.value})")
        
        return gate
    except Exception as e:
        logger.error(f"❌ Phase gate check failed: {e}")
        return None

def check_capital_authority():
    """Check CapitalAuthority state."""
    logger.info("\n" + "=" * 80)
    logger.info("5. CHECKING CAPITAL AUTHORITY")
    logger.info("=" * 80)
    
    try:
        from capital_authority import get_capital_authority
        
        ca = get_capital_authority()
        logger.info(f"Ready: {ca.is_ready()}")
        logger.info(f"Total balance: {ca.total_balance}")
        
        return ca
    except ImportError:
        logger.warning("⚠️  CapitalAuthority not available")
        return None
    except Exception as e:
        logger.error(f"❌ CA check failed: {e}")
        return None

def check_multi_account_manager():
    """Check MABM state."""
    logger.info("\n" + "=" * 80)
    logger.info("6. CHECKING MULTI-ACCOUNT BROKER MANAGER")
    logger.info("=" * 80)
    
    try:
        from bot.multi_account_broker_manager import multi_account_broker_manager as mabm
        
        logger.info(f"Platform brokers: {len(mabm.platform_brokers)}")
        for name, broker in mabm.platform_brokers.items():
            connected = getattr(broker, 'connected', False)
            logger.info(f"  ✅ {name}: connected={connected}")
        
        return mabm
    except ImportError:
        logger.warning("⚠️  MABM not available")
        return None
    except Exception as e:
        logger.error(f"❌ MABM check failed: {e}")
        return None

def main():
    logger.info("\n🔍 NIJA BOOTSTRAP DIAGNOSTIC")
    logger.info("Starting comprehensive system check...\n")
    
    # Run all checks
    creds_ok = check_credentials()
    broker_ok = check_broker_connection()
    fsm = check_bootstrap_state()
    gate = check_phase_gate()
    ca = check_capital_authority()
    mabm = check_multi_account_manager()
    
    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Credentials OK: {creds_ok}")
    logger.info(f"Broker connection OK: {broker_ok}")
    logger.info(f"FSM state: {fsm.state.value if fsm else 'N/A'}")
    logger.info(f"Phase gate: {gate.current.name if gate else 'N/A'}")
    logger.info(f"CA ready: {ca.is_ready() if ca else 'N/A'}")
    logger.info(f"MABM available: {mabm is not None}")
    
    if not broker_ok:
        logger.critical("\n❌ BROKER CONNECTION FAILED — This is why trades aren't starting!")
        logger.critical("   Check: Kraken API keys, rate limits, nonce state")
        sys.exit(1)
    
    if fsm and fsm.state.value not in ("CAPITAL_READY", "INIT_COMPLETE", "THREADS_STARTING", "RUNNING_SUPERVISED"):
        logger.critical(f"\n❌ FSM STUCK AT {fsm.state.value}")
        logger.critical("   Run with increased timeouts:")
        logger.critical("   export NIJA_BOOTSTRAP_BROKERS_READY_TIMEOUT_S=120")
        sys.exit(1)
    
    logger.info("\n✅ All checks passed — system appears healthy")
    sys.exit(0)

if __name__ == "__main__":
    main()
