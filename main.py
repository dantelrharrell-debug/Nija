import logging
import requests
import os

# --- Coinbase key settings from environment ---
COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_ORG_ID = os.environ.get("COINBASE_ORG_ID")
COINBASE_PEM_CONTENT = os.environ.get("COINBASE_PEM_CONTENT")

# --- Helper function to detect current outbound IP ---
def get_outbound_ip():
    try:
        response = requests.get("https://api.ipify.org?format=json", timeout=5)
        return response.json().get("ip")
    except Exception as e:
        logging.error(f"Unable to detect outbound IP: {e}")
        return None

# --- Check Coinbase key permissions ---
def check_coinbase_key_permissions():
    ip = get_outbound_ip()
    logging.info(f"Outbound IP detected: {ip}")
    
    # Simulate a permissions check call
    url = f"https://api.coinbase.com/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/key_permissions"
    headers = {"CB-ACCESS-KEY": COINBASE_API_KEY}
    
    response = requests.get(url, headers=headers)
    
    if response.status_code == 401:
        logging.error("❌ Coinbase API Unauthorized (401). Possible causes:")
        logging.error("- IP restrictions active for this key")
        logging.error("- Incorrect API key / org ID / PEM")
        if ip:
            logging.error(f"Current outbound IP: {ip}")
            logging.error("Action options:")
            logging.error(f"1️⃣ Whitelist this IP in Coinbase Advanced: {ip}")
            logging.error("2️⃣ Remove IP restriction entirely for this key in Coinbase Advanced")
        return False
    elif response.status_code != 200:
        logging.error(f"Unexpected Coinbase response: {response.status_code} - {response.text}")
        return False
    else:
        logging.info("✅ Coinbase key permissions verified.")
        return True

# --- Main bot startup ---
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logging.info("🔥 Nija Trading Bot starting up...")
    
    if check_coinbase_key_permissions():
        logging.info("🚀 Starting live trading...")
        # Place bot start logic here
    else:
        logging.error("⚠️ Startup halted due to Coinbase authentication failure.")
