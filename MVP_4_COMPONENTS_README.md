# NIJA Platform - 4-Component MVP Implementation

## Overview

This document describes the implementation of the 4 core components required for the NIJA multi-user trading platform. These components form the foundation for a secure, scalable, and production-ready trading system.

---

## 1️⃣ Secure Vault (NON-NEGOTIABLE)

### Purpose
Bank-grade API key protection with zero-trust credential handling.

### Implementation
**Location**: `/vault/__init__.py`

### Features
- ✅ **AES-256 Encryption** via Fernet (cryptography library)
- ✅ **SQLite Database** with encrypted credential storage
- ✅ **API Key Rotation** support with re-encryption
- ✅ **Audit Logging** for all credential access
- ✅ **Zero-Trust Design** - credentials NEVER stored in plain text
- ✅ **Regulatory Compliance** ready

### Database Schema
```sql
-- Encrypted credentials storage
CREATE TABLE credentials (
    id INTEGER PRIMARY KEY,
    user_id TEXT NOT NULL,
    broker TEXT NOT NULL,
    api_key_encrypted TEXT NOT NULL,
    api_secret_encrypted TEXT NOT NULL,
    additional_params_encrypted TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    rotation_count INTEGER DEFAULT 0,
    UNIQUE(user_id, broker)
);

-- Audit trail for security compliance
CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY,
    user_id TEXT NOT NULL,
    broker TEXT NOT NULL,
    action TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    ip_address TEXT,
    success INTEGER NOT NULL
);

-- Key rotation history
CREATE TABLE key_rotation_history (
    id INTEGER PRIMARY KEY,
    old_key_hash TEXT NOT NULL,
    new_key_hash TEXT NOT NULL,
    rotated_at TEXT NOT NULL,
    credentials_count INTEGER NOT NULL
);
```

### Usage Example
```python
from vault import get_vault

# Initialize vault (auto-creates encryption key if not provided)
vault = get_vault()

# Store encrypted credentials
vault.store_credentials(
    user_id="user_123",
    broker="coinbase",
    api_key="my_api_key",
    api_secret="my_api_secret",
    ip_address="192.168.1.1"  # For audit logging
)

# Retrieve decrypted credentials
creds = vault.get_credentials(user_id="user_123", broker="coinbase")
print(creds['api_key'])  # Decrypted on-the-fly

# View audit log
audit = vault.get_audit_log(user_id="user_123")
```

### Environment Configuration
```bash
# Set encryption key (store this securely!)
export VAULT_ENCRYPTION_KEY="your-generated-key"
```

### Security Guarantees
1. ✅ **Encryption at Rest**: All credentials encrypted with AES-256
2. ✅ **Audit Trail**: Every access logged with IP and timestamp
3. ✅ **Key Rotation**: Re-encrypt all data with new key
4. ✅ **No Plain Text**: Credentials never touch disk unencrypted
5. ✅ **Database Isolation**: Separate from user data

---

## 2️⃣ User Authentication & Identity

### Purpose
User isolation, permission enforcement, session control, and multi-user safety.

### Implementation
**Location**: `/auth/user_database.py`

### Features
- ✅ **Database-Backed Storage** (SQLite/PostgreSQL ready)
- ✅ **Argon2 Password Hashing** (OWASP recommended)
- ✅ **Session Management** with expiration
- ✅ **Login History Tracking** for security monitoring
- ✅ **JWT Token Authentication**
- ✅ **User Enable/Disable** (soft delete)
- ✅ **Email Verification** ready

### Database Schema
```sql
-- User accounts
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    user_id TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,  -- Argon2 hash
    subscription_tier TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_login TEXT,
    enabled INTEGER DEFAULT 1,
    email_verified INTEGER DEFAULT 0
);

-- Active sessions
CREATE TABLE sessions (
    id INTEGER PRIMARY KEY,
    session_id TEXT UNIQUE NOT NULL,
    user_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    ip_address TEXT,
    user_agent TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- Security monitoring
CREATE TABLE login_history (
    id INTEGER PRIMARY KEY,
    user_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    ip_address TEXT,
    success INTEGER NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);
```

