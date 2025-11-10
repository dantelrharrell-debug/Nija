import os
print("Files in /app:", os.listdir("/app"))

try:
    from nija_client import CoinbaseClient
    print("✅ Import successful:", CoinbaseClient)
except Exception as e:
    print("❌ Import failed:", e)
