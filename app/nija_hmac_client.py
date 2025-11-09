import os, time, hmac, hashlib, base64, json, requests

class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.base = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

    def _sign(self, method, path, body=""):
        ts = str(int(time.time()))
        message = ts + method.upper() + path + body
        h = hmac.new(self.api_secret.encode(), message.encode(), hashlib.sha256).digest()
        return ts, base64.b64encode(h).decode()

    def request(self, method, path, data=None):
        if not self.api_key or not self.api_secret:
            return 0, {"error": "Missing COINBASE_API_KEY or COINBASE_API_SECRET"}
        body = json.dumps(data) if data else ""
        ts, sig = self._sign(method, path, body)
        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": sig,
            "CB-ACCESS-TIMESTAMP": ts,
            "Content-Type": "application/json"
        }
        try:
            resp = requests.request(method, self.base + path, headers=headers, data=body)
            return resp.status_code, resp.json()
        except Exception as e:
            return 0, {"error": str(e)}
