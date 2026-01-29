# NIJA API Routes - Complete Specification

**Version:** 2.0
**Last Updated:** January 29, 2026
**Base URL:** `https://api.nija.com/api/v1`

---

## Table of Contents

1. [Authentication](#authentication)
2. [Trading Control](#trading-control)
3. [Account Management](#account-management)
4. [Configuration](#configuration)
5. [Subscription Management](#subscription-management)
6. [Analytics & Reporting](#analytics--reporting)
7. [Admin APIs](#admin-apis)
8. [WebSocket APIs](#websocket-apis)
9. [Webhook Endpoints](#webhook-endpoints)
10. [Error Codes](#error-codes)

---

## API Standards

### Authentication

All authenticated endpoints require a JWT token in the `Authorization` header:

```http
Authorization: Bearer <jwt_token>
```

### Request Format

```http
Content-Type: application/json
Accept: application/json
```

### Response Format

**Success Response:**
```json
{
  "success": true,
  "data": { ... },
  "timestamp": "2026-01-29T10:42:00Z"
}
```

**Error Response:**
```json
{
  "success": false,
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable error message",
    "details": { ... }
  },
  "timestamp": "2026-01-29T10:42:00Z"
}
```

### Pagination

```json
{
  "success": true,
  "data": {
    "items": [...],
    "pagination": {
      "page": 1,
      "per_page": 50,
      "total_items": 234,
      "total_pages": 5,
      "has_next": true,
      "has_prev": false
    }
  }
}
```

### Rate Limiting

Rate limits are tier-based:
- **Free**: 10 requests/minute
- **Basic**: 30 requests/minute
- **Pro**: 100 requests/minute
- **Enterprise**: 500 requests/minute

Headers returned:
```http
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1706529720
```

---

## Authentication

### Register User

Create a new user account.

```http
POST /auth/register
```

**Request:**
```json
{
  "email": "user@example.com",
  "password": "SecurePassword123!",
  "full_name": "John Doe",
  "accept_terms": true
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "user_id": "usr_abc123",
    "email": "user@example.com",
    "full_name": "John Doe",
    "subscription_tier": "free",
    "trial_active": true,
    "trial_ends_at": "2026-02-12T10:42:00Z",
    "created_at": "2026-01-29T10:42:00Z"
  }
}
```

**Error Codes:**
- `EMAIL_ALREADY_EXISTS` - Email is already registered
- `INVALID_EMAIL` - Invalid email format
- `WEAK_PASSWORD` - Password doesn't meet requirements
- `TERMS_NOT_ACCEPTED` - Terms of service not accepted

---

### Login

Authenticate user and receive JWT token.

```http
POST /auth/login
```

**Request:**
```json
{
  "email": "user@example.com",
  "password": "SecurePassword123!"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "token_type": "Bearer",
    "expires_in": 86400,
    "user": {
      "user_id": "usr_abc123",
      "email": "user@example.com",
      "full_name": "John Doe",
      "subscription_tier": "pro"
    }
  }
}
```

**Error Codes:**
- `INVALID_CREDENTIALS` - Email or password is incorrect
- `ACCOUNT_DISABLED` - Account has been disabled
- `ACCOUNT_SUSPENDED` - Account suspended (payment issue)

---

### Refresh Token

Refresh JWT access token.

```http
POST /auth/refresh
```

**Request:**
```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "token_type": "Bearer",
    "expires_in": 86400
  }
}
```

---

### Logout

Invalidate current session.

```http
POST /auth/logout
```

**Request:**
```json
{
  "revoke_all": false
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "message": "Logged out successfully"
  }
}
```

---

### Reset Password

Request password reset email.

```http
POST /auth/reset-password
```

**Request:**
```json
{
  "email": "user@example.com"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "message": "Password reset email sent"
  }
}
```

---

### Change Password

Change user password (authenticated).

```http
PUT /auth/change-password
```

**Request:**
```json
{
  "current_password": "OldPassword123!",
  "new_password": "NewPassword456!"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "message": "Password changed successfully"
  }
}
```

---

## Trading Control

### Start Trading

Start the trading bot for the authenticated user.

```http
POST /trading/start
```

**Request:**
```json
{
  "broker": "coinbase",
  "paper_trading": false,
  "risk_profile": "medium"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "status": "starting",
    "message": "Trading bot is starting",
    "estimated_ready_in_seconds": 10
  }
}
```

**Error Codes:**
- `ALREADY_RUNNING` - Bot is already running
- `NO_BROKER_CONFIGURED` - No broker API keys configured
- `SUBSCRIPTION_REQUIRED` - Live trading requires paid subscription
- `KILL_SWITCH_ACTIVE` - Trading is blocked by kill switch

---

### Stop Trading

Stop the trading bot.

```http
POST /trading/stop
```

**Request:**
```json
{
  "close_positions": false,
  "emergency": false
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "status": "stopped",
    "message": "Trading bot stopped",
    "open_positions": 3,
    "action_required": "Manual position closure recommended"
  }
}
```

---

### Get Trading Status

Get current bot status.

```http
GET /trading/status
```

**Response:**
```json
{
  "success": true,
  "data": {
    "status": "running",
    "uptime_seconds": 3600,
    "broker": "coinbase",
    "paper_trading": false,
    "last_scan": "2026-01-29T10:40:00Z",
    "next_scan": "2026-01-29T10:42:30Z",
    "active_positions": 3,
    "today_trades": 8,
    "last_error": null
  }
}
```

**Status Values:**
- `stopped` - Bot is not running
- `starting` - Bot is initializing
- `running` - Bot is actively trading
- `paused` - Bot is paused (manual or auto)
- `error` - Bot encountered an error

---

### Emergency Stop

Emergency kill switch - immediately stop all trading.

```http
POST /trading/emergency-stop
```

**Request:**
```json
{
  "reason": "Market volatility",
  "close_positions": true
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "status": "emergency_stopped",
    "positions_closed": 3,
    "message": "Emergency stop activated"
  }
}
```

---

## Account Management

### Get Account Balance

Get current account balance and equity.

```http
GET /account/balance
```

**Response:**
```json
{
  "success": true,
  "data": {
    "broker": "coinbase",
    "cash": 9850.50,
    "equity": 10450.75,
    "unrealized_pnl": 600.25,
    "buying_power": 9850.50,
    "currency": "USD",
    "last_updated": "2026-01-29T10:42:00Z"
  }
}
```

---

### Get Active Positions

Get all active trading positions.

```http
GET /account/positions
```

**Query Parameters:**
- `broker` (optional) - Filter by broker
- `symbol` (optional) - Filter by symbol

**Response:**
```json
{
  "success": true,
  "data": {
    "positions": [
      {
        "position_id": "pos_123",
        "symbol": "BTC-USD",
        "side": "long",
        "entry_price": 43210.50,
        "current_price": 43650.00,
        "size_usd": 500.00,
        "quantity": 0.01157,
        "unrealized_pnl": 44.85,
        "unrealized_pnl_pct": 8.97,
        "stop_loss": 42800.00,
        "take_profit": 44500.00,
        "opened_at": "2026-01-29T08:30:00Z",
        "broker": "coinbase"
      },
      {
        "position_id": "pos_124",
        "symbol": "ETH-USD",
        "side": "long",
        "entry_price": 2345.00,
        "current_price": 2389.50,
        "size_usd": 300.00,
        "quantity": 0.1279,
        "unrealized_pnl": 28.32,
        "unrealized_pnl_pct": 9.44,
        "stop_loss": 2320.00,
        "take_profit": 2420.00,
        "opened_at": "2026-01-29T09:15:00Z",
        "broker": "coinbase"
      }
    ],
    "summary": {
      "total_positions": 2,
      "total_value_usd": 800.00,
      "total_unrealized_pnl": 73.17,
      "total_unrealized_pnl_pct": 9.15
    }
  }
}
```

---

### Get Trade History

Get historical trade records.

```http
GET /account/history
```

**Query Parameters:**
- `page` (default: 1) - Page number
- `per_page` (default: 50, max: 100) - Items per page
- `start_date` (optional) - Filter by start date (ISO 8601)
- `end_date` (optional) - Filter by end date
- `symbol` (optional) - Filter by symbol
- `status` (optional) - Filter by status (open, closed, cancelled)

**Response:**
```json
{
  "success": true,
  "data": {
    "trades": [
      {
        "trade_id": "trd_789",
        "symbol": "BTC-USD",
        "side": "long",
        "entry_price": 42800.00,
        "exit_price": 43200.00,
        "size_usd": 500.00,
        "quantity": 0.01168,
        "realized_pnl": 46.72,
        "realized_pnl_pct": 9.34,
        "fees": 3.28,
        "opened_at": "2026-01-28T14:30:00Z",
        "closed_at": "2026-01-29T09:15:00Z",
        "duration_minutes": 1125,
        "exit_reason": "take_profit",
        "broker": "coinbase"
      }
    ],
    "pagination": {
      "page": 1,
      "per_page": 50,
      "total_items": 234,
      "total_pages": 5,
      "has_next": true,
      "has_prev": false
    }
  }
}
```

---

### Get Performance Metrics

Get trading performance statistics.

```http
GET /account/performance
```

**Query Parameters:**
- `period` (optional) - Time period (7d, 30d, 90d, 1y, all) - default: 30d

**Response:**
```json
{
  "success": true,
  "data": {
    "period": "30d",
    "metrics": {
      "total_trades": 156,
      "winning_trades": 108,
      "losing_trades": 48,
      "win_rate": 0.6923,
      "total_pnl": 2340.50,
      "total_pnl_pct": 23.41,
      "avg_win": 45.60,
      "avg_loss": -22.30,
      "largest_win": 156.80,
      "largest_loss": -87.40,
      "profit_factor": 2.04,
      "sharpe_ratio": 1.85,
      "max_drawdown": -8.5,
      "max_drawdown_pct": -8.5,
      "recovery_time_days": 3.2,
      "avg_trade_duration_minutes": 720,
      "total_fees": 128.45,
      "net_pnl": 2212.05
    },
    "daily_pnl": [
      {"date": "2026-01-01", "pnl": 45.60},
      {"date": "2026-01-02", "pnl": 78.20},
      {"date": "2026-01-03", "pnl": -23.40}
    ],
    "equity_curve": [
      {"date": "2026-01-01", "equity": 10045.60},
      {"date": "2026-01-02", "equity": 10123.80},
      {"date": "2026-01-03", "equity": 10100.40}
    ]
  }
}
```

---

### Get Account Statistics

Get comprehensive account statistics.

```http
GET /account/stats
```

**Response:**
```json
{
  "success": true,
  "data": {
    "account": {
      "user_id": "usr_abc123",
      "subscription_tier": "pro",
      "account_age_days": 45,
      "total_deposits": 10000.00,
      "total_withdrawals": 0.00,
      "current_balance": 12212.05,
      "all_time_high": 12450.80,
      "all_time_low": 9850.20
    },
    "trading": {
      "total_trades_all_time": 523,
      "total_volume_usd": 156780.50,
      "total_fees_paid": 487.32,
      "best_month": {
        "month": "2026-01",
        "pnl": 2340.50,
        "pnl_pct": 23.41
      },
      "current_streak": {
        "type": "winning",
        "count": 5,
        "started": "2026-01-27T10:00:00Z"
      }
    },
    "risk": {
      "current_risk_level": "medium",
      "max_position_size_usd": 2000.00,
      "max_positions": 10,
      "current_leverage": 1.0,
      "available_leverage": 3.0
    }
  }
}
```

---

## Configuration

### Get User Settings

Get user configuration settings.

```http
GET /config/settings
```

**Response:**
```json
{
  "success": true,
  "data": {
    "trading": {
      "risk_level": "medium",
      "max_position_size_usd": 500.0,
      "max_concurrent_positions": 5,
      "max_daily_loss_usd": 200.0,
      "allowed_pairs": ["BTC-USD", "ETH-USD", "SOL-USD"],
      "paper_trading": false
    },
    "notifications": {
      "email_enabled": true,
      "push_enabled": true,
      "trade_notifications": true,
      "daily_summary": true,
      "weekly_report": true
    },
    "advanced": {
      "enable_meta_ai": true,
      "enable_mmin": true,
      "enable_gmig": false,
      "execution_intelligence": true
    }
  }
}
```

---

### Update User Settings

Update user configuration settings.

```http
PUT /config/settings
```

**Request:**
```json
{
  "trading": {
    "risk_level": "high",
    "max_position_size_usd": 1000.0,
    "max_concurrent_positions": 8
  },
  "notifications": {
    "email_enabled": false,
    "push_enabled": true
  }
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "message": "Settings updated successfully",
    "updated_fields": ["risk_level", "max_position_size_usd", "max_concurrent_positions", "email_enabled"]
  }
}
```

**Error Codes:**
- `INVALID_RISK_LEVEL` - Invalid risk level value
- `EXCEEDS_TIER_LIMIT` - Setting exceeds subscription tier limits
- `INVALID_SETTING` - Setting name not recognized

---

### Get Configured Brokers

Get list of configured broker connections.

```http
GET /config/brokers
```

**Response:**
```json
{
  "success": true,
  "data": {
    "brokers": [
      {
        "broker_id": "brk_123",
        "name": "coinbase",
        "display_name": "Coinbase Advanced Trade",
        "status": "connected",
        "last_connected": "2026-01-29T10:30:00Z",
        "api_key_masked": "sk_live_***abc123",
        "permissions": ["read", "trade"],
        "created_at": "2026-01-15T10:00:00Z"
      },
      {
        "broker_id": "brk_124",
        "name": "kraken",
        "display_name": "Kraken Pro",
        "status": "connected",
        "last_connected": "2026-01-29T10:35:00Z",
        "api_key_masked": "kr_***xyz789",
        "permissions": ["read", "trade"],
        "created_at": "2026-01-20T14:30:00Z"
      }
    ]
  }
}
```

---

### Add Broker Connection

Add new broker API keys.

```http
POST /config/brokers
```

**Request:**
```json
{
  "broker": "coinbase",
  "api_key": "your_api_key_here",
  "api_secret": "your_api_secret_here",
  "additional_params": {
    "org_id": "org_id_here"
  }
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "broker_id": "brk_125",
    "message": "Broker connected successfully",
    "status": "connected"
  }
}
```

**Error Codes:**
- `INVALID_API_KEY` - API key validation failed
- `BROKER_ALREADY_CONNECTED` - Broker already configured
- `UNSUPPORTED_BROKER` - Broker not supported

---

### Remove Broker Connection

Remove broker API keys.

```http
DELETE /config/brokers/{broker_id}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "message": "Broker removed successfully",
    "open_positions": 2,
    "warning": "Close positions before removing broker"
  }
}
```

---

### Test Broker Connection

Test broker API credentials.

```http
POST /config/brokers/{broker_id}/test
```

**Response:**
```json
{
  "success": true,
  "data": {
    "status": "connected",
    "latency_ms": 145,
    "permissions": ["read", "trade"],
    "account_balance": 10450.75
  }
}
```

---

## Subscription Management

### Get Available Plans

Get all subscription tiers and pricing.

```http
GET /subscription/plans
```

**Response:**
```json
{
  "success": true,
  "data": {
    "plans": [
      {
        "tier": "free",
        "name": "Free",
        "price_monthly": 0,
        "price_yearly": 0,
        "features": [
          "Paper trading only",
          "Basic strategy (APEX V7.2)",
          "1 exchange connection",
          "Community support",
          "Basic analytics"
        ],
        "limits": {
          "max_position_size_usd": 0,
          "max_positions": 3,
          "max_daily_trades": 10,
          "api_calls_per_minute": 10
        }
      },
      {
        "tier": "basic",
        "name": "Basic",
        "price_monthly": 49,
        "price_yearly": 470,
        "yearly_savings": 118,
        "features": [
          "Live trading",
          "APEX V7.2 strategy",
          "2 exchange connections",
          "Email support",
          "Standard analytics",
          "Mobile app access"
        ],
        "limits": {
          "max_position_size_usd": 500,
          "max_positions": 5,
          "max_daily_trades": 30,
          "api_calls_per_minute": 30
        }
      },
      {
        "tier": "pro",
        "name": "Pro",
        "price_monthly": 149,
        "price_yearly": 1430,
        "yearly_savings": 358,
        "popular": true,
        "features": [
          "All Basic features",
          "Meta-AI optimization",
          "MMIN multi-market intelligence",
          "5 exchange connections",
          "Priority support",
          "Advanced analytics",
          "Custom risk profiles",
          "TradingView integration"
        ],
        "limits": {
          "max_position_size_usd": 2000,
          "max_positions": 10,
          "max_daily_trades": 100,
          "api_calls_per_minute": 100
        }
      },
      {
        "tier": "enterprise",
        "name": "Enterprise",
        "price_monthly": 499,
        "price_yearly": 4790,
        "yearly_savings": 1198,
        "features": [
          "All Pro features",
          "GMIG macro intelligence",
          "Unlimited exchanges",
          "Dedicated support",
          "Custom strategy tuning",
          "API access",
          "White-label option",
          "Multi-account management"
        ],
        "limits": {
          "max_position_size_usd": 10000,
          "max_positions": 50,
          "max_daily_trades": 500,
          "api_calls_per_minute": 500
        }
      }
    ]
  }
}
```

---

### Get Current Subscription

Get user's current subscription details.

```http
GET /subscription/current
```

**Response:**
```json
{
  "success": true,
  "data": {
    "subscription_id": "sub_abc123",
    "tier": "pro",
    "interval": "monthly",
    "status": "active",
    "current_period_start": "2026-01-15T00:00:00Z",
    "current_period_end": "2026-02-15T00:00:00Z",
    "cancel_at_period_end": false,
    "trial_active": false,
    "trial_ends_at": null,
    "amount": 149.00,
    "currency": "USD",
    "payment_method": {
      "type": "card",
      "last4": "4242",
      "brand": "visa",
      "exp_month": 12,
      "exp_year": 2028
    },
    "next_billing_date": "2026-02-15T00:00:00Z",
    "next_billing_amount": 149.00
  }
}
```

---

### Upgrade Subscription

Upgrade to a higher tier.

```http
POST /subscription/upgrade
```

**Request:**
```json
{
  "tier": "enterprise",
  "interval": "yearly",
  "payment_method_id": "pm_123abc"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "subscription_id": "sub_new456",
    "message": "Subscription upgraded successfully",
    "tier": "enterprise",
    "interval": "yearly",
    "amount": 4790.00,
    "proration_credit": -45.60,
    "amount_due_now": 4744.40,
    "effective_immediately": true
  }
}
```

---

### Cancel Subscription

Cancel current subscription.

```http
POST /subscription/cancel
```

**Request:**
```json
{
  "cancel_immediately": false,
  "reason": "Too expensive",
  "feedback": "Great product but out of budget"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "message": "Subscription cancelled",
    "cancel_at_period_end": true,
    "access_until": "2026-02-15T00:00:00Z",
    "refund_amount": 0.00
  }
}
```

---

### Get Usage Statistics

Get current billing period usage.

```http
GET /subscription/usage
```

**Response:**
```json
{
  "success": true,
  "data": {
    "period_start": "2026-01-15T00:00:00Z",
    "period_end": "2026-02-15T00:00:00Z",
    "usage": {
      "api_calls": 12450,
      "api_calls_limit": 100000,
      "trades_executed": 156,
      "trades_limit": 3000,
      "positions_opened": 156,
      "max_concurrent_positions": 8,
      "max_concurrent_positions_limit": 10,
      "brokers_connected": 3,
      "brokers_limit": 5
    },
    "overage": false,
    "warnings": []
  }
}
```

---

## Analytics & Reporting

### Get Dashboard Summary

Get overview statistics for dashboard.

```http
GET /analytics/dashboard
```

**Response:**
```json
{
  "success": true,
  "data": {
    "today": {
      "pnl": 145.60,
      "pnl_pct": 1.42,
      "trades": 8,
      "win_rate": 0.75
    },
    "week": {
      "pnl": 678.90,
      "pnl_pct": 6.64,
      "trades": 45,
      "win_rate": 0.69
    },
    "month": {
      "pnl": 2340.50,
      "pnl_pct": 23.41,
      "trades": 156,
      "win_rate": 0.69
    },
    "active_positions": 3,
    "balance": 12212.05,
    "top_performer": {
      "symbol": "BTC-USD",
      "pnl": 456.80,
      "pnl_pct": 15.2
    }
  }
}
```

---

### Get Trade Analytics

Get detailed trade analytics.

```http
GET /analytics/trades
```

**Query Parameters:**
- `period` (optional) - Time period (7d, 30d, 90d, 1y, all)
- `symbol` (optional) - Filter by symbol
- `group_by` (optional) - Group by (hour, day, week, month)

**Response:**
```json
{
  "success": true,
  "data": {
    "period": "30d",
    "total_trades": 156,
    "by_outcome": {
      "wins": 108,
      "losses": 48,
      "win_rate": 0.6923
    },
    "by_symbol": [
      {"symbol": "BTC-USD", "trades": 52, "pnl": 1245.60},
      {"symbol": "ETH-USD", "trades": 48, "pnl": 678.90},
      {"symbol": "SOL-USD", "trades": 32, "pnl": 416.00}
    ],
    "by_hour": [
      {"hour": 9, "trades": 23, "avg_pnl": 35.60},
      {"hour": 10, "trades": 28, "avg_pnl": 42.30}
    ],
    "avg_hold_time_minutes": 720,
    "best_trade": {
      "trade_id": "trd_best",
      "symbol": "BTC-USD",
      "pnl": 156.80,
      "pnl_pct": 12.5
    },
    "worst_trade": {
      "trade_id": "trd_worst",
      "symbol": "ETH-USD",
      "pnl": -87.40,
      "pnl_pct": -8.7
    }
  }
}
```

---

### Export Data

Export trade data to CSV/JSON.

```http
POST /analytics/export
```

**Request:**
```json
{
  "format": "csv",
  "data_type": "trades",
  "start_date": "2026-01-01",
  "end_date": "2026-01-31",
  "include_closed_positions": true,
  "include_open_positions": false
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "download_url": "https://api.nija.com/exports/trades_2026_01.csv",
    "expires_at": "2026-01-29T11:42:00Z",
    "file_size_bytes": 45678
  }
}
```

---

## Admin APIs

**Note:** These endpoints require admin role.

### List All Users

Get list of all users (admin only).

```http
GET /admin/users
```

**Query Parameters:**
- `page` (default: 1)
- `per_page` (default: 50)
- `search` (optional) - Search by email or user_id
- `tier` (optional) - Filter by subscription tier
- `status` (optional) - Filter by status (active, suspended, disabled)

**Response:**
```json
{
  "success": true,
  "data": {
    "users": [
      {
        "user_id": "usr_abc123",
        "email": "user@example.com",
        "full_name": "John Doe",
        "subscription_tier": "pro",
        "status": "active",
        "total_trades": 156,
        "total_pnl": 2340.50,
        "joined_at": "2026-01-15T10:00:00Z",
        "last_active": "2026-01-29T10:30:00Z"
      }
    ],
    "pagination": {...}
  }
}
```

---

### Get User Details

Get detailed user information (admin only).

```http
GET /admin/users/{user_id}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "user": {
      "user_id": "usr_abc123",
      "email": "user@example.com",
      "full_name": "John Doe",
      "subscription": {
        "tier": "pro",
        "status": "active",
        "started": "2026-01-15",
        "renews": "2026-02-15"
      },
      "trading": {
        "total_trades": 156,
        "total_pnl": 2340.50,
        "win_rate": 0.69,
        "active_positions": 3
      },
      "brokers": [
        {"name": "coinbase", "status": "connected"},
        {"name": "kraken", "status": "connected"}
      ],
      "joined_at": "2026-01-15T10:00:00Z",
      "last_active": "2026-01-29T10:30:00Z"
    }
  }
}
```

---

### Update User

Update user details (admin only).

```http
PUT /admin/users/{user_id}
```

**Request:**
```json
{
  "subscription_tier": "enterprise",
  "status": "active",
  "notes": "Upgraded to enterprise for beta testing"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "message": "User updated successfully"
  }
}
```

---

### Trigger Global Kill Switch

Activate global emergency stop (admin only).

```http
POST /admin/kill-switch
```

**Request:**
```json
{
  "reason": "Market emergency - extreme volatility",
  "close_all_positions": false,
  "notify_users": true
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "message": "Global kill switch activated",
    "affected_users": 1245,
    "active_positions": 3421,
    "timestamp": "2026-01-29T10:42:00Z"
  }
}
```

---

### Get System Metrics

Get platform-wide metrics (admin only).

```http
GET /admin/metrics
```

**Response:**
```json
{
  "success": true,
  "data": {
    "users": {
      "total": 1245,
      "active_today": 892,
      "free": 456,
      "basic": 345,
      "pro": 389,
      "enterprise": 55
    },
    "trading": {
      "bots_running": 892,
      "total_positions": 3421,
      "total_volume_24h": 4567890.50,
      "total_trades_24h": 5678
    },
    "system": {
      "api_requests_per_second": 145,
      "avg_response_time_ms": 85,
      "error_rate": 0.002,
      "uptime_pct": 99.98
    },
    "revenue": {
      "mrr": 156789.00,
      "arr": 1881468.00,
      "churn_rate": 0.035
    }
  }
}
```

---

### Get Audit Logs

Get system audit logs (admin only).

```http
GET /admin/audit-logs
```

**Query Parameters:**
- `page` (default: 1)
- `per_page` (default: 100)
- `event_type` (optional) - Filter by event type
- `user_id` (optional) - Filter by user
- `start_date` (optional)
- `end_date` (optional)

**Response:**
```json
{
  "success": true,
  "data": {
    "logs": [
      {
        "log_id": "log_123",
        "event_type": "user_login",
        "user_id": "usr_abc123",
        "ip_address": "192.168.1.1",
        "user_agent": "Mozilla/5.0...",
        "metadata": {
          "login_method": "email_password",
          "success": true
        },
        "timestamp": "2026-01-29T10:30:00Z"
      },
      {
        "log_id": "log_124",
        "event_type": "trade_executed",
        "user_id": "usr_abc123",
        "metadata": {
          "symbol": "BTC-USD",
          "side": "buy",
          "size_usd": 500.00,
          "broker": "coinbase"
        },
        "timestamp": "2026-01-29T10:35:00Z"
      }
    ],
    "pagination": {...}
  }
}
```

---

## WebSocket APIs

### Connect to WebSocket

```
WS wss://api.nija.com/ws/v1
```

**Authentication:**
```json
{
  "type": "auth",
  "token": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**Response:**
```json
{
  "type": "auth_success",
  "user_id": "usr_abc123",
  "subscriptions": []
}
```

---

### Subscribe to Positions

**Request:**
```json
{
  "type": "subscribe",
  "channel": "positions"
}
```

**Updates:**
```json
{
  "type": "position_update",
  "channel": "positions",
  "data": {
    "position_id": "pos_123",
    "symbol": "BTC-USD",
    "current_price": 43650.00,
    "unrealized_pnl": 44.85,
    "unrealized_pnl_pct": 8.97,
    "timestamp": "2026-01-29T10:42:00Z"
  }
}
```

---

### Subscribe to Trade Notifications

**Request:**
```json
{
  "type": "subscribe",
  "channel": "trades"
}
```

**Updates:**
```json
{
  "type": "trade_executed",
  "channel": "trades",
  "data": {
    "trade_id": "trd_789",
    "action": "opened",
    "symbol": "BTC-USD",
    "side": "long",
    "entry_price": 43210.50,
    "size_usd": 500.00,
    "timestamp": "2026-01-29T10:42:00Z"
  }
}
```

---

## Webhook Endpoints

### TradingView Webhook

Receive trading signals from TradingView.

```http
POST /webhooks/tradingview
```

**Request:**
```json
{
  "symbol": "BTC-USD",
  "action": "buy",
  "price": 43210.50,
  "strategy": "APEX_V72",
  "api_key": "your_webhook_key"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "received": true,
    "trade_id": "trd_new",
    "status": "processing"
  }
}
```

---

### Stripe Webhook

Receive payment events from Stripe.

```http
POST /webhooks/stripe
```

**Handled Events:**
- `invoice.payment_succeeded` - Activate subscription
- `invoice.payment_failed` - Suspend account
- `customer.subscription.deleted` - Cancel subscription
- `customer.subscription.updated` - Update subscription

---

## Error Codes

### Authentication Errors (4xx)

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `INVALID_CREDENTIALS` | 401 | Email or password incorrect |
| `TOKEN_EXPIRED` | 401 | JWT token has expired |
| `TOKEN_INVALID` | 401 | JWT token is invalid |
| `UNAUTHORIZED` | 403 | User not authorized for this action |
| `EMAIL_ALREADY_EXISTS` | 409 | Email already registered |

### Trading Errors (4xx)

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `ALREADY_RUNNING` | 409 | Bot is already running |
| `NOT_RUNNING` | 400 | Bot is not running |
| `NO_BROKER_CONFIGURED` | 400 | No broker API keys configured |
| `SUBSCRIPTION_REQUIRED` | 402 | Live trading requires subscription |
| `KILL_SWITCH_ACTIVE` | 403 | Trading blocked by kill switch |
| `POSITION_NOT_FOUND` | 404 | Position not found |

### Configuration Errors (4xx)

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `INVALID_SETTING` | 400 | Setting name not recognized |
| `EXCEEDS_TIER_LIMIT` | 403 | Setting exceeds tier limits |
| `INVALID_API_KEY` | 400 | Broker API key validation failed |
| `BROKER_ALREADY_CONNECTED` | 409 | Broker already configured |

### Server Errors (5xx)

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `INTERNAL_ERROR` | 500 | Internal server error |
| `DATABASE_ERROR` | 500 | Database operation failed |
| `BROKER_ERROR` | 502 | Broker API error |
| `SERVICE_UNAVAILABLE` | 503 | Service temporarily unavailable |

---

## SDK Examples

### Python SDK

```python
from nija_sdk import NIJAClient

# Initialize client
client = NIJAClient(api_key="your_jwt_token")

# Start trading
response = client.trading.start(
    broker="coinbase",
    paper_trading=False
)

# Get positions
positions = client.account.positions()

# Subscribe to WebSocket updates
@client.ws.on("position_update")
def on_position_update(data):
    print(f"Position update: {data}")

client.ws.connect()
```

### JavaScript SDK

```javascript
import { NIJAClient } from '@nija/sdk';

// Initialize client
const client = new NIJAClient({
  apiKey: 'your_jwt_token'
});

// Start trading
const response = await client.trading.start({
  broker: 'coinbase',
  paperTrading: false
});

// Get positions
const positions = await client.account.positions();

// Subscribe to WebSocket
client.ws.on('position_update', (data) => {
  console.log('Position update:', data);
});

await client.ws.connect();
```

---

**Version:** 2.0
**Last Updated:** January 29, 2026
**Maintained By:** NIJA Engineering Team
