# 🔧 Connect Master Kraken Account

You've successfully configured:
- ✅ Kraken User #1 (Daivon)
- ✅ Kraken User #2 (Tania)
- ✅ OKX Master Account

Now you just need to add the **Master Kraken** credentials!

## 🚀 Quick Start (Choose One)

### Option 1: Interactive Guide (Recommended)
```bash
python3 setup_kraken_master.py
# or
./setup_kraken_master.sh
```

### Option 2: Visual One-Page Guide
```bash
cat QUICKSTART_MASTER_KRAKEN.txt
```

### Option 3: Detailed Documentation
```bash
# Read the full guide
cat SETUP_MASTER_KRAKEN.md
```

## 📋 What You Need to Do

1. **Get Kraken API Key** (5 minutes)
   - Go to https://www.kraken.com
   - Create API key with trading permissions
   - Save API Key + API Secret

2. **Add to Deployment** (2 minutes)
   - Railway: Add 2 environment variables
   - Render: Add 2 environment variables
   - Local: Add to `.env` file

3. **Verify** (2 minutes)
   - Wait for restart
   - Check logs for ✅ confirmation

**Total Time**: ~10 minutes

## 🎯 The Two Variables You Need

```bash
KRAKEN_MASTER_API_KEY=your-56-char-api-key
KRAKEN_MASTER_API_SECRET=your-88-char-api-secret
```

## 📖 Where to Add Them

### Railway (https://railway.app/)
1. Your Project → Service → **Variables** tab
2. Add both variables
3. Auto-restarts → Done!

### Render (https://dashboard.render.com/)
1. Your Service → **Environment** tab
2. Add both variables
3. **Manual Deploy** → Done!

### Local Development
1. Edit `.env` file
2. Add both variables
3. Restart bot

## ✅ Success Looks Like

In your logs:
```
📊 KRAKEN (Master):
   ✅ Configured (Key: 56 chars, Secret: 88 chars)
```

Later in logs:
```
📊 Attempting to connect Kraken Pro (MASTER)...
   ✅ Connected to Kraken Pro API (MASTER)
   💰 Kraken balance: $X,XXX.XX
```

## 🆘 Need Help?

Run these diagnostic scripts:
```bash
python3 check_kraken_status.py           # Check status
python3 diagnose_kraken_connection.py    # Diagnose issues
python3 setup_kraken_master.py           # Interactive guide
```

Read these docs:
- `SETUP_MASTER_KRAKEN.md` - Full guide
- `QUICKSTART_MASTER_KRAKEN.txt` - Visual guide
- `KRAKEN_SETUP_GUIDE.md` - Complete Kraken setup
- `GETTING_STARTED.md` - General setup

## 🔒 Security

- ✅ Use 2FA on Kraken account
- ✅ Store keys in password manager
- ✅ Never commit keys to git
- ✅ Only enable needed permissions
- ✅ Rotate keys every 3-6 months

---

**That's it!** Follow any of the guides above to connect your Master Kraken account. The whole process takes about 10 minutes.

🚀 **Quick command**: `python3 setup_kraken_master.py`
