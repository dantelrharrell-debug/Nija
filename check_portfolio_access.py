#!/usr/bin/env python3
"""
Portfolio access diagnostic (no hardcoded credentials)

Usage examples:
  • Use default env creds: COINBASE_API_KEY / COINBASE_API_SECRET
      $ ./check_portfolio_access.py
  • Test a specific portfolio UUID (optional):
      $ ./check_portfolio_access.py 050cfcb3-....

Notes:
  - Reads creds from environment (or .env if present).
  - Never prints full secrets; previews only.
  - Intended for local diagnostics only.
"""
import os
import sys
from pathlib import Path
import tempfile
import base64
from coinbase.rest import RESTClient


def load_env_from_dotenv() -> None:
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


def preview(val: str, n: int = 10) -> str:
    if not val:
        return '<empty>'
    return f"{val[:n]}… (len={len(val)})"


def main():
    # Load optional .env
    load_env_from_dotenv()

    api_key = os.getenv('COINBASE_API_KEY')
    api_secret = os.getenv('COINBASE_API_SECRET')
    pem_content = os.getenv('COINBASE_PEM_CONTENT')
    pem_b64 = os.getenv('COINBASE_PEM_CONTENT_BASE64') or os.getenv('COINBASE_PEM_BASE64')
    pem_path = os.getenv('COINBASE_PEM_PATH')

    if not api_key:
        print("❌ COINBASE_API_KEY missing. Set env or .env.")
        sys.exit(1)

    # Normalize PEM/JWT secrets (handle escaped newlines)
    if api_secret and "\\n" in api_secret:
        api_secret = api_secret.replace("\\n", "\n")
    if api_secret and not api_secret.endswith("\n"):
        api_secret = api_secret.rstrip() + "\n"
    if pem_content and "\\n" in pem_content:
        pem_content = pem_content.replace("\\n", "\n")
    if pem_content and not pem_content.endswith("\n"):
        pem_content = pem_content.rstrip() + "\n"

    # Prefer JWT; allow PEM fallback if no api_secret provided
    # Determine auth method
    auth = 'jwt' if api_secret else ('pem' if (pem_content or pem_b64 or pem_path) else None)
    if not auth:
        print("❌ Missing secret. Set COINBASE_API_SECRET (JWT) or COINBASE_PEM_CONTENT (PEM).")
        sys.exit(1)

    print("=" * 70)
    print("PORTFOLIO ACCESS TEST")
    print("=" * 70)
    print(f"Auth: {auth} | key={preview(api_key, 16)} | secret={preview(api_secret or pem_content, 16)}")
    print()

    # Build REST client for JWT or PEM
    if auth == 'jwt':
        client = RESTClient(api_key=api_key, api_secret=api_secret)
    else:
        key_file_arg = None
        if pem_path and Path(pem_path).is_file():
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

    # 1) List portfolios
    print("1) Listing accessible portfolios…")
    print("-" * 70)
    try:
        resp = client.get_portfolios()
        portfolios = getattr(resp, 'portfolios', []) or []
        print(f"✅ Found {len(portfolios)} portfolio(s)\n")
        for i, p in enumerate(portfolios, 1):
            uuid = getattr(p, 'uuid', 'N/A')
            name = getattr(p, 'name', 'N/A')
            ptype = getattr(p, 'type', 'N/A')
            print(f"Portfolio #{i}:")
            print(f"  UUID: {uuid}")
            print(f"  Name: {name}")
            print(f"  Type: {ptype}")
            # Summarize USD/USDC if possible via breakdown
            try:
                br = client.get_portfolio_breakdown(portfolio_uuid=uuid)
                bd = getattr(br, 'breakdown', None)
                usd = usdc = 0.0
                if bd:
                    for pos in getattr(bd, 'spot_positions', []) or []:
                        asset = getattr(pos, 'asset', '')
                        fiat_val = float(getattr(pos, 'total_balance_fiat', 0) or 0)
                        if asset == 'USD':
                            usd += fiat_val
                        elif asset == 'USDC':
                            usdc += fiat_val
                print(f"  USD: ${usd:.2f} | USDC: ${usdc:.2f}")
            except Exception as be:
                print(f"  ⚠️ Breakdown unavailable: {str(be)[:160]}")
            print()
    except Exception as e:
        print(f"❌ Failed to fetch portfolios: {e}")
        print()

    # 2) Optional: test a specific portfolio UUID passed as argv[1]
    if len(sys.argv) > 1:
        test_uuid = sys.argv[1]
        print("=" * 70)
        print(f"2) Testing portfolio access: {test_uuid}")
        print("=" * 70)
        try:
            resp = client.get_portfolio_breakdown(portfolio_uuid=test_uuid)
            bd = getattr(resp, 'breakdown', None)
            positions = getattr(bd, 'spot_positions', []) if bd else []
            print(f"✅ SUCCESS. Positions: {len(positions)}")
            total = 0.0
            for pos in positions:
                asset = getattr(pos, 'asset', 'N/A')
                fiat = float(getattr(pos, 'total_balance_fiat', 0) or 0)
                avail = float(getattr(pos, 'available_to_trade_fiat', 0) or 0)
                total += fiat
                if fiat > 0:
                    print(f"  {asset}: ${fiat:.2f} (available: ${avail:.2f})")
            print(f"Total Value: ${total:.2f}")
        except Exception as e:
            print(f"❌ FAILED to access portfolio: {str(e)[:200]}")


if __name__ == '__main__':
    main()
