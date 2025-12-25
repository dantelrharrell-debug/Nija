# 🔍 Where Did My Money Go? - Coinbase Investigation Guide

**Current Situation:** Your bot shows $0.00 balance, but you mentioned having "over $50"

**CRITICAL FACT:** The bot never executed any trades (all 124+ attempts failed). So if money is missing, it went somewhere else.

---

## Step 1: Log Into Coinbase Advanced Trade

1. Go to: **https://advanced.coinbase.com/**
2. Sign in with your credentials
3. Make sure you're on the **same account** your API keys are connected to

---

## Step 2: Check Your Current Balance

### Quick Balance Check:
1. Look at the **top right corner** - your USD balance is displayed there
2. Click **"Portfolio"** in the left sidebar
3. Look for **"USD"** in your asset list

### What to Look For:
- **If it shows $0.00:** Money was withdrawn or transferred
- **If it shows $50+:** There's a disconnect between API and web interface (portfolio issue)
- **If it shows $5-6:** Matches what logs showed earlier

---

## Step 3: Check Transaction History

### Option A: Portfolio View
1. Click **"Portfolio"** (left sidebar)
2. Click on **"USD"** in your asset list
3. Click **"View transactions"** or **"Transaction history"**

### Option B: Orders & Transactions
1. Click **"Orders"** (left sidebar)
2. Look at the tabs:
   - **"Open orders"** - Currently active orders (should be empty)
   - **"Filled orders"** - Completed trades
   - **"Order history"** - All orders including cancelled

### What You're Looking For:

#### 🔴 **Failed Orders (Expected)**
- Look for orders with status: **"Cancelled"** or **"Failed"**
- Reason: **"Insufficient funds"**
- These are the 124+ attempts your bot made
- **These did NOT cost you money** (they never executed)

#### 🟢 **Filled Orders (Unexpected)**
- Look for orders with status: **"Filled"** or **"Completed"**
- If you see ANY filled orders:
  - **Note the date/time** - Were they from your bot or manual?
  - **Note the amounts** - How much USD was spent?
  - **Check if they were profitable** - Compare buy vs sell prices

---

## Step 4: Check Transfers & Withdrawals

### Transfers Tab:
1. Click your **profile icon** (top right)
2. Click **"Transactions"** or **"Activity"**
3. Filter by:
   - **"Transfers"** - Money moved between accounts
   - **"Withdrawals"** - Money sent to bank/wallet
   - **"Deposits"** - Money received

### What to Look For:

#### Recent Withdrawals:
```
Date          | Type         | Amount    | Destination
------------- | ------------ | --------- | ---------------------
2025-12-XX    | Withdrawal   | $45.00    | Bank account ****1234
2025-12-XX    | Transfer     | $50.00    | Coinbase Wallet
```

#### Common Scenarios:
- **Bank Withdrawal:** You cashed out to your bank account
- **Wallet Transfer:** You moved funds to Coinbase Wallet or another wallet
- **Convert/Swap:** You traded USD for crypto manually
- **Send:** You sent crypto to another address (converted USD to crypto first)

---

## Step 5: Check for Manual Trades

### In Advanced Trade Interface:
1. Click **"Trade"** (left sidebar)
2. Click **"Order history"** at the bottom
3. Look for orders YOU placed manually (not the bot)

### Time Range to Check:
- Last **7 days** - Most likely period
- Last **30 days** - To be thorough
- Since you **started the bot** - Complete picture

### Questions to Answer:
1. Did you manually buy any crypto in the last week?
2. Did you test a trade manually before starting the bot?
3. Did you sell any crypto recently?

---

## Step 6: Check Coinbase Consumer (Regular Coinbase)

**IMPORTANT:** You might have TWO separate Coinbase accounts:
1. **Coinbase Advanced Trade** (for trading)
2. **Coinbase Consumer** (regular Coinbase app/website)

### Check Regular Coinbase:
1. Go to: **https://www.coinbase.com/**
2. Sign in
3. Click **"Portfolio"**
4. Check if your USD is there instead

### Why This Matters:
- Your API keys might be for Advanced Trade
- But your USD might be in Consumer account
- They're **separate balances** even though same login

