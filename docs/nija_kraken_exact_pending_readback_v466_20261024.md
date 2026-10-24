# v466: Targeted Kraken pending-order evidence collection

**Review-only implementation. No production call, deployment, retry, or trading authorization.**

Production contains 13 pending platform-Kraken closing records that the canonical
trade ledger cannot match to a verified opening position. A preserved October 23
backup showed 13 distinct Kraken-format IDs, mixed buy and sell directions, and
zero canonical OPEN/closed-trade rows. These records are an unresolved
accounting exception, **not evidence of 13 profitable exits**. Never infer
whether a buy closes a short without the authenticated opening lot.

## Motivation

The existing optional v441 historical collector repeatedly failed on its
explicit complete-pagination budget. Kraken's private REST QueryOrders
endpoint can query **up to 50 exact order IDs in one authenticated read**. This
code offers a narrower, bounded way to validate the pending audit references
without repeated account-wide history pagination or order submissions.

Before any operator invokes it:
1. Verify current persisted ledger identity, snapshot age, owner and path,
   existing claims, and whether the previous account-history collection needs
   review. Do NOT run this against restored old data and interpret as live.
2. Independently verify the account is platform:kraken and the selected
   existing client already owns the authenticated private API and nonce.
3. Obtain operator-approved Kraken private REST rate budget and confirm the
   monitoring category and broker I/O limiter still protect runtime traffic.
4. Confirm a separately reviewed composition root can call
   inspect_exact_pending_orders(Path("/data/trade_ledger.db"), existing_broker,
   account_scope="platform:kraken", monitoring_category=CANONICAL_MONITORING)
   exactly once, after review, without blocking writer renewal or normal safety
   probes. **Do not import this function into the main loop by default.**
5. Preserve the currently verified encrypted off-host backup before any other
   production change. The existing private recovery identity must be retained
   separately.

## What the function does

- Reads only the existing canonical SQLite pending-close table, requiring a
  valid schema, integrity check, exact account scope, 1..50 unique Kraken IDs.
- Invokes only Kraken QueryOrders with the exact 13 IDs and trades=True via
  the **existing** preauthenticated broker client and monitoring category.
- Has **no automatic retries**. It checks exact returned order IDs, symbols,
  sides, filled amounts, fees and prices, current broker scope and unchanged
  ledger rows. Unknown rows or changes fail closed.
- Returns aggregate statuses and count only. It never prints order IDs,
  account data, API key, per-fill values or upstream exception text.
- No order placement, ledger writes, nonce-sidecar client, state changes,
  kill-switch operations, startup admission, or execution-proof generation.

## What this does NOT establish

A matching QueryOrders row cannot by itself certify all historic fills, fees,
account ownership, current positions, opening lots, protective stop orders,
full-history completeness, duplicate-intent fence, or safe live trading. It
does not mark the 13 pending closes reconciled. Exact fills, ledger entries,
broker-authenticated opening transactions, current holdings, and exchange-side
protective orders need an independent account-scoped review.

The system must remain RUNNING_SUPERVISED with execution authority False
until every production readiness condition passes. Review the actual full
release diff and hosted tests before considering use. This module does not
automatically install in or change the deployed image.

## Regression

Synthetic offline tests:
python -m pytest -q tests/test_nija_kraken_exact_pending_readback_v466.py

Local isolated test run: 18 passed with a local mirror for _broker_account_scope;
hosted CI must run against the exact release runtime code.
