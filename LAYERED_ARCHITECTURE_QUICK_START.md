# NIJA Layered Architecture - Quick Reference

## 🚀 Quick Start

### 1. Setup Encryption Key (One Time)
```bash
# Generate encryption key
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Store in environment
export NIJA_ENCRYPTION_KEY="<your-generated-key>"
```

### 2. Add a New User
```python
from auth import get_user_manager, get_api_key_manager
from execution import UserPermissions, get_permission_validator

# Create user account
user_mgr = get_user_manager()
user = user_mgr.create_user("john", "john@example.com", "pro")

# Store encrypted API keys
api_mgr = get_api_key_manager()
api_mgr.store_user_api_key("john", "coinbase", "api_key", "api_secret")

# Set permissions
perms = UserPermissions(
    user_id="john",
    allowed_pairs=["BTC-USD", "ETH-USD"],
    max_position_size_usd=200.0,
    max_positions=5
)
get_permission_validator().register_user(perms)
```

### 3. Execute Trade
```python
from execution.broker_adapter import SecureBrokerAdapter

adapter = SecureBrokerAdapter("john", "coinbase")
result = adapter.place_order("BTC-USD", "buy", 100.0)
```

## 📊 Architecture Layers

```
┌──────────────────────────────────────┐
│  Layer 3: UI (PUBLIC)                │  Users see this
│  - Dashboard, Stats, Settings        │
└──────────────────────────────────────┘
                ↓ (validates permissions)
┌──────────────────────────────────────┐
│  Layer 2: Execution (LIMITED)        │  Admins configure
│  - Brokers, Permissions, Orders      │
└──────────────────────────────────────┘
                ↓ (protected access)
┌──────────────────────────────────────┐
│  Layer 1: Core (PRIVATE)             │  Never exposed
│  - Strategy, Risk, AI                │
└──────────────────────────────────────┘
```

## 🔒 Hard Controls (Cannot Be Bypassed)

| Control | Limit | Enforced By |
|---------|-------|-------------|
| Min Position | 2% of account | `controls.validate_position_size()` |
| Max Position | 10% of account | `controls.validate_position_size()` |
| Daily Trades | 50 per user | `controls.check_daily_trade_limit()` |
| API Errors | 5 = auto-disable | `controls.record_api_error()` |
| Strategy Lock | Always locked | `controls.is_strategy_locked()` |

## 🛑 Emergency Controls

### Global Kill Switch (All Users)
```python
from controls import get_hard_controls
controls = get_hard_controls()

# Emergency stop ALL trading
controls.trigger_global_kill_switch("Market emergency")

# Resume (manual intervention required)
controls.reset_global_kill_switch()
```

### User Kill Switch (Single User)
```python
# Stop user trading
controls.trigger_user_kill_switch("john", "Daily loss exceeded")

# Resume user
controls.reset_user_kill_switch("john")
```

## 📚 Full Documentation

| File | Purpose |
|------|---------|
| **ARCHITECTURE.md** | Complete technical overview |
| **SECURITY.md** | Security model and best practices |
| **USER_MANAGEMENT.md** | User administration guide |
| **example_usage.py** | 7 working code examples |
| **validate_requirements.py** | Automated validation |

---

**Quick Reference Version**: 1.0  
**Last Updated**: January 8, 2026  
**For**: NIJA Layered Architecture v2.0
