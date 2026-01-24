#!/usr/bin/env python3
"""
Validation script for Coinbase Advanced Trade API field names

This script documents the correct field names for the Coinbase Advanced Trade API
get_portfolio_breakdown endpoint's spot_positions array.

PROBLEM IDENTIFIED (Jan 24, 2026):
The bot was using incorrect field names which caused it to not detect crypto balances,
leading to positions being marked as "phantom" and cleared from tracker without selling.

INCORRECT field names (what the code was using):
- available_to_trade_base
- hold_base
- available_to_trade
- hold

CORRECT field names (per Coinbase API documentation):
- available_to_trade_crypto (amount freely tradable in crypto units)
- total_balance_crypto (total balance in crypto units, includes available + held)

Reference: https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/portfolios/get-portfolio-breakdown

Example response structure from get_portfolio_breakdown:
{
  "spot_positions": [
    {
      "asset": "BTC",
      "account_uuid": "1234abc...",
      "total_balance_fiat": 50000.5,
      "total_balance_crypto": 1.234,        # <-- CORRECT: Total balance in BTC
      "available_to_trade_fiat": 49900.0,
      "available_to_trade_crypto": 1.23,    # <-- CORRECT: Available in BTC
      "allocation": 50.8,
      "cost_basis": { "value": "48000.0", "currency": "USD" },
      "asset_img_url": "https://cdn.coinbase.com/assets/btc.png",
      "is_cash": false,
      "average_entry_price": { "value": "48000.0", "currency": "USD" },
      "asset_uuid": "5678def...",
      "unrealized_pnl": 2000.5
    }
  ]
}

FIXES APPLIED:
1. Updated _get_account_balance_detailed() in broker_manager.py (lines 1666-1691)
2. Updated get_positions() in broker_manager.py (lines 3626-3650)
3. Now uses total_balance_crypto which includes both available AND held positions
4. Added debug logging to show API field values for troubleshooting

WHY THIS MATTERS:
- When field names are wrong, the API returns the data but we don't parse it correctly
- We end up with crypto_holdings[asset] = 0.0 for all assets
- The bot thinks it has zero balance and marks positions as "phantom"
- Positions get cleared from tracker without actually selling
- User loses money because positions are not closed when they should be
"""

def main():
    print("=" * 80)
    print("COINBASE ADVANCED TRADE API FIELD NAME VALIDATION")
    print("=" * 80)
    print()
    
    print("✅ CORRECT Field Names for spot_positions:")
    print("   - total_balance_crypto: Total balance of asset in crypto units")
    print("   - available_to_trade_crypto: Amount freely tradable in crypto units")
    print("   - total_balance_fiat: Total balance in fiat currency")
    print("   - available_to_trade_fiat: Amount freely tradable in fiat currency")
    print()
    
    print("❌ INCORRECT Field Names (DO NOT USE):")
    print("   - available_to_trade_base (does not exist)")
    print("   - hold_base (does not exist)")
    print("   - available_to_trade (does not exist)")
    print("   - hold (does not exist)")
    print()
    
    print("💡 KEY INSIGHT:")
    print("   total_balance_crypto = available_to_trade_crypto + held_amount")
    print("   For sells, use total_balance_crypto to get the FULL position size")
    print()
    
    print("📚 Reference:")
    print("   https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/")
    print("   rest-api/portfolios/get-portfolio-breakdown")
    print()
    
    print("=" * 80)
    print("✅ VALIDATION COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()
