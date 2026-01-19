# User Setup Guide - Adding New Users to NIJA Bot

This guide explains how to add new user accounts to the NIJA trading bot without modifying code.

## Overview

The NIJA bot now supports multiple user accounts across different brokerages using a **configuration file-based system**. Each brokerage (Kraken, Alpaca, Coinbase) has its own user configuration file where you can add, enable, or disable users simply by editing JSON files.

**Key Benefits:**
- ✅ No code changes required to add new users
- ✅ Each brokerage has its own dedicated user file
- ✅ Easy to enable/disable users without removing credentials
- ✅ All users trade independently with their own API credentials
- ✅ Master account and user accounts are completely separate

## Quick Start

### Adding a New User in 3 Steps

1. **Edit the appropriate brokerage user file** (e.g., `config/users/kraken_users.json`)
2. **Add environment variables** with the user's API credentials
3. **Restart the bot** - the new user will be automatically detected and connected

That's it! No code changes needed.

## File Structure

User configurations are stored in:
```
config/
  └── users/
      ├── README.md              # Detailed documentation
      ├── kraken_users.json      # Kraken user accounts
      ├── alpaca_users.json      # Alpaca user accounts (stocks)
      └── coinbase_users.json    # Coinbase user accounts (future)
```

## Detailed Step-by-Step Guide

### Step 1: Choose the Brokerage

Determine which brokerage the new user will trade on:
- **Kraken** - Cryptocurrency trading (BTC, ETH, etc.)
- **Alpaca** - Stock trading (US equities)
- **Coinbase** - Cryptocurrency trading (future support)

### Step 2: Edit the User Configuration File

Navigate to `config/users/` and edit the appropriate file.

**Example: Adding a user to Kraken**

Edit `config/users/kraken_users.json`:

```json
[
  {
    "user_id": "daivon_frazier",
    "name": "Daivon Frazier",
    "broker_type": "kraken",
    "enabled": true,
    "description": "User #1 - Kraken account"
  },
  {
    "user_id": "tania_gilbert",
    "name": "Tania Gilbert",
    "broker_type": "kraken",
    "enabled": true,
    "description": "User #2 - Kraken account"
  },
  {
    "user_id": "jane_smith",
    "name": "Jane Smith",
    "broker_type": "kraken",
    "enabled": true,
    "description": "New user added on 2026-01-12"
  }
]
```

**Field Descriptions:**

| Field | Required | Description | Example |
|-------|----------|-------------|---------|
| `user_id` | ✅ | Unique identifier (lowercase, underscores) | `"jane_smith"` |
| `name` | ✅ | Display name for logging | `"Jane Smith"` |
| `broker_type` | ✅ | Brokerage name (must match file) | `"kraken"` |
| `enabled` | ✅ | Whether to activate this account | `true` or `false` |
| `description` | ⚪ | Optional notes | `"Added 2026-01-12"` |

**Important Rules:**
- `user_id` must be lowercase with underscores (no spaces)
- `user_id` format: `firstname_lastname` or just `firstname`
- `broker_type` must match the filename (e.g., "kraken" for kraken_users.json)
- Each `user_id` must be unique across all brokerage files

### Step 3: Set Environment Variables

The bot needs API credentials for each user. These are stored as environment variables.

**Environment Variable Naming Convention:**

```
{BROKER}_USER_{FIRSTNAME}_API_KEY
{BROKER}_USER_{FIRSTNAME}_API_SECRET
```

The `{FIRSTNAME}` is extracted from the `user_id` (the part before the first underscore, in UPPERCASE).

**Examples:**

For `user_id: "jane_smith"` on Kraken:
```bash
KRAKEN_USER_JANE_API_KEY=your_api_key_here
KRAKEN_USER_JANE_API_SECRET=your_api_secret_here
```

For `user_id: "john"` on Alpaca:
```bash
ALPACA_USER_JOHN_API_KEY=your_api_key_here
ALPACA_USER_JOHN_API_SECRET=your_api_secret_here
ALPACA_USER_JOHN_PAPER=true  # true for paper trading, false for live
```

### Step 4: Add Credentials to .env File

Edit your `.env` file and add the user's credentials:

```bash
# Existing credentials...

# New user: Jane Smith on Kraken
KRAKEN_USER_JANE_API_KEY=abcdef123456
KRAKEN_USER_JANE_API_SECRET=xyz789secretkey
```

**⚠️ Security Warning:**
- Never commit your `.env` file to version control
- Keep API keys secure and private
- Use API key restrictions when available (IP whitelisting, permissions)

### Step 5: Restart the Bot

The bot automatically loads user configurations at startup:

```bash
# If running locally
./start.sh

# If using Docker (local development)
docker build -t nija-bot . && docker run --env-file .env nija-bot

# If deployed on Railway/Render
# Trigger a new deployment or restart the service
```

