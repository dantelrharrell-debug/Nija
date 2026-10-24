# NIJA v466: one-shot exact Kraken order/trade readback

## Why this path exists

Kraken history pagination has repeatedly exhausted the explicitly approved
page budget, while the canonical ledger has 13 pending unmatched platform
Kraken fill records. v466 offers a *more bounded* way to gather historical
evidence about those **exact order IDs**, using the already-running authenticated
Kraken client, its rate limiter, existing nonce owner, and current pending-ledger
rows. No orders are created/canceled, and the ledger is never changed.

This is **not** a complete cost-basis, ledger, fee-currency, account ownership,
open position, stop-loss, or execution authorization certificate. A successful
response is only a read-only private evidence receipt. No historical order
restamps execution proof age or meets a 1,800-second fresh-fill requirement.

## Required production conditions

- Independent production review of PR plus CI/secret scanning and Kraken rate
  monitoring; explicit operator review before any changes or live broker reads.
- The existing V363 deferred-fill worker must be deployed on the intended
  release. The opt-in recovery directory is already configured, private mode
  0700, owned by the same service process, and on appropriately durable storage.
- A fresh operator-created private mode 0600 file named exact_request.json
  **must** have exactly these JSON properties:
  request_id: new cryptographically random lower-case 32 hex characters;
  account_scope: platform:kraken;
  created_at: current Unix epoch seconds;
  max_pages: integer 1 (single exact-ID recovery mode, NOT history pagination).
- Do not reuse a failed recovery request ID. No old request.json may be present;
  both modes pending at once will defer. A non-owner or second independent
  Kraken instance will be rejected. The request expires after 300 seconds.
- The code snapshots the live SQLite pending table read-only. Unknown or
  ambiguous Kraken owner/scope, duplicate pending IDs, malformed rows, or
  more than 30 pending IDs fail closed, with no broker read.
- The existing broker uses the canonical monitoring API category for one
  QueryOrders request and up to three QueryTrades requests of at most 20
  IDs each (50 total trades maximum), with no retries. The source uses Kraken
  QueryTrades 20-ID maximum. Missing/extra/duplicate results, missing fees,
  wrong symbols or sides, unfilled orders, and incomplete trade IDs fail.
- Each request is moved to a private claimed file *before* broker I/O.
  An interrupted/failed request stays claimed and will never replay. Only
  a new operator-reviewed request can be issued.
- The result, including raw sensitive account rows, is written into a private
  mode 0600 evidence file in the same recovery directory. NEVER paste or
  upload the receipt to GitHub, ChatGPT, or public storage.
- Public logs contain only fixed error labels and aggregate counts.

## Remaining activation-critical work

The 13 fills are not reconciled until their opening lots, executed quantities,
entry/exit fees and fee assets, actual current position quantities, account
ownership and the full broker order-history context are independently proven
and safely committed to the canonical ledger. Exact-ID query readback cannot
prove that every historical trade belongs to this account or that all broker
orders are fully represented; the separate v441 complete history collector
still performs this broader certification.

Additionally verify all protective exits and independent current positions,
writer lease, nonce, duplicate fence, kill switch, limits and account scope.
Implement the independently reviewed cold-start two-phase admission transition
without relaxing strict post-trade verification. Do not promote execution
authority merely because this script writes a successful evidence receipt.

No live broker request is run merely by merging a PR; the operator's explicit
private short-lived opt-in is required. No background deployment is authorized
on the production service as part of this PR.
