#!/usr/bin/env python3
"""
FORCE SELL - Direct liquidation with error checking
This actually SHOWS what happens when we try to sell
"""
import os
import sys
import time
import logging

# Setup real logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)

from dotenv import load_dotenv
load_dotenv()

try:
    from coinbase.rest import RESTClient
    logger.info("✅ Coinbase REST client imported")
except ImportError as e:
    logger.error(f"❌ Cannot import coinbase: {e}")
    sys.exit(1)

def main():
    print("\n" + "="*80)
    print("🚨 FORCE SELL - EMERGENCY LIQUIDATION WITH DEBUG")
    print("="*80 + "\n")
    
    api_key = os.getenv('COINBASE_API_KEY')
    api_secret = os.getenv('COINBASE_API_SECRET')
    
    if not api_key or not api_secret:
        logger.error("❌ Missing credentials - cannot proceed")
        return False
    
    try:
        logger.info("Connecting to Coinbase...")
        client = RESTClient(
            api_key=api_key,
            api_secret=api_secret
        )
        logger.info("✅ Connected")
        
        # Get accounts
        logger.info("Fetching accounts...")
        accounts_resp = client.get_accounts()
        accounts = getattr(accounts_resp, 'accounts', [])
        logger.info(f"Found {len(accounts)} accounts")
        
        # Find crypto
        crypto_list = []
        for account in accounts:
            currency = getattr(account, 'currency', None)
            available = getattr(account, 'available_balance', None)
            
            if not currency:
                continue
            
            if hasattr(available, 'value'):
                balance = float(available.value)
            else:
                balance = 0
            
            if balance > 0.0001 and currency not in ['USD', 'USDC']:
                crypto_list.append({
                    'currency': currency,
                    'balance': balance,
                    'symbol': f"{currency}-USD"
                })
                logger.info(f"Found: {currency} = {balance:.8f}")
        
        if not crypto_list:
            print("\n✅ NO CRYPTO HOLDINGS - Already liquidated!\n")
            return True
        
        print(f"\n🪙 Found {len(crypto_list)} crypto positions to sell:\n")
        for item in crypto_list:
            print(f"   {item['currency']}: {item['balance']:.8f}")
        
        print("\n" + "="*80)
        print("SELLING NOW...\n")
        
        for pos in crypto_list:
            currency = pos['currency']
            symbol = pos['symbol']
            amount = pos['balance']
            
            try:
                logger.info(f"Getting price for {symbol}...")
                product = client.get_product(symbol)
                price = float(getattr(product, 'price', 0))
                value = amount * price
                logger.info(f"Price: ${price:.2f}, Value: ${value:.2f}")
                
                print(f"\n📤 Selling {currency}...")
                print(f"   Amount: {amount:.8f}")
                print(f"   Price: ${price:.2f}")
                print(f"   Value: ${value:.2f}")
                
                order = client.market_order_sell(
                    client_order_id=f"force_sell_{currency}_{int(time.time())}",
                    product_id=symbol,
                    quote_size=value
                )
                
                order_id = getattr(order, 'order_id', None)
                status = getattr(order, 'status', 'ERROR')
                
                print(f"   Order ID: {order_id}")
                print(f"   Status: {status}")
                
                if order_id:
                    print(f"   ✅ SOLD\n")
                    logger.info(f"✅ {currency} sold: {order_id}")
                else:
                    print(f"   ❌ FAILED\n")
                    logger.error(f"❌ {currency} - no order ID")
                
                time.sleep(2)
            
            except Exception as e:
                print(f"   ❌ ERROR: {e}\n")
                logger.error(f"Error selling {currency}: {e}")
        
        print("\n" + "="*80)
        print("LIQUIDATION COMPLETE\n")
        return True
    
    except Exception as e:
        logger.error(f"CRITICAL ERROR: {e}")
        return False

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
