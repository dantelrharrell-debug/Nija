import requests
import json
import time

# ----------------------------
# CONFIG
# ----------------------------
WEBHOOK_URL = "http://127.0.0.1:5000/webhook"  # Your bot endpoint
TEST_ORDER = True  # True = simulate, False = real trade

# Example trades to simulate
TRADE_SEQUENCE = [
    {"symbol": "BTC-USD", "side": "buy", "size": 0.001, "type": "market", "test": TEST_ORDER},
    {"symbol": "ETH-USD", "side": "buy", "size": 0.01, "type": "market", "test": TEST_ORDER},
    {"symbol": "BTC-USD", "side": "sell", "size": 0.001, "type": "market", "test": TEST_ORDER},
]

# Coinbase accounts endpoint (bot should expose this)
COINBASE_ACCOUNTS_ENDPOINT = "http://127.0.0.1:5000/accounts"

# ----------------------------
# FUNCTION TO SEND TRADE
# ----------------------------
def send_trade(trade_payload):
    try:
        resp = requests.post(WEBHOOK_URL, json=trade_payload, timeout=10)
        if resp.status_code == 200:
            print("✅ Webhook sent successfully!")
            print("Bot response:", resp.text)
        else:
            print(f"⚠️ Webhook returned status {resp.status_code}")
            print("Response:", resp.text)
    except Exception as e:
        print(f"❌ Failed to send webhook: {e}")

# ----------------------------
# FUNCTION TO CHECK BALANCES
# ----------------------------
def fetch_accounts():
    try:
        resp = requests.get(COINBASE_ACCOUNTS_ENDPOINT, timeout=10)
        if resp.status_code == 200:
            accounts = resp.json().get("data", [])
            if not accounts:
                print("⚠️ No accounts returned. Check your bot's /accounts endpoint.")
            else:
                print("✅ Coinbase accounts fetched:")
                for acc in accounts[:10]:
                    balance = acc.get("balance", {})
                    print(f"- {acc['id']} | {acc.get('currency')} | {balance.get('amount')}")
        else:
            print(f"⚠️ Failed to fetch accounts: {resp.status_code}")
            print("Response:", resp.text)
    except Exception as e:
        print(f"❌ Error fetching accounts: {e}")

# ----------------------------
# MAIN LOOP TO SIMULATE TRADES
# ----------------------------
for trade in TRADE_SEQUENCE:
    print("\n🔹 Sending trade:")
    print(json.dumps(trade, indent=2))
    send_trade(trade)
    print("⏳ Waiting 3 seconds for bot to process trade...")
    time.sleep(3)
    fetch_accounts()
    print("-" * 40)
