import logging
from nija_client import CoinbaseClient, get_usd_spot_balance, get_all_accounts

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("nija_debug")

# --- Position Sizing Function ---
def calculate_position_size(account_equity, risk_factor=1.0, min_percent=2, max_percent=10):
    """
    Calculates position size for a trade based on account equity.
    
    account_equity : float : USD account balance
    risk_factor    : float : Multiplier for trade confidence (default=1.0)
    min_percent    : int   : Minimum % of equity to trade
    max_percent    : int   : Maximum % of equity to trade
    
    returns : float : Trade size in USD
    """
    if account_equity <= 0:
        raise ValueError("Account equity must be greater than 0 to trade.")
    
    raw_allocation = account_equity * (risk_factor / 100)
    
    # Clamp allocation between min and max percent
    min_alloc = account_equity * (min_percent / 100)
    max_alloc = account_equity * (max_percent / 100)
    
    trade_size = max(min_alloc, min(raw_allocation, max_alloc))
    return trade_size

# --- Main Preflight & Trading Flow ---
def main():
    try:
        log.info("✅ Starting Nija preflight check...")
        
        # Fetch account balances
        usd_balance = get_usd_spot_balance()
        log.info(f"💰 Current USD balance: {usd_balance}")
        
        # Fetch all accounts for reference
        accounts = get_all_accounts()
        log.info(f"📊 Total accounts fetched: {len(accounts)}")
        
        # Calculate trade size dynamically
        trade_size = calculate_position_size(usd_balance, risk_factor=1)
        log.info(f"📈 Calculated trade size: ${trade_size:.2f}")
        
        # --- Here: Call your live trade function ---
        # Example: NijaBot.place_order(symbol="BTC-USD", size=trade_size)
        log.info("🚀 Ready to place live trade (insert order execution here)")

    except Exception as e:
        log.error(f"❌ Error in Nija debug: {e}")

if __name__ == "__main__":
    main()
