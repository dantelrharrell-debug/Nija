import os
import logging
from coinbase.rest import RESTClient
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')

# Load environment variables - JWT authentication (preferred)
COINBASE_ORG_ID = os.environ.get("COINBASE_ORG_ID")
COINBASE_JWT_PEM = os.environ.get("COINBASE_JWT_PEM")
COINBASE_JWT_KID = os.environ.get("COINBASE_JWT_KID")
COINBASE_JWT_ISSUER = os.environ.get("COINBASE_JWT_ISSUER")

# Load environment variables - Legacy authentication (fallback)
API_KEY = os.environ.get("COINBASE_API_KEY")
API_SECRET = os.environ.get("COINBASE_API_SECRET")
API_PASSPHRASE = os.environ.get("COINBASE_API_PASSPHRASE")

# Account ID for trading
ACCOUNT_ID = os.environ.get("COINBASE_ACCOUNT_ID") or os.environ.get("TRADING_ACCOUNT_ID")

# Initialize Coinbase client (JWT preferred, fallback to legacy)
client = None
if COINBASE_JWT_PEM and COINBASE_JWT_KID:
    # Use JWT authentication (modern approach)
    logging.info("🔐 Using JWT authentication for Coinbase Advanced")
    try:
        client = RESTClient(
            api_key=COINBASE_JWT_KID,
            api_secret=COINBASE_JWT_PEM
        )
        logging.info("✅ Coinbase client initialized with JWT authentication")
    except Exception as e:
        logging.error(f"❌ JWT authentication failed: {e}")
        client = None

if client is None and API_KEY and API_SECRET:
    # Fallback to legacy authentication
    logging.info("🔐 Using legacy API authentication for Coinbase")
    try:
        from coinbase_advanced.client import Client
        client = Client(api_key=API_KEY, api_secret=API_SECRET, api_passphrase=API_PASSPHRASE)
        logging.info("✅ Coinbase client initialized with legacy authentication")
    except Exception as e:
        logging.error(f"❌ Legacy authentication failed: {e}")
        client = None

if client is None:
    logging.error("❌ No valid Coinbase credentials provided. Set either JWT or legacy credentials.")
    logging.error("   JWT: COINBASE_JWT_PEM, COINBASE_JWT_KID")
    logging.error("   Legacy: COINBASE_API_KEY, COINBASE_API_SECRET, COINBASE_API_PASSPHRASE")
    exit(1)

def main_loop():
    logging.info("⚡ Bot is now running live!")
    if ACCOUNT_ID:
        logging.info(f"📊 Monitoring account: {ACCOUNT_ID}")
    
    while True:
        try:
            # Fetch account information
            if ACCOUNT_ID:
                # Try to get specific account
                try:
                    accounts = client.get_accounts()
                    account = next((a for a in accounts if a.get("id") == ACCOUNT_ID or a.get("uuid") == ACCOUNT_ID), None)
                    if account:
                        balance = account.get('balance', {}).get('amount', 'N/A')
                        currency = account.get('currency', 'N/A')
                        logging.info(f"💰 Account balance: {balance} {currency}")
                    else:
                        logging.warning(f"⚠️ Account {ACCOUNT_ID} not found")
                except Exception as e:
                    logging.error(f"Error fetching account {ACCOUNT_ID}: {e}")
            else:
                # List all accounts if no specific account is set
                try:
                    accounts = client.get_accounts()
                    logging.info(f"📋 Found {len(accounts) if accounts else 0} accounts")
                    for acc in (accounts[:3] if accounts else []):  # Show first 3
                        balance = acc.get('balance', {}).get('amount', 'N/A')
                        currency = acc.get('currency', 'N/A')
                        logging.info(f"   - {currency}: {balance}")
                except Exception as e:
                    logging.error(f"Error fetching accounts: {e}")
            
            # Add your trading logic here
            
        except Exception as e:
            logging.error(f"❌ Error in bot loop: {e}")
        
        time.sleep(10)  # adjust frequency as needed

if __name__ == "__main__":
    main_loop()
