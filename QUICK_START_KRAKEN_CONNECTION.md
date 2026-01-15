# Quick Start: Connect Master and Users to Kraken

## ⚡ TL;DR

**Kraken is already integrated!** You just need API credentials.

```bash
# 1. Run diagnostic
python3 connect_kraken.py

# 2. Follow instructions to get API keys from Kraken.com

# 3. Add to environment variables (Railway/Render)
KRAKEN_MASTER_API_KEY=<your-master-key>
KRAKEN_MASTER_API_SECRET=<your-master-secret>
KRAKEN_USER_DAIVON_API_KEY=<daivon-key>
KRAKEN_USER_DAIVON_API_SECRET=<daivon-secret>
KRAKEN_USER_TANIA_API_KEY=<tania-key>
KRAKEN_USER_TANIA_API_SECRET=<tania-secret>

# 4. Redeploy and done! ✅
```

## 📋 Why Trading Isn't Happening on Kraken

**Answer:** No API credentials configured. That's it!

**NOT because:**
- ❌ Coinbase is interfering (brokers are independent)
- ❌ Code is missing (Kraken is fully integrated)
- ❌ Users aren't configured (Daivon & Tania are set up)
- ❌ Permissions are wrong (permissions are correct)

**The ONLY issue:** Missing API keys from Kraken.com

## 🔑 Get API Keys (5 minutes per account)

### For Master Account (NIJA System)

1. Login to your main Kraken account
2. Settings → API → "Generate New Key"
3. **Permissions** (check these):
   - ✓ Query Funds
   - ✓ Query Open Orders & Trades
   - ✓ Query Closed Orders & Trades
   - ✓ Create & Modify Orders
   - ✓ Cancel/Close Orders
4. **Nonce Window:** 10 seconds
5. Generate → Save API Key + Private Key

### For Daivon Frazier

1. Login to Daivon's Kraken account
2. Repeat steps 2-5 above

### For Tania Gilbert

1. Login to Tania's Kraken account
2. Repeat steps 2-5 above

## 🚀 Deploy (Railway)

1. Go to your Railway project
2. Variables tab
3. Add these 6 variables:
   ```
   KRAKEN_MASTER_API_KEY
   KRAKEN_MASTER_API_SECRET
   KRAKEN_USER_DAIVON_API_KEY
   KRAKEN_USER_DAIVON_API_SECRET
   KRAKEN_USER_TANIA_API_KEY
   KRAKEN_USER_TANIA_API_SECRET
   ```
4. Click "Redeploy"

## ✅ Verify

After redeployment, check logs for:

```
✅ Kraken MASTER connected
✅ Daivon Frazier connected to Kraken
✅ Tania Gilbert connected to Kraken
```

**That's it!** Master and users are now trading on Kraken.

## 🎯 What Happens Next

**Automatic Trading Starts:**
- Master scans markets on Kraken
- Daivon's account trades independently
- Tania's account trades independently
- All accounts operate in parallel
- Coinbase continues trading (doesn't interfere)

**Each account:**
- Has its own balance
- Makes its own decisions
- Manages its own positions
- Logs its own trades

## ❓ FAQ

**Q: Can Coinbase interfere with Kraken trading?**  
A: No. Each broker runs in its own thread and operates independently.

**Q: Do I need to configure anything in the code?**  
A: No. Everything is already set up. Just add API keys.

**Q: What if I only want to connect the master?**  
A: Just add `KRAKEN_MASTER_API_KEY` and `KRAKEN_MASTER_API_SECRET`. Users are optional.

**Q: How do I know it's working?**  
A: Check logs for "✅ Kraken MASTER connected" and watch for Kraken trade logs.

**Q: Do all accounts need to be funded?**  
A: Minimum $1.00 to connect, $25.00 recommended for active trading.

## 🔧 Troubleshooting

**Problem:** "Connection failed"  
**Fix:** Check API key permissions on Kraken.com

**Problem:** "Nonce error"  
**Fix:** Set Nonce Window to 10 seconds in API settings

**Problem:** "Still not connecting"  
**Fix:** Run `python3 diagnose_kraken_status.py` for detailed diagnostics

## 📚 More Details

See `KRAKEN_CONNECTION_COMPLETE_GUIDE.md` for comprehensive documentation.

---

**Need help?** Run `python3 connect_kraken.py` for interactive setup.
