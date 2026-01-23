# Copy Trading Activation Checklist

## ✅ Quick Verification: Is Copy Trading Active?

Use this checklist to verify that copy trading is active and working correctly.

## Step 1: Check Environment Configuration

### Option A: Check Your `.env` File

Open your `.env` file and verify:

```bash
COPY_TRADING_MODE=MASTER_FOLLOW
```

**Expected:** This line should be **uncommented** (no `#` at the start)

### Option B: Use Default Templates

If you're using one of the provided templates, copy trading is **already enabled**:
- ✅ `.env.example`
- ✅ `.env.copy_trading_example`
- ✅ `.env.small_account_preset`
- ✅ `.env.saver_tier`
- ✅ `.env.investor_tier`
- ✅ `.env.income_tier`
- ✅ `.env.livable_tier`
- ✅ `.env.baller_tier`

## Step 2: Check Startup Logs

When you start the bot, look for these log messages:

### ✅ SUCCESS - Copy Trading is Active:

```
🔄 Starting copy trade engine in MASTER_FOLLOW MODE...
   📋 Mode: MASTER_FOLLOW (mirror master trades)
   📊 Allocation: Proportional (auto-scaled by balance)
   ✅ Copy trade engine started in ACTIVE MODE
   📡 Users will receive and execute copy trades from master accounts
   💰 User position sizes will be scaled based on account balance ratios
```

**If you see these messages:** Copy trading is **ACTIVE** ✅

### ❌ FAIL - Copy Trading is NOT Active:

```
🔄 Copy trading mode: INDEPENDENT
   ℹ️  Users will trade independently (copy trading disabled)
   ℹ️  Set COPY_TRADING_MODE=MASTER_FOLLOW to enable copy trading
```

**If you see these messages:** Copy trading is **NOT ACTIVE** ❌
- **Fix:** Set `COPY_TRADING_MODE=MASTER_FOLLOW` in your `.env` file

## Step 3: Verify User Accounts are Configured

Check that user accounts are properly configured in `config/users/`:

### For Kraken Users:

File: `config/users/retail_kraken.json`

```json
[
  {
    "user_id": "daivon_frazier",
    "name": "Daivon Frazier",
    "account_type": "retail",
    "broker_type": "kraken",
    "enabled": true,              // ✅ Must be true
    "copy_from_master": true,     // ✅ Must be true
    "disabled_symbols": ["XRP-USD"],
    "description": "Retail user - Kraken crypto account (copy trading enabled)"
  }
]
```

**Required Fields:**
- ✅ `"enabled": true` - User account is active
- ✅ `"copy_from_master": true` - Copy trading enabled for this user
- ✅ `"broker_type": "kraken"` - Matches the broker

### For Individual User Files:

Files: `config/users/daivon_frazier.json`, `config/users/tania_gilbert.json`

```json
{
  "name": "Daivon Frazier",
  "broker": "kraken",
  "role": "user",
  "enabled": true,              // ✅ Must be true
  "copy_from_master": true,     // ✅ Must be true
  "risk_multiplier": 1.0,
  "disabled_symbols": ["XRP-USD"]
}
```

## Step 4: Verify User API Credentials

User accounts need their own API credentials in the `.env` file:

### For Kraken Users:

```bash
# User: Daivon Frazier
KRAKEN_USER_DAIVON_API_KEY=your_api_key_here
KRAKEN_USER_DAIVON_API_SECRET=your_api_secret_here

# User: Tania Gilbert
KRAKEN_USER_TANIA_API_KEY=your_api_key_here
KRAKEN_USER_TANIA_API_SECRET=your_api_secret_here
```

**Format:** `KRAKEN_USER_{FIRSTNAME}_API_KEY`
- The `{FIRSTNAME}` is extracted from the `user_id` (part before underscore, uppercase)
- Example: `user_id: "daivon_frazier"` → `KRAKEN_USER_DAIVON_*`

### For Coinbase Users:

```bash
# User credentials follow similar pattern
COINBASE_USER_{FIRSTNAME}_API_KEY=...
COINBASE_USER_{FIRSTNAME}_API_SECRET=...
```

### For Alpaca Users:

```bash
ALPACA_USER_{FIRSTNAME}_API_KEY=...
ALPACA_USER_{FIRSTNAME}_API_SECRET=...
ALPACA_USER_{FIRSTNAME}_PAPER=true
```

## Step 5: Watch for Copy Trade Execution

