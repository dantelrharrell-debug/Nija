import os
import time
import jwt
import requests
from loguru import logger

CDP_BASE = "https://api.cdp.coinbase.com"
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")

if not API_KEY or not API_SECRET:
    logger.error("CDP API_KEY or API_SECRET not set")
    raise SystemExit(1)

class CoinbaseClient:
    def __init__(self):
        self.api_key = API_KEY
        self.api_secret = API_SECRET

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
