from flask import Flask
import requests
import os
from nija_client import preflight_check, get_usd_spot_balance

app = Flask(__name__)

@app.route("/debug")
def debug():
    debug_info = {}

    # Get public IP
    try:
        public_ip = requests.get("https://api.ipify.org").text
        debug_info["public_ip"] = public_ip
    except Exception as e:
        debug_info["public_ip_error"] = str(e)

    # Run Coinbase preflight
    try:
        preflight_result = preflight_check()
        debug_info["coinbase_preflight"] = preflight_result
    except Exception as e:
        debug_info["coinbase_preflight_error"] = str(e)

    # Try fetching USD balance
    try:
        usd_balance = get_usd_spot_balance()
        debug_info["usd_balance"] = str(usd_balance)
    except Exception as e:
        debug_info["usd_balance_error"] = str(e)

    return debug_info

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
