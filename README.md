# NIJA Trading Bot 🚀

...

## Advanced Trade Portfolio Binding (Required for Live Trading)

NIJA trades from a Coinbase Advanced Trade portfolio. If your USD/USDC isn’t detected, bind the bot to the correct funded portfolio by setting `COINBASE_RETAIL_PORTFOLIO_ID`.

What this does:
- Forces NIJA to use the specified Advanced Trade portfolio UUID.
- Ensures the balance fetch uses the correct portfolio so `trading_balance` is non-zero.

How to find your portfolio UUID:
1. Open [Coinbase Advanced Portfolio](https://www.coinbase.com/advanced-portfolio) while logged in.
2. Open your browser DevTools → Network.
3. Refresh the page and find a request to `/brokerage/portfolios`.
4. In the response, locate the portfolio entry that holds your USD/USDC and copy its `id` (UUID). Example: `a3f2b6d1-9c9e-4d4b-9b92-xxxxxxxx`.

Set the environment variable:

Shell:
```bash
export COINBASE_RETAIL_PORTFOLIO_ID="a3f2b6d1-9c9e-4d4b-9b92-xxxxxxxx"
python bot.py
```

Docker run:
```bash
docker run \
  -e COINBASE_API_KEY="..." \
  -e COINBASE_API_SECRET="..." \
  -e COINBASE_RETAIL_PORTFOLIO_ID="a3f2b6d1-9c9e-4d4b-9b92-xxxxxxxx" \
  your-image:tag
```

Docker Compose (see `docker-compose.yml` in repo):
```yaml
services:
  nija:
    image: your-image:tag
    environment:
      COINBASE_API_KEY: "..."
      COINBASE_API_SECRET: "..."
      COINBASE_RETAIL_PORTFOLIO_ID: "a3f2b6d1-9c9e-4d4b-9b92-xxxxxxxx"
```

Expected log lines after a correct bind:
- `Portfolio override in use: a3f2b6d1-9c9e-4d4b-9b92-xxxxxxxx`
- Balance fetch returns non-zero USD/USDC and `trading_balance > 0`.

Troubleshooting:
- Ensure funds are in the Advanced Trade portfolio (not just regular wallet).
- Confirm funds are “Available” (not on hold).
- Verify your API key has Advanced Trade permissions.
- Use production endpoints (not sandbox) for real balances.
- Keep system clock accurate (JWT depends on time).

## Railway Deployment (Recommended)

Set variables in your Railway service → Variables:
- `COINBASE_API_KEY`: organizations/<ORG_ID>/apiKeys/<API_KEY_ID>
- `COINBASE_API_SECRET`: PEM private key with real newlines:

  -----BEGIN EC PRIVATE KEY-----
  ...
  -----END EC PRIVATE KEY-----

Save and redeploy. Verify logs:
- "✅ Coinbase Advanced Trade connected"
- "Account balance: $<non-zero>"

Notes:
- Do not set conflicting auth variables (avoid `COINBASE_PEM_CONTENT` or `COINBASE_PEM_BASE64` if using `COINBASE_API_SECRET`).
- Never commit `.env` or credentials to git.

## Local Environment Setup

If using `.env` locally:
- Ensure PEM has true line breaks (not `\n`).
- Or export in shell to avoid multiline parsing:

```bash
export COINBASE_API_KEY="organizations/<ORG_ID>/apiKeys/<API_KEY_ID>"
export COINBASE_API_SECRET="-----BEGIN EC PRIVATE KEY-----
...
-----END EC PRIVATE KEY-----"
```

## First-Trade Checklist
- Fund your Advanced Trade portfolio with USD/USDC (https://www.coinbase.com/advanced-portfolio).
- Logs show non-zero trading balance.
- Trading loop runs every ~15s with per-symbol signals.
- Orders execute on BUY/SELL signals when risk checks pass.

## Troubleshooting
- 401 Unauthorized: Rotate keys; ensure org/key IDs are correct; PEM matches key.
- Zero balance warnings: Fund Advanced Trade or set `COINBASE_RETAIL_PORTFOLIO_ID` to a funded portfolio.
- PEM formatting: Use real newlines; avoid `\n` unless your parser supports it.
- Conflicting auth: Prefer a single method (JWT key + PEM secret).
