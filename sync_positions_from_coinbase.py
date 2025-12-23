#!/usr/bin/env python3
"""
CRITICAL FIX: Sync actual Coinbase positions into bot tracking

The bot can't manage positions it doesn't know about.
This script:
1. Reads actual crypto holdings from Coinbase
2. Populates data/open_positions.json with proper exit levels
3. Bot will then manage them on next cycle (2.5 min)
"""

import os
import sys
import json
from datetime import datetime
from coinbase.rest import RESTClient

def sync_positions():
    """Sync Coinbase positions to bot tracking file"""
    
    print("\n" + "="*70)
    print("🔄 SYNCING COINBASE POSITIONS TO BOT TRACKING")
    print("="*70 + "\n")
    
    # Get API credentials
    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")
    
    if not api_key or not api_secret:
        print("❌ ERROR: Missing API credentials")
        print("   Set COINBASE_API_KEY and COINBASE_API_SECRET")
        return False
    
    try:
        # Connect to Coinbase
        print("📡 Connecting to Coinbase...")
        client = RESTClient(api_key=api_key, api_secret=api_secret)
        
        # Get all accounts
        print("📊 Fetching accounts...")
        accounts_response = client.get_accounts()
        accounts = accounts_response.get('accounts', [])
        
        print(f"✅ Found {len(accounts)} accounts\n")
        
        # Find crypto holdings
        positions = {}
        
        for account in accounts:
            currency = account.get('currency', '')
            balance = float(account.get('available_balance', {}).get('value', 0))
            
            # Skip USD and zero/dust balances
            if currency == 'USD' or balance <= 0.00001:
                continue
            
            symbol = f"{currency}-USD"
            
            # Get current price
            try:
                product_response = client.get_product(symbol)
                current_price = float(product_response.get('price', 0))
            except:
                print(f"⚠️  Could not get price for {symbol}, skipping")
                continue
            
            if current_price <= 0:
                continue
            
            # Calculate position value
            position_value_usd = balance * current_price
            
            # Skip very small positions (< $1)
            if position_value_usd < 1.0:
                print(f"⚠️  Skipping {symbol} - position too small (${position_value_usd:.2f})")
                continue
            
            # Set exit levels (AGGRESSIVE: tight stops to prevent further bleeding)
            # Stop loss: 2% below current (cut losses fast)
            # Take profit: 3% above current (lock in small wins)
            # Trailing stop: same as stop loss initially
            
            stop_loss_pct = 0.02  # 2%
            take_profit_pct = 0.03  # 3%
            
            stop_loss = current_price * (1 - stop_loss_pct)
            take_profit = current_price * (1 + take_profit_pct)
            trailing_stop = stop_loss  # Start at stop loss level
            
            # Create position entry
            positions[symbol] = {
                "symbol": symbol,
                "side": "BUY",  # Assume all holdings are long positions
                "entry_price": current_price,  # Use current price as entry
                "current_price": current_price,
                "size_usd": position_value_usd,
                "crypto_quantity": balance,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "trailing_stop": trailing_stop,
                "highest_price": current_price,
                "status": "OPEN",
                "timestamp": datetime.now().isoformat(),
                "entry_time": datetime.now().isoformat(),
                "synced_from_coinbase": True,
                "note": "Position synced from Coinbase - exit levels set to stop bleeding"
            }
            
            print(f"💰 {symbol}:")
            print(f"   Balance: {balance:.8f} {currency}")
            print(f"   Current Price: ${current_price:.2f}")
            print(f"   Position Value: ${position_value_usd:.2f}")
            print(f"   Stop Loss: ${stop_loss:.2f} (-{stop_loss_pct*100}%)")
            print(f"   Take Profit: ${take_profit:.2f} (+{take_profit_pct*100}%)")
            print(f"   Trailing Stop: ${trailing_stop:.2f}")
            print()
        
        if not positions:
            print("✅ No positions found to sync")
            return True
        
        # Save to tracking file
        positions_file = "data/open_positions.json"
        
        # Create data directory if needed
        os.makedirs("data", exist_ok=True)
        
        # Create state object
        state = {
            "timestamp": datetime.now().isoformat(),
            "positions": positions,
            "count": len(positions),
            "synced_from_coinbase": True,
            "sync_note": "Positions loaded from Coinbase to enable automated exit management"
        }
        
        # Save atomically
        temp_file = positions_file + '.tmp'
        with open(temp_file, 'w') as f:
            json.dump(state, f, indent=2)
        
        # Rename to final file
        os.rename(temp_file, positions_file)
        
        print("="*70)
        print(f"✅ SYNC COMPLETE")
        print("="*70)
        print(f"📊 Synced {len(positions)} positions to {positions_file}")
        print(f"🤖 Bot will now manage these positions on next cycle (~2.5 min)")
        print(f"🎯 Exit strategy: 2% stop loss, 3% take profit, trailing stops")
        print("="*70 + "\n")
        
        # Display synced positions summary
        print("📋 SYNCED POSITIONS:")
        for symbol, pos in positions.items():
            pnl_from_current = 0.0  # We're using current price as entry
            print(f"   {symbol}: ${pos['size_usd']:.2f} | SL=${pos['stop_loss']:.2f} TP=${pos['take_profit']:.2f}")
        
        print(f"\n⏰ Bot checks every 2.5 minutes")
        print(f"🛡️  Positions will auto-close if stop loss or take profit hit")
        print(f"📈 Trailing stops will lock in profits if price moves up\n")
        
        return True
        
    except Exception as e:
        print(f"\n❌ SYNC FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = sync_positions()
    if success:
        print("✅ Position sync successful - bot will manage on next cycle")
        sys.exit(0)
    else:
        print("❌ Position sync failed")
        sys.exit(1)
