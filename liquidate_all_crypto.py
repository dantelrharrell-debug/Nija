#!/usr/bin/env python3
"""
Emergency liquidation: Sell all crypto holdings to free up capital for trading
"""
import os
import sys
sys.path.insert(0, '/usr/src/app/bot')

from coinbase.rest import RESTClient
import time

# Load .env file manually if dotenv not available
def load_env():
    env_path = '/workspaces/Nija/.env'
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip().strip('"').strip("'")

load_env()

# Load credentials
api_key = os.getenv("COINBASE_API_KEY")
api_secret = os.getenv("COINBASE_API_SECRET", "").replace("\\n", "\n")

if not api_key or not api_secret:
    print("❌ Missing API credentials")
    sys.exit(1)

print("=" * 80)
print("🔄 EMERGENCY LIQUIDATION - SELL ALL CRYPTO")
print("=" * 80)

client = RESTClient(api_key=api_key, api_secret=api_secret)

# Get current balance
print("\n📊 Fetching current portfolio...")
portfolios_resp = client.get_portfolios()
portfolios = getattr(portfolios_resp, 'portfolios', [])

default_portfolio = None
for p in portfolios:
    if p.name == 'Default':
        default_portfolio = p
        break

if not default_portfolio:
    print("❌ Could not find Default portfolio")
    sys.exit(1)

breakdown_resp = client.get_portfolio_breakdown(portfolio_uuid=default_portfolio.uuid)
breakdown = getattr(breakdown_resp, 'breakdown', None)

if not breakdown:
    print("❌ No breakdown data")
    sys.exit(1)

spot_positions = getattr(breakdown, 'spot_positions', [])

# Find crypto positions to sell
crypto_to_sell = []
total_usd_value = 0

print("\n💰 CURRENT HOLDINGS:")
print("-" * 80)

for position in spot_positions:
    asset = getattr(position, 'asset', 'N/A')
    is_cash = getattr(position, 'is_cash', False)
    total_crypto = getattr(position, 'total_balance_crypto', 0)
    total_fiat = getattr(position, 'total_balance_fiat', 0)
    
    if not is_cash and total_crypto > 0:
        crypto_to_sell.append({
            'asset': asset,
            'quantity': total_crypto,
            'value_usd': total_fiat
        })
        total_usd_value += total_fiat
        print(f"   🪙 {asset}: {total_crypto:.8f} (${total_fiat:.2f})")

if not crypto_to_sell:
    print("\n✅ No crypto holdings to sell")
    sys.exit(0)

print("-" * 80)
print(f"   📊 Total crypto value: ${total_usd_value:.2f}")
print()

# Confirm
print(f"⚠️  About to sell {len(crypto_to_sell)} crypto positions")
print(f"   Estimated proceeds: ${total_usd_value:.2f}")
print()
response = input("Continue? (yes/no): ")

if response.lower() != 'yes':
    print("❌ Canceled")
    sys.exit(0)

print("\n🔄 EXECUTING SALES...")
print("=" * 80)

successful_sales = 0
failed_sales = 0
total_proceeds = 0

for crypto in crypto_to_sell:
    asset = crypto['asset']
    quantity = crypto['quantity']
    symbol = f"{asset}-USD"
    
    print(f"\n📤 Selling {asset}...")
    print(f"   Quantity: {quantity:.8f}")
    print(f"   Pair: {symbol}")
    
    try:
        import uuid
        client_order_id = str(uuid.uuid4())
        
        # Place market sell order
        order = client.market_order_sell(
            client_order_id,
            product_id=symbol,
            base_size=str(round(quantity, 8))
        )
        
        # Check result
        order_dict = order if isinstance(order, dict) else (
            order.__dict__ if hasattr(order, '__dict__') else {}
        )
        
        success = order_dict.get('success', False)
        
        if success:
            print(f"   ✅ {asset} sold successfully")
            successful_sales += 1
            total_proceeds += crypto['value_usd']
        else:
            error_response = order_dict.get('error_response', {})
            error_msg = error_response.get('message', 'Unknown error')
            print(f"   ❌ Failed to sell {asset}: {error_msg}")
            failed_sales += 1
        
        # Rate limiting - wait between orders
        time.sleep(0.5)
        
    except Exception as e:
        print(f"   ❌ Error selling {asset}: {e}")
        failed_sales += 1

print("\n" + "=" * 80)
print("📊 LIQUIDATION SUMMARY")
print("=" * 80)
print(f"   ✅ Successful sales: {successful_sales}")
print(f"   ❌ Failed sales: {failed_sales}")
print(f"   💰 Estimated proceeds: ${total_proceeds:.2f}")
print()
print("🔄 Wait 5-10 seconds, then check your balance with:")
print("   python3 check_balance_now.py")
print("=" * 80)
