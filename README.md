# NIJA AI Trading LLC — Current Success State

**Status date:** July 26, 2026

**Last verified Render deployment:** [`388e5f3`](https://github.com/dantelrharrell-debug/Nija/commit/388e5f31b41b74a04ef83128a85e245efb4de384)

**Durable recovery branch:** [`recovery/2026-07-26-1437-three-broker-connected`](https://github.com/dantelrharrell-debug/Nija/tree/recovery/2026-07-26-1437-three-broker-connected)

**Repair provenance:** [PR #2279](https://github.com/dantelrharrell-debug/Nija/pull/2279) — Coinbase canonical-client and watchdog convergence

This README is the durable recovery anchor for NIJA. It separates what production logs have proved from what still must happen before trading is declared active.

NIJA does not guarantee trades or profits. A connected brokerage may enter a trade only when writer authority, authenticated capital, signal, risk, exchange-minimum, and order-admission checks all pass.

## Current Recovery Checkpoint — July 26, 2026 at 14:37 UTC

| Area | Proven state |
|---|---|
| Source of truth | Render entrypoint attestation proved branch `main`, deployed commit `388e5f3`, and the canonical `main.py -> bot.bot -> bot.bot_main` runtime |
| Coinbase | ES256 credentials canonicalized; canonical-client recovery v4 installed; the platform broker was registered for automatic exits and reported `coinbase_connected=True` in the all-three snapshot |
| Coinbase repair | Healthy clients are preserved only within the same account and credential family; stale aliases may adopt the verified client; pre-rotation clients are rejected; missing-client and confirmed-401 paths remain fail-closed |
| OKX US | Platform broker registered for automatic exits and reported `okx_connected=True`; earlier authenticated production evidence observed $144.96 and `funded` dual-wallet status |
| Kraken | Platform broker registered for automatic exits and reported `kraken_connected=True`; 824 tradable pairs were detected and one `ETH-USD` position was visible without tracker mutation |
| Three-broker convergence | One production snapshot reported `kraken_connected=True coinbase_connected=True okx_connected=True all_configured_connected=True` |
| Exit protection | Universal broker exit supervision registered Kraken, Coinbase, and OKX platform brokers in the same deployed window |
| Writer authority | The replacement Render instance remained safely in `ENTRYPOINT_WRITER_AUTHORITY_STANDBY` because the prior instance still held the Redis writer lease; generation 1887 was published |
| Kraken recovery coordinator | Installed and running, but waiting for the fencing token that becomes available only after writer authority transfers |
| Trading state | `STRATEGY_PUBLICATION_WAITING reason=state_not_live_active`; this window did not yet prove `LIVE_ACTIVE`, an order submission, a fill, or a completed exit |

### Durable recovery anchor

The recovery branch above is intended to point permanently to the repository state containing the verified Coinbase repair and this success record. Render credentials and broker secrets are environment variables and are not stored in GitHub, so they must remain configured separately.

To return safely to this checkpoint:

1. Open the [durable recovery branch](https://github.com/dantelrharrell-debug/Nija/tree/recovery/2026-07-26-1437-three-broker-connected) in GitHub.
2. Create a new recovery branch or pull request from that anchor into `main`; review the diff before merging. Do not force-push or hard-reset `main`.
3. If the application itself must be rolled back, use Render's rollback/redeploy control for the deployment associated with commit [`388e5f3`](https://github.com/dantelrharrell-debug/Nija/commit/388e5f31b41b74a04ef83128a85e245efb4de384).
4. Keep the existing Render environment variables, Redis instance, and broker credentials in place; the Git checkpoint cannot restore secrets.
5. Verify the markers below before allowing normal activation. Never delete the writer lease or use force-activation flags to manufacture readiness.

### Verified evidence at this checkpoint

```text
RUNTIME_ENTRYPOINT_ATTESTATION_OK ... branch=main commit=388e5f31b41b74a04ef83128a85e245efb4de384
COINBASE_AUTHENTICATED_CONNECT_RECOVERY_INSTALLED marker=20260726-coinbase-canonical-client-v4
UNIVERSAL_BROKER_EXIT_REGISTERED venue=okx account=platform
UNIVERSAL_BROKER_EXIT_REGISTERED venue=coinbase account=platform
UNIVERSAL_BROKER_EXIT_REGISTERED venue=kraken account=platform
LIVE_BROKER_CONNECTIVITY_SNAPSHOT ... kraken_connected=True coinbase_connected=True okx_connected=True all_configured_connected=True
```

### Safe continuation from this checkpoint

1. Keep the replacement Render instance running; do not repeatedly restart it while `ENTRYPOINT_WRITER_AUTHORITY_STANDBY` is present.
2. Wait for the previous instance to release its Redis lease, then confirm:
   ```text
   ENTRYPOINT_WRITER_AUTHORITY_READY
   ENTRYPOINT_WRITER_AUTHORITY_VERIFIED
   ```
3. Confirm Kraken's coordinator completes its authority handoff:
   ```text
   KRAKEN_RECOVERY_COORDINATOR_HANDOFF
   KRAKEN_AUTHENTICATED_RECOVERY_READY ... connected=true capital_rechecked=true
   ```
4. Confirm Coinbase remains connected through at least two 30-second connection-watchdog intervals. It must not be followed by `COINBASE_CLIENT_UNINITIALIZED_FAIL_CLOSED` for the same account.
5. Confirm broker-local readiness and authenticated spendable capital independently for every venue intended to enter trades.
6. Confirm normal activation gates commit:
   ```text
   ACTIVATION_COMMITTED
   NIJA_RUNTIME_TRADING_STATE=LIVE_ACTIVE
   ```
7. Confirm broker-specific scans, admitted orders, fills, and exits only from real runtime evidence. Connectivity alone is not proof of a trade or profit.
8. Never use forced activation, synthetic capital, credential bypasses, nonce bypasses, or writer-lock deletion.

## Earlier Verified Production Milestone — July 25, 2026 (historical)


NIJA completed a successful production bootstrap milestone through the canonical Render runtime.

| Component | Verified milestone |
|---|---|
| Canonical runtime | Deployed and entrypoint-attested |
| Distributed authority | Redis-backed writer and nonce safety connected |
| Kraken | Private balance hydrated and accepted |
| Capital pipeline | High-confidence live-exchange snapshot accepted with at least one valid broker |
| Bootstrap | Reached `CAPITAL_READY`; broker-scoped trading loop unblocked |
| Runtime activation | `LIVE_ACTIVE`, kill switch clear, and distributed writer heartbeat valid |
| Coinbase credential handling | Matched API-key/PEM family selected and ES256 validation passed |
| Coinbase live readiness | Authenticated balance and trading-readiness proof still required |
| OKX connection | Connected at manager layer; stable execution-readiness proof still required |
| Exit protection | Kraken account-exit, cost-basis, margin-cost, and downstream safety guards installed |
| Scan and execution | Trading-loop process reported running, but no observed scan cycle, order, or confirmed fill yet |

This is a successful **Kraken-backed capital bootstrap and live-authority activation**, not a claim that all configured venues are ready or that a trade or profit is guaranteed. Kraken and OKX were constructed as connected platform brokers, but only Kraken has stable private-capital and execution-readiness proof in the verified log window. Each optional venue remains isolated and fail-closed until its own private authentication, balance, and execution-readiness checks succeed.

The Coinbase credential-pair repair was delivered through [PR #2260](https://github.com/dantelrharrell-debug/Nija/pull/2260). It prevents startup from combining an API key from one configured credential family with a PEM belonging to another. A structurally valid PEM is not connection proof; Coinbase still requires a successful private account or balance request.

## Official NIJA Links

- **Website:** [nijaaitrading.com](https://nijaaitrading.com)
- **Mobile documentation:** [mobile/README.md](mobile/README.md)
- **Owner:** NIJA AI Trading LLC

---

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

---

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

---

## Production Startup Order

The active Render startup path is:

```text
scripts/production_bootstrap.sh
    -> start.sh
    -> main.py
    -> bot.bot
    -> bot.bot_main
```

Safety-critical order:

1. Start the isolated Render liveness server.
2. Acquire the Redis single-writer lease and fencing generation.
3. Start writer and authority heartbeats.
4. Initialize Kraken nonce protection.
5. Run SelfHealingStartup and connect the primary broker.
6. Initialize the canonical `MultiAccountBrokerManager`.
7. Connect configured Coinbase and OKX platform brokers.
8. Connect configured user broker accounts.
9. Hydrate real broker balances into `CapitalAuthority`.
10. Publish per-venue execution readiness.
11. Commit `LIVE_ACTIVE` only through the normal state machine.
12. Start independent broker-scoped scanning and execution.
13. Keep automatic position exits running for every registered live broker instance.

No deployment variable may pre-grant writer authority or `LIVE_ACTIVE`.

---

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

---

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

---

## Connect Coinbase Advanced Trade Correctly

NIJA connects to Coinbase Advanced Trade at:

```text
https://api.coinbase.com/api/v3/brokerage
```

### Create the correct Coinbase key

1. Sign in to Coinbase Developer Platform.
2. Open **API Keys** and choose **Secret API Keys**.
3. Create a key for NIJA.
4. Select **ECDSA / ES256**.
5. Enable **View** and **Trade**.
6. Keep **Transfer** disabled.
7. Restrict the key to the intended funded portfolio when applicable.
8. Save the complete API key name and EC private key.

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

NIJA evaluates Coinbase credentials as complete key/PEM families. It does not independently select a key from one alias family and a secret from another. Startup publishes the selected pair to the canonical variables while preserving other complete configured pairs for bounded authenticated recovery.

Expected normalization evidence:

```text
COINBASE_PEM_CANONICALIZED validation=es256 pair_source=<family> pair_count=<count>
```

A valid PEM proves key structure only; Coinbase is not connected until a private account or balance request succeeds.

### Coinbase PEM failure

This marker means Coinbase cannot authenticate:

```text
COINBASE_PEM_INVALID
```

It is a credential-format problem, not a trading-strategy problem. Correct it by replacing `COINBASE_API_SECRET` with the matching multi-line EC private key:

```text
-----BEGIN EC PRIVATE KEY-----
base64-key-material
-----END EC PRIVATE KEY-----
```

Rules:

- Preserve real line breaks.
- Preserve both boundary lines.
- Do not add leading spaces.
- Do not wrap the entire value in extra quote characters in Render.
- Do not paste an unrelated JSON payload or Ed25519 key.
- The private key must belong to the exact `organizations/.../apiKeys/...` name.

Validation commands from a secure backend shell:

```bash
python validate_broker_credentials.py
python validate_broker_credentials.py --test-connections
python scripts/auth_sanity.py
```

Required permissions:

```text
can_view=true
can_trade=true
```

Healthy Coinbase evidence:

```text
COINBASE_PEM_CANONICALIZED validation=es256 pair_source=<family> pair_count=<count>
COINBASE_AUTHENTICATED_PAIR_RETRY              # optional when alternatives exist
COINBASE_AUTHENTICATED_PAIR_RECOVERED
COINBASE_CONNECTION_SUCCESS
authenticated Coinbase balance observed
NIJA_COINBASE_ACTIVATION_STATE=ready
NIJA_COINBASE_TRADING_READY=1
```

Credential normalization, ES256 validation, and recovery installation are not proof of a live Coinbase connection. If every private probe fails, NIJA restores the primary pair, publishes `authentication_failed`, and keeps Coinbase fail-closed without disabling Kraken or OKX.

---

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

---

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

---

## Automatic Take-Profit And Stop-Loss Contract

NIJA has two complementary exit layers.

### Execution-engine exit monitor

Every `ExecutionEngine` instance is registered with the process-wide automatic exit monitor. It evaluates:

- Stored stop-loss.
- Synthesized loss-cap stop when a stored stop is absent.
- Take-profit 1, 2, and 3.
- Trailing profit lock.
- Trailing stop-loss.
- Breakeven stop-loss.
- Combined breakeven-to-trailing logic.
- Combined trailing take-profit and trailing stop-loss.

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

---

## Canonical Readiness Proof

A healthy deployment should progress through these groups.

### Authority

```text
PREBOT_WRITER_AUTHORITY_READY
ENTRYPOINT_WRITER_AUTHORITY_READY
```

### Broker and capital bootstrap

```text
CANONICAL_BROKER_BOOTSTRAP_HANDOFF_INSTALLED
CANONICAL_BROKER_BOOTSTRAP_INITIALIZING
CANONICAL_BROKER_BOOTSTRAP_READY hydrated=True capital=<positive> valid_brokers>=1
CAPITAL_READY
```

### Per-venue readiness

```text
SECONDARY_VENUE_ACTIVATION_INSTALLED venues=coinbase,okx
THREE_VENUE_EXECUTION_READINESS_INSTALLED
THREE_VENUE_EXECUTION_STAGE venue=kraken
THREE_VENUE_EXECUTION_STAGE venue=coinbase
THREE_VENUE_EXECUTION_STAGE venue=okx
```

### Runtime activation

```text
PREACTIVATION_READINESS_V16_RECONSTRUCTED
ACTIVATION_COMMITTED
NIJA_RUNTIME_TRADING_STATE=LIVE_ACTIVE
NIJA_RUNTIME_EXECUTION_AUTHORITY=1
```

### Trading and exits

```text
BROKER_INDEPENDENT_SCAN_START
BROKER_INDEPENDENT_SCAN_BROKER_START
AUTO_EXIT_SL_TP_MONITOR_STARTED
UNIVERSAL_BROKER_EXIT_SUPERVISOR_STARTED
```

`LIVE_ACTIVE` proves runtime readiness. It does not prove that a qualifying signal exists or that an order has been filled.

---

## Mobile App

NIJA includes a Capacitor 5.7 mobile foundation for iOS and Android. The current repository contains the wrapper configuration, native projects, shared frontend, setup/build guides, and prototype mobile API routes.

**Current mobile status: pre-beta.** Native packaging exists, but production authentication, secure device storage, push/biometric verification, automated mobile tests, legal review, signed release builds, and store approval are still required.

The detailed mobile source of truth is [mobile/README.md](mobile/README.md). It covers:

- Verified implementation status versus remaining work.
- The official NIJA black-and-gold sword-and-laurel brand system.
- The current Capacitor project structure and setup commands.
- The planned Expo React Native target structure.
- Server-side security and broker-secret boundaries.
- Home, Signals, Trades, Risk, and Profile product navigation.
- Live Mode consent, readiness, risk, and emergency-pause gates.
- A six-stage delivery roadmap and the next ten development milestones.

Mobile clients are a secure control and visibility layer. Broker credentials, writer authority, risk decisions, and order execution remain server-side.

---


## Protection Stack Modules

Key live modules include:

```text
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

---

## Important Disclaimer

NIJA AI Trading is not financial advice.

Trading involves risk and may result in financial loss. Users are responsible for their trading decisions. NIJA does not guarantee profits, returns, income, trade frequency, order fills, or trading success.
