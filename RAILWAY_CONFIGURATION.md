# Railway Configuration Guide

## Overview

This document describes the recommended Railway configuration settings for the NIJA trading bot to ensure **continuous operation**, **idle period survival**, **health check compliance**, and **automatic restart capability**.

## Key Requirements

The NIJA bot is configured to meet the following critical requirements:

1. ✅ **Runs Continuously** - Infinite trading loop with 2.5-minute cycle intervals
2. ✅ **Survives Idle Periods** - `sleepApplication: false` prevents automatic shutdown
3. ✅ **Passes Health Checks** - Always-on HTTP health server on `/health` endpoint
4. ✅ **Auto-Restarts on Failure** - `restartPolicyType: ALWAYS` ensures recovery

## Configuration Settings

The NIJA bot is configured with the following Railway deployment settings in `railway.json`:

### Sleep Application: false (CRITICAL)

```json
"sleepApplication": false
```

**Purpose**: Prevents Railway from automatically putting the application to sleep during periods of low HTTP traffic.

**Why This Matters**:
- Trading bots operate on scheduled intervals (2.5 minutes), not HTTP requests
- Without this setting, Railway might sleep the app during quiet periods
- Sleeping would stop trading operations and miss market opportunities

**Result**: NIJA runs 24/7 regardless of HTTP traffic patterns.

### Restart Policy: ALWAYS

```json
"restartPolicyType": "ALWAYS"
```

**Purpose**: Ensures the trading bot automatically restarts if it crashes or exits for any reason.

**Benefits**:
- Maximum uptime for continuous trading operations
- Automatic recovery from unexpected errors
- No manual intervention required for restarts

### Health Check Path: /health

```json
"healthCheckPath": "/health"
```

**Purpose**: Defines the HTTP endpoint Railway uses to monitor the bot's health status.

**Implementation**: The bot provides health check endpoints at:
- `/health` - Main health check endpoint (in both `bot.py` and `api_server.py`)
- `/healthz` - Alternative health check endpoint
- `/status` - Status endpoint

**Response**: Returns HTTP 200 with "OK" or JSON status when healthy.

### Health Check Timeout: 10 seconds

```json
"healthCheckTimeout": 10
```

**Purpose**: Gives the health check endpoint 10 seconds to respond before marking the service as unhealthy.

**Benefits**:
- Accommodates brief startup delays
- Prevents false positives during high load
- Allows sufficient time for the bot to initialize

## Continuous Operation Architecture

### How NIJA Stays Running Continuously

The bot implements multiple layers to ensure continuous operation:

#### 1. Infinite Trading Loop
```python
while True:
    try:
        cycle_count += 1
        logger.info(f"🔁 Main trading loop iteration #{cycle_count}")
        strategy.run_cycle()
        time.sleep(150)  # 2.5 minutes between cycles
    except Exception as e:
        logger.error(f"Error in trading cycle: {e}")
        time.sleep(10)  # Brief pause on error, then continue
```

**Key Features**:
- Never exits unless explicitly stopped
- Handles errors gracefully without crashing
- Continues trading even after encountering exceptions

#### 2. Always-On Health Server
```python
def _start_health_server():
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
```

**Key Features**:
- Runs as a daemon thread alongside trading operations
- Responds to health checks independent of trading activity
- Ensures Railway sees the app as "alive" at all times

#### 3. Railway Auto-Restart
```json
"restartPolicyType": "ALWAYS"
```

**Key Features**:
- If the process crashes, Railway immediately restarts it
- No manual intervention required
- Maximum uptime guarantee

#### 4. No Sleep Mode
```json
"sleepApplication": false
```

**Key Features**:
- Railway never puts the app to sleep
- Continuous operation even during low HTTP traffic
- Trading continues 24/7

## How to Configure in Railway

To apply these settings in Railway's dashboard:

1. Navigate to your Railway project
2. Click on the NIJA service
3. Go to **Settings** tab
4. Configure the following:
   - **Restart Policy**: Select "Always"
   - **Health Check Path**: Enter `/health`
   - **Health Timeout**: Enter `10` (seconds)

## Health Check Implementation

The bot implements health checks in two ways:

### 1. Bot.py Health Server

The main bot (`bot.py`) includes a minimal HTTP server that responds to health checks:

```python
def _start_health_server():
    # Starts on PORT environment variable (default: 8080)
    # Responds to /, /health, /healthz, /status
```

This server runs as a daemon thread alongside the trading bot.

### 2. API Server Health Endpoint

The API server (`api_server.py`) provides a comprehensive health check endpoint:

```python
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'service': 'NIJA Cloud API',
        'version': '1.0.0'
    })
```

## Testing Health Checks

