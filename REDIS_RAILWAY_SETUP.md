# Redis Connection Setup for NIJA on Railway

## 🔴 CRITICAL: Redis Lock Stability Issue

The distributed writer lock uses Redis to prevent multiple bot instances from trading simultaneously. **If your Redis URL is incorrect or uses the internal Railway domain (`redis://nija.railway.internal:6379`), you WILL experience lock failures and trade execution failures.**

## ✅ Solution: Use Railway TCP Proxy

Railway provides a TCP proxy to access Redis from external services. This is **required** for NIJA to work reliably.

### Step 1: Enable TCP Proxy in Railway

1. Go to Railway dashboard → Your project → Redis service
2. Click "Networking" tab
3. Enable "Public Networking" or "TCP Proxy"
4. You'll get:
   - **Domain**: `maglev.proxy.rlwy.net` (or similar)
   - **Port**: A random port (e.g., `12345`)
5. Note these values

### Step 2: Get Redis Password

1. In Redis service → "Variables" tab
2. Find `REDIS_PASSWORD` (or `REDIS_TOKEN`/`REDIS_URL`)
3. Copy the password value (looks like a random string)

### Step 3: Configure NIJA Environment Variables

Set these Railway environment variables for the NIJA service:

```bash
# Railway TCP Proxy connection (REQUIRED)
RAILWAY_TCP_PROXY_DOMAIN=maglev.proxy.rlwy.net
RAILWAY_TCP_PROXY_PORT=12345

# Redis authentication
REDIS_PASSWORD=your_redis_password_here
REDIS_DB=0
```

### Alternative: Use NIJA_REDIS_URL directly

If you prefer to set a single variable, construct the URL and set:

```bash
NIJA_REDIS_URL=rediss://default:your_redis_password_here@maglev.proxy.rlwy.net:12345/0
```

### Step 4: Restart NIJA Service

1. In Railway, restart the NIJA service
2. Watch logs for Redis connection confirmation
3. Look for: `✅ Redis connection established` or `✅ Distributed writer lock ready`

## 🔍 Verify Your Setup

Run this test command to verify Redis connection:

```bash
# In NIJA container or locally:
bash scripts/redis_connectivity_check.sh
```

The script now runs a 5-point verification sequence:

1. Confirm Redis URL parsing and TLS scheme sanity
2. Confirm Redis service status in Railway (best effort when Railway CLI is available)
3. Verify same-project/network linkage expectations
4. Run `nc` TCP reachability test against host:port
5. Run Redis `PING` with explicit TLS flags for `rediss://`

Optional: load env values from a file before checks:

```bash
bash scripts/redis_connectivity_check.sh --env-file .env
```

NIJA startup now runs this preflight automatically when Redis is configured.

- Default: `NIJA_REDIS_STARTUP_CHECK=true`
- Temporary bypass (not recommended): `NIJA_REDIS_STARTUP_CHECK=false`

Live-mode safety override:

- When `LIVE_CAPITAL_VERIFIED=true`, Redis is configured, and distributed lock protection is active, NIJA forces startup preflight back on even if `NIJA_REDIS_STARTUP_CHECK=false`.
- Reason: live trading cannot safely continue with a bypassed Redis lock preflight.

Strictness for Railway service/linkage checks:

- Default: `NIJA_REDIS_STRICT_CHECKS=true` (fails preflight if Railway status/linkage checks fail)
- Relaxed mode: `NIJA_REDIS_STRICT_CHECKS=false` (logs warnings but continues)

## 🧭 Operator Runbook: Expected Output

Use this when validating Redis during incident response or fresh deploys.

Command:

```bash
bash scripts/redis_connectivity_check.sh
```

### Check 1/5: Redis URL + TLS sanity

Expected pass indicators:

- `Redis URL: rediss://***@<host>:<port>`
- No `ERROR:` lines

Expected fail indicators:

- `ERROR: Redis URL is empty`
- `ERROR: NIJA_REDIS_URL uses redis:// on Railway proxy while NIJA_REDIS_FORCE_TLS=true`

### Check 2/5: Railway service status

Expected pass indicators:

- `Railway status includes a Redis service entry`
- `Railway reports at least one active deployment state`

Expected fail indicators (strict mode):

