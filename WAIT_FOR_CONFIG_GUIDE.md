# Wait-for-Config Mode Guide

## Overview

NIJA now supports a **wait-for-config** mode that prevents restart loops while providing clear, machine-readable health signals. This is production-grade infrastructure behavior that Railway, Kubernetes, and human operators expect.

## The Problem

Without wait-for-config mode:
- Missing credentials → container exits → restart loop
- No way to distinguish "waiting for config" from "crashed"
- Humans and orchestrators can't query deployment status
- Wastes resources and creates alert fatigue

## The Solution

With wait-for-config mode enabled:
- Missing credentials → container stays running
- Health endpoint reports clear status: BLOCKED, READY, or ERROR
- No restart loops, no wasted resources
- Debuggable in seconds instead of minutes

## Three-State Health Model

The health endpoint (`/healthz`, `/health`, `/status`) reports one of three states:

### 1. BLOCKED (HTTP 503 - Service Unavailable)

**When**: Required credentials are missing  
**HTTP Status**: 503  
**Railway Behavior**: Container runs, health check fails  
**Action Required**: Add credentials and restart

**Example Response**:
```json
{
  "status": "blocked",
  "state": "awaiting_configuration",
  "message": "Waiting for configuration",
  "config_status": "missing_credentials",
  "required": {
    "KRAKEN_PLATFORM_API_KEY": "Kraken API key (required)",
    "KRAKEN_PLATFORM_API_SECRET": "Kraken API secret (required)"
  },
  "action_required": "Set environment variables and restart deployment"
}
```

### 2. READY (HTTP 200 - OK)

**When**: Configuration is complete, bot is operational  
**HTTP Status**: 200  
**Railway Behavior**: Container healthy, service available  
**Action Required**: None

**Example Response**:
```json
{
  "status": "ready",
  "state": "configured",
  "message": "Configuration is complete, bot is ready to trade",
  "config_status": "credentials_configured",
  "credentials": {
    "kraken_platform": "configured"
  }
}
```

### 3. ERROR (HTTP 500 - Internal Server Error)

**When**: Hard error detected (emergency stop, corrupted files, etc.)  
**HTTP Status**: 500  
**Railway Behavior**: Container unhealthy, needs intervention  
**Action Required**: Investigate logs, fix issue, may need redeploy

**Example Response (Emergency Stop)**:
```json
{
  "status": "error",
  "state": "emergency_stopped",
  "message": "Emergency stop is active",
  "action_required": "Remove EMERGENCY_STOP file to resume"
}
```

**Example Response (Corrupted Deployment)**:
```json
{
  "status": "error",
  "state": "corrupted_deployment",
  "message": "Critical files missing",
  "missing_files": ["bot.py"],
  "action_required": "Redeploy from clean image"
}
```

## Usage

### Method 1: Command Line Argument

```bash
./start.sh --wait-for-config
```

### Method 2: Environment Variable

```bash
export WAIT_FOR_CONFIG=true
./start.sh
```

### Method 3: Railway Configuration

In Railway dashboard:
1. Go to your service settings
2. Add environment variable: `WAIT_FOR_CONFIG=true`
3. Deploy

Or in `railway.json`:
```json
{
  "build": {
    "builder": "DOCKERFILE"
  },
  "deploy": {
    "startCommand": "./start.sh --wait-for-config",
    "healthcheckPath": "/healthz",
    "restartPolicyType": "ON_FAILURE"
  }
}
```

## Querying Health Status

### From Railway Dashboard
Railway will automatically poll `/healthz` if configured in `railway.json`

### From Command Line
```bash
# Check status
curl http://localhost:8080/healthz

# Check status with headers (see HTTP status code)
curl -i http://localhost:8080/healthz

# Pretty print JSON
curl -s http://localhost:8080/healthz | python3 -m json.tool
```

### From Monitoring/Alerting
Set up alerts based on HTTP status codes:
- **503** → Send notification "NIJA waiting for config"
- **200** → All clear
- **500** → Send urgent alert "NIJA has hard error"

## Debugging Workflow

### Scenario 1: Deployment shows unhealthy

```bash
# 1. Check health endpoint
curl -i https://your-railway-app.up.railway.app/healthz

# 2. Interpret the status code
#    - 503 = missing config → add credentials
#    - 200 = healthy → check bot logs for other issues
#    - 500 = hard error → check error message in response

# 3. If BLOCKED (503), add credentials in Railway dashboard
#    Then restart deployment
```