### Step 6: Verify Connection

Check the bot logs for successful connection:

```
📂 LOADING USER CONFIGURATIONS
==================================================
   ✅ enabled: Jane Smith (jane_smith)
==================================================
✅ Loaded 3 total user(s) from 1 brokerage(s)
   • KRAKEN: 3/3 enabled
==================================================

👤 CONNECTING USERS FROM CONFIG FILES
==================================================
📊 Connecting Jane Smith (jane_smith) to Kraken...
   ✅ Jane Smith connected to Kraken
   💰 Jane Smith balance: $1,234.56
==================================================
✅ Connected 3 user(s) across 1 brokerage(s)
   • KRAKEN: 3 user(s)
==================================================

📊 ACCOUNT TRADING STATUS SUMMARY
==================================================
✅ MASTER ACCOUNT: TRADING (Broker: coinbase)
✅ USER: Daivon Frazier: TRADING (Broker: Kraken)
✅ USER: Tania Gilbert: TRADING (Broker: Kraken)
✅ USER: Jane Smith: TRADING (Broker: Kraken)
==================================================
```

## Common Scenarios

### Scenario 1: Temporarily Disable a User

Set `"enabled": false` in the user config file:

```json
{
  "user_id": "jane_smith",
  "name": "Jane Smith",
  "broker_type": "kraken",
  "enabled": false,  // Changed from true to false
  "description": "Temporarily disabled for account maintenance"
}
```

Restart the bot. The user will be skipped during connection.

**Note:** You can leave the environment variables in place. They won't be used while the user is disabled.

### Scenario 2: User on Multiple Brokerages

If a user has accounts on multiple brokerages, add them to each brokerage file:

**kraken_users.json:**
```json
{
  "user_id": "tania_gilbert",
  "name": "Tania Gilbert",
  "broker_type": "kraken",
  "enabled": true,
  "description": "Tania's crypto account"
}
```

**alpaca_users.json:**
```json
{
  "user_id": "tania_gilbert",
  "name": "Tania Gilbert",
  "broker_type": "alpaca",
  "enabled": true,
  "description": "Tania's stock account"
}
```

Then add credentials for both:
```bash
# Kraken credentials
KRAKEN_USER_TANIA_API_KEY=...
KRAKEN_USER_TANIA_API_SECRET=...

# Alpaca credentials
ALPACA_USER_TANIA_API_KEY=...
ALPACA_USER_TANIA_API_SECRET=...
ALPACA_USER_TANIA_PAPER=true
```

### Scenario 3: Removing a User

1. Set `"enabled": false` in the config file
2. Restart the bot
3. (Optional) Remove the user's credentials from `.env`
4. (Optional) Remove the user entry from the JSON file

## Brokerage-Specific Instructions

### Kraken Users

**Required Fields:**
- `KRAKEN_USER_{FIRSTNAME}_API_KEY`
- `KRAKEN_USER_{FIRSTNAME}_API_SECRET`

**Getting Kraken API Keys:**
1. Log in to https://www.kraken.com/
2. Go to Settings > API
3. Create a new API key with permissions:
   - ✅ Query Funds
   - ✅ Query Open Orders & Trades
   - ✅ Create & Modify Orders
   - ✅ Cancel/Close Orders
4. Copy the API key and private key
5. Add to `.env` file

**Example:**
```bash
KRAKEN_USER_JANE_API_KEY=abcd1234...
KRAKEN_USER_JANE_API_SECRET=xyz789/secret...
```

### Alpaca Users

**Required Fields:**
- `ALPACA_USER_{FIRSTNAME}_API_KEY`
- `ALPACA_USER_{FIRSTNAME}_API_SECRET`
- `ALPACA_USER_{FIRSTNAME}_PAPER` (true or false)

**Getting Alpaca API Keys:**
1. Log in to https://alpaca.markets/
2. Go to Your Apps > Paper Trading or Live Trading
3. Generate API keys
4. Add to `.env` file

**Example:**
```bash
ALPACA_USER_JANE_API_KEY=PKXXXXXX
ALPACA_USER_JANE_API_SECRET=xxxxxxxx
ALPACA_USER_JANE_PAPER=true  # Use true for paper trading
```

**Note:** Set `PAPER=false` only when you're ready for live trading with real money.

### Coinbase Users (Future)

Coinbase user accounts are not yet fully implemented but the configuration structure is ready:

```json
{
  "user_id": "jane_smith",
  "name": "Jane Smith",
  "broker_type": "coinbase",
  "enabled": false,
  "description": "Coinbase support coming soon"
}
```

## Troubleshooting

### Problem: User shows "NOT TRADING (Connection failed or not configured)"

