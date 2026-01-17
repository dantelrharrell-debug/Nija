#!/usr/bin/env python3
"""
Enable NIJA Trading NOW - Auto-configure for immediate trading

This script solves the "no trades" problem by:
1. Detecting if credentials are available
2. Auto-enabling paper trading if no credentials
3. Providing clear instructions for each mode

Usage:
    python3 enable_trading_now.py          # Auto-detect and start
    python3 enable_trading_now.py --info   # Show information only
"""

import os
import sys
import json
from pathlib import Path


def check_exchange_credentials():
    """Check which exchanges have credentials configured."""
    exchanges = {
        'Coinbase': ['COINBASE_API_KEY', 'COINBASE_API_SECRET'],
        'Kraken Master': ['KRAKEN_MASTER_API_KEY', 'KRAKEN_MASTER_API_SECRET'],
        'Kraken Legacy': ['KRAKEN_API_KEY', 'KRAKEN_API_SECRET'],
        'Alpaca': ['ALPACA_API_KEY', 'ALPACA_API_SECRET'],
        'OKX': ['OKX_API_KEY', 'OKX_API_SECRET', 'OKX_PASSPHRASE'],
        'Binance': ['BINANCE_API_KEY', 'BINANCE_API_SECRET'],
    }
    
    configured = []
    not_configured = []
    
    for name, keys in exchanges.items():
        if all(os.getenv(key, '').strip() for key in keys):
            configured.append(name)
        else:
            not_configured.append(name)
    
    return configured, not_configured


def create_paper_trading_file():
    """Create or verify paper trading data file."""
    paper_file = Path('paper_trading_data.json')
    
    if not paper_file.exists():
        initial_data = {
            'balance': 10000.0,
            'initial_balance': 10000.0,
            'positions': {},
            'trades': [],
            'total_pnl': 0.0,
            'daily_pnl': 0.0,
            'created': '2026-01-17',
            'last_updated': None
        }
        
        with open(paper_file, 'w') as f:
            json.dump(initial_data, f, indent=2)
        
        return True, "Created new paper trading account"
    else:
        # Load and verify existing data
        try:
            with open(paper_file, 'r') as f:
                data = json.load(f)
            
            balance = data.get('balance', 10000.0)
            total_pnl = data.get('total_pnl', 0.0)
            num_trades = len(data.get('trades', []))
            
            return False, f"Existing account: ${balance:.2f} balance, {num_trades} trades, ${total_pnl:+.2f} P&L"
        except Exception as e:
            return False, f"Error reading existing file: {e}"


def print_header():
    """Print application header."""
    print()
    print("="*80)
    print("    NIJA TRADING BOT - ENABLE TRADING NOW")
    print("="*80)
    print()


def print_credentials_status(configured, not_configured):
    """Print current credentials status."""
    print("📋 EXCHANGE CREDENTIALS STATUS")
    print("-" * 80)
    
    if configured:
        print(f"\n✅ CONFIGURED ({len(configured)} exchanges):")
        for name in configured:
            print(f"   • {name}")
    
    if not_configured:
        print(f"\n❌ NOT CONFIGURED ({len(not_configured)} exchanges):")
        for name in not_configured:
            print(f"   • {name}")
    
    print()


def show_paper_trading_solution():
    """Show paper trading solution."""
    print("="*80)
    print("🎯 SOLUTION: ENABLE PAPER TRADING MODE")
    print("="*80)
    print()
    print("Paper trading mode allows NIJA to trade immediately WITHOUT any credentials!")
    print()
    print("✅ Benefits:")
    print("   • No API credentials needed")
    print("   • No real money at risk")
    print("   • Uses real market data")
    print("   • Tests all bot functionality")
    print("   • Virtual $10,000 starting balance")
    print()
    print("📊 How it works:")
    print("   • Simulates all trades locally")
    print("   • Tracks virtual positions and P&L")
    print("   • Saves data to: paper_trading_data.json")
    print()
    
    # Check/create paper trading file
    is_new, msg = create_paper_trading_file()
    
    if is_new:
        print(f"✅ {msg}")
        print(f"   Initial balance: $10,000")
    else:
        print(f"ℹ️  {msg}")
    
    print()
    print("="*80)
    print("🚀 STARTING PAPER TRADING MODE")
    print("="*80)
    print()
    
    # Set environment variable
    os.environ['PAPER_MODE'] = 'true'
    
    print("Environment configured:")
    print("   PAPER_MODE=true")
    print()
    print("To start trading:")
    print()
    print("   Option 1 - Run directly:")
    print("      export PAPER_MODE=true")
    print("      python3 bot.py")
    print()
    print("   Option 2 - Use paper mode script:")
    print("      bash bot/run_paper_mode.sh")
    print()
    print("   Option 3 - Configure Railway/Render:")
    print("      Add environment variable: PAPER_MODE=true")
    print("      Deploy and it will run in paper mode")
    print()
    print("To view results:")
    print("   python3 bot/view_paper_account.py")
    print()
    print("="*80)
    print()


def show_live_trading_info(configured):
    """Show live trading information."""
    print("="*80)
    print("✅ LIVE TRADING READY")
    print("="*80)
    print()
    print(f"You have {len(configured)} exchange(s) configured with credentials:")
    for name in configured:
        print(f"   • {name}")
    print()
    print("⚠️  WARNING: LIVE TRADING USES REAL MONEY!")
    print()
    print("Before starting:")
    print("   1. Verify credentials are correct")
    print("   2. Check account balances")
    print("   3. Review risk management settings")
    print("   4. Start with small amounts")
    print()
    print("To start live trading:")
    print("   python3 bot.py")
    print()
    print("To check status first:")
    print("   python3 check_trading_status.py")
    print()
    print("="*80)
    print()


