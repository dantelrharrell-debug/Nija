# Safe Trading Stack - Usage Guide

This guide explains how to use the new safe trading features in Nija.

## Overview

The safe trading stack includes:
- **MODE-based trading** (SANDBOX/DRY_RUN/LIVE)
- **Safety checks** for live trading
- **Rate limiting** and order size limits
- **Manual approval** for first N trades
- **Audit logging** of all orders
- **TradingView webhook** integration with HMAC authentication

## Environment Variables

### Trading Mode Configuration

```bash
# MODE can be: SANDBOX, DRY_RUN, or LIVE (default: DRY_RUN)
MODE=DRY_RUN

# For LIVE mode, these are REQUIRED:
COINBASE_ACCOUNT_ID=your-account-id-here
CONFIRM_LIVE=true
```

### Safety Limits

```bash
# Maximum order size in USD
MAX_ORDER_USD=100.0

# Maximum orders per minute (rate limiting)
MAX_ORDERS_PER_MINUTE=5

# First N orders require manual approval (0 = disabled)
MANUAL_APPROVAL_COUNT=0
```

### Audit Logging

```bash
# Path to audit log file
LOG_PATH=trade_audit.log
```

### TradingView Webhook

```bash
# Secret for webhook signature verification
TRADINGVIEW_WEBHOOK_SECRET=your_secret_key_here
```

## Using Safe Order Submission

### Basic Usage

```python
from nija_client import CoinbaseClient
from safe_order import submit_order

# Initialize client (safety checks run automatically)
client = CoinbaseClient()

# Submit an order through the safe wrapper
response = submit_order(
    client,
    symbol='BTC-USD',
    side='buy',
    size_usd=50.0
)

print(response)
```

### DRY_RUN Mode (Default)

In DRY_RUN mode, orders are logged but not executed:

```bash
MODE=DRY_RUN
```

Output:
```
INFO:SafeOrder:DRY_RUN: BUY $50.00 BTC-USD
```

### LIVE Mode

For LIVE trading, you MUST set both COINBASE_ACCOUNT_ID and CONFIRM_LIVE:

```bash
MODE=LIVE
COINBASE_ACCOUNT_ID=your-funded-account-id
CONFIRM_LIVE=true
```

If these are not set, the client will refuse to start:
```
RuntimeError: LIVE mode requires COINBASE_ACCOUNT_ID to be set
RuntimeError: LIVE mode requires CONFIRM_LIVE=true to be explicitly set
```

## Safety Features

### 1. Order Size Limit

Orders exceeding MAX_ORDER_USD are rejected:

```python
# This will raise RuntimeError if size_usd > MAX_ORDER_USD
response = submit_order(client, 'BTC-USD', 'buy', size_usd=200.0)
```

### 2. Rate Limiting

The system enforces MAX_ORDERS_PER_MINUTE:

```python
# 6th order within 1 minute will fail if MAX_ORDERS_PER_MINUTE=5
for i in range(6):
    submit_order(client, 'BTC-USD', 'buy', size_usd=10.0)
# RuntimeError: Rate limit exceeded
```

### 3. Manual Approval

First N trades can require manual approval:

```bash
MANUAL_APPROVAL_COUNT=3
```

```python
from safe_order import submit_order, get_pending_orders, approve_pending_order

# First 3 orders will be pending
response = submit_order(client, 'BTC-USD', 'buy', size_usd=10.0)
# response['status'] == 'pending_approval'

# View pending orders
pending = get_pending_orders()
print(pending)

# Approve an order
approve_pending_order(pending[0]['order_id'])
```

Pending orders are stored in `pending_approvals.json` (same directory as LOG_PATH).

### 4. Audit Logging

All order requests and responses are logged to LOG_PATH:

```bash
LOG_PATH=trade_audit.log
```

Log format (JSON lines):
```json
{"timestamp": "2025-11-21T20:50:00.000000", "message": "ORDER_REQUEST", "data": {...}}
{"timestamp": "2025-11-21T20:50:01.000000", "message": "ORDER_DRY_RUN", "data": {...}}
```

