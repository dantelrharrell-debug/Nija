# NIJA AI Trading LLC — Current Success State

**Status date:** July 31, 2026

**Current hardening checkpoint:** [`f010e9c`](https://github.com/dantelrharrell-debug/Nija/commit/f010e9c1fa6fe92dae4e8681429f15b4223f916d)

**Latest recovery PRs:** [PR #2320](https://github.com/dantelrharrell-debug/Nija/pull/2320) — authority heartbeat timeout recovery; [PR #2321](https://github.com/dantelrharrell-debug/Nija/pull/2321) — isolated timeout-grace tests

This README is the durable recovery anchor for NIJA. It separates what production logs have proved from what still must happen before any run is declared actively trading.

NIJA does not guarantee trades, fills, profits, income, or returns. A connected brokerage may enter a trade only when writer authority, authenticated capital, signal, risk, exchange-minimum, order-admission, and venue-specific execution checks all pass.

## Current Recovery Checkpoint — July 31, 2026

The July 31 recovery work cleared the startup blockers observed after the July 26 three-broker recovery. The latest logs showed the system had progressed through capital readiness, three-broker connectivity, live broker exit registration, entry-price repair, and runtime guard audit readiness. The remaining blocker was an authority heartbeat probe that timed out even though Redis was reachable and the writer generation matched. PR #2320 hardened that path.

| Area | Proven or patched state |
|---|---|
| Source of truth | Canonical runtime path remains `scripts/canonical_runtime_launcher_v26.py -> main.py -> bot.bot -> bot.bot_main` |
| Latest code checkpoint | `main` includes commit `f010e9c1fa6fe92dae4e8681429f15b4223f916d` |
| Capital readiness | Runtime evidence showed `CAPITAL_READINESS_HANDOFF_V34_READY` with fresh live-exchange capital around `$466` and `broker_count=3` |
| Broker connectivity | Runtime evidence showed Kraken, Coinbase, and OKX all connected in `LIVE_BROKER_CONNECTIVITY_SNAPSHOT` |
| Exit protection | `UNIVERSAL_BROKER_EXIT_REGISTERED` was observed for OKX, Coinbase, and Kraken platform brokers |
| Runtime guard audit | Runtime evidence showed `RUNTIME_GUARD_AUDIT ready=true missing=none` |
| Entry cost-basis repair | Runtime evidence repaired the visible `ETH-USD` entry price from broker/account data |
| Prior blocker | `AUTHORITY_HEARTBEAT_EXPIRED` forced `LIVE_PENDING_CONFIRMATION -> EMERGENCY_STOP` after three 5-second authority probe timeouts |
| Current hardening | `bot.authority_heartbeat_timeout_grace_patch` now suppresses only soft authority-probe timeouts when Redis proves the current process still owns the writer lock token and matching generation |
| Fail-closed behavior | Generation mismatch, Redis outage, missing lock, token mismatch, missing fencing token, and non-timeout authority failures still fall through to the original emergency-stop path |
| Trading state | Latest user-provided logs proved readiness and protection layers, but did not prove a new order fill or completed exit after the final heartbeat fix deployed |

### July 31 success evidence

```text
CAPITAL_READINESS_HANDOFF_V34_READY ... capital=466.59 broker_count=3 fresh=true
LIVE_BROKER_CONNECTIVITY_SNAPSHOT ... kraken_connected=True coinbase_connected=True okx_connected=True all_configured_connected=True
UNIVERSAL_BROKER_EXIT_REGISTERED venue=okx account=platform
UNIVERSAL_BROKER_EXIT_REGISTERED venue=coinbase account=platform
UNIVERSAL_BROKER_EXIT_REGISTERED venue=kraken account=platform
RUNTIME_GUARD_AUDIT ... ready=true ... missing=none
[EntryPriceStore] repair: ETH-USD -> $1742.9200 qty=0.0381184362 (source=api)
```

### Last confirmed blocker fixed

The final blocking pattern before PR #2320 was:

```text
AUTHORITY_HEARTBEAT: HEARTBEAT FAILURE #3/3 — Authority check timed out after 5.0s | local_generation=2881 redis_generation=2881 redis_conn=reachable is_generation_mismatch=False
AuthorityHeartbeatMonitor: forcing EMERGENCY_STOP — AUTHORITY HEARTBEAT EXPIRED
State transition: LIVE_PENDING_CONFIRMATION -> EMERGENCY_STOP
```

This was treated as a slow authority status probe, not proven lost authority, because Redis was reachable and the writer generation matched. The new guard requires Redis to prove both generation and lock-token ownership before grace is applied.

Expected post-deploy markers:

```text
AUTHORITY_HEARTBEAT_TIMEOUT_GRACE_INSTALL_REQUESTED
AUTHORITY_HEARTBEAT_TIMEOUT_GRACE_INSTALLED marker=20260731-authority-heartbeat-timeout-grace-v1
```

If the same soft timeout recurs while ownership is still valid, the expected recovery marker is:

```text
AUTHORITY_HEARTBEAT_TIMEOUT_GRACE_APPLIED marker=20260731-authority-heartbeat-timeout-grace-v1
```

If ownership is not proven, NIJA must still halt and publish:

```text
AUTHORITY_HEARTBEAT_TIMEOUT_GRACE_DENIED
AUTHORITY_HEARTBEAT_EXPIRED
```

## Safe Continuation From This Checkpoint

1. Deploy or wait for Render to deploy commit `f010e9c1fa6fe92dae4e8681429f15b4223f916d` or newer.
2. Confirm the canonical entrypoint attestation references that commit or a later audited commit.
3. Confirm the heartbeat hardening module installs:
   ```text
   AUTHORITY_HEARTBEAT_TIMEOUT_GRACE_INSTALLED
   ```
4. Confirm writer authority and generation remain valid:
   ```text
   ENTRYPOINT_WRITER_AUTHORITY_READY
   ENTRYPOINT_WRITER_AUTHORITY_VERIFIED
   ```
5. Confirm capital and broker readiness remain live, fresh, and broker-backed:
   ```text
   CAPITAL_READINESS_HANDOFF_V34_READY
   FIRST_SNAPSHOT_GATE_LATCH accepted_latched=True stale=False
   LIVE_BROKER_CONNECTIVITY_SNAPSHOT ... all_configured_connected=True
   ```
6. Confirm runtime activation advances without emergency stop:
   ```text
   ACTIVATION_COMMITTED
   NIJA_RUNTIME_TRADING_STATE=LIVE_ACTIVE
   ```
7. Confirm scans and execution-admission logs before expecting any trade:
   ```text
   BROKER_INDEPENDENT_SCAN_START
   BROKER_INDEPENDENT_SCAN_BROKER_START broker=<venue>
   ```
8. Confirm fills and exits only from real broker/order evidence. Connectivity and `LIVE_ACTIVE` are not proof of a trade or profit.
9. Never use forced activation, synthetic capital, credential bypasses, nonce bypasses, or manual writer-lock deletion to manufacture readiness.

## Current Live Broker Contract

NIJA's active live cryptocurrency execution system supports exactly three platform venues:

| Brokerage | Runtime role | Live entries | Automatic exits | Required status |
|---|---|---:|---:|---|
| **Kraken** | Required primary platform broker | Yes | Yes | Connected, funded, nonce-ready |
| **Coinbase Advanced Trade** | Optional isolated secondary venue | Yes | Yes | Valid ECDSA key, connected, funded |
| **OKX US** | Optional isolated secondary venue | Yes | Yes | Key/secret/passphrase, connected, funded |

Additional repository adapters:

- **Alpaca** is retained for user and paper-trading workflows. It is not part of the active live crypto entry priority.
- **Binance** is a legacy/future venue label. The active production `MultiAccountBrokerManager` does not construct a Binance platform broker, so Binance must not be selected as `PRIMARY_EXECUTION_VENUE`.

The canonical live routing defaults are:

```bash
NIJA_ALLOWED_EXECUTION_BROKERS=okx,coinbase,kraken
NIJA_ENTRY_BROKER_PRIORITY=okx,coinbase,kraken
NIJA_BROKER_PRIORITY=okx,coinbase,kraken
PRIMARY_EXECUTION_VENUE=auto
```

`PRIMARY_EXECUTION_VENUE` may force only `kraken`, `coinbase`, or `okx`. Use `auto`, `best`, `all`, or an empty value for independent multi-venue routing.

## Brokerage Independence

Every platform and user brokerage trades independently.

- NIJA does not merge one brokerage's available cash into another brokerage.
- A low or disconnected Kraken account does not block a ready Coinbase or OKX account.
- A Coinbase or OKX authentication failure is isolated and does not disable Kraken.
- Each account has its own balance, position count, order minimum, risk state, entries, exits, and audit trail.
- Copy trading is disabled. User accounts are not mirrors of the platform account.

The three-venue readiness flag means **at least one** venue is fully ready, not that every configured venue must be healthy:

```text
NIJA_THREE_VENUE_EXECUTION_READY=1
```

A degraded optional venue is excluded until it recovers.

## Production Startup Order

The active Render startup path is:

```text
scripts/production_bootstrap.sh
    -> start.sh
    -> scripts/canonical_runtime_launcher_v26.py
    -> main.py
    -> bot.bot
    -> bot.bot_main
```

Safety-critical order:

1. Start the isolated Render liveness server.
2. Install pre-bot runtime guard patches, including current capital freshness and authority heartbeat timeout grace.
3. Acquire the Redis single-writer lease and fencing generation.
4. Start writer and authority heartbeats.
5. Initialize Kraken nonce protection.
6. Run SelfHealingStartup and connect the primary broker.
7. Initialize the canonical `MultiAccountBrokerManager`.
8. Connect configured Coinbase and OKX platform brokers.
9. Connect configured user broker accounts.
10. Hydrate real broker balances into `CapitalAuthority`.
11. Publish per-venue execution readiness.
12. Commit `LIVE_ACTIVE` only through the normal state machine.
13. Start independent broker-scoped scanning and execution.
14. Keep automatic position exits running for every registered live broker instance.

No deployment variable may pre-grant writer authority or `LIVE_ACTIVE`.

## Deterministic Pattern Recognition (Technical) vs ML

NIJA now wires deterministic chart-pattern recognition into the live production entry path:

`main.py -> bot.bot -> bot.nija_core_loop (Phase 3 scan) -> bot.nija_ai_engine -> bot.enhanced_entry_scoring -> bot.deterministic_pattern_recognition`

- Deterministic technical-pattern logic uses completed OHLCV candles only and returns explicit pattern structure (name, direction, confidence, levels, confirmation state, invalidation price).
- ML/AI modules remain separate and do not replace deterministic technical confirmation.

Example configuration (via scorer/config dict):

```python
{
    "enabled": True,
    "pattern_lookback": 120,
    "min_pattern_confidence": 0.65,
    "breakout_lookback": 20,
    "min_volume_ratio": 1.1,
    "stale_bars": 8,
    "atr_stop_buffer": 0.35,
}
```

## Authority Heartbeat Hardening

The authority heartbeat is a safety system, not a trading signal. It protects the single-writer lease and must remain fail-closed when authority is genuinely lost.

Current hardening module:

```text
bot/authority_heartbeat_timeout_grace_patch.py
```

The module may suppress lockdown only for this narrow case:

```text
reason contains: Authority check timed out
is_generation_mismatch=False
Redis generation == NIJA_WRITER_LEASE_GENERATION
Redis writer lock token == NIJA_WRITER_FENCING_TOKEN
```

It must not suppress lockdown for:

```text
generation mismatch
Redis ping timeout or Redis unavailable
missing writer lock
writer lock held by another token
missing fencing token
explicit authority assertion failure
operator emergency stop
```

Operational override:

```bash
NIJA_AUTHORITY_HEARTBEAT_TIMEOUT_GRACE_DISABLED=true
```

Use the override only if the timeout-grace path itself is suspected of masking a real authority issue.

## Writer Authority Handoff

During a Render rolling deployment, the new instance may report:

```text
ENTRYPOINT_WRITER_AUTHORITY_STANDBY
error=active_writer_lock_held
```

This is safe behavior. The new instance must not steal or delete an active writer's lease. It continues only after the previous holder releases the lock or its lease expires.

Render's `Your service is live` message proves that the HTTP liveness port is available. It does not prove that NIJA has trading authority.

Required authority proof:

```text
PREBOT_WRITER_AUTHORITY_READY
ENTRYPOINT_WRITER_AUTHORITY_READY
ENTRYPOINT_WRITER_AUTHORITY_VERIFIED
```

## Connect Kraken

Canonical platform variables:

```bash
KRAKEN_PLATFORM_API_KEY=YOUR_KEY
KRAKEN_PLATFORM_API_SECRET=YOUR_SECRET
```

Accepted platform aliases include:

```text
KRAKEN_API_KEY
KRAKEN_API_SECRET
KRAKEN_MASTER_API_KEY
KRAKEN_MASTER_API_SECRET
```

Recommended Kraken API permissions:

- Query funds.
- Query open and closed orders.
- Query ledger and trade history.
- Create and modify orders.
- Cancel and close orders.
- **Do not enable withdrawals.**

Kraken live readiness requires:

```text
writer lease ready
nonce authority ready
Kraken connected
positive spendable quote balance
balance payload hydrated
order adapter available
venue eligible for execution
```

Expected evidence includes:

```text
ENTRYPOINT_WRITER_AUTHORITY_READY
KRAKEN_CONNECTION_SUCCESS
CAPITAL_READY
THREE_VENUE_EXECUTION_STAGE venue=kraken
```

Kraken's configured effective order floor must be respected. Current defaults include additional headroom for fees and exchange minimums.

## Connect Coinbase Advanced Trade Correctly

NIJA connects to Coinbase Advanced Trade at:

```text
https://api.coinbase.com/api/v3/brokerage
```

Create a Coinbase Developer Platform **Secret API Key** using **ECDSA / ES256**, with **View** and **Trade** enabled and **Transfer** disabled.

Canonical variables:

```bash
COINBASE_API_KEY=organizations/ORG_ID/apiKeys/KEY_ID
COINBASE_API_SECRET="-----BEGIN EC PRIVATE KEY-----
YOUR_PRIVATE_KEY_BODY
-----END EC PRIVATE KEY-----"
ENABLE_COINBASE=true
ENABLE_COINBASE_TRADING=true
NIJA_DISABLE_COINBASE=false
```

Accepted aliases include:

```text
COINBASE_PLATFORM_API_KEY
COINBASE_PLATFORM_API_SECRET
COINBASE_CDP_API_KEY
COINBASE_CDP_API_SECRET
CDP_API_KEY_NAME
CDP_API_KEY_PRIVATE_KEY
```

NIJA evaluates Coinbase credentials as complete key/PEM families. It does not independently select a key from one alias family and a secret from another.

Expected normalization evidence:

```text
COINBASE_PEM_CANONICALIZED validation=es256 pair_source=<family> pair_count=<count>
```

A valid PEM proves key structure only; Coinbase is not connected until a private account or balance request succeeds.

Healthy Coinbase evidence:

```text
COINBASE_PEM_CANONICALIZED validation=es256 pair_source=<family> pair_count=<count>
COINBASE_AUTHENTICATED_PAIR_RECOVERED
COINBASE_CONNECTION_SUCCESS
authenticated Coinbase balance observed
NIJA_COINBASE_ACTIVATION_STATE=ready
NIJA_COINBASE_TRADING_READY=1
```

Credential normalization, ES256 validation, and recovery installation are not proof of a live Coinbase connection. If every private probe fails, NIJA restores the primary pair, publishes `authentication_failed`, and keeps Coinbase fail-closed without disabling Kraken or OKX.

## Connect OKX US Correctly

Canonical variables:

```bash
OKX_API_KEY=YOUR_KEY
OKX_API_SECRET=YOUR_SECRET
OKX_PASSPHRASE=YOUR_PASSPHRASE
ENABLE_OKX_TRADING=true
OKX_LIVE_TRADING_ENABLED=true
NIJA_OKX_EXECUTION_ENABLED=true
NIJA_OKX_LIVE_TRADING_ENABLED=true
NIJA_DISABLE_OKX=false
```

Accepted aliases include:

```text
OKX_PLATFORM_API_KEY
OKX_PLATFORM_API_SECRET
OKX_PLATFORM_PASSPHRASE
OKX_API_PASSPHRASE
```

The active endpoint contract is:

```text
https://us.okx.com
```

The three credentials must belong to the same OKX API key. Enable read and trade permissions, but do not enable withdrawals.

Healthy OKX evidence:

```text
OKX_CONNECTION_SUCCESS
NIJA_OKX_ACTIVATION_STATE=ready
NIJA_OKX_TRADING_READY=1
OKX_ROUTER_IDENTITY_CONVERGED
THREE_VENUE_EXECUTION_STAGE venue=okx
```

If credentials are absent, OKX is reported as `missing_credentials` and remains isolated.

## Independent Trade Entry Contract

NIJA's independent broker router scans every connected and eligible live venue separately.

For each brokerage, NIJA uses that brokerage's own:

- Spendable quote balance.
- Open-position count.
- Market metadata.
- Exchange minimum and fee buffer.
- Signal score and confidence.
- Risk and position limits.
- Order adapter.

Expected entry-routing evidence:

```text
BROKER_INDEPENDENT_LIVE_EXECUTION_PATCHED
BROKER_EXECUTION_DISCONNECTED_GUARD_PATCHED
BROKER_INDEPENDENT_SCAN_START brokers=okx,coinbase,kraken
BROKER_INDEPENDENT_SCAN_BROKER_START broker=<venue>
BROKER_INDEPENDENT_SCAN_BROKER_END broker=<venue>
BROKER_INDEPENDENT_SCAN_END
```

A disconnected broker must show a skip marker rather than receive an order attempt:

```text
BROKER_EXECUTION_DISCONNECTED_SKIPPED
```

A connected brokerage still will not enter a trade unless all normal conditions pass. Do not use `FORCE_TRADE`, forced activation, or writer-lock bypasses to manufacture an entry.

## Automatic Take-Profit And Stop-Loss Contract

NIJA has two complementary exit layers.

### Execution-engine exit monitor

Every `ExecutionEngine` instance is registered with the process-wide automatic exit monitor. It evaluates stored stop-loss, synthesized loss-cap stops, take-profit levels, trailing profit lock, trailing stop-loss, breakeven stop-loss, and combined trailing logic.

### Universal broker-native exit supervisor

Every connected Kraken, Coinbase, and OKX broker instance is registered directly, including platform and user accounts. This protects broker-native positions even when one execution engine does not own or mirror the position.

The supervisor uses verified entry price and quantity, broker-native market data, and a fee-aware minimum net-profit target before submitting a closing order.

Expected protection evidence:

```text
AUTO_EXIT_SL_TP_IMPORT_HOOK_INSTALLED
AUTO_EXIT_SL_TP_MONITOR_STARTED
UNIVERSAL_BROKER_EXIT_SUPERVISOR_INSTALLED
UNIVERSAL_BROKER_EXIT_SUPERVISOR_STARTED venues=kraken,coinbase,okx
UNIVERSAL_BROKER_EXIT_REGISTERED venue=<venue> account=<account>
```

Expected exit evidence when a valid trigger occurs:

```text
AUTO_EXIT_TRIGGERED
AUTO_EXIT_CLOSED
```

or:

```text
UNIVERSAL_BROKER_EXIT_TRIGGER
UNIVERSAL_BROKER_EXIT_CONFIRMED
```

The exit system must not invent entry prices or quantities. A position with unverified cost basis remains blocked until recovery supplies trustworthy data.

At startup the bot automatically runs `CostBasisReconciler` for each connected
broker to clear `auto_exit_blocked` on any position whose fill history can be
recovered from the exchange.  A `CostBasisAudit` daemon thread then runs
periodically (default every 3600 s) to repair any positions that were
unresolvable at startup.

For positions where fill history is **permanently** unavailable (e.g. positions
opened before the bot was deployed), set the adoption policy:

```bash
# "block"  (default) — adopted positions remain auto_exit_blocked=True until
#           fill history is recovered.
# "alert"  — exits are allowed; a warning is logged on every exit attempt.
# "allow"  — adopted positions are treated the same as verified ones (no warning).
NIJA_ADOPTED_POSITION_POLICY=alert
```

The startup-watchdog deadline can be extended when infrastructure barriers
(capital hydration, CSM ready) are expected to take longer than 5 minutes:

```bash
# Seconds to wait for SCAN_STARTED after writer lock acquisition (default 300).
NIJA_SCAN_STARTED_DEADLINE_S=600
```

Default protection settings include:

```bash
NIJA_AUTO_EXIT_SL_TP_ENABLED=true
NIJA_AUTO_EXIT_POLL_SECONDS=5
NIJA_UNIVERSAL_BROKER_EXIT_ENABLED=true
NIJA_UNIVERSAL_EXIT_POLL_SECONDS=3
NIJA_MAX_POSITION_LOSS_USD=2.00
NIJA_HARD_STOP_LOSS_PCT=0.015
NIJA_PROFIT_LOCK_ACTIVATION_PCT=0.008
NIJA_PROFIT_LOCK_CALLBACK_PCT=0.0035
NIJA_COMBINED_TRAILING_TP_SL_ENABLED=true
```

## Canonical Readiness Proof

A healthy deployment should progress through these groups.

### Authority

```text
PREBOT_WRITER_AUTHORITY_READY
ENTRYPOINT_WRITER_AUTHORITY_READY
ENTRYPOINT_WRITER_AUTHORITY_VERIFIED
AUTHORITY_HEARTBEAT_TIMEOUT_GRACE_INSTALLED
```

### Broker and capital bootstrap

```text
CANONICAL_BROKER_BOOTSTRAP_HANDOFF_INSTALLED
CANONICAL_BROKER_BOOTSTRAP_INITIALIZING
CAPITAL_READINESS_HANDOFF_V34_READY
FIRST_SNAPSHOT_GATE_LATCH accepted_latched=True stale=False
CAPITAL_READY
```

### Per-venue readiness

```text
SECONDARY_VENUE_ACTIVATION_INSTALLED venues=coinbase,okx
THREE_VENUE_EXECUTION_READINESS_INSTALLED
THREE_VENUE_EXECUTION_STAGE venue=kraken
THREE_VENUE_EXECUTION_STAGE venue=coinbase
THREE_VENUE_EXECUTION_STAGE venue=okx
LIVE_BROKER_CONNECTIVITY_SNAPSHOT ... all_configured_connected=True
```

### Runtime activation

```text
PREACTIVATION_READINESS_V16_RECONSTRUCTED
ACTIVATION_COMMITTED
NIJA_RUNTIME_TRADING_STATE=LIVE_ACTIVE
NIJA_RUNTIME_EXECUTION_AUTHORITY=1
RUNTIME_GUARD_AUDIT ... ready=true ... missing=none
```

### Trading and exits

```text
BROKER_INDEPENDENT_SCAN_START
BROKER_INDEPENDENT_SCAN_BROKER_START
AUTO_EXIT_SL_TP_MONITOR_STARTED
UNIVERSAL_BROKER_EXIT_SUPERVISOR_STARTED
UNIVERSAL_BROKER_EXIT_REGISTERED venue=<venue> account=<account>
```

`LIVE_ACTIVE` proves runtime readiness. It does not prove that a qualifying signal exists, that an order has been filled, or that an exit has closed.

## Mobile App

NIJA includes a Capacitor 5.7 mobile foundation for iOS and Android. The current repository contains the wrapper configuration, native projects, shared frontend, setup/build guides, and prototype mobile API routes.

**Current mobile status: pre-beta.** Native packaging exists, but production authentication, secure device storage, push/biometric verification, automated mobile tests, legal review, signed release builds, and store approval are still required.

The detailed mobile source of truth is [mobile/README.md](mobile/README.md).

Mobile clients are a secure control and visibility layer. Broker credentials, writer authority, risk decisions, and order execution remain server-side.

## Protection Stack Modules

Key live modules include:

```text
bot/authority_heartbeat_timeout_grace_patch.py
bot/current_capital_snapshot_freshness_repair_patch.py
bot/broker_independent_live_execution_patch.py
disconnected_broker_execution_guard_patch.py
secondary_venue_activation_patch.py
three_venue_execution_readiness.py
bot/broker_venue_cash_guard_patch.py
bot/position_close_pnl_runtime_patch.py
bot/auto_exit_sl_tp_runtime_patch.py
bot/universal_broker_exit_supervisor_patch.py
bot/trailing_stop_loss_runtime_patch.py
bot/breakeven_stop_loss_runtime_patch.py
bot/combo_breakeven_trailing_runtime_patch.py
bot/trailing_take_profit_runtime_patch.py
bot/combined_trailing_tp_sl_runtime_patch.py
bot/combined_trailing_position_size_calculator.py
```

## Earlier Verified Production Milestone — July 26, 2026

NIJA completed a successful production bootstrap milestone through the canonical Render runtime on July 26. That checkpoint proved Coinbase canonical-client recovery, all-three broker connectivity evidence, and universal broker exit registration in the same deployed window, but it did not yet prove `LIVE_ACTIVE`, an order submission, a fill, or a completed exit.

Historical anchor:

- Commit [`388e5f3`](https://github.com/dantelrharrell-debug/Nija/commit/388e5f31b41b74a04ef83128a85e245efb4de384)
- Branch [`recovery/2026-07-26-1437-three-broker-connected`](https://github.com/dantelrharrell-debug/Nija/tree/recovery/2026-07-26-1437-three-broker-connected)
- PR [#2279](https://github.com/dantelrharrell-debug/Nija/pull/2279)

## Official NIJA Links

- **Website:** [nijaaitrading.com](https://nijaaitrading.com)
- **Mobile documentation:** [mobile/README.md](mobile/README.md)
- **Owner:** NIJA AI Trading LLC

## Important Disclaimer

NIJA AI Trading is not financial advice.

Trading involves risk and may result in financial loss. Users are responsible for their trading decisions. NIJA does not guarantee profits, returns, income, trade frequency, order fills, or trading success.
