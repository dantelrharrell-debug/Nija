import os
from coinbase_advanced.client import Client

class CoinbaseClient:
    def __init__(self):
        self.api_key = os.environ.get("COINBASE_API_KEY")
        self.org_id = os.environ.get("COINBASE_ORG_ID")
        self.pem_content = os.environ.get("COINBASE_PEM_CONTENT")

        if not all([self.api_key, self.org_id, self.pem_content]):
            raise ValueError("❌ Missing Coinbase API credentials or PEM content.")

        self.client = Client(
            api_key=self.api_key,
            pem=self.pem_content,
            org_id=self.org_id
        )

    def fetch_accounts(self):
        return self.client.accounts.list()
