import requests
import json

# ----------------------------
# CONFIG
# ----------------------------
WEBHOOK_URL = "http://127.0.0.1:5000/webhook"  # Replace with your public URL if needed
TEST_ORDER = True  # True = simulate, False = real trade

# Example order
order_payload = {
    "symbol": "BTC-USD",    # Trading pair
    "side": "buy",           # "buy" or "sell"
    "size": 0.001,           # Small size for safety
    "type": "market",        # Order type
    "test": TEST_ORDER       # Your bot can interpret this to simulate
}

# ----------------------------
# SEND WEBHOOK
# ----------------------------
try:
    response = requests.post(WEBHOOK_URL, json=order_payload, timeout=10)
    if response.status_code == 200:
        print("✅ Webhook sent successfully!")
        print("Response:", response.text)
    else:
        print(f"⚠️ Webhook returned status {response.status_code}")
        print("Response:", response.text)
except Exception as e:
    print(f"❌ Failed to send webhook: {e}")

# ----------------------------
# LOGGING
# ----------------------------
print("\n🔹 Test payload sent:")
print(json.dumps(order_payload, indent=2))