### How to Transfer:
If you find USD in Consumer account:
1. Click **"Send & Receive"**
2. Select **"Transfer"**
3. Choose **"To Advanced Trade"**
4. Transfer USD to Advanced Trade
5. Wait 1-2 minutes and check bot again

---

## Step 7: Download Transaction CSV (Detailed Report)

### Get Complete Transaction History:
1. Go to **Settings** (profile icon → Settings)
2. Click **"Statements"** or **"Reports"**
3. Select **"Generate report"**
4. Choose:
   - **Date range:** Last 30-60 days
   - **Format:** CSV or PDF
   - **Account:** All accounts or USD specifically
5. Download and review

### What the CSV Shows:
- Every transaction (trades, transfers, deposits, withdrawals)
- Exact timestamps
- Amounts in and out
- Running balance
- Fee breakdowns

---

## Expected Findings & What They Mean

### Scenario 1: All Orders Show "Insufficient Funds"
✅ **This is what we expect**
- Bot attempted trades but couldn't execute
- No money lost from trading
- Balance disappeared another way

### Scenario 2: You See Filled Orders from the Bot
⚠️ **Unexpected but possible**
- Bot DID execute some trades
- Need to calculate profit/loss
- Check if trades were profitable

### Scenario 3: You See Manual Trades
💡 **Common scenario**
- You tested trading manually
- These trades may have lost money
- Not related to the bot

### Scenario 4: You See Withdrawals
✅ **This explains missing money**
- You withdrew funds to bank
- You transferred to wallet
- Money is safe, just not in trading account

### Scenario 5: You See Conversions to Crypto
💡 **Money converted, not lost**
- USD → Bitcoin/Ethereum/etc.
- Check if those crypto holdings are profitable
- Crypto value may be up or down

---

## What to Do Based on What You Find

### If You Withdrew Money:
- ✅ Money is safe in your bank/wallet
- To resume trading: Deposit $50-$100 back into Coinbase USD

### If You Made Manual Trades That Lost Money:
- ⚠️ Those trades caused the loss (not the bot)
- Review why those trades failed
- Deposit more funds to continue

### If Money is in Consumer Account:
- ✅ Transfer it to Advanced Trade
- Bot should start working immediately

### If You Converted to Crypto:
- 💰 Check the current value of that crypto
- If profitable: Sell back to USD
- If losing: Hold or sell based on strategy

### If Nothing Explains the Missing Money:
- 🚨 Contact Coinbase Support immediately
- Provide transaction IDs
- Request account review

---

## Quick Checklist

Use this checklist as you investigate:

- [ ] Logged into Coinbase Advanced Trade
- [ ] Checked current USD balance (Portfolio → USD)
- [ ] Reviewed filled orders (Orders → Filled)
- [ ] Reviewed cancelled/failed orders
- [ ] Checked withdrawals (Profile → Transactions)
- [ ] Checked transfers between accounts
- [ ] Logged into Coinbase Consumer
- [ ] Checked if USD is in Consumer account
- [ ] Reviewed manual trades you may have made
- [ ] Downloaded transaction report (CSV)
- [ ] Identified where the $45-50 went

---

## After You Find the Answer

### Report Back With:
1. **Current balance location:**
   - Advanced Trade: $___
   - Consumer: $___
   - Total: $___

2. **Where money went:**
   - [ ] Withdrawn to bank
   - [ ] Transferred to wallet
   - [ ] Converted to crypto (which coin: ___)
   - [ ] Lost in manual trades
   - [ ] Still investigating

3. **Filled orders count:**
   - Bot trades executed: ___
   - Manual trades: ___
   - Failed/cancelled: ___ (expected: 124+)

### Next Steps:
Once we know where the money is, I can help you:
- Transfer it back to trading account
- Adjust bot settings for your capital
- Calculate optimal position sizes
- Set up proper risk management

---

## 🆘 Need Help?

If you can't find the information or need help interpreting what you see, share:
- Screenshot of your Portfolio page (hide sensitive info)
- Transaction count from last 30 days
- Any large transactions you see

I'll help you trace exactly where your funds went.