### Scenario 2: Want to verify config before deploying

```bash
# 1. Deploy with WAIT_FOR_CONFIG=true
# 2. Health check will report BLOCKED
# 3. Add credentials via Railway UI
# 4. Restart deployment
# 5. Health check will report READY
```

### Scenario 3: Emergency stop active

```bash
# 1. Health endpoint reports ERROR (500) with "emergency_stopped"
# 2. Investigate why EMERGENCY_STOP file exists
# 3. Remove file: Delete EMERGENCY_STOP via Railway shell or redeploy
# 4. Restart deployment
```

## Production Best Practices

### 1. Always Enable in Production
```bash
# Add to your production environment
WAIT_FOR_CONFIG=true
```

### 2. Configure Health Check Path
In `railway.json`:
```json
{
  "deploy": {
    "healthcheckPath": "/healthz",
    "healthcheckTimeout": 300
  }
}
```

### 3. Set Up Monitoring
Monitor the health endpoint and alert on:
- Prolonged BLOCKED state (config not added after 1 hour)
- ERROR state (immediate escalation)
- READY → BLOCKED transition (credentials removed?)

### 4. Document Your Deployment
In your deployment docs, include:
1. Health endpoint URL
2. Expected states and what they mean
3. How to add/update credentials
4. Escalation path for ERROR states

## Backward Compatibility

**Default behavior (WAIT_FOR_CONFIG=false)**:
- Same as before: exits with code 0 when config missing
- No health server in wait mode
- Container stops (no restart loop)

**New behavior (WAIT_FOR_CONFIG=true)**:
- Starts health server on missing config
- Reports BLOCKED (503)
- Container keeps running
- No restart loop
- Clear status signals

## Technical Details

### Health Server Implementation
- **File**: `config_health_server.py`
- **Port**: Reads from `$PORT` environment variable (default: 8080)
- **Protocol**: HTTP/1.0
- **Endpoints**: `/health`, `/healthz`, `/status`, `/`
- **Response Format**: JSON

### State Detection Logic
1. Check for EMERGENCY_STOP file → ERROR
2. Check for missing critical files → ERROR
3. Check for credentials → BLOCKED or READY
4. Any exception in health handler → ERROR

### Integration with start.sh
1. Parse `--wait-for-config` flag and `WAIT_FOR_CONFIG` env var
2. Show mode status at startup
3. Run normal config validation
4. If config missing and wait mode enabled:
   - Skip exit
   - Start health server
   - Keep container running
5. If config ready:
   - Proceed with normal bot startup

## Troubleshooting

### Health server not starting
**Check**: Is `config_health_server.py` present?
```bash
ls -la config_health_server.py
```

### Health endpoint returns 404
**Check**: Are you using the correct endpoint?
- Valid: `/health`, `/healthz`, `/status`, `/`
- Invalid: `/api/health`, `/v1/health`

### Health endpoint not accessible
**Check**: Is the PORT environment variable set correctly?
```bash
echo $PORT
# Should match the port Railway assigns
```

### Status stuck on BLOCKED
**Check**: Are credentials actually set in Railway dashboard?
```bash
# From Railway shell
echo $KRAKEN_PLATFORM_API_KEY
echo $KRAKEN_PLATFORM_API_SECRET
# Both should show values, not empty
```

## Example Deployment Flow

### Initial Deployment (No Credentials)
1. Deploy NIJA with `WAIT_FOR_CONFIG=true`
2. Container starts, shows "Wait-for-config mode: ENABLED"
3. Config check fails, enters wait mode
4. Health server starts, reports BLOCKED (503)
5. Railway marks service as unhealthy but keeps it running
6. **No restart loop!**

### Adding Credentials
7. Add `KRAKEN_PLATFORM_API_KEY` in Railway UI
8. Add `KRAKEN_PLATFORM_API_SECRET` in Railway UI
9. Restart deployment
10. Config check passes
11. Bot starts normally
12. Health endpoint now reports READY (200)
13. Railway marks service as healthy

## Summary

Wait-for-config mode delivers:
- ✅ No restart loops due to missing config
- ✅ Machine-readable health signals (503/200/500)
- ✅ Railway compatibility
- ✅ Debuggable in seconds
- ✅ Production-grade infrastructure behavior

This is exactly what infrastructure teams expect from production services.
