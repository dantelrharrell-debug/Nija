# Deployment & Safety Guide

This document explains how to deploy and validate the application safely (Railway or local). DO NOT put secrets in the repo. Use Railway environment variables or a local .env file only for local testing.

## Overview of changes in this branch
- Added a defensive Coinbase adapter and safer client wiring.
- Added place_order_safe.py (requires MODE=LIVE and `--confirm` to place orders).
- Added constraints.txt and Dockerfile uses it during pip install to avoid resolver conflicts.
- nija_client now logs adapter detection and verifies accounts before claiming success.

---

## Set environment variables (Railway / cloud)

In Railway set the following environment variables (use the Railway UI secrets fields). Replace PLACEHOLDER tokens with actual values only in Railway's secret fields — do NOT commit secrets to Git.

- MODE = PLACEHOLDER (start with DRY_RUN)
- COINBASE_API_KEY = PLACEHOLDER
- COINBASE_API_SECRET = PLACEHOLDER
- COINBASE_API_PASSPHRASE = PLACEHOLDER (optional)
- COINBASE_PEM_CONTENT = PLACEHOLDER (optional, for JWT PEM content)
- COINBASE_ORG_ID = PLACEHOLDER (optional)
- COINBASE_BASE_URL = https://api.coinbase.com
- TRADINGVIEW_WEBHOOK_SECRET = PLACEHOLDER

Notes:
- For Coinbase Advanced / ES256 you may need to set COINBASE_PEM_CONTENT with your private key PEM content and COINBASE_ORG_ID if required by your enterprise config.
- Keep MODE=DRY_RUN while testing.

---

## Why constraints.txt is used

A constraints file (constraints.txt) pins a small set of packages to known-compatible wheel versions. This avoids long pip resolver backtracking and dependency conflicts during Docker builds. Dockerfile uses `pip install -r ... -c constraints.txt` so runtime requirements respect these pins.

If you need to update packages, update constraints.txt with care.

---

## Build & Deploy (Railway)

1. Push branch `fix/coinbase-adapter` to GitHub.
2. In Railway, point the service to build from that branch.
3. Set environment variables (see above). Start with MODE=DRY_RUN.
4. Deploy & watch build logs. Dockerfile uses constraints.txt.
5. If build fails on a package that requires system deps, ensure Dockerfile has required apt packages (already included).

---

## Safe verification (One‑off)

Run the following safe, read-only probe (Railway one-off or local with env vars). This does not place orders:

```bash
python - <<'PY'
from nija_client import CoinbaseClient
c = CoinbaseClient()
print("adapter_present:", bool(c.adapter))
print("adapter_client_name:", getattr(c.adapter, "client_name", None))
accounts = c.fetch_accounts()
print("accounts_count:", len(accounts))
print("open_orders_sample:", c.fetch_open_orders()[:10])
print("recent_fills_sample:", c.fetch_fills()[:10])
print("is_connected:", c.is_connected())
PY
```

Expected:
- `adapter_client_name` shows the client used (or "none").
- `accounts_count` should reflect the accounts visible to the key.
- While MODE=DRY_RUN, even if accounts are present, no trades should be placed.

---

## Testing a market order (DRY_RUN then LIVE)

1. Keep MODE=DRY_RUN and verify the probe shows your accounts but no orders executed.
2. To test the order script (local or Railway one-off) without placing orders:
   - Example (dry run): `MODE=DRY_RUN python place_order_safe.py --product_id BTC-USD --side buy --size 0.001`
   - The script should refuse to place the order and print diagnostics.

3. When you are ready to place a very small live order:
   - Rotate keys and webhook secret first as a safety precaution.
   - Set MODE=LIVE in Railway env.
   - Ensure TRADINGVIEW_WEBHOOK_SECRET has been rotated.
   - Run place_order_safe with `--confirm`:
     - `MODE=LIVE python place_order_safe.py --product_id BTC-USD --side buy --size 0.0001 --confirm`
   - Monitor logs and Coinbase activity immediately.

---

## Go-live checklist

1. Tests passed with MODE=DRY_RUN.
2. Verified probe shows accounts_count > 0 when expected.
3. Tracked and rotated TRADINGVIEW_WEBHOOK_SECRET.
4. Limit API key permissions (no withdrawal key).
5. Have a revoke plan: know how to delete the API key in Coinbase dashboard.
6. Enable MODE=LIVE only when ready and monitor logs for 1–2 hours.

---

## Coinbase Advanced / client notes & installation

- If you use Coinbase Advanced (enterprise), install the official client if available (may be a GitHub package). Example:
  - `pip install git+https://github.com/coinbase/coinbase-advanced-py.git` (replace with the correct repo URL if necessary).
- If coinbase_advanced is present, the adapter will prefer it.
- If you prefer the community `cbpro` client, be aware of possible dependency conflicts. This repository recommends using a single official client (coinbase or coinbase_advanced) to avoid resolver issues.

---

## Safety reminder

Never paste secrets into source files or PRs. Use Railway project secrets or a local `.env` file that is excluded from source control.
