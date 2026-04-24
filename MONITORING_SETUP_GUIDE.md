# NIJA Live Status Monitoring - Setup Guide

Complete guide for deploying continuous status monitoring with alerting and snapshot persistence.

## 🎯 Features Implemented

✅ **CLI Filters** - Target specific users or brokers
✅ **Alerting System** - Automated notifications for issues  
✅ **Snapshot Persistence** - Historical audit trails
✅ **Supervisor Integration** - Continuous monitoring daemon
✅ **Systemd Services** - Production deployment options

---

## 📦 Quick Start

### 1. Basic Usage with New Features

```bash
# Filter by specific user
python user_status_summary.py --user john_trader

# Filter by broker
python user_status_summary.py --broker kraken

# Filter by risk level
python user_status_summary.py --risk-level high

# Save snapshot
python user_status_summary.py --snapshot snapshots/daily.json

# Combine filters
python user_status_summary.py --user alice,bob --broker coinbase --json
```

### 2. Run Alert Check

```bash
# Check for alerts (dry run)
python status_alerts.py --check-only

# Send alerts to Slack
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/YOUR/WEBHOOK"
python status_alerts.py

# Send alerts via email
export ALERT_EMAIL="admin@example.com"
python status_alerts.py --email admin@example.com
```

### 3. Start Monitoring Daemon

```bash
# Run monitor with 5-minute intervals
python status_monitor.py --interval 300

# Custom snapshot directory
python status_monitor.py --snapshot-dir /var/nija/snapshots
```

---

## 🔧 Production Deployment

### Option 1: Systemd (Recommended for Linux)

**Installation:**

```bash
# Copy service files
sudo cp deployment/systemd/*.service /etc/systemd/system/
sudo cp deployment/systemd/*.timer /etc/systemd/system/

# Update paths in service files
sudo nano /etc/systemd/system/nija-status-monitor.service
# Change /opt/nija to your installation path

# Enable and start services
sudo systemctl daemon-reload
sudo systemctl enable nija-status-monitor.service
sudo systemctl enable nija-alerts.timer
sudo systemctl start nija-status-monitor.service
sudo systemctl start nija-alerts.timer

# Check status
sudo systemctl status nija-status-monitor
sudo systemctl status nija-alerts.timer
```

**View Logs:**

```bash
# Monitor daemon logs
sudo journalctl -u nija-status-monitor -f

# Check alert logs
sudo journalctl -u nija-alerts -f
```

### Option 2: Supervisor

**Installation:**

```bash
# Copy configuration
sudo cp deployment/supervisor/nija-monitoring.conf /etc/supervisor/conf.d/

# Update paths
sudo nano /etc/supervisor/conf.d/nija-monitoring.conf

# Reload supervisor
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start nija-status-monitor
```

**Monitor:**

```bash
# Check status
sudo supervisorctl status nija-status-monitor

# View logs
sudo supervisorctl tail -f nija-status-monitor
```

### Option 3: Cron Jobs (Simple)

**Setup:**

```bash
# Edit crontab
crontab -e

# Add entries:
# Run status monitor every 5 minutes
*/5 * * * * cd /opt/nija && python status_monitor.py --interval 1 >> /var/log/nija/monitor.log 2>&1

# Check alerts every 15 minutes
*/15 * * * * cd /opt/nija && python status_alerts.py >> /var/log/nija/alerts.log 2>&1

# Daily snapshot at midnight
0 0 * * * cd /opt/nija && python user_status_summary.py --snapshot snapshots/daily_$(date +\%Y\%m\%d).json
```

---

## 🚨 Alerting Configuration

### Slack Integration

```bash
# Set webhook URL
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/YOUR/WEBHOOK/URL"

# Test alert
python status_alerts.py

# Add to systemd service
sudo nano /etc/systemd/system/nija-alerts.service
# Add: Environment="SLACK_WEBHOOK_URL=https://hooks.slack.com/..."
```

### Email Alerts

```bash
# Install mail utility (if needed)
sudo apt-get install mailutils

# Set recipient
export ALERT_EMAIL="admin@example.com"

# Test
python status_alerts.py --email admin@example.com
```

### Custom Alert Thresholds

Edit `status_alerts.py`:

```python
# Alert thresholds (line ~35)
HIGH_RISK_THRESHOLD = 5.0  # Daily loss % for high risk
MEDIUM_RISK_THRESHOLD = 2.0  # Daily loss % for medium risk
LOW_BALANCE_THRESHOLD = 100.0  # Minimum balance in USD
```

---

## 💾 Snapshot Management

### Automatic Snapshots

The monitoring daemon automatically:
- Saves timestamped snapshots every check
- Maintains daily snapshots (overwritten each day)
- Cleans up snapshots older than 30 days

### Manual Snapshots

```bash
# Save current status
python user_status_summary.py --snapshot snapshots/manual_$(date +%Y%m%d_%H%M).json

# Save filtered snapshot
python user_status_summary.py --user high_value_user --snapshot snapshots/vip.json

# Save to remote location
python user_status_summary.py --snapshot /mnt/backup/nija/status.json
```

### Snapshot Locations

Default: `snapshots/`
- `status_YYYYMMDD_HHMMSS.json` - Timestamped snapshots
- `daily_YYYYMMDD.json` - Daily snapshot (one per day)

