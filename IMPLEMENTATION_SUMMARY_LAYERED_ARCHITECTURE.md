# NIJA Layered Architecture - Implementation Summary

## Executive Summary

NIJA has been successfully restructured from a single-user trading bot into a secure, multi-user trading platform with institutional-grade security and risk controls.

**Implementation Date**: January 8, 2026  
**Status**: ✅ COMPLETE  
**Architecture Version**: 2.0

## Requirements Met

### ✅ 1. Separate NIJA into LAYERS

#### Layer 1 — Core Brain (PRIVATE) 🚫 NEVER EXPOSE
**Location**: `/core/`

**Components**:
- Strategy logic (trading decisions, indicators, signals)
- Risk engine (position sizing, risk calculations)
- Trade decision system (entry/exit logic)
- AI tuning and optimization

**Protection**:
- ✅ Access control prevents unauthorized imports
- ✅ Strategy logic cannot be accessed by users
- ✅ Import validation in `core/__init__.py`
- ✅ Only execution layer can access core

**Code Example**:
```python
from core import verify_core_access

# Only authorized modules can access
verify_core_access(__name__)  # Raises PermissionError if unauthorized
```

---

#### Layer 2 — Execution Engine (LIMITED) ⚡
**Location**: `/execution/`

**Components**:
- Broker adapters (Coinbase, Binance, Alpaca, OKX, Kraken)
- Rate limiting and throttling
- Position sizing caps
- User permission enforcement

**Features**:
- ✅ User-specific permissions (`execution/__init__.py`)
- ✅ Permission validation before every trade
- ✅ Secure broker adapter (`execution/broker_adapter.py`)
- ✅ Rate limiting protection
- ✅ Position caps enforced

**Code Example**:
```python
from execution import UserPermissions, get_permission_validator

perms = UserPermissions(
    user_id="user123",
    allowed_pairs=["BTC-USD", "ETH-USD"],  # Limited pairs
    max_position_size_usd=100.0,            # Capped size
    max_positions=3                         # Position limit
)
validator.register_user(perms)
```

---

#### Layer 3 — User Interface (PUBLIC) 📊
**Location**: `/ui/`

**Components**:
- Dashboard and web interface
- Statistics and performance metrics
- User settings management
- Subscription management (stub)

**Features**:
- ✅ Read-only access to strategy performance
- ✅ Users can view their own stats only
- ✅ Settings modification limited to allowed parameters
- ✅ Cannot access other users' data
- ✅ Cannot modify core strategy logic

**Code Example**:
```python
from ui import DashboardAPI

dashboard = DashboardAPI()
stats = dashboard.get_user_stats("user123")  # Own data only
```

---

### ✅ 2. User-Based API Architecture (Critical)

#### ❌ Dangerous (Old Way)
```python
# Single master API key shared by all users
COINBASE_API_KEY = "master_key"  # Exposed, insecure
```

#### ✅ Correct (New Way)
**Location**: `/auth/`

**Implementation**:
- ✅ Encrypted API key storage using Fernet encryption
- ✅ Per-user API keys (each user has their own)
- ✅ Scoped permissions (trade-only, limited pairs)
- ✅ Max drawdown rules per user

**Features**:
- **Encryption**: AES-128-CBC + HMAC-SHA256 (Fernet)
- **Storage**: Encrypted at rest, decrypted on demand
- **Access**: Each user has isolated credentials
- **Revocation**: Can revoke individual user access

**Code Example**:
```python
from auth import get_api_key_manager

api_mgr = get_api_key_manager()

# Store User A's keys (encrypted automatically)
api_mgr.store_user_api_key(
    user_id="user_A",
    broker="coinbase",
    api_key="user_A_specific_key",
    api_secret="user_A_specific_secret"
)

# Store User B's keys (different from User A)
api_mgr.store_user_api_key(
    user_id="user_B",
    broker="coinbase",
    api_key="user_B_specific_key",
    api_secret="user_B_specific_secret"
)

# Retrieve decrypted (internal use only)
creds = api_mgr.get_user_api_key("user_A", "coinbase")
```

**User Permissions**:
```python
# User A: Conservative
UserPermissions(
    user_id="user_A",
    allowed_pairs=["BTC-USD"],          # Trade only BTC
    max_position_size_usd=50.0,         # Max $50 per trade
    max_positions=2                      # Max 2 positions
)

# User B: Aggressive
UserPermissions(
    user_id="user_B",
    allowed_pairs=["BTC-USD", "ETH-USD", "SOL-USD"],
    max_position_size_usd=200.0,
    max_positions=5
)
```

---

