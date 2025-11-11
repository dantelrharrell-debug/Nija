import requests
from loguru import logger

class CoinbaseClient:
    def __init__(self, api_key=None, api_secret=None, advanced=True):
        self.advanced = advanced
        self.api_key = api_key
        self.api_secret = api_secret

        # Try recommended base URLs
        candidate_bases = [
            "https://api.coinbase.com",       # Live Advanced Trade
            "https://api-public.sandbox.pro.coinbase.com",  # Sandbox
            "https://api.cdp.coinbase.com"    # Business API (legacy)
        ]

        self.base = None
        for url in candidate_bases:
            if self._test_base(url):
                self.base = url
                logger.info(f"✅ Using Coinbase API base: {self.base}")
                break

        if not self.base:
            raise RuntimeError("❌ Could not find a working Coinbase API base URL.")

    def _test_base(self, url):
        """Test if base URL responds to /accounts"""
        try:
            resp = requests.get(f"{url}/accounts", timeout=5)
            if resp.status_code == 200:
                return True
        except Exception as e:
            logger.debug(f"Base test failed for {url}: {e}")
        return False

    def fetch_accounts(self):
        """Fetch accounts dynamically based on available endpoints"""
        endpoints = [
            "/accounts",
            "/brokerage/accounts",
            "/api/v3/trading/accounts",
            "/api/v3/portfolios"
        ]
        for ep in endpoints:
            try:
                resp = requests.get(f"{self.base}{ep}", timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    logger.info(f"✅ Accounts fetched from {ep}")
                    return data
            except Exception as e:
                logger.warning(f"Failed {ep}: {e}")
        logger.error("❌ Failed to fetch accounts from all candidate endpoints")
        return []
