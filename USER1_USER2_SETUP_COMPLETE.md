# User #1 and User #2 Trading Setup

## Status: ✅ CONFIGURED AND ENABLED

This document confirms that User #1 (Daivon Frazier) and User #2 (Tania Gilbert) are properly configured and ready to start trading.

## Users Configured

### User #1: Daivon Frazier
- **User ID**: `daivon_frazier`
- **Account Type**: Retail
- **Broker**: Kraken
- **Status**: ✅ **ENABLED**
- **Configuration File**: `config/users/retail_kraken.json`

### User #2: Tania Gilbert
- **User ID**: `tania_gilbert`
- **Account Type**: Retail
- **Broker**: Kraken
- **Status**: ✅ **ENABLED**
- **Configuration File**: `config/users/retail_kraken.json`

## Configuration Summary

Both users are:
- ✅ Defined in the configuration file
- ✅ Marked as `enabled: true`
- ✅ Using Kraken as their broker
- ✅ Set up as retail accounts
- ✅ Ready to trade once API credentials are provided

## Required API Credentials

To enable trading for these users, add the following environment variables to your `.env` file:

```bash
# User #1: Daivon Frazier - Kraken
KRAKEN_USER_DAIVON_API_KEY=your_api_key_here
KRAKEN_USER_DAIVON_API_SECRET=your_api_secret_here

# User #2: Tania Gilbert - Kraken
KRAKEN_USER_TANIA_API_KEY=your_api_key_here
KRAKEN_USER_TANIA_API_SECRET=your_api_secret_here
```

### How to Get Kraken API Keys

1. Log in to your Kraken account
2. Go to: **Settings** → **API** → **Generate New Key**
3. Use **"Classic API Key"** (NOT OAuth or App keys)
4. Enable the following permissions:
   - ✅ Query Funds
   - ✅ Query Open Orders & Trades
   - ✅ Query Closed Orders & Trades
   - ✅ Create & Modify Orders
   - ✅ Cancel/Close Orders
   - ❌ Do NOT enable "Withdraw Funds"
5. Copy the API Key and API Secret
6. Add them to your `.env` file using the variable names above

## Verification Scripts

Two scripts are provided to help you verify and connect the users:

### 1. Verify Users Are Ready
```bash
python3 verify_users_ready.py
```

This script checks:
- ✅ Users exist in configuration files
- ✅ Users are enabled
- ✅ Configuration structure is correct
- ✅ API credentials are set (if available)
- ✅ System is ready to start trading

### 2. Connect and Enable Trading
```bash
python3 connect_and_enable_users.py
```

This script:
- Loads user configurations
- Verifies users are enabled
- Checks for API credentials
- Connects to Kraken for each user
- Retrieves account balances
- Enables trading for both users
- Reports connection status

## Quick Start Guide

### Step 1: Verify Configuration
```bash
python3 verify_users_ready.py
```

Expected output:
```
✅ User #1 (Daivon Frazier) - configured, enabled
✅ User #2 (Tania Gilbert) - configured, enabled
```

### Step 2: Add API Credentials

Edit your `.env` file and add the Kraken API credentials for both users.

### Step 3: Connect and Enable Trading
```bash
python3 connect_and_enable_users.py
```

Expected output:
```
✅ User #1: Daivon Frazier connected successfully
✅ User #2: Tania Gilbert connected successfully
✅ Trading enabled for both users
```

## Configuration File Reference

The users are defined in: `config/users/retail_kraken.json`

```json
[
  {
    "user_id": "daivon_frazier",
    "name": "Daivon Frazier",
    "account_type": "retail",
    "broker_type": "kraken",
    "enabled": true,
    "description": "Retail user - Kraken crypto account"
  },
  {
    "user_id": "tania_gilbert",
    "name": "Tania Gilbert",
    "account_type": "retail",
    "broker_type": "kraken",
    "enabled": true,
    "description": "Retail user - Kraken crypto account"
  }
]
```

## Environment Variables

The NIJA bot uses the following naming convention for user API credentials:

```
{BROKER}_USER_{FIRSTNAME}_API_KEY
{BROKER}_USER_{FIRSTNAME}_API_SECRET
```

For our users:
- **User #1** (daivon_frazier): `KRAKEN_USER_DAIVON_*`
- **User #2** (tania_gilbert): `KRAKEN_USER_TANIA_*`

The system extracts the first name from the user_id and converts it to uppercase.

## Trading Architecture

- **MASTER Account**: NIJA system controls overall trading strategy
- **User Accounts**: Individual retail users trade according to NIJA's strategy
- **Broker**: Kraken cryptocurrency exchange
- **Strategy**: APEX v7.1 dual RSI strategy
- **Account Type**: Retail (individual users)

## Security Notes

⚠️ **Important Security Practices:**

1. **Never commit API keys** to version control
2. Keep your `.env` file secure and private
3. Use API key restrictions when available:
   - IP whitelisting
   - Limited permissions (no withdrawals)
4. Rotate API keys periodically
5. Monitor API key usage for unusual activity

## Next Steps

Once both users are connected and trading is enabled:

1. **Monitor Trading Activity**
   - Check logs for trade execution
   - Monitor account balances
   - Review position entries and exits

2. **Track Performance**
   - Use the user dashboard API
   - Check PnL tracking
   - Review risk management metrics

3. **Adjust Settings** (if needed)
   - Modify risk limits
   - Update trading parameters
   - Configure webhooks for notifications

## Troubleshooting

### Users Not Connecting

1. Verify API credentials are correct
2. Check API key permissions
3. Ensure API keys are for the correct Kraken account
4. Verify network connectivity

### Trading Not Starting

1. Check if users are enabled in config
2. Verify API credentials are set
3. Check for error messages in logs
4. Run `verify_users_ready.py` to diagnose

### Connection Errors

1. Verify Kraken API endpoint is accessible
2. Check for rate limiting issues
3. Ensure API keys have required permissions
4. Review error logs for specific issues

## Support Files

- **Configuration**: `config/users/retail_kraken.json`
- **Verification Script**: `verify_users_ready.py`
- **Connection Script**: `connect_and_enable_users.py`
- **User Loader Module**: `config/user_loader.py`
- **Broker Manager**: `bot/broker_manager.py`
- **Example**: `.env.example` (reference for required variables)

## References

- [Kraken API Documentation](https://docs.kraken.com/rest/)
- [User Setup Guide](USER_SETUP_GUIDE.md)
- [Multi-User Setup Guide](MULTI_USER_SETUP_GUIDE.md)
- [Environment Variables Reference](.env.example)

---

**Last Updated**: 2026-01-18  
**Status**: ✅ Configuration Complete - Ready for API Credentials  
**Users**: 2 (Both Enabled)
