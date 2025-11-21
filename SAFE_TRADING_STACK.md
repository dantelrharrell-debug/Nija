# Safe Trading Stack

This document describes the safe trading stack implementation that protects against accidental trading from a funded account.

## Overview

The safe trading stack provides multiple layers of protection:

1. **Mode-based operation** (SANDBOX, DRY_RUN, LIVE)
2. **LIVE mode safety requirements**
3. **API key permission checks**
4. **Centralized order submission with safety controls**
5. **TradingView webhook integration with HMAC signature verification**
6. **Comprehensive audit logging**

## Environment Variables

### Trading Mode Configuration

- **`MODE`** (default: `DRY_RUN`)
  - `SANDBOX`: Use sandbox environment (no real orders)
  - `DRY_RUN`: Simulate orders without submitting them
  - `LIVE`: Submit real orders to Coinbase

- **`CONFIRM_LIVE`** (required for LIVE mode, default: `false`)
  - Must be set to `true` to enable LIVE trading
  - This is a safety mechanism to prevent accidental live trading

- **`COINBASE_ACCOUNT_ID`** (required for LIVE mode)
  - The Coinbase account ID to use for live trading
  - Must be set when `MODE=LIVE`

### Trading Safety Limits

- **`MAX_ORDER_USD`** (default: `100.0`)
  - Maximum order size in USD
  - Orders exceeding this limit will be rejected

- **`MAX_ORDERS_PER_MINUTE`** (default: `5`)
  - Maximum number of orders allowed per minute
  - Rate limiting to prevent runaway trading

- **`MANUAL_APPROVAL_COUNT`** (default: `0`)
  - Number of first orders that require manual approval
  - Set to `0` to disable manual approval
  - Orders requiring approval are written to a pending-approvals.json file

### Logging

- **`LOG_PATH`** (default: `/tmp/nija_trading.log`)
  - Path to audit log file
  - All order requests and responses are logged here

### TradingView Webhook

- **`TRADINGVIEW_WEBHOOK_SECRET`** (required for webhook security)
  - Secret key used to verify webhook signatures
  - Must match the secret configured in TradingView

- **`TV_WEBHOOK_PORT`** (default: `5000`)
  - Port for the webhook server

## Usage

### Basic Usage with Safe Order Module

```python
from nija_client import CoinbaseClient
import safe_order

# Initialize client (safety checks run automatically)
client = CoinbaseClient()

# Submit an order through the safe order module
result = safe_order.submit_order(
    client=client,
    symbol="BTC-USD",
    side="buy",
    size_usd=50.0
)
```

### Running in Different Modes

#### DRY_RUN Mode (Default)

```bash
# No configuration needed - this is the default
python demo_safe_trading.py
```

#### SANDBOX Mode

```bash
export MODE=SANDBOX
python demo_safe_trading.py
```

#### LIVE Mode

```bash
export MODE=LIVE
export COINBASE_ACCOUNT_ID=your-account-id
export CONFIRM_LIVE=true
python demo_safe_trading.py
```

### TradingView Webhook

The webhook endpoint is available at `/tradingview/webhook` and requires HMAC SHA256 signature verification.

#### Setting Up TradingView Webhook

1. Set the webhook secret:
```bash
export TRADINGVIEW_WEBHOOK_SECRET=your-secret-key
```

2. In TradingView alert settings:
   - Webhook URL: `https://your-server.com/tradingview/webhook`
   - Add custom header: `X-Tv-Signature: {{strategy.order.alert_message}}`
   - The signature should be computed as: `HMAC-SHA256(webhook_body, secret)`

3. Start the server:
```bash
python main.py
```

#### Testing the Webhook

```bash
# Health check
curl http://localhost:5000/tradingview/health

# Test webhook with signature
python -c "
import requests
import hmac
import hashlib
import json

payload = {'alert': 'BUY', 'symbol': 'BTC-USD'}
payload_str = json.dumps(payload)
secret = 'your-secret-key'

signature = hmac.new(
    secret.encode('utf-8'),
    payload_str.encode('utf-8'),
    hashlib.sha256
).hexdigest()

response = requests.post(
    'http://localhost:5000/tradingview/webhook',
    json=payload,
    headers={'X-Tv-Signature': signature}
)
print(response.json())
"
```

### Manual Order Approval

When `MANUAL_APPROVAL_COUNT > 0`, the first N orders require manual approval.

1. Orders are written to `pending-approvals.json` (located next to LOG_PATH)
2. Review pending orders:
```python
import safe_order
pending = safe_order.get_pending_approvals()
print(pending)
```

3. Approve an order:
```python
safe_order.approve_order(order_id)
```

## Safety Features

### 1. Mode-Based Protection

The system enforces different behaviors based on MODE:

- **SANDBOX**: Uses sandbox API endpoints (no real money)
- **DRY_RUN**: Simulates orders without submitting them
- **LIVE**: Requires explicit confirmation via `CONFIRM_LIVE=true` and `COINBASE_ACCOUNT_ID`

### 2. Rate Limiting

Orders are rate-limited to `MAX_ORDERS_PER_MINUTE` to prevent:
- Runaway trading loops
- API rate limit violations
- Accidental rapid-fire orders

### 3. Order Size Limits

All orders are checked against `MAX_ORDER_USD`:
- Prevents accidentally large orders
- Configurable per deployment

### 4. Manual Approval

The first N orders (configured by `MANUAL_APPROVAL_COUNT`) require manual approval:
- Useful for testing new strategies
- Provides a safety net for initial deployment
- Orders are logged and can be reviewed before execution

### 5. API Key Permission Check

The system checks that API keys do not have withdraw permissions:
- Prevents fund withdrawal via compromised keys
- Validates at client initialization

### 6. Audit Logging

Every order request and response is logged to `LOG_PATH`:
- Timestamped entries
- Includes mode, symbol, side, size
- JSON format for easy parsing
- Immutable audit trail

## Files

- **`config.py`**: Configuration and environment variable handling
- **`nija_client.py`**: Coinbase client with safety checks
- **`safe_order.py`**: Centralized order submission with all safety controls
- **`tv_webhook.py`**: TradingView webhook endpoint with signature verification
- **`main.py`**: Flask application with webhook blueprint registration

## Testing

Run the test suite:

```bash
# Unit and integration tests
python test_safe_trading_stack.py

# Webhook integration tests
python test_webhook_integration.py

# Demo
python demo_safe_trading.py
```

## Security Best Practices

1. **Never commit secrets** to version control
2. **Use environment variables** for all sensitive configuration
3. **Rotate webhook secrets** regularly
4. **Monitor audit logs** for suspicious activity
5. **Set conservative limits** for `MAX_ORDER_USD` and `MAX_ORDERS_PER_MINUTE`
6. **Test in DRY_RUN** before switching to LIVE mode
7. **Use MANUAL_APPROVAL_COUNT** for initial deployment
8. **Ensure API keys lack withdraw permissions**

## Troubleshooting

### "LIVE mode requires COINBASE_ACCOUNT_ID"

Set the environment variable:
```bash
export COINBASE_ACCOUNT_ID=your-account-id
```

### "LIVE mode requires CONFIRM_LIVE=true"

Set the confirmation flag:
```bash
export CONFIRM_LIVE=true
```

### "Rate limit exceeded"

Wait 60 seconds or increase `MAX_ORDERS_PER_MINUTE`

### "Order size exceeds maximum"

Reduce order size or increase `MAX_ORDER_USD`

### "Webhook signature verification failed"

Ensure the secret matches between TradingView and your server:
```bash
export TRADINGVIEW_WEBHOOK_SECRET=same-secret-as-tradingview
```
