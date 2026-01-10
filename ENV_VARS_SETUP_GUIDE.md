# Environment Variables Setup Guide for Multi-User Kraken Trading

**Quick Reference for Deploying User Accounts**  
**Updated**: January 10, 2026

---

## Overview

This guide shows you how to configure environment variables for multi-user Kraken trading on different deployment platforms.

---

## Required Environment Variables

### User #1: Daivon Frazier

```bash
KRAKEN_USER_DAIVON_API_KEY=8zdYy7PMRjnyDraiJUtrAb3wmu8MFxKBON3nrTkjkwnJ9iIUQyKNGKP7
KRAKEN_USER_DAIVON_API_SECRET=e2xaakHliGa5RwH7uXwuq6RLGospWaQhScaVJfsS6wIa9huHxmx+HgeQCax8A+gvqV3P9jXD9YbR3wtsipdpRA==
```

### User #2: Tania Gilbert

```bash
KRAKEN_USER_TANIA_API_KEY=XEB37FsbsQ2Wj/bknOy6HPZTFqs25nyU10M2oxF/ja//Yh/r2kSRCAp/
KRAKEN_USER_TANIA_API_SECRET=iINPAKFyVe9rTfYCKnauFCpOfqdsm9+lBFxzx2KLFkArjStbjAQ9Rr+FuA5lZgnzpZ85wMwnzKpkO07iHmMLmw==
```

---

## Platform-Specific Setup

### Railway

1. **Navigate to Project**
   - Go to https://railway.app
   - Select your NIJA project

2. **Open Variables Tab**
   - Click on your service
   - Go to "Variables" tab

3. **Add Variables**
   - Click "+ New Variable"
   - Add each variable one at a time:
     - `KRAKEN_USER_DAIVON_API_KEY` = `8zdYy7PMRjnyDraiJUtrAb3wmu8MFxKBON3nrTkjkwnJ9iIUQyKNGKP7`
     - `KRAKEN_USER_DAIVON_API_SECRET` = `e2xaakHliGa5RwH7uXwuq6RLGospWaQhScaVJfsS6wIa9huHxmx+HgeQCax8A+gvqV3P9jXD9YbR3wtsipdpRA==`
     - `KRAKEN_USER_TANIA_API_KEY` = `XEB37FsbsQ2Wj/bknOy6HPZTFqs25nyU10M2oxF/ja//Yh/r2kSRCAp/`
     - `KRAKEN_USER_TANIA_API_SECRET` = `iINPAKFyVe9rTfYCKnauFCpOfqdsm9+lBFxzx2KLFkArjStbjAQ9Rr+FuA5lZgnzpZ85wMwnzKpkO07iHmMLmw==`

4. **Redeploy**
   - Service will automatically redeploy with new variables
   - Or click "Redeploy" button to force immediate deployment

### Render

1. **Navigate to Service**
   - Go to https://render.com
   - Select your NIJA service

2. **Open Environment Tab**
   - Click "Environment" in left sidebar

3. **Add Variables**
   - Click "+ Add Environment Variable"
   - Add each variable:
     - Key: `KRAKEN_USER_DAIVON_API_KEY`  
       Value: `8zdYy7PMRjnyDraiJUtrAb3wmu8MFxKBON3nrTkjkwnJ9iIUQyKNGKP7`
     - Key: `KRAKEN_USER_DAIVON_API_SECRET`  
       Value: `e2xaakHliGa5RwH7uXwuq6RLGospWaQhScaVJfsS6wIa9huHxmx+HgeQCax8A+gvqV3P9jXD9YbR3wtsipdpRA==`
     - Key: `KRAKEN_USER_TANIA_API_KEY`  
       Value: `XEB37FsbsQ2Wj/bknOy6HPZTFqs25nyU10M2oxF/ja//Yh/r2kSRCAp/`
     - Key: `KRAKEN_USER_TANIA_API_SECRET`  
       Value: `iINPAKFyVe9rTfYCKnauFCpOfqdsm9+lBFxzx2KLFkArjStbjAQ9Rr+FuA5lZgnzpZ85wMwnzKpkO07iHmMLmw==`

4. **Save**
   - Service will automatically redeploy

### Heroku

1. **Using Web Dashboard**
   - Go to https://dashboard.heroku.com
   - Select your app
   - Go to "Settings" tab
   - Click "Reveal Config Vars"
   - Add each variable (same as Railway/Render)

2. **Using CLI**
   ```bash
   heroku config:set KRAKEN_USER_DAIVON_API_KEY=8zdYy7PMRjnyDraiJUtrAb3wmu8MFxKBON3nrTkjkwnJ9iIUQyKNGKP7
   heroku config:set KRAKEN_USER_DAIVON_API_SECRET=e2xaakHliGa5RwH7uXwuq6RLGospWaQhScaVJfsS6wIa9huHxmx+HgeQCax8A+gvqV3P9jXD9YbR3wtsipdpRA==
   heroku config:set KRAKEN_USER_TANIA_API_KEY=XEB37FsbsQ2Wj/bknOy6HPZTFqs25nyU10M2oxF/ja//Yh/r2kSRCAp/
   heroku config:set KRAKEN_USER_TANIA_API_SECRET=iINPAKFyVe9rTfYCKnauFCpOfqdsm9+lBFxzx2KLFkArjStbjAQ9Rr+FuA5lZgnzpZ85wMwnzKpkO07iHmMLmw==
   ```

