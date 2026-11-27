# NIJA Trading IQ — advanced simulator architecture proposal
Status: DESIGN ONLY; no runtime, infrastructure, billing or trading changes.

## Product boundaries
Two modes in one approved NIJA shell: (A) canonical free 12-round Trading IQ; (B) separate advanced simulated trading lab. The canonical mode's manifest, order, educational scoring and optional adult paid-report contract must remain unchanged without a separately approved migration. Simulator P&L never becomes the Trading IQ skill score.

## Proposed isolated components
- simulator/scenario-catalog: versioned, licensed historical or fictional OHLCV candles; metadata, provenance, deterministic seeds and content digests.
- simulator/replay-engine: virtual clock and candle-by-candle progression; forbid future-candle access/lookahead.
- simulator/order-engine: simulated market, limit and stop orders; explicit spread, slippage, fee, fill and partial-fill assumptions; no broker SDK or external order submission.
- simulator/virtual-ledger: virtual cash, positions, cost basis, realized/unrealized P&L, journal and replayable event log.
- simulator/risk-engine: position size, maximum exposure, stop distance, drawdown and concentration limits; fail-closed invalid orders.
- simulator/analytics: equity curve, drawdown, exposure, discipline metrics and deterministic educational feedback.
- simulator/progress: opt-in local persistence for free practice; server storage only after separate privacy review and consent.
- simulator/ui: reuse verified NIJA tokens, accessibility patterns, chart and Academy navigation; no source substitution.

## Integration boundaries
- No imports from production trading controller, brokerage adapters, API credentials, kill switch or real order routing.
- Separate simulator build/runtime from Nija_Trading_Bot and its live services; never adopt existing production resources to bypass billing holds.
- No real-money deposits, winnings, cash prizes, trade signals, broker connectivity or live trading claims.
- The TIQ12 $1 report backend remains separately gated: adult-only, test-mode first, signed raw-body Stripe webhooks, server-owned manifest, durable idempotent grants, buyer ownership, replay/refund/dispute revocation. No checkout activation in this work.
- The 72-decision staging prototype may be evaluated for reusable concepts but cannot be treated as the canonical game or automatically redeployed.

## Suggested API contracts (future review only)
GET /simulator/scenarios -> versioned public educational scenario metadata.
POST /simulator/runs -> optional authenticated/consented virtual session creation.
POST /simulator/runs/:id/decisions -> bounded decision; server verifies sequence and ownership when persistence enabled.
GET /simulator/runs/:id/report -> educational analytics; never Stripe paid TIQ12 report.
All future endpoints require independent threat modeling, rate limiting, origin/CSRF checks, storage approval and API versioning.

## Delivery stages
A. Canonical source/design reconciliation.
B. Standalone deterministic simulator library and synthetic fixtures.
C. Accessible NIJA UI integration behind disabled-by-default flag.
D. Educational Coach/Academy mapping and optional opt-in progress.
E. Independent security, privacy, mobile QA and owner-reviewed release.

Do not commit runtime files or deploy any service under this Gate A documentation approval.
