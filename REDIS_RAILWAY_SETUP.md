# Redis Connection Setup for NIJA on Railway

## 🔴 CRITICAL: Redis Lock Stability Issue

The distributed writer lock uses Redis to prevent multiple bot instances from trading simultaneously. **Production Railway configs must use a TLS public runtime URL (`rediss://...up.railway.app:6379/0`) for `NIJA_REDIS_URL`, plus explicit private/public fallback variables. Do not use the public Railway endpoint as plain `redis://`.**

## ✅ Recommended: Start with Railway TCP Proxy (TLS)

Railway TCP proxy is the recommended external endpoint for NIJA.
Use `rediss://` for proxy hosts and verify `PING` succeeds.

If proxy TLS fails in your environment, NIJA now falls back to other configured Redis URLs in this order:

1. Railway internal/private host (`*.railway.internal`) when available
2. Native/non-proxy Redis endpoint
3. Other configured Railway hostnames

## ✅ Step 0: Enable Redis persistence (AOF or RDB)

NIJA relies on Redis for writer fencing + nonce continuity. **Persistence must be enabled** or every Redis reset
looks like a split-brain event and trading will be blocked.

- Railway Redis: enable **AOF** or **RDB** snapshots in the Redis service settings
- Or use a managed provider (Upstash, Redis Cloud) with persistence enabled

If persistence cannot be verified, NIJA startup will fail closed in live mode.

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
REDIS_PASSWORD=your_redis_password_here

# PRIMARY (internal/private)
REDIS_PRIVATE_URL=redis://default:${REDIS_PASSWORD}@redis.railway.internal:6379/0

# FALLBACK (public TLS proxy)
REDIS_PUBLIC_URL=rediss://default:${REDIS_PASSWORD}@redis-production-e747.up.railway.app:6379/0

# PRIMARY runtime URL
NIJA_REDIS_URL=rediss://default:${REDIS_PASSWORD}@redis-production-e747.up.railway.app:6379/0
```

Remove these broken legacy variables if they are present:

```bash
REDIS_URL=
REDIS_TLS_URL=
```

The public Railway endpoint must use `rediss://`, never `redis://`.

### Step 4: Restart NIJA Service

1. In Railway, restart the NIJA service
2. Watch logs for Redis connection confirmation
3. Look for: `✅ Redis connection established` or `✅ Distributed writer lock ready`

## ✅ Single-Instance Requirement (Railway replicas)

NIJA must run as **ONE** replica in live mode.

- Keep `railway.json` → `deploy.numReplicas = 1`
- Do not scale the NIJA service above 1 replica

If a second instance boots, the writer lock will block it and live trading will fail closed.

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

One-command winner probe (shows whether proxy TLS or fallback endpoint was selected):

```bash
python3 scripts/redis_endpoint_probe.py
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

### Proxy TLS Confirmation + Fallback Decision

- Keep `NIJA_REDIS_URL` on the Railway public TLS endpoint (`rediss://...up.railway.app:6379/0`).
- Keep `REDIS_PRIVATE_URL` on the Railway internal/private endpoint (`redis://...railway.internal:6379/0`) for fallback inside Railway.
- Keep `REDIS_PUBLIC_URL` on the same public TLS endpoint for alternate-candidate retries.
- Remove `REDIS_URL` and `REDIS_TLS_URL` unless you explicitly depend on them elsewhere.

Connection runtime behavior:

- NIJA first tries the primary configured URL.
- If that fails, NIJA automatically tries alternate configured URLs (internal/private and non-proxy first).
- Optional same-endpoint TLS downgrade (`rediss://` → `redis://`) remains opt-in via `NIJA_REDIS_ALLOW_PLAIN_FALLBACK=true`.

### Exit code quick map

- `1`: Redis ping/connectivity failure
- `2`: Python redis module unavailable in fallback path
- `3`: TLS scheme mismatch (`redis://` used with forced TLS on proxy host)
- `4`: URL/host/port resolution failure
- `5`: Railway service status check failed (strict mode)
- `6`: Railway project/network linkage check failed (strict mode)

## ❌ What NOT to Do

### Do NOT use internal hosts from outside Railway private networking

- `redis://<service>.railway.internal:6379` only works when NIJA and Redis are in the same Railway project/network.
- From external networks, use a public endpoint (Railway proxy `rediss://` or a native Redis provider).

**❌ Do NOT use:** Insufficient Redis allocations

- Minimum: 256MB Redis instance
- Recommended: 512MB or 1GB for production

**❌ Do NOT disable** the distributed writer lock without understanding the consequences

- Only disable if you're running a single bot instance
- Multi-instance deployments REQUIRE Redis lock

## 🆘 Troubleshooting

### Error: "Redis connection timeout"

- Check that `NIJA_REDIS_URL` uses the Railway public TLS endpoint with `rediss://`
- Verify `REDIS_PRIVATE_URL` points at the internal Railway host on port `6379`
- Verify the Redis service is running and has public networking enabled

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

## 📘 Runbook

For production resilience (failover + reset recovery + zero-downtime steps), see:
`PRODUCTION_REDIS_RESILIENCE_RUNBOOK.md`.

## 📋 Configuration Priority

NIJA checks for Redis URLs in this order:

1. `NIJA_REDIS_URL` (highest priority)
2. `REDIS_PRIVATE_URL`
3. `REDIS_PUBLIC_URL`
4. `REDIS_URL` (legacy compatibility only)
5. `REDIS_TLS_URL` (legacy compatibility only)
6. Individual components: `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`, `REDIS_DB`

Recommended Railway production set:

- `REDIS_PASSWORD`
- `REDIS_PRIVATE_URL=redis://default:${REDIS_PASSWORD}@redis.railway.internal:6379/0`
- `REDIS_PUBLIC_URL=rediss://default:${REDIS_PASSWORD}@redis-production-e747.up.railway.app:6379/0`
- `NIJA_REDIS_URL=rediss://default:${REDIS_PASSWORD}@redis-production-e747.up.railway.app:6379/0`

## 🔧 Advanced: Manual URL Construction

If you must construct the URLs manually, use this Railway production layout:

```bash
REDIS_PRIVATE_URL=redis://default:YourPasswordHere@redis.railway.internal:6379/0
REDIS_PUBLIC_URL=rediss://default:YourPasswordHere@redis-production-e747.up.railway.app:6379/0
NIJA_REDIS_URL=rediss://default:YourPasswordHere@redis-production-e747.up.railway.app:6379/0
```

## 📚 References

- [Railway Redis Networking](https://docs.railway.app/)
- [NIJA Distributed Lock Guide](./DISTRIBUTED_LOCK_GUIDE.md) (if available)
- [Bot Troubleshooting](./TROUBLESHOOTING.md) (if available)
