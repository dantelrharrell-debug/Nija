#!/usr/bin/env python3
"""
Kraken Execution Audit - Diagnostic Test

Audits why Kraken hasn't executed any trades yet.
Tests all prerequisites for Kraken trading to work.

Priority C from architect's recommendation: "Audit why Kraken hasn't executed yet"
"""

import sys
import os
import logging
from typing import Dict, List

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_kraken_credentials():
    """
    Test if Kraken API credentials are configured.
    
    Without credentials, self.api remains None and all trading is blocked.
    """
    logger.info("=" * 80)
    logger.info("TEST 1: Kraken API Credentials")
    logger.info("=" * 80)
    
    issues = []
    
    # Check master account credentials
    master_key = os.getenv('KRAKEN_MASTER_API_KEY')
    master_secret = os.getenv('KRAKEN_MASTER_API_SECRET')
    
    if master_key and master_secret:
        logger.info(f"✅ KRAKEN MASTER credentials found")
        logger.info(f"   API Key: {master_key[:10]}... ({len(master_key)} chars)")
        logger.info(f"   API Secret: {master_secret[:10]}... ({len(master_secret)} chars)")
    else:
        logger.error(f"❌ KRAKEN MASTER credentials NOT configured")
        issues.append("Master account credentials missing")
        
        # Check legacy credentials
        legacy_key = os.getenv('KRAKEN_API_KEY')
        legacy_secret = os.getenv('KRAKEN_API_SECRET')
        if legacy_key and legacy_secret:
            logger.warning(f"⚠️  Legacy KRAKEN_API_KEY found but not KRAKEN_MASTER_API_KEY")
            logger.warning(f"   Rename to KRAKEN_MASTER_* for multi-account support")
        else:
            logger.error(f"❌ No Kraken credentials found (neither MASTER nor legacy)")
    
    # Check user account credentials
    users = ['DAIVON', 'TANIA']
    for user in users:
        user_key = os.getenv(f'KRAKEN_USER_{user}_API_KEY')
        user_secret = os.getenv(f'KRAKEN_USER_{user}_API_SECRET')
        
        if user_key and user_secret:
            logger.info(f"✅ KRAKEN USER {user} credentials found")
        else:
            logger.warning(f"⚠️  KRAKEN USER {user} credentials NOT configured (optional)")
    
    if issues:
        logger.error("")
        logger.error(f"❌ CRITICAL: {len(issues)} issue(s) found")
        for issue in issues:
            logger.error(f"   - {issue}")
        logger.error("")
        logger.error("Without credentials, KrakenBroker.api = None and all trading is blocked")
        return False
    
    logger.info("")
    logger.info("✅ Kraken credentials configured correctly")
    return True


def test_kraken_sdk_installed():
    """
    Test if Kraken SDK (krakenex + pykrakenapi) is installed.
    
    Without the SDK, KrakenBroker cannot initialize.
    """
    logger.info("")
    logger.info("=" * 80)
    logger.info("TEST 2: Kraken SDK Installation")
    logger.info("=" * 80)
    
    try:
        import krakenex
        logger.info("✅ krakenex module installed")
        logger.info(f"   Version: {krakenex.__version__ if hasattr(krakenex, '__version__') else 'unknown'}")
    except ImportError as e:
        logger.error(f"❌ krakenex module NOT installed: {e}")
        logger.error("   Install with: pip install krakenex")
        return False
    
    try:
        import pykrakenapi
        logger.info("✅ pykrakenapi module installed")
        logger.info(f"   Version: {pykrakenapi.__version__ if hasattr(pykrakenapi, '__version__') else 'unknown'}")
    except ImportError as e:
        logger.error(f"❌ pykrakenapi module NOT installed: {e}")
        logger.error("   Install with: pip install pykrakenapi")
        return False
    
    logger.info("")
    logger.info("✅ Kraken SDK installed correctly")
    return True


