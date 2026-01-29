# NIJA Layered Architecture Documentation

## Overview

NIJA has been restructured into a secure, multi-user trading platform with three distinct layers:

```
┌─────────────────────────────────────────────────┐
│         Layer 3: User Interface (PUBLIC)         │
│  - Dashboard, Stats, Settings Management         │
│  - Read-only strategy performance                │
│  - User cannot modify core logic                 │
└─────────────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────┐
│      Layer 2: Execution Engine (LIMITED)         │
│  - Broker adapters with user permissions         │
│  - Rate limiting & position caps                 │
│  - Per-user API key management (encrypted)       │
│  - Order execution with validation               │
└─────────────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────┐
│        Layer 1: Core Brain (PRIVATE)             │
│  - Strategy logic & indicators                   │
│  - Risk engine & calculations                    │
│  - Trade decision system                         │
│  - AI tuning (NEVER EXPOSED TO USERS)           │
└─────────────────────────────────────────────────┘
```

## Directory Structure

```
/core/                  # Layer 1 - PRIVATE strategy logic
  __init__.py          # Access control and verification

/execution/            # Layer 2 - LIMITED broker execution
  __init__.py          # User permissions and validation
  broker_adapter.py    # Secure broker wrapper with controls

/ui/                   # Layer 3 - PUBLIC user interface
  __init__.py          # Dashboard API

/auth/                 # User authentication & API key management
  __init__.py          # Encrypted API key storage

/config/               # User-specific configurations
  __init__.py          # Trading preferences & limits

/controls/             # Hard safety controls
  __init__.py          # Kill switches & mandatory limits
```

## Layer 1: Core Brain (PRIVATE)

**Purpose**: Contains proprietary trading strategy, risk algorithms, and decision logic.

**🚫 CRITICAL**: This layer is NEVER exposed to end users. All strategy logic remains private.

**Components**:
- Trading strategy implementation
- Risk management engine
- Technical indicators and signals
- AI/ML models and tuning
- Entry/exit decision logic

**Access Control**:
- Only accessible from execution layer
- Import validation prevents external access
- No user modification allowed

**Example** (internal use only):
```python
from core import verify_core_access

# Only execution layer can import core modules
verify_core_access(__name__)  # Raises PermissionError if unauthorized
```

## Layer 2: Execution Engine (LIMITED)

**Purpose**: Handles broker connections and order execution with user-specific permissions.

**Components**:
- Broker adapters (Coinbase, Binance, Alpaca, OKX, Kraken)
- User permission validation
- Rate limiting and throttling
- Position size enforcement
- Order execution and routing

**User Permissions**:
```python
from execution import UserPermissions, get_permission_validator

# Create user with specific permissions
perms = UserPermissions(
    user_id="user123",
    allowed_pairs=["BTC-USD", "ETH-USD"],  # Limited to these pairs
    max_position_size_usd=100.0,           # Max $100 per position
    max_daily_loss_usd=50.0,               # Max $50 daily loss
    max_positions=3,                        # Max 3 concurrent positions
    trade_only=True                         # Cannot modify strategy
)

# Register user
validator = get_permission_validator()
validator.register_user(perms)

# Validate trade before execution
valid, error = validator.validate_trade(
    user_id="user123",
    pair="BTC-USD",
    position_size_usd=50.0
)
```

**Secure Broker Adapter**:
```python
from execution.broker_adapter import SecureBrokerAdapter

# Create adapter with user permissions
adapter = SecureBrokerAdapter(
    user_id="user123",
    broker_name="coinbase"
)

# Place order (automatically validated)
result = adapter.place_order(
    pair="BTC-USD",
    side="buy",
    size_usd=50.0
)
```

## Layer 3: User Interface (PUBLIC)

**Purpose**: Public-facing interface for users to monitor and configure their trading.

**Components**:
- Dashboard and web UI
- Trading statistics and performance metrics
- User settings management
- Subscription management (planned)

