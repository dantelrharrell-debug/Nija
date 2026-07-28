# NIJA Verified Success & Recovery Checkpoint

**Verified production window:** July 27–28, 2026  
**Verified deployed commit:** `2fe06b40b52754d335b13c7a601225090cf4aca0`  
**Startup hardening commit:** `187c5ee448afc3a8fcedb2dff9ad31e9aba34fbb`

This file records the strongest production state verified so far and the exact evidence required to return NIJA to that state after a regression.

NIJA does not guarantee trades, fills, exits, profits, or returns. This checkpoint proves live execution readiness and exit-system availability, not that a new order or completed exit occurred during the captured log window.

## Verified production success state

The July 27–28 production logs proved all of the following at the same time:

| Area | Verified state |
|---|---|
| Canonical runtime | Runtime guard healthy on commit `2fe06b40b52754d335b13c7a601225090cf4aca0` |
| Writer authority | `writer_ready=True` |
| Capital authority | `capital_ready=True`; fresh CapitalCSMv2 snapshot accepted |
| Execution | `execution_enabled=True` |
| Kraken | Credentials, authentication, balance, markets, adapter, and eligibility all true |
| Coinbase | Credentials, authentication, balance, markets, adapter, and eligibility all true |
| OKX | Credentials, authentication, balance, markets, adapter, and eligibility all true |
| Three-venue convergence | `ready_venues=kraken,coinbase,okx`; `all_venues_ready=True` |
| Broker connectivity | All configured brokers connected simultaneously |
| Exit supervision | Universal exit supervisor registered OKX, Coinbase, and Kraken |
| OKX exit routing | Router binding and module identity converged |
| Position recovery | Exchange position synchronization started with all three brokers connected |
| Runtime safety | Runtime patch churn safety reported all required controls active and fail-closed |

The fresh capital snapshot reported approximately **$472.07** across three brokers. Per-venue balances are runtime observations and may change; they are not configuration values or guarantees.

## Decisive success markers

A deployment has returned to this checkpoint only when current production logs show the following markers or their direct successors:

```text
RUNTIME_GUARD_AUDIT ... ready=true ... missing=none
LIVE_BROKER_CONNECTIVITY_SNAPSHOT ... kraken_connected=True coinbase_connected=True okx_connected=True all_configured_connected=True
THREE_VENUE_STAGE venue=kraken ... authentication=True balance=True markets=True adapter=True marked_ready=True eligible=True reason=ready
THREE_VENUE_STAGE venue=coinbase ... authentication=True balance=True markets=True adapter=True marked_ready=True eligible=True reason=ready
THREE_VENUE_STAGE venue=okx ... authentication=True balance=True markets=True adapter=True marked_ready=True eligible=True reason=ready
BROKER_INDEPENDENT_EXECUTION_READY ... writer_ready=True capital_ready=True ready_venues=kraken,coinbase,okx degraded_venues=none all_venues_ready=True execution_enabled=True
THREE_VENUE_EXECUTION_READY ... writer_ready=True capital_ready=True kraken=True coinbase=True okx=True execution_enabled=True
CAPITAL_READINESS_HANDOFF_V34_READY ... fresh=true
UNIVERSAL_BROKER_EXIT_REGISTERED ... venue=okx account=platform
UNIVERSAL_BROKER_EXIT_REGISTERED ... venue=coinbase account=platform
UNIVERSAL_BROKER_EXIT_REGISTERED ... venue=kraken account=platform
OKX_ROUTER_BIND_VERIFIED ... router_patched=true
OKX_ROUTER_MODULE_IDENTITY_CONVERGED
RUNTIME_PATCH_CHURN_SAFETY_READY ... fail_closed=true
```

After startup hardening commit `187c5ee448afc3a8fcedb2dff9ad31e9aba34fbb` is deployed, also require:

```text
PREACTIVATION_RUNTIME_IDENTITY_V36_INSTALLED
PREACTIVATION_RUNTIME_IDENTITY_V36_INSTALL_REQUESTED verified=true
```