### Usage Example
```python
from auth.user_database import get_user_database

user_db = get_user_database()

# Create new user (password auto-hashed with Argon2)
user_db.create_user(
    user_id="user_123",
    email="user@example.com",
    password="secure_password",
    subscription_tier="pro"
)

# Verify password (uses Argon2)
if user_db.verify_password("user_123", "secure_password"):
    print("Login successful!")

# Get user profile
profile = user_db.get_user("user_123")
print(profile['subscription_tier'])  # "pro"
```

### Subscription Tiers
- **Basic**: $100 max position, 3 positions, shared infrastructure
- **Pro**: $1,000 max position, 10 positions, priority infrastructure
- **Enterprise**: $10,000 max position, unlimited positions, dedicated servers

### API Endpoints
```bash
# Register new user
POST /api/auth/register
{
    "email": "user@example.com",
    "password": "secure_password",
    "subscription_tier": "pro"
}

# Login
POST /api/auth/login
{
    "email": "user@example.com",
    "password": "secure_password"
}

# Returns JWT token
{
    "access_token": "eyJ0eXAi...",
    "user_id": "user_123",
    "email": "user@example.com",
    "subscription_tier": "pro"
}
```

---

## 3️⃣ Execution Router (The Money Engine)

### Purpose
Routes trades from many users → one trading engine → many brokers with load control, fault tolerance, and latency optimization.

### Implementation
**Location**: `/core/enhanced_execution_router.py`

### Features
- ✅ **Load Balancing** across multiple brokers
- ✅ **Health Monitoring** with real-time status
- ✅ **Circuit Breaker Pattern** for fault tolerance
- ✅ **Automatic Failover** to backup brokers
- ✅ **Latency Tracking** and optimization
- ✅ **Request Queuing** for load control
- ✅ **Priority-Based Routing** by subscription tier

### Architecture
```
User Request → Enhanced Router → Health Check → Best Broker Selection
                    ↓
            Circuit Breaker Protection
                    ↓
            Execute on Selected Broker
                    ↓
        Record Metrics & Update Health Status
                    ↓
            Return Result or Failover
```

### Circuit Breaker States
1. **CLOSED**: Normal operation, requests pass through
2. **OPEN**: Broker failing, block all requests
3. **HALF_OPEN**: Testing if broker recovered

### Broker Health Status
- **HEALTHY**: >80% success rate, normal latency
- **DEGRADED**: 50-80% success rate, elevated latency
- **UNHEALTHY**: <50% success rate
- **CIRCUIT_OPEN**: Circuit breaker tripped

### Usage Example
```python
from core.enhanced_execution_router import get_enhanced_router

router = get_enhanced_router()

# Register brokers
router.register_broker("coinbase")
router.register_broker("kraken")
router.register_broker("binance")

# Execute with automatic failover
def execute_trade(broker, user_id, symbol, quantity):
    # Your trading logic here
    return f"Executed on {broker}"

result = router.execute_with_failover(
    user_id="user_123",
    brokers=["coinbase", "kraken", "binance"],
    execute_func=execute_trade,
    symbol="BTC-USD",
    quantity=0.1
)

# Get broker health stats
stats = router.get_broker_stats()
# {
#   "coinbase": {
#     "success_rate": 95.5,
#     "average_latency_ms": 245,
#     "health": "healthy",
#     "circuit_state": "CLOSED"
#   }
# }
```

### Performance Benefits
- **Load Distribution**: Spread requests across multiple brokers
- **Fault Tolerance**: Auto-failover prevents downtime
- **Latency Optimization**: Route to fastest broker
- **System Stability**: Circuit breakers prevent cascade failures

---

