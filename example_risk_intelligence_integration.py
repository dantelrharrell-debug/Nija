#!/usr/bin/env python3
"""
Risk Intelligence Integration Example
======================================
Demonstrates how to integrate:
1. Legacy Position Exit Protocol with high-exposure monitoring
2. Risk Intelligence Gate for pre-entry checks
3. Full risk management workflow

This example shows how to use the Phase 3 enhancements:
- Volatility scaling before increasing position sizes
- Risk-weighted exposure before adding correlated positions
- High-exposure asset monitoring (PEPE, LUNA, etc.)

Author: NIJA Trading Systems
Version: 1.0
Date: February 2026
"""

import sys
import logging
from pathlib import Path
from typing import Dict, List, Optional

# Add bot directory to path
sys.path.insert(0, str(Path(__file__).parent / 'bot'))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def example_1_legacy_cleanup_with_monitoring():
    """
    Example 1: Run Legacy Exit Protocol with High-Exposure Monitoring
    
    This demonstrates:
    - Full legacy position cleanup
    - High-exposure asset monitoring (PEPE, LUNA, etc.)
    - Capital freed tracking
    - CLEAN state verification
    """
    logger.info("\n" + "=" * 80)
    logger.info("EXAMPLE 1: Legacy Cleanup with High-Exposure Monitoring")
    logger.info("=" * 80 + "\n")
    
    try:
        from bot.position_tracker import PositionTracker
        from bot.broker_integration import get_broker_integration
        from bot.legacy_position_exit_protocol import LegacyPositionExitProtocol
        
        # Initialize components
        position_tracker = PositionTracker()
        broker = get_broker_integration('coinbase')
        
        # Create protocol with high-exposure monitoring ENABLED
        protocol = LegacyPositionExitProtocol(
            position_tracker=position_tracker,
            broker_integration=broker,
            max_positions=8,
            dust_pct_threshold=0.01,  # 1% of account
            stale_order_minutes=30,
            monitor_high_exposure=True  # ✅ ENABLE monitoring
        )
        
        # Run full protocol
        logger.info("🚀 Running Legacy Exit Protocol...")
        results = protocol.run_full_protocol()
        
        # Display results
        logger.info("\n📊 RESULTS:")
        logger.info(f"   Success: {results.get('success', False)}")
        logger.info(f"   Final State: {results.get('phase4_verification', {}).get('account_state', 'UNKNOWN')}")
        
        # High-exposure monitoring results
        if 'high_exposure_monitoring' in results:
            monitoring = results['high_exposure_monitoring']
            logger.info(f"\n🚨 HIGH-EXPOSURE MONITORING:")
            logger.info(f"   Assets Tracked: {monitoring.get('positions_tracked', 0)}")
            logger.info(f"   Total Value: ${monitoring.get('total_value', 0):.2f}")
            logger.info(f"   % of Account: {monitoring.get('pct_of_account', 0):.2f}%")
            logger.info(f"   Alerts: {monitoring.get('alert_count', 0)}")
            
            # Display alerts
            for alert in monitoring.get('alerts', []):
                logger.warning(f"   🚨 {alert['severity']}: {alert['message']}")
        
        # Capital freed
        capital_freed = results.get('phase2_order_cleanup', {}).get('capital_freed_usd', 0)
        logger.info(f"\n💰 Capital Freed: ${capital_freed:.2f}")
        
        return results
        
    except Exception as e:
        logger.error(f"❌ Example 1 failed: {e}")
        return None


