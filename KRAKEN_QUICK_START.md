# ⚡ QUICK START: Enable Kraken Trading

**Status**: ❌ Kraken NOT currently trading  
**Reason**: API credentials not configured  
**Time to fix**: ~60 minutes  
**Difficulty**: Easy (just need to get API keys)

---

## 🎯 What You Need to Do

### Option 1: Interactive Setup (Recommended) ⭐

Run this command and follow the prompts:

```bash
python3 setup_kraken_credentials.py
```

The script will:
1. Show current credential status
2. Guide you through getting API keys from Kraken
3. Help you configure environment variables
4. Provide platform-specific instructions

**Time**: 10-60 minutes (depending on if you have API keys ready)

---

### Option 2: Manual Setup

#### Step 1: Check Current Status
```bash
python3 check_kraken_status.py
```

This shows which accounts need credentials.

#### Step 2: Get API Keys from Kraken

For each account (Master, Daivon, Tania):

1. Go to https://www.kraken.com/u/security/api
2. Click "Generate New Key"
3. Select these permissions:
   - ✅ Query Funds
   - ✅ Query Open Orders & Trades
   - ✅ Query Closed Orders & Trades
   - ✅ Create & Modify Orders
   - ✅ Cancel/Close Orders
   - ❌ Withdraw Funds (DON'T enable this)
4. Save both the API Key and Private Key immediately
   - ⚠️ Private Key is shown ONLY ONCE!

#### Step 3: Set Environment Variables

**Railway**:
1. Go to Railway dashboard
2. Select NIJA project
3. Click "Variables"
4. Add each variable (6 total):
   - `KRAKEN_MASTER_API_KEY`
   - `KRAKEN_MASTER_API_SECRET`
   - `KRAKEN_USER_DAIVON_API_KEY`
   - `KRAKEN_USER_DAIVON_API_SECRET`
   - `KRAKEN_USER_TANIA_API_KEY`
   - `KRAKEN_USER_TANIA_API_SECRET`

**Render**:
1. Go to Render dashboard
2. Select NIJA service
3. Click "Environment"
4. Add each variable (same 6 as above)

**Local (.env file)**:
```bash
# Add to .env file in repository root:
KRAKEN_MASTER_API_KEY=your-master-api-key
KRAKEN_MASTER_API_SECRET=your-master-api-secret
KRAKEN_USER_DAIVON_API_KEY=daivon-api-key
KRAKEN_USER_DAIVON_API_SECRET=daivon-api-secret
KRAKEN_USER_TANIA_API_KEY=tania-api-key
KRAKEN_USER_TANIA_API_SECRET=tania-api-secret
```

#### Step 4: Restart Bot

**Railway/Render**: Auto-deploys when you save variables

**Local**:
```bash
./start.sh
```

#### Step 5: Verify

```bash
# Should show all ✅ SET
python3 check_kraken_status.py

# Should connect successfully
python3 test_kraken_connection_live.py
```

Check bot logs for:
```
✅ Kraken connected (MASTER)
✅ Kraken connected (USER:daivon_frazier)
✅ Kraken connected (USER:tania_gilbert)
📊 Trading will occur on exchange(s): COINBASE, KRAKEN
```

---

## 📚 Need More Help?

### Documentation
- **Full Status**: [CURRENT_KRAKEN_STATUS.md](CURRENT_KRAKEN_STATUS.md)
- **Troubleshooting**: [KRAKEN_TROUBLESHOOTING_SUMMARY.md](KRAKEN_TROUBLESHOOTING_SUMMARY.md)
- **Setup Guide**: [KRAKEN_SETUP_GUIDE.md](KRAKEN_SETUP_GUIDE.md)

### Quick Commands
```bash
# Check status
python3 check_kraken_status.py

# Interactive setup
python3 setup_kraken_credentials.py

# Test connection
python3 test_kraken_connection_live.py

# Verify users
python3 verify_kraken_users.py
```

---

## ❓ FAQ

**Q: Do I need to do this for all 3 accounts?**  
A: Only for accounts you want to trade with. You can enable just Master, just users, or all 3.

**Q: I don't have a Kraken account. Can I still use NIJA?**  
A: Yes! NIJA works with Coinbase without any Kraken credentials. Kraken is optional.

**Q: Is my data safe?**  
A: Yes. Credentials are stored as environment variables, never committed to Git. Use minimum required permissions (don't enable "Withdraw Funds").

**Q: How long does this take?**  
A: ~15 minutes per account to get API keys + 5 minutes to configure = ~60 minutes total for all 3 accounts.

**Q: Will this keep happening?**  
A: No. Once credentials are set, they persist. You only need to do this once.

**Q: Something's not working. What do I do?**  
A: Check [KRAKEN_TROUBLESHOOTING_SUMMARY.md](KRAKEN_TROUBLESHOOTING_SUMMARY.md) for common issues and solutions.

---

## ✅ Success Checklist

- [ ] Got API keys from Kraken
- [ ] Set environment variables on deployment platform
- [ ] Bot restarted (or auto-redeployed)
- [ ] Ran `python3 check_kraken_status.py` → All ✅ SET
- [ ] Checked bot logs → "✅ Kraken connected"
- [ ] Confirmed trading on Kraken

---

**Bottom Line**: Infrastructure is ready. Just need API credentials. Run the setup script or follow manual steps above.

**Estimated Time**: 60 minutes  
**Required**: Kraken account(s) with API access  
**Difficulty**: Easy - just copy/paste credentials

🚀 **Start here**: `python3 setup_kraken_credentials.py`