## 4️⃣ Minimal Mobile UI (MVP)

### Purpose
Simple, mobile-first interface for essential trading controls.

### Implementation
**Location**: `/frontend/templates/index.html`

### MVP Features (ONLY)
✅ **Connect Exchange** - Add/remove broker credentials
✅ **See Balance** - Real-time account balance display
✅ **See Positions** - Active positions with P&L
✅ **See Profit** - Total P&L and win rate stats
✅ **On/Off Toggle** - Start/stop trading with one tap

### UI Components
```
┌─────────────────────────────────┐
│  🤖 NIJA                        │  Navigation
├─────────────────────────────────┤
│  Trading Control                │
│  ●─────────O  [ON/OFF Toggle]   │  ← Key Feature
│  Status: Trading ON             │
├─────────────────────────────────┤
│  Balance: $5,234.56            │  Stats Grid
│  P&L: +$234.56 (+4.7%)         │
│  Win Rate: 65%                  │
│  Positions: 3                   │
├─────────────────────────────────┤
│  Active Positions               │
│  BTC-USD: +2.3% ($45.67)       │  Position List
│  ETH-USD: -1.1% (-$23.45)      │
├─────────────────────────────────┤
│  Brokers                        │
│  ✓ Coinbase                     │  Exchange List
│  ✓ Kraken                       │
└─────────────────────────────────┘
```

### Mobile-First Design
- ✅ Responsive grid layout
- ✅ Touch-optimized controls
- ✅ Large tap targets (44x44px minimum)
- ✅ Progressive Web App (PWA) ready
- ✅ Works offline (cached assets)

### API Integration
```javascript
// Toggle trading on/off
async function handleTradingToggle() {
    const toggle = document.getElementById('trading-toggle');
    const action = toggle.checked ? 'start' : 'stop';

    await apiRequest('/api/trading/control', {
        method: 'POST',
        body: JSON.stringify({ action })
    });
}
```

### What's NOT in MVP
❌ Advanced charts
❌ Strategy configuration
❌ Backtesting interface
❌ Social/sharing features
❌ Notifications (push)

*Focus: Control trading, monitor results. That's it.*

---

## System Integration

### How Components Work Together

```
┌─────────────────────────────────────────────────────────┐
│                    Mobile UI (Layer 4)                   │
│  - Connect Exchange  - Balance  - Positions  - On/Off   │
└───────────────────┬─────────────────────────────────────┘
                    │ HTTPS/JWT
┌───────────────────▼─────────────────────────────────────┐
│            FastAPI Backend (API Gateway)                 │
│  - User Auth  - Broker Management  - Trading Control    │
└───────────────────┬─────────────────────────────────────┘
                    │
        ┌───────────┼───────────┐
        │           │           │
┌───────▼────┐ ┌───▼────┐ ┌───▼──────────┐
│   Secure   │ │  User  │ │  Execution   │
│   Vault    │ │  Auth  │ │   Router     │
│  (Layer 1) │ │(Layer2)│ │  (Layer 2)   │
└────────────┘ └────────┘ └──────┬───────┘
                                  │
                  ┌───────────────┼───────────────┐
                  │               │               │
            ┌─────▼────┐    ┌────▼─────┐   ┌────▼─────┐
            │ Coinbase │    │  Kraken  │   │ Binance  │
            └──────────┘    └──────────┘   └──────────┘
```

### Request Flow Example
1. User toggles "Trading ON" in mobile UI
2. UI sends POST /api/trading/control with JWT token
3. FastAPI validates JWT, extracts user_id
4. Router selects best broker based on health/latency
5. Vault retrieves encrypted credentials for user+broker
6. Execute trade with circuit breaker protection
7. Record metrics and update broker health
8. Return result to UI

---

## Deployment

### Prerequisites
```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export VAULT_ENCRYPTION_KEY="your-generated-key"
export JWT_SECRET_KEY="your-jwt-secret"
export DATABASE_URL="sqlite:///nija.db"  # Or PostgreSQL URL
```

