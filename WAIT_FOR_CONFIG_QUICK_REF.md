# Wait-for-Config Mode - Quick Reference

## What is it?

A production-grade startup mode that prevents restart loops and provides clear health signals when configuration is missing.

## Three States

| State | HTTP Code | Meaning | Action |
|-------|-----------|---------|--------|
| **BLOCKED** | 503 | Missing credentials | Add config, restart |
| **READY** | 200 | Fully configured | None needed |
| **ERROR** | 500 | Hard failure | Check logs, fix issue |

## Quick Start

### Enable via Environment Variable
```bash
export WAIT_FOR_CONFIG=true
./start.sh
```

### Enable via Command Line
```bash
./start.sh --wait-for-config
```

### Enable in Railway
Add environment variable in Railway dashboard:
```
WAIT_FOR_CONFIG=true
```

## Check Status

```bash
# Local
curl http://localhost:8080/healthz

# Railway
curl https://your-app.up.railway.app/healthz
```

**Response when blocked (503)**:
```json
{
  "status": "blocked",
  "state": "awaiting_configuration",
  "message": "Waiting for configuration",
  "required": {
    "KRAKEN_PLATFORM_API_KEY": "Kraken API key (required)",
    "KRAKEN_PLATFORM_API_SECRET": "Kraken API secret (required)"
  }
}
```

**Response when ready (200)**:
```json
{
  "status": "ready",
  "state": "configured",
  "message": "Configuration is complete, bot is ready to trade"
}
```

## Why Use It?

**Without wait-for-config**:
- Missing config → exit → restart loop
- Wastes resources
- Can't distinguish "waiting" from "crashed"

**With wait-for-config**:
- Missing config → stays running, reports status
- No restart loops
- Clear, queryable health signals
- Infrastructure teams can monitor state
- Debuggable in seconds

## Full Documentation

See [WAIT_FOR_CONFIG_GUIDE.md](WAIT_FOR_CONFIG_GUIDE.md) for complete documentation including:
- Detailed state descriptions
- Railway integration guide
- Monitoring and alerting setup
- Troubleshooting guide
- Production best practices
