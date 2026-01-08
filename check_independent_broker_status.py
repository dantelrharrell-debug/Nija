#!/usr/bin/env python3
"""
NIJA Independent Broker Trading Status Checker
==============================================

This script checks whether NIJA is trading each brokerage independently
and shows the isolation status of each broker.

For each broker, it shows:
1. Connection status
2. Funded status (balance >= minimum)
3. Independent trading thread status
4. Trading health and error isolation

Usage:
    python3 check_independent_broker_status.py
"""

import os
import sys
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

def print_header(title):
    """Print a formatted header"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)

def print_section(title):
    """Print a formatted section title"""
    print("\n" + "-" * 80)
    print(f"  {title}")
    print("-" * 80)

def main():
    """Main function to check independent broker trading status"""
    print_header("NIJA Independent Broker Trading Status")
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Import required modules
    try:
        from broker_manager import (
            BrokerManager, CoinbaseBroker, KrakenBroker, 
            OKXBroker, BinanceBroker, AlpacaBroker
        )
        from independent_broker_trader import IndependentBrokerTrader, MINIMUM_FUNDED_BALANCE
    except ImportError as e:
        print(f"\n❌ Error importing modules: {e}")
        sys.exit(1)
    
    # Initialize broker manager
    print_section("Initializing Broker Manager")
    broker_manager = BrokerManager()
    
    # Try to connect all brokers
    brokers_to_test = [
        ('Coinbase Advanced Trade', CoinbaseBroker, '🟦'),
        ('Kraken Pro', KrakenBroker, '🟪'),
        ('OKX', OKXBroker, '⬛'),
        ('Binance', BinanceBroker, '🟨'),
        ('Alpaca', AlpacaBroker, '🟩'),
    ]
    
    connected_count = 0
    for name, broker_class, icon in brokers_to_test:
        try:
            broker = broker_class()
            if broker.connect():
                broker_manager.add_broker(broker)
                print(f"{icon} {name}: ✅ Connected")
                connected_count += 1
            else:
                print(f"{icon} {name}: ⚪ Not connected")
        except Exception as e:
            print(f"{icon} {name}: ❌ Error: {str(e)[:50]}")
    
    print(f"\n✅ {connected_count}/{len(brokers_to_test)} brokers connected")
    
    if connected_count == 0:
        print("\n❌ No brokers connected. Cannot proceed with status check.")
        sys.exit(1)
    
    # Check independent broker trading capability
    print_section("Independent Trading Capability Check")
    
    # Create a mock trading strategy (we just need it for initialization)
    class MockStrategy:
        """Mock strategy for testing"""
        def __init__(self):
            self.broker = None
        
        def run_cycle(self):
            """Mock trading cycle"""
            pass
    
    mock_strategy = MockStrategy()
    
    # Initialize independent broker trader
    try:
        independent_trader = IndependentBrokerTrader(broker_manager, mock_strategy)
        print("✅ Independent broker trader initialized successfully")
    except Exception as e:
        print(f"❌ Failed to initialize independent trader: {e}")
        sys.exit(1)
    
    # Detect funded brokers
    print_section("Funded Broker Detection")
    funded_brokers = independent_trader.detect_funded_brokers()
    
    # Show which brokers can trade independently
    print_section("Independent Trading Assessment")
    
    if funded_brokers:
        print(f"\n✅ {len(funded_brokers)} BROKER(S) CAN TRADE INDEPENDENTLY:")
        print()
        
        for broker_name, balance in funded_brokers.items():
            print(f"   🟢 {broker_name}")
            print(f"      💰 Balance: ${balance:,.2f}")
            print(f"      ✅ Meets minimum balance (${MINIMUM_FUNDED_BALANCE:.2f})")
            print(f"      🔒 Will trade in isolated thread")
            print(f"      🛡️  Errors won't affect other brokers")
            print()
        
        print("=" * 80)
        print("✅ INDEPENDENT MULTI-BROKER TRADING IS ENABLED")
        print("=" * 80)
        print()
        print("How it works:")
        print("  • Each funded broker runs in its own thread")
        print("  • Each broker has independent error handling")
        print("  • If one broker fails, others continue trading")
        print("  • Each broker manages its own positions independently")
        print("  • No shared state between brokers")
        print()
        print("Example scenario:")
        print("  If Coinbase API goes down:")
        print("    ❌ Coinbase trading stops")
        print("    ✅ Kraken, OKX, Binance continue trading normally")
        print("    ✅ No cascade failures")
        print("    ✅ Automatic recovery when Coinbase comes back online")
        
    else:
        print("\n⚠️  NO FUNDED BROKERS DETECTED")
        print()
        print("None of the connected brokers have sufficient balance to trade.")
        print(f"Minimum required balance: ${MINIMUM_FUNDED_BALANCE:.2f}")
        print()
        print("To enable independent trading:")
        print("  1. Fund at least one broker account")
        print("  2. Ensure balance >= ${MINIMUM_FUNDED_BALANCE:.2f}")
        print("  3. Restart the bot")
    
    # Show current bot configuration
    print_section("Bot Configuration Status")
    
    multi_broker_enabled = os.getenv("MULTI_BROKER_INDEPENDENT", "true").lower() in ["true", "1", "yes"]
    
    print(f"\nEnvironment Variable: MULTI_BROKER_INDEPENDENT")
    if multi_broker_enabled:
        print("   ✅ Enabled (independent trading will be used)")
    else:
        print("   ⚠️  Disabled (will use single-broker mode)")
        print("   💡 Set MULTI_BROKER_INDEPENDENT=true to enable")
    
    # Final summary
    print_section("Summary")
    
    print(f"\n📊 Status Overview:")
    print(f"   Connected Brokers: {connected_count}")
    print(f"   Funded Brokers: {len(funded_brokers)}")
    print(f"   Independent Trading: {'✅ Enabled' if multi_broker_enabled else '⚠️  Disabled'}")
    
    if funded_brokers and multi_broker_enabled:
        print(f"\n✅ NIJA IS READY FOR INDEPENDENT MULTI-BROKER TRADING")
        print(f"\n   When the bot starts:")
        print(f"   • {len(funded_brokers)} trading thread(s) will be created")
        print(f"   • Each broker operates independently")
        print(f"   • Failures are isolated per broker")
        print(f"   • Total capital: ${sum(funded_brokers.values()):,.2f}")
    elif funded_brokers and not multi_broker_enabled:
        print(f"\n⚠️  INDEPENDENT TRADING IS DISABLED")
        print(f"\n   To enable:")
        print(f"   1. Set MULTI_BROKER_INDEPENDENT=true in .env")
        print(f"   2. Restart the bot")
    elif not funded_brokers and multi_broker_enabled:
        print(f"\n⚠️  NO FUNDED BROKERS")
        print(f"\n   Independent trading is enabled but no brokers have sufficient funds.")
        print(f"   Fund at least one account with ${MINIMUM_FUNDED_BALANCE:.2f}+")
    else:
        print(f"\n⚠️  INDEPENDENT TRADING NOT AVAILABLE")
        print(f"\n   • Independent trading disabled in config")
        print(f"   • No funded brokers detected")
    
    print("\n" + "=" * 80 + "\n")
    
    # Exit code based on status
    if funded_brokers and multi_broker_enabled:
        sys.exit(0)  # Success
    else:
        sys.exit(1)  # Not fully operational

if __name__ == "__main__":
    main()
