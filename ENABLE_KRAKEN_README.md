# Enable Kraken Trading - Complete Guide

> **TL;DR**: Kraken is already fully implemented and enabled by default. You just need to add API credentials.

## Quick Start (5 Minutes)

### 1. Verify Current Status

```bash
python3 verify_kraken_status.py
```

This will show you exactly what's configured and what's missing.

### 2. Get Kraken API Credentials

1. Go to https://www.kraken.com/u/security/api
2. Click "Generate New Key"
3. Set description: "NIJA Trading Bot"
4. Enable these permissions:
   - ✅ **Query Funds** (required)
   - ✅ **Query Open Orders & Trades** (required)
   - ✅ **Query Closed Orders & Trades** (required)
   - ✅ **Create & Modify Orders** (required)
   - ✅ **Cancel/Close Orders** (required)
   - ❌ **Withdraw Funds** (DO NOT enable - security risk)
5. Click "Generate Key"
6. Copy both the **API Key** and **Private Key** immediately (you won't see the Private Key again)

### 3. Add Environment Variables

#### Railway Platform

1. Go to https://railway.app
2. Click your NIJA project → Your service
3. Click "Variables" tab
4. Add these variables:
   - Click "+ New Variable"
   - Name: `KRAKEN_MASTER_API_KEY`
   - Value: `<paste your API key>`
   - Click "Add"
   - Repeat for `KRAKEN_MASTER_API_SECRET` with your Private Key
5. Railway will automatically restart (wait 2-3 minutes)

#### Render Platform

1. Go to https://dashboard.render.com
2. Click your NIJA service
3. Click "Environment" tab
4. Click "Add Environment Variable"
   - Key: `KRAKEN_MASTER_API_KEY`
   - Value: `<paste your API key>`
5. Click "Add Environment Variable" again
   - Key: `KRAKEN_MASTER_API_SECRET`
   - Value: `<paste your Private Key>`
6. Click "Save Changes"
7. Click "Manual Deploy" → "Deploy latest commit"
8. Wait 2-3 minutes for deployment

#### Local Development (.env file)

```bash
# Add to .env file (create if doesn't exist)
echo "KRAKEN_MASTER_API_KEY=your-api-key-here" >> .env
echo "KRAKEN_MASTER_API_SECRET=your-private-key-here" >> .env

# Start bot
./start.sh
```

### 4. Verify Kraken is Trading

Check your deployment logs for these messages:

```
✅ Kraken Master credentials detected
📊 Attempting to connect Kraken Pro (MASTER)...
   ✅ Kraken MASTER connected
   ✅ Kraken registered as MASTER broker in multi-account manager

🚀 STARTING INDEPENDENT MULTI-BROKER TRADING MODE
═══════════════════════════════════════════════════════════════
Each broker will trade independently in isolated threads.
═══════════════════════════════════════════════════════════════

🔍 Detecting funded brokers...
   💰 coinbase: $XX.XX
      ✅ FUNDED - Ready to trade
   💰 kraken: $XX.XX
      ✅ FUNDED - Ready to trade

✅ Started independent trading thread for coinbase (MASTER)
✅ Started independent trading thread for kraken (MASTER)
```

Then you should see cycle messages for both:
```
🔄 coinbase - Cycle #1
🔄 kraken - Cycle #1
```

**Done!** Kraken is now trading independently alongside Coinbase.

---

## Understanding Kraken Integration

### How It Works

1. **Kraken is already fully implemented** in the codebase
   - `bot/broker_manager.py` contains complete KrakenBroker class
   - Supports all necessary trading operations
   - Handles nonce generation, error retries, and rate limiting

2. **Independent multi-broker trading is enabled by default**
   - Environment variable `MULTI_BROKER_INDEPENDENT=true` (default)
   - Each broker trades in its own thread
   - Failures in one broker don't affect others
   - Each broker manages its own positions and balance

3. **What you need to provide**
   - Kraken API credentials (API Key + Private Key)
   - Sufficient funds in your Kraken account (minimum $0.50, recommended $25+)

### Architecture

```
NIJA Bot
├── Master Account (NIJA system)
│   ├── Coinbase (if credentials provided)
│   ├── Kraken (if credentials provided)  ← THIS IS WHAT YOU'RE ENABLING
│   ├── OKX (if credentials provided)
│   └── Alpaca (if credentials provided)
│
└── User Accounts (optional - for managing investor funds)
    ├── User 1 (Daivon) - Kraken
    └── User 2 (Tania) - Kraken/Alpaca
```

Each broker operates **completely independently**:
- Own trading decisions based on APEX v7.1 strategy
- Own balance and position tracking
- Own error handling and retry logic
- Own market scanning and order execution

### Benefits of Multi-Exchange Trading

1. **Reduced Rate Limiting** - Load split across exchanges
2. **Higher Resilience** - If one exchange has issues, others continue
3. **Access to Different Pairs** - Each exchange has unique cryptocurrency listings
4. **Diversification** - Don't put all eggs in one basket

---

## Advanced Configuration

### User Accounts (Optional)

If you want to trade on behalf of users/investors on Kraken:

```bash
# User 1 (Daivon)
KRAKEN_USER_DAIVON_API_KEY=user-api-key
KRAKEN_USER_DAIVON_API_SECRET=user-private-key

# User 2 (Tania)
KRAKEN_USER_TANIA_API_KEY=user-api-key
KRAKEN_USER_TANIA_API_SECRET=user-private-key
```

Then configure user accounts in `config/users/retail_kraken.json`:

```json
{
  "users": [
    {
      "user_id": "daivon_frazier",
      "name": "Daivon Frazier",
      "broker_type": "kraken",
      "account_type": "retail",
      "enabled": true
    },
    {
      "user_id": "tania_gilbert",
      "name": "Tania Gilbert",
      "broker_type": "kraken",
      "account_type": "retail",
      "enabled": true
    }
  ]
}
```

### Disable Independent Trading (Not Recommended)

If you want only one broker to trade (old behavior):

```bash
MULTI_BROKER_INDEPENDENT=false
```

This will make only the "primary" broker trade. Not recommended because:
- Wastes connected brokers
- More vulnerable to rate limiting
- Single point of failure

---

## Troubleshooting

### Problem: Bot says "Kraken Master credentials NOT SET"

**Solution**: Add environment variables to your platform

The bot checks for these exact variable names:
- `KRAKEN_MASTER_API_KEY`
- `KRAKEN_MASTER_API_SECRET`

Common mistakes:
- Typos in variable names
- Leading/trailing spaces in values
- Not restarting after adding variables
- Using wrong API key (Consumer API instead of Pro/Spot)

### Problem: Connection fails with "Permission denied"

**Solution**: Enable required permissions on your API key

1. Go to https://www.kraken.com/u/security/api
2. Find your API key → Edit
3. Enable these permissions:
   - Query Funds
   - Query/Create/Cancel Orders
   - Query Trades
4. Save and restart bot

### Problem: Connection fails with "Invalid nonce"

**Solution**: Wait 1-2 minutes and restart

Kraken uses nonce-based authentication. The bot handles this automatically with:
- Microsecond precision nonces
- Monotonic nonce generation
- Automatic nonce jumps on retries

If you see this error, it usually resolves after waiting 1-2 minutes.

### Problem: "Kraken SDK: Not installed"

**Solution**: Install required packages

The Kraken SDK should already be in `requirements.txt`, but if it's missing:

```bash
pip install krakenex==2.2.2 pykrakenapi==0.3.2
```

Then restart the bot.

### Problem: Only Coinbase is trading, not Kraken

**Check these in order:**

1. **Are credentials configured?**
   ```bash
   python3 verify_kraken_status.py
   ```

2. **Did Kraken connect successfully?**
   Check logs for: `✅ Kraken MASTER connected`

3. **Does Kraken have sufficient funds?**
   Minimum $0.50, recommended $25+
   Check logs for: `💰 kraken: $X.XX ✅ FUNDED - Ready to trade`

4. **Is independent trading enabled?**
   Check logs for: `🚀 STARTING INDEPENDENT MULTI-BROKER TRADING MODE`

5. **Was trading thread started?**
   Check logs for: `✅ Started independent trading thread for kraken (MASTER)`

If all checks pass but Kraken isn't trading:
- Check for error messages in logs containing "kraken"
- Run: `python3 diagnose_kraken_connection.py`
- Run: `python3 test_kraken_connection_live.py`

---

## Testing

### Verify Configuration

```bash
# Check all Kraken settings
python3 verify_kraken_status.py

# Test Kraken connection with live API
python3 test_kraken_connection_live.py

# Diagnose connection issues
python3 diagnose_kraken_connection.py

# Check all environment variables
python3 diagnose_env_vars.py
```

### Monitor Trading

```bash
# Watch logs in real-time (Railway)
railway logs --follow

# Watch logs in real-time (Render)
# Go to dashboard → Service → Logs tab

# Local
tail -f nija.log
```

Look for:
- `🔄 kraken - Cycle #N` (trading cycles)
- `📊 kraken scanning market:` (market scanning)
- `✅ kraken order placed:` (trades executed)

---

## Resources

### Documentation
- `HOW_TO_ENABLE_KRAKEN.md` - Original quick guide
- `KRAKEN_QUICK_START.md` - Step-by-step setup
- `MULTI_EXCHANGE_TRADING_GUIDE.md` - Multi-broker architecture
- `KRAKEN_TROUBLESHOOTING_SUMMARY.md` - Common issues

### Test Scripts
- `verify_kraken_status.py` - Check current status (NEW - use this first!)
- `test_kraken_connection_live.py` - Test API connection
- `diagnose_kraken_connection.py` - Diagnose issues
- `diagnose_env_vars.py` - Check all environment variables

### Configuration Files
- `.env.example` - Template for local development
- `requirements.txt` - Package dependencies (includes Kraken SDK)
- `config/users/retail_kraken.json` - User account config

### Code Files
- `bot/broker_manager.py` - KrakenBroker implementation (lines 3370-4295)
- `bot/trading_strategy.py` - Strategy initialization (connects Kraken)
- `bot/independent_broker_trader.py` - Multi-broker trading logic
- `bot.py` - Main entry point (checks credentials)

---

## FAQ

**Q: Is Kraken already implemented?**

A: Yes! Kraken is fully implemented. You just need to add credentials.

**Q: Will Kraken trade automatically?**

A: Yes, once credentials are provided and account is funded ($0.50+), Kraken will trade independently using the APEX v7.1 strategy.

**Q: Can I use only Kraken (without Coinbase)?**

A: Yes, but the bot requires at least one exchange with credentials. You can use any combination of Coinbase, Kraken, OKX, Binance, or Alpaca.

**Q: Do I need to modify any code?**

A: No! Everything is already implemented. Just add environment variables.

**Q: What's the difference between Master and User accounts?**

A: 
- **Master**: NIJA system account that you control
- **User**: Investor accounts you manage on behalf of others (optional)

**Q: How much money do I need in Kraken?**

A: Minimum $0.50 to start trading, but $25+ recommended for profitable trading (fees eat into small positions).

**Q: Will this affect my Coinbase trading?**

A: No! Each broker trades independently. Kraken and Coinbase run in separate threads with isolated error handling.

**Q: Can I enable Kraken on Railway?**

A: Yes! Just add the environment variables in the Railway dashboard (Variables tab).

**Q: Can I enable Kraken on Render?**

A: Yes! Just add the environment variables in the Render dashboard (Environment tab).

---

## Support

If you're still having issues after following this guide:

1. Run diagnostics: `python3 verify_kraken_status.py`
2. Check logs for error messages containing "kraken"
3. Review troubleshooting section above
4. Check existing issues on GitHub
5. Create new issue with:
   - Output from `verify_kraken_status.py`
   - Relevant log excerpts
   - Platform (Railway/Render/Local)
   - What you've tried

---

**Last Updated**: January 16, 2026

**Status**: ✅ Kraken is fully implemented and tested
