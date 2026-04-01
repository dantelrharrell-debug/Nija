# NIJA Trading Bot — Credential Setup Guide

This guide walks you through obtaining, configuring, and validating API
credentials for every broker the NIJA bot supports.

---

## Quick-start checklist

1. [ ] Obtain API credentials from each broker you want to use (see sections below)
2. [ ] Add them to Railway → Variables (production) or `.env` (local)
3. [ ] Run `python validate_broker_credentials.py` to confirm they are valid
4. [ ] If Kraken shows nonce errors, run `python reset_kraken_nonce.py`
5. [ ] Redeploy / restart the bot

---

## Table of contents

- [Kraken (PLATFORM)](#kraken-platform)
- [Coinbase](#coinbase)
- [Alpaca](#alpaca)
- [Binance](#binance)
- [OKX](#okx)
- [Setting variables in Railway](#setting-variables-in-railway)
- [Common errors and fixes](#common-errors-and-fixes)
- [Validating credentials before deployment](#validating-credentials-before-deployment)

---

## Kraken (PLATFORM)

Kraken is the primary broker for the NIJA bot. The "PLATFORM" account is
NIJA's own Kraken account — the AI trading engine.

### How to obtain credentials

1. Log in to [kraken.com](https://www.kraken.com)
2. Go to **Settings → API → Generate New Key**
3. **Important:** Select **Classic API Key** (NOT OAuth, NOT App key)
4. Enable **all** of the following permissions:
   - ✅ Query Funds
   - ✅ Query Open Orders & Trades
   - ✅ Query Closed Orders & Trades
   - ✅ Create & Modify Orders
   - ✅ Cancel/Close Orders
   - ❌ Do **NOT** enable Withdraw Funds
5. Copy the **API Key** (56 characters) and **API Secret** (88+ characters, Base64)

### Environment variables

```
KRAKEN_PLATFORM_API_KEY=<your-56-char-api-key>
KRAKEN_PLATFORM_API_SECRET=<your-88-char-base64-secret>
```

Legacy fallback (only if the above are not set):

```
KRAKEN_API_KEY=<your-api-key>
KRAKEN_API_SECRET=<your-api-secret>
```

### User accounts (optional)

If individual users connect their own Kraken accounts:

```
KRAKEN_USER_DAIVON_API_KEY=<daivon-api-key>
KRAKEN_USER_DAIVON_API_SECRET=<daivon-api-secret>

KRAKEN_USER_TANIA_API_KEY=<tania-api-key>
KRAKEN_USER_TANIA_API_SECRET=<tania-api-secret>
```

The prefix (`DAIVON`, `TANIA`) must match the first part of the `user_id`
field in `config/users/retail_kraken.json`.

---

## Coinbase

Coinbase uses the **Coinbase Developer Platform (CDP)** Cloud API Key format.

### How to obtain credentials

1. Go to [portal.cdp.coinbase.com](https://portal.cdp.coinbase.com/)
2. Create a new **API Key** with **Trade** and **View** permissions
3. Download or copy:
   - **API Key Name** — looks like `organizations/{org_id}/apiKeys/{key_id}`
   - **API Secret** — an EC private key in PEM format

### Environment variables

```
COINBASE_API_KEY=organizations/{org_id}/apiKeys/{key_id}
COINBASE_API_SECRET=-----BEGIN EC PRIVATE KEY-----
MHQCAQEEIAbc...
-----END EC PRIVATE KEY-----
```

> **Railway tip:** When pasting a multi-line PEM key into Railway Variables,
> paste it exactly as-is with real newlines. Do **not** replace newlines with
> `\n` — that causes 401 Unauthorized errors.

### Optional variables

```
COINBASE_RETAIL_PORTFOLIO_ID=<uuid>   # Trade from a specific portfolio
ALLOW_CONSUMER_USD=false              # Include consumer USD accounts
```

---

## Alpaca

Alpaca is used for US stock trading.

### How to obtain credentials

1. Sign up at [alpaca.markets](https://alpaca.markets/)
2. Go to **Paper Trading** (for testing) or **Live Trading**
3. Generate an API key from the dashboard
4. Copy the **API Key ID** (starts with `PK` for paper, `AK` for live)
   and the **Secret Key**

### Environment variables

```
ALPACA_API_KEY=PKxxxxxxxxxxxxxxxxxxxxxxxx
ALPACA_API_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
ALPACA_PAPER=true    # Set to false for live trading
```

---

## Binance

### How to obtain credentials

1. Log in to [binance.com](https://www.binance.com)
2. Go to **Account → API Management → Create API**
3. Enable **Enable Reading** and **Enable Spot & Margin Trading**
4. Copy the **API Key** (64 characters) and **Secret Key**

### Environment variables

```
BINANCE_API_KEY=<64-char-api-key>
BINANCE_API_SECRET=<64-char-secret-key>
BINANCE_USE_TESTNET=false   # Set to true for testnet
```

---

## OKX

OKX requires three credentials: key, secret, **and** a passphrase.

### How to obtain credentials

1. Log in to [okx.com](https://www.okx.com)
2. Go to **Account → API → Create V5 API Key**
3. Set a **passphrase** (you choose this — store it securely)
4. Enable **Trade** permission
5. Copy the **API Key**, **Secret Key**, and your **Passphrase**

### Environment variables

```
OKX_API_KEY=<your-api-key>
OKX_API_SECRET=<your-secret-key>
OKX_PASSPHRASE=<your-passphrase>
OKX_USE_TESTNET=false   # Set to true for demo trading
```

---

## Setting variables in Railway

1. Open your Railway project
2. Click the service → **Variables** tab
3. Click **+ New Variable** for each credential
4. Paste the value exactly (no extra spaces or quotes)
5. Click **Deploy** to apply changes

For multi-line values (e.g., Coinbase PEM key):
- Click the variable value field
- Paste the full PEM block including `-----BEGIN` and `-----END` lines
- Railway preserves newlines in multi-line values

---

## Common errors and fixes

### `EAPI:Invalid nonce` (Kraken)

**Cause:** The nonce sent to Kraken is lower than the last nonce it accepted.
This happens after rapid restarts or when the system clock drifts backward.

**Fix:**
```bash
python reset_kraken_nonce.py
```
Then redeploy the bot. The script jumps the nonce 60 seconds forward and
resets the in-memory nonce manager.

If the error persists:
- Wait 60–90 seconds before restarting (Kraken caches nonces for ~60 s)
- Check that your system clock is synced with NTP
- Run `python reset_kraken_nonce.py --dry-run` first to preview changes

### `401 Unauthorized` (Coinbase)

**Cause:** Almost always a malformed API secret. The most common mistake is
pasting the PEM key with literal `\n` instead of real newlines.

**Fix:**
1. In Railway Variables, delete the `COINBASE_API_SECRET` variable
2. Re-paste the PEM key with **real line breaks** (not `\n`)
3. Redeploy

Run `python validate_broker_credentials.py` — it will detect the `\n` issue
and tell you exactly what to fix.

### `Permission denied` (Kraken)

**Cause:** The API key was created without the required permissions.

**Fix:**
1. Go to [kraken.com/u/security/api](https://www.kraken.com/u/security/api)
2. Edit your API key
3. Enable: Query Funds, Query Open/Closed Orders, Create & Modify Orders, Cancel Orders
4. Save and restart the bot

### Bot starts in monitor mode (no trades)

**Cause:** No broker connected successfully.

**Fix:**
1. Run `python validate_broker_credentials.py` to identify missing/invalid credentials
2. Fix the reported issues
3. Redeploy

### Balance fetch timeout (Kraken)

**Cause:** Kraken API is slow or the connection is hanging.

The bot uses a 30-second HTTP timeout on Kraken API calls. If you see
repeated timeout errors:
- Check [status.kraken.com](https://status.kraken.com) for outages
- The bot will retry automatically with exponential backoff

---

## Validating credentials before deployment

Run the credential validator locally or in a Railway one-off command:

```bash
# Basic validation (format checks only — no network calls)
python validate_broker_credentials.py

# Full validation including network connectivity tests
python validate_broker_credentials.py --test-connections
```

The validator checks:
- All required variables are present and non-empty
- No placeholder values (`your_api_key`, `changeme`, etc.)
- Coinbase PEM key has real newlines (not `\n`)
- Kraken nonce manager is healthy and monotonically increasing
- (with `--test-connections`) Kraken and Coinbase APIs are reachable
- (with `--test-connections`) System clock drift vs Kraken server time

Exit code `0` means all configured brokers passed. Exit code `1` means
errors were found — fix them before deploying.

---

## Security best practices

- **Never commit credentials** to git. The `.env` file is in `.gitignore`.
- **Use Railway Variables** for production — never hardcode secrets.
- **Rotate API keys** periodically and after any suspected compromise.
- **Limit permissions** — never enable "Withdraw Funds" on Kraken.
- **Use separate keys** for different environments (dev vs production).
- **Enable 2FA** on all broker accounts.

---

## Related files

| File | Purpose |
|------|---------|
| `validate_broker_credentials.py` | Pre-deployment credential validator |
| `reset_kraken_nonce.py` | Kraken nonce reset utility |
| `API_CREDENTIALS_GUIDE.md` | Detailed credential management guide |
| `.env.example` | Template for all environment variables |
| `diagnose_kraken_trading.py` | Full Kraken trading diagnostic |
