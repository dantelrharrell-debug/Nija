#!/usr/bin/env python3
"""
NIJA Quick Start - Auto-configure and start trading immediately

This script automatically detects available credentials and enables
the best trading mode:
1. If credentials available → Live trading
2. If no credentials → Paper trading mode
3. If demo mode requested → Use Kraken Futures demo

Usage:
    python3 quick_start_trading.py                    # Auto-detect mode
    python3 quick_start_trading.py --paper            # Force paper trading
    python3 quick_start_trading.py --demo-futures     # Use Kraken Futures demo
    python3 quick_start_trading.py --check-only       # Check status without starting
"""

import os
import sys
import argparse


def check_credentials():
    """Check which exchange credentials are configured."""
    exchanges = {
        'coinbase': {
            'keys': ['COINBASE_API_KEY', 'COINBASE_API_SECRET'],
            'found': False
        },
        'kraken_master': {
            'keys': ['KRAKEN_MASTER_API_KEY', 'KRAKEN_MASTER_API_SECRET'],
            'found': False
        },
        'kraken_legacy': {
            'keys': ['KRAKEN_API_KEY', 'KRAKEN_API_SECRET'],
            'found': False
        },
        'alpaca': {
            'keys': ['ALPACA_API_KEY', 'ALPACA_API_SECRET'],
            'found': False
        },
        'okx': {
            'keys': ['OKX_API_KEY', 'OKX_API_SECRET', 'OKX_PASSPHRASE'],
            'found': False
        },
        'binance': {
            'keys': ['BINANCE_API_KEY', 'BINANCE_API_SECRET'],
            'found': False
        }
    }
    
    for exchange, config in exchanges.items():
        keys = config['keys']
        if all(os.getenv(key) for key in keys):
            config['found'] = True
    
    return exchanges


def print_status(exchanges):
    """Print current credential status."""
    print("="*70)
    print("    NIJA TRADING BOT - CREDENTIAL STATUS")
    print("="*70)
    print()
    
    any_found = False
    for exchange, config in exchanges.items():
        status = "✅ CONFIGURED" if config['found'] else "❌ NOT SET"
        print(f"  {exchange.upper().replace('_', ' '):<20} {status}")
        if config['found']:
            any_found = True
    
    print()
    print("="*70)
    print()
    
    return any_found


def configure_paper_mode():
    """Configure and enable paper trading mode."""
    print("📄 CONFIGURING PAPER TRADING MODE")
    print("="*70)
    print()
    print("✅ No real money will be used")
    print("✅ Starting with virtual $10,000")
    print("✅ All trades are simulated")
    print("✅ Uses real market data")
    print()
    
    # Set environment variable
    os.environ['PAPER_MODE'] = 'true'
    
    # Create paper trading data file if it doesn't exist
    if not os.path.exists('paper_trading_data.json'):
        import json
        with open('paper_trading_data.json', 'w') as f:
            json.dump({
                'balance': 10000.0,
                'positions': {},
                'trades': [],
                'total_pnl': 0.0
            }, f, indent=2)
        print("✅ Created paper_trading_data.json")
    else:
        print("✅ Using existing paper_trading_data.json")
    
    print()
    print("📊 View results anytime:")
    print("   python3 bot/view_paper_account.py")
    print()
    print("="*70)
    print()
    
    return True


def configure_demo_futures():
    """Configure Kraken Futures demo mode."""
    print("🎯 CONFIGURING KRAKEN FUTURES DEMO MODE")
    print("="*70)
    print()
    
    # Check if demo credentials are set
    demo_key = os.getenv('KRAKEN_DEMO_API_KEY')
    demo_secret = os.getenv('KRAKEN_DEMO_API_SECRET')
    
    if not demo_key or not demo_secret:
        print("⚠️  Kraken Futures demo credentials not found!")
        print()
        print("To use Kraken Futures demo:")
        print("1. Sign up at: https://demo-futures.kraken.com")
        print("2. Get API credentials from demo account")
        print("3. Set environment variables:")
        print("   KRAKEN_DEMO_API_KEY=your-demo-key")
        print("   KRAKEN_DEMO_API_SECRET=your-demo-secret")
        print()
        print("Falling back to paper trading mode...")
        print()
        return configure_paper_mode()
    
    print("✅ Kraken Futures demo credentials found")
    print("✅ Will use demo environment: demo-futures.kraken.com")
    print()
    
    # Map demo credentials to master credentials
    os.environ['KRAKEN_MASTER_API_KEY'] = demo_key
    os.environ['KRAKEN_MASTER_API_SECRET'] = demo_secret
    os.environ['KRAKEN_USE_FUTURES_DEMO'] = 'true'
    
    print("="*70)
    print()
    
    return True


def start_bot():
    """Start the NIJA trading bot."""
    print("🚀 STARTING NIJA TRADING BOT")
    print("="*70)
    print()
    
    # Import and run the bot
    try:
        import bot
        # The bot.py will use environment variables we've set
        os.system('python3 bot.py')
    except KeyboardInterrupt:
        print("\n⏹️  Bot stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error starting bot: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description='NIJA Quick Start - Auto-configure trading mode'
    )
    parser.add_argument(
        '--paper',
        action='store_true',
        help='Force paper trading mode (no real money)'
    )
    parser.add_argument(
        '--demo-futures',
        action='store_true',
        help='Use Kraken Futures demo environment'
    )
    parser.add_argument(
        '--check-only',
        action='store_true',
        help='Only check credentials, don\'t start bot'
    )
    
    args = parser.parse_args()
    
    print()
    print("╔════════════════════════════════════════════════════════════════════╗")
    print("║              NIJA TRADING BOT - QUICK START                       ║")
    print("╚════════════════════════════════════════════════════════════════════╝")
    print()
    
    # Check credentials
    exchanges = check_credentials()
    has_credentials = print_status(exchanges)
    
    if args.check_only:
        print("✅ Check complete (--check-only mode)")
        return 0
    
    # Determine mode
    if args.paper:
        print("📄 Paper trading mode requested (--paper flag)")
        configure_paper_mode()
    elif args.demo_futures:
        print("🎯 Kraken Futures demo mode requested (--demo-futures flag)")
        configure_demo_futures()
    elif not has_credentials:
        print("⚠️  No exchange credentials found")
        print()
        print("Auto-enabling PAPER TRADING MODE for testing...")
        print()
        configure_paper_mode()
    else:
        print("✅ Exchange credentials found")
        print()
        print("🔴 LIVE TRADING MODE ENABLED")
        print("⚠️  REAL MONEY WILL BE USED!")
        print()
        
        # Safety confirmation
        response = input("Continue with live trading? (yes/no): ").strip().lower()
        if response not in ['yes', 'y']:
            print("\n⏹️  Cancelled by user")
            print()
            print("💡 Tip: Use --paper flag for risk-free testing:")
            print("   python3 quick_start_trading.py --paper")
            return 1
        print()
    
    # Start the bot
    start_bot()
    
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n⏹️  Stopped by user")
        sys.exit(0)