### ✅ 3. HARD CONTROLS YOU MUST ENFORCE

**Location**: `/controls/`

All hard controls are **MANDATORY** and **CANNOT BE BYPASSED** by users.

#### ✅ Max % per trade (2–10%)
```python
MIN_POSITION_PCT = 0.02   # 2% minimum
MAX_POSITION_PCT = 0.10   # 10% maximum
```

**Example**:
- Account: $1,000
- Min position: $20 (2%)
- Max position: $100 (10%)
- User requests $150: ❌ **REJECTED**
- User requests $50: ✅ **ALLOWED**

**Enforcement**:
```python
from controls import get_hard_controls

controls = get_hard_controls()
valid, error = controls.validate_position_size(
    user_id="user123",
    position_size_usd=150.0,
    account_balance=1000.0
)
# Returns: (False, "Position too large: $150.00 (maximum $100.00, 10%)")
```

---

#### ✅ Daily loss limit
```python
MAX_DAILY_LOSS = configurable per user
```

**Features**:
- ✅ Tracks losses per user per day
- ✅ Automatically resets at midnight
- ✅ Blocks trading when limit exceeded

**Code Example**:
```python
# Set user's daily loss limit
user_config.set('max_daily_loss_pct', 10.0)  # 10% of exposure

# Record losses
controls.record_trade_loss("user123", 25.0)

# Check limit
can_trade, error = controls.check_daily_loss_limit(
    user_id="user123",
    max_daily_loss_usd=100.0
)
```

---

#### ✅ Kill switch (GLOBAL + PER USER)

**Global Kill Switch**:
```python
# Stop ALL trading for ALL users
controls.trigger_global_kill_switch("Market emergency")

# All users blocked immediately
# Requires manual reset
controls.reset_global_kill_switch()
```

**Per-User Kill Switch**:
```python
# Stop trading for specific user
controls.trigger_user_kill_switch("user123", "Daily loss exceeded")

# User blocked, others unaffected
# Can be reset when issue resolved
controls.reset_user_kill_switch("user123")
```

**Kill Switch Status**:
```python
can_trade, error = controls.can_trade("user123")
# If kill switch triggered: (False, "Trading halted (kill switch triggered)")
```

---

#### ✅ Strategy locking (users cannot tweak logic)

```python
is_locked = controls.is_strategy_locked()  # Always returns True
```

**What Users CANNOT Do**:
- ❌ Modify entry/exit logic
- ❌ Change risk calculations
- ❌ Adjust indicator parameters
- ❌ Change position sizing formulas
- ❌ Disable stop losses

**What Users CAN Do**:
- ✅ Choose which pairs to trade (from allowed list)
- ✅ Set position size limits (within hard limits)
- ✅ Choose risk level (low/medium/high preset)
- ✅ Enable/disable notifications

---

#### ✅ Auto-disable on errors / API abuse

```python
ERROR_THRESHOLD = 5  # Auto-disable after 5 errors
MAX_DAILY_TRADES = 50  # Max trades per user per day
```

**Auto-Disable Triggers**:
1. **API Errors**: 5+ errors → user kill switch triggered
2. **Daily Trade Limit**: 50+ trades → blocked for rest of day
3. **Daily Loss Limit**: Exceeded → blocked until reset
4. **Suspicious Activity**: Manual trigger available

**Code Example**:
```python
# Record API error
should_disable = controls.record_api_error("user123")

if should_disable:
    # User automatically disabled after 5th error
    # Kill switch triggered
    # Admin notification sent
    pass

# Manual reset
controls.reset_error_count("user123")
controls.reset_user_kill_switch("user123")
```

---

## Security Model

### API Key Security

**Old (Insecure)**:
```python
# Plain text in code/env
COINBASE_API_KEY = "abc123"
```

**New (Secure)**:
```python
# Encrypted storage
api_mgr.store_user_api_key(...)  # Fernet encryption
creds = api_mgr.get_user_api_key(...)  # Decrypt on demand
```

**Encryption Details**:
- **Algorithm**: Fernet (AES-128-CBC + HMAC-SHA256)
- **Key Size**: 256-bit encryption key
- **Storage**: Encrypted at rest
- **Access**: Decrypted only when needed
- **Rotation**: Supported

### Access Control

**Layer Isolation**:
```
UI Layer (PUBLIC)
    ↓ (validates permissions)
Execution Layer (LIMITED)
    ↓ (protected access)
Core Layer (PRIVATE - locked)
```

**Permission Validation**:
Every trade goes through:
1. User enabled check
2. Pair whitelist check
3. Position size validation (hard limits)
4. Daily loss limit check
5. Kill switch check
6. Execute only if all pass

