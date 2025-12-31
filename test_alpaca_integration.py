"""
Alpaca API Testing Script
Tests Alpaca integration with paper trading account
"""

import os
import sys

# Add bot directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

print("=" * 70)
print("ALPACA API TEST SCRIPT")
print("=" * 70)
print()

# ============================================================================
# METHOD 1: Using older alpaca_trade_api library (as provided in comment)
# ============================================================================

try:
    import alpaca_trade_api as tradeapi
    
    print("📦 Method 1: Using alpaca_trade_api library")
    print("-" * 70)
    
    # Alpaca API credentials (Paper Trading)
    API_KEY = "PKS2NORMEX6BMN6P3T63C7ICZ2"
    API_SECRET = "GPmZyiXDoP3A8VcsjcdiCcmdBdzFQnBsmyGSTFQpWyPJ"
    BASE_URL = "https://paper-api.alpaca.markets/v2"
    
    # Initialize API connection
    print(f"🔌 Connecting to Alpaca (Paper Trading)...")
    api = tradeapi.REST(API_KEY, API_SECRET, BASE_URL, api_version='v2')
    
    # Example: Get account information
    print(f"📊 Fetching account information...")
    account = api.get_account()
    print(f"✅ Account Status: {account.status}")
    print(f"💰 Cash: ${float(account.cash):,.2f}")
    print(f"💵 Buying Power: ${float(account.buying_power):,.2f}")
    print(f"📈 Portfolio Value: ${float(account.portfolio_value):,.2f}")
    print()
    
    # Example: Get list of positions
    print(f"📋 Fetching current positions...")
    positions = api.list_positions()
    if positions:
        print(f"✅ Found {len(positions)} position(s):")
        for position in positions:
            print(f"   - {position.symbol}: {position.qty} shares @ ${float(position.current_price):,.2f}")
            print(f"     P&L: ${float(position.unrealized_pl):,.2f} ({float(position.unrealized_plpc)*100:.2f}%)")
    else:
        print("ℹ️  No open positions")
    print()
    
    print("✅ Method 1: alpaca_trade_api - SUCCESS")
    print()

except ImportError as e:
    print(f"⚠️  alpaca_trade_api library not installed: {e}")
    print(f"   Install with: pip install alpaca-trade-api")
    print()
except Exception as e:
    print(f"❌ Method 1 Error: {e}")
    print()

# ============================================================================
# METHOD 2: Using newer alpaca-py library (NIJA's current integration)
# ============================================================================

try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce
    
    print("📦 Method 2: Using alpaca-py library (NIJA's integration)")
    print("-" * 70)
    
    # Same credentials
    API_KEY = "PKS2NORMEX6BMN6P3T63C7ICZ2"
    API_SECRET = "GPmZyiXDoP3A8VcsjcdiCcmdBdzFQnBsmyGSTFQpWyPJ"
    
    # Initialize with newer SDK
    print(f"🔌 Connecting to Alpaca (Paper Trading)...")
    client = TradingClient(API_KEY, API_SECRET, paper=True)
    
    # Get account information
    print(f"📊 Fetching account information...")
    account = client.get_account()
    print(f"✅ Account Status: {account.status}")
    print(f"💰 Cash: ${float(account.cash):,.2f}")
    print(f"💵 Buying Power: ${float(account.buying_power):,.2f}")
    print(f"📈 Portfolio Value: ${float(account.portfolio_value):,.2f}")
    print()
    
    # Get positions
    print(f"📋 Fetching current positions...")
    positions = client.get_all_positions()
    if positions:
        print(f"✅ Found {len(positions)} position(s):")
        for position in positions:
            print(f"   - {position.symbol}: {position.qty} shares @ ${float(position.current_price):,.2f}")
            print(f"     P&L: ${float(position.unrealized_pl):,.2f} ({float(position.unrealized_plpc)*100:.2f}%)")
    else:
        print("ℹ️  No open positions")
    print()
    
    print("✅ Method 2: alpaca-py - SUCCESS")
    print()

except ImportError as e:
    print(f"⚠️  alpaca-py library not installed: {e}")
    print(f"   Install with: pip install alpaca-py")
    print()
except Exception as e:
    print(f"❌ Method 2 Error: {e}")
    print()

# ============================================================================
# METHOD 3: Using NIJA's AlpacaBroker class
# ============================================================================

try:
    from broker_manager import AlpacaBroker
    
    print("📦 Method 3: Using NIJA's AlpacaBroker class")
    print("-" * 70)
    
    # Set environment variables for NIJA integration
    os.environ["ALPACA_API_KEY"] = "PKS2NORMEX6BMN6P3T63C7ICZ2"
    os.environ["ALPACA_API_SECRET"] = "GPmZyiXDoP3A8VcsjcdiCcmdBdzFQnBsmyGSTFQpWyPJ"
    os.environ["ALPACA_PAPER"] = "true"
    
    # Initialize broker
    print(f"🔌 Initializing AlpacaBroker...")
    broker = AlpacaBroker()
    
    # Connect
    if broker.connect():
        print(f"✅ Connected to Alpaca via NIJA's AlpacaBroker")
        
        # Get balance
        balance = broker.get_account_balance()
        print(f"💰 Account Balance: ${balance:,.2f}")
        
        # Get positions
        positions = broker.get_positions()
        if positions:
            print(f"📋 Found {len(positions)} position(s):")
            for symbol, position in positions.items():
                print(f"   - {symbol}: {position.get('quantity', 'N/A')} shares")
        else:
            print("ℹ️  No open positions")
        
        print()
        print("✅ Method 3: NIJA AlpacaBroker - SUCCESS")
    else:
        print("❌ Failed to connect via AlpacaBroker")
    print()

except ImportError as e:
    print(f"⚠️  Could not import AlpacaBroker: {e}")
    print(f"   Make sure you're running from NIJA directory")
    print()
except Exception as e:
    print(f"❌ Method 3 Error: {e}")
    print()

# ============================================================================
# SUMMARY
# ============================================================================

print("=" * 70)
print("TEST SUMMARY")
print("=" * 70)
print()
print("✅ This script tests Alpaca integration using:")
print("   1. alpaca_trade_api library (older, as provided in comment)")
print("   2. alpaca-py library (newer, NIJA's current integration)")
print("   3. NIJA's AlpacaBroker class")
print()
print("📝 API Credentials (Paper Trading):")
print(f"   API Key: PKS2NORMEX6BMN6P3T63C7ICZ2")
print(f"   Base URL: https://paper-api.alpaca.markets/v2")
print()
print("🎯 To use with NIJA:")
print("   1. Add credentials to .env file:")
print("      ALPACA_API_KEY=PKS2NORMEX6BMN6P3T63C7ICZ2")
print("      ALPACA_API_SECRET=GPmZyiXDoP3A8VcsjcdiCcmdBdzFQnBsmyGSTFQpWyPJ")
print("      ALPACA_PAPER=true")
print()
print("   2. Test connection:")
print("      python test_alpaca_integration.py")
print()
print("   3. Check broker status:")
print("      python check_broker_status.py")
print()
print("=" * 70)
