# NIJA Operational Safety Procedures

**Version**: 1.0  
**Date**: February 4, 2026  
**Status**: ACTIVE

This document outlines operational safety procedures for the NIJA trading platform, including emergency response, alerting, and schema management.

---

## Table of Contents

1. [Kill-Switch Procedures](#kill-switch-procedures)
2. [Alert Monitoring](#alert-monitoring)
3. [Database Schema Management](#database-schema-management)
4. [Emergency Response](#emergency-response)

---

## Kill-Switch Procedures

The NIJA kill-switch is an emergency mechanism to **immediately halt all trading operations**. It's designed to be reachable in **<30 seconds** from multiple interfaces.

### When to Activate

Activate the kill-switch when:

- ❌ Uncontrolled losses detected
- ❌ API errors causing erratic behavior
- ❌ Suspicious trading activity
- ❌ System malfunction or bug discovered
- ❌ Security breach suspected
- ❌ Platform outage affecting trades
- ❌ Any situation requiring immediate trading halt

### Activation Methods

#### Method 1: CLI (Fastest - <5 seconds)

```bash
# Emergency activation
python emergency_kill_switch.py activate "Reason for emergency stop"

# Quick activation with default reason
python emergency_kill_switch.py activate emergency

# Check status
python emergency_kill_switch.py status
```

#### Method 2: API Endpoint (<10 seconds)

```bash
# Activate (NO AUTH REQUIRED for emergency)
curl -X POST http://localhost:5000/api/emergency/kill-switch/activate \
  -H "Content-Type: application/json" \
  -d '{"reason": "Emergency halt", "source": "MANUAL"}'

# Check status
curl http://localhost:5000/api/emergency/kill-switch/status
```

#### Method 3: Python Code (<1 second)

```python
from bot.kill_switch import get_kill_switch

kill_switch = get_kill_switch()
kill_switch.activate("Reason for halt", source="MANUAL")
```

#### Method 4: File System (Manual - <10 seconds)

```bash
# Create emergency stop file
touch EMERGENCY_STOP

# The system will detect this file and halt trading
```

### Deactivation Procedures

**⚠️ IMPORTANT**: Only deactivate after:

1. Understanding why it was activated
2. Resolving the underlying issue
3. Verifying system integrity
4. Ensuring it's safe to resume

#### Deactivation via CLI

```bash
# Deactivate (requires confirmation)
python emergency_kill_switch.py deactivate "Issue resolved, resuming trading"
```

#### Deactivation via API

```bash
# Deactivate (REQUIRES AUTHENTICATION)
curl -X POST http://localhost:5000/api/emergency/kill-switch/deactivate \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -d '{"reason": "Issue resolved"}'
```

### Verification

After deactivation:

1. ✅ Check system logs for errors
2. ✅ Verify API connectivity
3. ✅ Check account balances
4. ✅ Review recent trades
5. ✅ Monitor first few trades closely
6. ✅ Verify risk management is active

---

## Alert Monitoring

NIJA includes a comprehensive alerting system that monitors critical conditions and can auto-activate the kill-switch.

### Alert Types

| Alert Type | Level | Description | Auto Kill-Switch |
|------------|-------|-------------|------------------|
| **ORDER_STUCK** | CRITICAL | Order pending > max age (5 min default) | Optional (3x threshold) |
| **ADOPTION_GUARDRAIL** | EMERGENCY | Too many active users (>80% default) | Configurable |
| **PLATFORM_EXPOSURE** | EMERGENCY | High concentration on one platform (>30% default) | Configurable (1.5x threshold) |
| BALANCE_LOW | CRITICAL | Balance below threshold | No |
| BALANCE_DROP | WARNING | Significant balance drop | No |
| CONSECUTIVE_LOSSES | WARNING | Multiple losses in a row | No |
| HIGH_ERROR_RATE | CRITICAL | API error rate too high | No |

### Monitoring Configuration

Edit `bot/monitoring_system.py` to adjust thresholds:

```python
# Alert thresholds (in __init__)
self.max_order_age_seconds = 300  # 5 minutes
self.max_adoption_rate_pct = 80.0  # 80%
self.max_platform_exposure_pct = 30.0  # 30%
```

### Checking Alerts

```python
from bot.monitoring_system import monitoring

# Get recent alerts
status = monitoring.check_health()
print(monitoring.get_summary())

# Check for stuck orders
stuck_orders = monitoring.check_stuck_orders()

# Check adoption guardrail
monitoring.check_adoption_guardrail(
    active_users=50,
    total_users=100,
    auto_trigger_kill_switch=False
)

# Check platform exposure
monitoring.check_platform_exposure(
    platform_balances={
        'Coinbase': 1000.0,
        'Kraken': 500.0
    },
    total_balance=1500.0,
    auto_trigger_kill_switch=False
)
```

### Alert Response Procedures

#### ORDER_STUCK Alert

1. **Investigate**: Check broker API status
2. **Manual Action**: Cancel stuck orders via broker UI
3. **Resolution**: Update order timeout threshold if needed
4. **Prevention**: Implement retry logic or timeout handling

#### ADOPTION_GUARDRAIL Alert

1. **Assess**: Determine if adoption spike is expected
2. **Scale**: Add resources if needed (API rate limits, compute)
3. **Throttle**: Consider temporary user limits
4. **Communicate**: Notify users if service degradation possible

#### PLATFORM_EXPOSURE Alert

1. **Review**: Check if concentration is intentional
2. **Diversify**: Move funds to other platforms if needed
3. **Risk Assessment**: Evaluate platform-specific risks
4. **Adjust**: Update exposure thresholds if appropriate

---

## Database Schema Management

All database schema changes **MUST** go through the Alembic migration system.

### Schema Freeze Policy

**FROZEN**: Direct schema changes are prohibited. See [DATABASE_MIGRATION_POLICY.md](DATABASE_MIGRATION_POLICY.md)

### Creating a Migration

```bash
# Generate migration file
alembic revision -m "description_of_change"

# Edit the generated file in alembic/versions/
# Implement upgrade() and downgrade()

# Test migration
alembic upgrade head
alembic downgrade -1
alembic upgrade head

# Stage migration for commit
git add alembic/versions/your_migration.py
```

### Pre-Commit Protection

A pre-commit hook automatically detects schema changes without migrations:

```bash
# Install pre-commit
pip install pre-commit
pre-commit install

# The hook will run automatically on git commit
# It will reject commits with schema changes but no migration
```

To bypass (NOT RECOMMENDED):

```bash
git commit --no-verify
```

### Safe Schema Changes

✅ **Allowed**:
- Adding nullable columns
- Creating new tables
- Adding indexes
- Adding columns with defaults

❌ **Dangerous** (requires planning):
- Dropping columns/tables
- Renaming columns/tables
- Changing column types
- Adding NOT NULL constraints

---

## Emergency Response

### Emergency Checklist

When an emergency occurs:

1. ⚠️ **HALT TRADING** - Activate kill-switch immediately
   ```bash
   python emergency_kill_switch.py activate emergency
   ```

2. 🔍 **ASSESS** - Determine the scope and severity
   - Check logs: `tail -f logs/nija.log`
   - Check balances: Review broker accounts
   - Check positions: Identify open trades

3. 📊 **ANALYZE** - Understand what went wrong
   - Review recent trades
   - Check API errors
   - Examine system metrics

4. 🛠️ **FIX** - Resolve the underlying issue
   - Fix code bugs
   - Resolve API issues
   - Update configurations

5. ✅ **VERIFY** - Ensure system is stable
   - Test fixes in staging
   - Verify API connectivity
   - Check risk management

6. 🔄 **RESUME** - Carefully restart trading
   ```bash
   python emergency_kill_switch.py deactivate "Issue resolved"
   ```

7. 👀 **MONITOR** - Watch closely for issues
   - Monitor first few trades
   - Check alerts
   - Review system metrics

### Communication

During emergencies:

- **Log everything**: Document actions taken
- **Notify team**: Alert relevant team members
- **Record lessons**: Document what happened and how to prevent

### Post-Incident Review

After resolving an emergency:

1. Document what happened
2. Identify root cause
3. Implement preventive measures
4. Update procedures if needed
5. Share learnings with team

---

## Testing Operational Safety

Run the operational safety test suite:

```bash
python test_operational_safety.py
```

Expected results:
- ✅ Kill-switch activation <1 second
- ✅ CLI response <2 seconds
- ✅ All alerts working correctly
- ✅ Status retrieval functional

---

## Monitoring Dashboards

### Kill-Switch Status

```bash
# Quick status check
python emergency_kill_switch.py status

# Detailed status
from bot.kill_switch import get_kill_switch
print(get_kill_switch().get_status())
```

### System Health

```python
from bot.monitoring_system import monitoring

# Health check
health = monitoring.check_health()

# Summary
print(monitoring.get_summary())

# Recent alerts
print(monitoring.alerts[-10:])
```

---

## Contacts & Resources

- **Documentation**: See all `*.md` files in repository
- **Kill-Switch**: `emergency_kill_switch.py`
- **Monitoring**: `bot/monitoring_system.py`
- **Migrations**: `alembic/versions/`

---

## Appendix: API Endpoints

### Emergency Endpoints (No Auth)

- `GET /api/emergency/kill-switch/status` - Check kill-switch status
- `POST /api/emergency/kill-switch/activate` - Activate kill-switch

### Protected Endpoints (Auth Required)

- `POST /api/emergency/kill-switch/deactivate` - Deactivate kill-switch

---

**Last Updated**: February 4, 2026  
**Review Frequency**: Monthly
