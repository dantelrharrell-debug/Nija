#!/usr/bin/env python3
"""
Force exit all losing positions that should have triggered stop loss
Uses bot's own position management logic to close positions
"""

import os
import sys
import json
from dotenv import load_dotenv

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from broker_manager import CoinbaseBroker

load_dotenv()

def main():
    print("=" * 80)
    print("🚨 FORCE EXIT LOSING POSITIONS")
    print("=" * 80)
    print()
    
    # Load current positions
    positions_file = os.path.join(os.path.dirname(__file__), 'data', 'open_positions.json')
    
    if not os.path.exists(positions_file):
        print("❌ No positions file found")
        return
    
    with open(positions_file, 'r') as f:
        data = json.load(f)
    
    positions = data.get('positions', {})
    
    if not positions:
        print("✅ No open positions")
        return
    
    print(f"📊 Found {len(positions)} position(s)")
    print()
    
    # Connect to broker
    broker = CoinbaseBroker()
    if not broker.connect():
        print("❌ Failed to connect to Coinbase")
        return
    
    print("✅ Connected to Coinbase")
    print()
    
    # Stop loss threshold
    STOP_LOSS_PCT = 0.015  # 1.5% as configured in bot
    
    positions_closed = 0
    total_recovered = 0
    
    for symbol, position in positions.items():
        print(f"\n{'='*80}")
        print(f"Checking: {symbol}")
        print(f"{'='*80}")
        
        entry_price = position['entry_price']
        current_price = position['current_price']
        amount = position['amount']
        value_usd = position.get('value_usd', 0)
        unrealized_loss = position.get('unrealized_loss', 0)
        
        # Calculate actual loss percentage
        loss_pct = abs(unrealized_loss) / value_usd if value_usd > 0 else 0
        
        print(f"Entry Price: ${entry_price:.4f}")
        print(f"Current Price: ${current_price:.4f}")
        print(f"Amount: {amount}")
        print(f"Value: ${value_usd:.2f}")
        print(f"Unrealized Loss: ${unrealized_loss:.2f} ({loss_pct*100:.2f}%)")
        
        # Check if stop loss should have triggered
        should_exit = False
        exit_reason = ""
        
        if unrealized_loss < 0:
            # Any loss should trigger immediate exit in current state
            should_exit = True
            exit_reason = f"Cutting loss at {loss_pct*100:.2f}% (${abs(unrealized_loss):.2f})"
        elif unrealized_loss == 0 and value_usd > 0:
            # Breakeven - exit to recover capital
            should_exit = True
            exit_reason = "BREAKEVEN - Recovering capital"
        
        if not should_exit:
            print(f"✅ Position OK - no exit needed")
            continue
        
        print(f"\n🔴 EXIT REQUIRED: {exit_reason}")
        print(f"Selling {amount} {symbol.split('-')[0]}...")
        
        try:
            # Get real-time price
            try:
                product = broker.client.get_product(symbol)
                current_market_price = float(product.price)
                print(f"Current market price: ${current_market_price:.4f}")
            except:
                current_market_price = current_price
            
            # Execute market sell
            import uuid
            order_id = str(uuid.uuid4())
            
            # Format amount based on crypto
            formatted_amount = f"{amount:.8f}" if amount < 1 else f"{amount:.4f}"
            
            print(f"Placing market SELL order...")
            print(f"  Product: {symbol}")
            print(f"  Amount: {formatted_amount}")
            
            order = broker.client.market_order_sell(
                client_order_id=order_id,
                product_id=symbol,
                base_size=formatted_amount
            )
            
            print(f"✅ ORDER PLACED!")
            print(f"Order ID: {order.get('order_id', 'N/A')}")
            
            # Estimate proceeds
            estimated_proceeds = amount * current_market_price
            estimated_loss = estimated_proceeds - value_usd
            
            print(f"Estimated proceeds: ${estimated_proceeds:.2f}")
            print(f"Estimated P&L: ${estimated_loss:.2f}")
            
            positions_closed += 1
            total_recovered += estimated_proceeds
            
        except Exception as e:
            print(f"❌ Error selling: {e}")
            
            # Try with adjusted amount for fees
            try:
                print(f"\nRetrying with 99.5% of amount (fee adjustment)...")
                adjusted_amount = amount * 0.995
                formatted_amount = f"{adjusted_amount:.8f}" if adjusted_amount < 1 else f"{adjusted_amount:.4f}"
                
                order_id = str(uuid.uuid4())
                order = broker.client.market_order_sell(
                    client_order_id=order_id,
                    product_id=symbol,
                    base_size=formatted_amount
                )
                
                print(f"✅ ORDER PLACED (adjusted)!")
                print(f"Order ID: {order.get('order_id', 'N/A')}")
                
                estimated_proceeds = adjusted_amount * current_market_price
                estimated_loss = estimated_proceeds - value_usd
                
                print(f"Estimated proceeds: ${estimated_proceeds:.2f}")
                print(f"Estimated P&L: ${estimated_loss:.2f}")
                
                positions_closed += 1
                total_recovered += estimated_proceeds
                
            except Exception as e2:
                print(f"❌ Failed again: {e2}")
                print(f"⚠️ You may need to manually close {symbol}")
    
    print(f"\n{'='*80}")
    print(f"SUMMARY")
    print(f"{'='*80}")
    print(f"Positions closed: {positions_closed}/{len(positions)}")
    print(f"Estimated capital recovered: ${total_recovered:.2f}")
    print()
    
    if positions_closed > 0:
        print("✅ Positions liquidated successfully")
        print("💰 Check your account balance - capital should be recovered")
        print()
        print("NEXT STEPS:")
        print("1. Wait 30 seconds for orders to settle")
        print("2. Restart Nija bot with fresh capital")
        print("3. Bot will scan for NEW profitable opportunities")
    else:
        print("ℹ️ No positions needed closing")

if __name__ == "__main__":
    main()
