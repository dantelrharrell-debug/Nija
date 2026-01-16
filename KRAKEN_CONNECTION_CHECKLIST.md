# Kraken Connection Setup Checklist

**Last Updated:** January 16, 2026  
**Purpose:** Ensure all Kraken accounts (master + users) are connected and trading

---

## 📋 Quick Status Check

Run this command to check current connection status:

```bash
python3 test_all_kraken_connections.py
```

---

## ✅ Required Setup

### 1. Master Account (NIJA System)

**Environment Variables Required:**
```bash
KRAKEN_MASTER_API_KEY=<your-master-api-key>
KRAKEN_MASTER_API_SECRET=<your-master-api-secret>
```

**OR** (legacy format):
```bash
KRAKEN_API_KEY=<your-master-api-key>
KRAKEN_API_SECRET=<your-master-api-secret>
```

**How to Get Credentials:**
1. Log in to Kraken: https://www.kraken.com/u/security/api
2. Click "Generate New Key"
3. Set Key Description: "NIJA Master Trading Bot"
4. Enable these permissions:
   - ✅ Query Funds
   - ✅ Query Open Orders & Trades
   - ✅ Query Closed Orders & Trades
   - ✅ Create & Modify Orders
   - ✅ Cancel/Close Orders
5. Click "Generate Key"
6. Copy the API Key and Private Key (you won't see the Private Key again!)

---

### 2. User Account: Daivon Frazier

**Configuration Status:** ✅ Enabled in `config/users/retail_kraken.json`

**Environment Variables Required:**
```bash
KRAKEN_USER_DAIVON_API_KEY=<daivon-api-key>
KRAKEN_USER_DAIVON_API_SECRET=<daivon-api-secret>
```

**How to Get Credentials:**
1. Log in to Kraken with Daivon's account: https://www.kraken.com/u/security/api
2. Click "Generate New Key"
3. Set Key Description: "NIJA Trading Bot - Daivon"
4. Enable same permissions as master (see above)
5. Click "Generate Key"
6. Copy the API Key and Private Key

---

### 3. User Account: Tania Gilbert (User2)

**Configuration Status:** ✅ Enabled in `config/users/retail_kraken.json`

**Environment Variables Required:**
```bash
KRAKEN_USER_TANIA_API_KEY=<tania-api-key>
KRAKEN_USER_TANIA_API_SECRET=<tania-api-secret>
```

**How to Get Credentials:**
1. Log in to Kraken with Tania's account: https://www.kraken.com/u/security/api
2. Click "Generate New Key"
3. Set Key Description: "NIJA Trading Bot - Tania"
4. Enable same permissions as master (see above)
5. Click "Generate Key"
6. Copy the API Key and Private Key

---

## 🚀 Adding Credentials to Railway

If you're deploying on Railway:

1. Go to your Railway dashboard
2. Select your NIJA project
3. Click on the service
4. Go to "Variables" tab
5. Click "+ New Variable"
6. Add each variable one by one:
   - Name: `KRAKEN_MASTER_API_KEY`
   - Value: `<your-actual-api-key>`
   - Click "Add"
7. Repeat for all 6 required variables:
   - `KRAKEN_MASTER_API_KEY`
   - `KRAKEN_MASTER_API_SECRET`
   - `KRAKEN_USER_DAIVON_API_KEY`
   - `KRAKEN_USER_DAIVON_API_SECRET`
   - `KRAKEN_USER_TANIA_API_KEY`
   - `KRAKEN_USER_TANIA_API_SECRET`
8. Railway will automatically redeploy after saving

---

## 🖥️ Adding Credentials to Render

If you're deploying on Render:

1. Go to your Render dashboard
2. Select your NIJA service
3. Click "Environment" tab
4. Click "Add Environment Variable"
5. Add each variable:
   - Key: `KRAKEN_MASTER_API_KEY`
   - Value: `<your-actual-api-key>`
   - Click "Save Changes"
6. Repeat for all 6 required variables
7. Render will automatically redeploy after saving

---

## 💻 Local Development (.env file)

If you're running locally:

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` file and fill in the credentials:
   ```bash
   # Master Account
   KRAKEN_MASTER_API_KEY=your-master-api-key-here
   KRAKEN_MASTER_API_SECRET=your-master-api-secret-here
   
   # Daivon Frazier
   KRAKEN_USER_DAIVON_API_KEY=daivon-api-key-here
   KRAKEN_USER_DAIVON_API_SECRET=daivon-api-secret-here
   
   # Tania Gilbert
   KRAKEN_USER_TANIA_API_KEY=tania-api-key-here
   KRAKEN_USER_TANIA_API_SECRET=tania-api-secret-here
   ```

3. Save the file (never commit `.env` to git!)

---

## ✅ Verification Steps

### Step 1: Check Credentials Are Set

```bash
python3 verify_kraken_users.py
```

**Expected Output:**
```
✅ KRAKEN_MASTER_API_KEY: VALID (64 chars)
✅ KRAKEN_MASTER_API_SECRET: VALID (88 chars)
✅ KRAKEN_USER_DAIVON_API_KEY: VALID (64 chars)
✅ KRAKEN_USER_DAIVON_API_SECRET: VALID (88 chars)
✅ KRAKEN_USER_TANIA_API_KEY: VALID (64 chars)
✅ KRAKEN_USER_TANIA_API_SECRET: VALID (88 chars)
```

### Step 2: Test Actual Connections

```bash
python3 test_all_kraken_connections.py
```

**Expected Output:**
```
✅ Master Account
    Credentials: ✅ SET
    Connection:  ✅ CONNECTED
    Balance:     $XXX.XX

✅ Daivon Frazier
    Credentials: ✅ SET
    Connection:  ✅ CONNECTED
    Balance:     $XXX.XX

✅ Tania Gilbert
    Credentials: ✅ SET
    Connection:  ✅ CONNECTED
    Balance:     $XXX.XX

🎉 ALL TESTS PASSED!
```

### Step 3: Start the Bot

```bash
python3 main.py
```

**Look for these lines in the logs:**
```
✅ Kraken MASTER connected
💰 Master balance: $XXX.XX
✅ Started independent trading thread for kraken (MASTER)

✅ USER: Daivon Frazier: TRADING (Broker: Kraken)
💰 Daivon Frazier balance: $XXX.XX
✅ Started independent trading thread for daivon_frazier (USER)

✅ USER: Tania Gilbert: TRADING (Broker: Kraken)
💰 Tania Gilbert balance: $XXX.XX
✅ Started independent trading thread for tania_gilbert (USER)
```

---

## 🔍 Troubleshooting

### Issue: "❌ NOT SET"

**Problem:** Environment variable is not set  
**Solution:** Add the environment variable to Railway/Render/local .env file

### Issue: "⚠️ SET but EMPTY"

**Problem:** Environment variable exists but contains only whitespace  
**Solution:** Check for extra spaces, newlines, or tabs in the value

### Issue: "⚠️ TOO SHORT"

**Problem:** Value is less than 10 characters  
**Solution:** Verify you copied the full API key/secret from Kraken

### Issue: "❌ PERMISSION ERROR"

**Problem:** API key exists but lacks required permissions  
**Solution:**
1. Go to https://www.kraken.com/u/security/api
2. Edit the API key
3. Enable all required permissions (see list above)
4. Save and restart the bot

### Issue: "❌ AUTHENTICATION ERROR"

**Problem:** Invalid API key or secret  
**Solution:**
1. Verify credentials at https://www.kraken.com/u/security/api
2. Generate a new API key if needed
3. Update environment variables
4. Restart deployment

### Issue: "⚠️ Account balance is very low"

**Problem:** Account has less than $1  
**Solution:** Deposit funds to Kraken account before trading

---

## 📊 Success Criteria

All of the following must be ✅:

- [ ] Master account credentials set in environment
- [ ] Master account connection successful
- [ ] Master account balance > $1.00
- [ ] Daivon Frazier credentials set in environment
- [ ] Daivon Frazier connection successful
- [ ] Daivon Frazier balance > $1.00
- [ ] Tania Gilbert credentials set in environment
- [ ] Tania Gilbert connection successful
- [ ] Tania Gilbert balance > $1.00
- [ ] All accounts show "TRADING" status in bot logs
- [ ] Independent trading threads started for each account

---

## 📖 Related Documentation

- **SETUP_KRAKEN_USERS.md** - Detailed step-by-step user setup guide
- **ANSWER_KRAKEN_USER_SETUP.md** - Quick reference for user setup
- **ANSWER_KRAKEN_MASTER_STATUS.md** - Master account architecture
- **KRAKEN_SETUP_GUIDE.md** - General Kraken setup information

---

## 🆘 Need Help?

If you're still having issues after following this checklist:

1. Run the diagnostic script:
   ```bash
   python3 diagnose_kraken_connection.py
   ```

2. Check the bot logs for error messages:
   ```bash
   railway logs -f  # Railway
   # or check Render logs in dashboard
   ```

3. Review the detailed setup guide: `SETUP_KRAKEN_USERS.md`

---

**Last Verified:** January 16, 2026  
**Test Script:** `test_all_kraken_connections.py`  
**Verification Script:** `verify_kraken_users.py`
