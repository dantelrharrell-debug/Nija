# Quick Start: OKX and Kraken Multi-Broker Trading

**🎯 Goal**: Connect NIJA to both OKX and Kraken for independent multi-broker trading

**⏱️ Time Required**: 10-15 minutes

**📍 Current Status**: 
- ✅ Code fully implemented
- ✅ SDKs installed
- ✅ Multi-broker trading enabled
- ⚠️ Awaiting API credentials

---

## 🚦 Current Funding Status

Based on your requirements:

| Broker | Funding Status | Action Required |
|--------|---------------|-----------------|
| **Kraken** | 🟢 **FUNDED** | Add API credentials to start trading |
| **OKX** | 🔴 **NOT FUNDED** | Add credentials (optional) + transfer funds |

---

## 📝 Quick Setup Steps

### Step 1: Get Kraken API Credentials (REQUIRED)

**Your Kraken account has funds and is ready to trade!**

1. Go to: https://www.kraken.com/u/security/api
2. Click "Generate New Key"
3. Set permissions:
   - ✅ Query Funds
   - ✅ Query Open Orders & Trades
   - ✅ Query Closed Orders & Trades
   - ✅ Create & Modify Orders
   - ✅ Cancel/Close Orders
   - ❌ **DO NOT** enable Withdraw Funds
4. Copy API Key and Private Key

### Step 2: Get OKX API Credentials (OPTIONAL - Not Funded)

**Your OKX account does NOT have funds yet.**

Only do this if you plan to transfer funds to OKX:

1. Go to: https://www.okx.com/account/my-api
2. Click "Create API Key"
3. Set permissions:
   - ✅ Trade
   - ❌ **DO NOT** enable Withdrawal
4. Copy API Key, Secret Key, and Passphrase

### Step 3: Add Credentials to .env File

Edit the `.env` file in the repository root:

```bash
# Kraken credentials - REQUIRED (account has funds)
KRAKEN_API_KEY=your_actual_kraken_api_key_here
KRAKEN_API_SECRET=your_actual_kraken_private_key_here

# OKX credentials - OPTIONAL (no funds currently)
# Only add if you plan to fund this account
OKX_API_KEY=your_actual_okx_api_key_here
OKX_API_SECRET=your_actual_okx_secret_here
OKX_PASSPHRASE=your_actual_okx_passphrase_here
OKX_USE_TESTNET=false

# Multi-Broker Independent Trading (already enabled)
MULTI_BROKER_INDEPENDENT=true
```

**Security Note**: Never commit the `.env` file to git!

### Step 4: Validate Configuration

Run the validation script:

```bash
python3 validate_multi_broker_readiness.py
```

**Expected Output (with Kraken credentials):**
```
✅ Kraken API Credentials: READY
✅ Kraken SDK Installation: READY
✅ Kraken API Connection: READY
   → USD: $XXX.XX, USDT: $XXX.XX, Total: $XXX.XX
✅ Kraken Funded: READY (minimum: $2.00)
```

### Step 5: Start Trading

Once validation passes, start the bot:

```bash
./start.sh
```

**What happens:**
1. Bot connects to Kraken ✅
2. Bot detects Kraken is funded ✅
3. Bot starts trading on Kraken ✅
4. Bot skips OKX (no credentials or not funded) ⏭️

---

## 🎯 What Will Happen With This Setup

### Immediate (After Adding Kraken Credentials)

