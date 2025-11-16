import requests
import json
import time

# ----------------------------
# CONFIG
# ----------------------------
WEBHOOK_URL = "http://127.0.0.1:5000/webhook"  # Your bot endpoint
TEST_ORDER = True  # True = simulate, False = real trade

# Example trade
TRADE_PAYLOAD = {
    "symbol": "BTC-USD",
    "side": "buy",       # "buy" or "sell"
    "size": 0.001,       # very small, safe size
    "type": "market",
    "test": TEST_ORDER
}

# Coinbase API endpoint for accounts (via your bot)
COINBASE_ACCOUNTS_ENDPOINT = "http://127.0.0.1:5000/accounts"

# ----------------------------
# STEP 1: SEND WEBHOOK
# ----------------------------
print("🔹 Sending trade webhook...")
try:
    resp = requests.post(WEBHOOK_URL, json=TRADE_PAYLOAD, timeout=10)
    if resp.status_code == 200:
        print("✅ Webhook sent successfully!")
        print("Bot response:", resp.text)
    else:
        print(f"⚠️ Webhook returned status {resp.status_code}")
        print("Response:", resp.text)
except Exception as e:
    print(f"❌ Failed to send webhook: {e}")

# ----------------------------
# STEP 2: WAIT FOR TRADE PROCESSING
# ----------------------------
print("\n⏳ Waiting 3 seconds for bot to process the trade...")
time.sleep(3)

# ----------------------------
# STEP 3: QUERY ACCOUNT BALANCES
# ----------------------------
print("\n🔹 Fetching Coinbase account balances...")
try:
    resp = requests.get(COINBASE_ACCOUNTS_ENDPOINT, timeout=10)
    if resp.status_code == 200:
        accounts = resp.json().get("data", [])
        if not accounts:
            print("⚠️ No accounts returned. Check your bot's /accounts endpoint.")
        else:
            print("✅ Coinbase accounts fetched:")
            for acc in accounts[:10]:  # show first 10 for readability
                balance = acc.get("balance", {})
                print(f"- {acc['id']} | {acc.get('currency')} | {balance.get('amount')}")
    else:
        print(f"⚠️ Failed to fetch accounts: {resp.status_code}")
        print("Response:", resp.text)
except Exception as e:
    print(f"❌ Error fetching accounts: {e}")

# ----------------------------
# STEP 4: LOG TRADE DETAILS
# ----------------------------
print("\n🔹 Trade payload sent:")
print(json.dumps(TRADE_PAYLOAD, indent=2))
