import os
import time
import tempfile
import logging
import requests
import pandas as pd
import jwt

from indicators import calculate_indicators  # <-- your existing indicator functions

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija.jwt.bot")

# --- Create temporary PEM file from .env ---
pem_content = os.getenv("COINBASE_PEM_CONTENT")
if not pem_content:
    raise ValueError("COINBASE_PEM_CONTENT not set in .env")

temp_pem = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
temp_pem.write(pem_content.encode())
temp_pem.flush()
temp_pem_path = temp_pem.name
os.environ["COINBASE_PRIVATE_KEY_PATH"] = temp_pem_path

# --- Coinbase JWT Client ---
class CoinbaseJWTClient:
    def __init__(self):
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.cdp.coinbase.com")
        self.org_id = os.getenv("COINBASE_ISS")
        self.pem_path = temp_pem_path

        if not self.org_id or not self.pem_path:
            raise Exception("Set COINBASE_ISS and COINBASE_PEM_CONTENT in your environment")

        with open(self.pem_path, "r") as f:
            self.private_key = f.read()

        logger.info("CoinbaseJWTClient initialized. Org: %s", self.org_id)

    def generate_jwt(self):
        now_ts = int(time.time())
        payload = {
            "iss": self.org_id,
            "sub": self.org_id,
            "nbf": now_ts,
            "iat": now_ts,
            "exp": now_ts + 120
        }
        token = jwt.encode(payload, self.private_key, algorithm="ES256")
        return token

    def request(self, method, path, data=None, params=None):
        token = self.generate_jwt()
        url = f"{self.base_url}{path}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        resp = requests.request(method, url, headers=headers, json=data, params=params)
        if resp.status_code not in [200, 201]:
            logger.error("Error %s %s: %s", method, path, resp.text)
        return resp.json()

    def list_accounts(self):
        return self.request("GET", "/platform/v1/wallets")

    def create_trade(self, product_id, side, size, type="market"):
        data = {
            "product_id": product_id.replace("/", "-"),
            "side": side,
            "size": str(size),
            "type": type
        }
        return self.request("POST", "/trades", data)

    def fetch_ohlcv(self, product_id, granularity=60, limit=100):
        params = {"granularity": granularity, "limit": limit}
        path = f"/products/{product_id.replace('/', '-')}/candles"
        data = self.request("GET", path, params=params)
        if not data:
            logger.warning("No OHLCV data returned for %s", product_id)
            return pd.DataFrame()
        df = pd.DataFrame(data, columns=["timestamp", "low", "high", "open", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
        df.set_index("timestamp", inplace=True)
        df = df.apply(pd.to_numeric, errors="coerce").sort_index()
        return df

# --- Initialize client ---
client = CoinbaseJWTClient()
accounts = client.list_accounts()
logger.info("Accounts: %s", accounts)

# --- Dynamic position sizing ---
def calculate_position_size(account_balance, trade_pct=0.05):
    """
    Returns trade size in units.
    - account_balance: USD equivalent of total balance for that coin or account
    - trade_pct: fraction of account balance to risk per trade (2%-10% recommended)
    """
    # Ensure safe boundaries
    trade_pct = max(0.02, min(0.10, trade_pct))
    return account_balance * trade_pct

# --- Trading settings ---
TRADING_PAIRS = ["BTC/USD", "ETH/USD", "ADA/USD", "SOL/USD", "LTC/USD", "BNB/USD"]
TRADE_INTERVAL = 5  # seconds between cycles
TRADE_RISK_PCT = 0.05  # 5% of account per trade (adjustable 0.02-0.10)

# --- Main trading loop ---
def run_trading_bot():
    logger.info("[NIJA] Trading bot started.")
    while True:
        try:
            for symbol in TRADING_PAIRS:
                # 1️⃣ Fetch market data
                df = client.fetch_ohlcv(symbol, granularity=60, limit=100)
                if df.empty:
                    continue

                # 2️⃣ Calculate signals
                signals = calculate_indicators(df)  # {"buy_signal": True/False}

                # 3️⃣ Determine trade side
                side = "buy" if signals.get("buy_signal") else "sell"

                # 4️⃣ Determine trade size dynamically based on USD account balance
                # Example: use first account's balance in USD
                usd_account = next((a for a in accounts if a.get("currency") == "USD"), None)
                if not usd_account:
                    logger.warning("USD account not found. Skipping trade for %s", symbol)
                    continue
                account_balance = float(usd_account.get("balance", 0))
                trade_size = calculate_position_size(account_balance, trade_pct=TRADE_RISK_PCT)

                # 5️⃣ Place trade
                response = client.create_trade(product_id=symbol, side=side, size=trade_size)
                logger.info("[NIJA] Trade %s %s: %s", symbol, side, response)

            time.sleep(TRADE_INTERVAL)

        except KeyboardInterrupt:
            logger.info("[NIJA] Bot stopped manually.")
            break
        except Exception as e:
            logger.error("[NIJA] Unexpected error: %s", e)
            time.sleep(TRADE_INTERVAL)

# --- Start bot ---
if __name__ == "__main__":
    run_trading_bot()
