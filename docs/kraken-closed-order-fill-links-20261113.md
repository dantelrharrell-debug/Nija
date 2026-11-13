# Kraken recovery: preserve closed-order execution links

The deployed recovery collector explicitly requests unconsolidated
`TradesHistory`, but requests `ClosedOrders` without either `trades` or
`consolidate_taker`. Kraken documents defaults of `trades=false` and
`consolidate_taker=true` for that endpoint. The collector can therefore finish
both verification passes consistently while its closed-order records omit
the individual execution IDs needed for downstream reconciliation.

The correction requests `trades=true` and `consolidate_taker=false` on every
closed-order page, in both cursor and offset modes and both verification passes.
The existing direct krakenex serializer sends lowercase form strings; gateway
JSON retains booleans. The adapter accepts only these exact boolean choices
and continues rejecting caller nonces, ownership filters and other parameters.
No new endpoint, API client, nonce owner, request budget or retry is introduced.

The regression models a two-fill order and 51 closed orders over two pages.
All four pagination/transport combinations fail against the release implementation
with missing fill links and pass after the correction. Tests also exercise
the real krakenex 2.2.2 signing/form path without network, reject wrong option
types and filtered requests, and retain denial without fallback on API errors.
Receipt, journal, ledger-intake, open-order and reconciliation checks remain
non-authorizing. An older intake fixture's exact parameter assertion also
required the already-existing TradesHistory unconsolidated flag.

## Official sources inspected

- https://docs.kraken.com/api-reference/account-data/get-closed-orders
  documents the trade-link and consolidation defaults.
- https://docs.kraken.com/api-reference/account-data/get-trades-history
  documents unconsolidated fills and cursor pagination.
- https://docs.kraken.com/api-reference/account-data/get-ledgers-info
  limits cursor pages to 50 ledger entries; cursor exhaustion, not its null
  count, establishes completion. Cursor mode already avoids the count query.
- https://docs.kraken.com/exchange/guides/rest/ratelimits
  assigns ledger/trade-history reads two REST counter points per call, with
  tier-specific decay. This does not justify bypassing NIJA's shared limiter.

This repairs execution-link collection; it does not accelerate the active
ledger read or prove opening basis, financing, protection or complete account
reconciliation. Existing private response journals and receipts are never
rewritten. New parameters apply only after a reviewed deployment and a
separately bounded new collection. Do not interrupt the current collection
merely to install this change. Required independent review, exact-release
security checks and deployment authorization remain outstanding. No collector
is registered, no protected files are provisioned, and no order is authorized.
