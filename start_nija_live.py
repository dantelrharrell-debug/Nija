import time
from loguru import logger
import os
import jwt
import requests

# ------------------------------
# ENV / Config
# ------------------------------
CDP_BASE = "https://api.cdp.coinbase.com"
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")

TRADE_INTERVAL = 10          # seconds between trading cycles
POSITION_SIZE = 0.5          # % of account balance to use per trade
MIN_BALANCE = 10.0           # minimum account balance to trade
PRODUCTS = ["BTC-USD", "ETH-USD", "LTC-USD"]  # products to trade

if not API_KEY or not API_SECRET:
    logger.error("COINBASE_API_KEY or COINBASE_API_SECRET not set in environment!")
    raise SystemExit(1)

# ------------------------------
# Coinbase CDP Client
# ------------------------------
class CoinbaseClient:
    def __init__(self, api_key, api_secret):
        self.api_key = api_key
        self.api_secret = api_secret

    def _generate_jwt(self):
        payload = {
            "iat": int(time.time()),
            "exp": int(time.time()) + 30,
        }
        token = jwt.encode(payload, self.api_secret, algorithm="HS256")
        return token

    def _request(self, method, path, params=None, data=None):
        url = f"{CDP_BASE}{path}"
        headers = {"Authorization": f"Bearer {self._generate_jwt()}"}
        try:
            resp = requests.request(method, url, headers=headers, params=params, json=data, timeout=10)
            resp.raise_for_status()
            return {"ok": True, "data": resp.json()}
        except requests.HTTPError as e:
            return {"ok": False, "error": str(e), "status": resp.status_code}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def list_accounts(self):
        return self._request("GET", "/platform/v2/evm/accounts")

    def place_order(self, account_id, side, product, size):
        payload = {
            "account_id": account_id,
            "side": side,
            "product_id": product,
            "size": size
        }
        return self._request("POST", "/platform/v2/evm/orders", data=payload)

# ------------------------------
# Preflight: Fetch funded accounts
# ------------------------------
def get_funded_accounts(client):
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

    if funded:
        logger.info(f"Funded accounts: {[a['currency'] for a in funded]}")
    else:
        logger.warning("No funded accounts found above minimum balance.")
    return funded

# ------------------------------
# Trading logic (placeholder)
# ------------------------------
def signal_generator(product):
    """
    Dummy trading signal generator.
    Replace with your real logic (VWAP, RSI, etc.).
    Returns 'buy', 'sell', or None.
    """
    import random
    return random.choice(["buy", "sell", None])

# ------------------------------
# Main Live Trader
# ------------------------------
def main():
    logger.info("Starting Nija Live Trader...")
    client = CoinbaseClient(API_KEY, API_SECRET)

    accounts = get_funded_accounts(client)
    if not accounts:
        logger.error("No funded accounts available. Exiting...")
        return

    while True:
        for acct in accounts:
            account_id = acct["id"]
            balance = acct["balance"]

            for product in PRODUCTS:
                signal = signal_generator(product)
                size = balance * POSITION_SIZE

                if signal in ["buy", "sell"]:
                    res = client.place_order(account_id, signal, product, size)
                    if res.get("ok"):
                        logger.info(f"[{product}] Order executed: {res['data']}")
                    else:
                        logger.error(f"[{product}] Order failed: {res.get('error')}")
        logger.info(f"Sleeping {TRADE_INTERVAL}s before next cycle...")
        time.sleep(TRADE_INTERVAL)

if __name__ == "__main__":
    main()
