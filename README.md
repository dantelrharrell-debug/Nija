# NIJA Trading Bot

NIJA is an autonomous Coinbase Advanced Trade bot (APEX v7.1) that trades USD/USDC pairs using dual RSI signals and adaptive risk management.

## What matters for live trading

- Uses the default Advanced Trade portfolio attached to your API key; portfolio overrides are removed.
- To trade, the key’s default Advanced Trade portfolio must hold USD/USDC. If logs show $0, the key is pointing at an unfunded portfolio.
- If needed, recreate the API key while the funded Advanced Trade portfolio is selected, then redeploy with the new key/secret.
- Move funds into the default Advanced Trade portfolio: https://www.coinbase.com/advanced-portfolio

## Quick balance check (same auth NIJA uses)

```bash
source .venv/bin/activate  # optional: use repo venv
export COINBASE_API_KEY="organizations/<ORG_ID>/apiKeys/<API_KEY_ID>"
export COINBASE_API_SECRET="-----BEGIN EC PRIVATE KEY-----
...
-----END EC PRIVATE KEY-----"

python - <<'PY'
import os
from coinbase.rest import RESTClient

api_key = os.environ["COINBASE_API_KEY"]
api_secret = os.environ["COINBASE_API_SECRET"]
if "\\n" in api_secret:
    api_secret = api_secret.replace("\\n", "\n")
if not api_secret.endswith("\n"):
    api_secret = api_secret.rstrip() + "\n"

client = RESTClient(api_key=api_key, api_secret=api_secret)
resp = client.get_accounts()
accts = getattr(resp, "accounts", []) or []

def bal(cur):
    return sum(
        float(getattr(getattr(a, "available_balance", None), "value", 0) or 0)
        for a in accts
        if getattr(a, "currency", "") == cur
    )

usd = bal("USD"); usdc = bal("USDC")
print(f"USD={usd:.2f} USDC={usdc:.2f} TOTAL={usd+usdc:.2f}")
for a in accts:
    print(getattr(a, "currency", "?"), getattr(getattr(a, "available_balance", None), "value", 0))
PY
```

## Deploy on Railway (recommended)

Set variables in Railway → Variables:
- `COINBASE_API_KEY`: organizations/<ORG_ID>/apiKeys/<API_KEY_ID>
- `COINBASE_API_SECRET`: PEM private key with real newlines (no `\n` literals)

Redeploy and confirm logs show:
- `✅ Coinbase Advanced Trade connected`
- `Account balance: $<non-zero>`

Notes:
- Use only one auth method; if you set `COINBASE_API_SECRET`, leave PEM path/content vars unset.
- Never commit `.env` or credentials to git.

## Run locally

- Keep PEM secrets with real line breaks; avoid `\n` unless you replace them before constructing the client.
- Minimal shell example:

```bash
export COINBASE_API_KEY="organizations/<ORG_ID>/apiKeys/<API_KEY_ID>"
export COINBASE_API_SECRET="-----BEGIN EC PRIVATE KEY-----
...
-----END EC PRIVATE KEY-----"
python bot.py
```

## First-trade checklist
- USD/USDC funded in the default Advanced Trade portfolio for this API key.
- Balance check above returns non-zero.
- NIJA logs show non-zero trading balance and the main loop is running.
- Orders execute when signals and risk checks pass.

## Troubleshooting
- 401 Unauthorized: rotate keys; confirm org/key IDs and PEM match; keep system clock accurate.
- Zero balance: funds are not in the key’s default Advanced Trade portfolio or the key was created against a different portfolio; move funds or recreate the key while the funded portfolio is selected.
- PEM formatting: ensure real newlines; do not mix PEM env vars.
