import os
import requests
import hmac
import hashlib
import time

# Load API keys from environment variables
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE", "")  # optional
BASE_URLS = {
    "Live": "https://api.coinbase.com/v2",
    "Sandbox": "https://api-public.sandbox.coinbase.com/v2"
}

def test_api(base_url):
    timestamp = str(int(time.time()))
    method = "GET"
    request_path = "/accounts"
    body = ""
    
    message = timestamp + method + request_path + body
    signature = hmac.new(
        API_SECRET.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()
    
    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": signature,
        "CB-ACCESS-TIMESTAMP": timestamp,
        "CB-VERSION": "2025-11-11"
    }
    
    if API_PASSPHRASE:
        headers["CB-ACCESS-PASSPHRASE"] = API_PASSPHRASE

    try:
        response = requests.get(base_url + request_path, headers=headers, timeout=10)
        return response.status_code, response.text
    except Exception as e:
        return None, str(e)

if __name__ == "__main__":
    for env, url in BASE_URLS.items():
        status, data = test_api(url)
        print(f"\nTesting {env} API:")
        print("Base URL:", url)
        if status == 200:
            print("✅ Keys are valid!")
        elif status == 401:
            print("❌ Unauthorized – check key, secret, passphrase, or permissions")
        elif status == 403:
            print("❌ Forbidden – key exists but lacks required permissions")
        elif status is None:
            print("❌ Request failed:", data)
        else:
            print(f"⚠️ Status {status}: {data}")
