# test_client.py
from nija_client import CoinbaseClient
from loguru import logger

def main():
    try:
        client = CoinbaseClient()
    except Exception as e:
        logger.error("Client init failed: %s", e)
        return

    # Report whether JWT will be used (based on internal pem_content presence)
    try:
        have_accounts = client.get_accounts()
        if have_accounts and "data" in have_accounts:
            logger.info("✅ Connected to Coinbase; account data returned (%d accounts).", len(have_accounts.get("data",[])))
            for a in have_accounts.get("data", [])[:5]:
                name = a.get("name") or a.get("currency") or "account"
                bal = a.get("balance", {})
                logger.info(" - %s: %s %s", name, bal.get("amount"), bal.get("currency"))
        else:
            logger.warning("Connected but /accounts returned no data or unexpected format: %s", have_accounts)
    except Exception as e:
        logger.error("Connection test failed: %s", e)

if __name__ == "__main__":
    main()
