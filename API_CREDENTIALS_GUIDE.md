# API Credentials Setup Guide

## Overview

This guide explains how to configure API credentials for the NIJA trading bot, with a focus on secure credential management following industry best practices.

## Kraken Platform Credentials

### Local Development

For local development, Kraken platform credentials are stored in the `.env` file in the repository root:

```bash
KRAKEN_PLATFORM_API_KEY=<your-api-key>
KRAKEN_PLATFORM_API_SECRET=<your-api-secret>
```

**Important Security Notes:**
- ✅ The `.env` file is automatically excluded from version control (listed in `.gitignore`)
- ✅ Never commit the `.env` file to git
- ✅ Never share your `.env` file or credentials publicly
- ✅ Rotate credentials regularly for security

### Production Deployment

For production deployments (Railway, Heroku, Render, etc.), set the following environment variables in your platform's dashboard:

```
KRAKEN_PLATFORM_API_KEY=<your-api-key>
KRAKEN_PLATFORM_API_SECRET=<your-api-secret>
```

**Platform-Specific Instructions:**

#### Railway
1. Go to your project → Variables tab
2. Click "+ New Variable"
3. Add `KRAKEN_PLATFORM_API_KEY` with your API key
4. Add `KRAKEN_PLATFORM_API_SECRET` with your API secret
5. Deploy

#### Heroku
1. Go to Settings → Config Vars
2. Click "Reveal Config Vars"
3. Add `KRAKEN_PLATFORM_API_KEY` with your API key
4. Add `KRAKEN_PLATFORM_API_SECRET` with your API secret

#### Render
1. Go to Environment → Environment Variables
2. Add `KRAKEN_PLATFORM_API_KEY` with your API key
3. Add `KRAKEN_PLATFORM_API_SECRET` with your API secret
4. Save changes

## How It Works

The NIJA bot automatically loads these credentials when connecting to Kraken:

1. **Local Development**: The `broker_manager.py` module uses `python-dotenv` to load credentials from the `.env` file
2. **Production**: The bot reads environment variables directly from the deployment platform
3. **Fallback**: If `KRAKEN_PLATFORM_API_KEY` is not found, the bot falls back to legacy `KRAKEN_API_KEY` for backward compatibility

## Getting Kraken API Credentials

To obtain your Kraken API credentials:

1. Log in to [Kraken.com](https://www.kraken.com)
2. Go to Settings → API
3. Click "Generate New Key"
4. **Important**: Use "Classic API Key" (NOT OAuth)
5. Enable required permissions:
   - ✅ Query Funds
   - ✅ Query Open Orders & Trades
   - ✅ Query Closed Orders & Trades
   - ✅ Create & Modify Orders
   - ✅ Cancel/Close Orders
   - ❌ Do NOT enable "Withdraw Funds"
6. Copy the API Key and API Secret

## Verification

To verify that credentials are properly configured:

1. Check that `.env` file exists in repository root (local development only)
2. Verify credentials are loaded:
   ```bash
   python3 -c "import os; from dotenv import load_dotenv; load_dotenv(); print('API Key loaded:', bool(os.getenv('KRAKEN_PLATFORM_API_KEY'))); print('API Secret loaded:', bool(os.getenv('KRAKEN_PLATFORM_API_SECRET')))"
   ```
3. Start the bot and check logs for "✅ Using KRAKEN_PLATFORM_API_KEY"

## Other Broker Credentials

### Coinbase (Optional - Currently Disabled)

Coinbase integration is currently disabled per user request. If you need to re-enable it, see `.env.example` for configuration details.

### Alpaca (Stock Trading)

For stock trading via Alpaca:

```bash
ALPACA_API_KEY=<your-api-key>
ALPACA_API_SECRET=<your-api-secret>
ALPACA_PAPER=true  # Set to false for live trading
```

See `.env.example` for complete Alpaca configuration options.

### OKX and Binance (Optional)

For OKX and Binance exchanges, see `.env.example` for required credentials and configuration.

## Troubleshooting

### Credentials Not Loading

If credentials are not loading:

1. **Local Development**: Ensure `.env` file exists in repository root
2. **Production**: Verify environment variables are set in platform dashboard
3. **Both**: Check for leading/trailing whitespace in credential values
4. **Both**: Ensure `python-dotenv` is installed: `pip install python-dotenv`

### Connection Errors

If you see connection errors:

1. Verify credentials are correct (check broker dashboard)
2. For Kraken: Ensure you're using "Classic API Key" not OAuth
3. Check that required permissions are enabled
4. Verify your IP address is not blocked by the broker

## Security Best Practices

### 1. Never Commit Credentials to Version Control

- The `.env` file is in `.gitignore` - keep it that way
- Never add credentials to code files
- Never commit files containing actual credentials

### 2. Use Environment Variables in Production

- Set credentials in platform dashboard
- Never hardcode credentials in deployment configs
- Use secret management tools when available

### 3. Rotate Credentials Regularly

- Generate new API keys periodically
- Revoke old credentials after rotation
- Update all environments after rotation

### 4. Limit Permissions

- Only enable necessary API permissions
- Never enable "Withdraw Funds" unless absolutely necessary
- Use separate API keys for different purposes

### 5. Monitor API Usage

- Check broker dashboards for unexpected API activity
- Set up alerts for unusual activity
- Revoke credentials immediately if compromised

### 6. Secure Your Environment

- Use strong passwords for deployment platforms
- Enable 2FA on all accounts
- Restrict access to production environments
- Keep deployment platforms updated

## Related Documentation

- [KRAKEN_TRADING_GUIDE.md](KRAKEN_TRADING_GUIDE.md) - How to view trades in Kraken
- [BROKER_INTEGRATION_GUIDE.md](BROKER_INTEGRATION_GUIDE.md) - Broker integration details
- [.env.example](.env.example) - Template for environment variables
- [.env.production.example](.env.production.example) - Production environment template

## Support

For issues with credential setup:

1. Check the logs for specific error messages
2. Verify credentials in broker dashboard
3. Review this guide and related documentation
4. Open an issue on GitHub with error details (never include actual credentials)

## Additional Resources

- [Kraken API Documentation](https://docs.kraken.com/rest/)
- [Railway Environment Variables](https://docs.railway.app/deploy/variables)
- [Heroku Config Vars](https://devcenter.heroku.com/articles/config-vars)
- [Render Environment Variables](https://render.com/docs/environment-variables)
