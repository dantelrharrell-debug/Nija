# NIJA User Management Guide

## Overview

This guide explains how to manage users in NIJA's multi-user trading platform. Each user has their own API keys, permissions, and trading limits.

## User Lifecycle

### 1. User Registration

Create a new user account:

```python
from auth import get_user_manager

user_mgr = get_user_manager()

# Create user
user = user_mgr.create_user(
    user_id="john_doe",
    email="john@example.com",
    subscription_tier="pro"  # basic, pro, or enterprise
)
```

**Subscription Tiers**:
- **basic**: Conservative limits, fewer pairs, lower position sizes
- **pro**: Moderate limits, more pairs, higher position sizes
- **enterprise**: Custom limits, all pairs, highest position sizes

### 2. API Key Setup

Store user's exchange API keys (encrypted):

```python
from auth import get_api_key_manager

api_mgr = get_api_key_manager()

# Store Coinbase keys
api_mgr.store_user_api_key(
    user_id="john_doe",
    broker="coinbase",
    api_key="user's_coinbase_api_key",
    api_secret="user's_coinbase_secret",
    additional_params={
        'org_id': 'coinbase_org_id',
        'jwt_kid': 'jwt_key_id'
    }
)

# Store Binance keys (if using multiple exchanges)
api_mgr.store_user_api_key(
    user_id="john_doe",
    broker="binance",
    api_key="user's_binance_api_key",
    api_secret="user's_binance_secret"
)
```

**Required from User**:
1. Exchange account with API access enabled
2. API key with trade permissions (read + trade, NO withdrawal)
3. API secret
4. Additional parameters (varies by exchange)

**Security Notes**:
- Keys are encrypted using Fernet encryption
- Never store keys in plain text
- User should create API keys with minimal permissions
- Recommend IP whitelisting if exchange supports it

### 3. Permission Configuration

Set user-specific trading permissions:

```python
from execution import UserPermissions, get_permission_validator

# Create permissions
permissions = UserPermissions(
    user_id="john_doe",
    allowed_pairs=["BTC-USD", "ETH-USD", "SOL-USD"],  # Whitelist
    max_position_size_usd=200.0,                       # Per position
    max_daily_loss_usd=100.0,                          # Daily limit
    max_positions=5,                                   # Concurrent
    trade_only=True,                                   # Cannot modify strategy
    enabled=True                                       # Trading enabled
)

# Register permissions
validator = get_permission_validator()
validator.register_user(permissions)
```

**Permission Defaults by Tier**:

**Basic Tier**:
- `max_position_size_usd`: $50
- `max_daily_loss_usd`: $25
- `max_positions`: 2
- `allowed_pairs`: Major coins only (BTC, ETH)

**Pro Tier**:
- `max_position_size_usd`: $200
- `max_daily_loss_usd`: $100
- `max_positions`: 5
- `allowed_pairs`: Top 20 coins

**Enterprise Tier**:
- `max_position_size_usd`: Custom (up to $1000)
- `max_daily_loss_usd`: Custom (up to $500)
- `max_positions`: Custom (up to 20)
- `allowed_pairs`: All available pairs

### 4. User Configuration

Set user preferences and settings:

```python
from config import get_config_manager

config_mgr = get_config_manager()

# Update user config
config_mgr.update_user_config("john_doe", {
    'max_position_size': 200.0,
    'max_concurrent_positions': 5,
    'risk_level': 'medium',  # low, medium, high
    'enable_trailing_stops': True,
    'enable_take_profit': True,
    'notify_on_trade': True,
    'notify_on_profit_target': True,
    'notify_on_stop_loss': True
})
```

### 5. User Activation

User is now ready to trade:

```python
from execution.broker_adapter import SecureBrokerAdapter

# Create broker adapter for user
adapter = SecureBrokerAdapter(
    user_id="john_doe",
    broker_name="coinbase"
)

# User can now place trades
result = adapter.place_order(
    pair="BTC-USD",
    side="buy",
    size_usd=100.0
)
```

## User Management Operations

### Viewing User Information

