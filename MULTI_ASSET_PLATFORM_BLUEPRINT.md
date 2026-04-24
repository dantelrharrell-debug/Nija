# NIJA Multi-Asset SaaS Platform - Technical Blueprint

## 🎯 Overview

NIJA has been transformed from a crypto-only trading bot into a **multi-asset SaaS trading platform** that intelligently routes capital across:
- **Crypto** (BTC, ETH, altcoins)
- **Equities** (stocks, ETFs)
- **Derivatives** (futures, options - Phase 2)

## 🏗️ Architecture

```
                 ┌───────────────┐
                 │   NIJA AI      │
                 │  CORE BRAIN    │
                 └───────────────┘
                          ↓
        ┌─────────────────────────────────────┐
        │   Multi-Asset Strategy Router        │
        └─────────────────────────────────────┘
         ↓                ↓                 ↓
   Crypto Engine     Equity Engine     Derivatives Engine
         ↓                ↓                 ↓
   Crypto Exchanges    Stock Brokers     Futures / Options
```

### Core Components

#### 1. Multi-Asset Strategy Router (`core/multi_asset_router.py`)
Intelligently allocates capital based on market conditions:
- **High crypto volatility** → Shift capital → Crypto scalping
- **Low crypto volatility** → Shift → Stock momentum
- **Risk-off macro** → Shift → ETFs / cash protection
- **High liquidity** → Futures → leverage

#### 2. Asset Engines (`core/asset_engines.py`)
Specialized engines for each asset class:

**Crypto Engine:**
- Momentum scalping
- Trend riding
- Market making
- Arbitrage
- Volatility capture

**Equity Engine:**
- AI momentum swing trades
- Earnings volatility capture
- Mean reversion
- ETF rotation

**Derivatives Engine (Phase 2):**
- Macro trend AI
- Index scalping
- Volatility breakout

#### 3. Tiered Risk Engine (`core/tiered_risk_engine.py`)
4-gate risk protection system that ALL trades pass through:

```
Capital Guard → Drawdown Guard → Volatility Guard → Execution Gate
```

Enforces:
- Tier risk rules
- Daily loss caps
- Black swan detection
- Kill switch logic

#### 4. Execution Router (`core/execution_router.py`)
Routes trades based on user tier:

| Tier     | Strategy Pool   | Infrastructure | Execution Priority |
|----------|----------------|----------------|-------------------|
| STARTER  | Safe copy      | Shared         | Normal            |
| SAVER    | Capital protect| Shared         | Normal            |
| INVESTOR | Full AI        | Priority       | High              |
| INCOME   | Full AI        | Priority       | High              |
| LIVABLE  | Pro AI         | Priority nodes | Very High         |
| BALLER   | Custom AI      | Dedicated      | Ultra High        |

#### 5. Equity Broker Integration (`core/equity_broker_integration.py`)
Stock broker connections:
- **Alpaca** (primary)
- Interactive Brokers
- TD Ameritrade (future)
- Tradier

#### 6. Revenue Tracker (`core/revenue_tracker.py`)
Tracks 3 revenue streams:

**Stream 1: Subscriptions**
- STARTER: $19/mo → $228/year
- SAVER: $49/mo → $588/year
- INVESTOR: $99/mo → $1,188/year
- INCOME: $249/mo → $2,988/year
- LIVABLE: $499/mo → $5,988/year
- BALLER: $999/mo → $11,988/year

**Stream 2: Performance Fees**
- 10% of all profits above high water mark
- User wins $1,000 → Platform earns $100

**Stream 3: Copy Trading Fees**
- Master traders earn 5% of follower profits
- Platform earns 2% facilitation fee

## 🔐 Security Model

### User Execution Isolation

Each user operates in an isolated execution environment:
- Separate API key vault (encrypted)
- Per-user risk limits
- Individual position tracking
- Isolated P&L tracking

### API Key Management

```python
# User-specific encrypted API keys
user_keys = {
    "crypto": {
        "coinbase": encrypted_api_key,
        "kraken": encrypted_api_key
    },
    "equity": {
        "alpaca": encrypted_api_key
    }
}
```

### Risk Isolation

Each user has independent risk tracking:
- Capital tracking
- Daily P&L limits
- Position limits
- Drawdown limits

## 🚀 API Endpoints

### Authentication

```bash
# Register new user
POST /api/v2/register
{
  "email": "user@example.com",
  "password": "secure_password",
  "tier": "INVESTOR",
  "initial_capital": 1000.0
}

# Login
POST /api/v2/login
{
  "email": "user@example.com",
  "password": "secure_password"
}
```

### Trading

```bash
# Get capital allocation
GET /api/v2/allocation
Authorization: Bearer <token>

Response:
{
  "crypto_pct": 60.0,
  "equity_pct": 40.0,
  "derivatives_pct": 0.0,
  "cash_pct": 0.0,
  "crypto_usd": 600.0,
  "equity_usd": 400.0
}

# Get trading status
GET /api/v2/status
Authorization: Bearer <token>

# Place trade
POST /api/v2/trade
Authorization: Bearer <token>
{
  "symbol": "AAPL",
  "asset_class": "equity",
  "side": "buy",
  "size": 100.0,
  "order_type": "market"
}
```

### Platform Metrics

