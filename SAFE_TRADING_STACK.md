# Safe Trading Stack Documentation

This document describes the safe trading stack implementation for the Nija trading bot.

## Overview

The safe trading stack provides multiple layers of protection to prevent accidental trading from a funded account:

1. **Trading Modes** - SANDBOX, DRY_RUN, or LIVE
2. **Live Trading Guards** - Required confirmations for live trading
3. **API Key Safety** - Checks for dangerous permissions
4. **TradingView Webhook** - Secure webhook endpoint with HMAC verification
5. **Centralized Order Submission** - Rate limits, size limits, and audit logging
6. **Manual Approval** - Optional approval workflow for first N trades

## Environment Variables

### Trading Mode
- `MODE` - Trading mode: `SANDBOX`, `DRY_RUN`, or `LIVE` (default: `DRY_RUN`)

### Live Trading Safety
- `COINBASE_ACCOUNT_ID` - Required when MODE=LIVE
- `CONFIRM_LIVE` - Must be `true` when MODE=LIVE (safety check)

### Order Limits
- `MAX_ORDER_USD` - Maximum order size in USD (default: `100.0`)
- `MAX_ORDERS_PER_MINUTE` - Rate limit for orders (default: `10`)

### Manual Approval
- `MANUAL_APPROVAL_COUNT` - Number of orders requiring manual approval (default: `0`)
  - When > 0, first N orders are marked pending until approved
  - Approvals tracked in `{LOG_PATH}_pending_approvals.json`

### Audit Logging
- `LOG_PATH` - Path to audit log file (default: `/tmp/nija_orders.log`)

### TradingView Webhook
- `TRADINGVIEW_WEBHOOK_SECRET` - Secret key for HMAC signature verification

### Other Configuration
- `COINBASE_API_BASE` - Coinbase API base URL (default: `https://api.coinbase.com`)
- `MIN_TRADE_PERCENT` - Minimum trade size as % of balance (default: `1.0`)
- `MAX_TRADE_PERCENT` - Maximum trade size as % of balance (default: `5.0`)

## Trading Modes

### SANDBOX Mode
```bash
export MODE=SANDBOX
```
- Uses test environment
- No real money involved
- Safe for testing

### DRY_RUN Mode (Default)
```bash
export MODE=DRY_RUN
```
- Simulates orders without executing them
- Logs what would have been done
- Default mode for safety

### LIVE Mode
```bash
export MODE=LIVE
export COINBASE_ACCOUNT_ID=your-account-id
export CONFIRM_LIVE=true
```
- ⚠️ **DANGER**: Real money at risk!
- Requires both `COINBASE_ACCOUNT_ID` and `CONFIRM_LIVE=true`
- Will refuse to start without both set
- Checks API key permissions

## Modules

### config.py
Centralized configuration module that reads environment variables and provides defaults.

### safe_order.py
Centralized order submission wrapper with safety checks:

```python
from safe_order import submit_order
from nija_client import CoinbaseClient

client = CoinbaseClient()

# Submit a safe order
result = submit_order(
    client=client,
    symbol='BTC-USD',
    side='buy',
    size_usd=50.0
)
```

**Safety Features:**
- Validates MODE and account requirements
- Enforces MAX_ORDER_USD limit
- Rate limits by MAX_ORDERS_PER_MINUTE
- Handles manual approval workflow
- Logs all orders to audit file

### tv_webhook.py
Flask blueprint for TradingView webhook integration:

**Endpoint:** `POST /webhook/tradingview`

**Headers:**
- `X-Tv-Signature` - HMAC SHA256 signature of request body

**Payload:**
```json
{
  "symbol": "BTC-USD",
  "action": "buy",
  "size": 50.0
}
```

**Signature Generation (TradingView):**
```javascript
// In TradingView webhook settings, use:
// Secret: <your TRADINGVIEW_WEBHOOK_SECRET>
```

The signature is verified using HMAC SHA256:
```python
signature = hmac.new(
    TRADINGVIEW_WEBHOOK_SECRET.encode('utf-8'),
    request_body,
    hashlib.sha256
).hexdigest()
```

