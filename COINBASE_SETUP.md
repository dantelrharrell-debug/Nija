# Coinbase Advanced Trade - JWT Authentication Setup

## Quick Start

NIJA uses **JWT authentication** for Coinbase Advanced Trade API. No PEM files needed.

### Required Environment Variables

```bash
COINBASE_API_KEY=your-api-key-here
COINBASE_API_SECRET=your-api-secret-here
```

### API Endpoints Used

- `GET /v3/accounts` - Fetch account balances
- `GET /v3/brokerage/products` - List trading pairs
- `GET /v3/brokerage/products/{product_id}/candles` - Get price data
- `POST /v3/brokerage/orders` - Place trades

### Test Connection

```bash
python scripts/print_accounts.py
```

### Configuration

Set in your `.env` file or Railway environment variables:

```bash
# Required
COINBASE_API_KEY=your_api_key
COINBASE_API_SECRET=your_api_secret

# Optional
PAPER_MODE=false
ALLOW_CONSUMER_USD=true
```

### Authentication Mode

- **AUTH_MODE**: JWT
- **USE_CDP_AUTH**: False
- No PEM files required
- No cryptography library needed for auth

### Troubleshooting

If you get 401 Unauthorized:
1. Verify `COINBASE_API_KEY` is set correctly
2. Verify `COINBASE_API_SECRET` is set correctly
3. Check API key has required permissions (view, trade)
4. Ensure API key is not expired or revoked

### Reference

- Coinbase Advanced Trade API: https://docs.cloud.coinbase.com/advanced-trade-api/docs
- coinbase-advanced-py SDK: https://github.com/coinbase/coinbase-advanced-py
