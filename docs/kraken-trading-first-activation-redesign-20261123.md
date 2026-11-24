# NIJA Kraken trading-first activation redesign (source-only proposal)

Status: design proposal, **not trading authorization**. Target: Render service `srv-d98dsr5aeets73fpbaqg`; production issue #3890. This document creates no orders, approvals, keys, or deployment.

## Objective
Make an authenticated, reconciled, bounded trading system reliably available whenever a strategy has a positive estimated net edge. Remove repeated manual paperwork from ordinary orders, not the broker/ledger integrity conditions that protect capital. No architecture can guarantee profitable trades or uninterrupted trading under exchange outages, stale state, or uncontrolled exposure.

## Separate three planes
1. **Release assurance** (on deploy or material source/config changes): reproducible image hash, software supply-chain scans, protected startup source authenticity, role-signature and custody review. Keep the existing three-receipt contract until an independently reviewed migration replaces it. Never fabricate receipt issuers or waive active mandatory controls in production.
2. **Account readiness** (continuous background reconciliation): one canonical Kraken client/nonce writer; account identity/permissions; durable order journal and duplicate fence; current balances, positions, fills, fees, open orders, protective exits; writer lease; operator authority and kill switch; 13 independently sourced observations with freshness budgets. Cache only validated, account-scoped, short-lived snapshots and invalidate on restart, unknown order outcome, lease loss, or discrepancy.
3. **Trading strategy** (each proposed order): risk-adjusted expected net value after fees/spread/slippage, confidence and drawdown bounds, pair/order-type/size policy; submit through the sole canonical writer only if account readiness remains current. No strategy signal can override missing order safety data.

## Proposed state machine
- `BOOTSTRAP`: restore durable journal, verify exact release and protected sources, acquire writer lease; new orders disabled.
- `SYNCING`: fetch authenticated Kraken snapshots and reconcile historical obligations; new orders disabled. Retry only idempotent read probes with jitter and bounded backoff.
- `PAPER_READY`: simulation and Kraken `validate=true` only; collect performance evidence.
- `LIVE_ELIGIBLE`: all current mandatory account and release conditions pass; issue exact-scope owner authorization proposal.
- `LIMITED_LIVE`: explicit bounded owner authorization active, per-order checks pass, and net-edge policy accepts the signal. Orders through durable journal and canonical writer only.
- `PROTECTIVE_STOP`: new orders denied on stale/unknown broker state, journal gap, protective coverage loss, nonce/lease conflict, kill-switch, or risk breach; manage existing exposure through approved protective paths.

## Failure scope and automatic recovery
- Strategy model fails: pause that strategy only; unaffected approved strategies continue if shared account state remains sound.
- Pair-specific market data or rate limit fails: pause/backoff that pair, not the whole service; preserve global account budgets.
- Noncritical reporting/analytics unavailable: alert and queue work without blocking safe orders.
- Shared account state, durable journal, nonce ownership, ledger/exits, kill switch or risk limits invalid: no new orders; never infer a green state from a timeout.
- Recovery is automatic **after authenticated evidence passes again** and any required existing owner authorization remains valid. Never auto-enable from a deployment heartbeat or cached flag.

## Kraken-specific implementation
- Support REST `AddOrder validate=true` for preflight; it does not submit an order or return a live order ID.
- Maintain strictly increasing nonces per Spot API key; only one nonce owner. Respect separate private and trading rate limits; use bounded backoff and distinguish per-pair throttling.
- For uncertain AddOrder/AddOrderBatch results, consult durable intent and authenticated order history before any retry. Never resend a possibly accepted order blindly.
- Reconcile WebSocket execution updates against periodic authenticated REST snapshots; detect disconnect gaps, late fills, partial fills and fee-currency changes.
- Maintain exchange-side protective orders where supported and verify their actual readback; local stop logic alone is not protection against process failure.

## Profitability acceptance
- Report net realized and unrealized P&L, fees, spread/slippage, win/loss payoff ratio, drawdown, exposure and trade expectancy by strategy and pair.
- Evaluate walk-forward/out-of-sample and paper results; account for multiple testing and adverse execution. Positive backtest alone never establishes a live edge.
- Begin with explicit small pair/notional/order-type limits and stop conditions. Scale only on evidence, not an arbitrary trading frequency target.

## Implementation slices / acceptance tests
1. Read-only gate dependency inventory: map every existing startup/activation gate to release, account or strategy plane; identify redundant duplicate checks without removing enforcement. Include 13-provider source owner map and exact image/commit.
2. Repair protected collector source and trust binding from genuinely reviewed production owners. No guessed files or signatures.
3. Reconcile historical 13 pending closes, current broker ledger/exits and durable submission journal, or independently certify a cutoff that preserves exceptions.
4. Add pure state evaluator and structured blocker metadata; deterministic tests for missing 1–13 observations, stale receipts, account mismatch, restart, nonce conflict, uncertain AddOrder/Batch, lease loss and protective-order disappearance.
5. Add scoped background probe retries and per-pair throttling; tests prove no unauthorized live order can be emitted.
6. Build net-edge and execution-cost metrics; shadow/paper and Kraken validation tests, then bounded first-order readiness evidence.
7. Run exact-head CI, security and artifact scans; resolve material findings. Independently verify actual deployment, collector_installed=true, all 13 current observations and signed source pins. Separate owner authorization required before first live order.

## Sources
- Kraken nonce: https://support.kraken.com/articles/360000906023-what-is-a-nonce-
- Kraken API limits: https://support.kraken.com/articles/206548367-what-are-the-api-rate-limits-
- Kraken validate preflight: https://support.kraken.com/ca/articles/advanced-api-faq
- NIST SSDF: https://csrc.nist.gov/projects/ssdf
- NIJA current review contract: docs/kraken-activation-controller-v1-review.md and docs/kraken-3890-production-provisioning-handoff.md

**Non-negotiable distinction:** make safe readiness achievable and automatically recoverable; never promise `no exceptions` to execution integrity, market conditions or loss limits.
