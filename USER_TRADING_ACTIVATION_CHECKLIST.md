# User Trading Activation Checklist

**Quick Reference Guide for Activating Live Trading on NIJA Bot**

Version: 1.0  
Last Updated: February 7, 2026

---

## Overview

This checklist guides you through activating trading on the NIJA autonomous cryptocurrency trading bot. Complete each section in order to ensure safe, successful activation.

**Estimated Time**: 15-30 minutes  
**Difficulty**: Beginner-friendly

---

## ✅ Phase 1: Prerequisites & Setup (5 minutes)

### 1.1 System Requirements
- [ ] Python 3.11+ installed
- [ ] Git installed (for cloning repository)
- [ ] Command line/terminal access
- [ ] Stable internet connection

### 1.2 Clone & Install
```bash
# Clone the repository
git clone https://github.com/dantelrharrell-debug/Nija.git
cd Nija

# Install dependencies
pip install -r requirements.txt
```

- [ ] Repository cloned successfully
- [ ] All dependencies installed without errors

### 1.3 Initial Environment Setup
```bash
# Run the setup helper script
python3 setup_env.py
```

- [ ] `.env` file created from template
- [ ] Confirm `.env` file exists in repository root

---

## ✅ Phase 2: Exchange API Credentials (10-15 minutes)

### 2.1 Choose Your Exchange

**Recommended for Beginners**: Kraken (lower fees, stable API)  
**Alternative**: Coinbase (user-friendly interface)

- [ ] Decided on primary exchange to use

### 2.2 Create Kraken API Keys (Recommended)

