import os
print("=== NIJA DEBUG: CODE UPDATED 2025-12-11 ===")
import sys
import time
from pathlib import Path
from coinbase_advanced.client import Client

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
    api_passphrase = os.environ.get("COINBASE_API_PASSPHRASE")

    print(f"🔑 API Key present: {'YES' if api_key else 'NO'}")
    print(f"🔑 API Secret present: {'YES' if api_secret else 'NO'}")
    print(f"🔑 API Passphrase present: {'YES' if api_passphrase else 'NO'}")

    try:
        print("🔌 Connecting to Coinbase Advanced API...")
        # Initialize Coinbase Advanced client
        client = Client(api_key=api_key, api_secret=api_secret, api_passphrase=api_passphrase)
        # Test connection
        print("📊 Fetching account data...")
        accounts = client.get_accounts()
        print("✅ Successfully connected to Coinbase!")
        print(f"Found {len(accounts['accounts'])} accounts")
        for account in accounts['accounts']:
            balance = float(account['available_balance']['value'])
            if balance > 0:
                print(f"  {account['currency']}: {balance} ({account['name']})")

        # Get ALL available trading pairs from Coinbase
        print("\n📡 Fetching all available trading products...")

        # DEBUG: Confirm main trading loop is starting
        print("[DEBUG] Entering main trading loop...")
        try:
            products_response = client.get_products()
            all_products = []
            products = getattr(products_response, 'products', None)
            if products is not None:
                for product in products:
                    product_id = product.product_id
                    if product_id.endswith('-USD') or product_id.endswith('-USDC') or product_id.endswith('-USDT'):
                        if hasattr(product, 'status') and product.status == 'online':
                            all_products.append(product_id)
            if not all_products:
                all_products = [
                    'BTC-USD', 'ETH-USD', 'SOL-USD', 'XRP-USD', 'ADA-USD',
                    'DOGE-USD', 'MATIC-USD', 'LINK-USD', 'AVAX-USD', 'DOT-USD',
                    'SHIB-USD', 'UNI-USD', 'ATOM-USD', 'LTC-USD', 'BCH-USD',
                    'NEAR-USD', 'APT-USD', 'ARB-USD', 'OP-USD', 'FIL-USD',
                    'ICP-USD', 'VET-USD', 'ALGO-USD', 'HBAR-USD', 'GRT-USD',
                    'AAVE-USD', 'MKR-USD', 'SNX-USD', 'CRV-USD', 'COMP-USD',
                    'IMX-USD', 'LRC-USD', 'MINA-USD',
                    'PEPE-USD', 'FLOKI-USD', 'BONK-USD',
                    'USDC-USD', 'DAI-USD', 'USDT-USD'
                ]
            print(f"   Found {len(all_products)} tradable products")
            print(f"   Markets: {', '.join(all_products[:10])}{'...' if len(all_products) > 10 else ''}")
        except Exception as e:
            print(f"   ⚠️ Could not fetch products: {e}")
            all_products = ['BTC-USD', 'ETH-USD', 'SOL-USD', 'XRP-USD', 'ADA-USD', 'DOGE-USD']
            print(f"   Using fallback: {', '.join(all_products)}")

        # --- STRATEGY DIVERSIFICATION ---
        # Define multiple strategies with different configs
        strategies = [
            TradingStrategy(
                client=client,
                pairs=["BTC-USD", "ETH-USD", "SOL-USD"],
                base_allocation=5.0,
                max_exposure=0.3,
                max_daily_loss=0.1
            ),
            TradingStrategy(
                client=client,
                pairs=["MATIC-USD", "LINK-USD", "AVAX-USD"],
                base_allocation=3.0,
                max_exposure=0.2,
                max_daily_loss=0.07
            ),
            # Add more strategies here as needed
        ]
        print(f"\n🚀 Starting 24/7 trading bot with {len(strategies)} strategies...")
        print(f"   Pairs: {len(all_products)} markets (ALL USD-based)")
        print("   Strategy: VWAP + RSI + MACD")
        print("   Scan interval: 2.5 minutes")
        print("   Signal threshold: 2/5 conditions")
        print("   Max daily trades: 200")
        print("   Press Ctrl+C to stop\n")

        # Main trading loop
        while True:
            try:
                print(f"🔍 [{time.strftime('%Y-%m-%d %H:%M:%S')}] Running trading cycle for all strategies...")
                for idx, strategy in enumerate(strategies):
                    print(f"\n--- Running Strategy {idx+1} ---")
                    # Optionally, update pairs dynamically if needed:
                    # strategy.pairs = all_products[:10]  # Example: rotate pairs
                    strategy.run_trading_cycle()
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
