# Deploy checklist

Required environment variables:
- LIVE_TRADING (0 or 1). Default 0.
- If LIVE_TRADING=1:
  - COINBASE_API_KEY
  - COINBASE_API_SECRET
  - COINBASE_API_SUB

Optional for webhook signing:
- TV_WEBHOOK_SECRET

Docker / build:
- Ensure bot/pyproject.toml is present
- .dockerignore must not exclude bot/pyproject.toml

CI:
- Set secrets.TV_WEBHOOK_SECRET in GitHub Actions if you want signature tests to run
