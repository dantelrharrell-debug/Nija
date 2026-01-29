# NIJA Platform Architecture - Complete System Design

**Version:** 2.0
**Last Updated:** January 29, 2026
**Status:** ✅ Production-Ready Architecture

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [System Overview](#system-overview)
3. [Architecture Layers](#architecture-layers)
4. [Backend Structure](#backend-structure)
5. [API Routes](#api-routes)
6. [Dashboard Layout](#dashboard-layout)
7. [Subscription Logic](#subscription-logic)
8. [Scaling Blueprint](#scaling-blueprint)
9. [Security Architecture](#security-architecture)
10. [Deployment Strategy](#deployment-strategy)
11. [Monitoring & Observability](#monitoring--observability)

---

## Executive Summary

NIJA is an **enterprise-grade autonomous cryptocurrency trading platform** that combines:
- **Proprietary AI-powered trading strategies** (APEX V7.2, Meta-AI, MMIN, GMIG)
- **Multi-user SaaS architecture** with subscription tiers
- **Multi-exchange support** (Coinbase, Kraken, Binance, OKX, Alpaca)
- **Advanced execution intelligence** (slippage modeling, smart order routing)
- **Real-time monitoring** via web and mobile dashboards

### Key Capabilities
- 🤖 **Autonomous Trading**: Scans 732+ markets every 2.5 minutes
- 🧠 **AI Intelligence**: Meta-learning, cross-market correlation, macro regime detection
- 📱 **Multi-Platform**: Web dashboard, iOS/Android apps, API access
- 🔐 **Enterprise Security**: Encrypted credentials, JWT auth, role-based access
- 📊 **Real-Time Analytics**: Live P&L, position tracking, performance metrics
- 💰 **SaaS Monetization**: Free, Basic, Pro, Enterprise tiers with Stripe integration

---

## System Overview

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     CLIENT APPLICATIONS                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │ Web Dashboard│  │  Mobile Apps │  │  API Clients │          │
│  │  (React.js)  │  │ (React Native│  │   (REST)     │          │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘          │
└─────────┼──────────────────┼──────────────────┼──────────────────┘
          │                  │                  │
          └──────────────────┴──────────────────┘
                             │
                    HTTPS/WSS (TLS 1.3)
                             │
┌─────────────────────────────▼────────────────────────────────────┐
│                     API GATEWAY LAYER                             │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  Kong/Nginx API Gateway                                    │  │
│  │  • SSL Termination                                         │  │
│  │  • JWT Authentication                                      │  │
│  │  • Rate Limiting (tier-based)                             │  │
│  │  • Request Routing                                         │  │
│  │  • CORS Policy Enforcement                                │  │
│  └────────────────────────────────────────────────────────────┘  │
└─────────────────────────────▼────────────────────────────────────┘
          ┌───────────────────┴───────────────────┐
          │                                       │
┌─────────▼───────────┐                ┌─────────▼───────────┐
│   PUBLIC APIs       │                │   ADMIN APIs        │
│   (FastAPI)         │                │   (FastAPI)         │
│                     │                │                     │
│  • Dashboard API    │                │  • User Management  │
│  • Trading API      │                │  • System Control   │
│  • Analytics API    │                │  • Monitoring       │
│  • User Settings    │                │  • Audit Logs       │
└─────────┬───────────┘                └─────────┬───────────┘
          │                                      │
          └──────────────────┬───────────────────┘
                             │
┌─────────────────────────────▼────────────────────────────────────┐
│                    BUSINESS LOGIC LAYER                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │ User Control │  │Subscription  │  │ Permission   │          │
│  │   Service    │  │   Engine     │  │  Validator   │          │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘          │
└─────────┼──────────────────┼──────────────────┼──────────────────┘
          │                  │                  │
          └──────────────────┴──────────────────┘
                             │
┌─────────────────────────────▼────────────────────────────────────┐
│                     EXECUTION LAYER                               │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  Execution Router & Trade Isolation                        │  │
│  │  • Per-user execution contexts                             │  │
│  │  • Broker adapter factory                                  │  │
│  │  • Order routing & validation                             │  │
│  │  • Position tracking                                       │  │
│  └────────────────────────────────────────────────────────────┘  │
└─────────────────────────────▼────────────────────────────────────┘
          ┌───────────────────┴───────────────────┐
          │                                       │
┌─────────▼───────────┐                ┌─────────▼───────────┐
│   CORE BRAIN        │                │  BROKER ADAPTERS    │
│   (PRIVATE)         │                │  (MULTI-EXCHANGE)   │
│                     │                │                     │
│  • APEX Strategy    │───signals──▶   │  • Coinbase         │
│  • Meta-AI Engine   │                │  • Kraken           │
│  • MMIN System      │                │  • Binance          │
│  • GMIG System      │                │  • OKX              │
│  • Risk Manager     │                │  • Alpaca           │
│  • Indicators       │                │  • Paper Trading    │
└─────────────────────┘                └─────────┬───────────┘
                                                 │
                                       ┌─────────▼───────────┐
                                       │   EXCHANGES         │
                                       │  (External APIs)    │
                                       └─────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                      DATA LAYER                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │ PostgreSQL   │  │    Redis     │  │  TimescaleDB │          │
│  │              │  │              │  │              │          │
│  │ • Users      │  │ • Sessions   │  │ • Trade Data │          │
│  │ • Trades     │  │ • Cache      │  │ • Metrics    │          │
│  │ • Positions  │  │ • Job Queue  │  │ • Analytics  │          │
│  │ • Subscript. │  │ • PubSub     │  │ • Time Series│          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    INFRASTRUCTURE LAYER                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │   HashiCorp  │  │ Prometheus + │  │   Logging    │          │
│  │     Vault    │  │   Grafana    │  │  (ELK Stack) │          │
│  │              │  │              │  │              │          │
│  │ • API Keys   │  │ • Metrics    │  │ • Audit Logs │          │
│  │ • Secrets    │  │ • Dashboards │  │ • Error Logs │          │
│  │ • Rotation   │  │ • Alerts     │  │ • Trade Logs │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
└─────────────────────────────────────────────────────────────────┘
```

---

## Architecture Layers

### Layer 1: Core Brain (PRIVATE)

**Purpose:** Contains proprietary trading algorithms and decision-making logic.

**Location:** `/core/` and `/bot/`

**Components:**
- **APEX V7.2 Strategy**: Dual RSI system (RSI_9 + RSI_14)
- **Meta-AI Engine**: Self-evolving strategy optimization
- **MMIN (Multi-Market Intelligence)**: Cross-asset learning
- **GMIG (Global Macro Intelligence)**: Macro regime detection
- **Execution Intelligence**: Slippage modeling, smart routing
- **Risk Manager**: Position sizing, stop-loss, profit targets
- **Indicators Library**: Technical analysis (RSI, MACD, Bollinger, etc.)

**Access Control:**
```python
# NEVER exposed to users
# Only accessible via execution layer
from core import verify_core_access

verify_core_access(__name__)  # Raises PermissionError if unauthorized
```

**Key Files:**
- `bot/nija_apex_strategy_v72_upgrade.py` - Main strategy
- `bot/meta_ai/` - AI evolution engine
- `bot/mmin/` - Multi-market intelligence
- `bot/gmig/` - Global macro intelligence
- `bot/execution_intelligence.py` - Execution optimization
- `bot/risk_manager.py` - Risk management

---

### Layer 2: Execution Engine (LIMITED)

**Purpose:** Handles broker connections and order execution with user-specific permissions.

**Location:** `/execution/` and `/bot/broker_*.py`

**Components:**

#### 2.1 Execution Router
Routes trades to appropriate broker adapters with user isolation.

```python
from execution import ExecutionRouter

router = ExecutionRouter()
result = router.route_order(
    user_id="user_123",
    broker="coinbase",
    symbol="BTC-USD",
    side="buy",
    size_usd=100.0
)
```

#### 2.2 Broker Adapters
Unified interface to multiple exchanges:
- **Coinbase Advanced Trade**
- **Kraken Pro**
- **Binance Futures**
- **OKX**
- **Alpaca (stocks)**
- **Paper Trading** (simulation)

```python
from execution.broker_adapter import SecureBrokerAdapter

adapter = SecureBrokerAdapter(
    user_id="user_123",
    broker_name="coinbase"
)

# Place order (automatically validated)
result = adapter.place_order(
    pair="BTC-USD",
    side="buy",
    size_usd=50.0
)
```

#### 2.3 Permission Validator
Enforces user-specific trading limits.

```python
from execution import UserPermissions, get_permission_validator

# Define user permissions
perms = UserPermissions(
    user_id="user_123",
    allowed_pairs=["BTC-USD", "ETH-USD"],
    max_position_size_usd=100.0,
    max_daily_loss_usd=50.0,
    max_positions=3,
    trade_only=True
)

# Validate trade
validator = get_permission_validator()
valid, error = validator.validate_trade(
    user_id="user_123",
    pair="BTC-USD",
    position_size_usd=50.0
)
```

**Key Files:**
- `execution/broker_adapter.py` - Secure broker wrapper
- `execution/__init__.py` - Permission system
- `bot/broker_manager.py` - Broker management
- `bot/broker_integration.py` - Exchange integrations
- `bot/unified_execution_engine.py` - Unified execution

---

### Layer 3: User Interface (PUBLIC)

**Purpose:** Public-facing interface for monitoring and configuration.

**Location:** `/ui/`, `/frontend/`, `/mobile/`

**Components:**

#### 3.1 Web Dashboard (React.js)
Single-page application for desktop browsers.

**Features:**
- Real-time P&L tracking
- Active positions table
- Performance charts (equity curve, win rate)
- Trade history
- Settings management
- Subscription management

**Tech Stack:**
- React 18
- TypeScript
- TailwindCSS
- Chart.js
- WebSocket for real-time updates

#### 3.2 Mobile Apps (React Native)
Native iOS and Android applications.

**Features:**
- Push notifications for trades
- Biometric authentication
- Real-time updates
- Quick actions (start/stop trading)
- Portfolio overview

**Tech Stack:**
- React Native
- Expo
- Native modules (iOS/Android)

#### 3.3 Dashboard API

```python
from ui import DashboardAPI

dashboard = DashboardAPI()

# Get user statistics
stats = dashboard.get_user_stats("user_123")
# Returns: {
#   'total_trades': 150,
#   'win_rate': 0.68,
#   'total_pnl': 2340.50,
#   'active_positions': 3,
#   'total_volume': 45000.00
# }

# Get active positions
positions = dashboard.get_positions("user_123")

# Get trade history
history = dashboard.get_trade_history(
    user_id="user_123",
    limit=50,
    offset=0
)
```

**Key Files:**
- `ui/__init__.py` - Dashboard API
- `frontend/` - Web dashboard (React)
- `mobile/` - Mobile apps (React Native)
- `bot/user_dashboard_api.py` - User data API

---

### Layer 4: Authentication & Authorization

**Purpose:** Secure user authentication and API credential management.

**Location:** `/auth/`

**Components:**

#### 4.1 User Manager
Manages user accounts and authentication.

```python
from auth import get_user_manager

user_mgr = get_user_manager()

# Create user
user_mgr.create_user(
    user_id="user_123",
    email="user@example.com",
    password_hash=hash_password("secure_password"),
    subscription_tier="pro"
)

# Authenticate user
authenticated, user = user_mgr.authenticate(
    email="user@example.com",
    password="secure_password"
)

# Generate JWT token
token = user_mgr.generate_jwt_token(user_id="user_123")
```

#### 4.2 API Key Manager
Securely stores user exchange API keys.

```python
from auth import get_api_key_manager

api_manager = get_api_key_manager()

# Store encrypted API keys
api_manager.store_user_api_key(
    user_id="user_123",
    broker="coinbase",
    api_key="user_api_key",
    api_secret="user_api_secret",
    additional_params={'org_id': 'org_123'}
)

# Retrieve decrypted credentials (internal only)
creds = api_manager.get_user_api_key("user_123", "coinbase")
```

**Security Features:**
- Fernet symmetric encryption for API keys
- JWT-based session management
- Password hashing with bcrypt
- API key rotation support
- Audit logging

**Key Files:**
- `auth/__init__.py` - Auth system
- `auth/user_database.py` - User data storage

---

### Layer 5: Configuration Management

**Purpose:** Manage user-specific trading preferences.

**Location:** `/config/`

**Components:**

```python
from config import get_config_manager

config_mgr = get_config_manager()

# Get user configuration
user_config = config_mgr.get_user_config("user_123")

# Update configuration
config_mgr.update_user_config("user_123", {
    'max_position_size': 150.0,
    'max_concurrent_positions': 5,
    'risk_level': 'medium',
    'allowed_pairs': ['BTC-USD', 'ETH-USD'],
    'notifications_enabled': True
})
```

**Default Configuration:**
- `max_position_size`: $100
- `max_concurrent_positions`: 3
- `max_daily_loss_pct`: 10%
- `risk_level`: 'medium'
- `allowed_pairs`: All (null = all allowed)

**Key Files:**
- `config/__init__.py` - Config management
- `.env.example` - Configuration template

---

### Layer 6: Hard Controls (SAFETY)

**Purpose:** Enforce mandatory safety limits.

**Location:** `/controls/`

**Components:**

```python
from controls import get_hard_controls

controls = get_hard_controls()

# Validate position size (enforces 2-10% rule)
valid, error = controls.validate_position_size(
    user_id="user_123",
    position_size_usd=50.0,
    account_balance=1000.0
)

# Trigger kill switch
controls.trigger_user_kill_switch(
    user_id="user_123",
    reason="Excessive losses detected"
)

# Global kill switch (stops ALL trading)
controls.trigger_global_kill_switch(
    reason="Market emergency"
)
```

**Hard Limits:**
- Min position: 2% of account
- Max position: 10% of account
- Max daily trades: 50 per user
- Auto-disable after 5 API errors
- Max drawdown: 20%

**Kill Switches:**
- **Global**: Stops all trading across all users
- **Per-User**: Stops trading for specific user
- **Auto-Disable**: Triggered by errors or losses

**Key Files:**
- `controls/__init__.py` - Safety controls

---

## Backend Structure

### Directory Organization

```
/
├── api_gateway.py              # Main API gateway (FastAPI)
├── api_server.py               # Legacy API server
├── fastapi_backend.py          # FastAPI backend
├── user_control.py             # User control backend
├── monetization_engine.py      # Subscription & billing
│
├── core/                       # Layer 1: Private strategy logic
│   └── (strategy files - private)
│
├── execution/                  # Layer 2: Execution engine
│   ├── __init__.py            # Execution router
│   └── broker_adapter.py      # Secure broker wrapper
│
├── ui/                        # Layer 3: User interface
│   ├── __init__.py           # Dashboard API
│   └── (UI components)
│
├── auth/                      # Authentication & API key management
│   ├── __init__.py           # User manager
│   └── user_database.py      # User data storage
│
├── config/                    # User configuration
│   └── __init__.py           # Config manager
│
├── controls/                  # Hard safety controls
│   └── __init__.py           # Kill switches & limits
│
├── database/                  # Database layer
│   ├── __init__.py
│   ├── db_connection.py      # PostgreSQL connection
│   └── models.py             # SQLAlchemy models
│
├── bot/                       # Core trading engine
│   ├── nija_apex_strategy_v72_upgrade.py  # Main strategy
│   ├── broker_manager.py                   # Broker management
│   ├── broker_integration.py               # Exchange integrations
│   ├── execution_intelligence.py           # Execution optimization
│   ├── risk_manager.py                     # Risk management
│   ├── meta_ai/                            # Meta-AI engine
│   ├── mmin/                               # Multi-market intelligence
│   ├── gmig/                               # Global macro intelligence
│   └── (other modules)
│
├── frontend/                  # Web dashboard (React)
│   ├── static/
│   └── templates/
│
├── mobile/                    # Mobile apps (React Native)
│   ├── ios/
│   ├── android/
│   └── (app source)
│
├── scripts/                   # Utility scripts
│   └── (various scripts)
│
├── k8s/                       # Kubernetes manifests
│   ├── base/
│   └── components/
│
├── docker-compose.yml         # Local development stack
├── Dockerfile.api             # API container
├── Dockerfile.dashboard       # Dashboard container
├── Dockerfile.gateway         # Gateway container
│
└── requirements.txt           # Python dependencies
```

### Service Architecture

#### Microservices Breakdown

```
┌─────────────────────────────────────────────────────────────┐
│                    NIJA Platform Services                    │
└─────────────────────────────────────────────────────────────┘

1. API Gateway Service (Port 8000)
   - Entry point for all API requests
   - JWT authentication
   - Rate limiting
   - Request routing

2. Trading Engine Service (Port 8001)
   - Core APEX strategy execution
   - Market scanning (732+ pairs)
   - Signal generation
   - Trade execution

3. Dashboard API Service (Port 8002)
   - User statistics
   - Position tracking
   - Performance analytics
   - Settings management

4. Subscription Service (Port 8003)
   - Stripe integration
   - Tier management
   - Usage tracking
   - Billing

5. WebSocket Service (Port 8004)
   - Real-time position updates
   - Trade notifications
   - Market data streaming
   - Chat support

6. Webhook Service (Port 5000)
   - TradingView webhooks
   - Payment webhooks (Stripe)
   - Exchange webhooks

7. Admin API Service (Port 8005)
   - User management
   - System monitoring
   - Kill switches
   - Audit logs
```

### Database Schema

See [DATABASE_SCHEMA.md](./DATABASE_SCHEMA.md) for detailed schema.

**Core Tables:**
- `users` - User accounts
- `subscriptions` - Subscription data
- `api_keys` - Encrypted exchange credentials
- `trades` - Trade history
- `positions` - Active positions
- `transactions` - Payment history
- `audit_logs` - System audit trail

---

## API Routes

See [API_ROUTES.md](./API_ROUTES.md) for complete API specification.

### Authentication Endpoints

```
POST   /api/v1/auth/register        - Register new user
POST   /api/v1/auth/login           - User login (returns JWT)
POST   /api/v1/auth/logout          - User logout
POST   /api/v1/auth/refresh         - Refresh JWT token
POST   /api/v1/auth/reset-password  - Password reset request
PUT    /api/v1/auth/change-password - Change password
```

### Trading Endpoints

```
POST   /api/v1/trading/start        - Start trading bot
POST   /api/v1/trading/stop         - Stop trading bot
GET    /api/v1/trading/status       - Get bot status
POST   /api/v1/trading/emergency-stop - Emergency kill switch
```

### Account Endpoints

```
GET    /api/v1/account/balance      - Get account balance
GET    /api/v1/account/positions    - Get active positions
GET    /api/v1/account/history      - Get trade history
GET    /api/v1/account/performance  - Get performance metrics
GET    /api/v1/account/stats        - Get trading statistics
```

### Configuration Endpoints

```
GET    /api/v1/config/settings      - Get user settings
PUT    /api/v1/config/settings      - Update settings
GET    /api/v1/config/brokers       - Get configured brokers
POST   /api/v1/config/brokers       - Add broker API keys
DELETE /api/v1/config/brokers/:id   - Remove broker
```

### Subscription Endpoints

```
GET    /api/v1/subscription/plans   - Get available plans
GET    /api/v1/subscription/current - Get current subscription
POST   /api/v1/subscription/upgrade - Upgrade subscription
POST   /api/v1/subscription/cancel  - Cancel subscription
GET    /api/v1/subscription/usage   - Get usage statistics
```

### Admin Endpoints (Protected)

```
GET    /api/v1/admin/users          - List all users
GET    /api/v1/admin/users/:id      - Get user details
PUT    /api/v1/admin/users/:id      - Update user
DELETE /api/v1/admin/users/:id      - Delete user
POST   /api/v1/admin/kill-switch    - Trigger global kill switch
GET    /api/v1/admin/metrics        - System metrics
GET    /api/v1/admin/audit-logs     - Audit logs
```

### WebSocket Endpoints

```
WS     /ws/positions                - Real-time position updates
WS     /ws/trades                   - Real-time trade notifications
WS     /ws/market-data              - Live market data
WS     /ws/notifications            - General notifications
```

---

## Dashboard Layout

See [DASHBOARD_DESIGN.md](./DASHBOARD_DESIGN.md) for detailed UI/UX specification.

### Web Dashboard Components

```
┌─────────────────────────────────────────────────────────────┐
│  HEADER                                                      │
│  [NIJA Logo]  Dashboard  Trading  Analytics  Settings  [👤] │
└─────────────────────────────────────────────────────────────┘
│
│ ┌─────────────────────────────────────────────────────────┐
│ │  OVERVIEW CARDS                                         │
│ │                                                         │
│ │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐│
│ │  │ Balance  │  │   P&L    │  │ Win Rate │  │ Active  ││
│ │  │ $10,450  │  │ +$1,234  │  │   68%    │  │ Trades  ││
│ │  │  ▲ 2.5%  │  │  ▲ 15%   │  │  ▲ 3%   │  │    3    ││
│ │  └──────────┘  └──────────┘  └──────────┘  └─────────┘│
│ └─────────────────────────────────────────────────────────┘
│
│ ┌─────────────────────────────────────────────────────────┐
│ │  EQUITY CURVE CHART                                     │
│ │  [Interactive line chart showing account growth]        │
│ │  $12k ┤                                        ╭──      │
│ │       │                              ╭────────╯        │
│ │  $10k ┤                     ╭────────╯                 │
│ │       │           ╭─────────╯                          │
│ │   $8k ┤  ╭────────╯                                    │
│ │       └──┴────┴────┴────┴────┴────┴────┴────┴─────    │
│ │        Jan  Feb  Mar  Apr  May  Jun  Jul  Aug  Sep    │
│ └─────────────────────────────────────────────────────────┘
│
│ ┌─────────────────────────────────────────────────────────┐
│ │  ACTIVE POSITIONS                                       │
│ │  ┌─────┬─────────┬──────┬──────┬──────┬────────┬─────┐│
│ │  │ ID  │ Symbol  │ Side │ Size │  P&L │ Entry  │ ... ││
│ │  ├─────┼─────────┼──────┼──────┼──────┼────────┼─────┤│
│ │  │ 001 │ BTC-USD │ LONG │ $500 │ +$45 │ 43210  │ ... ││
│ │  │ 002 │ ETH-USD │ LONG │ $300 │ +$28 │ 2345   │ ... ││
│ │  │ 003 │ SOL-USD │ LONG │ $200 │ -$12 │ 98.5   │ ... ││
│ │  └─────┴─────────┴──────┴──────┴──────┴────────┴─────┘│
│ └─────────────────────────────────────────────────────────┘
│
│ ┌─────────────────────────────────────────────────────────┐
│ │  RECENT TRADES                                          │
│ │  [Scrollable list of recent closed trades]             │
│ └─────────────────────────────────────────────────────────┘
│
└─────────────────────────────────────────────────────────────┘
```

### Mobile App Screens

#### 1. Home Screen
- Quick stats cards
- Start/Stop toggle
- Active positions count
- Daily P&L

#### 2. Positions Screen
- List of active positions
- Swipe actions (close position)
- P&L color-coded

#### 3. Analytics Screen
- Mini equity curve
- Win rate chart
- Performance metrics

#### 4. Settings Screen
- Risk preferences
- Notification settings
- Broker connections
- Account settings

---

## Subscription Logic

See [SUBSCRIPTION_SYSTEM.md](./SUBSCRIPTION_SYSTEM.md) for detailed specification.

### Subscription Tiers

```python
FREE_TIER = {
    'name': 'Free',
    'price_monthly': 0,
    'price_yearly': 0,
    'features': [
        'Paper trading only',
        'Basic strategy (APEX V7.2)',
        '1 exchange connection',
        'Community support',
        'Basic analytics'
    ],
    'limits': {
        'max_position_size_usd': 0,  # Paper only
        'max_positions': 3,
        'max_daily_trades': 10,
        'api_calls_per_minute': 10
    }
}

BASIC_TIER = {
    'name': 'Basic',
    'price_monthly': 49,
    'price_yearly': 470,  # ~20% discount
    'features': [
        'Live trading',
        'APEX V7.2 strategy',
        '2 exchange connections',
        'Email support',
        'Standard analytics',
        'Mobile app access'
    ],
    'limits': {
        'max_position_size_usd': 500,
        'max_positions': 5,
        'max_daily_trades': 30,
        'api_calls_per_minute': 30
    }
}

PRO_TIER = {
    'name': 'Pro',
    'price_monthly': 149,
    'price_yearly': 1430,  # ~20% discount
    'features': [
        'All Basic features',
        'Meta-AI optimization',
        'MMIN multi-market intelligence',
        '5 exchange connections',
        'Priority support',
        'Advanced analytics',
        'Custom risk profiles',
        'TradingView integration'
    ],
    'limits': {
        'max_position_size_usd': 2000,
        'max_positions': 10,
        'max_daily_trades': 100,
        'api_calls_per_minute': 100
    }
}

ENTERPRISE_TIER = {
    'name': 'Enterprise',
    'price_monthly': 499,
    'price_yearly': 4790,  # ~20% discount
    'features': [
        'All Pro features',
        'GMIG macro intelligence',
        'Unlimited exchanges',
        'Dedicated support',
        'Custom strategy tuning',
        'API access',
        'White-label option',
        'Multi-account management'
    ],
    'limits': {
        'max_position_size_usd': 10000,
        'max_positions': 50,
        'max_daily_trades': 500,
        'api_calls_per_minute': 500
    }
}
```

### Subscription Flow

```
User Registration
       ↓
14-Day Free Trial (Pro features)
       ↓
Trial Expiration
       ↓
┌──────┴──────┐
│             │
Choose Tier   ↓
       ↓   Downgrade to Free
Enter Payment (Stripe)
       ↓
Active Subscription
       ↓
Usage Tracking
       ↓
Monthly/Yearly Renewal
```

### Stripe Integration

```python
from monetization_engine import SubscriptionEngine
import stripe

stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
sub_engine = SubscriptionEngine()

# Create subscription
subscription = sub_engine.create_subscription(
    user_id="user_123",
    tier="pro",
    interval="monthly",
    payment_method_id="pm_123"
)

# Handle webhook events
@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    event = stripe.Webhook.construct_event(
        payload=await request.body(),
        sig_header=request.headers.get('stripe-signature'),
        secret=os.getenv('STRIPE_WEBHOOK_SECRET')
    )

    if event['type'] == 'invoice.payment_succeeded':
        # Activate subscription
        sub_engine.activate_subscription(event['data']['object'])

    elif event['type'] == 'invoice.payment_failed':
        # Suspend account
        sub_engine.suspend_subscription(event['data']['object'])

    return {'status': 'success'}
```

---

## Scaling Blueprint

See [SCALING_BLUEPRINT.md](./SCALING_BLUEPRINT.md) for detailed scaling strategy.

### Horizontal Scaling

```
┌─────────────────────────────────────────────────────────┐
│               Load Balancer (Nginx/HAProxy)              │
│                    SSL Termination                       │
└────────────────────┬────────────────────────────────────┘
                     │
        ┌────────────┼────────────┐
        │            │            │
┌───────▼───┐  ┌────▼─────┐  ┌──▼───────┐
│  API Pod  │  │ API Pod  │  │ API Pod  │
│  Instance │  │ Instance │  │ Instance │
│     1     │  │     2    │  │     3    │
└───────┬───┘  └────┬─────┘  └──┬───────┘
        │            │            │
        └────────────┼────────────┘
                     │
        ┌────────────┼────────────┐
        │            │            │
┌───────▼───┐  ┌────▼─────┐  ┌──▼───────┐
│  Trading  │  │ Trading  │  │ Trading  │
│  Engine   │  │ Engine   │  │ Engine   │
│  Worker 1 │  │ Worker 2 │  │ Worker 3 │
└───────────┘  └──────────┘  └──────────┘
```

### Vertical Scaling

**Compute Resources:**
- API Gateway: 2 vCPU, 4GB RAM
- Trading Engine: 4 vCPU, 8GB RAM (CPU-intensive)
- Dashboard API: 2 vCPU, 4GB RAM
- Database: 8 vCPU, 16GB RAM, SSD storage

**Auto-scaling Triggers:**
- CPU > 70% for 5 minutes → scale up
- Memory > 80% for 5 minutes → scale up
- Request latency > 500ms → scale up
- Active users > 80% capacity → scale up

### Database Scaling

#### PostgreSQL
- **Read Replicas**: 3 replicas for read queries
- **Connection Pooling**: PgBouncer (max 100 connections per service)
- **Sharding**: Shard by user_id for large datasets

#### Redis
- **Cluster Mode**: 3 master + 3 replica nodes
- **Persistence**: AOF (Append-Only File)
- **Eviction Policy**: allkeys-lru

#### TimescaleDB
- **Time-series Optimization**: Automatic chunking (1-day chunks)
- **Compression**: Enable compression for data > 7 days old
- **Retention**: Keep detailed data for 90 days, aggregated data for 2 years

### Caching Strategy

```
┌─────────────────────────────────────────────────────────┐
│                      Cache Layers                        │
└─────────────────────────────────────────────────────────┘

Level 1: Browser Cache
- Static assets (JS, CSS, images)
- Cache duration: 7 days

Level 2: CDN Cache (Cloudflare)
- API responses (GET only)
- User settings
- Cache duration: 5 minutes

Level 3: Redis Cache
- User sessions (JWT tokens)
- Active positions
- Market data
- Cache duration: 30 seconds - 5 minutes

Level 4: Database Query Cache
- PostgreSQL query cache
- Recent trade history
- User statistics
```

### Load Balancing Strategy

```python
# Round-robin for API requests
api_instances = [
    'api-1.nija.com',
    'api-2.nija.com',
    'api-3.nija.com'
]

# Least-connections for WebSocket
websocket_instances = [
    'ws-1.nija.com',
    'ws-2.nija.com'
]

# User-based sharding for trading engines
def get_trading_engine(user_id: str) -> str:
    shard = hash(user_id) % NUM_TRADING_ENGINES
    return f'trading-engine-{shard}'
```

### Geographic Distribution

```
┌─────────────────────────────────────────────────────────┐
│                  Global Distribution                     │
└─────────────────────────────────────────────────────────┘

Primary Region: US-East (Virginia)
- API Gateway
- Trading Engines
- Database (Master)

Secondary Region: US-West (Oregon)
- API Gateway (failover)
- Database (Read Replica)

Tertiary Region: EU-West (Ireland)
- API Gateway (EU users)
- Database (Read Replica)

Edge Locations (Cloudflare CDN):
- 200+ locations worldwide
- Static asset delivery
- DDoS protection
```

### Performance Targets

```
┌─────────────────────────────────────────────────────────┐
│                  Performance SLAs                        │
└─────────────────────────────────────────────────────────┘

API Response Time:
- p50: < 100ms
- p95: < 300ms
- p99: < 500ms

WebSocket Latency:
- Trade notifications: < 50ms
- Position updates: < 100ms

Database Queries:
- Simple reads: < 10ms
- Complex aggregations: < 100ms

Trade Execution:
- Signal to order: < 500ms
- Order confirmation: < 2s (depends on exchange)

Uptime:
- Target: 99.9% (8.7 hours downtime/year)
- Monitoring: 24/7 automated alerts
```

---

## Security Architecture

### Defense in Depth

```
┌─────────────────────────────────────────────────────────┐
│                 Security Layers                          │
└─────────────────────────────────────────────────────────┘

Layer 1: Network Security
- DDoS protection (Cloudflare)
- WAF (Web Application Firewall)
- IP whitelisting for admin endpoints
- Rate limiting (tier-based)

Layer 2: Authentication & Authorization
- JWT tokens (HS256 signing)
- Refresh token rotation
- Role-based access control (RBAC)
- Multi-factor authentication (optional)

Layer 3: Application Security
- Input validation (Pydantic)
- SQL injection prevention (SQLAlchemy ORM)
- XSS protection (React escaping)
- CSRF tokens for state-changing operations

Layer 4: Data Security
- Encryption at rest (AES-256)
- Encryption in transit (TLS 1.3)
- API key encryption (Fernet)
- Secure credential storage (HashiCorp Vault)

Layer 5: Audit & Monitoring
- Comprehensive audit logging
- Anomaly detection
- Security alerts (Slack, PagerDuty)
- Regular security audits
```

### Encryption

```python
# API Key Encryption (Fernet)
from cryptography.fernet import Fernet

key = Fernet.generate_key()
cipher = Fernet(key)

# Encrypt API key
encrypted_key = cipher.encrypt(api_key.encode())

# Decrypt API key
decrypted_key = cipher.decrypt(encrypted_key).decode()

# Database Encryption (at rest)
# PostgreSQL: pgcrypto extension
# Redis: redis-encryption module

# TLS/SSL (in transit)
# All HTTPS traffic uses TLS 1.3
# Certificate management: Let's Encrypt
```

### Rate Limiting

```python
from fastapi import FastAPI, Request
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app = FastAPI()
app.state.limiter = limiter

# Tier-based rate limits
@app.get("/api/v1/account/balance")
@limiter.limit("30/minute")  # Basic tier
async def get_balance(request: Request):
    # Check user tier
    tier = get_user_tier(request)

    if tier == "pro":
        # 100/minute for Pro
        pass
    elif tier == "enterprise":
        # 500/minute for Enterprise
        pass

    return {"balance": 10000.0}
```

---

## Deployment Strategy

### Development Environment

```bash
# Local development with Docker Compose
docker-compose up -d

# Services:
# - PostgreSQL (localhost:5432)
# - Redis (localhost:6379)
# - API Gateway (localhost:8000)
# - Dashboard (localhost:3000)

# Hot reload enabled for development
```

### Staging Environment

```bash
# Kubernetes cluster on Railway/Render
kubectl apply -f k8s/staging/

# Features:
# - Mirrors production architecture
# - Uses separate database
# - Automated testing
# - Preview deployments for PRs
```

### Production Environment

```bash
# Kubernetes cluster on AWS EKS / GCP GKE
kubectl apply -f k8s/production/

# Features:
# - Multi-region deployment
# - Auto-scaling
# - Load balancing
# - Monitoring & alerting
# - Automated backups
```

### CI/CD Pipeline

```
┌─────────────────────────────────────────────────────────┐
│                   CI/CD Workflow                         │
└─────────────────────────────────────────────────────────┘

Code Push (GitHub)
       ↓
Automated Tests (GitHub Actions)
 - Unit tests
 - Integration tests
 - Security scans (CodeQL)
       ↓
Build Docker Images
       ↓
Push to Container Registry
       ↓
Deploy to Staging
       ↓
Automated E2E Tests
       ↓
Manual Approval
       ↓
Blue-Green Deployment to Production
       ↓
Health Checks
       ↓
Rollback if Failed
```

### Kubernetes Configuration

```yaml
# Example deployment manifest
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nija-api-gateway
spec:
  replicas: 3
  selector:
    matchLabels:
      app: nija-api-gateway
  template:
    metadata:
      labels:
        app: nija-api-gateway
    spec:
      containers:
      - name: api
        image: nija/api-gateway:v2.0
        ports:
        - containerPort: 8000
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: nija-secrets
              key: database-url
        resources:
          requests:
            memory: "2Gi"
            cpu: "1"
          limits:
            memory: "4Gi"
            cpu: "2"
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /ready
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 5
```

---

## Monitoring & Observability

### Metrics Collection

```
┌─────────────────────────────────────────────────────────┐
│                Monitoring Stack                          │
└─────────────────────────────────────────────────────────┘

Prometheus
- Metrics collection (15s intervals)
- Time-series database
- Alerting rules

Grafana
- Dashboard visualization
- Multi-source aggregation
- Custom alerts

ELK Stack (Elasticsearch, Logstash, Kibana)
- Centralized logging
- Log aggregation
- Search & analytics

Jaeger / OpenTelemetry
- Distributed tracing
- Request flow visualization
- Performance profiling
```

### Key Metrics

```python
# Application Metrics
app_requests_total = Counter('app_requests_total', 'Total requests')
app_request_duration = Histogram('app_request_duration_seconds', 'Request duration')
app_errors_total = Counter('app_errors_total', 'Total errors')

# Trading Metrics
trades_executed_total = Counter('trades_executed_total', 'Total trades')
trade_pnl = Gauge('trade_pnl_usd', 'Current P&L')
positions_active = Gauge('positions_active', 'Active positions')

# System Metrics
cpu_usage = Gauge('cpu_usage_percent', 'CPU usage')
memory_usage = Gauge('memory_usage_bytes', 'Memory usage')
db_connections = Gauge('db_connections', 'Database connections')
```

### Alerts

```yaml
# Prometheus alerting rules
groups:
  - name: nija_alerts
    rules:
      # High error rate
      - alert: HighErrorRate
        expr: rate(app_errors_total[5m]) > 0.05
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High error rate detected"

      # API latency
      - alert: HighLatency
        expr: histogram_quantile(0.95, app_request_duration_seconds) > 0.5
        for: 5m
        labels:
          severity: warning

      # Database connections
      - alert: DatabaseConnectionsHigh
        expr: db_connections > 80
        for: 5m
        labels:
          severity: critical

      # Trading stopped
      - alert: TradingStopped
        expr: rate(trades_executed_total[15m]) == 0
        for: 15m
        labels:
          severity: warning
```

### Logging

```python
import logging
import structlog

# Structured logging
logger = structlog.get_logger()

logger.info(
    "trade_executed",
    user_id="user_123",
    symbol="BTC-USD",
    side="buy",
    size_usd=100.0,
    price=43210.50,
    trade_id="trade_456"
)

# Log levels:
# - DEBUG: Detailed debugging information
# - INFO: General informational messages
# - WARNING: Warning messages (potential issues)
# - ERROR: Error messages (failures)
# - CRITICAL: Critical issues (system failures)
```

---

## Summary

### Architecture Highlights

✅ **Secure Multi-User Platform**
- Encrypted API key storage
- Per-user trade isolation
- JWT-based authentication
- Role-based access control

✅ **Scalable Infrastructure**
- Horizontal scaling (Kubernetes)
- Database replication
- Caching layers (Redis, CDN)
- Load balancing

✅ **Advanced Trading System**
- APEX V7.2 strategy
- Meta-AI optimization
- Multi-market intelligence (MMIN)
- Global macro intelligence (GMIG)
- Execution intelligence

✅ **SaaS Monetization**
- 4 subscription tiers
- Stripe integration
- Usage tracking
- Trial periods

✅ **Comprehensive Monitoring**
- Prometheus + Grafana
- ELK stack logging
- Distributed tracing
- 24/7 alerts

---

## Next Steps

### Implementation Roadmap

**Phase 1: Foundation** (Weeks 1-2)
- [ ] Set up Kubernetes cluster
- [ ] Deploy PostgreSQL + Redis
- [ ] Implement API Gateway
- [ ] Set up monitoring (Prometheus/Grafana)

**Phase 2: Core Services** (Weeks 3-4)
- [ ] Implement Trading Engine service
- [ ] Implement Dashboard API service
- [ ] Implement Subscription service
- [ ] Set up WebSocket service

**Phase 3: Frontend** (Weeks 5-6)
- [ ] Build web dashboard (React)
- [ ] Build mobile apps (React Native)
- [ ] Integrate with backend APIs
- [ ] Implement real-time updates

**Phase 4: Testing & Security** (Weeks 7-8)
- [ ] End-to-end testing
- [ ] Security audit
- [ ] Performance testing
- [ ] Load testing

**Phase 5: Launch** (Week 9)
- [ ] Beta testing
- [ ] Production deployment
- [ ] Marketing & user onboarding
- [ ] Monitor & iterate

---

## Related Documentation

**Platform Architecture Documents (This PR):**
- [API_ROUTES.md](./API_ROUTES.md) - Complete API specification
- [DASHBOARD_DESIGN.md](./DASHBOARD_DESIGN.md) - UI/UX design
- [SUBSCRIPTION_SYSTEM.md](./SUBSCRIPTION_SYSTEM.md) - Billing & tiers
- [SCALING_BLUEPRINT.md](./SCALING_BLUEPRINT.md) - Scaling strategy

**Existing Documentation:**
- [ARCHITECTURE.md](./ARCHITECTURE.md) - Layered architecture overview
- [SECURITY.md](./SECURITY.md) - Security best practices
- [DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md) - Deployment instructions
- [MULTI_USER_PLATFORM_ARCHITECTURE.md](./MULTI_USER_PLATFORM_ARCHITECTURE.md) - Multi-user design

**Planned Documentation:**
- DATABASE_SCHEMA.md - Detailed database schema (TODO)
- MONITORING_GUIDE.md - Observability setup (TODO)
- PERFORMANCE_TUNING.md - Optimization guide (TODO)

---

**Version:** 2.0
**Last Updated:** January 29, 2026
**Status:** ✅ Production-Ready Architecture
**Maintained By:** NIJA Engineering Team
