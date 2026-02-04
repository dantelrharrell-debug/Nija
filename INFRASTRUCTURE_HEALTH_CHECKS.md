# Infrastructure-Grade Health Check System

## Overview

NIJA now implements a production-ready health check system that properly distinguishes between **liveness** (is the process alive?) and **readiness** (can it handle traffic?). This prevents container thrashing, enables proper orchestration, and provides clear operational visibility.

## Key Features

✅ **Proper Liveness/Readiness Separation**
- Liveness probes detect if process is alive (not deadlocked)
- Readiness probes detect if service is ready to handle traffic
- Configuration errors don't trigger restarts

✅ **Configuration Error Handling**
- Configuration issues exit with code 0 (not a crash)
- Service stays alive to report status via health endpoints
- Orchestrators receive accurate signals

✅ **Operational Visibility**
- Clear status information for operators
- Detailed error messages and troubleshooting guidance
- Real-time exchange connectivity status

✅ **Zero Container Thrashing**
- Configuration errors don't cause restart loops
- Proper exit codes for different failure modes
- Graceful degradation when services unavailable

## Health Check Endpoints

### Liveness Probe: `/health` or `/healthz`

**Purpose**: Indicates if the process is alive and not deadlocked.

**HTTP Status**: Always returns `200 OK` if process is running.

**Use Case**: Container orchestrators use this to restart crashed containers.

**Example Response**:
```json
{
  "status": "alive",
  "uptime_seconds": 3600.5,
  "last_heartbeat": "2026-02-04T22:00:00.000000",
  "timestamp": "2026-02-04T22:00:00.000000"
}
```

### Readiness Probe: `/ready` or `/readiness`

**Purpose**: Indicates if the service is ready to handle traffic/trades.

**HTTP Status**: 
- `200 OK` - Service is ready
- `503 Service Unavailable` - Not ready or configuration error

**Use Case**: Load balancers use this to route traffic only to ready instances.

**Example Response (Ready)**:
```json
{
  "status": "ready",
  "ready": true,
  "configuration_valid": true,
  "exchanges": {
    "connected": 2,
    "expected": 2
  },
  "trading": {
    "enabled": true,
    "active_positions": 3,
    "last_trade": "2026-02-04T21:55:00.000000"
  },
  "timestamp": "2026-02-04T22:00:00.000000"
}
```

**Example Response (Configuration Error)**:
```json
{
  "status": "configuration_error",
  "ready": false,
  "configuration_valid": false,
  "exchanges": {
    "connected": 0,
    "expected": 0
  },
  "trading": {
    "enabled": false,
    "active_positions": 0,
    "last_trade": null
  },
  "timestamp": "2026-02-04T22:00:00.000000",
  "configuration_errors": [
    "No exchange credentials configured"
  ],
  "last_error": "No exchange credentials configured"
}
```

### Detailed Status: `/status`

**Purpose**: Comprehensive operational status for debugging and monitoring.

**HTTP Status**: Always `200 OK`

**Example Response**:
```json
{
  "service": "NIJA Trading Bot",
  "version": "7.2.0",
  "liveness": {
    "status": "alive",
    "uptime_seconds": 3600.5,
    "last_heartbeat": "2026-02-04T22:00:00.000000",
    "timestamp": "2026-02-04T22:00:00.000000"
  },
  "readiness": {
    "status": "ready",
    "ready": true,
    "configuration_valid": true,
    "exchanges": {
      "connected": 2,
      "expected": 2
    },
    "trading": {
      "enabled": true,
      "active_positions": 3,
      "last_trade": "2026-02-04T21:55:00.000000"
    },
    "timestamp": "2026-02-04T22:00:00.000000"
  },
  "operational_state": {
    "configuration_checked": true,
    "error_count": 0,
    "uptime_seconds": 3600.5
  }
}
```

## Kubernetes Configuration

### Liveness and Readiness Probes

```yaml
livenessProbe:
  httpGet:
    path: /healthz
    port: 8000
  initialDelaySeconds: 30
  periodSeconds: 10
  timeoutSeconds: 5
  failureThreshold: 3

readinessProbe:
  httpGet:
    path: /ready
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 5
  timeoutSeconds: 3
  failureThreshold: 3
```

### Why This Configuration?

**Liveness Probe**:
- `initialDelaySeconds: 30` - Give service time to start
- `periodSeconds: 10` - Check every 10 seconds
- `failureThreshold: 3` - Restart after 3 consecutive failures (30 seconds)
- Only restarts if process is actually dead/deadlocked

**Readiness Probe**:
- `initialDelaySeconds: 10` - Start checking sooner
- `periodSeconds: 5` - Check more frequently
- `failureThreshold: 3` - Remove from load balancer after 3 failures (15 seconds)
- Doesn't restart on configuration errors

## Railway Configuration

The `railway.json` is configured to use the liveness endpoint:

```json
{
  "deploy": {
    "healthCheckPath": "/healthz",
    "healthCheckTimeout": 10,
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 3
  }
}
```

## Docker Health Check

The Dockerfile includes a health check using the liveness endpoint:

```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:5000/healthz', timeout=5)" || exit 1
```

## Configuration Error Handling

### Before (Old Behavior)
```bash
# No exchange credentials
❌ Bot exits with code 1
❌ Container restarts immediately
❌ Endless restart loop
❌ Wastes resources
❌ Hard to diagnose
```

### After (New Behavior)
```bash
# No exchange credentials
✅ Bot detects configuration error
✅ Exits with code 0 (not a crash)
✅ Container stays stopped
✅ Health endpoints report configuration_error
✅ Operator sees clear error message
✅ No resource waste
```

