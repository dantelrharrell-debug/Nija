# Railway Kraken Setup Guide

This guide explains how to configure NIJA to trade on Kraken for both the master account and user accounts when deployed on Railway.

## Overview

NIJA supports multi-account trading on Kraken:
- **Master Account**: The NIJA system's primary trading account
- **User Accounts**: Individual retail/investor accounts that trade independently

Both master and user accounts can trade simultaneously on Kraken with completely isolated balances and positions.

## Prerequisites

1. Kraken account(s) with API access enabled
2. Railway project with NIJA deployed
3. API credentials from Kraken for each account

## Step 1: Generate Kraken API Credentials

### For Master Account:

1. Log into your Kraken account at https://www.kraken.com
2. Navigate to: **Settings** → **API** → **Generate New Key**
3. Set permissions:
   - ✅ Query Funds
   - ✅ Query Open Orders & Trades
   - ✅ Query Closed Orders & Trades
   - ✅ Create & Modify Orders
   - ✅ Cancel/Close Orders
4. Click **Generate Key**
5. **IMPORTANT**: Save both the API Key and Private Key immediately (you won't be able to see the private key again)

### For User Accounts (Daivon, Tania, etc.):

Repeat the above process for each user account, logging into each user's individual Kraken account.

## Step 2: Configure User Accounts in NIJA

User accounts are configured in JSON files. For Kraken users, edit:

**File**: `config/users/retail_kraken.json`

```json
[
  {
    "user_id": "daivon_frazier",
    "name": "Daivon Frazier",
    "account_type": "retail",
    "broker_type": "kraken",
    "enabled": true,
    "description": "Retail user - Kraken crypto account"
  },
  {
    "user_id": "tania_gilbert",
    "name": "Tania Gilbert",
    "account_type": "retail",
    "broker_type": "kraken",
    "enabled": true,
    "description": "Retail user - Kraken crypto account"
  }
]
```

**Note**: The `user_id` field is critical - it determines the environment variable names.

## Step 3: Set Environment Variables in Railway

### Navigate to Railway Dashboard:

1. Go to https://railway.app
2. Select your NIJA project
3. Click on your service
4. Go to the **Variables** tab

### Add Master Account Credentials:

Add these environment variables with your actual Kraken API credentials:

```bash
# Master Account (NIJA System)
KRAKEN_API_KEY=your-master-api-key-here
KRAKEN_API_SECRET=your-master-api-secret-here
```

**Alternative format** (new style - both work):
```bash
KRAKEN_MASTER_API_KEY=your-master-api-key-here
KRAKEN_MASTER_API_SECRET=your-master-api-secret-here
```

### Add User Account Credentials:

For each user, add credentials following this pattern:

```bash
# User: Daivon Frazier (user_id: daivon_frazier)
KRAKEN_USER_DAIVON_API_KEY=daivon-api-key-here
KRAKEN_USER_DAIVON_API_SECRET=daivon-api-secret-here

# User: Tania Gilbert (user_id: tania_gilbert)
KRAKEN_USER_TANIA_API_KEY=tania-api-key-here
KRAKEN_USER_TANIA_API_SECRET=tania-api-secret-here
```

**Pattern**: `KRAKEN_USER_{FIRSTNAME}_API_KEY` where `{FIRSTNAME}` is the part before the underscore in `user_id`, converted to UPPERCASE.

### Add Additional Configuration:

```bash
# Trading Configuration
LIVE_TRADING=1
DEFAULT_TRADE_PERCENT=0.02
MIN_TRADE_PERCENT=0.02
MAX_TRADE_PERCENT=0.10
MAX_CONCURRENT_POSITIONS=7
MIN_CASH_TO_BUY=5.50
MINIMUM_TRADING_BALANCE=25.0
REENTRY_COOLDOWN_MINUTES=120
MAX_RETRIES=5
RETRY_DELAY=5

# Optional: Allow Consumer USD (if you have retail Coinbase account)
ALLOW_CONSUMER_USD=True
```

## Step 4: Restart Deployment

After adding all environment variables:

1. In Railway dashboard, click the **three dots** (⋯) menu
2. Select **Restart Deployment**
3. Wait for the deployment to complete

## Step 5: Verify Connection

Check the deployment logs to verify successful connection:

```
✅ Kraken Master credentials detected
✅ Kraken User #1 (Daivon) credentials detected
✅ Kraken User #2 (Tania) credentials detected
...
✅ Kraken MASTER connected
✅ Kraken registered as MASTER broker in multi-account manager
...
✅ User broker added: daivon_frazier -> kraken
✅ User broker added: tania_gilbert -> kraken
```

## Multi-Exchange Support

NIJA can trade on multiple exchanges simultaneously. If you also want to enable:

### Coinbase (Crypto):
```bash
COINBASE_API_KEY=organizations/your-org-id/apiKeys/your-key-id
COINBASE_API_SECRET="-----BEGIN EC PRIVATE KEY-----
your-private-key-here
-----END EC PRIVATE KEY-----"
```

### Alpaca (Stocks - for users):
```bash
ALPACA_USER_TANIA_API_KEY=tania-alpaca-key
ALPACA_USER_TANIA_API_SECRET=tania-alpaca-secret
ALPACA_USER_TANIA_PAPER=true  # false for live trading
```

## Troubleshooting

### "Kraken credentials not configured"

**Solution**: Check that environment variable names exactly match the pattern:
- Master: `KRAKEN_MASTER_API_KEY` or `KRAKEN_API_KEY`
- Users: `KRAKEN_USER_{FIRSTNAME}_API_KEY`

The `{FIRSTNAME}` must be the part before the first underscore in the `user_id`, in UPPERCASE.

### "Permission error" or "Invalid API key"

**Solution**: 
1. Verify API permissions in Kraken dashboard include trading permissions
2. Make sure you copied the complete API secret (they're very long)
3. Check for extra spaces or line breaks in the secret

### "Invalid nonce" errors

This is usually temporary. The bot has built-in retry logic. If it persists:
1. Restart the deployment
2. Ensure only one instance of the bot is running per API key

### User not connecting

**Checklist**:
1. Is the user `"enabled": true` in the JSON config file?
2. Does the environment variable name match the user_id? (e.g., `daivon_frazier` → `KRAKEN_USER_DAIVON_*`)
3. Are both API_KEY and API_SECRET set?
4. Did you restart the deployment after adding the credentials?

## Account Isolation

**IMPORTANT**: Master and user accounts are completely independent:
- Each account has its own balance
- Each account trades independently
- Master account balance does NOT include user balances
- Users cannot affect master's trading capital

This is intentional and by design for proper fund segregation.

## Support

For additional help:
- Check `MULTI_EXCHANGE_TRADING_GUIDE.md` for multi-exchange setup
- See `USER_SETUP_GUIDE.md` for detailed user account configuration
- Review `KRAKEN_SETUP_GUIDE.md` for Kraken-specific information

## Example: Complete Railway Environment Variables

Here's what a complete Railway environment configuration looks like:

```bash
# Master Kraken
KRAKEN_API_KEY=8zdYy7PMRjnyDraiJUtrAb3wmu8MFxKBON3nrTkjkwnJ9iIUQyKNGKP7
KRAKEN_API_SECRET=e2xaakHliGa5RwH7uXwuq6RLGospWaQhScaVJfsS6wIa9huHxmx+HgeQCax8A+gvqV3P9jXD9YbR3wtsipdpRA==

# User: Daivon
KRAKEN_USER_DAIVON_API_KEY=HSo/f1zjeQALCM/rri9bjTB5JisQ/SPgurCRTx8W7kLD7psjcv2PXEf+
KRAKEN_USER_DAIVON_API_SECRET=6WOxnBLq+r4ln2Zz7nT0Nvv8CMkaolHtjYdOgTm7NWIq/mJqV8KbDA2XaThP65bHK9QvpEabRr1u38FrBJntaQ==

# User: Tania (Kraken)
KRAKEN_USER_TANIA_API_KEY=XEB37FsbsQ2Wj/bknOy6HPZTFqs25nyU10M2oxF/ja//Yh/r2kSRCAp/
KRAKEN_USER_TANIA_API_SECRET=iINPAKFyVe9rTfYCKnauFCpOfqdsm9+lBFxzx2KLFkArjStbjAQ9Rr+FuA5lZgnzpZ85wMwnzKpkO07iHmMLmw==

# User: Tania (Alpaca - optional)
ALPACA_USER_TANIA_API_KEY=AKG546YWGRDFHUHOOOXZXUCDV5
ALPACA_USER_TANIA_API_SECRET=Fss3zVU5yme6V96X833rsJe4aD3j2fY9TmGZC7UTMfb6
ALPACA_USER_TANIA_PAPER=true

# Coinbase (optional)
COINBASE_API_KEY=organizations/ce77e4ea-ecca-42ec-912a-b6b4455ab9d0/apiKeys/05067708-2a5d-43a5-a4c6-732176c05e7c
COINBASE_API_SECRET="-----BEGIN EC PRIVATE KEY-----
MHcCAQEEIIpbqWDgEUayl0/GuwoWe04zjdwyliPABAzHTRlzhJbFoAoGCCqGSM49
AwEHoUQDQgAEqoQqw6ZbWDfB1ElbpHfYAJCBof7ala7v5e3TqqiWiYqtprUajjD+
mqoVbKN6pqHMcnFwC86rM/jRId+1rgf31A==
-----END EC PRIVATE KEY-----"

# Trading config
LIVE_TRADING=1
DEFAULT_TRADE_PERCENT=0.02
MAX_CONCURRENT_POSITIONS=7
MIN_CASH_TO_BUY=5.50
MINIMUM_TRADING_BALANCE=25.0
ALLOW_CONSUMER_USD=True
```

✅ After setting these variables and restarting, NIJA will trade on Kraken for master and all configured users!
