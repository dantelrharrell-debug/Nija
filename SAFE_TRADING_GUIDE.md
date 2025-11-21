# Safe Trading Stack Documentation

## Overview

This implementation adds a comprehensive safe trading stack with multiple layers of protection to prevent accidental trading from funded accounts. The system supports three modes: SANDBOX, DRY_RUN, and LIVE.

## Key Features

### 1. Trading Modes
- **DRY_RUN** (default): Simulates trades without executing them
- **SANDBOX**: Uses sandbox/test environment
- **LIVE**: Executes real trades (requires explicit confirmation)

### 2. Safety Mechanisms

#### Mode Safety Checks
- **LIVE mode requires**:
  - `COINBASE_ACCOUNT_ID` environment variable must be set
  - `CONFIRM_LIVE=true` must be set to confirm intent
  - API key must NOT have withdraw permission

#### Order Protections
- **MAX_ORDER_USD**: Maximum dollar amount per order (default: $100)
- **MAX_ORDERS_PER_MINUTE**: Rate limiting (default: 5 orders/minute)
- **MANUAL_APPROVAL_COUNT**: First N orders require manual approval (default: 0)

#### Audit Logging
- All order requests logged to `LOG_PATH` with timestamp
- Includes both request and Coinbase response
- JSON format for easy parsing

### 3. TradingView Webhook Integration
- Secure webhook endpoint with HMAC SHA256 signature verification
- Uses `TRADINGVIEW_WEBHOOK_SECRET` for validation
- Header: `X-Tv-Signature` contains the HMAC signature

## Configuration

Set these environment variables to configure the trading stack:

```bash
# Trading mode (required)
MODE=DRY_RUN                          # Options: SANDBOX, DRY_RUN, LIVE

# LIVE mode requirements (only for MODE=LIVE)
COINBASE_ACCOUNT_ID=your-account-id   # Your Coinbase account ID
CONFIRM_LIVE=true                     # Explicit confirmation for live trading

# Order safety limits
MAX_ORDER_USD=100.0                   # Maximum order size in USD
MAX_ORDERS_PER_MINUTE=5               # Rate limit for orders
MANUAL_APPROVAL_COUNT=0               # Number of orders requiring manual approval

# Logging
LOG_PATH=/tmp/nija_trading.log        # Path to audit log file

# TradingView webhook
TRADINGVIEW_WEBHOOK_SECRET=your_secret_key  # Secret for webhook signature verification
```

## Usage

### Starting in DRY_RUN Mode (Safe Testing)

```bash
MODE=DRY_RUN python main.py
```

This will:
- Log all trade signals
- NOT execute any real orders
- Allow testing without risk

### Starting in LIVE Mode

```bash
MODE=LIVE \
COINBASE_ACCOUNT_ID=your-account-id \
CONFIRM_LIVE=true \
MAX_ORDER_USD=50.0 \
python main.py
```

**WARNING**: Only use LIVE mode when you are absolutely certain and have:
1. Set the correct `COINBASE_ACCOUNT_ID`
2. Confirmed with `CONFIRM_LIVE=true`
3. Verified your API key does NOT have withdraw permission
4. Set appropriate limits with `MAX_ORDER_USD`

### Using Safe Order Submission

```python
from safe_order import submit_order
from nija_client import CoinbaseClient

client = CoinbaseClient()

# Submit a safe order (enforces all protections)
result = submit_order(
    client=client,
    symbol="BTC-USD",
    side="buy",
    size_usd=50.0
)
```

### TradingView Webhook

The webhook endpoint is available at:
```
POST /tradingview/webhook
```

Required header:
```
X-Tv-Signature: <hmac_sha256_signature>
```

Example TradingView alert webhook payload:
```json
{
  "action": "buy",
  "symbol": "BTC-USD",
  "price": 50000
}
```

Generate signature:
```python
import hmac
import hashlib
import json

payload = {"action": "buy", "symbol": "BTC-USD"}
payload_bytes = json.dumps(payload).encode('utf-8')

signature = hmac.new(
    secret.encode('utf-8'),
    payload_bytes,
    hashlib.sha256
).hexdigest()
```

Health check endpoint:
```
GET /tradingview/health
```

### Manual Approval Workflow

When `MANUAL_APPROVAL_COUNT` is set (e.g., `MANUAL_APPROVAL_COUNT=3`), the first N orders will be saved to a pending approvals file instead of being executed immediately.

Check pending approvals:
```python
from safe_order import get_pending_approvals

pending = get_pending_approvals()
print(pending)
```

Approve an order:
```python
from safe_order import approve_order

# Approve the first pending order (index 0)
approve_order(0)
```

## File Structure

```
nija/
├── config.py              # Configuration with MODE, limits, etc.
├── nija_client.py         # Enhanced CoinbaseClient with safety checks
├── safe_order.py          # Centralized order submission module
├── webhook_handler.py     # TradingView webhook Blueprint
├── main.py               # Flask app with webhook registered
└── tests/
    ├── test_safe_order.py
    ├── test_webhook_handler.py
    └── test_integration.py
```

## Security Best Practices

1. **Never use LIVE mode without explicit confirmation**
   - Always set `CONFIRM_LIVE=true` explicitly
   - Never use default values for LIVE mode

2. **API Key Permissions**
   - Remove withdraw permission from your Coinbase API key
   - System will check and refuse to run if withdraw permission detected

3. **Start with DRY_RUN**
   - Always test your strategy in DRY_RUN mode first
   - Verify logs and behavior before going live

4. **Use Manual Approval for First Orders**
   - Set `MANUAL_APPROVAL_COUNT=5` to manually approve first 5 orders
   - Review each order before executing

5. **Set Conservative Limits**
   - Start with low `MAX_ORDER_USD` values
   - Adjust `MAX_ORDERS_PER_MINUTE` to prevent runaway trading

6. **Monitor Audit Logs**
   - Regularly review `LOG_PATH` for all trading activity
   - Each entry contains full request and response data

## Testing

Run the test suite:

```bash
# Test safe_order module
python tests/test_safe_order.py

# Test webhook_handler module
python tests/test_webhook_handler.py

# Run integration tests
python tests/test_integration.py
```

## Troubleshooting

### "LIVE mode requires COINBASE_ACCOUNT_ID to be set"
- Set the `COINBASE_ACCOUNT_ID` environment variable
- Get your account ID from Coinbase Advanced Trade

### "LIVE mode requires CONFIRM_LIVE=true to be set"
- Set `CONFIRM_LIVE=true` environment variable
- This is a safety measure to prevent accidental live trading

### "API key has withdraw permission"
- Remove withdraw permission from your Coinbase API key
- Go to Coinbase API settings and edit permissions
- Only allow trade and view permissions

### "Rate limit exceeded"
- Wait 60 seconds or adjust `MAX_ORDERS_PER_MINUTE`
- Check for runaway trading logic

### "Order amount exceeds MAX_ORDER_USD limit"
- Reduce order size or increase `MAX_ORDER_USD`
- Review your position sizing logic

## Support

For issues or questions, please open an issue in the repository.
