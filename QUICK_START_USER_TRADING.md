# Quick Reference: Activating User Trading for NIJA

## TL;DR - What You Need

To have NIJA actively manage and sell positions for user accounts:

### 1. Set API Credentials (REQUIRED)

Add to `.env` file or export as environment variables:

```bash
# Daivon Frazier (User #1)
KRAKEN_USER_DAIVON_API_KEY=your_api_key_here
KRAKEN_USER_DAIVON_API_SECRET=your_api_secret_here

# Tania Gilbert (User #2)  
KRAKEN_USER_TANIA_API_KEY=your_api_key_here
KRAKEN_USER_TANIA_API_SECRET=your_api_secret_here

# Platform Account (RECOMMENDED)
KRAKEN_PLATFORM_API_KEY=your_api_key_here
KRAKEN_PLATFORM_API_SECRET=your_api_secret_here
```

### 2. Verify Configuration

```bash
python scripts/activate_user_trading.py
```

Expected output: ✅ ALL CHECKS PASSED

### 3. Start NIJA

```bash
./start.sh
```

## That's It!

NIJA will automatically:
- ✅ Start trading thread: `Trader-daivon_frazier_kraken`
- ✅ Start trading thread: `Trader-tania_gilbert_kraken`
- ✅ Scan markets every 2.5 minutes
- ✅ Execute trades independently (NO copy trading)
- ✅ Apply stop-loss and take-profit
- ✅ Close profitable positions

## Getting API Credentials

**Kraken:**
1. Go to: https://www.kraken.com/u/security/api
2. Click "Generate New Key"
3. Enable permissions:
   - ✅ Query Funds
   - ✅ Query Open Orders & Trades
   - ✅ Query Closed Orders & Trades  
   - ✅ Create & Modify Orders
   - ✅ Cancel/Close Orders
4. Copy API Key and Private Key
5. Add to `.env` file

## Expected Logs

When NIJA starts successfully:

```
======================================================================
🔄 INDEPENDENT TRADING MODE ENABLED (NO COPY TRADING)
======================================================================
   ✅ Each account trades INDEPENDENTLY using NIJA strategy
   ❌ NO trade copying or mirroring between accounts

======================================================================
👤 STARTING USER BROKER THREADS
======================================================================

   🚀 TRADING THREAD STARTED for daivon_frazier_kraken (USER)
   📊 Thread name: Trader-daivon_frazier_kraken
   👤 User: daivon_frazier
   🔄 This thread will:
      • Scan markets independently every 2.5 minutes
      • Execute USER trades when signals trigger
      • Manage existing positions independently
      • NO copy trading - makes own trading decisions

   🚀 TRADING THREAD STARTED for tania_gilbert_kraken (USER)
   📊 Thread name: Trader-tania_gilbert_kraken
   👤 User: tania_gilbert
   🔄 This thread will:
      • Scan markets independently every 2.5 minutes
      • Execute USER trades when signals trigger
      • Manage existing positions independently
      • NO copy trading - makes own trading decisions
```

## Common Issues

### ❌ "Missing API credentials"
**Solution**: Set environment variables (see step 1)

### ❌ "No funded brokers detected"
**Solution**: Add funds to account (minimum $0.50)

### ❌ "User broker connection failed"
**Solution**: Verify API key has correct permissions

## Pro Mode (Optional)

For advanced position scaling:

```bash
export PRO_MODE=true
```

## Full Documentation

- `USER_TRADING_ACTIVATION_GUIDE.md` - Complete setup guide
- `INDEPENDENT_TRADING_NO_COPY.md` - Explains independent trading model

## Need Help?

Run the activation checker for detailed diagnostics:
```bash
python scripts/activate_user_trading.py
```
