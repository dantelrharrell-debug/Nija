import os
import sys
import time
from pathlib import Path
from coinbase.rest import RESTClient

# Add bot directory to path
sys.path.insert(0, os.path.dirname(__file__))

from trading_strategy import TradingStrategy

# Load environment variables from .env file
def load_env():
    env_path = Path(__file__).parent.parent / '.env'
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    # Remove quotes if present
                    value = value.strip('"').strip("'")
                    os.environ[key] = value

def run_live_trading():
    print("📋 Initializing trading bot...")
    
    # Load environment variables
    load_env()
    
    # Pull keys from environment
    api_key = os.environ.get("COINBASE_API_KEY")
    api_secret = os.environ.get("COINBASE_API_SECRET")
    
    print(f"🔑 API Key present: {'YES' if api_key else 'NO'}")
    print(f"🔑 API Secret present: {'YES' if api_secret else 'NO'}")
    
    # Handle newline characters in the PEM key
    if api_secret and "\\n" in api_secret:
        api_secret = api_secret.replace("\\n", "\n")
    
    # Ensure proper PEM format
    if api_secret and not api_secret.endswith("\n"):
        api_secret = api_secret.rstrip() + "\n"

    try:
        print("🔌 Connecting to Coinbase API...")
        # Initialize Coinbase client
        client = RESTClient(api_key=api_key, api_secret=api_secret)
        
        # Test connection
        print("📊 Fetching account data...")
        accounts = client.get_accounts()
        print("✅ Successfully connected to Coinbase!")
        print(f"Found {len(accounts['accounts'])} accounts")
        
        # Display account balances
        for account in accounts['accounts']:
            balance = float(account['available_balance']['value'])
            if balance > 0:
                print(f"  {account['currency']}: {balance} ({account['name']})")
        
        # Initialize trading strategy
        print("\n🔧 Initializing trading strategy...")
        strategy = TradingStrategy(
            client=client,
            pairs=["BTC-USD", "ETH-USD", "SOL-USD"],
            base_allocation=5.0,  # 5% of balance per trade
            max_exposure=0.3,     # Max 30% in open positions
            max_daily_loss=0.1    # Max 10% daily loss
        )
        print("✅ Strategy initialized successfully")
        
        # Get ALL available trading pairs from Coinbase
        print("\n📡 Fetching all available trading products...")
        try:
            products_response = client.get_products()
            all_products = []
            
            # Filter for tradable products ending in USD, USDC, or USDT
            for product in products_response.products:
                product_id = product.product_id
                # Include all USD-based pairs (crypto, stocks, futures, options)
                if product_id.endswith('-USD') or product_id.endswith('-USDC') or product_id.endswith('-USDT'):
                    # Check if trading is enabled
                    if hasattr(product, 'status') and product.status == 'online':
                        all_products.append(product_id)
            
            # If can't get products, fallback to expanded list
            if not all_products:
                all_products = [
                    # Major Crypto
                    'BTC-USD', 'ETH-USD', 'SOL-USD', 'XRP-USD', 'ADA-USD',
                    'DOGE-USD', 'MATIC-USD', 'LINK-USD', 'AVAX-USD', 'DOT-USD',
                    'SHIB-USD', 'UNI-USD', 'ATOM-USD', 'LTC-USD', 'BCH-USD',
                    'NEAR-USD', 'APT-USD', 'ARB-USD', 'OP-USD', 'FIL-USD',
                    'ICP-USD', 'VET-USD', 'ALGO-USD', 'HBAR-USD', 'GRT-USD',
                    # DeFi
                    'AAVE-USD', 'MKR-USD', 'SNX-USD', 'CRV-USD', 'COMP-USD',
                    # Layer 2s
                    'IMX-USD', 'LRC-USD', 'MINA-USD',
                    # Meme/Community
                    'PEPE-USD', 'FLOKI-USD', 'BONK-USD',
                    # Stablecoins (for monitoring)
                    'USDC-USD', 'DAI-USD', 'USDT-USD'
                ]
            
            print(f"   Found {len(all_products)} tradable products")
            print(f"   Markets: {', '.join(all_products[:10])}{'...' if len(all_products) > 10 else ''}")
            
        except Exception as e:
            print(f"   ⚠️ Could not fetch products: {e}")
            # Fallback to major crypto pairs
            all_products = ['BTC-USD', 'ETH-USD', 'SOL-USD', 'XRP-USD', 'ADA-USD', 'DOGE-USD']
            print(f"   Using fallback: {', '.join(all_products)}")
        
        print("\n🚀 Starting 24/7 trading bot...")
        print(f"   Pairs: {len(all_products)} markets (ALL USD-based)")
        print("   Strategy: VWAP + RSI + MACD")
        print("   Scan interval: 2.5 minutes")
        print("   Signal threshold: 2/5 conditions")
        print("   Max daily trades: 200")
        print("   Press Ctrl+C to stop\n")
        
        # Main trading loop
        while True:
            try:
                print(f"🔍 [{time.strftime('%Y-%m-%d %H:%M:%S')}] Running trading cycle...")
                
                # Update strategy pairs with all available products each cycle
                strategy.pairs = all_products
                strategy.run_trading_cycle()
                
                # Wait 2.5 minutes between cycles (24 scans/hour = 12+ trades/hour)
                print(f"\n⏰ Waiting 2.5 minutes until next cycle...")
                time.sleep(150)
                
            except KeyboardInterrupt:
                print("\n\n🛑 Stopping trading bot...")
                break
            except Exception as e:
                print(f"\n❌ Error in trading cycle: {e}")
                print("   Retrying in 1 minute...")
                time.sleep(60)
        
    except Exception as e:
        print(f"❌ Error connecting to Coinbase: {e}")
        raise

if __name__ == "__main__":
    run_live_trading()
