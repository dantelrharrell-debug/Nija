# test_classic_api.py
import os
import time
import requests
from loguru import logger

API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
BASE = "https://api.coinbase.com"

url = f"{BASE}/v2/accounts"
headers = {
    "CB-ACCESS-KEY": API_KEY,
    "CB-ACCESS-SIGN": API_SECRET,  # NOTE: must generate HMAC signature for live trading
    "CB-ACCESS-TIMESTAMP": str(int(time.time())),
    "Content-Type": "application/json"
}

r = requests.get(url, headers=headers)
logger.info(f"{r.status_code} | {r.text}")
