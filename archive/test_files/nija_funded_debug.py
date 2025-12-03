import os
import sys
from nija_client import CoinbaseClient, calculate_position_size

class NijaDebug:
    def __init__(self, risk_factor=5):
        try:
            self.client = CoinbaseClient()
        except Exception as e:
            print(f"❌ Error creating CoinbaseClient: {e}")
            sys.exit(1)
        self.risk_factor = risk_factor
        self.funded_account = self.get_funded_account()
        if not self.funded_account:
            print("⚠️ No funded accounts found. Fund your Coinbase account.")
            sys.exit(1)
        self.currency = self.funded_account.get("currency")
        self.balance = float(self.funded_account.get("balance", {}).get("amount", 0))
        print(f"✅ Using funded account: {self.currency}, balance: {self.balance}")

    def get_funded_account(self):
        accounts = self.client.get_all_accounts()
        print("📋 Listing all Coinbase accounts:")
        for acct in accounts:
            currency = acct.get("currency")
            balance = float(acct.get("balance", {}).get("amount", 0))
            available = float(acct.get("available", {}).get("amount", 0))
            print(f"- {currency}: total={balance}, available={available}")
            if balance > 0:
                return acct
        return None

    def calculate_trade_size(self):
        return calculate_position_size(self.balance, risk_factor=self.risk_factor)

if __name__ == "__main__":
    debug = NijaDebug(risk_factor=5)
    trade_size = debug.calculate_trade_size()
    print(f"💰 Calculated trade size for {debug.currency}: {trade_size}")