### Retrieving Historical Data

```bash
# List all snapshots
ls -lh snapshots/

# View specific snapshot
cat snapshots/status_20260207_120000.json | jq '.platform_overview'

# Compare two snapshots
diff <(jq '.platform_overview' snapshots/status_20260207_0900.json) \
     <(jq '.platform_overview' snapshots/status_20260207_1700.json)

# Get balance history for user
for f in snapshots/status_2026020*.json; do
    echo -n "$(basename $f): "
    jq -r '.users[] | select(.user_id == "john_trader") | .total_balance_usd' "$f"
done
```

---

## 🔍 CLI Filters Usage

### Filter by User

```bash
# Single user
python user_status_summary.py --user alice_investor

# Multiple users
python user_status_summary.py --user "alice,bob,charlie"

# User with detailed info
python user_status_summary.py --user alice --detailed
```

### Filter by Broker

```bash
# Show only Kraken users
python user_status_summary.py --broker kraken

# Show only Coinbase users
python user_status_summary.py --broker coinbase

# Combine with other filters
python user_status_summary.py --broker kraken --risk-level high
```

### Filter by Risk Level

```bash
# High risk users only
python user_status_summary.py --risk-level high

# Profitable users
python user_status_summary.py --risk-level profitable

# Medium risk with details
python user_status_summary.py --risk-level medium --detailed
```

### Combined Filters

```bash
# High-risk Kraken users
python user_status_summary.py --broker kraken --risk-level high

# Specific users on specific broker
python user_status_summary.py --user "alice,bob" --broker coinbase --json

# Save filtered snapshot
python user_status_summary.py --risk-level high --snapshot alerts/high_risk.json
```

---

## 📊 Dashboard Integration

### Web Dashboard

```python
# Flask endpoint example
from flask import Flask, jsonify
import subprocess
import json

app = Flask(__name__)

@app.route('/api/status')
def get_status():
    result = subprocess.run(
        ['python', 'user_status_summary.py', '--json', '--quiet'],
        capture_output=True,
        text=True
    )
    return jsonify(json.loads(result.stdout))

@app.route('/api/status/<user_id>')
def get_user_status(user_id):
    result = subprocess.run(
        ['python', 'user_status_summary.py', '--user', user_id, '--json', '--quiet'],
        capture_output=True,
        text=True
    )
    return jsonify(json.loads(result.stdout))
```

### Grafana Integration

```bash
# Create data source script
cat > /usr/local/bin/nija-metrics << 'EOF'
#!/bin/bash
python /opt/nija/user_status_summary.py --json --quiet
EOF

chmod +x /usr/local/bin/nija-metrics

# Use JSON API plugin in Grafana to query this endpoint
```

---

## 🔐 Security Considerations

### File Permissions

```bash
# Restrict access to snapshot directory
chmod 700 snapshots
chown nija:nija snapshots

# Protect service files
chmod 600 deployment/systemd/*.service
```

### Environment Variables

Never commit credentials to version control:

```bash
# Use environment files
sudo nano /etc/environment
# Add:
# DATABASE_URL="postgresql://..."
# SLACK_WEBHOOK_URL="..."

# Or use systemd EnvironmentFile
sudo nano /etc/systemd/system/nija-status-monitor.service
# Add: EnvironmentFile=/opt/nija/.env
```

### Log Rotation

```bash
# Create logrotate config
sudo nano /etc/logrotate.d/nija

# Add:
/var/log/nija/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
}
```

---

## 🐛 Troubleshooting

### Monitor Not Starting

```bash
# Check logs
sudo journalctl -u nija-status-monitor -n 50

# Test manually
python status_monitor.py --interval 60

# Check permissions
ls -la status_monitor.py
```

### Alerts Not Sending

```bash
# Test Slack webhook
curl -X POST -H 'Content-type: application/json' \
    --data '{"text":"Test"}' \
    $SLACK_WEBHOOK_URL

# Run alert check manually
python status_alerts.py --check-only

# Check environment variables
env | grep -E '(SLACK|EMAIL|DATABASE)'
```

### Snapshots Not Saving

```bash
# Check directory permissions
ls -ld snapshots/

# Check disk space
df -h

# Test manually
python user_status_summary.py --snapshot test.json
```

---

## 📈 Performance Tuning

### Adjust Check Intervals

```bash
# Fast monitoring (1 minute)
python status_monitor.py --interval 60

# Standard (5 minutes)
python status_monitor.py --interval 300

# Light load (15 minutes)
python status_monitor.py --interval 900
```

### Optimize Snapshot Retention

Edit `status_monitor.py`:

```python
# Keep snapshots for 7 days instead of 30
self._cleanup_old_snapshots(days=7)
```

---

## 📚 Additional Resources

- **Operators Dashboard Guide:** `OPERATORS_DASHBOARD_GUIDE.md`
- **Quick Launcher:** `./dashboard.sh` - Convenient command shortcuts
- **User Status Script:** `user_status_summary.py` - Core monitoring tool
- **Alert System:** `status_alerts.py` - Notification system
- **Monitor Daemon:** `status_monitor.py` - Continuous monitoring

---

**Last Updated:** February 7, 2026 | **Version:** 1.0