```bash
# Revenue metrics (admin only)
GET /api/v2/revenue

Response:
{
  "total_revenue": 15000.0,
  "mrr": 2500.0,
  "arr": 30000.0,
  "revenue_by_type": {
    "subscription": 8000.0,
    "performance_fee": 5000.0,
    "copy_trading_fee": 2000.0
  }
}

# Execution stats
GET /api/v2/execution/stats
```

## 🌐 Cloud Deployment

### Railway Deployment

```yaml
# railway.json
{
  "build": {
    "builder": "DOCKERFILE",
    "dockerfilePath": "Dockerfile"
  },
  "deploy": {
    "startCommand": "python api_multi_asset.py",
    "healthcheckPath": "/health",
    "restartPolicyType": "ON_FAILURE"
  }
}
```

### Environment Variables

```bash
# Required
PORT=8000
JWT_SECRET_KEY=your_secret_key

# Crypto Exchanges
COINBASE_API_KEY=xxx
COINBASE_API_SECRET=xxx
KRAKEN_API_KEY=xxx
KRAKEN_API_SECRET=xxx

# Equity Brokers
ALPACA_API_KEY=xxx
ALPACA_API_SECRET=xxx

# Tier Configuration
MINIMUM_TRADING_BALANCE=10.0
```

## 📊 Market Regime Detection

The router automatically detects market conditions:

```python
class MarketRegime(Enum):
    TRENDING_UP = "trending_up"        # Strong uptrend
    TRENDING_DOWN = "trending_down"    # Strong downtrend
    RANGING = "ranging"                # Sideways/choppy
    HIGH_VOLATILITY = "high_volatility"  # VIX spike
    LOW_VOLATILITY = "low_volatility"    # Calm markets
    RISK_OFF = "risk_off"              # Flight to safety
```

Allocation examples:
- **High Volatility**: 90% crypto (scalping), 10% equity
- **Low Volatility**: 40% crypto, 60% equity (stock momentum)
- **Risk-Off**: 20% crypto, 30% equity, 50% cash
- **Ranging**: 50% crypto, 50% equity

## 📈 Usage Example

```python
from core.multi_asset_router import MultiAssetRouter
from core.tiered_risk_engine import TieredRiskEngine
from core.execution_router import ExecutionRouter

# Initialize for user
router = MultiAssetRouter(
    user_tier="INVESTOR",
    total_capital=1000.0,
    risk_tolerance="moderate"
)

# Get allocation
allocation = router.route_capital()
print(allocation.to_dict())
# {'crypto': 60.0, 'equity': 40.0, 'derivatives': 0.0, 'cash': 0.0}

# Validate trade with risk engine
risk_engine = TieredRiskEngine(
    user_tier="INVESTOR",
    total_capital=1000.0
)

approved, risk_level, message = risk_engine.validate_trade(
    trade_size=50.0,
    current_positions=1,
    market_volatility=45.0,
    asset_class="equity"
)

if approved:
    # Route to execution
    exec_router = ExecutionRouter()
    order = {"symbol": "AAPL", "side": "buy", "size": 50.0}
    routing_info = exec_router.route_order("INVESTOR", order)
```

## 🔄 Integration with Existing Infrastructure

The multi-asset platform integrates with existing NIJA components:

### Crypto Trading
- Uses existing `bot/trading_strategy.py` for crypto signals
- Connects through `bot/broker_integration.py`
- Supports Coinbase, Kraken, Binance, OKX

### Copy Trading
- Existing `bot/copy_trade_engine.py` integration
- Multi-asset copy trading support
- Master/follower architecture maintained

### Risk Management
- Enhances existing `bot/risk_manager.py`
- Adds tier-specific controls
- Multi-asset risk aggregation

## 🚦 Getting Started

### 1. Install Dependencies

```bash
pip install -r requirements.txt

# Additional for equity trading
pip install alpaca-trade-api
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your API keys
```

### 3. Run API Server

```bash
python api_multi_asset.py
```

### 4. Access API Documentation

Navigate to: `http://localhost:8000/api/docs`

## 📚 Next Steps

### Phase 2: Full Integration (Days 16-30)
- [ ] Connect crypto engines to existing bot infrastructure
- [ ] Complete Alpaca integration
- [ ] Add Interactive Brokers support
- [ ] Build user dashboard
- [ ] Implement WebSocket real-time updates

### Phase 3: Mobile & Web (Days 31-60)
- [ ] React dashboard
- [ ] Mobile app (iOS/Android)
- [ ] Push notifications
- [ ] Real-time charts

### Phase 4: Institutional (3-6 months)
- [ ] Dedicated infrastructure
- [ ] Compliance & audit systems
- [ ] Institutional-grade reporting
- [ ] Custom strategy builder

## 🔒 Security Checklist

- [x] User execution isolation
- [x] API key encryption
- [x] Tier-based access control
- [x] Risk limits per user
- [x] Kill switch mechanism
- [ ] JWT authentication
- [ ] Rate limiting
- [ ] SQL injection protection
- [ ] DDoS protection
- [ ] Penetration testing

## 📞 Support

For questions or issues:
- Documentation: `/api/docs`
- GitHub Issues: [Create Issue](https://github.com/dantelrharrell-debug/Nija/issues)

---

**NIJA Multi-Asset Platform v2.0**
*Autonomous trading across all markets*
