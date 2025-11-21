# NIJA Bot - Stable Deployment (Green Checks ✅)

This is the **stable version** of the NIJA trading bot, fully deployed and connected to your funded Coinbase account. All critical systems are running, webhook server active, and the bot is ready for live trades.

---

## What NIJA Bot Is Capable Of

NIJA Bot is a **high-speed, AI-driven crypto trading bot** designed for aggressive yet safe trading. Its capabilities include:

- ⚡ **Live trading on funded Coinbase accounts**  
- 📈 **Automatic order execution** based on TradingView alerts  
- 🔒 **Safety checks**:
  - Minimum funded account threshold
  - Stops trading if no account is funded
- 📊 **Portfolio monitoring** in real time  
- 🧠 **Dynamic position sizing**:
  - Minimum 2% and maximum 10% of account equity per trade  
  - Bot adjusts allocation based on current account size and market signals
- 💡 **Webhook integration** for instant alert response  
- 🛡 **Code integrity enforcement**:
  - Nested folder structure prevents circular imports
  - Bot refuses to start if critical files are missing or misconfigured  

> ⚠️ NIJA is designed for advanced users. Never disable safeguards.

---

## Folder Structure

Nija/
├─ app/
│  ├─ init.py
│  ├─ start_bot_main.py
│  ├─ nija_client.py
│  ├─ app/                   # Nested app folder
│  │  ├─ init.py         # MUST exist
│  │  └─ webhook.py
├─ start_bot.py
├─ requirements.txt
└─ README.md

### Notes on Folder Structure

- `start_bot.py` → Entry point for the bot  
- `start_bot_main.py` → Main bot logic: initializes Coinbase client, checks funded accounts, starts webhook server  
- `nija_client.py` → Coinbase client code; fully connected to your funded account  
- `app/webhook.py` → Webhook server handling; must remain inside `app/app` to **avoid circular imports**  
- `FUND_THRESHOLD` is implemented: bot **will not trade** if no account meets minimum balance  

---

## Deployment Status

- **Container Status:** ✅ Active and running  
- **Webhook Server:** ✅ Started  
- **Coinbase Client:** ✅ Connected to funded account  
- **Trading Ready:** ✅ Yes, live and ready to execute trades  

---

## Important Warnings

1. **Do NOT move or rename the nested `app/app` folder** — this will break imports.  
2. **Do NOT import `start_bot_main` inside `webhook.py`** — prevents circular imports.  
3. **Lock this deployment**. Only test updates in a separate branch.  
4. **Minimum funded account check** is active. If no account is funded, bot will stop automatically.  
5. **Always verify your funded accounts** before trading; bot will not override safeguards.  

---

## Startup Command

Run the bot with:

```bash
python3 start_bot.py

This will:
	1.	Start the bot
	2.	Initialize Coinbase client
	3.	Check funded accounts
	4.	Start the webhook server
	5.	Begin listening for live trading signals

⸻

Recommended Best Practices
	•	Always verify funded account balance before trading
	•	Keep app/app/webhook.py unchanged unless you fully understand circular import constraints
	•	Use a separate test branch for any modifications
	•	Do not manually edit running containers; redeploy from this locked, stable version if needed

⸻

Status Summary
	•	✅ Stable and running
	•	✅ Connected to funded account
	•	✅ Webhook server started
	•	✅ Ready to trade
	•	✅ All safeguards active

This README reflects the current green-check stable version of NIJA Bot and its full capabilities.

# Nija Trading Bot

1. Copy `.env.example` → `.env` and fill your Coinbase PEM/ORG_ID
2. Deploy to Railway
3. Bot runs 24/7, trades automatically on Coinbase if SDK is available
4. If Coinbase SDK is unavailable or PEM invalid, bot runs in **safe dry-run mode**

---

## Startup Script

The repository includes a robust startup script at `scripts/start_all.sh` for production deployments.

### Required Environment Variables

The startup script checks for the following required environment variables:
- `COINBASE_API_KEY` - Your Coinbase API key
- `COINBASE_API_SECRET` - Your Coinbase API secret
- `COINBASE_PEM_CONTENT` - Your Coinbase PEM certificate content

If any of these variables are missing, the script will exit with a non-zero status unless `ALLOW_MISSING_ENV=1` is set (see below).

### Optional Environment Variables

- `PORT` - The port to run the server on (default: 5000)
- `WEB_CONCURRENCY` - The number of gunicorn workers to spawn (default: 1)
- `ALLOW_MISSING_ENV` - Set to `1` to allow the script to continue even if required environment variables are missing. This is useful for testing/demo environments but should **never** be used in production.

### Features

- **Environment validation**: Checks all required environment variables before starting
- **UTC timestamps**: All log lines include UTC timestamps for easier troubleshooting
- **Flexible execution**: Prefers system `gunicorn`, falls back to `python -m gunicorn`, and ultimately to `python main.py` if gunicorn is unavailable
- **Signal handling**: Uses `exec` to ensure the process receives signals directly for graceful shutdown
- **POSIX-compatible**: Written in POSIX-compatible Bash with `set -euo pipefail` for robust error handling

### Usage

```bash
# Production usage (with all required env vars set)
./scripts/start_all.sh

# Testing/demo usage (allows missing env vars)
ALLOW_MISSING_ENV=1 ./scripts/start_all.sh

# Custom port and worker count
PORT=8080 WEB_CONCURRENCY=4 ./scripts/start_all.sh
```

### Security Note

⚠️ **Never** set `ALLOW_MISSING_ENV=1` in production environments. This setting bypasses critical environment variable validation and should only be used for testing or demonstration purposes.

