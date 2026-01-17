# NIJA Advanced User Management Features

## Overview

NIJA now includes comprehensive per-user management features for enhanced control, monitoring, and safety.

## Features

### 🔁 Automatic Nonce Self-Healing

**Location:** `bot/user_nonce_manager.py`

Each user gets their own nonce tracking system with automatic error recovery:

- **Individual nonce files** per user (prevents collisions)
- **Automatic detection** of nonce errors
- **Self-healing recovery** - jumps nonce forward 60 seconds after 2 errors
- **Thread-safe** operations with per-user locks
- **Persistent storage** in `/data/kraken_nonce_{user_id}.txt`

**Usage:**
```python
from bot.user_nonce_manager import get_user_nonce_manager

nonce_manager = get_user_nonce_manager()

# Get next nonce for user
nonce = nonce_manager.get_nonce('user_id')

# Record error (triggers self-healing after 2 errors)
nonce_manager.record_nonce_error('user_id')

# Record success (resets error count)
nonce_manager.record_success('user_id', nonce)

# Get stats
stats = nonce_manager.get_stats('user_id')
```

### 🧯 Auto-Disable Broken Users

**Location:** `controls/__init__.py`

Automatically disables users experiencing persistent API errors:

- **Error threshold:** 5 errors = auto-disable
- **Error type tracking:** Categorize errors (nonce, auth, connection)
- **Kill switch trigger:** Automatically triggered on threshold
- **Logging:** Detailed error logging with counts

**Enhanced from existing system:**
```python
from controls import get_hard_controls

controls = get_hard_controls()

# Record error with type
disabled = controls.record_api_error('user_id', 'nonce_error')
# After 5 errors, user is automatically disabled

# Check if user can trade
can_trade, reason = controls.can_trade('user_id')
```

### 📊 User-Level PnL Dashboards

**Location:** `bot/user_pnl_tracker.py`

Comprehensive profit/loss tracking with detailed analytics:

- **Trade history** with timestamps
- **Win rate** and performance metrics
- **Daily/Weekly/Monthly** breakdowns
- **Best and worst** trades tracking
- **Persistent storage** in `/data/pnl_{user_id}.json`

**Features:**
- Total PnL (all-time)
- Completed vs open positions
- Profit factor calculation
- Recent trades list
- Time-based statistics

**Usage:**
```python
from bot.user_pnl_tracker import get_user_pnl_tracker

pnl_tracker = get_user_pnl_tracker()

# Record entry
pnl_tracker.record_trade(
    user_id='alice',
    symbol='BTC-USD',
    side='buy',
    quantity=0.001,
    price=50000.0,
    size_usd=50.0,
    strategy='APEX_v7.1',
    broker='coinbase'
)

# Record exit with PnL
pnl_tracker.record_trade(
    user_id='alice',
    symbol='BTC-USD',
    side='sell',
    quantity=0.001,
    price=51000.0,
    size_usd=51.0,
    pnl_usd=1.0,
    pnl_pct=2.0
)

# Get stats
stats = pnl_tracker.get_stats('alice')
# Returns: total_pnl, win_rate, winners, losers, avg_win, avg_loss, etc.

# Get recent trades
recent = pnl_tracker.get_recent_trades('alice', limit=10)

# Get daily breakdown
daily = pnl_tracker.get_daily_breakdown('alice', days=7)
```

### 🔒 Risk Caps Per User

**Location:** `bot/user_risk_manager.py`

Individual risk management with configurable limits:

- **Position sizing:** 2-10% default range (configurable)
- **Daily loss limits:** USD amount and percentage
- **Weekly loss limits:** Track cumulative losses
- **Drawdown tracking:** Monitor decline from peak
- **Circuit breaker:** Auto-halt at 3% daily loss
- **Max concurrent positions:** Default 5 positions
- **Persistent storage** in `/data/risk_limits_{user_id}.json` and `/data/risk_state_{user_id}.json`

**Default Limits:**
- Max position: 10% of balance
- Min position: 2% of balance
- Max daily loss: $100 or 5% of balance
- Max weekly loss: $500
- Max drawdown: 15%
- Max daily trades: 20
- Circuit breaker: 3% daily loss

**Usage:**
```python
from bot.user_risk_manager import get_user_risk_manager

risk_manager = get_user_risk_manager()

# Update balance
risk_manager.update_balance('alice', 1000.0)

# Check if can trade
can_trade, reason = risk_manager.can_trade('alice', 50.0)

# Record trade
risk_manager.record_trade('alice', pnl_usd=-10.0)

# Get current state
state = risk_manager.get_state('alice')
# Returns: balance, daily_pnl, daily_trades, drawdown_pct, etc.

# Get/Update limits
limits = risk_manager.get_limits('alice')
risk_manager.update_limits('alice', max_daily_loss_usd=200.0)

# Reset circuit breaker (manual intervention)
risk_manager.reset_circuit_breaker('alice')
```

### 🛑 Global Kill Switch

**Already implemented in** `controls/__init__.py`

**New API endpoints** in `bot/user_dashboard_api.py`:

- **POST `/api/killswitch/global`** - Trigger global kill switch
- **DELETE `/api/killswitch/global`** - Reset global kill switch
- **POST `/api/killswitch/user/{user_id}`** - Trigger user kill switch
- **DELETE `/api/killswitch/user/{user_id}`** - Reset user kill switch

**Usage:**
```python
from controls import get_hard_controls

controls = get_hard_controls()

# Trigger global kill switch
controls.trigger_global_kill_switch('Market crash')

# Check status
can_trade, reason = controls.can_trade('alice')
# Returns: (False, 'Global trading halted (kill switch triggered)')

# Reset (requires manual intervention)
controls.reset_global_kill_switch()
```

