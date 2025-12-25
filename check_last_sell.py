#!/usr/bin/env python3
"""
Check Nija's last sell transaction
"""
import os
import sys
from datetime import datetime

# Add bot directory to path
sys.path.insert(0, '/workspaces/Nija/bot')

def load_env_file():
    """Load .env file manually and normalize PEM content"""
    env_path = '/workspaces/Nija/.env'
    if not os.path.exists(env_path):
        print("❌ .env file not found")
        return False

    with open(env_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key.strip()] = value.strip()

    # Prefer PEM content if provided; normalize escaped newlines
    pem_content = os.getenv('COINBASE_PEM_CONTENT')
    if pem_content:
        normalized_pem = pem_content.replace('\\n', '\n').strip()
        os.environ['COINBASE_API_SECRET'] = normalized_pem

    return True

def main():
    print("\n" + "="*80)
    print("🔍 NIJA - LAST SELL ORDER CHECK")
    print("="*80 + "\n")
    
    # Load environment
    if not load_env_file():
        print("Failed to load environment variables")
        return
    
    api_key = os.getenv('COINBASE_API_KEY')
    api_secret = os.getenv('COINBASE_API_SECRET')
    
    if not api_key or not api_secret:
        print("❌ Missing Coinbase API credentials")
        return
    
    try:
        from coinbase.rest import RESTClient

        # Basic credential diagnostics (do not print secrets)
        print(f"🔐 Credentials check: API Key: {'Found' if bool(api_key) else 'Missing'}; "
              f"API Secret: {'Found' if bool(api_secret) else 'Missing'}")

        print("🔌 Connecting to Coinbase...")
        client = RESTClient(api_key=api_key, api_secret=api_secret)
        print("✅ Connected!\n")
        
        # Get recent filled orders
        print("📊 Fetching recent filled orders...\n")
        
        orders_response = client.list_orders(
            limit=100,
            order_status=['FILLED']
        )
        
        order_list = orders_response.orders if hasattr(orders_response, 'orders') else []
        
        if not order_list:
            print("❌ No filled orders found")
            return
        
        # Find the most recent SELL order
        last_sell = None
        sell_count = 0
        
        for order in order_list:
            side = getattr(order, 'side', '')
            if side == 'SELL':
                sell_count += 1
                if last_sell is None:
                    last_sell = order
        
        print(f"Total filled orders: {len(order_list)}")
        print(f"Total SELL orders: {sell_count}\n")
        
        if last_sell:
            print("="*80)
            print("🎯 LAST SELL ORDER DETAILS")
            print("="*80 + "\n")
            
            # Extract order details
            product_id = getattr(last_sell, 'product_id', 'UNKNOWN')
            order_id = getattr(last_sell, 'order_id', 'UNKNOWN')
            created_time = getattr(last_sell, 'created_time', 'UNKNOWN')
            filled_size = getattr(last_sell, 'filled_size', '0')
            filled_value = getattr(last_sell, 'filled_value', '0')
            average_filled_price = getattr(last_sell, 'average_filled_price', '0')
            
            # Format time
            if created_time != 'UNKNOWN':
                try:
                    dt = datetime.fromisoformat(created_time.replace('Z', '+00:00'))
                    time_str = dt.strftime('%Y-%m-%d %H:%M:%S UTC')
                except:
                    time_str = created_time[:19]
            else:
                time_str = 'UNKNOWN'
            
            print(f"   Product:     {product_id}")
            print(f"   Time:        {time_str}")
            print(f"   Order ID:    {order_id}")
            print(f"   Size:        {filled_size}")
            print(f"   Value:       ${float(filled_value):.2f}")
            print(f"   Avg Price:   ${float(average_filled_price):.2f}")
            
            print("\n" + "="*80)
            
        else:
            print("❌ No SELL orders found in recent history")
            print("\n📝 Recent orders are all BUY transactions\n")
        
        # Show last 5 orders for context
        print("\n📋 LAST 5 ORDERS (All Types):")
        print("-"*80 + "\n")
        
        for i, order in enumerate(order_list[:5], 1):
            product_id = getattr(order, 'product_id', 'UNKNOWN')
            side = getattr(order, 'side', 'UNKNOWN')
            filled_value = getattr(order, 'filled_value', '0')
            created_time = getattr(order, 'created_time', '')[:19]
            
            side_emoji = "🟢" if side == "BUY" else "🔴"
            
            print(f"   {i}. {side_emoji} {created_time} | {product_id:15} | {side:4} | ${float(filled_value):8.2f}")
        
        print()
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        # Provide a helpful hint for PEM formatting issues
        msg = str(e)
        if 'PEM' in msg or 'Malformed' in msg or 'Unable to load PEM' in msg:
            print("\n💡 Hint: Your Coinbase PEM secret likely needs newline normalization. "
                  "If you're storing it in .env as a single line, ensure COINBASE_PEM_CONTENT "
                  "uses escaped newlines (\\n). This script now normalizes them and passes a "
                  "proper PEM to the client.")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
