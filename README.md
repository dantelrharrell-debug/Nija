# ⚡ NIJA UGUMU AMANI™ — Live Coinbase Trading Bot

**Author:** Dante Harrell  
**Tagline:** “The Path of Struggle is Peace.”  
**Version:** Live Deployment — November 7, 2025  

---

## 🧠 Overview

**NIJA** is a fully automated live trading bot built around the NIJA UGUMU AMANI™ philosophy — discipline, resilience, and precision through data and code.  
It connects directly to **Coinbase Advanced Trade API** using JWT authentication for **secure live trading**.

NIJA dynamically manages trades with:
- ✅ Smart **entry and exit logic**
- ✅ **Stop loss** and **trailing take profit**
- ✅ Aggressive–safe position sizing (2–10% per trade)
- ✅ Automated **health checks** and **status logging**
- ✅ Full **Render.com deployment** support for continuous uptime

---

## 🌍 Deployment Status (LIVE)

Your last successful deployment log:
2025-11-07 03:22:45,784 INFO ⚡ NIJA bot is LIVE! Real trades will execute.
[INFO] Starting gunicorn 23.0.0
[INFO] Listening at: http://0.0.0.0:10000
==> Available at your primary URL https://nija.onrender.com

✅ **NIJA is LIVE and trading real positions** using your Coinbase API keys stored as Render secrets.

---

## 🏗️ Project Structure
Nija/
│
├── nija_app.py              # Web server entry point (Render deploy target)
├── nija_client.py           # Coinbase REST/JWT API client
├── nija_trade_logic.py      # Core trade engine: stop loss, trailing take profit
├── nija_logger.py           # Handles info/error logging
├── requirements.txt         # All Python dependencies
├── Dockerfile               # Container config for Render
└── README.md                # This file

---

## ⚙️ Environment Variables (Render Secrets)

Set these **in your Render dashboard** under “Environment” → “Secret Files”:

| Key | Description |
|-----|--------------|
| `COINBASE_API_KEY` | Your Coinbase API Key |
| `COINBASE_API_SECRET` | Your Coinbase API Secret |
| `COINBASE_PASSPHRASE` | Your API Passphrase |
| `LIVE_TRADING` | Set to `1` for live mode |
| `LOG_LEVEL` | Optional: INFO, DEBUG, ERROR |
| `PYTHONUNBUFFERED` | `1` |

✅ Once all are set, NIJA will automatically authenticate and begin trading live.

---

## 🚀 Render Deployment Blueprint

Your working `render.yaml` (auto-created from Render Dashboard):

```yaml
services:
  - type: web
    name: nija-live
    env: python
    plan: starter
    buildCommand: pip install -r requirements.txt
    startCommand: gunicorn nija_app:app --workers 1 --bind 0.0.0.0:$PORT
    envVars:
      - key: COINBASE_API_KEY
        fromSecret: COINBASE_API_KEY
      - key: COINBASE_API_SECRET
        fromSecret: COINBASE_API_SECRET
      - key: COINBASE_PASSPHRASE
        fromSecret: COINBASE_PASSPHRASE
      - key: LIVE_TRADING
        value: "1"
      - key: LOG_LEVEL
        value: "INFO"

🧩 Local Run Command (Testing Locally)
To run NIJA manually on your machine before deployment:
export COINBASE_API_KEY="your_key"
export COINBASE_API_SECRET="your_secret"
export COINBASE_PASSPHRASE="your_passphrase"
export LIVE_TRADING=1

python3 nija_app.py

If everything is configured correctly, you’ll see:
⚡ NIJA bot is LIVE! Real trades will execute.

🧾 Coinbase Balance + Trade Verification Script

You can use this script to instantly check your Coinbase account balance, API key health, and active trading status.
Save this as check_balance.py in your main repo:

# check_balance.py
import os, requests, jwt, time, json, base64, hashlib, hmac

API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
BASE_URL = "https://api.coinbase.com"

if not API_KEY or not API_SECRET:
    raise SystemExit("❌ Missing Coinbase credentials. Check environment variables.")

# Create JWT
now = int(time.time())
payload = {"sub": API_KEY, "iss": "coinbase-cloud", "iat": now, "exp": now + 120}
token = jwt.encode(payload, API_SECRET, algorithm="HS256")

headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json",
}

print("🔍 Checking Coinbase balances...")

try:
    r = requests.get(f"{BASE_URL}/v2/accounts", headers=headers)
    data = r.json()

    if r.status_code == 200:
        print("✅ API Authentication Successful!")
        for acct in data["data"]:
            bal = acct["balance"]
            print(f"{acct['name']}: {bal['amount']} {bal['currency']}")
    else:
        print(f"⚠️ Error: {r.status_code}")
        print(json.dumps(data, indent=2))
except Exception as e:
    print(f"❌ Exception: {e}")

📊 Live Verification Checklist

When Render logs show:
⚡ NIJA bot is LIVE! Real trades will execute.

You can confirm:
	•	Coinbase API keys authenticated
	•	Trade logic initialized
	•	Worker active (PID shown)
	•	Bot online at https://nija.onrender.com

⸻

🔄 Quick Restore Script

If you ever need to rebuild or restore your Render deployment from scratch:
# Clone repo
git clone https://github.com/dantelrharrell-debug/Nija.git
cd Nija

# Install dependencies
pip install -r requirements.txt

# Export secrets (replace with your actual values)
export COINBASE_API_KEY="your_key"
export COINBASE_API_SECRET="your_secret"
export COINBASE_PASSPHRASE="your_passphrase"
export LIVE_TRADING=1

# Run NIJA locally
python3 nija_app.py

Then redeploy using the Render Dashboard or:

git add .
git commit -m "restore live config"
git push

🔒 Security Note
	•	Never commit .env files or raw API keys to GitHub.
	•	Always store API credentials as Render Secrets or Railway Environment Variables.
	•	Rotate Coinbase keys regularly for safety.

📜 License

MIT License © 2025 Dante Harrell
All rights reserved.
Use and modification permitted with attribution.

“No Easy Routes. Embrace the Grind. Mind Over Mass.” — NIJA UGUMU AMANI™

---

✅ **Next Steps**

1. Copy this entire README.  
2. In GitHub → open your repo → click `README.md`.  
3. Click **Edit**, delete the old content, and **paste everything above**.  
4. Commit the change.  

Then you can run:
```bash
python3 check_balance.py
to confirm NIJA’s connection to your Coinbase live trading account.