**Dashboard API**:
```python
from ui import DashboardAPI

dashboard = DashboardAPI()

# Get user statistics
stats = dashboard.get_user_stats("user123")
# Returns: total_trades, win_rate, total_pnl, active_positions

# Get user settings
settings = dashboard.get_user_settings("user123")

# Update user settings (limited to allowed settings)
dashboard.update_user_settings("user123", {
    'notifications_enabled': True,
    'risk_level': 'medium'
})
```

## User Authentication & API Key Management

**Purpose**: Securely store and manage user API credentials.

**⚠️ SECURITY**: All API keys are encrypted using Fernet symmetric encryption.

**API Key Manager**:
```python
from auth import get_api_key_manager

# Initialize with encryption key (store this securely!)
api_manager = get_api_key_manager()

# Store user's encrypted API keys
api_manager.store_user_api_key(
    user_id="user123",
    broker="coinbase",
    api_key="user_api_key_here",
    api_secret="user_api_secret_here",
    additional_params={'org_id': 'org-id-here'}  # Optional
)

# Retrieve decrypted credentials (internal use only)
creds = api_manager.get_user_api_key("user123", "coinbase")
# Returns: {'api_key': '...', 'api_secret': '...', 'additional_params': {...}}
```

**User Manager**:
```python
from auth import get_user_manager

user_mgr = get_user_manager()

# Create new user
user_mgr.create_user(
    user_id="user123",
    email="user@example.com",
    subscription_tier="pro"
)

# Disable user trading
user_mgr.disable_user("user123")

# Enable user trading
user_mgr.enable_user("user123")
```

## User Configuration Management

**Purpose**: Manage user-specific trading preferences and limits.

**Configuration**:
```python
from config import get_config_manager

config_mgr = get_config_manager()

# Get user configuration
user_config = config_mgr.get_user_config("user123")

# Update configuration
config_mgr.update_user_config("user123", {
    'max_position_size': 150.0,
    'max_concurrent_positions': 5,
    'risk_level': 'high'
})

# Validate position size
valid, error = user_config.validate_position_size(100.0)

# Check if pair is allowed
can_trade = user_config.can_trade_pair("BTC-USD")
```

**Default Configuration**:
- `allowed_pairs`: None (all pairs allowed by default)
- `max_position_size`: $100
- `max_concurrent_positions`: 3
- `max_daily_loss_pct`: 10%
- `max_drawdown_pct`: 20%
- `risk_level`: 'medium'

## Hard Controls (Safety System)

**Purpose**: Enforce mandatory safety limits that protect users and the platform.

**🔒 CRITICAL**: These controls CANNOT be disabled or bypassed by users.

**Hard Limits**:
- Min position: 2% of account
- Max position: 10% of account
- Max daily trades: 50 per user
- Auto-disable after 5 API errors

**Hard Controls Usage**:
```python
from controls import get_hard_controls

controls = get_hard_controls()

# Validate position size (enforces 2-10% rule)
valid, error = controls.validate_position_size(
    user_id="user123",
    position_size_usd=50.0,
    account_balance=1000.0
)

# Check if user can trade (checks kill switches)
can_trade, error = controls.can_trade("user123")

# Trigger kill switch (stops all trading for user)
controls.trigger_user_kill_switch("user123", "Excessive losses detected")

# Trigger global kill switch (stops ALL trading)
controls.trigger_global_kill_switch("Market emergency")

# Record API error (auto-disables after threshold)
should_disable = controls.record_api_error("user123")

# Record trade loss for daily tracking
controls.record_trade_loss("user123", loss_usd=25.0)
```

**Kill Switches**:
- **Global Kill Switch**: Stops all trading across all users
- **Per-User Kill Switch**: Stops trading for specific user
- **Auto-Disable**: Triggered after excessive errors or losses

## Security Best Practices

### API Key Storage

**❌ WRONG (Dangerous)**:
```python
# DO NOT DO THIS!
COINBASE_API_KEY = "my_master_key"  # Exposed in code
```

