# Safe Trading Stack - Documentation

This document describes the safe trading stack features added to the Nija trading bot.

## Overview

The safe trading stack provides multiple layers of protection to prevent accidental trading with funded accounts. It includes:

1. **MODE-based execution** (SANDBOX, DRY_RUN, LIVE)
2. **Live trading safeguards** (required account ID and confirmation)
3. **API key safety checks** (prevents use of keys with withdraw permissions)
4. **Rate limiting** (prevents excessive order submission)
5. **Order size limits** (prevents oversized orders)
6. **Manual approval system** (requires approval for first N trades)
7. **Comprehensive audit logging** (all orders logged with timestamps)
8. **TradingView webhook integration** (secure HMAC-signed webhook endpoint)

## Environment Variables

### Core Settings

- `MODE` - Trading mode: `SANDBOX`, `DRY_RUN`, or `LIVE` (default: `DRY_RUN`)
- `COINBASE_ACCOUNT_ID` - Account ID for trading (required when `MODE=LIVE`)
- `CONFIRM_LIVE` - Must be set to `true` to enable live trading (required when `MODE=LIVE`)

### Safety Limits

- `MAX_ORDER_USD` - Maximum order size in USD (default: `100.0`)
- `MAX_ORDERS_PER_MINUTE` - Maximum orders per minute (default: `5`)
- `MANUAL_APPROVAL_COUNT` - Number of orders requiring manual approval (default: `0`)

### Logging

- `LOG_PATH` - Path to audit log file (default: `/tmp/nija_orders.log`)
- `LOG_LEVEL` - Logging level (default: `INFO`)

### TradingView Webhook

- `TRADINGVIEW_WEBHOOK_SECRET` - Secret key for HMAC signature verification

## Usage

### DRY_RUN Mode (Default)

Safe for testing - no real orders are placed:

```bash
# No special env vars needed - DRY_RUN is the default
python main.py
```

### SANDBOX Mode

Uses test environment (if supported by exchange):

```bash
MODE=SANDBOX python main.py
```

### LIVE Mode

**⚠️ WARNING: This mode uses real money!**

To enable live trading, you must:

1. Set `MODE=LIVE`
2. Set `COINBASE_ACCOUNT_ID` to your trading account ID
3. Set `CONFIRM_LIVE=true` to confirm you understand this is live trading

```bash
MODE=LIVE \
COINBASE_ACCOUNT_ID=your-account-id-here \
CONFIRM_LIVE=true \
MAX_ORDER_USD=50 \
python main.py
```

## Safe Order Submission

All order submissions should go through the `safe_order` module:

```python
from safe_order import submit_safe_order

result = submit_safe_order(
    symbol="BTC-USD",
    side="buy",
    size_usd=50.0,
    client_order_id="optional-id"
)

if result["status"] == "dry_run":
    print(f"DRY_RUN: {result['message']}")
elif result["status"] == "rejected":
    print(f"Rejected: {result['error']}")
elif result["status"] == "rate_limited":
    print(f"Rate limited: {result['error']}")
elif result["status"] == "pending_approval":
    print(f"Needs approval: {result['message']}")
```

## Manual Approval System

When `MANUAL_APPROVAL_COUNT` is set to a value greater than 0, the first N orders will require manual approval:

1. Set `MANUAL_APPROVAL_COUNT=3` to require approval for first 3 orders
2. When an order needs approval, it's added to `pending_approvals.json`
3. To approve, edit the file and move the order ID from `pending` to `approved` list:

```json
{
  "pending": ["order_123"],
  "approved": ["order_456", "order_789"]
}
```

4. Resubmit the order - it will now be processed

## TradingView Webhook

### Endpoint

`POST /tradingview/webhook`

### Required Headers

- `Content-Type: application/json`
- `X-Tv-Signature: <HMAC-SHA256-signature>`

### Payload Format

```json
{
  "symbol": "BTC-USD",
  "side": "buy",
  "size_usd": 50.0,
  "client_order_id": "optional-id"
}
```

### Signature Generation

The signature is an HMAC-SHA256 hash of the request body using `TRADINGVIEW_WEBHOOK_SECRET`:

```python
import hmac
import hashlib
import json

payload = {"symbol": "BTC-USD", "side": "buy", "size_usd": 50.0}
payload_json = json.dumps(payload, separators=(',', ':'))
signature = hmac.new(
    TRADINGVIEW_WEBHOOK_SECRET.encode('utf-8'),
    payload_json.encode('utf-8'),
    hashlib.sha256
).hexdigest()
```

### Testing the Webhook

```bash
# Generate test signature
python tradingview_webhook.py

# Use the output curl command to test
curl -X POST http://localhost:5000/tradingview/webhook \
  -H "Content-Type: application/json" \
  -H "X-Tv-Signature: <signature-from-above>" \
  -d '{"symbol": "BTC-USD", "side": "buy", "size_usd": 50.0}'
```

## Audit Logging

All order requests and responses are logged to the file specified by `LOG_PATH`. Each log entry is a JSON object with:

- `timestamp` - ISO 8601 timestamp
- `mode` - Trading mode (SANDBOX, DRY_RUN, or LIVE)
- `status` - Order status (dry_run, rejected, rate_limited, pending_approval, etc.)
- `order_request` - Full order request details
- `response` - Response from order submission

Example log entry:

```json
{
  "timestamp": "2025-11-21T21:00:00.000000+00:00",
  "mode": "DRY_RUN",
  "status": "dry_run",
  "order_request": {
    "client_order_id": "order_123",
    "symbol": "BTC-USD",
    "side": "buy",
    "size_usd": 50.0
  },
  "response": {
    "status": "dry_run",
    "message": "DRY_RUN: BUY $50.0 BTC-USD"
  }
}
```

## Testing

Run the test suite:

```bash
# Integration tests
python tests/test_integration.py

# Safe order tests
python -c "import sys; sys.path.insert(0, '.'); exec(open('tests/test_safe_order.py').read())"

# Webhook tests
python -c "import sys; sys.path.insert(0, '.'); exec(open('tests/test_tradingview_webhook.py').read())"
```

## Safety Features Summary

1. **Default DRY_RUN**: System starts in safe mode by default
2. **Double confirmation for LIVE**: Requires both account ID and explicit confirmation
3. **API key checks**: Warns/errors if withdraw permissions detected
4. **Rate limiting**: Prevents runaway order submission
5. **Size limits**: Prevents oversized orders
6. **Manual approval**: Allows review of first N trades
7. **Comprehensive logging**: Full audit trail of all orders
8. **Webhook security**: HMAC signature verification prevents unauthorized orders

## Troubleshooting

### "MODE=LIVE requires COINBASE_ACCOUNT_ID"

Set the `COINBASE_ACCOUNT_ID` environment variable to your trading account ID.

### "MODE=LIVE requires CONFIRM_LIVE=true"

Set `CONFIRM_LIVE=true` to explicitly confirm you want to trade live.

### "Rate limit exceeded"

Wait for the time specified in the error message, or increase `MAX_ORDERS_PER_MINUTE`.

### "Order size exceeds MAX_ORDER_USD"

Reduce the order size or increase the `MAX_ORDER_USD` limit.

### "Invalid signature" (webhook)

Ensure the `X-Tv-Signature` header matches the HMAC-SHA256 hash of the request body using your `TRADINGVIEW_WEBHOOK_SECRET`.
