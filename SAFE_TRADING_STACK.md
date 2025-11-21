# Safe Trading Stack Documentation

This document describes the safe trading stack implementation for the Nija trading bot.

## Overview

The safe trading stack provides comprehensive safety controls and audit logging for cryptocurrency trading operations. It includes:

- **Multi-mode operation**: SANDBOX, DRY_RUN, and LIVE modes
- **Safety controls**: Multiple layers of protection against accidental live trading
- **Rate limiting**: Configurable limits on order frequency
- **Order size limits**: Maximum order size enforcement
- **Manual approval workflow**: Require manual approval for first N orders
- **Audit logging**: Complete audit trail of all order requests
- **Webhook integration**: Secure TradingView webhook endpoint with HMAC verification

## Environment Variables

### Required for LIVE Mode

```bash
# Trading mode - SANDBOX, DRY_RUN, or LIVE (default: DRY_RUN)
MODE=DRY_RUN

# Required for LIVE mode
COINBASE_ACCOUNT_ID=your-account-id-here
CONFIRM_LIVE=true
```

### Optional Configuration

```bash
# Trading limits
MAX_ORDER_USD=100.0              # Maximum order size in USD
MAX_ORDERS_PER_MINUTE=10         # Rate limit for orders
MANUAL_APPROVAL_COUNT=0          # Number of orders requiring manual approval
MIN_TRADE_PERCENT=1.0            # Minimum trade size as % of balance
MAX_TRADE_PERCENT=5.0            # Maximum trade size as % of balance

# Logging
LOG_PATH=/tmp/nija_trade_audit.log

# TradingView Webhook
TRADINGVIEW_WEBHOOK_SECRET=your-secret-here

# Coinbase API
COINBASE_API_BASE=https://api.coinbase.com
```

## Modes

### SANDBOX Mode
- Simulates orders without touching the Coinbase API
- Useful for testing strategy logic
- No live trading

### DRY_RUN Mode (Default)
- Default mode if MODE is not set
- Simulates orders without executing them
- Good for testing before going live

### LIVE Mode
- **WARNING**: Places real orders with real money
- Requires `COINBASE_ACCOUNT_ID` to be set
- Requires `CONFIRM_LIVE=true` to be set
- API key must NOT have withdraw permission

## Safety Controls

### 1. Mode Validation
Before placing any orders, the system validates:
- MODE is one of: SANDBOX, DRY_RUN, LIVE
- If MODE=LIVE, COINBASE_ACCOUNT_ID must be set
- If MODE=LIVE, CONFIRM_LIVE must be true

### 2. API Key Permission Check
On initialization, the system attempts to verify that the API key does NOT have withdraw permission. If withdraw permission is detected, the system refuses to start.

### 3. Order Validation
Every order is validated against:
- Maximum order size (MAX_ORDER_USD)
- Rate limit (MAX_ORDERS_PER_MINUTE)
- Manual approval requirement (if MANUAL_APPROVAL_COUNT > 0)

### 4. Audit Logging
Every order request and response is logged to LOG_PATH with:
- Timestamp
- Order details (symbol, side, size)
- Order status
- Metadata (source, strategy, etc.)

## Using the Safe Order Module

### Basic Usage

```python
from safe_order import safe_place_order
from nija_client import CoinbaseClient

# Initialize client
client = CoinbaseClient()

# Place an order through safe order module
result = safe_place_order(
    client=client,
    symbol="BTC-USD",
    side="buy",
    size_usd=50.0,
    metadata={
        "strategy": "my_strategy",
        "signal": "bullish"
    }
)

print(result)
```

### Response Format

```python
{
    "status": "dry_run_simulated" | "sandbox_simulated" | "live_order_placed" | "pending_approval" | "rejected",
    "order_id": "sim_1234567890",
    "symbol": "BTC-USD",
    "side": "buy",
    "size_usd": 50.0,
    "mode": "DRY_RUN",
    "timestamp": "2024-01-01T12:00:00Z"
}
```

## Manual Approval Workflow

When `MANUAL_APPROVAL_COUNT` is set to a value greater than 0, the first N orders will be marked as pending approval instead of being executed immediately.

### Viewing Pending Approvals

Pending approvals are stored in `pending_approvals.json` in the same directory as LOG_PATH.

```python
from safe_order import get_safe_order_manager

manager = get_safe_order_manager()
pending = manager.get_pending_approvals()

for order in pending:
    print(f"Order {order['order_id']}: {order['side']} {order['size_usd']} {order['symbol']}")
```

### Approving an Order

```python
from safe_order import get_safe_order_manager

manager = get_safe_order_manager()
result = manager.approve_pending_order("pending_1234567890")
print(result)
```

After approval, the next order submission will execute the approved order.

## TradingView Webhook Integration

