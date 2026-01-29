#!/usr/bin/env python3
"""
NIJA P&L Monitor - Real-time profit tracking
"""
import os
import sys
import time
from pathlib import Path
from datetime import datetime
from coinbase.rest import RESTClient

# Load environment variables
def load_env():
    env_path = Path(__file__).parent.parent / '.env'
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    value = value.strip('"').strip("'")
                    os.environ[key] = value

def get_total_portfolio_value(client):
    """Calculate total portfolio value in USD"""
    total_usd = 0.0
    positions = []

    try:
        accounts = client.get_accounts()

        # Handle both dict and object responses from Coinbase SDK
        accounts_list = accounts.get('accounts') if isinstance(accounts, dict) else getattr(accounts, 'accounts', [])

        for account in accounts_list:
            # Handle both dict and object account formats
            if isinstance(account, dict):
                currency = account.get('currency')
                balance = float(account.get('available_balance', {}).get('value', 0)) if account.get('available_balance') else 0
            else:
                # Account object from Coinbase SDK
                currency = getattr(account, 'currency', None)
                balance_obj = getattr(account, 'available_balance', {})
                balance = float(balance_obj.get('value', 0)) if isinstance(balance_obj, dict) else float(getattr(balance_obj, 'value', 0)) if balance_obj else 0

            if balance > 0:
                if currency in ['USD', 'USDC', 'USDT']:
                    # Already in USD
                    total_usd += balance
                    if balance > 0.01:
                        positions.append({
                            'currency': currency,
                            'balance': balance,
                            'value_usd': balance
                        })
                else:
                    # Get current market price for crypto
                    try:
                        product_id = f"{currency}-USD"
                        product = client.get_product(product_id)
                        price = float(product.get('price', 0))

                        if price > 0:
                            value_usd = balance * price
                            total_usd += value_usd

                            if value_usd > 0.01:
                                positions.append({
                                    'currency': currency,
                                    'balance': balance,
                                    'price': price,
                                    'value_usd': value_usd
                                })
                    except:
                        pass

        return total_usd, positions

    except Exception as e:
        print(f"Error fetching portfolio: {e}")
        return 0.0, []

def display_pnl(client, starting_balance=None):
    """Display current P&L summary"""
    print("\n" + "="*70)
    print(f"💰 NIJA P&L MONITOR - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)

    total_value, positions = get_total_portfolio_value(client)

    if total_value > 0:
        print(f"\n📊 TOTAL PORTFOLIO VALUE: ${total_value:,.2f}")

        if starting_balance:
            profit = total_value - starting_balance
            profit_pct = (profit / starting_balance) * 100

            print(f"🎯 Starting Balance: ${starting_balance:,.2f}")
            print(f"{'📈' if profit >= 0 else '📉'} P&L: ${profit:+,.2f} ({profit_pct:+.2f}%)")

        print(f"\n💼 POSITIONS ({len(positions)}):")
        print("-" * 70)
        print(f"{'ASSET':<10} {'BALANCE':>15} {'PRICE':>12} {'VALUE (USD)':>15}")
        print("-" * 70)

        for pos in sorted(positions, key=lambda x: x['value_usd'], reverse=True):
            currency = pos['currency']
            balance = pos['balance']
            value = pos['value_usd']

            if 'price' in pos:
                price = pos['price']
                print(f"{currency:<10} {balance:>15.8f} ${price:>11.2f} ${value:>14.2f}")
            else:
                # Stablecoins (no price needed)
                print(f"{currency:<10} {balance:>15.2f} {'—':>12} ${value:>14.2f}")

        print("-" * 70)
        print(f"{'TOTAL':<10} {'':<15} {'':<12} ${total_value:>14.2f}")
        print("="*70)
    else:
        print("⚠️ No portfolio data available")

def monitor_continuous(client, refresh_seconds=60):
    """Continuous monitoring mode"""
    print("\n🔄 Starting continuous P&L monitoring...")
    print(f"   Refresh interval: {refresh_seconds} seconds")
    print("   Press Ctrl+C to stop\n")

    # Get initial balance as baseline
    starting_balance, _ = get_total_portfolio_value(client)

    try:
        while True:
            display_pnl(client, starting_balance)
            print(f"\n⏰ Next update in {refresh_seconds} seconds...")
            time.sleep(refresh_seconds)
    except KeyboardInterrupt:
        print("\n\n🛑 Monitoring stopped")

def main():
    # Load environment
    load_env()

    api_key = os.environ.get("COINBASE_API_KEY")
    api_secret = os.environ.get("COINBASE_API_SECRET")

    # Handle PEM formatting
    if api_secret and "\\n" in api_secret:
        api_secret = api_secret.replace("\\n", "\n")
    if api_secret and not api_secret.endswith("\n"):
        api_secret = api_secret.rstrip() + "\n"

    try:
        # Connect to Coinbase
        print("🔌 Connecting to Coinbase...")
        client = RESTClient(api_key=api_key, api_secret=api_secret)

        # Test connection
        client.get_accounts()
        print("✅ Connected successfully\n")

        # Check if continuous mode requested
        if len(sys.argv) > 1 and sys.argv[1] == '--continuous':
            refresh = int(sys.argv[2]) if len(sys.argv) > 2 else 60
            monitor_continuous(client, refresh)
        else:
            # Single snapshot
            display_pnl(client)
            print("\n💡 Tip: Use '--continuous 60' for live monitoring")

    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
