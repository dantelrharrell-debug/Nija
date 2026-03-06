# NIJA Smart Structure Guide
**Running NIJA as a Real SaaS Platform**

---

## Overview

NIJA is designed to operate with two distinct Kraken account tiers:

```
┌─────────────────────────────────────────────────────────────────┐
│                 SMART STRUCTURE (Recommended)                    │
│                                                                 │
│   Kraken Account 1                                              │
│     Owner  : You                                                │
│     Purpose: Personal investing                                 │
│     → Connects to NIJA as a USER account                        │
│                                                                 │
│   Kraken Account 2                                              │
│     Owner  : NIJA                                               │
│     Purpose: AI trading engine                                  │
│     → Registered as the NIJA PLATFORM account                   │
│                                                                 │
│   User connection pattern:   User Kraken ──► API ──► NIJA       │
└─────────────────────────────────────────────────────────────────┘
```

### Why two accounts?

| | Account 1 (Personal) | Account 2 (NIJA) |
|---|---|---|
| **Owner** | You | NIJA |
| **Role** | User / subscriber | Platform / AI engine |
| **Capital** | Your own funds | NIJA's operating funds |
| **Trading** | Managed by NIJA AI | Managed by NIJA AI |
| **Env var** | `KRAKEN_USER_YOURNAME_*` | `KRAKEN_PLATFORM_*` |

Both accounts use the same NIJA AI strategy. The difference is that
Account 2 is NIJA's own seat at the exchange — it is the "house" account
that makes NIJA a real trading platform rather than just a script that
manages someone else's account.

---

## Step-by-Step Setup

### Step 1 — Create Kraken Account 2 (NIJA's account)

1. Go to [kraken.com](https://www.kraken.com) and create a **new** Kraken account.
   - Use an email address dedicated to NIJA (e.g. `trading@yourdomain.com`).
   - This account will belong to the NIJA platform, not to any individual user.
2. Complete KYC verification on the new account.
3. Fund the account with whatever capital NIJA will trade autonomously.

### Step 2 — Generate API keys for Account 2

1. Log in to **Account 2** (NIJA's account).
2. Navigate to **Settings → API → Generate New Key**.
3. Select **"Classic API Key"** (not OAuth or App keys).
4. Enable the following permissions — **nothing else**:
   - ✅ Query Funds
   - ✅ Query Open Orders & Trades
   - ✅ Query Closed Orders & Trades
   - ✅ Create & Modify Orders
   - ✅ Cancel/Close Orders
   - ❌ **Do NOT enable Withdraw Funds**
5. Copy the **API Key** and **API Secret**.

### Step 3 — Set the platform environment variables

In your `.env` file (or Railway/Render environment variables):

```bash
# NIJA Platform Account — Kraken Account 2 (AI trading engine)
KRAKEN_PLATFORM_API_KEY=<paste-api-key-here>
KRAKEN_PLATFORM_API_SECRET=<paste-api-secret-here>
```

### Step 4 — Connect Kraken Account 1 (your personal account)

Account 1 is your own personal Kraken account. You connect it to NIJA
by providing its API keys as a USER account.

1. Log in to **Account 1** (your personal account).
2. Generate a new API key (same permissions as above).
3. Add it to your `.env` file:

```bash
# Your personal account (Kraken Account 1) connecting to NIJA
KRAKEN_USER_YOURNAME_API_KEY=<paste-api-key-here>
KRAKEN_USER_YOURNAME_API_SECRET=<paste-api-secret-here>
```

Replace `YOURNAME` with your first name in uppercase (e.g. `JOHN`, `SARAH`).

4. Register yourself in `config/users/retail_kraken.json`:

```json
[
  {
    "user_id": "yourname",
    "name": "Your Name",
    "account_type": "retail",
    "broker_type": "kraken",
    "enabled": true,
    "independent_trading": true,
    "description": "Account 1 — personal investing via NIJA"
  }
]
```

### Step 5 — Restart NIJA

After setting the environment variables and updating the config, restart NIJA.
On startup you will see:

```
================================================================
🏦  NIJA PLATFORM ACCOUNT LAYER — Smart Structure
================================================================
  ✅  Kraken Account 2  │  Owner: NIJA  │  Purpose: AI trading engine
          Status: CONNECTED

  👥  Connected user accounts  (1/1)
      ✅  Yourname (yourname)       │  KRAKEN_USER_YOURNAME_API_KEY  │  CONNECTED

  User connection pattern:  User Kraken ──► API ──► NIJA
================================================================
```

---

## Adding More Users

Any person can connect their own Kraken account to NIJA by following
the same pattern as Step 4 above:

1. They generate a Kraken API key (read/trade — no withdrawals).
2. You add their credentials to the environment:
   ```bash
   KRAKEN_USER_JANE_API_KEY=<their-api-key>
   KRAKEN_USER_JANE_API_SECRET=<their-api-secret>
   ```
3. You add them to `config/users/retail_kraken.json`:
   ```json
   {
     "user_id": "jane_smith",
     "name": "Jane Smith",
     "account_type": "retail",
     "broker_type": "kraken",
     "enabled": true,
     "independent_trading": true
   }
   ```
4. Restart NIJA.

Each user's capital and positions are fully isolated — NIJA never mixes
funds between accounts.

---

## Environment Variables Reference

| Variable | Account | Description |
|---|---|---|
| `KRAKEN_PLATFORM_API_KEY` | Account 2 (NIJA) | NIJA's Kraken API key |
| `KRAKEN_PLATFORM_API_SECRET` | Account 2 (NIJA) | NIJA's Kraken API secret |
| `KRAKEN_USER_{FIRSTNAME}_API_KEY` | Account 1+ (users) | User's Kraken API key |
| `KRAKEN_USER_{FIRSTNAME}_API_SECRET` | Account 1+ (users) | User's Kraken API secret |

The `{FIRSTNAME}` in the environment variable name is chosen **freely by you**
when you set the variable — it just needs to be a single uppercase word
(e.g. `JOHN`, `SARAH`, `YOURNAME`).

The `user_id` field in `config/users/retail_kraken.json` is **separate** and
does not have to match the env-var name exactly, but by convention NIJA uses
the lowercase version of `{FIRSTNAME}` as the `user_id`:

| Env var prefix | Conventional `user_id` |
|---|---|
| `KRAKEN_USER_JOHN_*` | `john` or `john_smith` |
| `KRAKEN_USER_SARAH_*` | `sarah` or `sarah_jones` |
| `KRAKEN_USER_YOURNAME_*` | `yourname` |

When `bot/platform_account_layer.py` discovers user connections at startup it
reads the environment directly (scanning for `KRAKEN_USER_*_API_KEY` variables
that have a matching `_SECRET`).  The JSON config files tell NIJA **which**
users to actively trade for and with what settings.

---

## Security Notes

- **Never share** NIJA's Account 2 API keys with users.
- **Never enable** "Withdraw Funds" on any API key given to NIJA.
- API keys are stored only in environment variables — never committed to git.
- Each user's API key gives NIJA permission to trade *only* on that user's
  account; NIJA cannot move funds between accounts.
- Rotate API keys periodically (every 90 days recommended).

---

## Related Files

| File | Purpose |
|---|---|
| `bot/platform_account_layer.py` | Core platform account layer module |
| `config/users/retail_kraken.json` | Retail user registry for Kraken |
| `config/users/investor_kraken.json` | Investor user registry for Kraken |
| `.env.example` | Environment variable template |
| `PLATFORM_ACCOUNT_REQUIRED.md` | Legacy platform account documentation |
