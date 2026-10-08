# NIJA market coverage and performance audit — October 8, 2026

## Outcome and scope

The upgrade repairs supported-market discovery and scan starvation, measures
actual scoring-loop coverage, reports confirmed winners/losers per broker and
user, and hardens current Alpaca short eligibility. It does not certify global
market access, profitable strategies, optimal timing or live trading readiness.

Base inspected: `1e4f7807f628fc00afac4525b0c3051ade13aa54`; subsequently synchronized
with `bf134dbb9755b4e962e45d98a1a7f313d4caa218` (PR #2972's independent public spot
quote observer). That observer measures public quotes, not account permissions,
entry signals, fills or profit. Its existing implementation is preserved.

## Findings and implemented repairs

| Finding | Repair | Evidence/limit |
| --- | --- | --- |
| Outer scanner admits up to 100 symbols; nested Phase 3 budgets admit fewer | Outer windows now prioritize symbols actually missed by the scoring loop | Offline replay with 1,000 instruments, a 100-symbol outer window and eight-symbol inner budget reaches every symbol |
| Priority symbols beyond the reserved first six could disappear permanently | Remaining priority symbols stay in the exploration pool; at least half of a constrained budget is available for exploration | Regression replay at budgets 1, 2, 8 and 24 |
| One global rotation counter served different brokers/accounts | Admission history belongs to each core-loop/broker instance | Independent-account wrapper test |
| A requested scan window could be mistaken for completed coverage | Track advertised universe, actual scoring-loop visits and usable data responses separately | Admission alone increments no evaluation counter; visits include explicit data/quarantine rejection, not necessarily successful scoring |
| Coinbase arbitrary base-ticker length 2–8 excluded legitimate catalog identifiers | Accept catalog-observed alphanumeric bases without an arbitrary length ceiling | Single-character and long-ticker regression |
| Coinbase catalog visibility could include view-only/disabled/order-restricted or unsupported product types | Exclude known restrictions and keep this adapter's spot scope | Catalog fixture covers view-only, disabled, cancel/limit/post-only, auction and futures rows |
| Kraken discovery used substring matching for quote currencies and did not exclude known offline states | Match USD/USDT/USDC exactly and exclude known non-online pairs | Exact-quote and offline regression; does not add FX conversion or futures transport |
| Winner/loser modules exist, but main orchestration does not prove their integration | Add a read-only report directly from confirmed-close ledger rows | Re-read current recorded fees; no secondary P&L ledger or automatic sizing multiplier |
| Cross-user or cross-venue statistics could distort a learning decision | Require explicit owner plus exact close-transaction broker identity | Other users, other brokers and manual closes excluded; duplicate close rows count once |
| A positive gross trade can lose after fees | Classify wins/losses/breakeven from reconciled net P&L; report expectancy and profit factor | Gross-positive/net-negative and late-fee-update fixtures |
| New borrow status could conflict with deprecated easy-to-borrow flags | Current status wins; unavailable/unknown status fails closed | HTB plus stale easy flag cannot authorize a short |
| Alpaca adapter exposed no current asset metadata to the profitability gate | Add read-only asset/account metadata interface with eligibility checks | Require finite equity ≥ $2,000, explicit short permission and an active, unblocked account |
| HTB locate metadata was accepted as proof | Keep HTB blocked until authenticated locate readback, expiration, quantity and consumption are implemented | A signal's locate flag/id is no longer sufficient |
| Canonical fee diagnostics lost a compatibility export | Restore `_patch_exchange_capabilities` alias to the existing core implementation | Existing fee/capability regression now passes |

Telemetry is per process and broker instance. Restart/reconnection begins a new
coverage history. `data_available` records a usable response, not verified candle
timestamps. The adapter's advertised universe can be regional, quote-restricted,
or a fallback; coverage percentages must never be described as worldwide coverage.

Confirmed performance is net of recorded entry/exit fees. Borrow, funding, tax,
and other carrying costs are not certified. Missing strategy attribution remains
`unavailable`, not fabricated. Reports use a bounded latest-close window and label
possible truncation. A 20-trade label is descriptive only, never validation of edge.

## What remains necessary for the requested worldwide trading system

