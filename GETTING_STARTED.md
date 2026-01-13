# NIJA Getting Started Guide

This guide will help you get NIJA up and running quickly, whether you want to trade with just the master account or enable multi-user trading.

## Table of Contents
- [Prerequisites](#prerequisites)
- [Quick Setup (5 minutes)](#quick-setup-5-minutes)
- [Enabling User Accounts](#enabling-user-accounts)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

Before you begin, you'll need:

1. **Python 3.11+** installed
2. **API credentials** from one or more exchanges:
   - Coinbase (recommended for beginners)
   - Kraken (optional, for expanded market access)

---

## Quick Setup (5 minutes)

### Step 1: Clone and Install

```bash
# Clone the repository
git clone https://github.com/dantelrharrell-debug/Nija.git
cd Nija

# Install dependencies
pip install -r requirements.txt
```

### Step 2: Create Your `.env` File

```bash
# Run the setup helper script
python3 setup_env.py
```

This creates a `.env` file from the template with placeholder values.

### Step 3: Configure Coinbase (Master Account)

1. **Get API credentials from Coinbase:**
   - Go to https://www.coinbase.com/
   - Navigate to API settings
   - Create a new API key with trading permissions
   - Save your credentials securely

2. **Edit `.env` file:**
   ```bash
   nano .env  # or use your preferred editor
   ```

3. **Fill in Coinbase credentials:**
   ```bash
   COINBASE_ORG_ID=your-org-id-here
   COINBASE_JWT_PEM="-----BEGIN EC PRIVATE KEY-----\nYOUR_KEY_HERE\n-----END EC PRIVATE KEY-----"
   COINBASE_JWT_KID=your-kid-here
   COINBASE_JWT_ISSUER=organizations/your-org-id-here
   ```

### Step 4: Run NIJA

```bash
python3 bot.py
```

You should see:
```
✅ MASTER ACCOUNT: TRADING (Broker: coinbase)
❌ USER #1 (Daivon Frazier): NOT TRADING (Connection failed or not configured)
❌ USER #2 (Tania Gilbert): NOT TRADING (Connection failed or not configured)
```

**This is normal!** User accounts are optional. NIJA will trade with the master account.

---

## Adding Kraken Master Account (Optional)

Want to expand your trading to Kraken? You can enable Kraken for the master account to trade on multiple exchanges simultaneously.

### Quick Setup for Kraken Master

**🚀 NEW: Quick Guide Available!**

For the fastest setup, check out:
- **QUICKSTART_MASTER_KRAKEN.txt** - Visual one-page guide
- **SETUP_MASTER_KRAKEN.md** - Detailed step-by-step instructions
- Run: `python3 setup_kraken_master.py` - Interactive setup wizard

### Manual Setup (5 minutes)

1. **Get Kraken API credentials:**
   - Log in to Kraken: https://www.kraken.com/u/security/api
   - Click "Generate New Key"
   - Name it "NIJA Trading Bot - Master"
   - Enable permissions:
     - ✅ Query Funds
     - ✅ Query Open Orders & Trades
     - ✅ Query Closed Orders & Trades
     - ✅ Create & Modify Orders
     - ✅ Cancel/Close Orders
   - Save both the API key and private key

2. **Add to `.env` file (local) OR Railway/Render (production):**
   ```bash
   KRAKEN_MASTER_API_KEY=your-master-api-key
   KRAKEN_MASTER_API_SECRET=your-master-private-key
   ```

3. **Restart NIJA**

You should now see:
```
📊 KRAKEN (Master):
   ✅ Configured (Key: 56 chars, Secret: 88 chars)
```

**For Railway/Render deployments:** See SETUP_MASTER_KRAKEN.md for platform-specific instructions.

---

## Enabling User Accounts

User accounts allow NIJA to manage multiple trading accounts independently. This is useful for:
- Managing funds for multiple investors
- Separating personal and business trading
- Pro-tier features with isolated accounts

### Why You See "No user accounts configured"

If you see:
```
⚪ No user accounts configured
```

This is **normal and expected** when user accounts are disabled in the configuration files. User accounts are completely optional - NIJA works perfectly with just the master account.

User accounts in `config/users/*.json` files are **disabled by default** (`"enabled": false`) and should only be enabled after:
1. You have API credentials for that user
2. You've added those credentials to your environment variables
3. You want NIJA to manage that account

### To Enable User #1 (Daivon Frazier)

1. **Get Kraken API credentials:**
   - Log in to Kraken: https://www.kraken.com/u/security/api
   - Click "Generate New Key"
   - Name it "NIJA Trading Bot - Daivon"
   - Enable permissions:
     - ✅ Query Funds
     - ✅ Query Open Orders & Trades
     - ✅ Query Closed Orders & Trades
     - ✅ Create & Modify Orders
     - ✅ Cancel/Close Orders
   - Save both the API key and private key

2. **Add to `.env` file:**
   ```bash
   KRAKEN_USER_DAIVON_API_KEY=your-daivon-api-key
   KRAKEN_USER_DAIVON_API_SECRET=your-daivon-private-key
   ```

3. **Enable the user in config file:**
   Edit `config/users/retail_kraken.json` and change Daivon's `"enabled"` from `false` to `true`:
   ```json
   {
     "user_id": "daivon_frazier",
     "name": "Daivon Frazier",
     "account_type": "retail",
     "broker_type": "kraken",
     "enabled": true,
     "description": "Retail user - Kraken crypto account"
   }
   ```

4. **Restart NIJA:**
   ```bash
   python3 bot.py
   ```

You should now see:
```
✅ USER: Daivon Frazier: TRADING (Broker: Kraken)
```

### To Enable User #2 (Tania Gilbert)

Follow the same process as User #1:

1. Get Kraken API credentials for Tania
2. Add to `.env` file:
   ```bash
   KRAKEN_USER_TANIA_API_KEY=your-tania-api-key
   KRAKEN_USER_TANIA_API_SECRET=your-tania-private-key
   ```
3. Enable in `config/users/retail_kraken.json` by changing `"enabled"` to `true`
4. Restart NIJA

### Verify Configuration

Run the verification script:
```bash
python3 kraken_deployment_verify.py
```

Expected output when all accounts are configured:
```
✅ Master Account: READY to trade on Kraken
✅ User #1 (Daivon Frazier): READY to trade on Kraken
✅ User #2 (Tania Gilbert): READY to trade on Kraken
```

---

## Troubleshooting

### "NOT TRADING (Connection failed or not configured)"

**This is normal** if you haven't configured that account yet. User accounts are optional.

**To fix (if you want that account to trade):**
1. Get API credentials from Kraken
2. Add them to `.env` file
3. Restart NIJA

**To ignore:** If you don't need user accounts, you can safely ignore these messages. NIJA will trade with the master account only.

### "Invalid nonce" errors

Already fixed in the code! If you still see this:
1. Make sure each account uses separate API keys
2. Don't share API keys between accounts
3. Check that system clock is accurate

### "Permission denied" errors

Your API key doesn't have the required permissions:
1. Go to https://www.kraken.com/u/security/api
2. Edit your API key
3. Enable all required permissions (see list above)
4. Save and restart NIJA

### Environment variables not loading

1. Make sure `.env` file exists in the project root
2. Check there are no syntax errors in `.env`
3. Verify python-dotenv is installed: `pip install python-dotenv`
4. Try loading environment manually:
   ```bash
   export $(cat .env | xargs)
   python3 bot.py
   ```

### Still having issues?

1. Check the main README.md for detailed setup instructions
2. Review KRAKEN_ENV_VARS_REFERENCE.md for variable names
3. See MULTI_USER_SETUP_GUIDE.md for advanced multi-user setup
4. Open an issue on GitHub with your error logs (remove API keys!)

---

## Deployment to Production

For deploying to Railway or Render:

1. **Railway:**
   - Go to https://railway.app
   - Create new project from GitHub repo
   - Add environment variables in Variables tab
   - See: KRAKEN_ENV_VARS_REFERENCE.md for exact variable names

2. **Render:**
   - Go to https://render.com
   - Create new Web Service from GitHub repo
   - Add environment variables in Environment tab
   - See: KRAKEN_ENV_VARS_REFERENCE.md for exact variable names

3. **Verify deployment:**
   ```bash
   python3 kraken_deployment_verify.py
   ```

---

## Security Best Practices

⚠️ **IMPORTANT:**
- Never commit `.env` file to git (already in .gitignore)
- Never share API keys publicly
- Enable 2FA on all exchange accounts
- Use IP whitelisting on API keys when possible
- Use minimum required permissions for API keys
- Store credentials in a password manager
- Rotate API keys regularly

---

## Next Steps

Once NIJA is running:

1. **Monitor the logs** to see trading activity
2. **Check account balances** regularly
3. **Review strategy documentation** in APEX_V71_DOCUMENTATION.md
4. **Adjust parameters** in your `.env` if needed
5. **Set up TradingView webhooks** (see TRADINGVIEW_SETUP.md)

---

## Summary

**Minimum setup for trading:**
- ✅ Coinbase master account credentials
- ✅ Run `python3 bot.py`

**Optional user accounts:**
- Add Kraken credentials for User #1 and/or User #2
- Each user trades independently with their own balance

**The "NOT TRADING" messages are normal** if you haven't configured those accounts. NIJA will work fine with just the master account!

---

**Need help?** See the documentation in:
- README.md - Main documentation
- KRAKEN_ENV_VARS_REFERENCE.md - Environment variable reference
- MULTI_USER_SETUP_GUIDE.md - Advanced multi-user setup
- APEX_V71_DOCUMENTATION.md - Trading strategy details