## TradingView Webhook Integration

### Setup

1. Set your webhook secret:
```bash
TRADINGVIEW_WEBHOOK_SECRET=my_super_secret_key_12345
```

2. The webhook endpoint is automatically registered at `/webhook`

3. Start your Flask app:
```bash
python main.py
```

### TradingView Configuration

In TradingView, configure your alert webhook:

**Webhook URL:**
```
https://your-domain.com/webhook
```

**Payload:**
```json
{
  "signal": "{{strategy.order.action}}",
  "symbol": "{{ticker}}",
  "price": {{close}}
}
```

### Signature Verification

The webhook requires HMAC SHA256 signature in the `X-Tv-Signature` header.

**Generating the signature (example in Python):**
```python
import hmac
import hashlib
import json

payload = {"signal": "buy", "symbol": "BTC-USD"}
payload_bytes = json.dumps(payload).encode('utf-8')
secret = 'my_super_secret_key_12345'

signature = hmac.new(
    secret.encode('utf-8'),
    payload_bytes,
    hashlib.sha256
).hexdigest()

# Send signature in X-Tv-Signature header
```

### Testing the Webhook

```bash
curl -X POST http://localhost:5000/webhook \
  -H "Content-Type: application/json" \
  -H "X-Tv-Signature: <signature>" \
  -d '{"signal": "buy", "symbol": "BTC-USD"}'
```

## API Key Safety

The client checks for withdraw permissions and warns if it cannot verify:

```
WARNING:NijaCoinbaseClient:API key permission check: Coinbase API does not expose key permissions via API. 
Please manually verify that your API key does NOT have withdraw permissions.
Only 'view' and 'trade' permissions should be enabled for safety.
```

**Important:** Manually verify your Coinbase API key has ONLY these permissions:
- ✅ View
- ✅ Trade
- ❌ Withdraw (NEVER enable this)

## Example .env File

```bash
# Trading Mode
MODE=DRY_RUN

# Live Trading Requirements (only needed if MODE=LIVE)
# COINBASE_ACCOUNT_ID=your-account-id
# CONFIRM_LIVE=true

# Safety Limits
MAX_ORDER_USD=100.0
MAX_ORDERS_PER_MINUTE=5
MANUAL_APPROVAL_COUNT=0

# Logging
LOG_PATH=trade_audit.log
LOG_LEVEL=INFO

# TradingView Webhook
TRADINGVIEW_WEBHOOK_SECRET=change_me_to_secure_random_string

# Coinbase API
COINBASE_API_BASE=https://api.coinbase.com

# Trade Sizing
MIN_TRADE_PERCENT=2.0
MAX_TRADE_PERCENT=10.0
```

## Testing

Run the test suite:

```bash
# Run all tests
python -m unittest discover tests/

# Run specific test files
python -m unittest tests.test_safe_order
python -m unittest tests.test_tradingview_webhook
python -m unittest tests.test_nija_client_safety
```

## Security Best Practices

1. **Never commit secrets** - Use `.env` file (already in `.gitignore`)
2. **Start in DRY_RUN mode** - Test thoroughly before going live
3. **Use MANUAL_APPROVAL_COUNT** - Approve first few trades manually
4. **Set conservative limits** - Start with low MAX_ORDER_USD
5. **Monitor audit logs** - Review `trade_audit.log` regularly
6. **API key permissions** - Only enable View and Trade (never Withdraw)
7. **Webhook secret** - Use a strong random string for TRADINGVIEW_WEBHOOK_SECRET

## Troubleshooting

### "LIVE mode requires COINBASE_ACCOUNT_ID to be set"
Set the environment variable:
```bash
export COINBASE_ACCOUNT_ID=your-account-id
```

### "Rate limit exceeded"
Wait 1 minute or increase MAX_ORDERS_PER_MINUTE

### "Order size exceeds MAX_ORDER_USD limit"
Reduce order size or increase MAX_ORDER_USD

### "Invalid signature" on webhook
Verify the HMAC SHA256 signature is correctly generated and matches TRADINGVIEW_WEBHOOK_SECRET
