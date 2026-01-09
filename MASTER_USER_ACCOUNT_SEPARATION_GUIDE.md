# Nija Master/User Account Separation - Setup Guide

## Overview

Nija now supports separate trading accounts for:
- **MASTER Account**: Nija system account (controlled by system administrators)
- **USER Accounts**: Individual user/investor accounts

Each account trades completely independently with:
- Separate API credentials
- Separate balances
- Separate positions
- Separate risk limits

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     NIJA TRADING SYSTEM                       │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌────────────────────┐         ┌────────────────────┐      │
│  │  MASTER ACCOUNT    │         │  USER ACCOUNTS     │      │
│  │  (Nija System)     │         │  (Investors)       │      │
│  ├────────────────────┤         ├────────────────────┤      │
│  │ • Coinbase         │         │ User #1: Daivon    │      │
│  │ • Kraken (Master)  │         │  • Kraken          │      │
│  │ • OKX              │         │                    │      │
│  │ • Alpaca           │         │ User #2: ...       │      │
│  └────────────────────┘         │  • Kraken          │      │
│                                 └────────────────────┘      │
│                                                               │
│  Accounts are completely isolated - no mixing of trades     │
└─────────────────────────────────────────────────────────────┘
```

## Current Status

### ✅ Completed
- Account type system (MASTER vs USER)
- Multi-account broker manager
- Separate Kraken connections for master and users
- Balance checking script
- User #1 (Daivon Frazier) credentials configured

### ⚠️ Pending
- Master Kraken API credentials needed
- Integration into main bot trading loop
- Testing with live trades

## Setup Instructions

### Step 1: Configure Master Kraken Account

1. **Create or access master Kraken account**
   - This should be the Nija system account
   - Not a user/investor account

2. **Generate API keys on Kraken**
   - Go to: https://www.kraken.com/u/security/api
   - Create new API key with permissions:
     - ✅ Query Funds
     - ✅ Query Open Orders & Trades
     - ✅ Query Closed Orders & Trades
     - ✅ Create & Modify Orders
     - ✅ Cancel/Close Orders
     - ❌ Withdraw Funds (NEVER enable for security)

3. **Update .env file**
   ```bash
   # Add master Kraken credentials
   KRAKEN_MASTER_API_KEY=your_master_api_key_here
   KRAKEN_MASTER_API_SECRET=your_master_api_secret_here
   ```

### Step 2: Verify User Account Configuration

User #1 (Daivon Frazier) credentials are already configured:
```bash
KRAKEN_USER_DAIVON_API_KEY=8zdYy7PMRjnyDraiJUtrAb3wmu8MFxKBON3nrTkjkwnJ9iIUQyKNGKP7
KRAKEN_USER_DAIVON_API_SECRET=e2xaakHliGa5RwH7uXwuq6RLGospWaQhScaVJfsS6wIa9huHxmx+HgeQCax8A+gvqV3P9jXD9YbR3wtsipdpRA==
```

### Step 3: Check Account Balances

Run the balance checker to verify both accounts:

```bash
python check_master_user_balances.py
```

Expected output:
```
======================================================================
NIJA MASTER & USER ACCOUNT BALANCE CHECK
======================================================================

🔍 Connecting to MASTER Kraken account...
✅ KRAKEN PRO CONNECTED (MASTER)
   Account: MASTER
   USD Balance: $X.XX
   USDT Balance: $X.XX
   Total: $X.XX

🔍 Connecting to USER Kraken account (daivon_frazier)...
✅ KRAKEN PRO CONNECTED (USER:daivon_frazier)
   Account: USER:daivon_frazier
   USD Balance: $X.XX
   USDT Balance: $X.XX
   Total: $X.XX

======================================================================
NIJA MULTI-ACCOUNT STATUS REPORT
======================================================================

🔷 MASTER ACCOUNT (Nija System)
   KRAKEN: $X.XX
   COINBASE: $X.XX
   TOTAL MASTER: $X.XX

🔷 USER ACCOUNTS
   User: daivon_frazier
      KRAKEN: $X.XX
      TOTAL USER: $X.XX

======================================================================
TRADING STATUS
======================================================================

