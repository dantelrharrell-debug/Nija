# Quick Start: Multi-Exchange Trading for Nija

## Overview

**Good news!** The multi-exchange trading system is **already implemented and ready to use**. 

Your request to "connect users to their funded Kraken and Alpaca accounts" and "enable Nija to trade on these exchanges" is **already built**. You just need to configure the credentials.

## Current Status

✅ **INFRASTRUCTURE: COMPLETE**
- Kraken integration (master + user accounts)
- Alpaca integration (master + user accounts)  
- Multi-account broker manager
- Independent trading threads
- User configuration system
- All required SDKs installed

✅ **USER CONFIGURATIONS: READY**
- Daivon Frazier → Kraken (config/users/retail_kraken.json)
- Tania Gilbert → Kraken (config/users/retail_kraken.json)
- Tania Gilbert → Alpaca (config/users/retail_alpaca.json)

❌ **MISSING: API CREDENTIALS ONLY**

## What Happens When You Start the Bot

1. **Connects Master Account (Nija)**: 
   - Tries to connect to Coinbase (primary)
   - Optionally connects to Kraken, Alpaca, OKX, Binance
   - Uses master account credentials

2. **Connects User Accounts**:
   - Loads user configs from config/users/*.json
   - Connects each user to their configured exchange
   - Uses user-specific credentials (KRAKEN_USER_*, ALPACA_USER_*)

3. **Starts Independent Trading**:
   - Each account gets its own trading thread
   - Failures in one account don't affect others
   - All accounts trade the APEX v7.1 strategy

## Setup Steps

### 1. Set Environment Variables

Add these to your `.env` file or deployment platform (Railway/Render):

```bash
# ============================================================================
# MASTER ACCOUNT (Nija System)
# ============================================================================

# Coinbase (Primary - Required for master trading)
COINBASE_API_KEY=organizations/your-org-id/apiKeys/your-key-id
COINBASE_API_SECRET="-----BEGIN EC PRIVATE KEY-----
YOUR_PRIVATE_KEY_HERE
-----END EC PRIVATE KEY-----"

# Kraken Master (Optional - for multi-exchange diversification)
KRAKEN_MASTER_API_KEY=your_kraken_api_key
KRAKEN_MASTER_API_SECRET=your_kraken_api_secret

# Alpaca Master (Optional - for stock trading)
ALPACA_API_KEY=your_alpaca_api_key
ALPACA_API_SECRET=your_alpaca_api_secret
ALPACA_PAPER=true  # Set to false for live trading

# ============================================================================
# USER ACCOUNTS (Individual Traders)
# ============================================================================

# Daivon Frazier → Kraken
KRAKEN_USER_DAIVON_API_KEY=daivon_kraken_api_key
KRAKEN_USER_DAIVON_API_SECRET=daivon_kraken_api_secret

# Tania Gilbert → Kraken
KRAKEN_USER_TANIA_API_KEY=tania_kraken_api_key
KRAKEN_USER_TANIA_API_SECRET=tania_kraken_api_secret

# Tania Gilbert → Alpaca
ALPACA_USER_TANIA_API_KEY=tania_alpaca_api_key
ALPACA_USER_TANIA_API_SECRET=tania_alpaca_api_secret
ALPACA_USER_TANIA_PAPER=true  # Set to false for live trading
```

### 2. Get API Credentials

#### For Coinbase (Master Account):
1. Go to https://portal.cdp.coinbase.com/
2. Create new API key
3. Enable "Trade" permissions
4. Copy the API key and private key
5. Add to .env file

#### For Kraken (Master + Users):
1. Go to https://www.kraken.com/u/security/api
2. Create new API key with these permissions:
   - ✅ Query Funds
   - ✅ Query Open Orders & Trades
   - ✅ Query Closed Orders & Trades
   - ✅ Create & Modify Orders
   - ✅ Cancel/Close Orders
3. Copy API Key and Private Key
4. Add to .env file

**For user accounts**: Create separate API keys for each user on their Kraken account.

#### For Alpaca (Master + Users):
1. Go to https://alpaca.markets/
2. Sign up or log in
3. Generate API keys (Paper Trading or Live)
4. Copy API Key and Secret Key
5. Add to .env file

**For user accounts**: Each user needs their own Alpaca account with separate API keys.

### 3. Verify Configuration

Run the verification script:

```bash
python3 verify_multi_exchange_status.py
```

This will show:
- ✅ Which exchanges are configured
- ✅ Which user accounts are configured
- ❌ What's missing
- 🎯 Trading readiness assessment

### 4. Start Trading

```bash
./start.sh
```

The bot will:
1. Check all credentials at startup
2. Connect to each configured exchange
3. Load user configurations
4. Start independent trading threads
5. Report which accounts are active

## How It Works

### Master Account Trading

**Nija (Master)** trades like this:
- Connects to Coinbase (and optionally Kraken, Alpaca, etc.)
- Uses master account credentials
- Trades APEX v7.1 strategy
- Has its own balance and positions
- **Completely independent from user accounts**

### User Account Trading

**Each User** trades like this:
- Has their own API credentials (set via environment variables)
- Configured in config/users/*.json
- Runs in independent thread
- Has separate balance and positions
- **Completely independent from master and other users**

### Example Execution Flow

When you start the bot with all credentials configured:

```
🚀 STARTING NIJA TRADING BOT
================================
✅ Connecting Coinbase (Master)...
   Balance: $1,000.00
   
✅ Connecting Kraken (Master)...
   Balance: $500.00
   
✅ Connecting User: Daivon Frazier → Kraken...
   Balance: $250.00
   
✅ Connecting User: Tania Gilbert → Kraken...
   Balance: $300.00
   
✅ Connecting User: Tania Gilbert → Alpaca...
   Balance: $400.00

🔷 MASTER ACCOUNT TRADING
   • Coinbase: $1,000.00
   • Kraken: $500.00
   Total: $1,500.00

👤 USER ACCOUNT TRADING  
   • Daivon Frazier (Kraken): $250.00
   • Tania Gilbert (Kraken): $300.00
   • Tania Gilbert (Alpaca): $400.00
   Total: $950.00

🚀 Starting 5 independent trading threads...
✅ Thread 1: Coinbase (Master)
✅ Thread 2: Kraken (Master)
✅ Thread 3: Daivon → Kraken
✅ Thread 4: Tania → Kraken
✅ Thread 5: Tania → Alpaca

🔄 Trading active on all funded accounts
```

## Account Independence

**CRITICAL**: Each account is completely independent:

- ✅ Master balance ≠ User balances
- ✅ Master positions ≠ User positions
- ✅ Master trades independently from users
- ✅ Users trade independently from master and each other
- ✅ Failures in one account don't affect others

## Monitoring

The bot logs trading activity for each account:

```
🔄 Coinbase (Master) - Cycle #42
   Scanning markets...
   Signal: BUY BTC-USD
   ✅ Order placed: $100.00

🔄 Daivon → Kraken - Cycle #42
   Scanning markets...
   Signal: BUY ETH-USD
   ✅ Order placed: $50.00

🔄 Tania → Alpaca - Cycle #42
   Scanning markets...
   Signal: BUY AAPL
   ✅ Order placed: $75.00
```

## Troubleshooting

### "No master exchanges configured"
- Add Coinbase credentials to .env
- Restart the bot

### "No user accounts configured"
- Add KRAKEN_USER_* or ALPACA_USER_* credentials to .env
- Verify user configs in config/users/*.json
- Restart the bot

### "Kraken connection failed"
- Verify API key has correct permissions
- Check credentials in .env (no extra spaces/newlines)
- Run: `python3 test_kraken_connection_live.py`

### "Alpaca connection failed"
- Verify API key and secret are correct
- Check ALPACA_PAPER setting (true/false)
- Ensure account is funded for live trading

## Railway/Render Deployment

### Railway:
1. Dashboard → Your Service → "Variables" tab
2. Add each environment variable
3. Click "Save" (auto-restarts)

### Render:
1. Dashboard → Your Service → "Environment" tab
2. Add each environment variable
3. Click "Save Changes"
4. Click "Manual Deploy" → "Deploy latest commit"

## Summary

**The system is ready!** Just add your API credentials:

1. ✅ Copy .env.example to .env
2. ✅ Fill in API credentials (master + users)
3. ✅ Run: `python3 verify_multi_exchange_status.py`
4. ✅ Run: `./start.sh`
5. ✅ Monitor logs for connection status

The bot will automatically:
- Connect Nija to Coinbase (and optionally other exchanges)
- Connect each user to their configured exchange
- Start independent trading on all funded accounts
- Trade the APEX v7.1 strategy on each account

## More Help

- **MULTI_EXCHANGE_TRADING_GUIDE.md** - Detailed multi-exchange setup
- **USER_SETUP_GUIDE.md** - User account configuration
- **.env.example** - Environment variable format reference
- **KRAKEN_SETUP_GUIDE.md** - Kraken-specific setup
- **verify_multi_exchange_status.py** - Check configuration status

## Questions?

Run the verification script to see exactly what's configured and what's missing:

```bash
python3 verify_multi_exchange_status.py
```

It will tell you exactly what to do next!