### 📡 Trade Confirmation Webhooks

**Location:** `bot/trade_webhook_notifier.py`

Send trade notifications to user-configured webhook URLs:

- **Per-user webhook URLs**
- **Async sending** with retry logic (3 attempts)
- **Event types:** Entry, Exit, Error
- **Timeout protection:** 5 second timeout
- **Statistics tracking**
- **Persistent config** in `/data/webhook_config_{user_id}.json`

**Payload Format:**
```json
{
  "event_type": "trade_exit",
  "user_id": "alice",
  "timestamp": "2026-01-17T22:00:00",
  "symbol": "BTC-USD",
  "side": "sell",
  "quantity": 0.001,
  "price": 51000.0,
  "size_usd": 51.0,
  "pnl_usd": 1.0,
  "pnl_pct": 2.0,
  "strategy": "APEX_v7.1",
  "broker": "coinbase"
}
```

**Usage:**
```python
from bot.trade_webhook_notifier import get_webhook_notifier

notifier = get_webhook_notifier()

# Configure webhook
notifier.configure_webhook(
    user_id='alice',
    webhook_url='https://your-webhook-url.com/notify',
    enabled=True,
    send_entries=True,
    send_exits=True,
    send_errors=False
)

# Send entry notification
notifier.notify_trade_entry(
    user_id='alice',
    symbol='BTC-USD',
    side='buy',
    quantity=0.001,
    price=50000.0,
    size_usd=50.0
)

# Send exit notification
notifier.notify_trade_exit(
    user_id='alice',
    symbol='BTC-USD',
    side='sell',
    quantity=0.001,
    price=51000.0,
    size_usd=51.0,
    pnl_usd=1.0,
    pnl_pct=2.0
)

# Get stats
stats = notifier.get_stats()
# Returns: total_sent, total_failed, total_retried
```

## Dashboard API

**Location:** `bot/user_dashboard_api.py`

REST API for managing users and viewing dashboards:

### Endpoints

#### User Management
- **GET `/api/users`** - List all users with basic stats
- **GET `/api/user/{user_id}/pnl`** - Get detailed PnL dashboard
- **GET `/api/user/{user_id}/risk`** - Get risk status and limits
- **POST `/api/user/{user_id}/risk`** - Update risk limits

#### Kill Switches
- **POST `/api/killswitch/global`** - Trigger global kill switch
- **DELETE `/api/killswitch/global`** - Reset global kill switch
- **POST `/api/killswitch/user/{user_id}`** - Trigger user kill switch
- **DELETE `/api/killswitch/user/{user_id}`** - Reset user kill switch

#### System
- **GET `/api/health`** - Health check
- **GET `/api/stats`** - System-wide statistics

#### Nonce Management
- **GET `/api/user/{user_id}/nonce`** - Get nonce statistics
- **POST `/api/user/{user_id}/nonce/reset`** - Reset nonce tracking

### Running the Dashboard API

```bash
# Start the dashboard API server
python bot/user_dashboard_api.py

# Or set custom port
DASHBOARD_PORT=5001 python bot/user_dashboard_api.py
```

### Example API Calls

```bash
# List all users
curl http://localhost:5001/api/users

# Get PnL for user
curl http://localhost:5001/api/user/alice/pnl

# Get risk status
curl http://localhost:5001/api/user/alice/risk

# Update risk limits
curl -X POST http://localhost:5001/api/user/alice/risk \
  -H "Content-Type: application/json" \
  -d '{"max_daily_loss_usd": 200.0}'

# Trigger global kill switch
curl -X POST http://localhost:5001/api/killswitch/global \
  -H "Content-Type: application/json" \
  -d '{"reason": "Market emergency"}'

# Reset kill switch
curl -X DELETE http://localhost:5001/api/killswitch/global
```

## Data Storage

All user-specific data is stored in `/data/` directory:

- `kraken_nonce_{user_id}.txt` - Nonce tracking
- `pnl_{user_id}.json` - Trade history and PnL
- `risk_limits_{user_id}.json` - Risk limit configuration
- `risk_state_{user_id}.json` - Current risk state
- `webhook_config_{user_id}.json` - Webhook configuration

## Testing

Run the test suite:

```bash
python test_user_management_features.py
```

Tests cover:
- User nonce manager (generation, collision detection, self-healing)
- User PnL tracker (trade recording, statistics)
- User risk manager (limits, state tracking, circuit breaker)
- Trade webhook notifier (configuration, notifications)
- Hard controls integration (kill switches, error tracking)

## Integration with Existing Code

These features are designed to work seamlessly with the existing NIJA codebase:

1. **Nonce Manager** - Can be integrated into `bot/broker_manager.py` KrakenBroker
2. **PnL Tracker** - Can be integrated into trade execution in `bot/execution_engine.py`
3. **Risk Manager** - Can be integrated into order validation in `bot/risk_manager.py`
4. **Webhooks** - Can be called after trade execution
5. **Dashboard API** - Can run as a separate service

## Security Considerations

- All webhook URLs should use HTTPS
- API endpoints should be protected with authentication (not included in basic implementation)
- Webhook payloads don't include sensitive API keys or credentials
- Rate limiting should be added for production use
- Consider adding JWT or API key authentication to dashboard endpoints

## Future Enhancements

Possible improvements:
- Web UI for dashboard (currently REST API only)
- Email notifications in addition to webhooks
- Advanced analytics and charting
- User account management (create/disable users via API)
- Multi-exchange PnL aggregation
- Risk limit templates
- Automated risk adjustment based on performance