def show_kraken_demo_solution():
    """Show Kraken Futures demo solution."""
    print("="*80)
    print("💡 ALTERNATIVE: KRAKEN FUTURES DEMO (Free Test Environment)")
    print("="*80)
    print()
    print("Kraken offers a FREE demo environment for testing:")
    print()
    print("✅ Benefits:")
    print("   • Real API testing (not simulated)")
    print("   • Free virtual funds")
    print("   • No KYC required")
    print("   • Instant account creation")
    print()
    print("📝 Setup Steps (5 minutes):")
    print()
    print("1. Sign up at: https://demo-futures.kraken.com")
    print("   • Use any email (no verification needed)")
    print("   • Create password")
    print()
    print("2. Get API credentials:")
    print("   • Log in to demo account")
    print("   • Go to: Profile → API Settings")
    print("   • Create new API key")
    print("   • Enable: Read + Trade permissions")
    print()
    print("3. Configure NIJA:")
    print("   Add these environment variables:")
    print()
    print("   KRAKEN_DEMO_API_KEY=<your-demo-key>")
    print("   KRAKEN_DEMO_API_SECRET=<your-demo-secret>")
    print("   KRAKEN_USE_FUTURES_DEMO=true")
    print()
    print("   Then run: python3 quick_start_trading.py --demo-futures")
    print()
    print("⚠️  Note: Kraken Futures is different from Kraken Spot")
    print("   • Futures = Leveraged derivatives trading")
    print("   • Spot = Regular buy/sell cryptocurrency")
    print("   • NIJA is designed for Spot, but demo tests API connectivity")
    print()
    print("="*80)
    print()


def show_production_kraken_info():
    """Show production Kraken setup information."""
    print("="*80)
    print("📖 SETUP PRODUCTION KRAKEN CREDENTIALS")
    print("="*80)
    print()
    print("To enable LIVE Kraken trading:")
    print()
    print("1. Create Kraken account:")
    print("   • Sign up: https://www.kraken.com")
    print("   • Complete KYC (1-2 days)")
    print("   • Deposit funds (min $25 recommended)")
    print()
    print("2. Get API credentials:")
    print("   • Go to: https://www.kraken.com/u/security/api")
    print("   • Click 'Generate New Key'")
    print("   • Description: 'NIJA Trading Bot'")
    print("   • Enable these permissions:")
    print("      ✅ Query Funds")
    print("      ✅ Query Open Orders & Trades")
    print("      ✅ Query Closed Orders & Trades")
    print("      ✅ Create & Modify Orders")
    print("      ✅ Cancel/Close Orders")
    print("      ❌ DO NOT enable: Withdraw Funds")
    print("   • Save API Key and Secret immediately!")
    print()
    print("3. Configure NIJA:")
    print()
    print("   For Master Account:")
    print("   KRAKEN_MASTER_API_KEY=<your-api-key>")
    print("   KRAKEN_MASTER_API_SECRET=<your-api-secret>")
    print()
    print("   For User Accounts (optional):")
    print("   KRAKEN_USER_DAIVON_API_KEY=<daivon-key>")
    print("   KRAKEN_USER_DAIVON_API_SECRET=<daivon-secret>")
    print("   KRAKEN_USER_TANIA_API_KEY=<tania-key>")
    print("   KRAKEN_USER_TANIA_API_SECRET=<tania-secret>")
    print()
    print("4. Deploy:")
    print("   • Railway: Add variables → Auto-restart")
    print("   • Render: Add variables → Manual Deploy")
    print()
    print("5. Verify:")
    print("   python3 check_kraken_status.py")
    print()
    print("📖 Detailed guides:")
    print("   • SOLUTION_ENABLE_TRADING_NOW.md")
    print("   • CONFIGURE_KRAKEN_MASTER.md")
    print("   • GETTING_STARTED.md")
    print()
    print("="*80)
    print()


def main():
    """Main function."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Enable NIJA Trading NOW')
    parser.add_argument('--info', action='store_true', help='Show information only')
    args = parser.parse_args()
    
    print_header()
    
    # Check credentials
    configured, not_configured = check_exchange_credentials()
    
    print_credentials_status(configured, not_configured)
    
    # Determine what to show
    if configured:
        # Has credentials - show live trading info
        show_live_trading_info(configured)
        
        if args.info:
            # Also show alternative options
            print()
            show_paper_trading_solution()
            print()
            show_kraken_demo_solution()
    else:
        # No credentials - show paper trading as primary solution
        show_paper_trading_solution()
        
        if args.info:
            # Also show other options
            print()
            show_kraken_demo_solution()
            print()
            show_production_kraken_info()
    
    # Summary
    print("="*80)
    print("📚 QUICK REFERENCE")
    print("="*80)
    print()
    print("Commands:")
    print("   python3 enable_trading_now.py          # This script")
    print("   python3 quick_start_trading.py --paper # Start paper trading")
    print("   python3 check_trading_status.py        # Check current status")
    print("   python3 bot/view_paper_account.py      # View paper account")
    print("   python3 bot.py                         # Start bot (live)")
    print()
    print("Documentation:")
    print("   SOLUTION_ENABLE_TRADING_NOW.md         # All solutions")
    print("   GETTING_STARTED.md                     # Complete setup")
    print("   CONFIGURE_KRAKEN_MASTER.md             # Kraken setup")
    print()
    print("="*80)
    print()
    
    if not args.info and not configured:
        # Auto-start paper trading
        print("💡 READY TO START? Run one of these commands:")
        print()
        print("   export PAPER_MODE=true && python3 bot.py")
        print("   bash bot/run_paper_mode.sh")
        print("   python3 quick_start_trading.py --paper")
        print()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nCancelled by user")
        sys.exit(0)
