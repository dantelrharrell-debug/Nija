# NIJA - Coinbase Balance Detection Fix

## What Was Fixed

Balance detection now works correctly to enable trade execution.

### Root Cause
The `coinbase-advanced-py` SDK uses **JWT authentication where JWTs are signed with EC private keys**. The API_SECRET must be a PEM-formatted private key, not a simple string.

### Changes Made

1. **broker_manager.py**:
   - Added PEM newline normalization (`\n` → actual newlines)
   - Simplified connection while keeping PEM support
   - Cleaner error messages

2. **print_accounts.py**:
   - Added PEM newline normalization
   - Better credential validation

### How It Works

```
COINBASE_API_KEY → Used in JWT "kid" header
COINBASE_API_SECRET → PEM private key used to sign JWT
    ↓
SDK generates JWT token signed with private key
    ↓
JWT sent in Authorization header to Coinbase API
```

### Required Credentials Format

```bash
# API Key format
COINBASE_API_KEY=organizations/{org_id}/apiKeys/{key_id}

# API Secret format (PEM private key)
COINBASE_API_SECRET=-----BEGIN EC PRIVATE KEY-----
MHcCAQEEI...
...
-----END EC PRIVATE KEY-----
```

Or single-line with `\n`:
```bash
COINBASE_API_SECRET=-----BEGIN EC PRIVATE KEY-----\nMHcCAQEEI...\n-----END EC PRIVATE KEY-----\n
```

### Test Balance Detection

```bash
python scripts/print_accounts.py
```

Should output:
```
🔐 Coinbase Advanced Trade Authentication
   API Key: ✅ Set
   API Secret: ✅ Set

📡 Calling GET /v3/accounts...

💰 BALANCES:
USD=123.45 USDC=0.00 TOTAL=123.45

📋 ALL ACCOUNTS:
USD: 123.45
BTC: 0.00050000
...
```

### Trades Will Now Execute

Once balance detection works (showing non-zero balance), the trading bot can:
1. Calculate position sizes based on available USD/USDC
2. Place market orders via `POST /v3/brokerage/orders`
3. Execute the APEX v7.1 trading strategy

Balance must be > 0 for trades to execute.
