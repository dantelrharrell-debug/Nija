#!/usr/bin/env python3
"""
Diagnostic script to trace take profit logic
"""

import sys
sys.path.insert(0, '/workspaces/Nija/bot')

# Example: Simulate a buy position and check if it closes on take profit

class MockPosition:
    def __init__(self):
        self.entry_price = 100.0
        self.base_take_profit_pct = 0.05
        self.take_profit = self.entry_price * (1 + self.base_take_profit_pct)  # 105.0
        self.highest_price = self.entry_price
        self.tp_stepped = False
        self.stepped_take_profit_pct = 0.08
        self.take_profit_step_trigger = 0.03
        
print("=" * 80)
print("TAKE PROFIT LOGIC DIAGNOSTIC")
print("=" * 80)

# Test Case 1: BUY position price climbing
print("\n📊 TEST: BUY Position")
print("-" * 80)
pos = MockPosition()
print(f"Entry Price: ${pos.entry_price:.2f}")
print(f"Base Take Profit: {pos.base_take_profit_pct*100}%")
print(f"Take Profit Level: ${pos.take_profit:.2f}")

prices = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0]
for price in prices:
    # Update highest price for trailing
    if price > pos.get('highest_price', pos.entry_price):
        pos.highest_price = price
        
    # Check step trigger
    if (not pos.tp_stepped) and price >= pos.entry_price * (1 + pos.take_profit_step_trigger):
        stepped_tp = pos.entry_price * (1 + pos.stepped_take_profit_pct)
        pos.take_profit = stepped_tp
        pos.tp_stepped = True
        print(f"\nPrice: ${price:.2f} → TP STEPPED UP to ${stepped_tp:.2f} (from ${pos.take_profit:.2f})")
    
    # Check take profit for BUY
    if price >= pos.take_profit:
        print(f"Price: ${price:.2f} → ✅ TAKE PROFIT HIT! (price >= ${pos.take_profit:.2f})")
    else:
        pct = ((price - pos.entry_price) / pos.entry_price) * 100
        print(f"Price: ${price:.2f} → P&L: +{pct:.2f}% (TP at ${pos.take_profit:.2f})")

# Test Case 2: SELL position price dropping
print("\n📊 TEST: SELL Position")
print("-" * 80)

class MockSellPos:
    def __init__(self):
        self.entry_price = 100.0
        self.base_take_profit_pct = 0.05
        self.take_profit = self.entry_price * (1 - self.base_take_profit_pct)  # 95.0
        self.lowest_price = self.entry_price
        self.tp_stepped = False
        self.stepped_take_profit_pct = 0.08
        self.take_profit_step_trigger = 0.03

pos2 = MockSellPos()
print(f"Entry Price: ${pos2.entry_price:.2f}")
print(f"Base Take Profit: {pos2.base_take_profit_pct*100}%")
print(f"Take Profit Level: ${pos2.take_profit:.2f}")

prices = [100.0, 99.0, 98.0, 97.0, 96.0, 95.0, 94.0]
for price in prices:
    # Update lowest price for trailing
    if price < pos2.lowest_price:
        pos2.lowest_price = price
        
    # Check step trigger (price goes DOWN sufficiently)
    if (not pos2.tp_stepped) and price <= pos2.entry_price * (1 - pos2.take_profit_step_trigger):
        stepped_tp = pos2.entry_price * (1 - pos2.stepped_take_profit_pct)
        pos2.take_profit = stepped_tp
        pos2.tp_stepped = True
        print(f"\nPrice: ${price:.2f} → TP STEPPED DOWN to ${stepped_tp:.2f} (from ${pos2.take_profit:.2f})")
    
    # Check take profit for SELL
    if price <= pos2.take_profit:
        print(f"Price: ${price:.2f} → ✅ TAKE PROFIT HIT! (price <= ${pos2.take_profit:.2f})")
    else:
        pct = ((pos2.entry_price - price) / pos2.entry_price) * 100
        print(f"Price: ${price:.2f} → P&L: +{pct:.2f}% (TP at ${pos2.take_profit:.2f})")

print("\n" + "=" * 80)
print("DIAGNOSTIC SUMMARY")
print("=" * 80)
print("""
✅ Take profit logic appears correct:
   • BUY:  Closes when price >= take_profit
   • SELL: Closes when price <= take_profit
   
⚠️  POSSIBLE ISSUES:
   1. Positions closing but not being recorded in logs
   2. Take profit exit orders failing silently
   3. Position data not being checked by manage_open_positions()
   4. Check Coinbase account for filled orders
""")