- `ERROR: Railway service status check failed`
- `WARN: Railway status did not mention a Redis service`

### Check 3/5: Project/network linkage

Expected pass indicators:

- For internal host: `Using Railway internal Redis hostname: ...` with runtime context confirmation
- For public proxy: `Using Railway public TCP proxy hostname: ...`

Expected fail indicators (strict mode):

- `ERROR: Railway project/network linkage check failed`
- `WARN: Internal Railway host requires NIJA and Redis services in same Railway project/environment`

### Check 4/5: TCP reachability (`nc`)

Expected pass indicators:

- `nc reachability test passed`
- Or `socket reachability test passed` (fallback path)

Expected fail indicators:

- `ERROR: nc reachability test failed for <host>:<port>`
- `ERROR: socket reachability test failed: ...`

### Check 5/5: Redis PING with explicit TLS

Expected pass indicators:

- `PONG`
- `Connectivity check completed`

Expected fail indicators:

- `ERROR: Redis connectivity check failed: ...`

### Exit code quick map

- `1`: Redis ping/connectivity failure
- `2`: Python redis module unavailable in fallback path
- `3`: TLS scheme mismatch (`redis://` used with forced TLS on proxy host)
- `4`: URL/host/port resolution failure
- `5`: Railway service status check failed (strict mode)
- `6`: Railway project/network linkage check failed (strict mode)

## ❌ What NOT to Do

**❌ Do NOT use:** `redis://nija.railway.internal:6379`

- This is Railway's internal network, only accessible within the same private network
- External connections will fail
- Bot will hang or crash with lock contention errors

**❌ Do NOT use:** Insufficient Redis allocations

- Minimum: 256MB Redis instance
- Recommended: 512MB or 1GB for production

**❌ Do NOT disable** the distributed writer lock without understanding the consequences

- Only disable if you're running a single bot instance
- Multi-instance deployments REQUIRE Redis lock

## 🆘 Troubleshooting

### Error: "Redis connection timeout"

- Check that RAILWAY_TCP_PROXY_DOMAIN and RAILWAY_TCP_PROXY_PORT are correct
- Verify the Redis service is running and has public networking enabled
- Check Railway firewall rules allow outbound connections

### Error: "Redis WRONGPASS or invalid user"

- Verify REDIS_PASSWORD matches exactly
- Make sure there are no extra spaces or special characters
- The username should be `default` (not your account name)

### Error: "Lock contention" or "Writer lock held by another process"

- Check that only one NIJA instance is running
- Restart both the NIJA service and Redis service
- Clear Redis cache (dangerous—wipes all data): `FLUSHALL`

### Bot hangs with no trades executing

- This usually means Redis lock is stuck
- Check logs for `EXECUTION BLOCKED | ...committed=false`
- Restart the NIJA service to reset the lock

## 📋 Configuration Priority

NIJA checks for Redis URLs in this order:

1. `NIJA_REDIS_URL` (highest priority)
2. `REDIS_URL`
3. `REDIS_PRIVATE_URL`
4. `REDIS_PUBLIC_URL`
5. Individual components: `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`, `REDIS_DB`

If **Railway proxy environment variables are set first**, they're used to construct the URL automatically:

- `RAILWAY_TCP_PROXY_DOMAIN` + `RAILWAY_TCP_PROXY_PORT` + `REDIS_PASSWORD` → `rediss://default:PASSWORD@DOMAIN:PORT/DB`

## 🔧 Advanced: Manual URL Construction

If Railway proxy variables aren't available, manually construct and set NIJA_REDIS_URL:

```bash
# Format: rediss://USERNAME:PASSWORD@HOST:PORT/DATABASE
NIJA_REDIS_URL=rediss://default:YourPasswordHere@maglev.proxy.rlwy.net:12345/0
```

Replace:

- `YourPasswordHere` → actual Redis password
- `maglev.proxy.rlwy.net` → your Railway TCP proxy domain
- `12345` → your Railway TCP proxy port
- `0` → Redis database number (usually 0)

## 📚 References

- [Railway Redis Networking](https://docs.railway.app/)
- [NIJA Distributed Lock Guide](./DISTRIBUTED_LOCK_GUIDE.md) (if available)
- [Bot Troubleshooting](./TROUBLESHOOTING.md) (if available)
