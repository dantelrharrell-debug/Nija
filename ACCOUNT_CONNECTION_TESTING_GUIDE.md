# Account Connection Testing Guide

**Date:** January 18, 2026  
**Purpose:** Comprehensive testing of master and user account connections

---

## Overview

This guide explains how to test and verify:
1. **Master trading account** connection status
2. **All user accounts** connection status  
3. **Active trade execution** readiness on Kraken
4. **Trade history preservation** on Coinbase

## Available Test Scripts

### 1. Master and User Connection Test

**Script:** `test_master_and_user_connections.py`

Tests all configured accounts (master + users) across all exchanges (Coinbase, Kraken, Alpaca, OKX, Binance).

**Usage:**
```bash
python3 test_master_and_user_connections.py
```

**What it checks:**
- ✅ Credential configuration for each account
- ✅ API connection status
- ✅ Account balance retrieval
- ✅ Master account vs user account separation
- ✅ Multi-exchange support

**Output:**
- Console report with detailed status
- `connection_test_results.json` file

---

### 2. Coinbase Trade History Verification

**Script:** `verify_coinbase_trade_history.py`

Verifies that NIJA preserves ALL trade records, including losing trades (doesn't "get rid of" them).

**Usage:**
```bash
python3 verify_coinbase_trade_history.py
```

**What it checks:**
- ✅ Trade journal integrity
- ✅ Losing trades are recorded (not deleted)
- ✅ 30-minute losing trade exit logic is implemented
- ✅ Trade history preservation

**Output:**
- Console report with trade statistics
- `coinbase_trade_history_report.json` file

---

### 3. Kraken Execution Readiness

**Script:** `verify_kraken_execution_ready.py`

Verifies Kraken is ready for active trade execution.

**Usage:**
```bash
python3 verify_kraken_execution_ready.py
```

**What it checks:**
- ✅ Kraken broker implementation
- ✅ API credentials configuration
- ✅ Trading configuration (profit targets, stop loss, etc.)
- ✅ Multi-account support
- ✅ Live API connection test

**Output:**
- Console report with readiness score
- `kraken_execution_readiness_report.json` file

---

## Current Status (No Credentials Configured)

### Master Accounts
| Exchange | Credentials | Connection | Status |
|----------|------------|------------|--------|
| Coinbase | ❌ Not set | ⏭️ Skipped | Need API keys |
| Kraken | ❌ Not set | ⏭️ Skipped | Need API keys |
| Alpaca | ❌ Not set | ⏭️ Skipped | Need API keys |
| OKX | ❌ Not set | ⏭️ Skipped | Need API keys |
| Binance | ❌ Not set | ⏭️ Skipped | Need API keys |

### User Accounts
| User | Exchange | Enabled | Credentials | Status |
|------|----------|---------|-------------|--------|
| Daivon Frazier | Kraken | ✅ Yes | ❌ Not set | Need API keys |
| Tania Gilbert | Kraken | ✅ Yes | ❌ Not set | Need API keys |

### Kraken Execution Readiness
| Component | Status | Notes |
|-----------|--------|-------|
| Broker Implementation | ✅ Complete | All code ready |
| Configuration | ✅ Complete | Settings configured |
| Multi-Account Support | ✅ Ready | 2 users configured |
| Master Credentials | ❌ Missing | KRAKEN_MASTER_API_KEY/SECRET |
| User Credentials | ❌ Missing | Need keys for users |

**Readiness Score:** 3/4 (75%) - Only credentials missing

### Coinbase Trade History
| Aspect | Status | Notes |
|--------|--------|-------|
| Trade Journal | ✅ Exists | 77 records, 10KB |
| Losing Trade Exit Logic | ✅ Implemented | 30-minute max hold |
| History Preservation | ✅ Verified | All trades preserved |
| Coinbase Trades | ℹ️ None yet | No Coinbase trades recorded |

---

## How to Configure Credentials

### For Coinbase

1. **Get API Keys:**
   - Log in to Coinbase: https://www.coinbase.com/
   - Go to Settings → API
   - Create new API key with trading permissions

2. **Set Environment Variables:**
   ```bash
   # Master account
   COINBASE_MASTER_API_KEY=your-api-key
   COINBASE_MASTER_API_SECRET=your-api-secret
   ```

3. **Deploy/Restart:**
   - For Railway: Add to Variables tab
   - For Render: Add to Environment tab
   - For local: Add to `.env` file

### For Kraken

1. **Get API Keys:**
   - Log in to Kraken: https://www.kraken.com/u/security/api
   - Create new **Classic API Key** (NOT OAuth)
   - Enable permissions:
     - ✅ Query Funds
     - ✅ Query Open Orders & Trades
     - ✅ Query Closed Orders & Trades
     - ✅ Create & Modify Orders
     - ✅ Cancel/Close Orders
     - ❌ Do NOT enable "Withdraw Funds" (security)

2. **Set Environment Variables:**
   ```bash
   # Master account
   KRAKEN_MASTER_API_KEY=your-api-key
   KRAKEN_MASTER_API_SECRET=your-api-secret
   
   # User: Daivon Frazier
   KRAKEN_USER_DAIVON_API_KEY=daivon-api-key
   KRAKEN_USER_DAIVON_API_SECRET=daivon-api-secret
   
   # User: Tania Gilbert
   KRAKEN_USER_TANIA_API_KEY=tania-api-key
   KRAKEN_USER_TANIA_API_SECRET=tania-api-secret
   ```

3. **Deploy/Restart** (same as Coinbase)

---

## Testing Workflow

### Initial Testing (No Credentials)
```bash
# 1. Test all connections (shows what's missing)
python3 test_master_and_user_connections.py

# 2. Verify Coinbase trade history preservation
python3 verify_coinbase_trade_history.py

# 3. Check Kraken execution readiness
python3 verify_kraken_execution_ready.py
```

**Expected Results:**
- ❌ No accounts connected (no credentials)
- ✅ Trade history preservation verified
- ⚠️ Kraken 75% ready (only credentials missing)

### After Configuring Credentials
```bash
# 1. Test connections again
python3 test_master_and_user_connections.py

# 2. Verify Kraken is fully ready
python3 verify_kraken_execution_ready.py
```

**Expected Results:**
- ✅ Configured accounts connected
- ✅ Account balances retrieved
- ✅ Kraken 100% ready for trading

---

## Understanding Test Results

### Connection Test Results

**File:** `connection_test_results.json`

```json
{
  "timestamp": "2026-01-18T14:20:04.381904",
  "master_accounts": {
    "KRAKEN_MASTER": {
      "credentials": {
        "configured": true,
        "api_key": "ABC12345...XYZ9",
        "api_secret": "***CONFIGURED***"
      },
      "connection": {
        "connected": true,
        "account_info": {
          "balance": 1000.00,
          "available": 950.00,
          "currency": "USD"
        }
      }
    }
  },
  "user_accounts": { ... }
}
```

### Kraken Readiness Report

**File:** `kraken_execution_readiness_report.json`

Shows detailed status of:
- Implementation files
- Credential status
- Configuration settings
- Multi-account support
- Connection test results

### Trade History Report

**File:** `coinbase_trade_history_report.json`

Shows:
- Total trades (winning/losing/breakeven)
- P&L statistics
- Exit logic verification
- Trade preservation confirmation

---

## Troubleshooting

### Issue: "No accounts connected"

**Cause:** No API credentials configured

**Solution:**
1. Get API keys from exchange websites
2. Set environment variables (see above)
3. Restart bot
4. Run tests again

### Issue: "Connection failed - Check credentials"

**Possible causes:**
- Wrong API key or secret
- Insufficient permissions on API key
- API key disabled or revoked
- Network/firewall blocking connection

**Solution:**
1. Verify credentials are correct
2. Check API key permissions on exchange
3. Try regenerating API keys
4. Test internet connectivity

### Issue: "SDK not installed"

**Cause:** Required Python packages not installed

**Solution:**
```bash
pip install -r requirements.txt
```

For specific exchanges:
- Coinbase: `pip install coinbase-advanced-py`
- Kraken: `pip install krakenex pykrakenapi`
- Alpaca: `pip install alpaca-py`

### Issue: Kraken "Permission denied"

**Cause:** API key doesn't have required permissions

**Solution:**
1. Go to Kraken API settings
2. Edit API key permissions
3. Enable all trading permissions (except "Withdraw Funds")
4. Save and test again

---

## What Each Test Verifies

### Master and User Connections Test
✅ Verifies master account can connect to each exchange  
✅ Verifies user accounts can connect to their exchanges  
✅ Tests actual API connectivity (not just credential check)  
✅ Retrieves account balances to confirm access  
✅ Identifies which accounts are ready for trading  

### Coinbase Trade History Test
✅ Confirms trade journal exists and is readable  
✅ Proves losing trades are NOT deleted from history  
✅ Verifies 30-minute losing trade exit logic is implemented  
✅ Shows trade statistics (winning vs losing)  
✅ Ensures all trades are preserved permanently  

### Kraken Execution Readiness Test
✅ Confirms Kraken broker code is fully implemented  
✅ Checks all required configuration files exist  
✅ Verifies profit targets, stop loss, fees are configured  
✅ Tests multi-account support (master + users)  
✅ Provides readiness score and actionable next steps  

---

## FAQ

### Q: Why are no credentials configured?
**A:** This is a fresh environment. Credentials must be added via environment variables for security.

### Q: Which exchange should I configure first?
**A:** Configure **Kraken** first - it has:
- Lower fees (0.36% vs 1.4% Coinbase)
- More profit opportunities
- Better for small accounts
- Multi-account support ready

### Q: Are losing trades deleted from history?
**A:** **NO**. All trades (winning and losing) are preserved in `trade_journal.jsonl`. The 30-minute exit logic limits how long you HOLD losing positions, but the records are kept.

### Q: What's the difference between master and user accounts?
**A:**
- **Master Account:** NIJA system account (your main trading account)
- **User Accounts:** Individual investor accounts (Daivon, Tania, etc.)
- Each has separate API credentials and trades independently

### Q: Can I test without real money?
**A:** Yes! Many exchanges offer paper trading:
- Alpaca: Built-in paper trading mode
- Kraken Futures: Demo account (https://demo-futures.kraken.com)
- Coinbase: Advanced Trade sandbox (limited availability)

### Q: How do I know if trading is working?
**A:** After configuring credentials:
1. Run `python3 test_master_and_user_connections.py`
2. Check for ✅ "Connected successfully"
3. Monitor logs for trade activity
4. Check `trade_journal.jsonl` for new records

---

## Next Steps

1. **Immediate:** Run all three test scripts to see current status
2. **Short-term:** Configure Kraken credentials (highest priority)
3. **Medium-term:** Configure Coinbase credentials
4. **Optional:** Configure additional exchanges (Alpaca, OKX, Binance)

---

## Related Documentation

- `KRAKEN_SETUP_GUIDE.md` - Complete Kraken setup instructions
- `COMPLETE_BROKER_STATUS_REPORT.md` - Comprehensive status report
- `COINBASE_LOSING_TRADES_SOLUTION.md` - 30-minute exit logic details
- `.env.example` - Environment variable reference
- `MULTI_EXCHANGE_TRADING_GUIDE.md` - Multi-exchange setup

---

## Support

If you encounter issues:
1. Check the troubleshooting section above
2. Run diagnostic scripts: `check_trading_status.py`, `diagnose_kraken_status.py`
3. Review logs for error messages
4. See exchange-specific documentation files

---

**Last Updated:** January 18, 2026  
**Test Scripts Version:** 1.0  
**Status:** All infrastructure ready - credentials needed for activation
