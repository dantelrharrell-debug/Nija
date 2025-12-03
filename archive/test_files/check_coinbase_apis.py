from dotenv import load_dotenv
import os, requests, time, hmac, hashlib

# Load .env keys
load_dotenv()

API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")  # for standard Coinbase Pro if needed
BASE_ADVANCED = os.getenv("COINBASE_ADVANCED_BASE", "https://api.cdp.coinbase.com")
BASE_STANDARD = os.getenv("COINBASE_STANDARD_BASE", "https://api.pro.coinbase.com")

if not API_KEY or not API_SECRET:
    raise Exception("API_KEY or API_SECRET not set")

def check_advanced():
    endpoint = "/v2/accounts"
    url = BASE_ADVANCED + endpoint

    timestamp = str(int(time.time()))
    message = timestamp + 'GET' + endpoint
    signature = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": signature,
        "CB-ACCESS-TIMESTAMP": timestamp,
    }

    try:
        resp = requests.get(url, headers=headers)
        print("Advanced API Status Code:", resp.status_code)
        print("Advanced API Response:", resp.text[:500])  # first 500 chars
    except Exception as e:
        print("Advanced API Error:", e)

def check_standard():
    endpoint = "/accounts"
    url = BASE_STANDARD + endpoint

    timestamp = str(int(time.time()))
    method = 'GET'
    body = ""
    message = timestamp + method + endpoint + body
    signature = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": signature,
        "CB-ACCESS-TIMESTAMP": timestamp,
        "CB-ACCESS-PASSPHRASE": API_PASSPHRASE or "",
    }

    try:
        resp = requests.get(url, headers=headers)
        print("Standard API Status Code:", resp.status_code)
        print("Standard API Response:", resp.text[:500])  # first 500 chars
    except Exception as e:
        print("Standard API Error:", e)

if __name__ == "__main__":
    print("Checking Coinbase Advanced API...")
    check_advanced()
    print("\nChecking Coinbase Standard API...")
    check_standard()