**Steps**:
1. Log in to [Kraken.com](https://www.kraken.com)
2. Go to Settings → API → Generate New Key
3. **CRITICAL**: Use "Classic API Key" (NOT OAuth)
4. Name it: "NIJA Trading Bot - Platform"
5. Enable these permissions (ALL required):
   - ✅ Query Funds
   - ✅ Query Open Orders & Trades
   - ✅ Query Closed Orders & Trades
   - ✅ Create & Modify Orders
   - ✅ Cancel/Close Orders
   - ❌ Do NOT enable "Withdraw Funds" (security)
6. Copy both API Key and API Secret to secure location

**Checklist**:
- [ ] Kraken account created/logged in
- [ ] API key generated with correct permissions
- [ ] API Key saved securely
- [ ] API Secret saved securely
- [ ] Withdrawal permissions disabled

### 2.3 Alternative: Create Coinbase API Keys

**Steps**:
1. Log in to [Coinbase](https://www.coinbase.com)
2. Go to Settings → API → Create API Key
3. Enable trading permissions
4. Save credentials securely

**Checklist**:
- [ ] Coinbase API credentials obtained (if using Coinbase)

---

## ✅ Phase 3: Configure Environment Variables (5 minutes)

### 3.1 Edit `.env` File

Open `.env` file in your preferred text editor:
```bash
nano .env  # or use VS Code, Sublime, etc.
```

### 3.2 Add Kraken Platform Credentials

**For Kraken** (add these lines):
```bash
KRAKEN_PLATFORM_API_KEY=your-api-key-here
KRAKEN_PLATFORM_API_SECRET=your-api-secret-here
```

**Checklist**:
- [ ] `KRAKEN_PLATFORM_API_KEY` set with your actual API key
- [ ] `KRAKEN_PLATFORM_API_SECRET` set with your actual API secret
- [ ] No extra spaces or quotes around values
- [ ] Credentials match exactly what Kraken provided

### 3.3 Add Coinbase Credentials (If Using Coinbase)

**For Coinbase** (uncomment and fill these lines):
```bash
COINBASE_API_KEY=organizations/your-org-id/apiKeys/your-key-id
COINBASE_API_SECRET="-----BEGIN EC PRIVATE KEY-----
YOUR_PRIVATE_KEY_HERE
-----END EC PRIVATE KEY-----"
```

**Checklist**:
- [ ] Coinbase credentials added (if applicable)

### 3.4 Configure Safety Settings

**CRITICAL**: Set these safety controls in `.env`:

```bash
# Enable live trading (default: false for safety)
LIVE_CAPITAL_VERIFIED=false  # Set to 'true' only when ready for real trading

# Trading mode
TRADING_MODE=independent

# Initial capital tracking
INITIAL_CAPITAL=auto  # Automatically uses your broker balance

# Position management
MAX_CONCURRENT_POSITIONS=7
MIN_CASH_TO_BUY=5.50
MINIMUM_TRADING_BALANCE=25.0
```

**Checklist**:
- [ ] `LIVE_CAPITAL_VERIFIED` confirmed as `false` (for initial testing)
- [ ] `TRADING_MODE=independent` set
- [ ] `INITIAL_CAPITAL=auto` set
- [ ] Position limits configured

### 3.5 Save Environment File

- [ ] `.env` file saved with all changes
- [ ] **VERIFY**: `.env` file is in `.gitignore` (never commit credentials!)

---

## ✅ Phase 4: First Test Run (Paper Trading Mode)

### 4.1 Start Bot in Safe Mode

```bash
# Start the bot (with LIVE_CAPITAL_VERIFIED=false, it won't trade real money)
python3 bot.py
```

### 4.2 Verify Connection

**Look for these success messages in the logs**:
```
✅ PLATFORM ACCOUNT: TRADING (Broker: kraken)
✅ Kraken Platform credentials detected
✅ CONNECTED
```

**Checklist**:
- [ ] Bot starts without errors
- [ ] Kraken connection shows as "✅ CONNECTED"
- [ ] No authentication errors in logs
- [ ] Platform account shows as "TRADING"

### 4.3 Troubleshooting Connection Issues

**If you see errors**:

| Error | Solution |
|-------|----------|
| "Invalid API key" | Double-check credentials in `.env` match Kraken exactly |
| "Permission denied" | Verify all required permissions enabled in Kraken API settings |
| "Invalid nonce" | Check system clock is accurate, wait 30 seconds and retry |
| "Connection failed" | Check internet connection, verify Kraken is not down |

**Checklist**:
- [ ] All connection errors resolved
- [ ] Bot running successfully

---

## ✅ Phase 5: Risk Configuration & Account Setup

### 5.1 Understand Your Account Tier

NIJA automatically detects your tier based on account balance:

| Tier | Balance Range | Min Visible Trade | Max Risk |
|------|---------------|-------------------|----------|
| **STARTER** | $50-$99 | $10 | 10-15% |
| **SAVER** | $100-$249 | $15 | 7-10% |
| **INVESTOR** | $250-$999 | $20 | 5-7% |
| **INCOME** | $1k-$5k | $30 | 3-5% |
| **LIVABLE** | $5k-$25k | $50 | 2-3% |
| **BALLER** | $25k+ | $100 | 1-2% |

**Checklist**:
- [ ] Understand which tier applies to your account balance
- [ ] Comfortable with risk parameters for your tier

### 5.2 Set Risk Profile (Optional Advanced)

In `.env`, you can force a specific tier:
```bash
# Force platform account to BALLER tier (most conservative risk)
PLATFORM_ACCOUNT_TIER=BALLER
```

**Checklist**:
- [ ] Risk profile configured (or default auto-detection accepted)

### 5.3 Configure Position Management

**Review these settings in `.env`**:
```bash
# Maximum concurrent open positions
MAX_CONCURRENT_POSITIONS=7

# Minimum cash required to buy
MIN_CASH_TO_BUY=5.50

# Minimum balance to start trading
MINIMUM_TRADING_BALANCE=25.0

# For small accounts under $25, you can lower these:
# MINIMUM_TRADING_BALANCE=15.0
# MIN_CASH_TO_BUY=5.0
```

**Checklist**:
- [ ] Position limits appropriate for account size
- [ ] Minimum balance requirements understood

---

## ✅ Phase 6: Enable Live Trading (When Ready)

### 6.1 Pre-Activation Safety Checklist

**Before enabling live trading, verify**:
- [ ] Bot successfully connected to exchange in test mode
- [ ] Understand trading strategy (see `APEX_V71_DOCUMENTATION.md`)
- [ ] Reviewed risk disclosures
- [ ] Have adequate balance in exchange account ($25+ recommended)
- [ ] Understand maximum position sizes for your tier
- [ ] Set up 2FA on exchange account
- [ ] Exchange API key has withdrawal disabled
- [ ] Comfortable with autonomous trading concept

### 6.2 Understand What Will Happen

**When you enable live trading**:
1. ✅ Bot will scan 732+ cryptocurrency markets every 2.5 minutes
2. ✅ Uses dual RSI strategy (RSI_9 + RSI_14) to find opportunities
3. ✅ Executes trades automatically when signals meet criteria
4. ✅ Manages stop losses and profit targets automatically
5. ✅ Compounds profits by increasing position sizes over time

**You should monitor**:
- 📊 Check logs regularly for trading activity
- 📊 Review positions via exchange dashboard
- 📊 Monitor account balance
- 📊 Watch for any error messages

### 6.3 Enable Live Trading

**Edit `.env` file**:
```bash
# Change from false to true
LIVE_CAPITAL_VERIFIED=true
```

**Save file and restart bot**:
```bash
# Stop current bot (Ctrl+C)
# Restart with live trading enabled
python3 bot.py
```

**Checklist**:
- [ ] `LIVE_CAPITAL_VERIFIED=true` set in `.env`
- [ ] Bot restarted
- [ ] Live trading activated

### 6.4 Verify Live Trading Active

**Look for these messages**:
```
✅ LIVE TRADING ENABLED
✅ PLATFORM ACCOUNT: TRADING (Broker: kraken)
🚀 Scanning markets...
```

**Checklist**:
- [ ] "LIVE TRADING ENABLED" message appears
- [ ] Bot scanning markets
- [ ] No critical errors in logs

---

## ✅ Phase 7: Monitoring & Maintenance

### 7.1 Initial Monitoring (First 24 Hours)

**Check every 2-4 hours**:
- [ ] Bot still running (no crashes)
- [ ] Review any trades executed
- [ ] Check account balance changes
- [ ] Verify stop losses are set on positions
- [ ] Read through logs for any warnings

### 7.2 Daily Monitoring

**Once per day**:
- [ ] Check bot status and uptime
- [ ] Review open positions in exchange dashboard
- [ ] Monitor profit/loss metrics
- [ ] Check for software updates
- [ ] Verify API keys still valid

### 7.3 Emergency Controls

**If you need to stop trading immediately**:

1. **Quick Stop**: Press `Ctrl+C` in terminal
2. **Emergency Kill Switch**:
   ```bash
   python3 emergency_kill_switch.py
   ```
3. **Disable in `.env`**:
   ```bash
   LIVE_CAPITAL_VERIFIED=false
   ```
   Then restart bot.

**Checklist**:
- [ ] Know how to stop bot immediately if needed
- [ ] Understand emergency procedures

---

## ✅ Phase 8: Optional Enhancements

### 8.1 TradingView Webhooks (Advanced)

For instant execution based on TradingView alerts:
- [ ] See `TRADINGVIEW_SETUP.md` for webhook configuration
- [ ] Set up webhook server for faster signal execution

### 8.2 Multi-User Accounts (Advanced)

To manage multiple trading accounts:
- [ ] See `GETTING_STARTED.md` section on "Enabling User Accounts"
- [ ] Configure user accounts in `config/users/*.json`
- [ ] Add user API credentials to `.env`

### 8.3 Deployment to Cloud (Production)

For 24/7 uptime:
- [ ] See `QUICK_START.md` for Railway deployment
- [ ] See `DEPLOYMENT_GUIDE.md` for full production setup
- [ ] Configure environment variables in cloud platform

---

## ✅ Post-Activation Checklist

### Immediate (First Hour)
- [ ] Bot running without errors
- [ ] Connection to exchange stable
- [ ] First market scan completed
- [ ] Logs readable and understandable

### First 24 Hours
- [ ] Bot executed at least one trade (or explain why no trades if market conditions poor)
- [ ] Stop losses set on all positions
- [ ] No unexpected errors or crashes
- [ ] Account balance tracking correctly

### First Week
- [ ] Profitable trades executed (net positive or break-even expected)
- [ ] Risk management working (no single trade > configured max)
- [ ] Bot stable and running continuously
- [ ] Comfortable with autonomous operation

---

## 🔒 Security Best Practices

**ALWAYS follow these security rules**:

- [ ] ✅ Never commit `.env` file to git (already in `.gitignore`)
- [ ] ✅ Never share API keys publicly
- [ ] ✅ Enable 2FA on exchange accounts
- [ ] ✅ Disable withdrawal permissions on API keys
- [ ] ✅ Use minimum required API permissions
- [ ] ✅ Store credentials in password manager
- [ ] ✅ Rotate API keys every 90 days
- [ ] ✅ Monitor API usage in exchange dashboard
- [ ] ✅ Set up alerts for unusual activity
- [ ] ✅ Keep software updated

---

## 📚 Additional Resources

**Essential Documentation**:
- `GETTING_STARTED.md` - Detailed setup guide
- `APEX_V71_DOCUMENTATION.md` - Trading strategy details
- `API_CREDENTIALS_GUIDE.md` - Credential management
- `BROKER_INTEGRATION_GUIDE.md` - Broker setup details
- `RISK_DISCLOSURE.md` - Important risk information

**Advanced Topics**:
- `TRADINGVIEW_SETUP.md` - Webhook integration
- `DEPLOYMENT_GUIDE.md` - Production deployment
- `PAPER_TO_LIVE_GRADUATION.md` - Paper trading progression

**Support**:
- Review logs for error messages
- Check GitHub issues for known problems
- See `README.md` for comprehensive documentation

---

## 🆘 Common Issues & Solutions

### Bot Won't Start
**Problem**: Error on `python3 bot.py`  
**Solution**: Check Python version (`python3 --version`), reinstall dependencies (`pip install -r requirements.txt`)

### "Invalid API Key" Error
**Problem**: Cannot connect to exchange  
**Solution**: Verify credentials in `.env` match exactly what exchange provided, check for extra spaces

### No Trades Executing
**Problem**: Bot running but no trades  
**Solution**: Normal if market conditions don't meet strategy criteria. Review `APEX_V71_DOCUMENTATION.md` for entry requirements. May take hours to find suitable setups.

### "Insufficient Balance" Error
**Problem**: Bot cannot place orders  
**Solution**: Ensure exchange account has minimum $25 balance (or $15 for small accounts). Check `MIN_CASH_TO_BUY` in `.env`.

### Bot Crashes Overnight
**Problem**: Bot stops running  
**Solution**: Deploy to cloud platform (Railway/Render) for 24/7 uptime. See `DEPLOYMENT_GUIDE.md`.

---

## ✨ Quick Start Summary

**Absolute minimum to start trading**:

1. ✅ Clone repository: `git clone https://github.com/dantelrharrell-debug/Nija.git`
2. ✅ Install dependencies: `pip install -r requirements.txt`
3. ✅ Create `.env`: `python3 setup_env.py`
4. ✅ Get Kraken API credentials (with trading permissions)
5. ✅ Add credentials to `.env` file
6. ✅ Test connection: `python3 bot.py` (verify "✅ CONNECTED")
7. ✅ When ready for live trading: Set `LIVE_CAPITAL_VERIFIED=true`
8. ✅ Restart bot and monitor

**Time from zero to trading**: 15-30 minutes

---

## 📝 Version History

- **v1.0** (Feb 7, 2026) - Initial release of activation checklist

---

**Remember**: Start with paper trading or small amounts to familiarize yourself with the system before committing significant capital. Trading cryptocurrencies involves substantial risk of loss.

**Questions?** Review the comprehensive documentation in the repository or open an issue on GitHub (never include actual API credentials in issues).
