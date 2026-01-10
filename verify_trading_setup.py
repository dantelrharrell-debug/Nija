#!/usr/bin/env python3
"""
Verify Trading Setup - Check if NIJA is properly configured to trade
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()

def check_credentials():
    """Check if all required credentials are set"""
    print("="*70)
    print("CHECKING CREDENTIALS")
    print("="*70)
    
    credentials = {
        'Coinbase MASTER': {
            'COINBASE_API_KEY': os.getenv('COINBASE_API_KEY'),
            'COINBASE_API_SECRET': os.getenv('COINBASE_API_SECRET'),
        },
        'Kraken MASTER': {
            'KRAKEN_MASTER_API_KEY': os.getenv('KRAKEN_MASTER_API_KEY'),
            'KRAKEN_MASTER_API_SECRET': os.getenv('KRAKEN_MASTER_API_SECRET'),
        },
        'User #1 (Daivon) Kraken': {
            'KRAKEN_USER_DAIVON_API_KEY': os.getenv('KRAKEN_USER_DAIVON_API_KEY'),
            'KRAKEN_USER_DAIVON_API_SECRET': os.getenv('KRAKEN_USER_DAIVON_API_SECRET'),
        },
        'Alpaca MASTER (Paper)': {
            'ALPACA_API_KEY': os.getenv('ALPACA_API_KEY'),
            'ALPACA_API_SECRET': os.getenv('ALPACA_API_SECRET'),
        },
        'OKX MASTER (Optional)': {
            'OKX_API_KEY': os.getenv('OKX_API_KEY'),
            'OKX_API_SECRET': os.getenv('OKX_API_SECRET'),
            'OKX_PASSPHRASE': os.getenv('OKX_PASSPHRASE'),
        },
        'Binance MASTER (Optional)': {
            'BINANCE_API_KEY': os.getenv('BINANCE_API_KEY'),
            'BINANCE_API_SECRET': os.getenv('BINANCE_API_SECRET'),
        }
    }
    
    any_configured = False
    master_count = 0
    user_count = 0
    
    for broker, creds in credentials.items():
        print(f"\n{broker}:")
        all_set = True
        for key, val in creds.items():
            if val and len(val) > 5:
                print(f"  ✅ {key}: Set ({len(val)} chars)")
            else:
                print(f"  ❌ {key}: Not set")
                all_set = False
        
        if all_set:
            if '(Optional)' not in broker:
                any_configured = True
                if 'User' in broker:
                    user_count += 1
                else:
                    master_count += 1
            print(f"  ✅ {broker} fully configured")
        elif '(Optional)' not in broker:
            print(f"  ⚠️  {broker} NOT configured (required)")
    
    print("\n" + "="*70)
    print(f"SUMMARY: {master_count} master broker(s) + {user_count} user account(s) configured")
    print("="*70)
    return any_configured

def check_configuration():
    """Check bot configuration"""
    print("\n" + "="*70)
    print("CHECKING CONFIGURATION")
    print("="*70)
    
    multi_broker = os.getenv('MULTI_BROKER_INDEPENDENT', 'true')
    paper_mode = os.getenv('PAPER_MODE', 'false')
    alpaca_paper = os.getenv('ALPACA_PAPER', 'true')
    
    print(f"\n✅ MULTI_BROKER_INDEPENDENT: {multi_broker}")
    print(f"   Independent trading enabled: {multi_broker.lower() in ['true', '1', 'yes']}")
    
    print(f"\n✅ PAPER_MODE: {paper_mode}")
    print(f"   Live trading mode: {paper_mode.lower() not in ['true', '1', 'yes']}")
    
    print(f"\n✅ ALPACA_PAPER: {alpaca_paper}")
    print(f"   Alpaca paper trading: {alpaca_paper.lower() in ['true', '1', 'yes']}")
    
    print("\n" + "="*70)

def check_trading_logic():
    """Check if trading logic is properly configured"""
    print("\n" + "="*70)
    print("CHECKING TRADING LOGIC")
    print("="*70)
    
    # Check if key files exist
    files = [
        'bot.py',
        'bot/trading_strategy.py',
        'bot/independent_broker_trader.py',
        'bot/broker_integration.py',
        'bot/multi_account_broker_manager.py',
    ]
    
    for file in files:
        if os.path.exists(file):
            print(f"✅ {file} exists")
        else:
            print(f"❌ {file} MISSING")
    
    print("\n" + "="*70)

def main():
    print("\n" + "="*70)
    print("NIJA TRADING SETUP VERIFICATION")
    print("="*70)
    
    creds_ok = check_credentials()
    check_configuration()
    check_trading_logic()
    
    print("\n" + "="*70)
    print("FINAL ASSESSMENT")
    print("="*70)
    
    if creds_ok:
        print("\n✅ READY TO TRADE")
        print("\nAt least one broker is fully configured.")
        print("The bot should start trading when launched.")
        print("\nTo start trading:")
        print("  python bot.py")
        print("\nOr using the start script:")
        print("  ./start.sh")
    else:
        print("\n❌ NOT READY TO TRADE")
        print("\nNo brokers are fully configured.")
        print("Please set the required credentials in .env file.")
    
    print("\n" + "="*70)

if __name__ == "__main__":
    main()
