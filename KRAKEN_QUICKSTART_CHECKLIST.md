# Kraken Quick Start Checklist

**Complete this checklist to connect all accounts to Kraken in 10-15 minutes.**

---

## ✅ Pre-Flight Check

- [ ] I have access to all 3 Kraken accounts:
  - [ ] Master account (NIJA system)
  - [ ] User #1: Daivon Frazier's account
  - [ ] User #2: Tania Gilbert's account
- [ ] I know my deployment platform:
  - [ ] Railway
  - [ ] Render
  - [ ] Local development
- [ ] I have read [CONNECT_KRAKEN_COMPLETE_GUIDE.md](CONNECT_KRAKEN_COMPLETE_GUIDE.md)

---

## 📝 Step 1: Create API Keys (3 accounts x 1 key each = 3 keys)

### Master Account

- [ ] Logged into Master Kraken account
- [ ] Navigate to: https://www.kraken.com/u/security/api
- [ ] Click "Add Key" or "Create API Key"
- [ ] Set description: "NIJA Master Trading Bot"
- [ ] Enable these 5 permissions:
  - [ ] ✅ Query Funds
  - [ ] ✅ Query Open Orders & Trades
  - [ ] ✅ Query Closed Orders & Trades
  - [ ] ✅ Create & Modify Orders
  - [ ] ✅ Cancel/Close Orders
- [ ] ❌ DO NOT enable "Withdraw Funds"
- [ ] Click "Generate Key"
- [ ] Copy API Key: `_____________________________`
- [ ] Copy Private Key: `_____________________________`
- [ ] Store keys securely

### User #1: Daivon Frazier

- [ ] Logged into Daivon's Kraken account
- [ ] Navigate to: https://www.kraken.com/u/security/api
- [ ] Click "Add Key" or "Create API Key"
- [ ] Set description: "NIJA User Trading Bot - Daivon"
- [ ] Enable the same 5 permissions as above
- [ ] ❌ DO NOT enable "Withdraw Funds"
- [ ] Click "Generate Key"
- [ ] Copy API Key: `_____________________________`
- [ ] Copy Private Key: `_____________________________`
- [ ] Store keys securely

### User #2: Tania Gilbert

- [ ] Logged into Tania's Kraken account
- [ ] Navigate to: https://www.kraken.com/u/security/api
- [ ] Click "Add Key" or "Create API Key"
- [ ] Set description: "NIJA User Trading Bot - Tania"
- [ ] Enable the same 5 permissions as above
- [ ] ❌ DO NOT enable "Withdraw Funds"
- [ ] Click "Generate Key"
- [ ] Copy API Key: `_____________________________`
- [ ] Copy Private Key: `_____________________________`
- [ ] Store keys securely

---

## 🚀 Step 2: Add Environment Variables

### For Railway Users

- [ ] Go to: https://railway.app/dashboard
- [ ] Select NIJA project
- [ ] Click on your service
- [ ] Click "Variables" tab
- [ ] Add these 6 variables (click "+ New Variable" for each):

```
KRAKEN_MASTER_API_KEY = [paste Master API key]
KRAKEN_MASTER_API_SECRET = [paste Master Private key]
KRAKEN_USER_DAIVON_API_KEY = [paste Daivon's API key]
KRAKEN_USER_DAIVON_API_SECRET = [paste Daivon's Private key]
KRAKEN_USER_TANIA_API_KEY = [paste Tania's API key]
KRAKEN_USER_TANIA_API_SECRET = [paste Tania's Private key]
```

- [ ] Click "Save" (Railway auto-redeploys)
- [ ] Wait 2-3 minutes for deployment
- [ ] Skip to Step 3

### For Render Users

- [ ] Go to: https://dashboard.render.com/
- [ ] Select NIJA service
- [ ] Click "Environment" tab
- [ ] Add the same 6 variables as above
- [ ] Click "Save Changes"
- [ ] Click "Manual Deploy" → "Deploy latest commit"
- [ ] Wait 3-5 minutes for deployment
- [ ] Skip to Step 3

### For Local Development Users

- [ ] Open `.env` file: `nano .env`
- [ ] Add these 6 lines:

```bash
KRAKEN_MASTER_API_KEY=[paste Master API key]
KRAKEN_MASTER_API_SECRET=[paste Master Private key]
KRAKEN_USER_DAIVON_API_KEY=[paste Daivon's API key]
KRAKEN_USER_DAIVON_API_SECRET=[paste Daivon's Private key]
KRAKEN_USER_TANIA_API_KEY=[paste Tania's API key]
KRAKEN_USER_TANIA_API_SECRET=[paste Tania's Private key]
```

- [ ] Save file (Ctrl+X, Y, Enter)
- [ ] Restart bot: `./start.sh`

---

## ✅ Step 3: Verify Connection

### Check Status

- [ ] Run: `python3 check_kraken_status.py`
- [ ] Verify output shows:
  ```
  ✅ KRAKEN_MASTER_API_KEY: SET
  ✅ KRAKEN_MASTER_API_SECRET: SET
  ✅ KRAKEN_USER_DAIVON_API_KEY: SET
  ✅ KRAKEN_USER_DAIVON_API_SECRET: SET
  ✅ KRAKEN_USER_TANIA_API_KEY: SET
  ✅ KRAKEN_USER_TANIA_API_SECRET: SET
  
  Configured Accounts: 3/3
  ```

### Check Logs

Railway:
- [ ] View logs in Railway dashboard
- [ ] Look for: `✅ Kraken MASTER connected`
- [ ] Look for: `✅ Kraken connected (USER:daivon_frazier)`
- [ ] Look for: `✅ Kraken connected (USER:tania_gilbert)`
- [ ] Look for: `Trading will occur on exchange(s): COINBASE, KRAKEN`

Render:
- [ ] View logs in Render dashboard
- [ ] Look for same success messages as above

Local:
- [ ] Run: `tail -f nija.log`
- [ ] Look for same success messages as above

---

## 🎯 Step 4: Confirm Trading

- [ ] Wait 5-10 minutes for first trades
- [ ] Check Kraken account for orders
- [ ] Verify NIJA is trading on both Coinbase AND Kraken
- [ ] Celebrate! 🎉

---

## ❌ Troubleshooting

If you see permission errors:
- [ ] Go back to Step 1
- [ ] Verify all 5 permissions are enabled
- [ ] Delete old API key and create new one
- [ ] Update environment variables with new key
- [ ] Restart bot

If variables show "NOT SET":
- [ ] Wait for deployment to complete (2-5 minutes)
- [ ] Verify no extra spaces in values
- [ ] Force manual redeploy
- [ ] Check deployment platform logs

If stuck:
- [ ] Read: [CONNECT_KRAKEN_COMPLETE_GUIDE.md](CONNECT_KRAKEN_COMPLETE_GUIDE.md)
- [ ] Run: `python3 diagnose_kraken_connection.py`
- [ ] Check: [KRAKEN_TROUBLESHOOTING_SUMMARY.md](KRAKEN_TROUBLESHOOTING_SUMMARY.md)

---

## ✅ Success Criteria

You're done when:
- [ ] All 6 environment variables set
- [ ] `check_kraken_status.py` shows 3/3 configured
- [ ] Logs show all 3 accounts connected
- [ ] Trading occurs on both Coinbase and Kraken
- [ ] Kraken trades visible in Kraken account

**Expected Time**: 10-15 minutes total
