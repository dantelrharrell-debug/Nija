from loguru import logger
from nija_coinbase_client import CoinbaseClient

MIN_BALANCE = 10.0

client = CoinbaseClient()

def get_funded_accounts():
    res = client.list_accounts()
    if not res["ok"]:
        logger.error(f"Failed to fetch accounts: {res.get('error')}")
        return []

    funded = []
    for acct in res["data"].get("accounts", []):
        balance = float(acct.get("balance", 0))
        if balance >= MIN_BALANCE:
            funded.append({
                "id": acct["id"],
                "currency": acct["currency"],
                "balance": balance
            })

    logger.info(f"Funded accounts: {[a['currency'] for a in funded]}")
    return funded
