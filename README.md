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
