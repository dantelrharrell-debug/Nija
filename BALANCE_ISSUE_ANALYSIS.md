# Balance Detection Issue Analysis

## Current Situation (January 10, 2026)

### What the Bot Reports:
- **Coinbase Advanced Trade**: $1.37
- **Kraken Master**: Connection failed (EAPI:Invalid nonce)
- **Alpaca Paper**: Not checked yet
- **User #1 (Daivon Frazier) Kraken**: Connection failed (EAPI:Invalid nonce)

### What Should Be There (User Reports):
- **Master Coinbase**: $28.00
- **Master Kraken**: $28.00
- **Master Alpaca (Paper Trading)**: $100,000.00
- **User #1**: $30.00

### Discrepancy:
- Coinbase shows **$26.63 missing** ($28.00 expected - $1.37 detected = $26.63)

---

## Root Cause Analysis

### Issue #1: Coinbase Balance Mismatch ($1.37 vs $28.00)

**Possible Causes:**

1. **Funds in Consumer Wallet** (Most Likely)
   - The $26.63 might be in the Coinbase Consumer wallet
   - Consumer wallets are **NOT accessible** via Advanced Trade API
   - The bot correctly reports only Advanced Trade portfolio balance
   - **Solution**: Transfer funds from Consumer to Advanced Trade portfolio

2. **Funds in Wrong Portfolio**
   - Coinbase allows multiple portfolios
   - The bot reads the DEFAULT portfolio
   - Funds might be in a different portfolio
   - **Solution**: Check all portfolios and move funds to default

3. **Funds Held in Open Positions**
   - The $26.63 might be tied up in open crypto positions
   - Available balance = Total - Held in positions
   - **Solution**: Check open positions/holdings

4. **Wrong API Credentials**
   - The API keys might be for a different Coinbase account
   - **Solution**: Verify API keys match the account with $28

### Issue #2: Kraken "Invalid Nonce" Error

**What is a Nonce Error?**
- Nonce = "Number used ONCE" for API request authentication
- Kraken requires each API call to have an incrementing nonce value
- "Invalid nonce" means the nonce is too old or out of sequence

**Possible Causes:**

1. **System Clock Drift** (Most Common)
   - Server clock is out of sync with Kraken servers
   - **Solution**: Sync system time with NTP server

2. **Multiple API Calls Too Quickly**
   - Sending requests faster than nonce can increment
   - **Solution**: Add delays between API calls

3. **Nonce Not Incrementing**
   - Using same nonce value multiple times
   - **Solution**: Use microsecond timestamp for nonce

4. **API Key Permissions**
   - API keys lack required permissions
   - **Solution**: Regenerate keys with full permissions

### Issue #3: User #1 Connection Failed

Same as Kraken Master - likely the same nonce issue.

---

## Solutions

### Fix #1: Diagnose Coinbase Balance

Run the diagnostic script to find where the $28 actually is:

```bash
python3 diagnose_all_balances.py
```

This will show:
- Advanced Trade balance (API tradable)
- Consumer wallet balance (NOT API tradable)
- Crypto holdings
- All portfolios

**If funds are in Consumer wallet:**
1. Go to: https://www.coinbase.com/advanced-portfolio
2. Click "Deposit" → "From Coinbase"
3. Transfer funds to Advanced Trade
4. Restart bot - it will detect the new balance

### Fix #2: Fix Kraken Nonce Error

**Option A: Regenerate API Keys** (Recommended)
1. Go to: https://www.kraken.com/u/security/api
2. Delete old API keys
3. Create new API keys with permissions:
   - Query Funds
   - Query Open Orders & Trades
   - Create & Modify Orders
4. Update environment variables:
   ```
   KRAKEN_MASTER_API_KEY=<new-key>
   KRAKEN_MASTER_API_SECRET=<new-secret>
   ```
5. Restart bot

**Option B: Sync System Clock**
```bash
sudo ntpdate -s time.nist.gov
# or
sudo timedatectl set-ntp true
```

**Option C: Add Nonce Delay** (Code fix)
Modify Kraken API calls to use microsecond timestamps and add delays.

### Fix #3: Fix User #1 Connection

Same as Kraken Master fix - regenerate API keys for User #1:
```
KRAKEN_USER_DAIVON_API_KEY=<new-key>
KRAKEN_USER_DAIVON_API_SECRET=<new-secret>
```

### Fix #4: Verify Alpaca Balance

The bot hasn't checked Alpaca yet. Ensure:
```
ALPACA_API_KEY=<your-paper-key>
ALPACA_API_SECRET=<your-paper-secret>
ALPACA_PAPER=true
```

---

## Implementation Priority

1. **✅ COMPLETED**: Lower minimum balance threshold to $1.00
2. **🔄 IN PROGRESS**: Diagnose actual Coinbase balance location
3. **⏳ PENDING**: Fix Kraken nonce error
4. **⏳ PENDING**: Fix User #1 Kraken connection
5. **⏳ PENDING**: Verify Alpaca paper trading connection
6. **⏳ PENDING**: Verify all balances match user expectations

---

## Expected Outcome After Fixes

Once all issues are resolved, the bot should report:

```
✅ MASTER ACCOUNT BROKERS:
   💰 Coinbase: $28.00 (FUNDED ✅)
   💰 Kraken: $28.00 (FUNDED ✅)
   💰 Alpaca: $100,000.00 (FUNDED ✅)
   
✅ USER ACCOUNT BROKERS:
   💰 User #1 (Daivon Frazier) Kraken: $30.00 (FUNDED ✅)

💰 TOTAL TRADING CAPITAL: $100,086.00
🚀 Starting independent multi-broker trading...
```

---

## Next Steps

1. Run `python3 diagnose_all_balances.py` to identify where funds are
2. Transfer Coinbase funds from Consumer wallet to Advanced Trade (if needed)
3. Regenerate Kraken API keys to fix nonce errors
4. Update .env file with new credentials
5. Redeploy bot
6. Monitor startup logs to verify all connections succeed
