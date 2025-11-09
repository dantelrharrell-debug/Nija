import json
from loguru import logger

def fetch_hmac_accounts(client):
    """
    Safely fetch accounts using HMAC client.
    Returns a list of accounts if successful, otherwise empty list.
    """
    try:
        status, response = client.request(method="GET", path="/v2/accounts")  # keep your path here
        logger.info(f"Status code from /v2/accounts: {status}")

        try:
            accounts = response.json() if hasattr(response, "json") else json.loads(response)
            logger.info("✅ Accounts fetched:")
            for acct in accounts.get("data", []):
                logger.info(f"{acct['name']} ({acct['currency']}): {acct['balance']['amount']}")
            return accounts.get("data", [])
        except json.JSONDecodeError:
            logger.warning(f"⚠️ JSON decode failed. Status: {status}, Body: {response.text if hasattr(response, 'text') else response}")
            return []

    except Exception as e:
        logger.exception(f"❌ Error fetching HMAC accounts: {e}")
        return []