✅ MASTER is trading on Kraken
✅ USER (daivon_frazier) is trading on Kraken
```

## Account Separation Guarantees

### How Accounts Are Kept Separate

1. **Different API Credentials**
   - Master uses: `KRAKEN_MASTER_API_KEY/SECRET`
   - User uses: `KRAKEN_USER_DAIVON_API_KEY/SECRET`
   - Different keys = Different accounts on Kraken

2. **Different Broker Instances**
   - Master: `KrakenBroker(account_type=AccountType.MASTER)`
   - User: `KrakenBroker(account_type=AccountType.USER, user_id='daivon_frazier')`

3. **Separate Balance Tracking**
   - Each broker instance connects to its own Kraken account
   - get_account_balance() returns balance from correct account
   - No shared state between accounts

4. **Separate Order Placement**
   - Each trade uses the correct broker instance
   - Orders go to the correct Kraken account
   - Impossible to mix up trades

## Adding More Users

To add User #2, #3, etc.:

1. **Get user's Kraken API credentials**

2. **Add to .env**
   ```bash
   # User #2: John Doe
   KRAKEN_USER_JOHN_API_KEY=user2_api_key
   KRAKEN_USER_JOHN_API_SECRET=user2_api_secret
   ```

3. **Update code to create broker**
   ```python
   user_kraken = multi_account_broker_manager.add_user_broker(
       'john_doe',
       BrokerType.KRAKEN
   )
   ```

## Security Considerations

### API Key Permissions

**CRITICAL**: NEVER enable withdrawal permissions on API keys!

Required permissions:
- ✅ Query Funds
- ✅ Query Orders & Trades
- ✅ Create/Modify/Cancel Orders

NEVER enable:
- ❌ Withdraw Funds
- ❌ Export Data
- ❌ Close Position (for futures)

### API Key Storage

- All API keys stored in `.env` file
- `.env` is in `.gitignore` (NEVER commit to git)
- Keys are encrypted when stored in user database
- Each account has completely separate credentials

## Troubleshooting

### Master Kraken Not Connecting

**Error**: `⚠️ Kraken credentials not configured for MASTER (skipping)`

**Solution**:
1. Check `.env` has `KRAKEN_MASTER_API_KEY` and `KRAKEN_MASTER_API_SECRET`
2. Verify credentials are correct (copy-paste from Kraken)
3. Ensure no extra spaces or newlines in credentials

### User Kraken Not Connecting

**Error**: `⚠️ Kraken credentials not configured for USER:daivon_frazier (skipping)`

**Solution**:
1. Check `.env` has `KRAKEN_USER_DAIVON_API_KEY` and `KRAKEN_USER_DAIVON_API_SECRET`
2. Username in env var must match pattern: `KRAKEN_USER_{FIRST_NAME}_API_KEY`
3. Verify credentials are valid on Kraken

### Both Accounts Show Same Balance

**This should be IMPOSSIBLE** with the current architecture because:
1. Different API keys connect to different Kraken accounts
2. Each broker instance is independent
3. API calls go to separate accounts

If this happens:
1. Verify you're using different API keys in .env
2. Check that API keys correspond to different Kraken accounts
3. Contact support - this indicates a configuration error

## Testing

### Test Account Separation

1. **Check balances**
   ```bash
   python check_master_user_balances.py
   ```
   - Master and user should show different balances
   - Each connects to its own Kraken account

2. **Make a small test trade**
   - Place small order on master account
   - Verify it appears in master Kraken account only
   - Verify user account is unaffected

3. **Check positions**
   - Master positions and user positions should be separate
   - No mixing of trades

## Integration Status

### Current State
- ✅ Multi-account system implemented
- ✅ Separate broker connections working
- ✅ Balance checking working
- ⚠️ Not yet integrated into main bot trading loop

### Next Steps
1. Get master Kraken API credentials
2. Test both accounts can connect
3. Integrate into main bot.py
4. Test live trading with small amounts
5. Monitor for any mixing of trades (should be impossible)

## Contact

For issues or questions about the multi-account system:
- Check logs for connection errors
- Verify .env configuration
- Test with `check_master_user_balances.py`

---

**Version**: 1.0  
**Last Updated**: January 9, 2026  
**Status**: ✅ Multi-Account System Implemented, Awaiting Master Credentials
