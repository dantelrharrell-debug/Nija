from nija_client import CoinbaseClient
from loguru import logger

logger.remove()
logger.add(lambda msg: print(msg, end=""), level="INFO")

def main():
    logger.info("Starting Nija loader (robust).")

    client = CoinbaseClient()  # auto-detects advanced vs spot

    # Try Advanced API first
    accounts = client.fetch_advanced_accounts()
    if not accounts:
        logger.warning("Advanced API failed; falling back to Spot API.")
        accounts = client.fetch_spot_accounts()

    if not accounts:
        logger.error("No accounts returned. Check COINBASE env vars and key permissions.")
        return

    logger.info(f"Successfully fetched {len(accounts)} accounts.")
    for acct in accounts:
        balance = acct.get("balance", {}).get("amount") if acct.get("balance") else "N/A"
        logger.info(f"Account ID: {acct.get('id')} | Currency: {acct.get('currency')} | Balance: {balance}")

if __name__ == "__main__":
    main()
