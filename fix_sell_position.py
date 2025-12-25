#!/usr/bin/env python3
"""
Temporary fix script to rewrite the sell_position method correctly
"""

import re

# Read the entire file
with open('/workspaces/Nija/bot/position_cap_enforcer.py', 'r') as f:
    content = f.read()

# Find and replace the broken sell_position method
old_method = '''    def sell_position(self, position: Dict) -> bool:
        """
        Market-sell a single position.
        
        Args:
            position: Position dict with 'symbol', 'balance', etc.
        
        Returns:
            True if successful, False otherwise
        """
        symbol = position['symbol']
        balance = position['balance']
        currency = position['currency']
        
        try:
            logger.info(f"🔴 ENFORCER: Selling {currency}... (${position['usd_value']:.2f})")
            
            # Attempt market sell by quote size (USD value)
                client_order_id = f"enforcer_{currency}_{int(__import__('time').time())}"
                order = self.broker.client.market_order_sell(
                    client_order_id,
                    product_id=symbol,
                    quote_size=str(int(position['usd_value']))  # Round down to avoid overage
                )
            
            logger.info(f"✅ SOLD {currency}! Order placed.")
            return True
        
        except Exception as e:
            logger.error(f"❌ Error selling {symbol}: {e}")
            # Attempt by base_size as fallback
            try:
                adjusted = balance * 0.995  # Account for fee slippage
                    client_order_id = f"enforcer_{currency}_retry_{int(__import__('time').time())}"
                    order = self.broker.client.market_order_sell(
                        client_order_id,
                        product_id=symbol,
                        base_size=str(adjusted)
                    )
                logger.info(f"✅ SOLD {currency} (retry by quantity)!")
                return True
            except Exception as e2:
                logger.error(f"❌ Fallback also failed: {e2}")
                return False'''

new_method = '''    def sell_position(self, position: Dict) -> bool:
        """
        Market-sell a single position.
        
        Args:
            position: Position dict with 'symbol', 'balance', etc.
        
        Returns:
            True if successful, False otherwise
        """
        symbol = position['symbol']
        balance = position['balance']
        currency = position['currency']
        
        try:
            logger.info(f"🔴 ENFORCER: Selling {currency}... (${position['usd_value']:.2f})")
            
            # Attempt market sell by quote size (USD value)
            client_order_id = f"enforcer_{currency}_{int(__import__('time').time())}"
            order = self.broker.client.market_order_sell(
                client_order_id,
                product_id=symbol,
                quote_size=str(int(position['usd_value']))  # Round down to avoid overage
            )
            
            logger.info(f"✅ SOLD {currency}! Order placed.")
            return True
        
        except Exception as e:
            logger.error(f"❌ Error selling {symbol}: {e}")
            # Attempt by base_size as fallback
            try:
                adjusted = balance * 0.995  # Account for fee slippage
                client_order_id = f"enforcer_{currency}_retry_{int(__import__('time').time())}"
                order = self.broker.client.market_order_sell(
                    client_order_id,
                    product_id=symbol,
                    base_size=str(adjusted)
                )
                logger.info(f"✅ SOLD {currency} (retry by quantity)!")
                return True
            except Exception as e2:
                logger.error(f"❌ Fallback also failed: {e2}")
                return False'''

# Replace
if old_method in content:
    content = content.replace(old_method, new_method)
    print("✅ Method replaced successfully")
else:
    print("❌ Could not find the exact method to replace")
    print("Trying with regex...")
    # Try regex replacement
    pattern = r'def sell_position\(self, position: Dict\) -> bool:.*?return False'
    if re.search(pattern, content, re.DOTALL):
        content = re.sub(pattern, new_method, content, flags=re.DOTALL)
        print("✅ Method replaced with regex")
    else:
        print("❌ Regex replacement also failed")

# Write back
with open('/workspaces/Nija/bot/position_cap_enforcer.py', 'w') as f:
    f.write(content)
    
print("✅ File updated")
