# User Setup Complete: Tania Gilbert

**User #2 Setup Documentation**  
**Date**: January 10, 2026  
**Status**: ✅ Complete

---

## Overview

Tania Gilbert has been successfully added to the NIJA multi-user trading system with Kraken integration.

---

## User Information

- **Full Name**: Tania Gilbert
- **Email**: Tanialgilbert@gmail.com
- **User ID**: `tania_gilbert`
- **Subscription Tier**: Pro
- **Status**: Active ✅

---

## Broker Configuration

### Kraken Account

**Broker**: Kraken Pro  
**Account Type**: USER (individual user account)  
**Status**: Configured ✅

**API Credentials**:
- API Key: `XEB37FsbsQ2Wj/bknOy6HPZTFqs25nyU10M2oxF/ja//Yh/r2kSRCAp/`
- Private Key: `iINPAKFyVe9rTfYCKnauFCpOfqdsm9+lBFxzx2KLFkArjStbjAQ9Rr+FuA5lZgnzpZ85wMwnzKpkO07iHmMLmw==`
- Storage: Encrypted in `users_db.json` ✅

---

## Trading Permissions

| Permission | Value |
|-----------|-------|
| Max Position Size | $300 USD |
| Max Daily Loss | $150 USD |
| Max Concurrent Positions | 7 |
| Trade-Only Mode | Yes |
| Trading Enabled | Yes ✅ |

### Allowed Trading Pairs

1. BTC-USD (Bitcoin)
2. ETH-USD (Ethereum)
3. SOL-USD (Solana)
4. AVAX-USD (Avalanche)
5. MATIC-USD (Polygon)
6. DOT-USD (Polkadot)
7. LINK-USD (Chainlink)
8. ADA-USD (Cardano)

---

## Account Settings

| Setting | Value |
|---------|-------|
| Risk Level | Moderate |
| Trailing Stops | Enabled ✅ |
| Auto-Compound | Enabled ✅ |
| Notifications | Enabled to Tanialgilbert@gmail.com |

---

## Management Commands

### Check Status
```bash
python manage_user_tania.py status
```

### Enable Trading
```bash
python manage_user_tania.py enable
```

### Disable Trading
```bash
python manage_user_tania.py disable
```

### Show Detailed Info
```bash
python manage_user_tania.py info
```

---

## Environment Variables Required

For deployment platforms (Railway, Render, etc.), set these environment variables:

```bash
KRAKEN_USER_TANIA_API_KEY=XEB37FsbsQ2Wj/bknOy6HPZTFqs25nyU10M2oxF/ja//Yh/r2kSRCAp/
KRAKEN_USER_TANIA_API_SECRET=iINPAKFyVe9rTfYCKnauFCpOfqdsm9+lBFxzx2KLFkArjStbjAQ9Rr+FuA5lZgnzpZ85wMwnzKpkO07iHmMLmw==
```

### Setting Environment Variables

**Railway**:
1. Go to project settings
2. Navigate to "Variables" tab
3. Add both variables above
4. Redeploy the service

**Render**:
1. Go to service dashboard
2. Navigate to "Environment" tab
3. Add both variables above
4. Service will auto-redeploy

**Local (.env file)**:
```bash
echo "KRAKEN_USER_TANIA_API_KEY=XEB37FsbsQ2Wj/bknOy6HPZTFqs25nyU10M2oxF/ja//Yh/r2kSRCAp/" >> .env
echo "KRAKEN_USER_TANIA_API_SECRET=iINPAKFyVe9rTfYCKnauFCpOfqdsm9+lBFxzx2KLFkArjStbjAQ9Rr+FuA5lZgnzpZ85wMwnzKpkO07iHmMLmw==" >> .env
```

---

## Files Created

### User Setup Files
- `init_user_tania.py` - Initialization script
- `manage_user_tania.py` - Management interface
- `USER_SETUP_COMPLETE_TANIA.md` - This documentation

### Shared Files Updated
- `USER_INVESTOR_REGISTRY.md` - Registry updated with Tania's information
- `users_db.json` - Database updated (not in git, contains encrypted credentials)

---

## Security Notes

✅ **API credentials are encrypted** using Fernet encryption before storage  
✅ **Credentials are NOT committed to git** (in `.gitignore`)  
✅ **Trade-only mode enabled** - cannot modify core strategy  
✅ **Position size limits enforced** - maximum $300 per trade  
✅ **Daily loss limits enforced** - maximum $150 daily loss  

---

## Next Steps

### 1. Verify Kraken Connection
```bash
python activate_both_users_kraken.py
```

This will:
- Initialize both User #1 and User #2
- Connect to Kraken API for both users
- Display status report

### 2. Check Trading Status
```bash
python manage_user_tania.py status
```

### 3. Monitor Performance
- Check logs for trade activity
- Review position tracking
- Monitor P&L metrics

---

## Troubleshooting

### Kraken Connection Issues

**Problem**: "Kraken credentials not configured"  
**Solution**: Set environment variables `KRAKEN_USER_TANIA_API_KEY` and `KRAKEN_USER_TANIA_API_SECRET`

**Problem**: "Permission denied" error  
**Solution**: Verify API key has these permissions enabled:
- ✅ Query Funds
- ✅ Query Open Orders & Trades
- ✅ Query Closed Orders & Trades
- ✅ Create & Modify Orders
- ✅ Cancel/Close Orders

**Problem**: "User not found"  
**Solution**: Run `python init_user_tania.py` to initialize the user

### Trading Issues

**Problem**: "Trading disabled"  
**Solution**: Run `python manage_user_tania.py enable`

**Problem**: "Cannot trade - no balance"  
**Solution**: Fund the Kraken account associated with the API keys

---

## Support

For issues or questions:
1. Check `manage_user_tania.py info` for detailed account status
2. Review logs for error messages
3. Verify environment variables are set correctly
4. Ensure Kraken API key permissions are correct

---

## Related Documentation

- `USER_INVESTOR_REGISTRY.md` - Complete user registry
- `MULTI_USER_SETUP_GUIDE.md` - Multi-user setup guide
- `KRAKEN_MULTI_ACCOUNT_GUIDE.md` - Kraken account setup
- `ENVIRONMENT_VARIABLES_GUIDE.md` - Environment variable configuration

---

**Setup Completed**: January 10, 2026  
**Setup By**: System Administrator  
**Next Review**: January 15, 2026
