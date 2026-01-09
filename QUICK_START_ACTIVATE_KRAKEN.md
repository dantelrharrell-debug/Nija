# QUICK START: Activate Kraken Trading NOW

## ⚡ Run These Commands

```bash
# Test Kraken connection
python3 enable_kraken_and_verify.py

# Activate both NIJA and User #1 Kraken accounts
python3 activate_kraken_trading_both_accounts.py
```

## 🔧 Then Configure Railway

1. Go to Railway dashboard
2. Click on your NIJA project
3. Go to Variables tab
4. Add these (if not already there):

```
KRAKEN_API_KEY=8zdYy7PMRjnyDraiJUtrAb3wmu8MFxKBON3nrTkjkwnJ9iIUQyKNGKP7
KRAKEN_API_SECRET=e2xaakHliGa5RwH7uXwuq6RLGospWaQhScaVJfsS6wIa9huHxmx+HgeQCax8A+gvqV3P9jXD9YbR3wtsipdpRA==
```

5. Bot will auto-redeploy with new variables

## ✅ Verify It's Working

Look for these in logs:

```
📊 Attempting to connect Kraken Pro...
   ✅ Kraken connected
======================================================================
✅ KRAKEN PRO CONNECTED
======================================================================
   USD Balance: $XXX.XX
   USDT Balance: $XXX.XX
======================================================================
```

And during trading:
```
🔄 coinbase - Cycle #1
🔄 kraken - Cycle #1   ← YOU SHOULD SEE THIS
```

## ❌ If Still Not Working

Check bot startup logs for:
```
⚠️  Kraken error: ...
```

Common issues:
- API key permissions (needs Query Funds, Create Orders)
- Rate limiting (403/429 errors)
- Insufficient balance on Kraken

## 📋 What You'll Have When Done

1. ✅ Coinbase trading (your main account)
2. ✅ Kraken trading (NIJA's account)
3. ✅ User #1 (Daivon) trading on Kraken (if multi-user activated)

**Total: 2-3 accounts trading simultaneously**

---

See ANSWER_ACTIVATE_KRAKEN_NOW.md for detailed troubleshooting.
