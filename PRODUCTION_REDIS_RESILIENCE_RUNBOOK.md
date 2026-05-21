# Production Redis Resilience Runbook

## Purpose
This runbook documents how NIJA handles Redis durability, lease recovery, and
zero-downtime deployments so single-writer safety stays intact.

## 1) Redis Persistence (Required)
NIJA uses Redis for writer fencing + Kraken nonce continuity. Persistence **must**
be enabled or Redis resets will be treated as a split-brain event.

- Railway Redis: enable **AOF** or **RDB** snapshots.
- Managed Redis (Upstash, Redis Cloud): ensure persistence is enabled.

If persistence cannot be verified, live-mode startup fails closed.

## 2) Single-Instance Enforcement
Live trading **must** run with exactly one replica.

- Railway: keep `deploy.numReplicas = 1` (see `railway.json`)
- Do not scale NIJA above one instance

If a second instance starts, the writer lock blocks it and live mode exits.

## 3) Lease Recovery Behavior
NIJA validates:
- Writer lock ownership (fencing token)
- Nonce lease version continuity
- Nonce monotonicity

If a reset is detected (token/lease/nonce decreases), startup halts until an
operator confirms the reset and the exchange state is reconciled. NIJA also
enters **SAFE START** mode on reset or unclean shutdown — live trading remains
blocked until reconciliation succeeds or an explicit manual override is set.

**Manual confirmation flow**
1. Inspect Redis persistence settings and logs.
2. Confirm no other NIJA instance is running.
3. Reconcile exchange state (positions + open orders) and confirm internal
   state is in sync (or no positions remain).
4. Acknowledge reset:
   - Set `NIJA_REDIS_RESET_ACK=true`
   - Redeploy

**Optional auto-reinit**
- Set `NIJA_REDIS_RESET_POLICY=auto_reinit`
- Set `NIJA_REDIS_RESET_RECONCILED=true` once reconciliation is complete
- NIJA will log the reset and proceed after reconciliation confirms safety

**Force takeover (crash recovery)**
- Optional: `NIJA_REDIS_LEASE_FORCE_TAKEOVER=1`
- Set `NIJA_REDIS_LEASE_FORCE_TAKEOVER_TIMEOUT_S=<seconds>` to allow a new
  instance to force-acquire the nonce writer lease when the existing holder
  stops refreshing its TTL.

**Lease stability safeguards**
- Startup backoff: `NIJA_REDIS_LEASE_STARTUP_BACKOFF_MIN_S` /
  `NIJA_REDIS_LEASE_STARTUP_BACKOFF_MAX_S` (default 5–15s) adds jitter before
  first lease acquisition to avoid
  synchronized contention storms.
- Renewal loop: `NIJA_REDIS_LEASE_RENEWAL_FRACTION` (default 0.6) refreshes the
  nonce writer lease at ~60% of TTL (min cadence via
  `NIJA_REDIS_LEASE_RENEWAL_MIN_S`).
- Stability gate: `NIJA_NONCE_LEASE_STABILITY_S` (default 30s in live mode)
  requires a stable lease window before LIVE activation. Use
  `NIJA_REQUIRE_NONCE_LEASE_STABILITY=1` to enforce in non-live modes or set the
  window to 0 to disable.
- Lease status logs: `LEASE STATUS: key_id=... token=... owner_id=...
  ttl_remaining_ms=...` are emitted on lease acquire/change events. Periodic
  steady-state status logs are disabled by default; set
  `NIJA_REDIS_LEASE_STATUS_LOG_INTERVAL_S` to a positive value when you need
  recurring diagnostics.

## 4) Redis Failover Strategy
Recommended approach:
1. Use managed Redis with built-in durability.
2. Keep the same Redis endpoint (stable URL) across restarts.
3. Monitor for `Redis reset detected` logs and respond immediately.

If Redis must be replaced:
1. Provision new Redis with persistence enabled.
2. Update `NIJA_REDIS_URL` to the new endpoint.
3. Follow the reseed + deploy steps below.

## 5) Zero-Downtime Deployment Sequence
When moving from file-based nonces to Redis or after a Redis reset:

1. **Seed Redis** with current nonce high-water marks (safe to run multiple times).
   - See `bot/distributed_nonce_manager.py` "Phase 1 — Seed Redis".
2. **Set Redis URL** (`NIJA_REDIS_URL`) in the environment.
3. **Restart** NIJA (single replica only).
4. **Verify** logs:
   - `DistributedNonceManager: using Redis backend`
   - `Redis persistence confirmed`
   - `Redis nonce continuity verified`

If a reset was detected, acknowledge with `NIJA_REDIS_RESET_ACK=true` (or
`NIJA_REDIS_RESET_RECONCILED=true` for auto-reinit) before redeploying.

## 6) Post-Reset Validation Checklist
- Redis persistence enabled
- `deploy.numReplicas = 1`
- Writer lock token matches local token
- Nonce lease version present
- Nonce value monotonic (no decrease)

If any check fails, do **not** trade until resolved.
