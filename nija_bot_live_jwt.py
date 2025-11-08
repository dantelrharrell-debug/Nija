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

    def request(self, method, path, data=None):
        token = self.generate_jwt()
        url = f"{self.base_url}{path}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        resp = requests.request(method, url, headers=headers, json=data)
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

# --- Initialize client ---
client = CoinbaseJWTClient()
accounts = client.list_accounts()
logger.info("Accounts: %s", accounts)

# --- Trading settings ---
TRADING_PAIRS = ["BTC/USD", "ETH/USD", "ADA/USD", "SOL/USD", "LTC/USD", "BNB/USD"]
TRADE_AMOUNT = 0.01  # Default size per trade, adjust per coin
TRADE_INTERVAL = 5  # seconds

# --- Market data fetcher ---
def fetch_market_data(symbol):
    """
    Replace with real Coinbase market data fetch if needed.
    Here we create a dummy DataFrame for testing and indicator calculations.
    """
    now = pd.Timestamp.now()
    data = {
        "open": [100 + i for i in range(10)],
        "high": [101 + i for i in range(10)],
        "low": [99 + i for i in range(10)],
        "close": [100 + i for i in range(10)],
        "volume": [10 + i for i in range(10)],
        "timestamp": [now - pd.Timedelta(minutes=i) for i in range(10)]
    }
    df = pd.DataFrame(data)
    df.set_index("timestamp", inplace=True)
    return df

# --- Main trading loop ---
def run_trading_bot():
    logger.info("[NIJA] Trading bot started.")
    while True:
        try:
            for symbol in TRADING_PAIRS:
                # 1️⃣ Fetch market data
                df = fetch_market_data(symbol)

                # 2️⃣ Calculate signals using your custom indicators
                signals = calculate_indicators(df)  # returns {"buy_signal": True/False}

                # 3️⃣ Determine trade side
                side = "buy" if signals.get("buy_signal") else "sell"

                # 4️⃣ Place live trade
                response = client.create_trade(product_id=symbol, side=side, size=TRADE_AMOUNT)
                logger.info("[NIJA] Trade %s %s: %s", symbol, side, response)

            # 5️⃣ Wait before next cycle
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
