# Safe Trading Stack Documentation

This document describes the safe trading stack implementation for the Nija trading bot, including MODE-based trading, safety checks, rate limiting, manual approval, and TradingView webhook integration.

## Overview

The safe trading stack provides multiple layers of protection to prevent accidental trading with real funds:

1. **MODE-based trading**: SANDBOX, DRY_RUN, or LIVE modes
2. **LIVE mode safety checks**: Requires explicit account ID and confirmation
3. **API key permission checks**: Refuses to run if withdraw permission is detected
4. **Rate limiting**: Prevents too many orders in a short time
5. **Order size limits**: Enforces maximum order size in USD
6. **Manual approval**: First N trades require manual approval
7. **Audit logging**: All orders logged to persistent file
8. **Webhook security**: HMAC SHA256 signature verification

## Environment Variables

### Trading Mode Configuration

- **`MODE`**: Trading mode (default: `DRY_RUN`)
  - `SANDBOX`: Use test environment
  - `DRY_RUN`: Simulate orders without executing them
  - `LIVE`: Execute real orders (requires additional safety settings)

### LIVE Mode Safety Requirements

- **`COINBASE_ACCOUNT_ID`**: Account ID for live trading (required for LIVE mode)
- **`CONFIRM_LIVE`**: Must be set to `true` to enable live trading

### Trading Limits

- **`MAX_ORDER_USD`**: Maximum order size in USD (default: `100`)
- **`MAX_ORDERS_PER_MINUTE`**: Maximum orders per minute (default: `5`)
- **`MANUAL_APPROVAL_COUNT`**: Number of first orders requiring manual approval (default: `0`)

### Logging

- **`LOG_PATH`**: Path to audit log file (default: `orders.log`)

### TradingView Webhook

- **`TRADINGVIEW_WEBHOOK_SECRET`**: Secret for HMAC signature verification
- **`TV_WEBHOOK_PORT`**: Port for webhook server (default: `5000`)

## Usage

### Basic Setup

```bash
# Set trading mode (DRY_RUN is default)
export MODE=DRY_RUN

# Set order limits
export MAX_ORDER_USD=100
export MAX_ORDERS_PER_MINUTE=5

# Enable manual approval for first 3 orders
export MANUAL_APPROVAL_COUNT=3

# Set log path
export LOG_PATH=./logs/orders.log
```

### Enabling LIVE Trading

**⚠️ WARNING: Only enable LIVE mode when you're ready to trade with real money!**

```bash
# 1. Set MODE to LIVE
export MODE=LIVE

# 2. Set your Coinbase account ID
export COINBASE_ACCOUNT_ID=your-account-id-here

# 3. Explicitly confirm live trading
export CONFIRM_LIVE=true
```

### Using Safe Order Submission

```python
from safe_order import submit_order
from nija_client import CoinbaseClient

# Initialize client (will perform safety checks)
client = CoinbaseClient()

# Submit order through safe wrapper
result = submit_order(
    client=client,
    symbol='BTC-USD',
    side='buy',
    size_usd=50.0,
    metadata={'source': 'manual', 'strategy': 'TestStrategy'}
)

print(f"Order result: {result}")
```

### TradingView Webhook Integration

The webhook endpoint is available at `/tradingview/webhook` and requires HMAC SHA256 signature verification.

#### Setting Up TradingView Webhook

1. Set the webhook secret:
```bash
export TRADINGVIEW_WEBHOOK_SECRET=your-secret-here
```

2. In TradingView, configure the webhook URL:
```
https://your-domain.com/tradingview/webhook
```

3. Generate the HMAC signature in your TradingView alert:
```javascript
// In TradingView Pine Script
signature = str.hmac_sha256("your-secret-here", message)
```

4. Include the signature in the `X-Tv-Signature` header.

#### Webhook Payload Format

```json
{
  "symbol": "BTC-USD",
  "action": "buy",
  "size_usd": 50.0,
  "strategy": "MyStrategy",
  "timestamp": "2025-01-01T00:00:00Z"
}
```

### Manual Approval Workflow

When `MANUAL_APPROVAL_COUNT` is set to a value greater than 0, the first N orders will be marked as pending and won't execute until approved.

```python
from safe_order import approve_pending_orders, get_pending_orders

# Check pending orders
pending = get_pending_orders()
print(f"Pending orders: {len(pending)}")

# Approve orders (e.g., approve 3 orders)
approve_pending_orders(count=3)
```

The pending approvals are stored in a JSON file alongside the log path (default: `pending-approvals.json`).

## Safety Mechanisms

### 1. MODE Validation