You can test the health check endpoints locally:

```bash
# Test the health endpoint
curl http://localhost:5000/health

# Expected response:
# OK
# or
# {"status":"healthy","timestamp":"2026-02-02T00:00:00.000Z","service":"NIJA Cloud API","version":"1.0.0"}
```

## Deployment Workflow

When deploying to Railway:

1. Railway reads `railway.json` configuration
2. Builds the Docker image using the Dockerfile
3. Starts the container with `bash start.sh`
4. Begins health checks at `/health` endpoint
5. Marks service as healthy when endpoint returns 200
6. Automatically restarts on failure (due to "ALWAYS" restart policy)

## Monitoring

With these settings, Railway will:

- ✅ Continuously monitor the `/health` endpoint
- ✅ Restart the service automatically if it becomes unhealthy
- ✅ Restart the service automatically if it crashes
- ✅ Wait up to 10 seconds for health check responses
- ✅ Keep the application running 24/7 (never sleep)
- ✅ Maintain continuous trading operations

### Expected Behavior

**Normal Operation**:
- Bot runs continuously in infinite loop
- Health endpoint responds to Railway checks every few seconds
- Trading cycles execute every 2.5 minutes
- App never sleeps or stops

**During Errors**:
- If trading cycle throws exception → Error logged, brief 10s pause, then continues
- If process crashes → Railway immediately restarts (ALWAYS policy)
- If health check fails → Railway marks unhealthy and may restart
- If network issues → Bot retries and continues

**Uptime Guarantee**:
- 24/7 operation with automatic recovery
- No manual intervention needed
- Survives idle periods, errors, and crashes

## Troubleshooting

### Service marked as unhealthy

1. Check the logs in Railway dashboard
2. Verify the PORT environment variable is set correctly
3. Ensure the health server is starting (look for "🌐 Health server listening on port X" in logs)

### Service keeps restarting

1. Check for errors in the startup logs
2. Verify Kraken API credentials are set correctly
3. Check that all required environment variables are configured

### Health endpoint not responding

1. Verify PORT environment variable is set
2. Check firewall/network settings
3. Ensure the health server thread is starting successfully
4. Look for "🌐 Health server listening on port X" in logs

### App goes to sleep during idle periods

**This should NOT happen** with current configuration:
- Verify `sleepApplication: false` in railway.json
- Check Railway dashboard settings
- If still sleeping, contact Railway support

### Bot stops trading but health checks pass

1. Check for EMERGENCY_STOP file in root directory
2. Review trading logs for errors
3. Verify broker credentials are valid
4. Check if minimum balance requirements are met

## Verification Checklist

Before deploying, verify these settings:

- [ ] `railway.json` has `"sleepApplication": false`
- [ ] `railway.json` has `"restartPolicyType": "ALWAYS"`
- [ ] `railway.json` has `"healthCheckPath": "/health"`
- [ ] `railway.json` has `"healthCheckTimeout": 10`
- [ ] Railway dashboard shows "Restart Policy: Always"
- [ ] Railway dashboard shows "Health Check Path: /health"
- [ ] Bot logs show "🌐 Health server listening on port X"
- [ ] Health endpoint returns 200 OK when tested
- [ ] Trading loop logs show "🔁 Main trading loop iteration #X"

## Complete Configuration Example

Here's the complete `railway.json` for reference:

```json
{
  "$schema": "https://railway.com/railway.schema.json",
  "build": {
    "builder": "DOCKERFILE",
    "buildEnvironment": "V3"
  },
  "deploy": {
    "startCommand": "bash start.sh",
    "runtime": "V2",
    "numReplicas": 1,
    "sleepApplication": false,
    "useLegacyStacker": false,
    "multiRegionConfig": {
      "us-west2": {
        "numReplicas": 1
      }
    },
    "restartPolicyType": "ALWAYS",
    "restartPolicyMaxRetries": 10,
    "healthCheckPath": "/health",
    "healthCheckTimeout": 10
  }
}
```

## Summary

The NIJA bot is configured for **maximum uptime and reliability**:

1. **Continuous Operation**: Infinite trading loop runs 24/7
2. **Idle Survival**: `sleepApplication: false` prevents auto-sleep
3. **Health Compliance**: Always-on health server at `/health`
4. **Auto-Recovery**: `ALWAYS` restart policy ensures automatic restart

This configuration ensures NIJA runs continuously, survives idle periods, passes health checks, and is automatically restarted if Railway intervenes.

## Additional Resources

- [Railway Documentation](https://docs.railway.app/)
- [Railway Health Checks](https://docs.railway.app/deploy/healthchecks)
- [Railway Restart Policies](https://docs.railway.app/deploy/deployments#restart-policy)
