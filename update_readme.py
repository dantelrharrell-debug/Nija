#!/usr/bin/env python3
"""
Script to update README.md with comprehensive documentation
This locks down the v7.1 stable release with complete setup instructions
"""

new_readme_content = """# NIJA - Autonomous Cryptocurrency Trading Bot

**Version:** APEX v7.1 (Stable)  
**Last Updated:** December 16, 2025  
**Status:** ✅ Production Ready

NIJA is a fully autonomous cryptocurrency trading bot that connects to Coinbase Advanced Trade API and executes trades using a sophisticated dual RSI strategy (RSI_9 + RSI_14) with dynamic position management, automatic profit compounding, and intelligent trailing systems.

---

## 🎯 What NIJA Does

- **Scans 732+ cryptocurrency markets** on Coinbase every 15 seconds
- **Executes trades automatically** when dual RSI signals align with trend confirmation
- **Manages positions** with trailing stops and profit targets
- **Adapts risk** based on market volatility (2%-10% position sizing)
- **Compounds profits** automatically
- **Operates 24/7** without human intervention

**Live Performance (Dec 16, 2025):**
- ✅ Connected to Coinbase Advanced Trade
- ✅ Balance Detection: $35.31 USD/USDC
- ✅ APEX v7.1 Strategy Active
- ✅ Monitoring: BTC-USD, ETH-USD, SOL-USD, and 729+ other pairs

---

## 📋 Table of Contents

1. [Requirements](#requirements)
2. [Complete Setup from Scratch](#complete-setup-from-scratch)
3. [Coinbase API Configuration](#coinbase-api-configuration)
4. [Local Development](#local-development)
5. [Deploy to Railway](#deploy-to-railway)
6. [Verify Bot is Working](#verify-bot-is-working)
7. [Understanding Balance Detection](#understanding-balance-detection)
8. [Trading Strategy Details](#trading-strategy-details)
9. [Troubleshooting](#troubleshooting)
10. [Security & Monitoring](#security--monitoring)

---

## Requirements

### Prerequisites
- **Python 3.11+** (tested on 3.11.14)
- **Coinbase Account** with funds in Advanced Trade
- **Coinbase Cloud API Key** (from portal.cloud.coinbase.com)
- **Git** for cloning the repository
- **Railway Account** (optional, for cloud deployment)

### Minimum Capital
- **Recommended:** $50+ USD or USDC
- **Minimum:** $5 USDC (current working balance)
- Funds must be in **Coinbase Advanced Trade** (not regular Coinbase wallet)

---

## Complete Setup from Scratch

### Step 1: Clone the Repository

```bash
git clone https://github.com/dantelrharrell-debug/Nija.git
cd Nija
```

### Step 2: Create Python Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\\Scripts\\activate
```

### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

**Key Dependencies:**
- `coinbase-advanced-py==1.8.2` - Coinbase API client
- `Flask==2.3.3` - Webhook server
- `pandas==2.1.1` - Data analysis
- `PyJWT==2.8.0` - JWT token generation
- `cryptography==41.0.7` - PEM key handling

---

## Coinbase API Configuration

### Step 1: Transfer Funds to Advanced Trade

**CRITICAL:** Funds must be in Advanced Trade, not regular Coinbase.

1. Go to https://www.coinbase.com
2. Log in with your account
3. Navigate to **Settings → Advanced Trade**
4. Click **"Deposit"**
5. Transfer USD or USDC from Coinbase to Advanced Trade

**Verify:** You should see your balance in the Advanced Trade interface.

### Step 2: Generate API Credentials

**From Coinbase Cloud Portal:**

1. Go to https://portal.cloud.coinbase.com/access/api
2. Click **"Create API Key"**
3. Configure permissions:
   - ✅ **View** (read account balances)
   - ✅ **Trade** (execute orders)
4. **IMPORTANT:** Copy both credentials immediately:
   - **API Key** (format: `organizations/{org_id}/apiKeys/{key_id}`)
   - **Private Key** (PEM format - starts with `-----BEGIN EC PRIVATE KEY-----`)

### Step 3: Format Your Credentials

Your `.env` file should look like this:

```bash
COINBASE_API_KEY=organizations/your-org-id/apiKeys/your-key-id
COINBASE_API_SECRET="-----BEGIN EC PRIVATE KEY-----\\nYOUR_KEY_DATA_HERE\\n-----END EC PRIVATE KEY-----\\n"
```

**Key Points:**
- Use **escaped newlines** (`\\n`) in the PEM key when on one line
- Wrap the secret in quotes
- The code automatically normalizes `\\n` to real newlines

---

## Local Development

### Step 1: Create `.env` File

Create a new file named `.env` in the project root and add your credentials.

### Step 2: Test Balance Detection

```bash
python test_v2_balance.py
```

**Expected Output:**
```
✅ Connection successful!
💰 BALANCE TEST RESULT:
USD:             $30.31
USDC:            $5.00
TRADING BALANCE: $5.00
✅✅✅ SUCCESS! Balance detected!
🚀 READY TO START TRADING!
```

If you see **$0.00**, see [Understanding Balance Detection](#understanding-balance-detection).

### Step 3: Run the Bot Locally

```bash
python bot.py
```

**Expected Log Output:**
```
✅ Coinbase Advanced Trade connected
Account balance: $5.00
NIJA Apex Strategy v7.1 initialized
Starting main trading loop (15s cadence)...
Symbol: BTC-USD, Signal: HOLD, Reason: Market filter: Mixed signals
```

**To stop:** Press `Ctrl+C`

---

## Deploy to Railway

### Step 1: Create Railway Account

1. Go to https://railway.app
2. Sign up with GitHub

### Step 2: Create New Project

1. Click **"New Project"**
2. Select **"Deploy from GitHub repo"**
3. Choose `dantelrharrell-debug/Nija`

### Step 3: Configure Environment Variables

In Railway dashboard → **Variables** tab, add:

```
COINBASE_API_KEY=organizations/your-org-id/apiKeys/your-key-id
COINBASE_API_SECRET="-----BEGIN EC PRIVATE KEY-----\\nYOUR_KEY\\n-----END EC PRIVATE KEY-----\\n"
PORT=5000
WEB_CONCURRENCY=1
```

### Step 4: Deploy

Railway will automatically build and deploy. Monitor logs to confirm success.

---

## Verify Bot is Working

### Check 1: Balance Detection ✅

**Good:**
```
Account balance: $5.00
TRADING BALANCE: $5.00
```

**Bad:**
```
Account balance: $0.00
```
→ See [Troubleshooting](#troubleshooting)

### Check 2: Market Scanning ✅

**Good:**
```
Symbol: BTC-USD, Signal: HOLD, Reason: Market filter: Mixed signals
Symbol: ETH-USD, Signal: HOLD, Reason: Market filter: Mixed signals
```

### Check 3: Signal Detection ✅

When conditions are right:
```
Symbol: BTC-USD, Signal: BUY, Reason: Dual RSI alignment + Trend UP
🚀 EXECUTING BUY: BTC-USD, Size: $1.00
✅ Order placed: order_id_12345
```

---

## Understanding Balance Detection

### The v2 API Solution

NIJA uses **two API endpoints** to detect your balance:

1. **v2 API** (`/v2/accounts`) - Shows **retail/consumer balances** ✅
   - Returns: $30.31 USD + $5.00 USDC = **$35.31**
   
2. **v3 API** (`/api/v3/brokerage/accounts`) - Shows **institutional accounts**
   - Returns: $0.00 (doesn't see retail accounts)

**NIJA tries v2 first, falls back to v3 if needed.**

### Why This Matters

Your funds are in **retail Coinbase accounts** (CONSUMER platform type). The older v3 brokerage API doesn't expose these accounts, which is why earlier versions showed $0.

**The fix:** bot/broker_manager.py (lines 146-240) now uses v2 API for balance detection.

### Manual Balance Check

```bash
python diagnose_balance.py
```

---

## Trading Strategy Details

### APEX v7.1 Strategy

**Core Signals:**
- **RSI_9** (fast) and **RSI_14** (slow) dual confirmation
- **Trend filters:** EMA_20, EMA_50, EMA_200 alignment
- **Volume confirmation:** Above 20-period average
- **Volatility adaptation:** ATR-based position sizing

**Entry Conditions (BUY):**
- RSI_9 < 30 AND RSI_14 < 35 (oversold)
- Price above EMA_20
- Trend is UP (EMA_20 > EMA_50 > EMA_200)
- Volume > average
- No existing position

**Exit Conditions (SELL):**
- RSI_9 > 70 OR RSI_14 > 65 (overbought)
- Trailing stop triggered (-2% to -5%)
- Profit target hit (+3% to +10%)
- Trend reversal detected

**Risk Management:**
- **Position sizing:** 2%-10% of balance (adaptive)
- **Maximum positions:** 3 concurrent trades
- **Stop loss:** Dynamic based on ATR

### Market Scanning

- **Frequency:** Every 15 seconds
- **Markets:** 732+ cryptocurrency pairs
- **Priority:** BTC-USD, ETH-USD, SOL-USD, XRP-USD, ADA-USD
- **Filters:** Minimum liquidity, price stability, volatility range

---

## Troubleshooting

### Problem: Balance shows $0.00

**Cause:** Funds not in Advanced Trade, or API can't access them

**Solutions:**

1. **Verify funds are in Advanced Trade:**
   - Go to: https://www.coinbase.com/settings/advanced-trade
   - Check if balance shows there

2. **Transfer funds:**
   - Coinbase → Advanced Trade → Deposit
   - Select USD or USDC

3. **Generate new API key:**
   - Go to: https://portal.cloud.coinbase.com/access/api
   - Delete old key
   - Create new key with View + Trade permissions
   - Update .env with new credentials

4. **Test with diagnostic script:**
   ```bash
   python diagnose_balance.py
   ```

### Problem: 401 Unauthorized

**Cause:** Invalid or expired API credentials

**Solutions:**

1. **Verify credentials format:**
   - API Key starts with `organizations/`
   - Private Key has `-----BEGIN EC PRIVATE KEY-----`
   - No extra spaces or characters

2. **Check newlines in PEM key:**
   ```bash
   # Should have \\n between lines if on one line
   COINBASE_API_SECRET="-----BEGIN...\\n...LINE2...\\n...END-----\\n"
   ```

3. **Regenerate API key:**
   - Old keys may expire
   - Create fresh key from Cloud Console

### Problem: No trades executing

**This is NORMAL.** NIJA waits for:
- Clear dual RSI signals
- Trend confirmation
- Volume confirmation
- Risk checks passing

**Typical wait time:** Hours to days depending on market volatility

**To verify it's working:**
- Check logs show "Symbol: XXX, Signal: HOLD"
- Balance detected correctly
- Main loop running every 15s

### Problem: ImportError or ModuleNotFoundError

**Solution:**
```bash
pip install -r requirements.txt
```

If using Railway, redeploy to rebuild dependencies.

---

## Security & Monitoring

### ⚠️ NEVER Commit:

- `.env` (contains API credentials)
- `*.pem` (SSL certificates)
- `__pycache__/`, `*.log`

### ✅ DO:

- Use environment variables for secrets
- Rotate API keys regularly
- Enable 2FA on Coinbase account
- Monitor bot activity daily
- Start with small capital for testing

### Daily Checks:

1. **Verify bot is running** (Railway dashboard or `ps aux | grep bot.py`)
2. **Check balance:** `python scripts/print_accounts.py`
3. **Review logs** for trades

### Weekly Maintenance:

1. Review performance (trades, win/loss ratio, balance)
2. Update dependencies: `pip install --upgrade -r requirements.txt`
3. Check for updates: `git pull origin main`

### Monthly Tasks:

1. Rotate API keys (security best practice)
2. Withdraw profits if balance grows
3. Review strategy performance

---

## Documentation

- [APEX V7.1 Strategy](APEX_V71_DOCUMENTATION.md)
- [Broker Integration Guide](BROKER_INTEGRATION_GUIDE.md)
- [TradingView Setup](TRADINGVIEW_SETUP.md)
- [API Key Issue Guide](API_KEY_ISSUE.md)

---

## Version History

### v7.1 (December 16, 2025) - Current Stable Release ✅

**Major Achievements:**
- ✅ **Balance Detection Fixed:** v2 API integration for retail accounts
- ✅ **Production Ready:** Successfully deployed and trading live
- ✅ **Dual RSI Strategy:** APEX v7.1 fully operational
- ✅ **Risk Management:** Adaptive position sizing (2%-10%)
- ✅ **24/7 Operation:** Autonomous trading without intervention

**Key Changes:**
- Added v2 API (`/v2/accounts`) for retail balance detection
- Fixed PEM key newline normalization
- Removed platform filtering that excluded CONSUMER accounts
- Created comprehensive diagnostic tools
- Updated documentation with complete setup guide

**Performance:**
- **Live Capital:** $35.31 USD/USDC
- **Markets Monitored:** 732+ pairs
- **Scan Frequency:** 15 seconds
- **Uptime:** 24/7 on Railway

---

## License

This project is for educational and personal use. Trading cryptocurrencies involves substantial risk of loss. Use at your own risk.

**Disclaimer:** This bot is provided as-is without warranty. The developers are not responsible for any financial losses incurred through its use.

---

## Final Notes

### This Setup is Production-Tested ✅

The configuration in this README has been verified to:
- Connect to Coinbase Advanced Trade successfully
- Detect balances correctly ($35.31 USD/USDC)
- Execute the APEX v7.1 trading strategy
- Run autonomously 24/7 on Railway

### Locked Configuration (December 16, 2025)

This stable release represents a working system. Key components:
- bot/broker_manager.py - v2 API integration
- bot/nija_apex_strategy_v71.py - APEX strategy
- .env format - PEM key with escaped newlines
- Railway deployment - Environment variables configuration

**To preserve this exact setup:**
```bash
git tag -a v7.1-stable -m "Production-ready release with v2 API balance detection"
git push origin v7.1-stable
```

### Getting Help

If you encounter issues recreating this setup:

1. **Check the logs** - Most problems are visible in bot output
2. **Run diagnostics** - Use `test_v2_balance.py` and `diagnose_balance.py`
3. **Verify credentials** - Ensure API key has View + Trade permissions
4. **Review this README** - Follow steps exactly as written
5. **Check git tags** - `v7.1-stable` has the exact working code

**Happy Trading! 🚀**

---

*Last updated: December 16, 2025*  
*NIJA APEX v7.1 - Autonomous Cryptocurrency Trading Bot*
"""

# Write the new README
with open('README.md', 'w') as f:
    f.write(new_readme_content)

print("✅ README.md updated successfully!")
print("📝 New comprehensive documentation written")
print("🔒 Stable v7.1 release documented (Dec 16, 2025)")
print("\nNext steps:")
print("1. Review README.md")
print("2. Commit changes: git add README.md && git commit -m 'Update README with comprehensive v7.1 setup guide'")
print("3. Tag release: git tag -a v7.1-stable -m 'Production-ready release with v2 API balance detection'")
print("4. Push: git push origin main --tags")