### Running the Platform
```bash
# Start FastAPI backend
uvicorn fastapi_backend:app --host 0.0.0.0 --port 8000

# Or with Gunicorn for production
gunicorn fastapi_backend:app -w 4 -k uvicorn.workers.UvicornWorker
```

### Docker Deployment
```bash
# Build image
docker build -t nija-platform .

# Run container
docker run -d \
  -p 8000:8000 \
  -e VAULT_ENCRYPTION_KEY=$VAULT_ENCRYPTION_KEY \
  -e JWT_SECRET_KEY=$JWT_SECRET_KEY \
  nija-platform
```

---

## Security Checklist

### Production Requirements
- [ ] Set unique VAULT_ENCRYPTION_KEY (never commit to git)
- [ ] Set unique JWT_SECRET_KEY (never commit to git)
- [ ] Enable HTTPS/TLS for all API requests
- [ ] Configure CORS for production domains only
- [ ] Set up database backups (vault.db, users.db)
- [ ] Monitor audit logs regularly
- [ ] Implement rate limiting on auth endpoints
- [ ] Set up intrusion detection (fail2ban)
- [ ] Configure firewall rules
- [ ] Enable database encryption at rest

### Compliance
✅ **GDPR Ready**: User data can be exported/deleted
✅ **SOC 2**: Audit logging for all access
✅ **PCI DSS**: No payment card data stored
✅ **CCPA**: User privacy controls in place

---

## Testing

### Test Vault Security
```python
from vault import get_vault

vault = get_vault()

# Test encryption/decryption
vault.store_credentials("test_user", "test_broker", "key123", "secret456")
creds = vault.get_credentials("test_user", "test_broker")
assert creds['api_key'] == "key123"  # Should match
assert creds['api_secret'] == "secret456"

# Test audit logging
audit = vault.get_audit_log("test_user")
assert len(audit) >= 2  # Store + Get
```

### Test User Authentication
```python
from auth.user_database import get_user_database

user_db = get_user_database()

# Test registration and login
user_db.create_user("test_user", "test@example.com", "password123")
assert user_db.verify_password("test_user", "password123") == True
assert user_db.verify_password("test_user", "wrong_password") == False
```

### Test Execution Router
```python
from core.enhanced_execution_router import get_enhanced_router

router = get_enhanced_router()

# Test broker selection
router.register_broker("broker1")
router.register_broker("broker2")

# Simulate successful execution
router.record_execution("broker1", success=True, latency_ms=200)
router.record_execution("broker2", success=True, latency_ms=400)

best = router.select_best_broker("user_123")
assert best == "broker1"  # Should select lowest latency
```

---

## Monitoring

### Key Metrics to Track
1. **Vault**: Credential access rate, failed decryption attempts
2. **Authentication**: Login success rate, failed login attempts
3. **Router**: Broker health, average latency, failover rate
4. **UI**: Page load time, API response time

### Health Check Endpoint
```bash
curl https://your-domain.com/health

# Response
{
    "status": "healthy",
    "timestamp": "2026-01-27T20:00:00Z",
    "components": {
        "vault": "operational",
        "user_db": "operational",
        "router": "operational"
    }
}
```

---

## Support & Documentation

### Additional Resources
- [Secure Vault Documentation](vault/__init__.py)
- [User Database Documentation](auth/user_database.py)
- [Execution Router Documentation](core/enhanced_execution_router.py)
- [API Documentation](http://localhost:8000/api/docs)

### Contact
For questions or issues, refer to the main [README.md](README.md)

---

## Version History

### v1.0.0 - MVP Launch (January 27, 2026)
- ✅ Secure Vault with AES-256 encryption
- ✅ User Authentication with Argon2
- ✅ Enhanced Execution Router
- ✅ Minimal Mobile UI
- ✅ FastAPI Backend Integration