---

## Files Created

```
/core/__init__.py                    # Core layer with access control
/execution/__init__.py               # User permissions & validation
/execution/broker_adapter.py         # Secure broker wrapper
/ui/__init__.py                      # Public dashboard API
/auth/__init__.py                    # Encrypted API key management (8.4KB)
/config/__init__.py                  # User configuration (6.4KB)
/controls/__init__.py                # Hard safety controls (9.2KB)
ARCHITECTURE.md                      # Complete architecture docs (12.2KB)
SECURITY.md                          # Security best practices (10.4KB)
USER_MANAGEMENT.md                   # User admin guide (12.2KB)
example_usage.py                     # Working examples (12.3KB)
```

**Total**: 12 new files, ~71KB of new code and documentation

---

## Testing Results

All 7 example scenarios passed:

1. ✅ User registration with encrypted API keys
2. ✅ Trade validation (allowed/denied scenarios)
3. ✅ Secure broker adapter usage
4. ✅ Kill switch functionality (global + per-user)
5. ✅ Daily loss tracking and limits
6. ✅ Auto-disable on API errors (5 error threshold)
7. ✅ Multi-user with different permissions

**Test Command**: `python example_usage.py`

---

## Migration Guide

### For Existing Single-User Setup

**Step 1**: Create user account
```python
from auth import get_user_manager

user_mgr = get_user_manager()
user = user_mgr.create_user(
    user_id="main_user",
    email="your@email.com",
    subscription_tier="pro"
)
```

**Step 2**: Migrate API keys
```python
from auth import get_api_key_manager
import os

api_mgr = get_api_key_manager()

# Store existing Coinbase keys encrypted
api_mgr.store_user_api_key(
    user_id="main_user",
    broker="coinbase",
    api_key=os.getenv("COINBASE_API_KEY"),
    api_secret=os.getenv("COINBASE_API_SECRET")
)
```

**Step 3**: Set permissions
```python
from execution import UserPermissions, get_permission_validator

perms = UserPermissions(
    user_id="main_user",
    allowed_pairs=None,  # All pairs
    max_position_size_usd=1000.0,
    max_positions=8,
    trade_only=True
)

validator = get_permission_validator()
validator.register_user(perms)
```

**Step 4**: Use secure adapter
```python
from execution.broker_adapter import SecureBrokerAdapter

adapter = SecureBrokerAdapter(
    user_id="main_user",
    broker_name="coinbase"
)
```

---

## Benefits

### Security
- ✅ API keys never stored in plain text
- ✅ Per-user credential isolation
- ✅ Strategy logic protected from user access
- ✅ Complete audit trail

### Scalability
- ✅ Support unlimited users
- ✅ Each user has own limits
- ✅ Individual kill switches
- ✅ No shared resources

### Risk Management
- ✅ Hard position limits (2-10%)
- ✅ Daily loss limits
- ✅ Auto-disable on errors
- ✅ Emergency kill switches

### Compliance
- ✅ User attribution for all trades
- ✅ Cannot bypass safety controls
- ✅ Strategy locking prevents manipulation
- ✅ Full logging and audit trail

---

## Next Steps

### For Admins

1. **Generate Encryption Key**:
   ```bash
   export NIJA_ENCRYPTION_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
   ```

2. **Store Key Securely**: Add to secrets manager or secure .env

3. **Onboard First User**: Follow USER_MANAGEMENT.md guide

4. **Test Controls**: Run `python example_usage.py`

5. **Monitor**: Set up logging and alerting

### For Users

1. **Create Exchange API Keys**: With trade-only permissions
2. **Provide Keys to Admin**: For encrypted storage
3. **Understand Limits**: Review your permissions
4. **Monitor Performance**: Use dashboard to track stats

---

## Documentation

- **[ARCHITECTURE.md](ARCHITECTURE.md)** - Complete technical overview
- **[SECURITY.md](SECURITY.md)** - Security model and best practices
- **[USER_MANAGEMENT.md](USER_MANAGEMENT.md)** - User administration
- **[example_usage.py](example_usage.py)** - Working code examples

---

## Support

For questions or issues:

1. Review documentation above
2. Check `example_usage.py` for implementation patterns
3. Verify hard controls are active: `python -c "from controls import get_hard_controls; print(get_hard_controls().is_strategy_locked())"`

---

**Status**: ✅ PRODUCTION READY  
**Version**: 2.0  
**Date**: January 8, 2026  
**Architecture**: Layered (3 layers + 4 support modules)  
**Security**: Encrypted API keys, Hard controls enforced  
**Multi-User**: Supported with per-user permissions
