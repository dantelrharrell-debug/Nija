# NIJA AI Trading LLC — Current Success State

**Status date:** July 23, 2026

This README is the current recovery anchor for NIJA. It documents the active production broker contract, startup order, independent trade-entry path, automatic take-profit/stop-loss protection, and mobile-app direction.

NIJA does not guarantee trades or profits. A connected brokerage may enter a trade only when writer authority, capital, signal, risk, exchange-minimum, and order-admission checks all pass.

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

Do not keep conflicting Coinbase credential aliases. A stale canonical `COINBASE_API_SECRET` can override a valid alias.

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
COINBASE_AUTH_NORMALIZED
pem_ok=True
COINBASE_CONNECTION_SUCCESS
NIJA_COINBASE_ACTIVATION_STATE=ready
NIJA_COINBASE_TRADING_READY=1
```

Credential normalization alone is not proof of a live connection.

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

## Mobile App Blueprint

The NIJA mobile app remains education-first.

Five planned tabs:

1. **Home** — account, broker, system, positions, risk, and emergency pause.
2. **Signals** — confidence, ADX, volume, spread, fees, readiness, and pass/skip reasons.
3. **Trades** — completed, failed, skipped, and simulated activity.
4. **Risk** — loss limits, position size, leverage, balance checks, disclosures, and consent.
5. **Profile** — account, connected brokers, privacy, terms, support, and deletion.

Live Mode must remain locked until disclosures, consent, broker permissions, verified balance, execution readiness, audit logging, and emergency pause are complete.

Broker secrets remain server-side only.

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
