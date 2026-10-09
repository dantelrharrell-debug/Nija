# NIJA Global Research Architecture — v432 (October 8, 2026)

## Scope: verified versus aspirational

NIJA must **discover widely, analyze selectively, and execute only where independently authorized**. Scanning market data does not establish trade permissions, predictive profitability, strategy validation, or broker connectivity.

| Asset class | Market-data position | Live execution | Long / short |
| --- | --- | --- | --- |
| Crypto spot: Kraken, Coinbase, OKX | Public quote observer active, 1,824 combined listed pairs and 60 first-cycle quotes verified on the checked deployment; repeated coin listings are not unique assets | Canonical trading loop still held fail-closed | Long/spot sale only; spot sale is not an uncovered short |
| U.S. stocks and ETFs: Alpaca | Connected catalog returned 14,392 active assets, of which 13,506 were tagged tradable and 5,383 shortable on October 8. A catalog is not a real-time data feed subscription | Separate production broker activation, authorized live data and exit readback unverified | Long and short research; margin, current ETB/HTB locate, and broker readback required for live short |
| U.S. options | Alpaca has option contracts/quote APIs, NIJA execution adapter and account options permission not verified | Not cleared for live expansion | Put options have different risk/payoff than borrowed-share short |
| Global equities, futures, FX, commodities, bonds, crypto derivatives | Dedicated transports, entitlements, geography, clearing, calendars, contract specs, regulatory permissions unverified | Not authorized | Watchlist/research only pending integration |

The public observer at /market-observerz reports public bid/ask/last coverage, **not** OHLCV strategy evaluation, verified net edge, or trading readiness. The legacy strategy still has separate nested scan budgets and writer/execution gates.

## Target production design

1. **Registry:** store venue/native symbol, asset type, contract multiplier, country restrictions, settlement, tick/lot increments, exchange hours, listing state, data entitlement and live short-borrow eligibility. Respect stale/expired instrument metadata.
2. **Broad discovery:** refresh eligible markets at provider-supported cadence and rotate inexpensive snapshots within quotas. Count discovered, attempted, verified bid/ask, fresh OHLCV and strategy-evaluated separately. Missing quotes are not completed scans; share a canonical asset ID across repeated venue listings.
3. **Deeper research:** rank data-refresh priorities by spread, liquidity, volatility, time since last complete analysis and research quality; maintain fairness so long-tail assets are visited. Use clean timestamped bars, exchange sessions, historical listings, and corporate actions as applicable.
4. **Strategy candidates:** evaluate versioned trend, breakout/retest, momentum, mean-reversion, regime and spread strategies as independent *research* candidates; actual integration and efficacy are not assumed merely because a detector file exists. Spot sell is NOT shorting.
5. **Shadow net-edge ranking:** bot/research_edge_ranking_v432.py implements explicit long/short research eligibility with strict account scope, market availability, current bid/ask, borrowing (where supported), full costs and chronological test evidence. All results are research-only.
6. **Confirmed outcome ledger:** bot/confirmed_performance_report.py already reports winners, losers, breakeven, net expectancy and profit factor by confirmed broker/user close, net of recorded entry and exit fees; strategy attribution and missing costs are presently unavailable. Never fabricate attribution from nearby timestamps.
7. **Strategy validation:** stratify by strategy ID/version, account, venue, instrument, regime, long/short and risk cohort. Measure net expectancy, tail loss, profit factor, drawdown, slippage and fee drag. Validate chronological holdouts, rolling walk-forward, regime shifts, overfit corrections and selection bias; examine transaction costs, borrow, funding, spread, impact and taxes if applicable.
8. **Execution separation:** no scanner result clears writer lock, nonce, broker health, capital, kill switch, risk sizing, stale proof, minimum notional, or protective-exit gate. No automatic size escalation from a lucky streak or unverified signal.

## Research-only v432 contract

A research input declares explicit account scope, venue, instrument type, canonical symbol, versioned strategy ID, timestamped bid/ask, rights/session eligibility, borrowing status if relevant, conservative expected move, forecast volatility, full round-trip cost model, and independently generated chronological holdout evidence.

Outputs are one of blocked_in_research or shadow_research_only with precise blockers, conservative expected move net of spread/cost assumptions, and a descriptive research score. Outputs always say live_execution_authorized=false, orders_submitted=false and automatic_position_sizing_changes=false.

**Important:** The ranker only checks that the caller provides well-formed evidence fields; it does not authenticate the dataset or demonstrate actual realized profitability. A positive shadow score never permits live entry. This module is not wired into production execution, places no orders and makes no broker/API calls.

### Required provenance for any future learning loop

Join every canonical confirmed close to its immutable signed opening and closing order/fill IDs, exact fee records, account/venue identity, instrument, direction, entry-fixed strategy ID/version, regime, quantity and costs. Include financing/borrow/funding as relevant. Label unknown attribution explicitly unavailable rather than treating it as zero. Do not update strategy weights from unmatched fills, paper simulations mixed with live outcomes, or ambiguous P&L.

## Release criteria and remaining work

- [x] Public Kraken/Coinbase/OKX quote observer active in production deployment dep-db431ac9v7es73a861rg.
- [x] Confirmed-close winner/loser report exists with account isolation and recorded fees.
- [x] Scan fairness and broker catalog eligibility fixes shipped via PR #2974 and PR #2975.
- [x] v432 shadow-only engine and synthetic tests created on a feature branch.
- [ ] Complete the full GitHub CI, secret scan and review for v432.
- [ ] Independently validate datasets and strategy attribution; run out-of-sample and walk-forward cost-inclusive studies.
- [ ] Confirm Alpaca live deployment, market-data subscriptions, account status and current borrow/locate proof.
- [ ] Build compliant licensed adapters for desired international asset classes, then validate with paper trading.
- [ ] Authorize live policy changes only after separate risk/safety signoff and protected order/fill verification.

**Economic objective:** improve positive *verified net expectancy* and reduce drawdown, not maximize win percentage. A strategy winning 70% can still lose money when its losers and costs outweigh gains. No trading algorithm guarantees profits.