1. **Live readiness:** Render logs at 2026-10-08 23:25:43 UTC showed
   `trading_engine_ready=False` and `execution_ready=False`. At 23:34:28 UTC they
   still showed `EXECUTION_ALLOWED: FALSE`. These are point-in-time observations.
   Scanner upgrades do not clear stops, invent proof or authorize execution.
2. **Venue inventory:** This audit observed Kraken/Coinbase/OKX in the live
   deployment context. Alpaca code supports US equities/ETFs, but its production
   activation, data subscription and protection readback still need verification.
3. **Other asset classes:** Worldwide equities, FX, futures, options and commodities
   need actual account-authorized transports and feeds. Kraken's spot AssetPairs
   response is not evidence of a working derivatives adapter. Coinbase's broader
   platform support is not proof that this NIJA spot adapter supports it.
4. **Strategy provenance:** Trend, momentum, breakout and mean-reversion selection
   code exists; direct wiring from those modules to the current canonical
   orchestration is not established by this audit. Record strategy, regime,
   direction, broker/account, entry/exit/fill ids and full costs before using
   results to allocate capital among strategy families.
5. **Research validation:** Obtain a verified historical dataset with timestamps,
   trading calendars, fees, spreads, slippage, carry, delistings and corporate
   actions as applicable. Use chronological holdouts/walk-forward evaluation;
   account for repeated strategy/parameter searches. The scan replay is an
   engineering regression, not a market backtest or return forecast.
6. **Controlled activation:** Existing entry/exit thresholds, sizing, kill switch,
   writer/nonce authority, capital and position/fill gates remain in force. Do not
   activate all strategies or increase winner position size on an unvalidated
   global singleton. Backtest each changed trading policy, then observe paper
   and controlled live results separately.
7. **Release:** AGENTS.md requires passing CI/secret checks and human review of
   strategy/broker changes before merging. Render auto-deploys main; any merge can
   restart the service and interrupt a stability observation.

## Research sources

Official broker documentation and primary research checked October 8, 2026:

- [Kraken tradable asset pairs](https://docs.kraken.com/api-reference/market-data/get-tradable-asset-pairs): pair metadata and country/region filtering.
- [Kraken instrument stream](https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/instrument): reference data, online status, increments and marginability.
- [Coinbase list products](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/products/list-products): product types, disabled/view-only and order restrictions.
- [Coinbase Advanced Trade overview](https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/overview): distinct spot/derivatives interfaces; platform capability is separate from NIJA integration.
- [OKX API documentation](https://www.okx.com/docs-v5/en/): instrument state, account mode and instrument-specific trade configuration.
- [Alpaca borrow-status change](https://docs.alpaca.markets/us/changelog/2026-06-05-borrow-status-6b96a5a): current borrow_status replaces easy_to_borrow.
- [Alpaca margin/short selling and locates](https://docs.alpaca.markets/us/docs/margin-and-short-selling): account equity, ETB/HTB and authenticated locate requirements.
- [The probability of backtest overfitting](https://escholarship.org/uc/item/4w1110bb): repeated strategy searches can overstate apparent performance.
- [Deflated Sharpe Ratio, author paper](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf): selection bias, non-normal returns and backtest evaluation.

## Validation

75 targeted pytest tests pass without credentials or live orders. All changed
Python files pass syntax compilation. Local verification uses Python 3.12; the
production Python 3.11 matrix remains a CI requirement. Secret scanning finds no
new findings (three unchanged baseline keyword findings in broker_manager.py).
Focused CodeQL SQL/command-injection queries report zero findings. The prescribed
secret-scanning/CodeQL connector tools were unavailable; detect-secrets and the
official CodeQL CLI were used as local equivalents. These focused queries are
not a complete security audit. The 1,000-symbol replay verifies engineering coverage under nested limits.
The repository's older stall-guard test file has three shared-fixture/idempotent
patch assertions that fail in a combined run. Replaying the unchanged HEAD
module/test in an isolated baseline also yields the same three failures (two
passes). These are recorded as a pre-existing test-harness limitation.

No claim of production deployment, complete worldwide scanning, strategy
profitability or a completed 24-hour observation is made by this report.