def example_2_pre_trade_risk_checks():
    """
    Example 2: Pre-Trade Risk Intelligence Checks
    
    This demonstrates:
    - Volatility scaling verification before entry
    - Correlation exposure checks before entry
    - Pre-trade risk assessment gate
    """
    logger.info("\n" + "=" * 80)
    logger.info("EXAMPLE 2: Pre-Trade Risk Intelligence Checks")
    logger.info("=" * 80 + "\n")
    
    try:
        from bot.risk_intelligence_gate import RiskIntelligenceGate, create_risk_intelligence_gate
        from bot.broker_integration import get_broker_integration
        import pandas as pd
        
        # Initialize broker
        broker = get_broker_integration('coinbase')
        
        # Create risk intelligence gate
        # In production, you would pass actual volatility_sizer and portfolio_risk_engine instances
        risk_gate = create_risk_intelligence_gate(
            volatility_sizer=None,  # Optional: pass VolatilityAdaptiveSizer instance
            portfolio_risk_engine=None,  # Optional: pass PortfolioRiskEngine instance
            config={
                'max_volatility_multiplier': 3.0,  # Max 3x target volatility
                'max_correlation_exposure': 0.40,   # Max 40% in correlated assets
                'min_diversification_ratio': 0.5    # Min diversification ratio
            }
        )
        
        # Simulate proposed trade
        symbol = 'BTC-USD'
        proposed_size = 500.0  # $500 position
        account_balance = 10000.0  # $10k account
        
        # Get current positions
        current_positions = broker.get_open_positions()
        
        # Get market data for volatility analysis
        try:
            df = broker.get_market_data(symbol, timeframe='1h', limit=100)
        except:
            logger.warning("Could not fetch market data - using mock data")
            df = pd.DataFrame({
                'open': [50000] * 100,
                'high': [51000] * 100,
                'low': [49000] * 100,
                'close': [50500] * 100,
                'volume': [1000] * 100
            })
        
        # Run pre-trade assessment
        logger.info(f"🎯 Assessing trade: {symbol} for ${proposed_size:.2f}")
        approved, assessment = risk_gate.pre_trade_risk_assessment(
            symbol=symbol,
            df=df,
            proposed_position_size=proposed_size,
            current_positions=current_positions,
            account_balance=account_balance
        )
        
        # Display results
        logger.info(f"\n📊 ASSESSMENT RESULT:")
        logger.info(f"   Approved: {'✅ YES' if approved else '❌ NO'}")
        logger.info(f"   Checks Passed: {assessment['checks_passed']}/{assessment['checks_total']}")
        
        if not approved:
            logger.warning(f"   Rejection Reasons:")
            for reason in assessment.get('rejection_reasons', []):
                logger.warning(f"   - {reason}")
        
        return approved, assessment
        
    except Exception as e:
        logger.error(f"❌ Example 2 failed: {e}")
        return False, None


def example_3_integrated_workflow():
    """
    Example 3: Integrated Risk Management Workflow
    
    This demonstrates:
    - Run legacy cleanup first
    - Check account is CLEAN
    - Then use risk intelligence gate for new entries
    - Complete risk management workflow
    """
    logger.info("\n" + "=" * 80)
    logger.info("EXAMPLE 3: Integrated Risk Management Workflow")
    logger.info("=" * 80 + "\n")
    
    try:
        from bot.position_tracker import PositionTracker
        from bot.broker_integration import get_broker_integration
        from bot.legacy_position_exit_protocol import LegacyPositionExitProtocol, AccountState
        from bot.risk_intelligence_gate import create_risk_intelligence_gate
        
        # Step 1: Initialize components
        logger.info("📦 Step 1: Initializing components...")
        position_tracker = PositionTracker()
        broker = get_broker_integration('coinbase')
        
        # Step 2: Run legacy cleanup
        logger.info("\n🧹 Step 2: Running legacy cleanup...")
        protocol = LegacyPositionExitProtocol(
            position_tracker=position_tracker,
            broker_integration=broker,
            monitor_high_exposure=True
        )
        
        cleanup_results = protocol.run_full_protocol()
        account_state = cleanup_results.get('phase4_verification', {}).get('account_state', 'UNKNOWN')
        
        logger.info(f"   Account State: {account_state}")
        
        # Step 3: Verify account is CLEAN before proceeding
        if account_state != AccountState.CLEAN.value:
            logger.warning("⚠️  Account not CLEAN - cleanup needed before new trades")
            logger.warning("   Run legacy exit protocol again or address issues manually")
            return False
        
        logger.info("✅ Account is CLEAN - proceeding to risk checks")
        
        # Step 4: Create risk intelligence gate
        logger.info("\n🎯 Step 3: Creating risk intelligence gate...")
        risk_gate = create_risk_intelligence_gate()
        
        # Step 5: Check proposed trade
        logger.info("\n🔍 Step 4: Evaluating proposed trade...")
        
        # Simulate trade proposal
        symbol = 'ETH-USD'
        proposed_size = 300.0
        account_balance = broker.get_account_balance()
        if isinstance(account_balance, dict):
            account_balance = account_balance.get('available', 0)
        
        current_positions = broker.get_open_positions()
        
        # Get market data
        try:
            df = broker.get_market_data(symbol, timeframe='1h', limit=100)
        except:
            import pandas as pd
            df = pd.DataFrame({
                'open': [3000] * 100,
                'high': [3100] * 100,
                'low': [2900] * 100,
                'close': [3050] * 100,
                'volume': [1000] * 100
            })
        
        # Pre-trade assessment
        approved, assessment = risk_gate.pre_trade_risk_assessment(
            symbol=symbol,
            df=df,
            proposed_position_size=proposed_size,
            current_positions=current_positions,
            account_balance=account_balance
        )
        
        # Step 6: Make decision
        logger.info("\n📊 FINAL DECISION:")
        if approved:
            logger.info("✅ ALL CHECKS PASSED - Trade approved")
            logger.info("   - Account is CLEAN")
            logger.info("   - Volatility is acceptable")
            logger.info("   - Correlation exposure is acceptable")
            logger.info("   → Proceed with trade execution")
        else:
            logger.warning("❌ TRADE REJECTED")
            logger.warning("   → Do NOT execute trade")
            if 'rejection_reasons' in assessment:
                for reason in assessment['rejection_reasons']:
                    logger.warning(f"   - {reason}")
        
        return approved
        
    except Exception as e:
        logger.error(f"❌ Example 3 failed: {e}")
        return False


