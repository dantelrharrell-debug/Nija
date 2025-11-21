# Safe Trading Stack - Usage Guide

This implementation adds a safe trading stack to prevent accidental live trading and provide comprehensive audit logging.

## Features

### 1. Trading Modes

The system supports three trading modes controlled by the `MODE` environment variable:

- **SANDBOX**: For testing in a sandbox environment (simulated orders)
- **DRY_RUN**: Default mode - simulates orders without actually submitting them
- **LIVE**: Real trading mode with additional safety checks

```bash
# Set the trading mode
export MODE=DRY_RUN  # or SANDBOX or LIVE
```

### 2. LIVE Mode Safety Checks

When `MODE=LIVE`, the following requirements must be met:

1. **COINBASE_ACCOUNT_ID** must be set
2. **CONFIRM_LIVE** must be explicitly set to `true`
3. API key must NOT have withdraw permissions

```bash
# Required for LIVE mode
export MODE=LIVE
export COINBASE_ACCOUNT_ID=your-account-id
export CONFIRM_LIVE=true
```

If any of these requirements are not met, the system will refuse to start with a clear error message.

### 3. Order Limits and Safety

The safe order module enforces the following limits:

```bash
# Maximum order size in USD (default: 100.0)
export MAX_ORDER_USD=100.0

# Maximum orders per minute (default: 5)
export MAX_ORDERS_PER_MINUTE=5

# Number of orders requiring manual approval (default: 0)
export MANUAL_APPROVAL_COUNT=2
```

### 4. Manual Approval Workflow

When `MANUAL_APPROVAL_COUNT > 0`, the first N orders will be marked as "pending approval" and saved to a file.

```bash
# Enable manual approval for first 3 orders
export MANUAL_APPROVAL_COUNT=3
```

Orders requiring approval are saved to `pending_approvals.json` (in the same directory as LOG_PATH).

To approve an order:
1. Review the pending orders in `pending_approvals.json`
2. Manually increment the `approved_count` field
3. The next order submission will check this count

### 5. Audit Logging

All order requests and responses are logged to a persistent file:

```bash
# Set the audit log path (default: /tmp/nija_orders.log)
export LOG_PATH=/var/log/nija/orders.log
```

Each log entry is a JSON object with:
- `timestamp`: ISO 8601 timestamp
- `event_type`: Type of event (order_request, order_submitted, order_rejected, etc.)
- `data`: Event-specific data

### 6. TradingView Webhook

The system includes a secure TradingView webhook endpoint at `/webhook/tradingview`.

```bash
# Set the webhook secret for HMAC SHA256 signature validation
export TRADINGVIEW_WEBHOOK_SECRET=your-secret-here
```

**Important**: In LIVE mode, `TRADINGVIEW_WEBHOOK_SECRET` must be configured.

#### Webhook Request Format

```json
{
  "symbol": "BTC-USD",
  "side": "buy",
  "size_usd": 50.0
}
```

#### Signature Calculation

The webhook request must include an `X-Tv-Signature` header containing the HMAC SHA256 signature:

```python
import hmac
import hashlib

payload = '{"symbol": "BTC-USD", "side": "buy", "size_usd": 50.0}'
signature = hmac.new(
    TRADINGVIEW_WEBHOOK_SECRET.encode('utf-8'),
    payload.encode('utf-8'),
    hashlib.sha256
).hexdigest()

# Include in request header: X-Tv-Signature: <signature>
```

#### Testing the Webhook

```bash
# Test endpoint (no signature required)
curl http://localhost:5000/webhook/tradingview/test
```

## Configuration Summary

All environment variables with their defaults:

```bash
# Trading Mode
MODE=DRY_RUN                          # SANDBOX, DRY_RUN, or LIVE

# LIVE Mode Requirements
COINBASE_ACCOUNT_ID=                  # Required for LIVE mode
CONFIRM_LIVE=false                    # Must be 'true' for LIVE mode

# Order Limits
MAX_ORDER_USD=100.0                   # Maximum order size in USD
MAX_ORDERS_PER_MINUTE=5               # Rate limit
MANUAL_APPROVAL_COUNT=0               # Number of orders requiring manual approval

# Logging
LOG_PATH=/tmp/nija_orders.log         # Audit log path

# Webhook
TRADINGVIEW_WEBHOOK_SECRET=your_webhook_secret_here  # Required for LIVE mode
```

## Example Workflows

### Development/Testing (DRY_RUN)

```bash
export MODE=DRY_RUN
export MAX_ORDER_USD=50.0
export LOG_PATH=/tmp/dev_orders.log

# Start the application
python main.py
```

### Staged Testing with Manual Approval

```bash
export MODE=DRY_RUN
export MANUAL_APPROVAL_COUNT=5        # First 5 orders need approval
export LOG_PATH=/var/log/nija/staging_orders.log

# Start the application
python main.py

# Review pending approvals
cat /var/log/nija/pending_approvals.json

# After review, manually increment approved_count in the file
```

### Production (LIVE)

```bash
export MODE=LIVE
export COINBASE_ACCOUNT_ID=your-real-account-id
export CONFIRM_LIVE=true
export MAX_ORDER_USD=100.0
export MAX_ORDERS_PER_MINUTE=3
export LOG_PATH=/var/log/nija/live_orders.log
export TRADINGVIEW_WEBHOOK_SECRET=your-production-secret

# Start the application
python main.py
```

## Safety Checklist

Before running in LIVE mode:

- [ ] Verify `COINBASE_ACCOUNT_ID` is correct
- [ ] Set `CONFIRM_LIVE=true`
- [ ] Ensure API key does NOT have withdraw permission
- [ ] Configure `MAX_ORDER_USD` to a safe limit
- [ ] Set `MAX_ORDERS_PER_MINUTE` to prevent runaway trading
- [ ] Configure `TRADINGVIEW_WEBHOOK_SECRET` if using webhooks
- [ ] Set `LOG_PATH` to a persistent location (not /tmp)
- [ ] Consider using `MANUAL_APPROVAL_COUNT` for first few orders
- [ ] Test in DRY_RUN mode first
- [ ] Monitor audit logs regularly

## Monitoring

### Check Order Statistics

```python
from safe_order import get_order_stats

stats = get_order_stats()
print(stats)
```

### Review Audit Logs

```bash
# View recent order events
tail -f /var/log/nija/live_orders.log | jq .

# Count orders by event type
cat /var/log/nija/live_orders.log | jq -r .event_type | sort | uniq -c

# Find all rejected orders
cat /var/log/nija/live_orders.log | jq 'select(.event_type == "order_rejected")'
```

## Troubleshooting

### "LIVE mode requires COINBASE_ACCOUNT_ID to be set"

Set the `COINBASE_ACCOUNT_ID` environment variable to your Coinbase account ID.

### "LIVE mode requires CONFIRM_LIVE=true to be set"

This is a safety measure. Set `CONFIRM_LIVE=true` to confirm you want to enable live trading.

### "API key has 'withdraw' permission"

For safety, create a new API key without withdraw permission. Trading API keys should only have 'trade' and 'view' permissions.

### "Rate limit exceeded"

You've submitted too many orders in the last minute. Wait or increase `MAX_ORDERS_PER_MINUTE`.

### "Order size exceeds MAX_ORDER_USD limit"

The order size exceeds your configured limit. Either increase `MAX_ORDER_USD` or reduce the order size.

### "Invalid signature" on webhook

Check that:
1. `TRADINGVIEW_WEBHOOK_SECRET` matches between server and client
2. Signature is computed correctly using HMAC SHA256
3. Signature is sent in `X-Tv-Signature` header