The system validates the MODE setting and enforces different behaviors:

- **DRY_RUN**: Orders are logged but not executed
- **SANDBOX**: Orders are executed in test environment
- **LIVE**: Orders are executed with real money (requires safety checks)

### 2. LIVE Mode Safety Checks

Before allowing LIVE trading, the system checks:

1. `COINBASE_ACCOUNT_ID` is set
2. `CONFIRM_LIVE=true` is set
3. User is warned about real money trading

### 3. API Key Permission Check

The system attempts to verify that the API key doesn't have withdraw permission. This prevents unauthorized withdrawals from your account.

### 4. Rate Limiting

Orders are tracked over time, and the system prevents exceeding `MAX_ORDERS_PER_MINUTE` to avoid:

- Accidental rapid-fire orders
- API rate limit violations
- Unintended high-frequency trading

### 5. Order Size Limits

Each order is validated against `MAX_ORDER_USD` to prevent accidentally placing orders that are too large.

### 6. Audit Logging

Every order request and response is logged to the audit log file with:

- Timestamp (UTC)
- Event type (order_placed_live, order_dry_run, order_failed, etc.)
- MODE
- Complete order data
- Coinbase response (if applicable)

### 7. Webhook Signature Verification

All webhook requests must include a valid HMAC SHA256 signature in the `X-Tv-Signature` header. This prevents unauthorized webhook requests.

## Testing

Run the test suite to verify all safety mechanisms:

```bash
# Run all tests
python -m unittest tests.test_safe_trading tests.test_integration -v

# Run specific test class
python -m unittest tests.test_safe_trading.TestSafetyChecks -v

# Run specific test
python -m unittest tests.test_safe_trading.TestSafeOrder.test_rate_limiting -v
```

## Architecture

### Modules

- **`config.py`**: Configuration management with environment variable parsing
- **`nija_client.py`**: Coinbase client with safety checks
- **`safe_order.py`**: Centralized order submission wrapper
- **`tradingview_webhook.py`**: Flask blueprint for webhook endpoint
- **`main.py`**: Flask application with webhook registration

### Flow Diagram

```
TradingView Alert
    ↓
Webhook Endpoint (HMAC verification)
    ↓
safe_order.submit_order()
    ↓
Safety Checks:
  - MODE validation
  - Rate limiting
  - Order size validation
  - Manual approval check
    ↓
Order Execution (based on MODE)
    ↓
Audit Logging
```

## Troubleshooting

### Error: "LIVE mode requires COINBASE_ACCOUNT_ID"

Set the `COINBASE_ACCOUNT_ID` environment variable:
```bash
export COINBASE_ACCOUNT_ID=your-account-id
```

### Error: "LIVE mode requires CONFIRM_LIVE=true"

You must explicitly confirm live trading:
```bash
export CONFIRM_LIVE=true
```

### Error: "Rate limit exceeded"

You've exceeded the maximum orders per minute. Wait a minute or increase `MAX_ORDERS_PER_MINUTE`:
```bash
export MAX_ORDERS_PER_MINUTE=10
```

### Error: "Order size exceeds maximum"

The order size is too large. Either reduce the order size or increase `MAX_ORDER_USD`:
```bash
export MAX_ORDER_USD=200
```

### Webhook Error: "Invalid signature"

The HMAC signature doesn't match. Ensure:
1. `TRADINGVIEW_WEBHOOK_SECRET` matches the secret used to generate the signature
2. The signature is computed correctly: `HMAC-SHA256(secret, payload)`
3. The signature is included in the `X-Tv-Signature` header

## Best Practices

1. **Start with DRY_RUN**: Always test with `MODE=DRY_RUN` first
2. **Use SANDBOX for testing**: Test with `MODE=SANDBOX` before going live
3. **Enable manual approval**: Set `MANUAL_APPROVAL_COUNT=3` or higher when first starting
4. **Monitor audit logs**: Regularly review the audit log file
5. **Set conservative limits**: Start with low `MAX_ORDER_USD` and `MAX_ORDERS_PER_MINUTE`
6. **Secure webhook secret**: Use a strong, random secret for `TRADINGVIEW_WEBHOOK_SECRET`
7. **Rotate API keys**: Regularly rotate your Coinbase API keys
8. **Never share credentials**: Keep API keys and webhook secrets private

## Security Considerations

- API keys should never have withdraw permission enabled
- Webhook secret should be strong and unique
- Always use HTTPS for webhook endpoints
- Regularly review audit logs for suspicious activity
- Keep software dependencies up to date
- Use environment variables for sensitive configuration
- Never commit secrets to version control
