# 🎯 NIJA Live Status Dashboard Reference

**Quick Reference for Operators** • Monitor All Users at a Glance • Version 1.0 • February 2026

---

## 📊 Quick Start

```bash
# View all users now
python user_status_summary.py

# Detailed mode (shows email, brokers, timestamps)
python user_status_summary.py --detailed

# JSON for automation/dashboards
python user_status_summary.py --json

# Quiet mode (clean output, no warnings)
python user_status_summary.py --quiet
```

---

## 🎨 Status Icons & Colors

### Trading Status
| Icon | Status | Meaning |
|------|--------|---------|
| **✅** | Ready | User can trade (all systems go) |
| **⛔** | Disabled | Trading blocked (see reason in output) |

### Account Indicators
| Icon | Indicator | Meaning |
|------|-----------|---------|
| **💰** | Has Balance | User has funds available |
| **📈** | Open Positions | Active trades in market |

### Risk Levels
| Icon | Level | Condition | Action Required |
|------|-------|-----------|-----------------|
| **🔴** | High Risk | Daily loss > 5% | **Monitor closely, may auto-disable** |
| **🟡** | Medium Risk | Daily loss 2-5% | Watch for deterioration |
| **🟢** | Normal | Within safe limits | Standard operation |
| **💚** | Profitable | Daily gain > 2% | Healthy performance |

---

## 📋 Sample Output

```
====================================================================
NIJA LIVE USER STATUS SUMMARY
====================================================================

📊 PLATFORM OVERVIEW
   Total Users: 5 | Active: 5 | Trading Ready: 3 | With Positions: 2
   Total Capital: $47,500.00 | Unrealized P&L: +$1,234.50

👥 USER STATUS
--------------------------------------------------------------------

✅ 💰 📈 💚 john_trader (pro)
      Balance: $25,000.00 (coinbase: $15,000 | kraken: $10,000)
      Positions: 3 open | Unrealized P&L: +$850.00
      Status: Running | Daily P&L: +$420.00

✅ 💰       alice_investor (basic)
      Balance: $10,000.00 (coinbase: $10,000)
      Status: Running

⛔          bob_newbie (basic)
      Balance: $2,500.00
      Status: ⛔ Circuit breaker triggered - Daily loss limit

⛔          charlie_test (basic)
      Balance: $0.00
      Status: ⛔ 🔴 LIVE_CAPITAL_VERIFIED: FALSE
```

---

## 🔧 JSON Output Structure

```json
{
  "timestamp": "2026-02-07T19:00:00",
  "platform_overview": {
    "total_users": 5,
    "active_users": 5,
    "trading_ready": 3,
    "users_with_positions": 2,
    "total_capital_usd": 47500.0,
    "total_unrealized_pnl": 1234.5
  },
  "users": [
    {
      "user_id": "john_trader",
      "can_trade": true,
      "total_balance_usd": 25000.0,
      "broker_balances": {
        "coinbase": 15000.0,
        "kraken": 10000.0
      },
      "open_positions": 3,
      "unrealized_pnl": 850.0,
      "daily_pnl": 420.0,
      "risk_level": "profitable",
      "circuit_breaker": false
    }
  ]
}
```

---

## 🚨 Quick Troubleshooting

### ⛔ User Shows "Trading Disabled"

**Common Reasons:**
1. **LIVE_CAPITAL_VERIFIED=false** → Set to `true` in `.env` to enable live trading
2. **Circuit breaker triggered** → Daily loss limit exceeded, resets at midnight
3. **Kill switch active** → Manual disable via controls, check logs
4. **Missing credentials** → Verify API keys in database or config files
5. **Balance too low** → User below minimum tier threshold

### 💰 Balance Shows $0.00

**Possible Causes:**
- Database not connected (using config file fallback)
- Risk manager not initialized
- User credentials not configured
- API connection issues with broker

**Fix:** Check database connection, verify broker credentials

### 🔴 High Risk User

**Immediate Actions:**
1. Review open positions for that user
2. Check if circuit breaker will trigger soon
3. Monitor for auto-liquidation
4. Consider manual intervention if needed

### No Users Found

**Checklist:**
- ✓ Database connection configured? (`DATABASE_URL` or `POSTGRES_*` vars)
- ✓ Config files present? (check `config/users/*.yaml`)
- ✓ Script permissions? (`chmod +x user_status_summary.py`)

---

## 💡 Common Use Cases

### 1. Daily Morning Check
```bash
python user_status_summary.py | grep "PLATFORM OVERVIEW" -A 3
```

### 2. Find High-Risk Users
```bash
python user_status_summary.py --json | jq '.users[] | select(.risk_level == "high")'
```

### 3. List All Trading-Ready Users
```bash
python user_status_summary.py --json | jq '.users[] | select(.can_trade == true) | .user_id'
```

### 4. Check Total Platform Capital
```bash
python user_status_summary.py --json | jq '.platform_overview.total_capital_usd'
```

### 5. Export Daily Snapshot
```bash
python user_status_summary.py --json > snapshots/status_$(date +%Y%m%d_%H%M).json
```

### 6. Monitor Specific User
```bash
python user_status_summary.py --detailed | grep -A 10 "username"
```

### 7. Alert on Circuit Breakers
```bash
if python user_status_summary.py --json | jq -e '.users[] | select(.circuit_breaker == true)' > /dev/null; then
    echo "⚠️ ALERT: Circuit breaker triggered!"
fi
```

---

## 📡 Automation Examples

### Cron Job (Every 5 Minutes)
```bash
*/5 * * * * cd /path/to/nija && python user_status_summary.py --json > /var/www/dashboard/live_status.json
```

### Systemd Timer
```ini
[Unit]
Description=NIJA Status Update

[Timer]
OnCalendar=*:0/5
Persistent=true

[Install]
WantedBy=timers.target
```

### Slack Alert on Issues
```bash
#!/bin/bash
STATUS=$(python user_status_summary.py --json)
HIGH_RISK=$(echo "$STATUS" | jq '.users[] | select(.risk_level == "high") | .user_id')

if [ -n "$HIGH_RISK" ]; then
    curl -X POST -H 'Content-type: application/json' \
        --data "{\"text\":\"🚨 High risk users: $HIGH_RISK\"}" \
        $SLACK_WEBHOOK_URL
fi
```

---

## 📞 Support Contacts

| Issue | Contact | Priority |
|-------|---------|----------|
| User trading disabled unexpectedly | Platform Admin | High |
| Circuit breaker triggered | Risk Management | Medium |
| Balance discrepancy | Finance Team | High |
| API connection issues | DevOps | Critical |

---

## 📌 Key Reminders

- ⚡ **Run daily** before market open to check system health
- 🔍 **Monitor 🔴 high risk users** closely throughout the day
- 💾 **Save snapshots** for audit and compliance
- 🚨 **Circuit breakers reset** at midnight UTC
- 📊 **Use JSON mode** for integration with monitoring tools
- 🔒 **All operations are read-only** - safe to run anytime

---

**Last Updated:** February 7, 2026 | **Version:** 1.0 | **Status:** Production Ready