def test_kraken_broker_initialization():
    """
    Test if KrakenBroker class can be imported and initialized.
    """
    logger.info("")
    logger.info("=" * 80)
    logger.info("TEST 3: KrakenBroker Initialization")
    logger.info("=" * 80)
    
    try:
        from bot.broker_manager import KrakenBroker, BrokerType, AccountType
        logger.info("✅ KrakenBroker class imported")
        
        # Verify class has required methods
        required_methods = ['place_market_order', 'get_account_balance', 'supports_symbol']
        for method in required_methods:
            if hasattr(KrakenBroker, method):
                logger.info(f"✅ KrakenBroker.{method}() exists")
            else:
                logger.error(f"❌ KrakenBroker.{method}() NOT found")
                return False
        
        logger.info("")
        logger.info("✅ KrakenBroker class structure validated")
        return True
        
    except ImportError as e:
        logger.error(f"❌ Failed to import KrakenBroker: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        return False


def test_kraken_symbol_support():
    """
    Test if Kraken symbol filtering is working correctly.
    
    Kraken should reject BUSD pairs (Binance-only).
    """
    logger.info("")
    logger.info("=" * 80)
    logger.info("TEST 4: Kraken Symbol Filtering")
    logger.info("=" * 80)
    
    try:
        from bot.broker_manager import KrakenBroker, BrokerType, AccountType
        
        # Create a mock KrakenBroker instance
        # We can't connect without real credentials, so we'll test the logic directly
        
        # Test symbols
        test_cases = [
            ('BTC-USD', True, 'Standard crypto pair'),
            ('ETH-USD', True, 'Standard crypto pair'),
            ('SOL-USD', True, 'Standard crypto pair'),
            ('BTC-BUSD', False, 'BUSD not supported on Kraken'),
            ('ETH-BUSD', False, 'BUSD not supported on Kraken'),
            ('MATIC-USDT', True, 'USDT is supported on Kraken'),
        ]
        
        # Create mock broker to test supports_symbol
        from unittest.mock import Mock
        mock_broker = Mock(spec=KrakenBroker)
        mock_broker.broker_type = BrokerType.KRAKEN
        
        # Test the supports_symbol method from BaseBroker
        from bot.broker_manager import BaseBroker
        
        all_passed = True
        for symbol, expected, description in test_cases:
            # Use BaseBroker.supports_symbol (which KrakenBroker inherits)
            result = BaseBroker.supports_symbol(mock_broker, symbol)
            
            if result == expected:
                logger.info(f"✅ {symbol}: {description} - {'Supported' if result else 'Rejected'}")
            else:
                logger.error(f"❌ {symbol}: {description} - Expected {expected}, got {result}")
                all_passed = False
        
        if all_passed:
            logger.info("")
            logger.info("✅ Kraken symbol filtering working correctly")
            logger.info("   BUSD pairs are properly rejected")
            return True
        else:
            logger.error("")
            logger.error("❌ Kraken symbol filtering has issues")
            return False
        
    except Exception as e:
        logger.error(f"❌ Symbol filtering test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_kraken_nonce_management():
    """
    Test if Kraken nonce management is properly configured.
    
    Nonce errors can prevent all Kraken API calls.
    """
    logger.info("")
    logger.info("=" * 80)
    logger.info("TEST 5: Kraken Nonce Management")
    logger.info("=" * 80)
    
    try:
        # Check if global nonce manager exists
        try:
            from bot.global_kraken_nonce import GlobalKrakenNonceManager
            logger.info("✅ GlobalKrakenNonceManager class found")
        except ImportError:
            logger.warning("⚠️  GlobalKrakenNonceManager not found (may use per-broker nonce)")
        
        # Check if KrakenNonce class exists
        try:
            from bot.kraken_nonce import KrakenNonce
            logger.info("✅ KrakenNonce class found")
        except ImportError:
            logger.warning("⚠️  KrakenNonce class not found (may use fallback implementation)")
        
        # Verify KrakenBroker has nonce handling
        from bot.broker_manager import KrakenBroker
        if hasattr(KrakenBroker, '_kraken_private_call'):
            logger.info("✅ KrakenBroker._kraken_private_call() method exists")
        else:
            logger.error("❌ KrakenBroker._kraken_private_call() method NOT found")
            return False
        
        logger.info("")
        logger.info("✅ Kraken nonce management structure in place")
        return True
        
    except Exception as e:
        logger.error(f"❌ Nonce management test failed: {e}")
        return False


def test_kraken_place_order_logic():
    """
    Test the KrakenBroker.place_market_order() method logic.
    
    Verifies all the checks that could block order execution.
    """
    logger.info("")
    logger.info("=" * 80)
    logger.info("TEST 6: Kraken Order Placement Logic")
    logger.info("=" * 80)
    
    try:
        # Read the broker_manager.py to check place_market_order logic
        with open('bot/broker_manager.py', 'r') as f:
            content = f.read()
        
        # Find the place_market_order method for KrakenBroker
        kraken_place_order_start = content.find('class KrakenBroker')
        if kraken_place_order_start == -1:
            logger.error("❌ KrakenBroker class not found in broker_manager.py")
            return False
        
        # Extract KrakenBroker section
        next_class = content.find('\nclass ', kraken_place_order_start + 1)
        kraken_section = content[kraken_place_order_start:next_class if next_class != -1 else len(content)]
        
        # Check for place_market_order method
        if 'def place_market_order' in kraken_section:
            logger.info("✅ KrakenBroker.place_market_order() method found")
        else:
            logger.error("❌ KrakenBroker.place_market_order() method NOT found")
            return False
        
        # Check for API connection check
        if 'if not self.api:' in kraken_section:
            logger.info("✅ API connection check exists (line: if not self.api)")
            logger.info("   This blocks trading when credentials are not configured")
        else:
            logger.warning("⚠️  API connection check not found")
        
        # Check for supports_symbol check
        if 'self.supports_symbol' in kraken_section:
            logger.info("✅ Symbol support check exists (filters BUSD pairs)")
        else:
            logger.warning("⚠️  Symbol support check not found")
        
        # Check for trade confirmation logging
        if 'TRADE CONFIRMATION' in kraken_section:
            logger.info("✅ Trade confirmation logging exists")
            logger.info("   Should log when Kraken orders execute successfully")
        else:
            logger.warning("⚠️  Trade confirmation logging not found")
        
        logger.info("")
        logger.info("✅ Kraken order placement logic structure validated")
        logger.info("")
        logger.info("Order execution flow:")
        logger.info("  1. Check if self.api is connected (blocks if no credentials)")
        logger.info("  2. Check if symbol is supported (blocks BUSD pairs)")
        logger.info("  3. Normalize symbol to Kraken format")
        logger.info("  4. Call Kraken API with nonce")
        logger.info("  5. Log trade confirmation if successful")
        
        return True
        
    except FileNotFoundError:
        logger.error("❌ Could not find bot/broker_manager.py")
        return False
    except Exception as e:
        logger.error(f"❌ Order logic test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_trade_journal_analysis():
    """
    Analyze trade_journal.jsonl to confirm no Kraken trades.
    """
    logger.info("")
    logger.info("=" * 80)
    logger.info("TEST 7: Trade Journal Analysis")
    logger.info("=" * 80)
    
    try:
        import json
        
        if not os.path.exists('trade_journal.jsonl'):
            logger.warning("⚠️  trade_journal.jsonl not found (no trades yet)")
            return True
        
        kraken_trades = []
        coinbase_trades = []
        total_trades = 0
        
        with open('trade_journal.jsonl', 'r') as f:
            for line in f:
                if line.strip():
                    total_trades += 1
                    try:
                        trade = json.loads(line)
                        broker = trade.get('broker', '').lower()
                        
                        if 'kraken' in broker:
                            kraken_trades.append(trade)
                        elif 'coinbase' in broker:
                            coinbase_trades.append(trade)
                    except json.JSONDecodeError:
                        pass
        
        logger.info(f"Trade Statistics:")
        logger.info(f"  Total trades: {total_trades}")
        logger.info(f"  Kraken trades: {len(kraken_trades)}")
        logger.info(f"  Coinbase trades: {len(coinbase_trades)}")
        
        if len(kraken_trades) == 0:
            logger.warning("")
            logger.warning("⚠️  ZERO Kraken trades found in journal")
            logger.warning("   This confirms Kraken has not executed any trades")
            
            if total_trades == 0:
                logger.info("   (No trades from any broker - system may be in setup)")
            else:
                logger.warning(f"   ({len(coinbase_trades)} Coinbase trades found - bot IS trading)")
        else:
            logger.info(f"✅ Found {len(kraken_trades)} Kraken trades")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Trade journal analysis failed: {e}")
        return False


def generate_diagnostic_report():
    """
    Generate a comprehensive diagnostic report for Kraken execution.
    """
    logger.info("")
    logger.info("=" * 80)
    logger.info("DIAGNOSTIC REPORT: Why Kraken Hasn't Executed Trades")
    logger.info("=" * 80)
    logger.info("")
    
    # Check credentials
    master_key = os.getenv('KRAKEN_MASTER_API_KEY')
    master_secret = os.getenv('KRAKEN_MASTER_API_SECRET')
    
    if not (master_key and master_secret):
        logger.error("🔴 ROOT CAUSE: Kraken API credentials are NOT configured")
        logger.error("")
        logger.error("WHY THIS BLOCKS TRADING:")
        logger.error("  1. KrakenBroker.__init__() checks for API credentials")
        logger.error("  2. If missing, self.api = None")
        logger.error("  3. place_market_order() checks: if not self.api: return error")
        logger.error("  4. ALL trading attempts are blocked")
        logger.error("")
        logger.error("SOLUTION:")
        logger.error("  1. Get Kraken API credentials from: https://www.kraken.com/u/security/api")
        logger.error("  2. Set environment variables:")
        logger.error("     export KRAKEN_MASTER_API_KEY='your-key-here'")
        logger.error("     export KRAKEN_MASTER_API_SECRET='your-secret-here'")
        logger.error("  3. Restart the bot")
        logger.error("")
        logger.error("PERMISSIONS REQUIRED:")
        logger.error("  ✓ Query Funds")
        logger.error("  ✓ Query Open Orders & Trades")
        logger.error("  ✓ Query Closed Orders & Trades")
        logger.error("  ✓ Create & Modify Orders")
        logger.error("  ✓ Cancel/Close Orders")
        logger.error("  ✗ Do NOT enable 'Withdraw Funds' (security)")
        return
    
    logger.info("✅ Credentials are configured - Kraken SHOULD be able to trade")
    logger.info("")
    logger.info("Possible reasons for no trades:")
    logger.info("  1. Bot hasn't found any trading signals for Kraken-supported pairs")
    logger.info("  2. BUSD pairs are being filtered out (expected behavior)")
    logger.info("  3. Nonce errors preventing API calls")
    logger.info("  4. Kraken SDK not installed in deployment environment")
    logger.info("  5. Balance too low to meet minimum position size")
    logger.info("")
    logger.info("NEXT STEPS:")
    logger.info("  1. Check bot logs for Kraken connection messages")
    logger.info("  2. Verify Kraken SDK is installed in production: start.sh checks this")
    logger.info("  3. Review recent trades to see if any Kraken orders were attempted")
    logger.info("  4. Check Kraken account balance: needs minimum $5-10 for trading")


def main():
    """Run all Kraken execution audit tests."""
    logger.info("\n")
    logger.info("╔" + "=" * 78 + "╗")
    logger.info("║" + " " * 20 + "KRAKEN EXECUTION AUDIT" + " " * 35 + "║")
    logger.info("║" + " " * 15 + "Priority C: Audit Why Kraken Not Trading" + " " * 21 + "║")
    logger.info("╚" + "=" * 78 + "╝")
    logger.info("\n")
    
    tests = [
        ("Kraken Credentials", test_kraken_credentials),
        ("Kraken SDK Installation", test_kraken_sdk_installed),
        ("KrakenBroker Initialization", test_kraken_broker_initialization),
        ("Symbol Filtering", test_kraken_symbol_support),
        ("Nonce Management", test_kraken_nonce_management),
        ("Order Placement Logic", test_kraken_place_order_logic),
        ("Trade Journal Analysis", test_trade_journal_analysis),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            logger.error(f"❌ Test '{test_name}' crashed: {e}")
            import traceback
            traceback.print_exc()
            results.append((test_name, False))
    
    # Generate diagnostic report
    generate_diagnostic_report()
    
    # Summary
    logger.info("")
    logger.info("=" * 80)
    logger.info("TEST SUMMARY")
    logger.info("=" * 80)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"{status} - {test_name}")
    
    logger.info("")
    logger.info(f"Results: {passed}/{total} tests passed")
    
    if passed == total:
        logger.info("✅ All Kraken prerequisites validated")
        return 0
    else:
        logger.error(f"❌ {total - passed} issue(s) found - review diagnostic report above")
        return 1


if __name__ == "__main__":
    sys.exit(main())
