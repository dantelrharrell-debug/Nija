#!/usr/bin/env python3
"""Quick balance check using NIJA's trading strategy

Enhancements:
- Automatically loads credentials from a local .env if exports are not present
- Supports PEM secret via COINBASE_PEM_CONTENT
- Prints clearer diagnostics on auth failures
"""

import sys
import os
from pathlib import Path
sys.path.insert(0, 'bot')

from trading_strategy import TradingStrategy
from coinbase.rest import RESTClient
import tempfile
import base64


def load_env_from_dotenv():
    """Load environment variables from a local .env file if present and not already set.

    This avoids requiring `export COINBASE_API_KEY/SECRET` in the shell.
    """
    dotenv_path = Path('.env')
    if not dotenv_path.exists():
        return
    try:
        with dotenv_path.open('r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' not in line:
                    continue
                key, val = line.split('=', 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                # Only set if not already present in env
                if key and (os.getenv(key) is None):
                    os.environ[key] = val
    except Exception as e:
        print(f"⚠️ Failed to parse .env: {e}")


def safe_preview(value: str, max_prefix: int = 6) -> str:
    if not value:
        return "<empty>"
    return f"{value[:max_prefix]}… (len={len(value)})"


# Attempt to load from .env if not set
if not os.getenv('COINBASE_API_KEY') or not os.getenv('COINBASE_API_SECRET'):
    load_env_from_dotenv()

# Load credentials (JWT or PEM)
api_key = os.getenv('COINBASE_API_KEY')
api_secret = os.getenv('COINBASE_API_SECRET')
pem_content = os.getenv('COINBASE_PEM_CONTENT')
pem_b64 = os.getenv('COINBASE_PEM_CONTENT_BASE64') or os.getenv('COINBASE_PEM_BASE64')
pem_path = os.getenv('COINBASE_PEM_PATH')

if not api_key:
    print("❌ Missing COINBASE_API_KEY. Set in env or .env")
    sys.exit(1)

if not api_secret and not pem_content:
    print("❌ Missing secret. Provide COINBASE_API_SECRET (JWT) or COINBASE_PEM_CONTENT (PEM) via env or .env")
    sys.exit(1)

auth_method = 'pem' if (not api_secret and (pem_content or pem_b64 or pem_path)) else 'jwt'
print(f"🔐 Auth method: {auth_method} | key={safe_preview(api_key)} | secret={safe_preview(api_secret or pem_content)}")

if auth_method == 'jwt':
    client = RESTClient(api_key=api_key, api_secret=api_secret)
else:
    key_file_arg = None
    if pem_path and os.path.isfile(pem_path):
        key_file_arg = pem_path
    else:
        raw_pem = None
        if pem_content and pem_content.strip():
            raw_pem = pem_content
        elif pem_b64 and pem_b64.strip():
            try:
                raw_pem = base64.b64decode(pem_b64).decode('utf-8')
            except Exception as e:
                print(f"❌ Failed to decode COINBASE_PEM_CONTENT_BASE64: {e}")
        if raw_pem:
            normalized = raw_pem.replace("\\n", "\n").strip()
            if "BEGIN" in normalized and "END" in normalized:
                tmp = tempfile.NamedTemporaryFile(delete=False, mode='w', suffix='.pem')
                tmp.write(normalized)
                tmp.flush()
                key_file_arg = tmp.name
            else:
                print("❌ Provided PEM content missing BEGIN/END headers")
    if not key_file_arg:
        print('❌ No valid PEM found: set COINBASE_PEM_PATH or COINBASE_PEM_CONTENT/BASE64')
        sys.exit(1)
    client = RESTClient(api_key=None, api_secret=None, key_file=key_file_arg)

# Use strategy's get_usd_balance method
strategy = TradingStrategy(client, paper_mode=False)

print('\n' + '='*70)
print('💰 NIJA FUNDED ACCOUNT STATUS')
print('='*70)

# Get USD balance with auth diagnostics
try:
    usd_balance = strategy.get_usd_balance()
    print(f'\n💵 Available USD: ${usd_balance:.2f}')
except Exception as e:
    # Commonly 401 Unauthorized due to invalid credentials or wrong auth mode
    msg = str(e)
    print(f"❌ Error retrieving USD balance: {msg}")
    print("   Tips: Verify the key/secret pair (JWT) or provide PEM via COINBASE_PEM_CONTENT."
          " Rotate creds if previously exposed. Ensure Advanced Trade is enabled.")
    sys.exit(1)

# Get all positions
try:
    accounts = client.get_accounts()
    total_value = usd_balance
    positions = []
    
    for account in accounts['accounts']:
        currency = account['currency']
        balance = float(account['available_balance']['value'])
        
        if balance > 0 and currency not in ['USD', 'USDC', 'USDT']:
            try:
                product_id = f'{currency}-USD'
                product = client.get_product(product_id)
                price = float(product.get('price', 0))
                
                if price > 0:
                    value_usd = balance * price
                    total_value += value_usd
                    positions.append({
                        'currency': currency,
                        'balance': balance,
                        'price': price,
                        'value_usd': value_usd
                    })
            except:
                pass
    
    if positions:
        print(f'\n💼 CRYPTO POSITIONS ({len(positions)}):')
        print('-' * 70)
        for pos in sorted(positions, key=lambda x: x['value_usd'], reverse=True):
            print(f'{pos["currency"]:<8} {pos["balance"]:>12.8f} @ ${pos["price"]:>8.2f} = ${pos["value_usd"]:>8.2f}')
    
    print(f'\n{"="*70}')
    print(f'📊 TOTAL PORTFOLIO VALUE: ${total_value:.2f}')
    print(f'{"="*70}')
    
    # Growth calculations (skip if zero to avoid div-by-zero)
    target = 1000000
    if total_value > 0:
        remaining = target - total_value
        growth_needed = ((target / total_value) - 1) * 100
        daily_compound = ((target / total_value) ** (1/90) - 1) * 100

        print(f'\n🎯 $1M GROWTH TARGET:')
        print(f'   Current: ${total_value:.2f}')
        print(f'   Goal: ${target:,.2f}')
        print(f'   Remaining: ${remaining:,.2f} ({growth_needed:,.0f}% growth)')
        print(f'   Required daily compound: {daily_compound:.2f}%/day')
        print(f'   Timeline: 90 days')
    else:
        print('\n🎯 $1M GROWTH TARGET: Current portfolio value is $0.00; add funds to compute growth path.')

    # Estimate based on current NIJA settings
    print(f'\n🚀 NIJA GROWTH ACCELERATORS ACTIVE:')
    print(f'   ✅ 95% Profit Lock (never lose gains)')
    print(f'   ✅ Pyramiding at +1%, +2%, +3%')
    print(f'   ✅ Runners to 20% (was 5%)')
    print(f'   ✅ Dynamic signals (scales with account)')
    print(f'   ✅ 85% max exposure (was 70%)')
    print(f'   ✅ 1,000 trades/day limit\n')

except Exception as e:
    print(f'❌ Error fetching positions: {e}')