**Kraken Trading: ✅ ACTIVE**
- Will connect and start trading immediately
- Uses funds already in your Kraken account
- Trades cryptocurrency pairs (BTC-USD, ETH-USD, etc.)
- Operates in isolated thread (failures won't affect other brokers)

**OKX Trading: ⏸️ INACTIVE**
- Will NOT trade (no funds)
- If credentials added: Will connect but remain idle
- If credentials NOT added: Will be skipped entirely

### Later (If You Want to Add OKX)

1. Add OKX credentials to `.env`
2. Transfer funds to OKX account
3. Restart bot: `./start.sh`
4. OKX will start trading automatically

---

## 🔍 Verification Commands

### Check if Kraken is Connected
```bash
python3 check_kraken_connection_status.py
```

### Check if OKX is Connected
```bash
python3 test_okx_connection.py
```

### Check All Broker Status
```bash
python3 check_broker_status.py
```

### Check Which Brokers Are Trading
```bash
python3 check_active_trading_per_broker.py
```

### View Bot Logs
```bash
tail -f nija.log | grep -E "KRAKEN|OKX|CONNECTED"
```

---

## ⚡ Quick Reference

### Minimum Balance Requirements
- **Absolute Minimum**: $2.00 per broker
- **Recommended**: $25+ per broker for active trading

### API Permissions

**Kraken:**
- ✅ Query Funds
- ✅ Create/Modify/Cancel Orders
- ❌ NO Withdrawal

**OKX:**
- ✅ Trade
- ❌ NO Withdrawal

### Environment Variables

```bash
# Required for Kraken (has funds)
KRAKEN_API_KEY=
KRAKEN_API_SECRET=

# Optional for OKX (no funds)
OKX_API_KEY=
OKX_API_SECRET=
OKX_PASSPHRASE=

# Already configured
MULTI_BROKER_INDEPENDENT=true
```

---

## 🚨 Common Issues & Solutions

### "Kraken connection failed: Invalid API key"
- Double-check API key and secret in `.env`
- Make sure there are no extra spaces
- Verify key hasn't expired on Kraken website

### "Kraken connection failed: Permission denied"
- Check API key permissions on Kraken website
- Ensure all required trading permissions are enabled

### "OKX connection failed: Invalid passphrase"
- Verify passphrase is correct (case-sensitive)
- Passphrase is NOT your account password
- It's the value you set when creating the API key

### "No funded brokers detected"
- Check Kraken account actually has funds
- Verify minimum balance ($2.00)
- Run: `python3 check_kraken_connection_status.py`

---

## 📊 Trading Pairs

### Kraken Supports
- BTC-USD, ETH-USD, SOL-USD, XRP-USD
- ADA-USD, DOT-USD, MATIC-USD, LINK-USD
- 100+ cryptocurrency pairs

### OKX Supports
- BTC-USDT, ETH-USDT, SOL-USDT, XRP-USDT
- ADA-USDT, DOT-USDT, MATIC-USDT, LINK-USDT
- 400+ cryptocurrency pairs

**Note**: Kraken uses USD, OKX uses USDT. The bot handles this automatically.

---

## 🔒 Security Checklist

- [ ] API keys have only necessary permissions (no withdrawal)
- [ ] `.env` file is NOT committed to git (check `.gitignore`)
- [ ] API keys are stored securely
- [ ] IP whitelist enabled on OKX (if using)
- [ ] Starting with reasonable position sizes
- [ ] Monitoring logs regularly

---

## 📚 Additional Documentation

- **Full Status Report**: `OKX_KRAKEN_MULTI_BROKER_STATUS.md`
- **Kraken Details**: `KRAKEN_CONNECTION_STATUS.md`
- **OKX Details**: `OKX_TRADING_READINESS_STATUS.md`
- **Multi-Broker Guide**: `INDEPENDENT_MULTI_BROKER_GUIDE.md`
- **Broker Integration**: `BROKER_INTEGRATION_GUIDE.md`

---

## ✅ Setup Checklist

### Kraken (REQUIRED - Has Funds)
- [ ] Generated API key on Kraken website
- [ ] Set correct permissions (trade only, no withdrawal)
- [ ] Added `KRAKEN_API_KEY` to `.env`
- [ ] Added `KRAKEN_API_SECRET` to `.env`
- [ ] Ran `validate_multi_broker_readiness.py` - passes ✅
- [ ] Started bot with `./start.sh`
- [ ] Verified connection in logs
- [ ] Confirmed trading started

### OKX (OPTIONAL - No Funds)
- [ ] Decided if I want to use OKX
- [ ] Generated API key on OKX website (if using)
- [ ] Added `OKX_API_KEY` to `.env` (if using)
- [ ] Added `OKX_API_SECRET` to `.env` (if using)
- [ ] Added `OKX_PASSPHRASE` to `.env` (if using)
- [ ] Transferred funds to OKX account (if using)
- [ ] Verified connection in logs (if using)

---

## 🎉 Summary

**What You Have:**
- ✅ Kraken broker fully implemented and ready
- ✅ OKX broker fully implemented and ready
- ✅ Multi-broker independent trading enabled
- ✅ All SDKs installed
- ✅ Kraken account funded and ready to trade

**What You Need:**
1. Add Kraken API credentials to `.env`
2. Run validation script
3. Start the bot
4. Start trading!

**Expected Time to Trading**: 10-15 minutes after credentials are added

---

## 🆘 Need Help?

Run this command for comprehensive validation:
```bash
python3 validate_multi_broker_readiness.py
```

Check current status:
```bash
python3 check_broker_status.py
```

View detailed instructions:
```bash
cat OKX_KRAKEN_MULTI_BROKER_STATUS.md
```

---

**Last Updated**: January 8, 2026  
**Status**: ⏳ Awaiting Kraken API credentials  
**Next Step**: Add Kraken credentials to `.env` file