**Possible Causes:**
1. User is disabled in config file (`"enabled": false`)
2. Environment variables are not set correctly
3. API credentials are invalid
4. Bot hasn't been restarted after changes

**Solution:**
1. Check config file: ensure `"enabled": true`
2. Check `.env` file: verify environment variable names match pattern
3. Check API keys: ensure they're valid and have correct permissions
4. Restart the bot

### Problem: "Invalid user_id format" error

**Cause:** user_id contains invalid characters

**Solution:** 
- Use only lowercase letters, numbers, and underscores
- Format: `firstname_lastname` or `firstname`
- Examples: ✅ `jane_smith`, `john_doe`, `alice`
- Invalid: ❌ `Jane Smith`, `jane-smith`, `jane.smith`

### Problem: Environment variables not found

**Cause:** Variable name doesn't match expected pattern

**Solution:**
- Check the exact pattern: `{BROKER}_USER_{FIRSTNAME}_*`
- BROKER must be UPPERCASE: `KRAKEN`, `ALPACA`, `COINBASE`
- FIRSTNAME is extracted from user_id and must be UPPERCASE
- Example: `user_id: "jane_smith"` → `KRAKEN_USER_JANE_API_KEY`

### Problem: User connected but shows $0.00 balance

**Possible Causes:**
1. API keys have read-only permissions
2. Account actually has no funds
3. API connection issue

**Solution:**
1. Check API key permissions (should allow querying funds)
2. Verify account has funds on the exchange
3. Check bot logs for specific error messages

### Problem: Bot doesn't detect new user after adding to config

**Cause:** Bot hasn't been restarted

**Solution:** Restart the bot. Config files are loaded at startup, not dynamically.

## Environment Variable Reference

### Master Account (NIJA System)

```bash
# Kraken Master
KRAKEN_MASTER_API_KEY=...
KRAKEN_MASTER_API_SECRET=...

# Alpaca Master
ALPACA_API_KEY=...
ALPACA_API_SECRET=...
ALPACA_PAPER=true

# Coinbase Master
COINBASE_ORG_ID=...
COINBASE_JWT_PEM=...
COINBASE_JWT_KID=...
COINBASE_JWT_ISSUER=...
```

### User Accounts

```bash
# Kraken Users
KRAKEN_USER_{FIRSTNAME}_API_KEY=...
KRAKEN_USER_{FIRSTNAME}_API_SECRET=...

# Alpaca Users
ALPACA_USER_{FIRSTNAME}_API_KEY=...
ALPACA_USER_{FIRSTNAME}_API_SECRET=...
ALPACA_USER_{FIRSTNAME}_PAPER=true

# Coinbase Users (future)
COINBASE_USER_{FIRSTNAME}_API_KEY=...
COINBASE_USER_{FIRSTNAME}_API_SECRET=...
```

## Best Practices

1. **Use Descriptive user_ids**: `firstname_lastname` format is clearest
2. **Add Descriptions**: Note when and why users were added
3. **Enable Selectively**: Only enable accounts that are funded and ready
4. **Test First**: Use paper trading (Alpaca) or small balances to test
5. **Monitor Logs**: Check startup logs to verify connections
6. **Secure Credentials**: Never share or commit `.env` files
7. **Document Changes**: Update descriptions when modifying user configs

## Architecture Notes

### How It Works

1. **Startup**: Bot loads `config/users/*.json` files
2. **Validation**: Each user config is validated
3. **Connection**: For each enabled user, bot:
   - Reads environment variables for credentials
   - Creates a broker connection
   - Verifies account balance
   - Registers user for independent trading
4. **Trading**: Each user trades independently on their brokerage
5. **Monitoring**: All user accounts are monitored separately

### Independent Trading

- Each user broker runs in its own thread
- Users are completely isolated from each other
- Failures in one user account don't affect others
- Master account and user accounts are independent

### File Organization

```
config/users/
  ├── kraken_users.json    → Kraken crypto trading accounts
  ├── alpaca_users.json    → Alpaca stock trading accounts
  └── coinbase_users.json  → Coinbase crypto accounts (future)
```

Each file is independent and can be edited separately.

## Additional Resources

- **User Config Schema**: See `config/users/README.md`
- **Multi-Exchange Guide**: See `MULTI_EXCHANGE_TRADING_GUIDE.md`
- **Environment Setup**: See `.env.example`
- **Kraken Setup**: See `KRAKEN_SETUP_GUIDE.md`

## Support

If you encounter issues:

1. Check the troubleshooting section above
2. Review bot startup logs for specific error messages
3. Verify your config files are valid JSON
4. Ensure environment variables are set correctly
5. Check that API credentials have appropriate permissions

For additional help, review the detailed documentation in `config/users/README.md`.
