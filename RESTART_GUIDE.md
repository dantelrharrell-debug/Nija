# NIJA Bot Restart Guide

This document explains how to restart the NIJA trading bot.

## Overview

NIJA provides two methods for restarting the bot:
1. **Web Dashboard API** - Restart via HTTP endpoint
2. **Command-line Script** - Restart via shell script

Both methods perform a graceful shutdown by sending a SIGTERM signal to the bot process, allowing it to close positions and clean up resources before the deployment platform automatically restarts it.

## Method 1: Web Dashboard API

### Endpoint
```
POST /api/restart
```

### Usage with curl
```bash
curl -X POST http://localhost:5001/api/restart
```

### Response (Success)
```json
{
  "success": true,
  "message": "Restart signal sent to NIJA bot",
  "pid": 12345,
  "timestamp": "2026-01-21T20:45:00.000Z"
}
```

### Response (Bot Not Running)
```json
{
  "success": false,
  "message": "Bot process not found - it may not be running",
  "timestamp": "2026-01-21T20:45:00.000Z"
}
```

### Response (Error)
```json
{
  "success": false,
  "error": "Error message here",
  "timestamp": "2026-01-21T20:45:00.000Z"
}
```

## Method 2: Command-line Script

### Usage
```bash
./restart_nija.sh
```

### Example Output
```
==============================
  RESTARTING NIJA TRADING BOT
==============================
Found NIJA bot process: PID 12345
Sending SIGTERM signal for graceful shutdown...
✅ Restart signal sent
   The deployment platform will automatically restart the bot

To check if the bot restarted successfully:
  tail -f nija.log
```

## How It Works

1. The restart mechanism finds the running `bot.py` process
2. Sends a SIGTERM signal to the process
3. The bot handles the signal gracefully (see `bot.py` line 135-137):
   - Closes open positions (if configured to do so)
   - Saves state to disk
   - Exits cleanly
4. The deployment platform (Railway/Render) detects the process exit
5. The platform automatically restarts the bot using the configured start command

## Platform-Specific Behavior

### Railway
- Restart policy: `ON_FAILURE` with max 10 retries (see `railway.json`)
- The platform will automatically restart the bot after a clean shutdown

### Render
- Render will automatically restart the service after the process exits

### Docker
- If using Docker with restart policies (e.g., `--restart=unless-stopped`), the container will be restarted automatically

## When to Use Restart

Restart the bot when you need to:
- Apply configuration changes from `.env` file
- Recover from a stuck state
- Force a reconnection to exchange APIs
- Apply code changes (after deploying new code)

## Monitoring the Restart

After triggering a restart, monitor the bot logs:

```bash
# Watch live logs
tail -f nija.log

# Check recent logs
tail -100 nija.log
```

Look for the startup banner:
```
======================================================================
NIJA TRADING BOT - APEX v7.1
Branch: main
Commit: abc1234
======================================================================
```

## Troubleshooting

### "Bot process not found"
This means the bot is not currently running. Start it with:
```bash
./start.sh
```

### Bot doesn't restart automatically
Check your deployment platform's restart policy configuration:
- **Railway**: Check `railway.json` for `restartPolicyType`
- **Render**: Check service settings for auto-restart configuration
- **Docker**: Ensure container has restart policy set

### Restart is taking too long
The bot may be waiting for:
- Open positions to close (if configured to do so on shutdown)
- API calls to complete
- File writes to finish

Give it 30-60 seconds before checking the logs.

## Security Considerations

The `/api/restart` endpoint should be protected in production environments:
- Consider adding authentication to the dashboard
- Restrict access to the dashboard port (5001) to trusted IPs
- Use environment variables to enable/disable the restart endpoint

## Related Files

- `/bot/dashboard_server.py` - Contains the `/api/restart` endpoint implementation
- `/restart_nija.sh` - Command-line restart script
- `/bot.py` - Main bot entry point with signal handlers
- `/start.sh` - Bot startup script

## See Also

- [Trading Strategy Documentation](APEX_V71_DOCUMENTATION.md)
- [Deployment Guide](DOCKER_DEPLOYMENT_GUIDE.md)
- [Getting Started](GETTING_STARTED.md)
