#!/usr/bin/env python3
"""Auto-liquidate crypto without confirmation"""
import os
import sys
import time
import uuid

sys.path.insert(0, '/usr/src/app/bot')
from coinbase.rest import RESTClient

# Load .env manually
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

api_key = os.getenv("COINBASE_API_KEY")
api_secret = os.getenv("COINBASE_API_SECRET", "").replace("\\n", "\n")

if not api_key or not api_secret:
    print("❌ Missing credentials")
    sys.exit(1)

print("="*70)
print("🔄 AUTO LIQUIDATION")
print("="*70)

client = RESTClient(api_key=api_key, api_secret=api_secret)

# Get portfolio
portfolios_resp = client.get_portfolios()
portfolios = getattr(portfolios_resp, 'portfolios', [])
default = None
for p in portfolios:
    if p.name == 'Default':
        default = p
        break

if not default:
    print("❌ No Default portfolio")
    sys.exit(1)

# Get breakdown
breakdown_resp = client.get_portfolio_breakdown(portfolio_uuid=default.uuid)
breakdown = getattr(breakdown_resp, 'breakdown', None)
spot_positions = getattr(breakdown, 'spot_positions', [])

# Find crypto to sell
crypto_to_sell = []
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

if not crypto_to_sell:
    print("✅ No crypto to sell")
    sys.exit(0)

print(f"\nSelling {len(crypto_to_sell)} crypto positions:\n")

successful = 0
failed = 0

for crypto in crypto_to_sell:
    asset = crypto['asset']
    quantity = crypto['quantity']
    symbol = f"{asset}-USD"
    
    # Round to appropriate decimal places based on asset
    if asset in ['BTC', 'ETH']:
        rounded_qty = round(quantity, 6)  # 6 decimals for BTC/ETH
    elif asset in ['ATOM', 'LINK', 'DOT']:
        rounded_qty = round(quantity, 2)  # 2 decimals for other crypto
    else:
        rounded_qty = round(quantity, 4)  # 4 decimals default
    
    print(f"📤 Selling {rounded_qty:.8f} {asset}... ", end='', flush=True)
    
    try:
        client_order_id = str(uuid.uuid4())
        order = client.market_order_sell(
            client_order_id,
            product_id=symbol,
            base_size=str(rounded_qty)
        )
        
        # Safely serialize Coinbase SDK response objects
        if isinstance(order, dict):
            order_dict = order
        else:
            # Convert object to dict safely
            try:
                import json
                json_str = json.dumps(order, default=str)
                order_dict = json.loads(json_str)
            except Exception:
                # Fallback: just try __dict__
                order_dict = {}
                if hasattr(order, '__dict__'):
                    for k, v in order.__dict__.items():
                        if isinstance(v, (dict, list, str, int, float, bool, type(None))):
                            order_dict[k] = v
                        else:
                            order_dict[k] = str(v)
        
        if order_dict.get('success', False):
            print(f"✅ ${crypto['value_usd']:.2f}")
            successful += 1
        else:
            error_msg = order_dict.get('error_response', {}).get('message', 'Unknown')
            print(f"❌ {error_msg}")
            failed += 1
        
        time.sleep(0.5)
        
    except Exception as e:
        print(f"❌ {str(e)}")
        failed += 1

print("\n" + "="*70)
print(f"✅ Sold: {successful} | ❌ Failed: {failed}")
print("="*70)
print("\n💡 Run: python3 quick_status.py to see updated balance")
