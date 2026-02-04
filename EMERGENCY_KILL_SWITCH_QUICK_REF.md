# Quick Reference: Emergency Kill-Switch

**⏱️ Target: <30 seconds activation**  
**✅ Actual: <1 second activation**

---

## Emergency Activation (Choose One)

### Option 1: CLI (Fastest)
```bash
python emergency_kill_switch.py activate emergency
```

### Option 2: API
```bash
curl -X POST http://localhost:5000/api/emergency/kill-switch/activate \
  -H "Content-Type: application/json" \
  -d '{"reason": "Emergency halt"}'
```

### Option 3: File System
```bash
touch EMERGENCY_STOP
```

---

## Check Status

```bash
# CLI
python emergency_kill_switch.py status

# API
curl http://localhost:5000/api/emergency/kill-switch/status
```

---

## Deactivation (After Resolving Issue)

```bash
# CLI (requires confirmation)
python emergency_kill_switch.py deactivate "Issue resolved"

# API (requires auth token)
curl -X POST http://localhost:5000/api/emergency/kill-switch/deactivate \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{"reason": "Resolved"}'
```

---

## Alert Monitoring

### Check for Critical Alerts

```python
from bot.monitoring_system import monitoring

# Check stuck orders
stuck = monitoring.check_stuck_orders()

# Check adoption guardrail
monitoring.check_adoption_guardrail(active_users=50, total_users=100)

# Check platform exposure
monitoring.check_platform_exposure(
    platform_balances={'Coinbase': 1000.0},
    total_balance=1500.0
)
```

### Alert Thresholds

| Alert | Threshold | Auto Kill-Switch |
|-------|-----------|------------------|
| Order Stuck | 5 minutes | Optional (15 min) |
| Adoption Rate | 80% | Configurable |
| Platform Exposure | 30% | Configurable (45%) |

---

## Testing

```bash
# Run operational safety tests
python test_operational_safety.py

# Expected: 7/7 tests pass
```

---

## Documentation

- **Detailed Procedures**: `OPERATIONAL_SAFETY_PROCEDURES.md`
- **Schema Policy**: `DATABASE_MIGRATION_POLICY.md`
- **Main README**: `README.md`

---

## Emergency Contacts

In case of emergency:
1. Activate kill-switch immediately
2. Review logs: `tail -f logs/nija.log`
3. Check positions via broker UI
4. Follow procedures in OPERATIONAL_SAFETY_PROCEDURES.md