The v36 installer is now invoked by the canonical `main.py` startup path. In live mode, startup fails closed if the installer is unavailable, returns false, or fails to publish its installed marker.

## What this checkpoint proves

It proves that NIJA is authorized and technically able to:

- Scan eligible markets independently on Kraken, Coinbase, and OKX.
- Submit orders when strategy, risk, sizing, exchange-minimum, and admission checks pass.
- Monitor broker-native held positions.
- Route qualifying exits through registered broker and engine exit protections.
- Preserve broker independence so a degraded optional venue does not block a healthy venue.

It does **not** prove an order or exit occurred. Actual trading requires explicit runtime evidence such as:

```text
BROKER_INDEPENDENT_SCAN_START
BUY_ORDER_SUBMITTED
SELL_ORDER_SUBMITTED
ORDER_FILLED
AUTO_EXIT_TRIGGERED
AUTO_EXIT_CLOSED
UNIVERSAL_BROKER_EXIT_TRIGGER
UNIVERSAL_BROKER_EXIT_CONFIRMED
POSITION_CLOSED
```

## Safe recovery procedure

1. Keep the existing Render environment variables, Redis service, broker credentials, and account permissions intact. Git cannot restore secrets.
2. Redeploy the latest known-good `main` containing startup hardening commit `187c5ee448afc3a8fcedb2dff9ad31e9aba34fbb`.
3. If the hardening change itself must be isolated, redeploy verified runtime commit `2fe06b40b52754d335b13c7a601225090cf4aca0`, then compare startup behavior before making further changes.
4. Do not delete or steal the Redis writer lease. During a rolling deployment, allow the previous writer to release or expire normally.
5. Do not use forced activation, synthetic capital, credential bypasses, nonce bypasses, or writer-lock bypasses.
6. Verify the two v36 startup markers after deploying the hardening commit.
7. Verify all three broker authentication/readiness stages independently.
8. Verify fresh capital handoff and both execution-ready markers.
9. Verify all three universal exit registrations and OKX router convergence.
10. Allow the normal scanner and exit monitors to operate. Lack of immediate trades can mean no valid strategy signal exists.

## Regression triage order

When NIJA stops trading or exit monitoring appears stalled, diagnose in this order:

1. **Runtime identity:** deployed commit and canonical entrypoint.
2. **Single-writer authority:** lease, generation, and fresh heartbeat.
3. **Preactivation guard:** v36 installed markers.
4. **Capital freshness:** `CAPITAL_READINESS_HANDOFF_V34_READY ... fresh=true`.
5. **Per-venue authentication:** never infer authentication from object construction or public-market access.
6. **Execution readiness:** writer, capital, adapter, markets, and eligibility.
7. **Router identity:** especially OKX final-stage routing.
8. **Exit registration and cost basis:** held positions require trustworthy quantity and entry data.
9. **Actual scan/signal evidence:** readiness alone does not force trades.

## Known-good reference evidence

The captured success window included:

```text
BROKER_INDEPENDENT_EXECUTION_READY ... writer_ready=True capital_ready=True ready_venues=kraken,coinbase,okx degraded_venues=none all_venues_ready=True execution_enabled=True
THREE_VENUE_EXECUTION_READY ... writer_ready=True capital_ready=True kraken=True coinbase=True okx=True execution_enabled=True
FIRST_SNAPSHOT_GATE_CSM_LATCH accepted_latched=True state=READY capital=$472.07 broker_count=3 stale=False
CAPITAL_READINESS_HANDOFF_V34_READY ... capital=472.07 broker_count=3 fresh=true
RUNTIME_PATCH_CHURN_SAFETY_READY ... live_active=True dispatch_latch=True execution_contract=True kraken_live_ecel=True kraken_floor_ecel=True fail_closed=true
```

This document is the recovery anchor for the July 27–28, 2026 three-venue execution success state.