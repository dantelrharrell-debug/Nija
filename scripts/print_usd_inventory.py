#!/usr/bin/env python3
"""
Print USD/USDC account inventory for the current Advanced Trade API key.

- Uses env vars or a local .env (COINBASE_API_KEY / COINBASE_API_SECRET)
- Shows currency, account name, platform, available and held balances
- Summarizes totals for USD and USDC

Run:
  python3 scripts/print_usd_inventory.py

(Optional) Using a .env file in repo root with:
  COINBASE_API_KEY=organizations/.../apiKeys/...
  COINBASE_API_SECRET=...
"""
from __future__ import annotations
import os
from pathlib import Path
from typing import Any

try:
    from coinbase.rest import RESTClient
except Exception as e:
    print(f"❌ coinbase-advanced-py not available: {e}")
    raise SystemExit(1)


def load_env() -> None:
    p = Path('.env')
    if not p.exists():
        return
    try:
        for line in p.read_text().splitlines():
            s = line.strip()
            if not s or s.startswith('#') or '=' not in s:
                continue
            k, v = s.split('=', 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and os.getenv(k) is None:
                os.environ[k] = v
    except Exception as e:
        print(f"⚠️ Failed to parse .env: {e}")


def as_float(v: Any) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0


def main() -> None:
    load_env()

    api_key = os.getenv('COINBASE_API_KEY')
    api_secret = os.getenv('COINBASE_API_SECRET')
    pem_content = os.getenv('COINBASE_PEM_CONTENT')

    if not api_key:
        print('❌ COINBASE_API_KEY missing. Set env or .env.')
        raise SystemExit(1)

    auth = 'jwt' if api_secret else ('pem' if pem_content else None)
    if not auth:
        print('❌ Missing secret. Set COINBASE_API_SECRET (JWT) or COINBASE_PEM_CONTENT (PEM).')
        raise SystemExit(1)

    client_kwargs = {'api_key': api_key}
    client_kwargs['api_secret'] = api_secret if auth == 'jwt' else pem_content
    client = RESTClient(**client_kwargs)

    print('=' * 70)
    print('USD/USDC ACCOUNT INVENTORY')
    print('=' * 70)

    try:
        resp = client.get_accounts()
        accounts = getattr(resp, 'accounts', []) or (resp.get('accounts', []) if isinstance(resp, dict) else [])
        usd_total = 0.0
        usdc_total = 0.0
        found = False
        for a in accounts:
            # typed or dict handling
            currency = getattr(a, 'currency', None) if not isinstance(a, dict) else a.get('currency')
            name = getattr(a, 'name', None) if not isinstance(a, dict) else a.get('name')
            platform = getattr(a, 'platform', None) if not isinstance(a, dict) else a.get('platform')
            av = getattr(getattr(a, 'available_balance', None), 'value', None) if not isinstance(a, dict) else (a.get('available_balance') or {}).get('value')
            hd = getattr(getattr(a, 'hold', None), 'value', None) if not isinstance(a, dict) else (a.get('hold') or {}).get('value')
            avf = as_float(av)
            hdf = as_float(hd)

            if currency in ('USD', 'USDC'):
                found = True
                print(f"{currency:>4} | name={name} | platform={platform} | avail={avf:>10.2f} | held={hdf:>10.2f}")
                if currency == 'USD':
                    usd_total += avf
                else:
                    usdc_total += avf

        if not found:
            print('⚠️ No USD/USDC accounts found for this API key via Advanced Trade.')
        print('-' * 70)
        print(f"Totals → USD: ${usd_total:.2f} | USDC: ${usdc_total:.2f} | Trading Balance: ${usdc_total if usdc_total > 0 else usd_total:.2f}")
        if usd_total == 0.0 and usdc_total == 0.0:
            print('\n👉 Move funds into your Advanced Trade portfolio: https://www.coinbase.com/advanced-portfolio')
    except Exception as e:
        print(f"❌ Error fetching accounts: {e}")


if __name__ == '__main__':
    main()
