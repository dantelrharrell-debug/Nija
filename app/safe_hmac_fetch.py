# safe_hmac_fetch.py
from nija_hmac_client import CoinbaseClient
from loguru import logger

def fetch_hmac_accounts_safe():
    """
    Fetch accounts via HMAC safely. Handles 404, invalid JSON, empty lists.
    Never crashes.
    Returns list of accounts (may be empty).
    """
    try:
        client = CoinbaseClient()
        status, resp = client.request(method="GET", path="/accounts")  # HMAC endpoint
        
        if status != 200:
            logger.warning(f"⚠️ Failed to fetch accounts. Status: {status}, Body: {resp}")
            return []  # Never crash

        # Attempt JSON parsing safely
        accounts_data = []
        try:
            if isinstance(resp, (dict, list)):
                accounts_data = resp.get("data", []) if isinstance(resp, dict) else resp
            else:
                # Sometimes resp is text, try json safely
                import json
                accounts_data = json.loads(resp).get("data", [])
        except Exception as e:
            logger.warning(f"⚠️ JSON parse failed, returning empty list: {e}")
            accounts_data = []

        if not accounts_data:
            logger.warning("⚠️ No HMAC accounts found.")
        else:
            logger.info("✅ Accounts fetched:")
            for acct in accounts_data:
                balance = acct.get("balance", {}).get("amount", "0")
                logger.info(f"{acct.get('name')} ({acct.get('currency')}): {balance}")

        return accounts_data

    except Exception as e:
        logger.error(f"❌ Unexpected error fetching HMAC accounts: {e}")
        return []  # Never crash

# Example usage
if __name__ == "__main__":
    accounts = fetch_hmac_accounts_safe()
    if not accounts:
        logger.warning("No accounts available. Bot will not trade.")