```python
from auth import get_user_manager
from execution import get_permission_validator
from config import get_config_manager

user_mgr = get_user_manager()
validator = get_permission_validator()
config_mgr = get_config_manager()

# Get user profile
user = user_mgr.get_user("john_doe")
print(f"User: {user}")

# Get permissions
perms = validator.get_user_permissions("john_doe")
print(f"Permissions: {perms.to_dict()}")

# Get configuration
config = config_mgr.get_user_config("john_doe")
print(f"Config: {config.to_dict()}")
```

### Updating User Limits

```python
# Increase position size limit
validator.user_permissions["john_doe"].max_position_size_usd = 300.0

# Update config
config_mgr.update_user_config("john_doe", {
    'max_position_size': 300.0
})
```

### Disabling User Trading

Temporarily disable a user:

```python
from auth import get_user_manager
from controls import get_hard_controls

user_mgr = get_user_manager()
controls = get_hard_controls()

# Soft disable (can re-enable)
user_mgr.disable_user("john_doe")

# Or use kill switch (requires manual reset)
controls.trigger_user_kill_switch("john_doe", "User requested trading pause")
```

### Re-enabling User Trading

```python
# Re-enable user
user_mgr.enable_user("john_doe")

# Reset kill switch
controls.reset_user_kill_switch("john_doe")
```

### Deleting User

Permanently remove a user:

```python
from auth import get_api_key_manager, get_user_manager
from config import get_config_manager

api_mgr = get_api_key_manager()
user_mgr = get_user_manager()
config_mgr = get_config_manager()

# Delete API keys (all brokers)
brokers = api_mgr.list_user_brokers("john_doe")
for broker in brokers:
    api_mgr.delete_user_api_key("john_doe", broker)

# Delete user config
config_mgr.delete_user_config("john_doe")

# Delete user account
user_mgr.disable_user("john_doe")  # Soft delete
```

## Monitoring Users

### Trading Activity

```python
from ui import DashboardAPI

dashboard = DashboardAPI()

# Get user statistics
stats = dashboard.get_user_stats("john_doe")
print(f"Total trades: {stats['total_trades']}")
print(f"Win rate: {stats['win_rate']}")
print(f"Total P&L: ${stats['total_pnl']}")
print(f"Active positions: {stats['active_positions']}")
```

### Daily Loss Tracking

```python
from controls import get_hard_controls

controls = get_hard_controls()

# Check if user has daily loss tracker
if "john_doe" in controls.daily_loss_trackers:
    tracker = controls.daily_loss_trackers["john_doe"]
    print(f"Today's loss: ${tracker.total_loss_usd}")
    print(f"Trade count: {tracker.trade_count}")
    print(f"Last trade: {tracker.last_trade_time}")
```

### Error Tracking

```python
# Check error count
if "john_doe" in controls.user_error_counts:
    error_count = controls.user_error_counts["john_doe"]
    print(f"API errors today: {error_count}/{controls.ERROR_THRESHOLD}")

    if error_count >= controls.ERROR_THRESHOLD:
        print("⚠️ User auto-disabled due to errors")
```

## Bulk Operations

### Onboard Multiple Users

```python
users_to_add = [
    {
        'user_id': 'user1',
        'email': 'user1@example.com',
        'tier': 'basic',
        'pairs': ['BTC-USD'],
        'max_size': 50.0
    },
    {
        'user_id': 'user2',
        'email': 'user2@example.com',
        'tier': 'pro',
        'pairs': ['BTC-USD', 'ETH-USD'],
        'max_size': 200.0
    }
]

for user_data in users_to_add:
    # Create user
    user_mgr.create_user(
        user_id=user_data['user_id'],
        email=user_data['email'],
        subscription_tier=user_data['tier']
    )

    # Set permissions
    perms = UserPermissions(
        user_id=user_data['user_id'],
        allowed_pairs=user_data['pairs'],
        max_position_size_usd=user_data['max_size'],
        max_positions=3,
        trade_only=True
    )
    validator.register_user(perms)

    print(f"✅ Added user: {user_data['user_id']}")
```

### Disable All Users (Emergency)

```python
# Trigger global kill switch
controls.trigger_global_kill_switch("System maintenance")

# All users stopped immediately
print("🚨 All trading halted")
```

### List All Users

```python
# Get all users
all_users = user_mgr.users
for user_id, user_data in all_users.items():
    perms = validator.get_user_permissions(user_id)
    print(f"{user_id}: {user_data['subscription_tier']} - "
          f"Enabled: {user_data['enabled']}")
```