When the master account executes a trade, you should see logs like:

```
🔔 RECEIVED MASTER ENTRY SIGNAL
═══════════════════════════════════════════════════════════════════
   Symbol: BTC-USD
   Side: BUY
   Size: 50.0 (quote)
   Broker: kraken
═══════════════════════════════════════════════════════════════════
🔄 Copying trade to 2 user account(s)...
   🔄 Copying to user: daivon_frazier
      User Balance: $100.00
      Master Balance: $1000.00
      Calculated Size: 5.0 (quote)
      Scale Factor: 0.1000 (10.00%)
      📤 Placing BUY order...
      ══════════════════════════════════════════════════
      🟢 COPY TRADE SUCCESS
      ══════════════════════════════════════════════════
      User: daivon_frazier
      ✅ Trade executed in your KRAKEN account
      Order ID: XXXXX-XXXXX-XXXXXX
      Symbol: BTC-USD
      Side: BUY
      Size: 5.0 (quote)
      Order Status: filled
      ══════════════════════════════════════════════════
```

**If you see these logs:** Users are successfully executing copy trades! ✅

## Step 6: Verify Trades in Exchange

Users should see their trades in their exchange accounts:

### Kraken:
1. Go to https://www.kraken.com
2. Navigate to **Trade** → **History**
3. Look for recent orders matching the master's trades

### Coinbase:
1. Go to https://www.coinbase.com
2. Navigate to **Portfolio** → **Transactions**
3. Look for recent trades

## Common Issues and Solutions

### Issue 1: Copy Trading Not Starting

**Symptom:** See "INDEPENDENT" mode in logs

**Solution:**
1. Check your `.env` file
2. Ensure `COPY_TRADING_MODE=MASTER_FOLLOW` is **uncommented**
3. Restart the bot

### Issue 2: Users Skipped in Copy Trading

**Symptom:** See "⏭️ {user}: No kraken account configured" in logs

**Solution:**
1. Verify user configuration in `config/users/retail_kraken.json`
2. Check `"broker_type": "kraken"` matches the master's broker
3. Ensure `"enabled": true` and `"copy_from_master": true`

### Issue 3: User Broker Not Connected

**Symptom:** See "⚠️ {user}: kraken not connected - skipping"

**Solution:**
1. Verify user API credentials in `.env` file
2. Check API key format: `KRAKEN_USER_{FIRSTNAME}_API_KEY`
3. Ensure API credentials have correct permissions
4. Restart the bot to reconnect

### Issue 4: Position Size Too Small (Dust)

**Symptom:** See "⚠️ Skipping dust position: Position size $0.50 below dust threshold $1.00"

**Solution:**
1. User account balance might be too small
2. Master position might be too small for scaling
3. Consider funding the user account with more capital
4. This is a safety feature - positions below $1 are skipped

### Issue 5: Master Not Connected

**Symptom:** See "⚠️ KRAKEN MASTER offline - skipping copy trading"

**Solution:**
1. Verify master API credentials in `.env` file
2. Check: `KRAKEN_MASTER_API_KEY` and `KRAKEN_MASTER_API_SECRET`
3. Ensure master credentials have correct permissions
4. Restart the bot to reconnect

## Summary Checklist

Use this quick checklist to verify everything is set up:

- [ ] ✅ `COPY_TRADING_MODE=MASTER_FOLLOW` in `.env` (uncommented)
- [ ] ✅ User accounts configured in `config/users/` with `enabled: true`
- [ ] ✅ User accounts have `copy_from_master: true`
- [ ] ✅ User API credentials added to `.env` file
- [ ] ✅ Bot shows "MASTER_FOLLOW MODE" in startup logs
- [ ] ✅ Bot shows "✅ Copy trade engine started in ACTIVE MODE"
- [ ] ✅ Master trades generate copy trade logs
- [ ] ✅ Users see "🟢 COPY TRADE SUCCESS" logs
- [ ] ✅ Trades appear in user exchange accounts

**All checked?** Copy trading is fully active! 🎉

## Need Help?

See these guides for more information:
- 📚 [COPY_TRADING_SETUP.md](COPY_TRADING_SETUP.md) - Complete setup guide
- 📋 [.env.copy_trading_example](.env.copy_trading_example) - Example configuration
- 📖 [.env.example](.env.example) - All configuration options
- 👥 [USER_MANAGEMENT.md](USER_MANAGEMENT.md) - User account setup
