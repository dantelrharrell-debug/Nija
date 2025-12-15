#!/usr/bin/env python3
"""
Check which portfolios the current API key can access
"""
from coinbase.rest import RESTClient

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
    portfolios = resp.get('portfolios', [])
    print(f"✅ Found {len(portfolios)} portfolio(s)\n")
    
    for i, p in enumerate(portfolios, 1):
        uuid = p.get('uuid', 'N/A')
        name = p.get('name', 'N/A')
        ptype = p.get('type', 'N/A')
        print(f"Portfolio #{i}:")
        print(f"  UUID: {uuid}")
        print(f"  Name: {name}")
        print(f"  Type: {ptype}")
        
        # Try to get accounts
        try:
            accts_resp = client.get_portfolio_breakdown(portfolio_uuid=uuid)
            breakdown = accts_resp.get('breakdown', {})
            positions = breakdown.get('spot_positions', [])
            print(f"  Positions: {len(positions)}")
            
            total_value = 0
            for pos in positions:
                asset = pos.get('asset', 'N/A')
                fiat_value = float(pos.get('total_balance_fiat', 0))
                available = float(pos.get('available_to_trade_fiat', 0))
                total_value += fiat_value
                if fiat_value > 0.01:  # Only show non-zero balances
                    print(f"    {asset}: ${fiat_value:.2f} (available: ${available:.2f})")
            
            print(f"  Total Value: ${total_value:.2f}")
        except Exception as e:
            print(f"  ❌ Error accessing accounts: {str(e)[:100]}")
        
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
    breakdown = resp.get('breakdown', {})
    positions = breakdown.get('spot_positions', [])
    
    print(f"✅ SUCCESS! Can access this portfolio")
    print(f"Found {len(positions)} positions:")
    
    total_value = 0
    for pos in positions:
        asset = pos.get('asset', 'N/A')
        fiat_value = float(pos.get('total_balance_fiat', 0))
        available = float(pos.get('available_to_trade_fiat', 0))
        total_value += fiat_value
        print(f"  {asset}: ${fiat_value:.2f} (available: ${available:.2f})")
    
    print(f"\nTotal Portfolio Value: ${total_value:.2f}")
    
    if total_value == 0:
        print("\n⚠️  WARNING: Portfolio is empty (no funds)")
    
except Exception as e:
    print(f"❌ FAILED to access portfolio: {e}")

print()
print("=" * 70)
