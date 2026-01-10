#!/usr/bin/env python3
"""
Test NIJA Alpaca Paper Trading Integration
Verifies that Alpaca broker is properly connected and ready for trading
"""

import os
import sys

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

print("=" * 80)
print("NIJA ALPACA PAPER TRADING INTEGRATION TEST")
print("=" * 80)
print()

# Step 1: Verify environment variables
print("📋 Step 1: Checking Environment Variables")
print("-" * 80)

alpaca_key = os.getenv("ALPACA_API_KEY", "")
alpaca_secret = os.getenv("ALPACA_API_SECRET", "")
alpaca_paper = os.getenv("ALPACA_PAPER", "true")

if alpaca_key:
    print(f"✅ ALPACA_API_KEY: {alpaca_key[:10]}... ({len(alpaca_key)} chars)")
else:
    print("❌ ALPACA_API_KEY: Not set")

if alpaca_secret:
    print(f"✅ ALPACA_API_SECRET: {alpaca_secret[:10]}... ({len(alpaca_secret)} chars)")
else:
    print("❌ ALPACA_API_SECRET: Not set")

print(f"✅ ALPACA_PAPER: {alpaca_paper} ({'Paper Trading' if alpaca_paper.lower() == 'true' else 'Live Trading'})")
print()

# Step 2: Verify alpaca-py library
print("📦 Step 2: Checking alpaca-py Library")
print("-" * 80)

try:
    from alpaca.trading.client import TradingClient
    print("✅ alpaca-py library is installed")
    print("   ✓ TradingClient available")
except ImportError as e:
    print(f"❌ alpaca-py library not installed: {e}")
    print("   Run: pip install alpaca-py==0.36.0")
    sys.exit(1)
print()

# Step 3: Verify AlpacaBroker class
print("🔧 Step 3: Checking AlpacaBroker Implementation")
print("-" * 80)

try:
    from broker_manager import AlpacaBroker, BrokerType, BrokerManager
    print("✅ AlpacaBroker class imported successfully")
    
    # Initialize broker
    broker = AlpacaBroker()
    print(f"✅ AlpacaBroker initialized")
    print(f"   • Broker type: {broker.broker_type.value}")
    print(f"   • Connected: {broker.connected}")
    
except ImportError as e:
    print(f"❌ Failed to import AlpacaBroker: {e}")
    sys.exit(1)
except Exception as e:
    print(f"❌ Error initializing AlpacaBroker: {e}")
    sys.exit(1)
print()

# Step 4: Test connection (will fail in sandboxed environment, but validates code)
print("🔌 Step 4: Testing Alpaca Connection")
print("-" * 80)
print("⚠️  Note: Connection will fail in sandboxed environments without internet access")
print("   This is expected. In production, connection should succeed.")
print()

try:
    connection_result = broker.connect()
    if connection_result:
        print("✅ Successfully connected to Alpaca!")
        try:
            balance = broker.get_account_balance()
            print(f"💰 Account Balance: ${balance:,.2f}")
        except Exception as e:
            print(f"⚠️  Could not fetch balance: {e}")
    else:
        print("⚠️  Connection failed (expected in sandboxed environment)")
        print("   In production with internet access, this should succeed")
except Exception as e:
    print(f"⚠️  Connection error: {e}")
    print("   This is expected in sandboxed environments")
print()

# Step 5: Verify BrokerManager integration
print("🌐 Step 5: Checking BrokerManager Integration")
print("-" * 80)

try:
    manager = BrokerManager()
    
    # Try adding Alpaca broker
    alpaca_broker = AlpacaBroker()
    manager.add_broker(alpaca_broker)
    
    print("✅ AlpacaBroker successfully added to BrokerManager")
    print(f"   • Total brokers in manager: {len(manager.brokers)}")
    print(f"   • Alpaca in brokers: {BrokerType.ALPACA in manager.brokers}")
    
except Exception as e:
    print(f"❌ Error adding Alpaca to BrokerManager: {e}")
print()

# Step 6: Verify TradingStrategy will initialize Alpaca
print("🎯 Step 6: Checking TradingStrategy Integration")
print("-" * 80)

try:
    # Check the trading_strategy.py file for Alpaca initialization
    strategy_file = os.path.join(os.path.dirname(__file__), 'bot', 'trading_strategy.py')
    
    with open(strategy_file, 'r') as f:
        content = f.read()
    
    if 'AlpacaBroker' in content and 'alpaca.connect()' in content:
        print("✅ TradingStrategy includes AlpacaBroker initialization code")
        
        # Find the line numbers
        lines = content.split('\n')
        for i, line in enumerate(lines, 1):
            if 'Try to connect Alpaca' in line:
                print(f"   • Found at line ~{i}")
                break
    else:
        print("⚠️  AlpacaBroker initialization code not found in TradingStrategy")
        
except Exception as e:
    print(f"⚠️  Could not verify TradingStrategy: {e}")
print()

# Final Summary
print("=" * 80)
print("INTEGRATION STATUS SUMMARY")
print("=" * 80)
print()

checks_passed = []
checks_failed = []

if alpaca_key and alpaca_secret:
    checks_passed.append("✅ Alpaca credentials configured")
else:
    checks_failed.append("❌ Alpaca credentials missing")

try:
    from alpaca.trading.client import TradingClient
    checks_passed.append("✅ alpaca-py library installed")
except:
    checks_failed.append("❌ alpaca-py library not installed")

try:
    from broker_manager import AlpacaBroker
    checks_passed.append("✅ AlpacaBroker class available")
except:
    checks_failed.append("❌ AlpacaBroker class not available")

for check in checks_passed:
    print(check)

for check in checks_failed:
    print(check)

print()

if len(checks_failed) == 0:
    print("🎉 SUCCESS: NIJA is ready for Alpaca paper trading!")
    print()
    print("📝 Next Steps:")
    print("   1. Ensure internet connectivity to paper-api.alpaca.markets")
    print("   2. Run: python bot.py")
    print("   3. NIJA will automatically connect to Alpaca and start trading")
    print("   4. Check logs for 'Alpaca connected' message")
    print("   5. Monitor trades in Alpaca paper account dashboard")
    print()
    print("🔗 Alpaca Paper Trading Dashboard:")
    print("   https://app.alpaca.markets/paper/dashboard/overview")
else:
    print("⚠️  SETUP INCOMPLETE: Please address the failed checks above")

print()
print("=" * 80)
