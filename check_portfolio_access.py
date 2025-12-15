#!/usr/bin/env python3
"""
Check which portfolios the current API key can access
"""
from coinbase.rest import RESTClient

# NOTE: For local diagnostics only. Do NOT commit real secrets.
api_key = "organizations/ce77e4ea-ecca-42ec-912a-b6b4455ab9d0/apiKeys/4cfe95c4-23c3-4480-a13c-1259f7320c36"
api_secret = """-----BEGIN EC PRIVATE KEY-----
MHcCAQEEIN8qIYi2YYF+EVw3SjBFI4vGG5s5+GK67PMtJsihiqMboAoGCCqGSM49
AwEHoUQDQgAEyX6F9fdJ6FN8iigO3bOpAgs5rURgmpbPQulXOJhVUIQrBVvdHPz3
KBxA/l4CdmnIbdsK4d+kTK8bNygn794vPA==
-----END EC PRIVATE KEY-----"""

client = RESTClient(api_key=api_key, api_secret=api_secret)

print("=" * 70)
print("PORTFOLIO ACCESS TEST")
print("=" * 70)
print()

print("1. Fetching all portfolios accessible to this API key...")
print("-" * 70)
try:
    resp = client.get_portfolios()
    # Coinbase SDK returns a typed response, not a dict
    portfolios = getattr(resp, "portfolios", []) or []
    print(f"✅ Found {len(portfolios)} portfolio(s)\n")

    for i, p in enumerate(portfolios, 1):
        uuid = getattr(p, "uuid", "N/A")
        name = getattr(p, "name", "N/A")
        ptype = getattr(p, "type", "N/A")
        print(f"Portfolio #{i}:")
        print(f"  UUID: {uuid}")
        print(f"  Name: {name}")
        print(f"  Type: {ptype}")

        # Try to get accounts/breakdown
        try:
            accts_resp = client.get_portfolio_breakdown(portfolio_uuid=uuid)
            breakdown = getattr(accts_resp, "breakdown", None)
            positions = []
            total_value = 0.0
            if breakdown:
                positions = getattr(breakdown, "spot_positions", []) or []
                print(f"  Positions: {len(positions)}")
                for pos in positions:
                    asset = getattr(pos, "asset", "N/A")
                    fiat_value = float(getattr(pos, "total_balance_fiat", 0) or 0)
                    available = float(getattr(pos, "available_to_trade_fiat", 0) or 0)
                    total_value += fiat_value
                    if fiat_value > 0.01:  # Only show non-zero balances
                        print(f"    {asset}: ${fiat_value:.2f} (available: ${available:.2f})")
            else:
                print("  Positions: 0")
            print(f"  Total Value: ${total_value:.2f}")
        except Exception as e:
            print(f"  ❌ Error accessing accounts: {str(e)[:200]}")

        print()

except Exception as e:
    print(f"❌ Failed to fetch portfolios: {e}")
    print()

print()
print("=" * 70)
print("2. Testing DIRECT access to override portfolio:")
print("   050cfcb3-6262-404a-a620-9c4437769db4")
print("=" * 70)
try:
    resp = client.get_portfolio_breakdown(portfolio_uuid="050cfcb3-6262-404a-a620-9c4437769db4")
    breakdown = getattr(resp, "breakdown", None)
    positions = getattr(breakdown, "spot_positions", []) if breakdown else []

    print(f"✅ SUCCESS! Can access this portfolio")
    print(f"Found {len(positions)} positions:")

    total_value = 0.0
    for pos in positions:
        asset = getattr(pos, "asset", "N/A")
        fiat_value = float(getattr(pos, "total_balance_fiat", 0) or 0)
        available = float(getattr(pos, "available_to_trade_fiat", 0) or 0)
        total_value += fiat_value
        print(f"  {asset}: ${fiat_value:.2f} (available: ${available:.2f})")

    print(f"\nTotal Portfolio Value: ${total_value:.2f}")

    if total_value == 0:
        print("\n⚠️  WARNING: Portfolio is empty (no funds)")

except Exception as e:
    print(f"❌ FAILED to access portfolio: {str(e)[:200]}")

print()
print("=" * 70)
