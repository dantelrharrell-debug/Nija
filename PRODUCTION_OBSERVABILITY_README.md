# NIJA Production Observability Dashboard

## Overview

This dashboard provides **production-level observability** for critical system failures. It displays adoption failures, broker health issues, and halted trading threads **immediately in RED**, enabling instant response to system issues.

## Features

### 🔴 Critical Failure Detection

The dashboard monitors and displays three critical failure types:

1. **Adoption Failures**
   - User registration failures
   - Broker authentication failures
   - Trading activation failures
   - Shows recent failures with error details

2. **Broker Health**
   - Connection status for each broker (Coinbase, Kraken, etc.)
   - Failed brokers displayed in RED
   - Degraded brokers displayed in ORANGE
   - Real-time error tracking

3. **Trading Thread Status**
   - Active/halted threads per broker
   - Halted threads displayed in RED
   - Thread heartbeat monitoring
   - Automatic deadlock detection

### ⚡ Real-Time Updates

- **Auto-refresh**: Dashboard updates every 5 seconds
- **Immediate alerts**: Failures appear in RED immediately
- **Status indicators**: Clear visual indicators (✅ healthy, 🚨 failed)
- **Pulse animation**: Failed states pulse to draw attention

### 📊 Historical Tracking

- Last 24 hours of failures displayed
- Total failure counts tracked
- Failure event history with timestamps
- Recovery tracking (when issues resolve)

## Quick Start

### 1. Access the Dashboard

Open the HTML dashboard directly in your browser:

```bash
# From the project root
open NIJA_PRODUCTION_OBSERVABILITY_DASHBOARD.html
```

Or serve it via HTTP:

```bash
# Using Python's built-in HTTP server
python3 -m http.server 8000

# Then visit: http://localhost:8000/NIJA_PRODUCTION_OBSERVABILITY_DASHBOARD.html
```

### 2. Start the Founder Dashboard API

The HTML dashboard requires the Founder Dashboard API to be running:

```bash
python founder_dashboard.py
```

This starts the API server on port 5001 (or as configured via `PORT` environment variable).

### 3. Monitor Critical Status

The dashboard will:
- ✅ Show **GREEN** when all systems are healthy
- 🚨 Show **RED** immediately when failures occur
- ⚡ Auto-refresh every 5 seconds
- 📊 Display detailed failure information

## API Endpoints

### Production Observability Endpoints

```bash
# Get complete critical status
GET /api/founder/critical-status

# Get adoption failures only
GET /api/founder/adoption-failures

# Get broker health only
GET /api/founder/broker-health

# Get trading thread status only
GET /api/founder/trading-threads
```

### Example Response

```json
{
  "adoption": {
    "status": "failed",
    "recent_failures": 2,
    "total_failures": 5,
    "last_failure": "2026-02-17T20:48:28.269Z",
    "failures": [
      {
        "type": "broker_auth",
        "user_id": "user_123",
        "error": "Invalid API key",
        "timestamp_iso": "2026-02-17T20:48:28.269Z"
      }
    ]
  },
  "broker_health": {
    "status": "failed",
    "failed_brokers": ["coinbase"],
    "degraded_brokers": [],
    "recent_failures": 1,
    "broker_status": {
      "coinbase": {
        "status": "failed",
        "error_count": 3,
        "last_error": "Connection timeout"
      }
    }
  },
  "trading_threads": {
    "status": "halted",
    "halted_threads": ["coinbase"],
    "halted_count": 1,
    "thread_status": {
      "coinbase": {
        "status": "halted",
        "last_heartbeat": 1708201708.27,
        "thread_id": 12345
      }
    }
  }
}
```

## Integration Guide

### Recording Adoption Failures

```python
from bot.health_check import get_health_manager

health_mgr = get_health_manager()

# Record adoption failure
health_mgr.record_adoption_failure(
    failure_type='broker_auth',  # or 'registration', 'trading_activation'
    user_id='user_123',
    error_message='Failed to authenticate with Coinbase API'
)
```

### Updating Broker Health

```python
from bot.health_check import get_health_manager

health_mgr = get_health_manager()

# Report broker failure
health_mgr.update_broker_health(
    broker_name='coinbase',
    status='failed',  # or 'healthy', 'degraded'
    error_message='Connection timeout after 30 seconds'
)

# Report broker recovery
health_mgr.update_broker_health(
    broker_name='coinbase',
    status='healthy'
)
```

### Updating Trading Thread Status

```python
from bot.health_check import get_health_manager
import threading

health_mgr = get_health_manager()

# Update thread status
health_mgr.update_trading_thread_status(
    broker_name='coinbase',
    status='running',  # or 'halted', 'idle', 'error'
    thread_id=threading.get_ident()
)

# Report thread halt
health_mgr.update_trading_thread_status(
    broker_name='coinbase',
    status='halted',
    thread_id=threading.get_ident()
)
```

## Testing

Run the test suite to verify all observability features:

```bash
python test_production_observability.py
```

This tests:
- ✅ Adoption failure tracking
- ✅ Broker health monitoring
- ✅ Trading thread status tracking
- ✅ Recovery scenarios
- ✅ Prometheus metrics export
- ✅ API endpoints (if Flask is available)

## Prometheus Metrics

The health check system exports Prometheus-compatible metrics:

```bash
# Get Prometheus metrics
curl http://localhost:5001/metrics
```

Key metrics for production observability:

```prometheus
# Adoption failures
nija_adoption_failures_total

# Broker health
nija_broker_failures_total
nija_brokers_failed

# Trading threads
nija_trading_threads_halted
```

## Dashboard Features

### Visual Indicators