## Operational States

### 1. Healthy and Ready
- ✅ Configuration valid
- ✅ Exchanges connected
- ✅ Ready to trade
- 🟢 Liveness: 200 OK
- 🟢 Readiness: 200 OK

### 2. Alive but Not Ready
- ✅ Process running
- ⚠️ Exchanges not connected yet
- ⚠️ Not ready to trade
- 🟢 Liveness: 200 OK
- 🔴 Readiness: 503 Service Unavailable

### 3. Configuration Error
- ✅ Process running (to report status)
- ❌ Configuration invalid
- ❌ Cannot trade
- 🟢 Liveness: 200 OK
- 🔴 Readiness: 503 Service Unavailable (with error details)
- Container will NOT restart

### 4. Crashed
- ❌ Process terminated unexpectedly
- ❌ No response from health endpoints
- Container WILL restart

## Testing

### Test Health Check System
```bash
python3 test_health_check_system.py
```

This tests:
- Health manager initialization
- Liveness probe logic
- Readiness probe logic
- Configuration error handling
- Exchange status tracking
- Heartbeat updates

### Test HTTP Endpoints
```bash
python3 test_health_http_endpoints.py
```

This tests:
- `/healthz` endpoint
- `/ready` endpoint
- `/status` endpoint
- 404 responses

### Manual Testing

#### Check Liveness
```bash
curl http://localhost:8080/healthz
```

#### Check Readiness
```bash
curl http://localhost:8080/ready
```

#### Check Detailed Status
```bash
curl http://localhost:8080/status | jq
```

## Benefits

### For Operators
- ✅ **Immediate Understanding**: Clear status messages explain system state
- ✅ **No Guesswork**: Differentiate between crashes and configuration issues
- ✅ **Actionable Errors**: Error messages include fix instructions
- ✅ **No Noise**: Configuration errors don't spam restart logs

### For Orchestrators (Kubernetes, Railway, etc.)
- ✅ **Accurate Signals**: Proper distinction between liveness and readiness
- ✅ **Smart Routing**: Load balancers only route to ready instances
- ✅ **Appropriate Restarts**: Only restart actual crashes, not config errors
- ✅ **Resource Efficiency**: No restart loops burning CPU/memory

### For Developers
- ✅ **Better Debugging**: Detailed status endpoint shows internal state
- ✅ **Easier Testing**: Test endpoints work in any environment
- ✅ **Standard Patterns**: Follows Kubernetes health check best practices
- ✅ **Comprehensive Logging**: Health state changes are logged

## Best Practices

### 1. Use Different Endpoints for Different Purposes
- Use `/healthz` for liveness checks (is it alive?)
- Use `/ready` for readiness checks (can it handle traffic?)
- Use `/status` for debugging and monitoring dashboards

### 2. Don't Confuse Liveness and Readiness
- Liveness = Process is alive and responsive
- Readiness = Service is ready to handle requests
- Configuration errors affect readiness, not liveness

### 3. Monitor Both Probes
- Set up alerts on readiness probe failures
- Investigate liveness probe failures immediately
- Track readiness status over time to spot patterns

### 4. Adjust Timeouts Appropriately
- Liveness: Longer timeouts, fewer retries (avoid false positives)
- Readiness: Shorter timeouts, more aggressive (respond to issues quickly)

## Troubleshooting

### Pod Keeps Restarting
**Check**: Is liveness probe failing?
```bash
kubectl describe pod <pod-name>
# Look for "Liveness probe failed"
```

**Common Causes**:
- Process is actually crashed (correct behavior)
- Timeout too short (increase `timeoutSeconds`)
- Port misconfigured (check health server port)

### Pod Not Receiving Traffic
**Check**: Is readiness probe failing?
```bash
kubectl describe pod <pod-name>
# Look for "Readiness probe failed"
```

**Common Causes**:
- Configuration error (check `/ready` response)
- Exchanges not connected (check exchange status)
- Service initializing (wait for `initialDelaySeconds`)

### Configuration Error Not Visible
**Check**: View detailed status
```bash
curl http://<pod-ip>:8080/status | jq '.readiness'
```

**Look For**:
- `configuration_errors` array
- `last_error` message
- `configuration_valid: false`

## Migration Guide

### From Old Health Checks
If you're upgrading from the old simple health check:

1. **Update Health Check Paths**:
   - Change `/health` to `/healthz` for liveness
   - Add `/ready` for readiness

2. **Update Kubernetes Manifests**:
   - Add separate `livenessProbe` and `readinessProbe`
   - Use recommended timeouts and thresholds

3. **Update Monitoring**:
   - Monitor both probes separately
   - Alert on readiness failures
   - Track configuration errors

4. **Test Thoroughly**:
   - Test configuration error scenarios
   - Verify containers don't restart on config errors
   - Confirm traffic routing works correctly

## Summary

NIJA now behaves as a **proper infrastructure-grade service**:

✅ **Configuration issues do not masquerade as crashes**
- Configuration errors clearly identified and reported
- No restart loops on configuration issues
- Operators immediately understand the problem

✅ **Orchestrators receive accurate health signals**
- Liveness probe: Is the process alive?
- Readiness probe: Can it handle traffic?
- Proper HTTP status codes for each state

✅ **Containers do not thrash or waste resources**
- Configuration errors exit with code 0
- No endless restart loops
- Resources available for actual work

✅ **Operators immediately understand system state**
- Clear, actionable error messages
- Detailed status endpoint for debugging
- Comprehensive logging of state changes

**Status**: Production-ready. Boring in the best possible way. ✅
