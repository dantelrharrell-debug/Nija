from loguru import logger

logger.remove()
logger.add(lambda msg: print(msg, end=""), level="INFO")

try:
    from nija_client import CoinbaseClient
except ImportError as e:
    logger.error(f"Cannot import CoinbaseClient: {e}")
    raise

def get_balances():
    client = CoinbaseClient(advanced=True)
    accounts = client.fetch_advanced_accounts()
    if not accounts:
        logger.warning("Advanced API failed; falling back to Spot API.")
        accounts = client.fetch_spot_accounts()
    if not accounts:
        logger.error("No accounts returned. Check COINBASE env vars and key permissions.")
        return []

    balances = []
    for a in accounts:
        bal = a.get("balance", {})
        balances.append({
            "name": a.get("name", "<unknown>"),
            "amount": bal.get("amount", "0"),
            "currency": bal.get("currency", "?")
        })
    return balances

if __name__ == "__main__":
    for b in get_balances():
        logger.info(f"{b['name']}: {b['amount']} {b['currency']}")