**✅ CORRECT (Secure)**:
```python
from auth import get_api_key_manager

# Store encrypted per-user keys
api_manager = get_api_key_manager()
api_manager.store_user_api_key(
    user_id="user_A",
    broker="coinbase",
    api_key="user_A_key",  # Encrypted automatically
    api_secret="user_A_secret"
)
```

### User Permissions

**❌ WRONG (No Limits)**:
```python
# User can trade unlimited size on any pair
# No position limits or risk controls
```

**✅ CORRECT (Scoped Permissions)**:
```python
from execution import UserPermissions

# User A: Conservative limits
UserPermissions(
    user_id="user_A",
    allowed_pairs=["BTC-USD"],  # Limited pairs
    max_position_size_usd=50.0,  # Capped size
    max_positions=2
)

# User B: Different limits
UserPermissions(
    user_id="user_B",
    allowed_pairs=["BTC-USD", "ETH-USD", "SOL-USD"],
    max_position_size_usd=200.0,
    max_positions=5
)
```

### Strategy Locking

**🔒 Strategy is ALWAYS locked**:
```python
from controls import get_hard_controls

controls = get_hard_controls()

# Users CANNOT modify strategy
is_locked = controls.is_strategy_locked()  # Always returns True

# Core strategy logic is inaccessible to users
# Only admins can modify core layer
```

## Migration from Single-User to Multi-User

### Legacy (Single-User) Setup

```python
# Old way - single master API key
from bot.broker_manager import BrokerManager

broker = BrokerManager()
# Uses COINBASE_API_KEY from .env
```

### New (Multi-User) Setup

```python
# New way - per-user encrypted keys
from auth import get_api_key_manager
from execution.broker_adapter import SecureBrokerAdapter

# Store user's API key (one time)
api_manager = get_api_key_manager()
api_manager.store_user_api_key(
    user_id="user123",
    broker="coinbase",
    api_key="user_specific_key",
    api_secret="user_specific_secret"
)

# Create secure adapter for user
adapter = SecureBrokerAdapter(
    user_id="user123",
    broker_name="coinbase"
)

# Trade with user's credentials and permissions
result = adapter.place_order(
    pair="BTC-USD",
    side="buy",
    size_usd=50.0
)
```

## Environment Variables

### Required (Global)

```bash
# Encryption key for API key storage (generate securely!)
NIJA_ENCRYPTION_KEY=your-secure-encryption-key-here
```

### Per-User (Stored Encrypted)

These are NO LONGER environment variables. They are stored encrypted in the auth layer:

- `COINBASE_API_KEY` → Stored per-user encrypted
- `COINBASE_API_SECRET` → Stored per-user encrypted
- `BINANCE_API_KEY` → Stored per-user encrypted
- etc.

## Testing the Layered Architecture

See `example_usage.py` for complete examples.

## Summary

### ✅ Benefits of Layered Architecture

1. **Security**: User API keys encrypted, strategy logic private
2. **Isolation**: Core strategy cannot be accessed or modified by users
3. **Scalability**: Support multiple users with individual limits
4. **Control**: Hard limits enforce safety across all users
5. **Flexibility**: Per-user permissions and configurations

### 🚫 What Users CANNOT Do

- Access or modify core strategy logic
- Bypass hard control limits (2-10% position sizing)
- Exceed daily trade limits
- Trade when kill switch is triggered
- Access other users' data or API keys

### ✅ What Users CAN Do

- View their trading statistics and performance
- Configure their risk preferences (within allowed limits)
- Set allowed/blocked trading pairs
- Enable/disable notifications
- Monitor their positions in real-time

## Support

For questions or issues with the layered architecture:

1. Check `ARCHITECTURE.md` (this file)
2. Review `example_usage.py` for implementation examples
3. See `SECURITY.md` for security best practices
4. Consult `USER_MANAGEMENT.md` for user administration

---

**Version**: 1.0
**Last Updated**: January 8, 2026
**Status**: ✅ Core Architecture Implemented
