# fetch_hmac_accounts.py

from nija_hmac_client import CoinbaseClient
from loguru import logger

def fetch_hmac_accounts():
    """
    Fetch accounts using HMAC client safely.
    Handles JSON errors, 404s, and empty responses without crashing.
    Returns a list of account dicts (can be empty if nothing found).
    """
    try:
        client = CoinbaseClient()
        # Use Advanced API HMAC endpoint
        status, resp = client.request(method="GET", path="/accounts")
        
        if status != 200:
            logger.error(f"❌ Failed to fetch accounts. Status: {status}, Body: {resp}")
            return []
        
        try:
            # If response is already dict/list, no need to json() again
            if isinstance(resp, (dict, list)):
                accounts_data = resp.get("data", []) if isinstance(resp, dict) else resp
            else:
                accounts_data = resp.json().get("data", [])

            if not accounts_data:
                logger.warning("⚠️ No HMAC accounts found.")
            else:
                logger.info("✅ Accounts fetched:")
                for acct in accounts_data:
                    balance = acct.get("balance", {}).get("amount", "0")
                    logger.info(f"{acct.get('name')} ({acct.get('currency')}): {balance}")
            return accounts_data
        
        except Exception as e:
            logger.exception(f"⚠️ Failed to parse JSON response: {e}")
            return []

    except Exception as e:
        logger.exception(f"❌ Error initializing CoinbaseClient or fetching accounts: {e}")
        return []

if __name__ == "__main__":
    accounts = fetch_hmac_accounts()
    if not accounts:
        logger.warning("No accounts returned. Check HMAC key permissions and endpoint.")