def example_4_startup_integration():
    """
    Example 4: Integrate with Bot Startup
    
    This shows how to integrate legacy cleanup and risk checks at bot startup.
    """
    logger.info("\n" + "=" * 80)
    logger.info("EXAMPLE 4: Bot Startup Integration")
    logger.info("=" * 80 + "\n")
    
    def bot_startup_sequence():
        """Example bot startup sequence with integrated checks"""
        try:
            from bot.position_tracker import PositionTracker
            from bot.broker_integration import get_broker_integration
            from bot.legacy_position_exit_protocol import LegacyPositionExitProtocol, AccountState
            
            logger.info("🚀 Bot Starting Up...")
            
            # Step 1: Initialize core components
            logger.info("\n1️⃣ Initializing components...")
            position_tracker = PositionTracker()
            broker = get_broker_integration('coinbase')
            
            # Step 2: Verify account state
            logger.info("\n2️⃣ Verifying account state...")
            protocol = LegacyPositionExitProtocol(
                position_tracker=position_tracker,
                broker_integration=broker,
                monitor_high_exposure=True
            )
            
            # Quick verification (no cleanup, just check)
            state, diagnostics = protocol.verify_clean_state()
            
            if state != AccountState.CLEAN:
                logger.warning("⚠️  Account needs cleanup - running protocol...")
                results = protocol.run_full_protocol()
                
                if not results.get('success', False):
                    logger.error("❌ Cleanup failed - manual intervention needed")
                    return False
                
                logger.info("✅ Cleanup complete")
            else:
                logger.info("✅ Account is CLEAN")
            
            # Step 3: Initialize risk intelligence gate
            logger.info("\n3️⃣ Initializing risk intelligence gate...")
            from bot.risk_intelligence_gate import create_risk_intelligence_gate
            risk_gate = create_risk_intelligence_gate()
            
            logger.info("\n✅ Bot startup complete - ready for trading")
            logger.info("   - Account verified CLEAN")
            logger.info("   - High-exposure monitoring active")
            logger.info("   - Risk intelligence gate ready")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Startup failed: {e}")
            return False
    
    # Run startup sequence
    success = bot_startup_sequence()
    return success


def main():
    """Run all integration examples"""
    logger.info("=" * 80)
    logger.info("🎯 RISK INTELLIGENCE INTEGRATION EXAMPLES")
    logger.info("=" * 80)
    
    # Example 1: Legacy cleanup with monitoring
    logger.info("\n\n")
    example_1_legacy_cleanup_with_monitoring()
    
    # Example 2: Pre-trade risk checks
    logger.info("\n\n")
    example_2_pre_trade_risk_checks()
    
    # Example 3: Integrated workflow
    logger.info("\n\n")
    example_3_integrated_workflow()
    
    # Example 4: Startup integration
    logger.info("\n\n")
    example_4_startup_integration()
    
    logger.info("\n" + "=" * 80)
    logger.info("✅ ALL EXAMPLES COMPLETE")
    logger.info("=" * 80)


if __name__ == '__main__':
    main()
