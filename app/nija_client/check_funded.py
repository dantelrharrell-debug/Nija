import logging

def check_funded_accounts():
    # Replace this mock with your Coinbase API call later
    funded_accounts = ["BTC", "ETH"]  # Example, could be empty []
    if funded_accounts:
        logging.info(f"✅ Funded accounts found: {funded_accounts}")
        return True
    else:
        logging.warning("⚠️ No funded accounts found.")
        return False
