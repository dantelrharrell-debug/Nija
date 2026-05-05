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
operator confirms the reset.

**Manual confirmation flow**
1. Inspect Redis persistence settings and logs.
2. Confirm no other NIJA instance is running.
3. Acknowledge reset:
   - Set `NIJA_REDIS_RESET_ACK=true`
   - Redeploy

**Optional auto-reinit**
- Set `NIJA_REDIS_RESET_POLICY=auto_reinit`
- NIJA will log the reset and proceed after reinitializing state

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

If a reset was detected, acknowledge with `NIJA_REDIS_RESET_ACK=true` before redeploying.

## 6) Post-Reset Validation Checklist
- Redis persistence enabled
- `deploy.numReplicas = 1`
- Writer lock token matches local token
- Nonce lease version present
- Nonce value monotonic (no decrease)

If any check fails, do **not** trade until resolved.