### Local Development (.env file)

1. **Create/Update .env file**
   ```bash
   # Navigate to project directory
   cd /path/to/Nija
   
   # Add variables to .env file
   cat >> .env << EOF
   KRAKEN_USER_DAIVON_API_KEY=8zdYy7PMRjnyDraiJUtrAb3wmu8MFxKBON3nrTkjkwnJ9iIUQyKNGKP7
   KRAKEN_USER_DAIVON_API_SECRET=e2xaakHliGa5RwH7uXwuq6RLGospWaQhScaVJfsS6wIa9huHxmx+HgeQCax8A+gvqV3P9jXD9YbR3wtsipdpRA==
   KRAKEN_USER_TANIA_API_KEY=XEB37FsbsQ2Wj/bknOy6HPZTFqs25nyU10M2oxF/ja//Yh/r2kSRCAp/
   KRAKEN_USER_TANIA_API_SECRET=iINPAKFyVe9rTfYCKnauFCpOfqdsm9+lBFxzx2KLFkArjStbjAQ9Rr+FuA5lZgnzpZ85wMwnzKpkO07iHmMLmw==
   EOF
   ```

2. **Verify .env file**
   ```bash
   cat .env | grep KRAKEN_USER
   ```

---

## How Environment Variables Work

### Variable Naming Convention

Format: `KRAKEN_USER_{FIRSTNAME}_API_KEY` and `KRAKEN_USER_{FIRSTNAME}_API_SECRET`

**Examples**:
- User ID `daivon_frazier` → Environment variable prefix `KRAKEN_USER_DAIVON_`
- User ID `tania_gilbert` → Environment variable prefix `KRAKEN_USER_TANIA_`
- User ID `john_smith` → Environment variable prefix `KRAKEN_USER_JOHN_`

**How it works**:
1. The system extracts the first name from the user_id
2. Converts to uppercase: `daivon_frazier` → `DAIVON`
3. Constructs env var name: `KRAKEN_USER_DAIVON_API_KEY`

### Loading Process

1. Bot starts up
2. Attempts to initialize each user's Kraken broker
3. Looks for environment variables:
   - `KRAKEN_USER_{FIRSTNAME}_API_KEY`
   - `KRAKEN_USER_{FIRSTNAME}_API_SECRET`
4. If found, connects to Kraken API
5. If not found, skips that user with warning (not an error)

---

## Verification

### After Setting Variables

1. **Restart the service** (if not auto-restarted)

2. **Check logs for connection messages**:
   ```
   ✅ KRAKEN PRO CONNECTED (USER:daivon_frazier)
   ✅ KRAKEN PRO CONNECTED (USER:tania_gilbert)
   ```

3. **Run activation script**:
   ```bash
   python activate_both_users_kraken.py
   ```

4. **Check individual user status**:
   ```bash
   python manage_user_daivon.py status
   python manage_user_tania.py status
   ```

---

## Troubleshooting

### "Kraken credentials not configured"

**Cause**: Environment variables not set or misspelled  
**Solution**: 
1. Verify exact variable names (case-sensitive)
2. Check for typos in API key/secret
3. Restart service after adding variables

### "Permission denied" or "API key invalid"

**Cause**: API key lacks required permissions  
**Solution**: 
1. Go to https://www.kraken.com/u/security/api
2. Edit API key permissions
3. Enable: Query Funds, Orders, Trades, Create Orders, Cancel Orders

### User still not trading

**Cause**: User account disabled or database not loaded  
**Solution**:
1. Run `python init_user_tania.py` to initialize
2. Run `python manage_user_tania.py enable` to enable trading
3. Check `users_db.json` exists and contains user data

---

## Security Best Practices

✅ **Never commit .env file to git** (already in `.gitignore`)  
✅ **Use platform environment variables** for production  
✅ **Rotate API keys regularly** (every 3-6 months)  
✅ **Use minimum required permissions** on API keys  
✅ **Never enable "Withdraw Funds" permission**  
✅ **Monitor API key usage** in Kraken dashboard  

---

## Adding Future Users

To add a new user (e.g., "John Smith" with user_id `john_smith`):

1. **Create initialization script**: `init_user_john.py`
2. **Create management script**: `manage_user_john.py`
3. **Set environment variables**:
   ```bash
   KRAKEN_USER_JOHN_API_KEY=<john's-api-key>
   KRAKEN_USER_JOHN_API_SECRET=<john's-api-secret>
   ```
4. **Run initialization**: `python init_user_john.py`
5. **Verify connection**: `python manage_user_john.py status`

---

## Related Documentation

- `USER_INVESTOR_REGISTRY.md` - Complete user registry
- `USER_SETUP_COMPLETE_TANIA.md` - Tania's setup documentation
- `USER_SETUP_COMPLETE_DAIVON.md` - Daivon's setup documentation
- `MULTI_USER_SETUP_GUIDE.md` - Multi-user architecture guide

---

**Last Updated**: January 10, 2026  
**Maintained By**: NIJA System Administrator