- **🚨 RED with pulse animation**: Critical failures requiring immediate attention
- **⚠️ ORANGE**: Degraded state, needs monitoring
- **✅ GREEN**: Healthy, all systems operational

### Auto-Refresh

- Dashboard auto-refreshes every 5 seconds by default
- Click "Auto-refresh: ON" to toggle auto-refresh
- Last update time displayed in header

### Failure Details

Each failure type shows:
- Current status (healthy/failed/degraded)
- Count of recent failures (last 24 hours)
- Total failure count (all time)
- Last failure timestamp
- Detailed error messages for recent failures

## Deployment

### Production Deployment

1. **Deploy Founder Dashboard API**:
   ```bash
   # Using Railway
   railway up
   
   # Or Docker
   docker build -t nija-dashboard .
   docker run -p 5001:5001 nija-dashboard
   ```

2. **Serve HTML Dashboard**:
   - Static hosting (S3, CloudFront, etc.)
   - Nginx/Apache
   - Integrated with main application

3. **Configure API URL**:
   The dashboard uses `window.location.origin` by default. For cross-domain deployments, update the `API_BASE_URL` in the HTML file:
   
   ```javascript
   const API_BASE_URL = 'https://your-api-domain.com';
   ```

### Security Considerations

- ⚠️ **Authentication**: Add authentication to protect the dashboard
- 🔒 **HTTPS**: Always use HTTPS in production
- 🛡️ **Rate limiting**: Implement rate limiting on API endpoints
- 👥 **Access control**: Restrict access to authorized operators only

## Monitoring Best Practices

### What to Monitor

1. **Adoption Failures**
   - High failure rate = onboarding issues
   - Check API credentials, network connectivity
   - Review error messages for patterns

2. **Broker Health**
   - Failed brokers = trading disruption
   - Check exchange status pages
   - Verify API credentials and rate limits

3. **Trading Threads**
   - Halted threads = no trading happening
   - Check for deadlocks, exceptions
   - Review thread logs for root cause

### Alert Thresholds

Recommended alert thresholds:

- **Critical**: Any broker in failed state
- **Critical**: Any trading thread halted
- **Warning**: >5 adoption failures in 1 hour
- **Warning**: Any broker degraded for >10 minutes

### Response Playbook

**When Dashboard Shows RED:**

1. **Immediate Actions**
   - Review failure details in dashboard
   - Check system logs for root cause
   - Verify network connectivity
   - Check broker status pages

2. **Adoption Failures**
   - Verify API credentials
   - Check user input validation
   - Review onboarding flow

3. **Broker Health Failed**
   - Check broker status page
   - Verify API credentials
   - Test connectivity manually
   - Consider failover to backup broker

4. **Trading Thread Halted**
   - Check application logs
   - Look for exceptions/errors
   - Restart trading thread
   - Investigate deadlock if recurring

## Troubleshooting

### Dashboard Shows "Error loading data"

1. Check if Founder Dashboard API is running:
   ```bash
   curl http://localhost:5001/api/health
   ```

2. Check API logs for errors:
   ```bash
   tail -f logs/founder_dashboard.log
   ```

3. Verify CORS settings if accessing from different domain

### Dashboard Not Updating

1. Check auto-refresh is ON (top right of dashboard)
2. Check browser console for JavaScript errors
3. Verify API endpoints are responding:
   ```bash
   curl http://localhost:5001/api/founder/critical-status
   ```

### Metrics Not Showing

1. Ensure health check manager is initialized:
   ```python
   from bot.health_check import get_health_manager
   health_mgr = get_health_manager()
   ```

2. Verify metrics are being recorded (check logs)

3. Test metrics endpoint:
   ```bash
   curl http://localhost:5001/metrics
   ```

## Architecture

### Component Diagram

```
┌─────────────────────────────────────────────┐
│   NIJA Production Observability Dashboard   │
│           (HTML + JavaScript)               │
└─────────────────┬───────────────────────────┘
                  │ HTTP/REST
                  ▼
┌─────────────────────────────────────────────┐
│      Founder Dashboard API (Flask)          │
│   /api/founder/critical-status              │
│   /api/founder/adoption-failures            │
│   /api/founder/broker-health                │
│   /api/founder/trading-threads              │
└─────────────────┬───────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────┐
│      Health Check Manager (Singleton)       │
│   - Adoption failure tracking               │
│   - Broker health monitoring                │
│   - Trading thread status                   │
│   - Prometheus metrics export               │
└─────────────────┬───────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────┐
│         NIJA Trading Bot Components         │
│   - Broker Manager                          │
│   - Trading Strategy                        │
│   - Independent Broker Trader               │
└─────────────────────────────────────────────┘
```

## Next Steps

### Future Enhancements

1. **Alert Integration**
   - PagerDuty integration
   - Slack/Discord webhooks
   - Email notifications

2. **Advanced Analytics**
   - Failure trend analysis
   - Recovery time tracking
   - SLO/SLA monitoring

3. **Distributed Tracing**
   - Request correlation IDs
   - Cross-service tracing
   - Performance monitoring

4. **Mobile Dashboard**
   - Responsive design
   - Push notifications
   - Offline support

## Support

For issues or questions:
- Check the troubleshooting section
- Review system logs
- Run test suite: `python test_production_observability.py`
- Check GitHub issues

## Version

- **Dashboard Version**: 1.0.0
- **NIJA Version**: 7.2.0
- **Last Updated**: February 17, 2026

---

**Production-Ready Observability** ✅
- Adoption failures: Tracked and displayed in RED
- Broker health: Monitored and failures shown in RED
- Trading threads: Status tracked and halts shown in RED
- Real-time updates: Auto-refresh every 5 seconds
- Prometheus metrics: Full metric export support