## Common Scenarios

### Scenario 1: User Hits Daily Loss Limit

```python
# Automatic handling
# 1. Hard controls detect daily loss exceeded
# 2. User kill switch triggered automatically
# 3. User blocked from trading

# Manual intervention
# 1. Review user's trades
# 2. Determine if limit should be increased or reset
# 3. Reset kill switch if appropriate

controls.reset_user_kill_switch("john_doe")
print("User can trade again tomorrow (tracker resets daily)")
```

### Scenario 2: User Reports API Key Compromised

```python
# 1. Immediately trigger kill switch
controls.trigger_user_kill_switch("john_doe", "API key compromised")

# 2. Delete old API keys
api_mgr.delete_user_api_key("john_doe", "coinbase")

# 3. User creates new API keys on exchange

# 4. Store new keys
api_mgr.store_user_api_key(
    user_id="john_doe",
    broker="coinbase",
    api_key="new_api_key",
    api_secret="new_api_secret"
)

# 5. Reset kill switch
controls.reset_user_kill_switch("john_doe")

# 6. Reset error count
controls.reset_error_count("john_doe")
```

### Scenario 3: Upgrade User Tier

```python
# Update subscription tier
user_mgr.update_user("john_doe", {
    'subscription_tier': 'pro'
})

# Update permissions
perms = validator.get_user_permissions("john_doe")
perms.max_position_size_usd = 200.0  # Pro tier limit
perms.max_positions = 5
perms.allowed_pairs = ["BTC-USD", "ETH-USD", "SOL-USD", "AVAX-USD"]

# Update config
config_mgr.update_user_config("john_doe", {
    'max_position_size': 200.0,
    'max_concurrent_positions': 5
})

print("✅ User upgraded to Pro tier")
```

### Scenario 4: Temporary Trading Pause

```python
# User requests to pause trading (vacation, etc.)

# Option 1: Disable user account
user_mgr.disable_user("john_doe")

# Option 2: Use kill switch
controls.trigger_user_kill_switch("john_doe", "User requested pause")

# When user returns
user_mgr.enable_user("john_doe")
controls.reset_user_kill_switch("john_doe")
```

## Best Practices

### User Onboarding

1. Start with conservative limits
2. Monitor for first 30 days
3. Gradually increase based on performance
4. Require exchange API keys with trade-only permissions
5. Educate users about limits and safety features

### Limit Setting

1. **Position Size**: Start at 2-5% of account
2. **Daily Loss**: 10% of max exposure
3. **Max Positions**: 2-3 for beginners, 5-10 for experienced
4. **Allowed Pairs**: Start with major coins, expand gradually

### Monitoring

1. Review daily loss trackers daily
2. Check error counts weekly
3. Audit permissions quarterly
4. Review user performance monthly
5. Adjust limits based on track record

### Security

1. Never share encryption key
2. Store API keys encrypted only
3. Use kill switches proactively
4. Monitor for suspicious activity
5. Have emergency procedures documented

## Troubleshooting

### User Cannot Trade

**Check**:
1. Is user enabled? `user_mgr.get_user("user_id")['enabled']`
2. Is kill switch triggered? `controls.can_trade("user_id")`
3. Daily loss limit exceeded? `controls.check_daily_loss_limit(...)`
4. Too many errors? `controls.user_error_counts.get("user_id", 0)`

### User Trades Rejected

**Check**:
1. Is pair allowed? `perms.can_trade_pair("BTC-USD")`
2. Position size within limits? `perms.validate_position_size(100.0)`
3. Hard controls pass? `controls.validate_position_size(...)`

### API Key Issues

**Check**:
1. Are keys stored? `api_mgr.list_user_brokers("user_id")`
2. Can decrypt keys? `api_mgr.get_user_api_key("user_id", "broker")`
3. Are keys valid on exchange? (test externally)

## Support

For user management questions:
- Architecture: See `ARCHITECTURE.md`
- Security: See `SECURITY.md`
- Examples: See `example_usage.py`

---

**Version**: 1.0
**Last Updated**: January 8, 2026
**Status**: ✅ User Management System Operational