The webhook endpoint accepts POST requests with HMAC SHA256 signature verification.

### Endpoint

```
POST /api/tradingview/webhook
```

### Headers

```
Content-Type: application/json
X-Tv-Signature: <hmac_sha256_signature>
```

### Request Body

```json
{
    "symbol": "BTC-USD",
    "side": "buy",
    "size_usd": 100.0,
    "strategy": "my_strategy",
    "alert_message": "Optional alert message"
}
```

### Generating HMAC Signature

```python
import hmac
import hashlib
import json

# Your webhook secret
secret = "your_webhook_secret_here"

# Request body
payload = {
    "symbol": "BTC-USD",
    "side": "buy",
    "size_usd": 100.0
}

# Convert to JSON string
payload_json = json.dumps(payload)

# Generate HMAC signature
signature = hmac.new(
    secret.encode('utf-8'),
    payload_json.encode('utf-8'),
    hashlib.sha256
).hexdigest()

print(f"X-Tv-Signature: {signature}")
```

### TradingView Alert Setup

1. Create a webhook URL: `https://your-domain.com/api/tradingview/webhook`
2. Set the webhook secret in your environment: `TRADINGVIEW_WEBHOOK_SECRET=your-secret-here`
3. Configure TradingView alert to send JSON payload with required fields
4. Include the HMAC signature in the `X-Tv-Signature` header

## Security Best Practices

1. **Never commit secrets**: Use environment variables for all sensitive data
2. **Rotate secrets regularly**: Change TRADINGVIEW_WEBHOOK_SECRET periodically
3. **Start with DRY_RUN**: Test thoroughly before enabling LIVE mode
4. **Monitor logs**: Regularly review audit logs for unexpected activity
5. **Use manual approval**: Enable MANUAL_APPROVAL_COUNT for first few live orders
6. **Check API permissions**: Ensure API key does NOT have withdraw permission
7. **Set conservative limits**: Start with low MAX_ORDER_USD and MAX_ORDERS_PER_MINUTE

## Monitoring and Debugging

### Check Current Mode

```python
from config import MODE
print(f"Current MODE: {MODE}")
```

### View Audit Log

```bash
tail -f /tmp/nija_trade_audit.log
```

### Test Webhook Locally

```bash
# Generate signature
python3 -c "
import hmac
import hashlib
import json

secret = 'your_webhook_secret_here'
payload = {'symbol': 'BTC-USD', 'side': 'buy', 'size_usd': 10.0}
payload_json = json.dumps(payload)
sig = hmac.new(secret.encode(), payload_json.encode(), hashlib.sha256).hexdigest()
print(f'Signature: {sig}')
print(f'Payload: {payload_json}')
"

# Send test request
curl -X POST http://localhost:5000/api/tradingview/webhook \
  -H "Content-Type: application/json" \
  -H "X-Tv-Signature: <signature_from_above>" \
  -d '{"symbol": "BTC-USD", "side": "buy", "size_usd": 10.0}'
```

## Troubleshooting

### "LIVE mode requires COINBASE_ACCOUNT_ID"
Set the environment variable: `export COINBASE_ACCOUNT_ID=your-account-id`

### "LIVE mode requires CONFIRM_LIVE=true"
Set the environment variable: `export CONFIRM_LIVE=true`

### "API key has withdraw permission"
Remove withdraw permission from your Coinbase API key in the Coinbase dashboard.

### "Invalid signature"
Ensure the HMAC signature is correctly generated using the exact request body and the correct secret.

### "Rate limit exceeded"
Wait for the rate limit window to pass or increase MAX_ORDERS_PER_MINUTE.

### "Order size exceeds MAX_ORDER_USD"
Reduce the order size or increase MAX_ORDER_USD (carefully!).

## Testing

Run the comprehensive test suite:

```bash
python3 tests/test_safe_trading_stack.py
```

All tests should pass before deploying to production.

## Migration Guide

### From Direct CoinbaseClient Usage

**Before:**
```python
from nija_client import CoinbaseClient

client = CoinbaseClient()
result = client.place_order("BTC-USD", "buy", 50.0)
```

**After:**
```python
from safe_order import safe_place_order
from nija_client import CoinbaseClient

client = CoinbaseClient()
result = safe_place_order(client, "BTC-USD", "buy", 50.0)
```

### From LIVE_TRADING Flag

**Before:**
```python
LIVE_TRADING = True
```

**After:**
```bash
export MODE=LIVE
export COINBASE_ACCOUNT_ID=your-account-id
export CONFIRM_LIVE=true
```

## Support

For issues or questions, please:
1. Check the audit log at LOG_PATH
2. Review environment variables
3. Run the test suite
4. Check the GitHub issues

## License

This implementation is part of the Nija trading bot project.
