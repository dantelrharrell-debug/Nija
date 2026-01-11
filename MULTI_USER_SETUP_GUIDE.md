# NIJA Multi-User Setup Guide

## Overview

NIJA now supports multiple users with individual API keys, permissions, and independent control. Each user can be enabled/disabled without affecting other users.

## Current Users

### User 1: Daivon Frazier
- **User ID**: `daivon_frazier`
- **Email**: Frazierdaivon@gmail.com
- **Tier**: Pro
- **Status**: Active ✅
- **Setup Date**: January 8, 2026
- **Broker**: Coinbase

**Permissions**:
- Max position size: $300
- Max daily loss: $150
- Max concurrent positions: 7
- Allowed pairs: BTC-USD, ETH-USD, SOL-USD, AVAX-USD, MATIC-USD, DOT-USD, LINK-USD, ADA-USD

**Configuration**:
- Risk level: Moderate
- Trailing stops: Enabled
- Auto-compound: Enabled

### User 2: Tania Gilbert
- **User ID**: `tania_gilbert`
- **Email**: Tanialgilbert@gmail.com
- **Tier**: Pro
- **Status**: Active ✅
- **Setup Date**: January 11, 2026
- **Broker**: Alpaca (https://api.alpaca.markets)

**Permissions**:
- Max position size: $200
- Max daily loss: $100
- Max concurrent positions: 5
- Allowed pairs: AAPL, MSFT, GOOGL, AMZN, TSLA, NVDA, META, BTC/USD, ETH/USD, SOL/USD

**Configuration**:
- Risk level: Moderate
- Trailing stops: Enabled
- Auto-compound: Enabled
- Trading mode: Paper (for testing)

## User Management Commands

### Check User Status
```python
from auth import get_user_manager

user_mgr = get_user_manager()
user = user_mgr.get_user('daivon_frazier')
print(f"User: {user['email']}, Enabled: {user['enabled']}")
```

### Enable User Trading
```python
from auth import get_user_manager

user_mgr = get_user_manager()
user_mgr.enable_user('daivon_frazier')
print("✅ User trading enabled")
```

### Disable User Trading
```python
from auth import get_user_manager

user_mgr = get_user_manager()
user_mgr.disable_user('daivon_frazier')
print("🛑 User trading disabled")
```

### Check if User Can Trade
```python
from controls import get_hard_controls

controls = get_hard_controls()
can_trade, error = controls.can_trade('daivon_frazier')
if can_trade:
    print("✅ User can trade")
else:
    print(f"❌ User cannot trade: {error}")
```

### View User API Keys (Decrypted)
```python
from auth import get_api_key_manager

api_mgr = get_api_key_manager()
creds = api_mgr.get_user_api_key('daivon_frazier', 'coinbase')
if creds:
    print(f"API Key: {creds['api_key'][:20]}...")
    print(f"Broker: {creds['broker']}")
```

## Adding New Users

To add a new user, follow the structure used for Daivon Frazier:

### Step 1: Create User Account
```python
from auth import get_user_manager

user_mgr = get_user_manager()
user = user_mgr.create_user(
    user_id="new_user_id",
    email="user@example.com",
    subscription_tier="pro"  # basic, pro, or enterprise
)
```

### Step 2: Store API Credentials
```python
from auth import get_api_key_manager

api_mgr = get_api_key_manager()
api_mgr.store_user_api_key(
    user_id="new_user_id",
    broker="coinbase",  # or alpaca, binance, okx, kraken
    api_key="user_api_key_here",
    api_secret="user_api_secret_here",
    additional_params={
        'name': 'User Full Name',
        'email': 'user@example.com'
    }
)
```

**Note for Alpaca users**: Set environment variables instead of storing in script:
```bash
# For user 'tania_gilbert', set:
export ALPACA_USER_TANIA_API_KEY="your-api-key"
export ALPACA_USER_TANIA_API_SECRET="your-api-secret"
export ALPACA_USER_TANIA_PAPER="true"  # or false for live trading
```

### Step 3: Configure Permissions
```python
from execution import UserPermissions, get_permission_validator

permissions = UserPermissions(
    user_id="new_user_id",
    allowed_pairs=["BTC-USD", "ETH-USD"],  # Specify allowed pairs
    max_position_size_usd=200.0,           # Max per position
    max_daily_loss_usd=100.0,              # Daily loss limit
    max_positions=5,                       # Concurrent positions
    trade_only=True,                       # Cannot modify strategy
    enabled=True                           # Trading enabled
)

validator = get_permission_validator()
validator.register_user(permissions)
```

### Step 4: Configure User Settings
```python
from config import get_config_manager

config_mgr = get_config_manager()
config_mgr.update_user_config("new_user_id", {
    'max_position_size': 200.0,
    'max_concurrent_positions': 5,
    'risk_level': 'moderate',  # low, moderate, high
    'enable_trailing_stops': True,
    'enable_auto_compound': True,
    'notification_email': 'user@example.com'
})
```

## User Setup Script Template

For each new user, create a setup script similar to `setup_user_daivon.py`:

```python
#!/usr/bin/env python3
"""
Setup script for user: [User Name]

User Information:
- Name: [Full Name]
- Email: [email@example.com]
- User ID: [user_id]
"""

import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from auth import get_api_key_manager, get_user_manager
from execution import UserPermissions, get_permission_validator
from config import get_config_manager

def setup_user():
    """Set up user account."""
    user_id = "user_id"
    email = "email@example.com"
    name = "Full Name"
    
    # API credentials
    api_key = "user_api_key"
    api_secret = "user_api_secret"
    
    # 1. Create user
    user_mgr = get_user_manager()
    user = user_mgr.create_user(
        user_id=user_id,
        email=email,
        subscription_tier="pro"
    )
    
    # 2. Store encrypted credentials
    api_mgr = get_api_key_manager()
    api_mgr.store_user_api_key(
        user_id=user_id,
        broker="coinbase",
        api_key=api_key,
        api_secret=api_secret,
        additional_params={'name': name, 'email': email}
    )
    
    # 3. Configure permissions
    permissions = UserPermissions(
        user_id=user_id,
        allowed_pairs=["BTC-USD", "ETH-USD", "SOL-USD"],
        max_position_size_usd=300.0,
        max_daily_loss_usd=150.0,
        max_positions=7,
        trade_only=True,
        enabled=True
    )
    validator = get_permission_validator()
    validator.register_user(permissions)
    
    # 4. Configure settings
    config_mgr = get_config_manager()
    config_mgr.update_user_config(user_id, {
        'max_position_size': 300.0,
        'max_concurrent_positions': 7,
        'risk_level': 'moderate',
        'enable_trailing_stops': True,
        'enable_auto_compound': True
    })
    
    print(f"✅ User {name} setup complete!")

if __name__ == "__main__":
    setup_user()
```

## Security Best Practices

1. **API Keys**: Always use encrypted storage via `APIKeyManager`
2. **Permissions**: Set conservative limits initially, increase gradually
3. **Monitoring**: Track daily losses and trade counts per user
4. **Kill Switches**: Use user-specific kill switches for emergencies
5. **Credentials**: Never commit API keys to git or share publicly

## Independent User Control

Each user operates independently:
- Disabling one user doesn't affect others
- API errors for one user don't impact other users
- Daily limits are tracked per user
- Each user has their own encrypted API keys
- Permissions are enforced at the user level

## Subscription Tiers

### Basic Tier
- Max position: $50
- Max daily loss: $25
- Max positions: 3
- Limited pairs (major cryptos only)

### Pro Tier (Daivon Frazier)
- Max position: $300
- Max daily loss: $150
- Max positions: 7
- Extended pairs (top 10-20 cryptos)

### Enterprise Tier
- Custom limits
- All trading pairs
- Priority support
- Custom risk parameters

## Troubleshooting

### User Cannot Trade

Check these in order:

1. **User Enabled?**
   ```python
   user = user_mgr.get_user('daivon_frazier')
   print(user['enabled'])  # Should be True
   ```

2. **Permissions Active?**
   ```python
   perms = validator.get_user_permissions('daivon_frazier')
   print(perms.enabled)  # Should be True
   ```

3. **Kill Switch?**
   ```python
   can_trade, error = controls.can_trade('daivon_frazier')
   print(f"Can trade: {can_trade}, Error: {error}")
   ```

4. **Daily Limits?**
   ```python
   can_trade, error = controls.check_daily_loss_limit(
       'daivon_frazier', 
       max_daily_loss_usd=150.0
   )
   print(f"Within limits: {can_trade}, Error: {error}")
   ```

### Resetting User State

If a user needs a fresh start:

```python
from auth import get_user_manager, get_api_key_manager
from execution import get_permission_validator
from controls import get_hard_controls

user_id = 'daivon_frazier'

# Reset kill switch
controls = get_hard_controls()
controls.reset_user_kill_switch(user_id)

# Re-enable user
user_mgr = get_user_manager()
user_mgr.enable_user(user_id)

# Verify
user = user_mgr.get_user(user_id)
print(f"User enabled: {user['enabled']}")
```

## Next Steps

When adding user #2, #3, etc.:
1. Create a setup script: `setup_user_[name].py`
2. Run the setup script to add the user
3. Update this document with the new user's information
4. Test user-specific enable/disable functionality
5. Verify independent operation (one user's issues don't affect others)

---

**Important**: Each user's credentials are encrypted and stored separately. Users cannot see or access other users' data or credentials.
