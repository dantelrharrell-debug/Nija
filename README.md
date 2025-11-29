NIJA Bot – Stable Live-Trading Deployment (Green Checks ✅)

This is the stable, production-ready version of the NIJA Automated Trading Bot.
Currently connected to your funded Coinbase account, container active, and webhook server running.

NIJA executes aggressive-but-safe algorithmic trades using AI logic, TradingView alerts, and Coinbase Advanced API.


⸻

🚀 Copilot Coding-Agent Onboarding

This repo includes:
.github/copilot-coding-agent.yml

This config powers:
	•	Automatic code analysis
	•	Auto-container fixes
	•	Startup validation checks
	•	Secret/environment guidance

Your agent is fully configured for this repo.

⚡ What NIJA Bot Can Do

Core Live-Trading Abilities
	•	🟢 Executes real trades on Coinbase funded accounts
	•	🚀 Responds instantly to TradingView Webhook alerts
	•	📡 Persistent webhook listener (24/7)
	•	📈 Dynamic position sizing (2%–10% of account equity)
	•	🧠 AI risk logic based on balance, volatility, and alerts
	•	🔒 Funding safeguard:
	•	Bot will not start trading unless ≥1 account is funded
	•	Prevents accidental execution on empty accounts

System Safeguards
	•	Auto-stop if:
	•	No funded accounts
	•	Coinbase connection fails
	•	Missing critical files
	•	Circular import prevention enforced with locked folder structure
	•	Nested module architecture prevents accidental breakage

	📁 Folder Structure (DO NOT CHANGE)
	
Nija/
├─ app/
│  ├─ __init__.py
│  ├─ start_bot_main.py
│  ├─ nija_client.py
│  ├─ app/                    # ← nested on purpose (DON’T MOVE)
│  │  ├─ __init__.py
│  │  └─ webhook.py
├─ start_bot.py               # ← entry script
├─ requirements.txt
└─ README.md

Critical Notes
	•	Do NOT rename or relocate app/app/ — this breaks import resolution.
	•	Never import start_bot_main from webhook.py — avoids circular reference.
	•	nija_client.py contains your Coinbase Advanced client bound to your funded account.
	•	start_bot_main.py runs:
	1.	Coinbase initialization
	2.	Funding check
	3.	Webhook server startup
	4.	Trading engine

	💼 Deployment Status

	Component
Status
Container
🟢 Running
Webhook Server
🟢 Active
Coinbase Client
🟢 Connected
Funded Account
🟢 Verified
Trading Mode
🟢 Live Enabled
Safeguards
🟢 Active

NIJA Bot is fully operational.

⸻

⚠️ Warnings (Read Carefully)
	1.	Do NOT edit the folder structure.
	2.	Do NOT disable funding checks.
	3.	Do NOT import files upward from nested app/app.
	4.	Only update code from a separate branch, then redeploy clean.
	5.	Never modify running containers directly on Render — always redeploy stable build.

▶️ Start the Bot Locally

python3 start_bot.py

This will:
	1.	Start Coinbase Client
	2.	Validate funded accounts
	3.	Start the webhook server
	4.	Begin listening for live trade alerts

🛠 start_all.sh (Deployment Entrypoint)

Environment vars required:
	•	COINBASE_API_KEY
	•	COINBASE_API_SECRET
	•	COINBASE_PEM_CONTENT
	•	(Optional) PORT (default: 5000)

Features:
	•	Validates environment configuration
	•	Falls back to python main.py if gunicorn is unavailable
	•	Uses exec so Unix signals (SIGTERM) are handled properly

Run:
	./scripts/start_all.sh

	
📘 If Coinbase SDK is Missing

If the SDK cannot load or API credentials fail:

✔ Bot automatically switches to dry-run mode
✔ Avoids all live orders
✔ Still logs alerts and order calculations

Safety is never bypassed.


🎯 Status Summary
	•	🟢 Stable and Running
	•	🟢 Connected to funded account
	•	🟢 Coinbase Client Verified
	•	🟢 Webhook server up
	•	🟢 Live trading authorized
	•	🛡 All protections ON

This README reflects the official stable deployment of NIJA Bot.





