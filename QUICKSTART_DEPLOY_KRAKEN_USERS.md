# QUICK START: Deploy Multi-User Kraken Trading

**Goal**: Get both users (Daivon & Tania) trading on Kraken  
**Time**: 5-10 minutes  
**Status**: ✅ Code Ready - Just needs environment variables

---

## What's Already Done ✅

- User #1 (Daivon Frazier) initialized
- User #2 (Tania Gilbert) initialized
- Kraken integration code ready
- All scripts tested and working
- Documentation complete

---

## What You Need To Do (3 Steps)

### Step 1: Set Environment Variables (2 minutes)

Go to your deployment platform and add these 4 variables:

#### Railway
1. Go to https://railway.app → Your Project
2. Click Service → "Variables" tab
3. Click "+ New Variable" for each:

```
KRAKEN_USER_DAIVON_API_KEY
8zdYy7PMRjnyDraiJUtrAb3wmu8MFxKBON3nrTkjkwnJ9iIUQyKNGKP7

KRAKEN_USER_DAIVON_API_SECRET
e2xaakHliGa5RwH7uXwuq6RLGospWaQhScaVJfsS6wIa9huHxmx+HgeQCax8A+gvqV3P9jXD9YbR3wtsipdpRA==

KRAKEN_USER_TANIA_API_KEY
XEB37FsbsQ2Wj/bknOy6HPZTFqs25nyU10M2oxF/ja//Yh/r2kSRCAp/

KRAKEN_USER_TANIA_API_SECRET
iINPAKFyVe9rTfYCKnauFCpOfqdsm9+lBFxzx2KLFkArjStbjAQ9Rr+FuA5lZgnzpZ85wMwnzKpkO07iHmMLmw==
```

4. Service will auto-deploy

#### Render
Same process, use "Environment" tab instead of "Variables"

### Step 2: Verify Deployment (1 minute)

Check your service logs for these success messages:

```
✅ KRAKEN PRO CONNECTED (USER:daivon_frazier)
   USD Balance: $XXX.XX
   
✅ KRAKEN PRO CONNECTED (USER:tania_gilbert)
   USD Balance: $XXX.XX
```

If you see these, **YOU'RE DONE!** Both users are trading.

### Step 3: Fund Accounts (5 minutes)

Transfer USD/USDT to each Kraken account:
- **Minimum**: $50 per account
- **Recommended**: $100+ per account

---

## How To Verify It's Working

### Check Logs
Look for:
```
✅ User #1 Kraken connection successful
✅ User #2 Kraken connection successful
```

### Common Issues

**"Kraken credentials not configured"**
→ Environment variables not set correctly

**"Permission denied"**  
→ API keys need permissions enabled on Kraken:
1. Go to https://www.kraken.com/u/security/api
2. Edit each API key
3. Enable: Query Funds, Query Orders, Create Orders, Cancel Orders

**"No balance"**
→ Fund the Kraken accounts

---

## What Happens Next

Once deployed with environment variables:

1. **Bot starts** → Loads both users from database
2. **Connects to Kraken** → Using the API keys you set
3. **Scans markets** → 732+ crypto pairs every 2.5 minutes
4. **Places trades** → For BOTH users simultaneously
5. **Tracks positions** → Separate P&L for each user
6. **Manages risk** → $300 max per trade, $150 max daily loss

---

## Management Commands

If you need to enable/disable users later:

```bash
# Check status
python manage_user_daivon.py status
python manage_user_tania.py status

# Disable trading
python manage_user_daivon.py disable
python manage_user_tania.py disable

# Re-enable trading
python manage_user_daivon.py enable
python manage_user_tania.py enable
```

---

## Support

**Everything working?** 
→ Great! Both users are now trading automatically on Kraken.

**Need help?**
→ See `MULTI_USER_KRAKEN_SETUP_COMPLETE.md` for detailed troubleshooting

**Want to add more users?**
→ See `ENV_VARS_SETUP_GUIDE.md` for the pattern to follow

---

**Ready to deploy?** Just set those 4 environment variables and you're done! 🚀
