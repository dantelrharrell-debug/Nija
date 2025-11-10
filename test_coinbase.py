from dotenv import load_dotenv
import os, requests, time, hmac, hashlib

load_dotenv()  # loads keys from your .env file

API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
BASE_URL = os.getenv("COINBASE_ADVANCED_BASE", "https://api.cdp.coinbase.com")

if not API_KEY or not API_SECRET:
    raise Exception("API_KEY or API_SECRET not set")

endpoint = "/v2/accounts"
url = BASE_URL + endpoint

timestamp = str(int(time.time()))
message = timestamp + 'GET' + endpoint
signature = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
headers = {
    "CB-ACCESS-KEY": API_KEY,
    "CB-ACCESS-SIGN": signature,
    "CB-ACCESS-TIMESTAMP": timestamp,
}

response = requests.get(url, headers=headers)

print("Status Code:", response.status_code)
print("Response Body:", response.text)
