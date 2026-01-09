#!/usr/bin/env python3
"""
Quick Diagnostic: Check Broker Configuration Status

This script checks which brokers are configured and ready to trade.
Run this to quickly see if NIJA can connect to Coinbase, Kraken, or other brokers.

Usage:
    python3 quick_broker_diagnostic.py
"""

import os
import sys

def print_header(title):
    """Print formatted header"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)

def print_section(title):
    """Print formatted section"""
    print("\n" + "-" * 80)
    print(f"  {title}")
    print("-" * 80)

def check_env_credentials():
    """Check which broker credentials are set in environment"""
    print_header("BROKER CREDENTIALS STATUS")
    
    brokers = {
        'Coinbase': {
            'key': 'COINBASE_API_KEY',
            'secret': 'COINBASE_API_SECRET',
            'optional': []
        },
        'Kraken': {
            'key': 'KRAKEN_API_KEY',
            'secret': 'KRAKEN_API_SECRET',
            'optional': []
        },
        'OKX': {
            'key': 'OKX_API_KEY',
            'secret': 'OKX_API_SECRET',
            'optional': ['OKX_PASSPHRASE']
        },
        'Binance': {
            'key': 'BINANCE_API_KEY',
            'secret': 'BINANCE_API_SECRET',
            'optional': []
        },
        'Alpaca': {
            'key': 'ALPACA_API_KEY',
            'secret': 'ALPACA_API_SECRET',
            'optional': []
        }
    }
    
    configured_brokers = []
    
    for broker_name, creds in brokers.items():
        print_section(broker_name)
        
        key = os.getenv(creds['key'])
        secret = os.getenv(creds['secret'])
        
        if key and secret:
            print(f"  ✅ {creds['key']}: SET ({len(key)} chars)")
            print(f"  ✅ {creds['secret']}: SET ({len(secret)} chars)")
            
            # Check optional credentials
            for opt_key in creds['optional']:
                opt_val = os.getenv(opt_key)
                if opt_val:
                    print(f"  ✅ {opt_key}: SET ({len(opt_val)} chars)")
                else:
                    print(f"  ⚠️  {opt_key}: NOT SET (optional)")
            
            print(f"\n  🎯 Status: CONFIGURED - {broker_name} can connect")
            configured_brokers.append(broker_name)
        else:
            if not key:
                print(f"  ❌ {creds['key']}: NOT SET")
            else:
                print(f"  ✅ {creds['key']}: SET ({len(key)} chars)")
                
            if not secret:
                print(f"  ❌ {creds['secret']}: NOT SET")
            else:
                print(f"  ✅ {creds['secret']}: SET ({len(secret)} chars)")
            
            print(f"\n  ⚠️  Status: NOT CONFIGURED - {broker_name} cannot connect")
    
    return configured_brokers

def check_sdk_availability():
    """Check which broker SDKs are installed"""
    print_header("BROKER SDK AVAILABILITY")
    
    sdks = {
        'Coinbase': ['coinbase.rest', 'coinbase-advanced-py'],
        'Kraken': ['krakenex', 'krakenex + pykrakenapi'],
        'OKX': ['okx', 'okx SDK'],
        'Binance': ['binance', 'python-binance'],
        'Alpaca': ['alpaca_trade_api', 'alpaca-trade-api']
    }
    
    available_sdks = []
    
    for broker_name, modules in sdks.items():
        module_to_check = modules[0]
        full_name = modules[1]
        
        try:
            if broker_name == 'Kraken':
                # Special check for Kraken (needs both krakenex and pykrakenapi)
                import krakenex
                from pykrakenapi import KrakenAPI
                print(f"  ✅ {broker_name}: SDK installed ({full_name})")
                available_sdks.append(broker_name)
            elif broker_name == 'Coinbase':
                from coinbase.rest import RESTClient
                print(f"  ✅ {broker_name}: SDK installed ({full_name})")
                available_sdks.append(broker_name)
            else:
                __import__(module_to_check)
                print(f"  ✅ {broker_name}: SDK installed ({full_name})")
                available_sdks.append(broker_name)
        except ImportError:
            print(f"  ❌ {broker_name}: SDK NOT installed ({full_name})")
            print(f"     Install with: pip install {full_name}")
    
    return available_sdks

def check_multi_broker_mode():
    """Check if multi-broker mode is enabled"""
    print_header("MULTI-BROKER MODE")
    
    multi_broker = os.getenv('MULTI_BROKER_INDEPENDENT', 'true').lower()
    
    if multi_broker in ['true', '1', 'yes']:
        print("  ✅ Multi-broker mode: ENABLED")
        print("     Bot will attempt to connect to all configured brokers")
        print("     Each broker trades independently")
        return True
    else:
        print("  ❌ Multi-broker mode: DISABLED")
        print("     Bot will only use primary broker (Coinbase)")
        return False

def main():
    """Main diagnostic function"""
    print_header("NIJA BROKER CONFIGURATION DIAGNOSTIC")
    print(f"  Run Date: {os.popen('date').read().strip()}")
    
    # Check credentials
    configured = check_env_credentials()
    
    # Check SDKs
    print("\n")
    available = check_sdk_availability()
    
    # Check multi-broker mode
    print("\n")
    multi_broker_enabled = check_multi_broker_mode()
    
    # Summary
    print_header("SUMMARY")
    
    print("\n  📊 Configured Brokers (have API credentials):")
    if configured:
        for broker in configured:
            print(f"     ✅ {broker}")
    else:
        print("     ❌ No brokers configured")
        print("     ⚠️  Set environment variables to configure brokers")
    
    print("\n  📦 Available SDKs (installed):")
    if available:
        for sdk in available:
            print(f"     ✅ {sdk}")
    else:
        print("     ❌ No broker SDKs installed")
        print("     ⚠️  Run: pip install -r requirements.txt")
    
    print("\n  🎯 Ready to Trade:")
    ready_brokers = set(configured) & set(available)
    if ready_brokers:
        for broker in ready_brokers:
            print(f"     ✅ {broker} - Credentials SET + SDK installed")
    else:
        print("     ❌ No brokers are ready")
        print("     ⚠️  Set credentials AND install SDKs")
    
    print("\n  🔧 Multi-Broker Mode:")
    if multi_broker_enabled:
        print("     ✅ ENABLED - Will use all ready brokers")
    else:
        print("     ❌ DISABLED - Will use only primary broker")
    
    # Recommendations
    print_header("RECOMMENDATIONS")
    
    if not configured:
        print("\n  ⚠️  NO BROKERS CONFIGURED")
        print("     1. Set environment variables for at least one broker")
        print("     2. Example for Coinbase:")
        print("        export COINBASE_API_KEY='your_key'")
        print("        export COINBASE_API_SECRET='your_secret'")
        print("     3. Or add to .env file")
    
    if not available:
        print("\n  ⚠️  NO SDKs INSTALLED")
        print("     1. Install dependencies:")
        print("        pip install -r requirements.txt")
        print("     2. Or install specific SDK:")
        print("        pip install coinbase-advanced-py")
        print("        pip install krakenex pykrakenapi")
    
    if configured and available and ready_brokers:
        print("\n  ✅ READY TO TRADE")
        print(f"     Bot can trade on: {', '.join(ready_brokers)}")
        print("     Start the bot with: python3 bot.py")
    
    if 'Coinbase' in configured and 'Coinbase' not in available:
        print("\n  ⚠️  COINBASE CONFIGURED BUT SDK MISSING")
        print("     Install with: pip install coinbase-advanced-py")
    
    if 'Kraken' in configured and 'Kraken' not in available:
        print("\n  ⚠️  KRAKEN CONFIGURED BUT SDK MISSING")
        print("     Install with: pip install krakenex pykrakenapi")
    
    if 'Coinbase' not in configured and 'Kraken' in ready_brokers:
        print("\n  ℹ️  TRADING WITH KRAKEN ONLY")
        print("     Coinbase not configured - using Kraken")
    
    if 'Kraken' not in configured and 'Coinbase' in ready_brokers:
        print("\n  ℹ️  TRADING WITH COINBASE ONLY")
        print("     Kraken not configured - using Coinbase")
    
    print("\n" + "=" * 80 + "\n")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Diagnostic interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