### nija_client.py
Enhanced Coinbase client with safety checks:

```python
from nija_client import CoinbaseClient, check_live_safety

# Manually check safety
check_live_safety()

# Client automatically checks on initialization
client = CoinbaseClient()
```

**Safety Checks:**
- Validates MODE configuration
- Requires COINBASE_ACCOUNT_ID and CONFIRM_LIVE for LIVE mode
- Checks API key permissions for withdraw permission
- Logs safety status

## Manual Approval Workflow

When `MANUAL_APPROVAL_COUNT > 0`, the first N orders require manual approval:

1. Order is submitted via `safe_order.submit_order()`
2. Order is marked as `pending_approval`
3. Order details saved to `{LOG_PATH}_pending_approvals.json`
4. To approve, edit the file and set `approved: true` for the order
5. Next order submission reloads approval state
6. Once N orders approved, subsequent orders proceed normally

**Example approval file:**
```json
{
  "orders": [
    {
      "timestamp": "2025-11-21T21:00:00.000000",
      "request": {
        "symbol": "BTC-USD",
        "side": "buy",
        "size_usd": 50.0
      },
      "approved": true,
      "order_number": 1
    }
  ]
}
```

## Audit Logging

Every order request and response is logged to `LOG_PATH`:

```json
{
  "timestamp": "2025-11-21T21:00:00.000000",
  "mode": "DRY_RUN",
  "request": {
    "symbol": "BTC-USD",
    "side": "buy",
    "size_usd": 50.0,
    "type": "market"
  },
  "response": {
    "status": "dry_run",
    "message": "DRY RUN: BUY $50.0 BTC-USD"
  }
}
```

## Testing

Run the test suite:

```bash
# Unit tests
python test_safe_trading_stack.py

# Integration tests
python test_integration.py
```

## Example Usage

### Development (DRY_RUN)
```bash
export MODE=DRY_RUN
export MAX_ORDER_USD=100.0
python main.py
```

### Testing with Manual Approval
```bash
export MODE=DRY_RUN
export MANUAL_APPROVAL_COUNT=3
export LOG_PATH=/tmp/nija_orders.log
python main.py

# After 3 orders are approved in the pending file, normal operation resumes
```

### Production (LIVE) - Use with Extreme Caution
```bash
export MODE=LIVE
export COINBASE_ACCOUNT_ID=your-real-account-id
export CONFIRM_LIVE=true
export MAX_ORDER_USD=50.0
export MAX_ORDERS_PER_MINUTE=5
export LOG_PATH=/var/log/nija_orders.log
python main.py
```

## Security Considerations

1. **Never commit secrets** - Use environment variables, not hardcoded values
2. **API Key Permissions** - Create API keys without withdraw permission
3. **Webhook Secret** - Use a strong random string for TRADINGVIEW_WEBHOOK_SECRET
4. **Rate Limiting** - Set conservative MAX_ORDERS_PER_MINUTE values
5. **Order Size Limits** - Set MAX_ORDER_USD to a safe value for your account
6. **Manual Approval** - Use MANUAL_APPROVAL_COUNT when first deploying to production
7. **Monitor Logs** - Review LOG_PATH regularly for unexpected activity

## Troubleshooting

### "MODE=LIVE requires COINBASE_ACCOUNT_ID to be set"
Set the `COINBASE_ACCOUNT_ID` environment variable before running in LIVE mode.

### "MODE=LIVE requires CONFIRM_LIVE=true to be set"
Set `CONFIRM_LIVE=true` to acknowledge you want to trade with real money.

### "API key has WITHDRAW permission"
Create a new API key without withdraw permission for safety.

### "Rate limit exceeded"
Reduce your trading frequency or increase `MAX_ORDERS_PER_MINUTE`.

### "Order size exceeds MAX_ORDER_USD"
Reduce order size or increase `MAX_ORDER_USD` (carefully!).

### Webhook signature verification fails
Ensure `TRADINGVIEW_WEBHOOK_SECRET` matches the secret configured in TradingView.
