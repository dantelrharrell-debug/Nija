# Margin cash and open-position comparison

`bot/kraken_margin_cash_reconciliation.py` compares independently persisted
margin/rollover ledger rows against supplied Kraken Ledgers records. It performs
no I/O and is deliberately not wired into startup or the certification provider.

Kraken documents margin realized P&L in `margin.amount`, opening/trading fees in
`margin.fee`, and financing fees in `rollover.fee`. Spot `trade` transfers cannot
be used as a replacement. The implementation sums exact decimal strings per raw
asset code, preserves exchange references, rejects nonzero rollover amounts,
and compares every included ledger ID, type, subtype, asset, class, timestamp,
amount, fee and running balance against its independently persisted counterpart.
Missing/extra rows, duplicate local IDs and account/key provenance conflicts deny.

Sources checked on November 14, 2026:
- https://docs.kraken.com/api-reference/account-data/get-ledgers-info
- https://support.kraken.com/articles/360027712571-how-to-calculate-profits-losses-from-trading-on-margin
- https://docs.kraken.com/api-reference/account-data/get-open-positions
- https://support.kraken.com/articles/360001184886-how-to-interpret-trades-history-fields

## Call contract

`compare_margin_cash_records(exchange_ledger, persisted_rows, account_scope=...,
account_sha256=..., api_key_sha256=...)` accepts an exchange ledger-ID mapping
and a list of independently persisted margin/rollover records. Each persisted
row carries the Kraken fields plus `exchange_ledger_id`, `broker`,
`account_scope`, `account_sha256` and `api_key_sha256`. Financial values must be
plain decimal strings. This function neither creates those records nor verifies
that their declared provenance is authentic. Callers must not copy the exchange
input into the local argument and describe the match as independent evidence.

An empty/empty comparison reports zero matched rows, not complete history.
Known non-margin types, including settlements, are explicitly counted as
excluded; unknown types fail closed. The output never establishes complete
pagination, authenticated identity, independent provenance, current balances,
position reconciliation, protective exits, collector certification or orders.
It contains no private ledger IDs or transaction references. Fixed denial codes
do not interpolate input values. No API calls, signing, database writes,
credential changes, startup hooks, or production configuration changes occur.

## Individual open margin position comparison

`compare_margin_position_records(exchange_positions, persisted_rows,
account_scope=..., account_sha256=..., api_key_sha256=...)` compares the supplied
unconsolidated OpenPositions result against independently persisted position
records. It requires the exact position-ID set, original opening-order ID, raw
pair code, direction, order type, position timestamp, cost, fee, opened volume,
closed volume and margin amount to match. Financial values remain bounded decimal
strings. Missing, extra, duplicate, malformed, closed, zero-margin or conflicting
rows deny. Multiple position IDs may share an opening order, preserving partial
executions instead of merging them by order ID.

Each local row carries `exchange_position_id`, `broker`, `account_scope`,
`account_sha256`, `api_key_sha256` and the listed native Kraken fields. Read
OpenPositions without market consolidation and without a position-ID filter.
The caller must establish request scope and response completeness; this pure
comparison cannot detect an omitted position that is missing from both inputs.
Do not copy the broker response into local rows and call that independence.

Remaining base quantities are computed as `vol - vol_closed` with exact decimal
arithmetic. Buys and sells remain separate per raw pair code, so opposite
positions cannot conceal each other's exposure. These quantities are not USD
valuation. Dynamic `value`, `net`, financing terms and next-rollover time are
outside this comparison and are not authenticated by its output. Fees still
require the separate ledger cash comparison; a matching position fee field
does not identify the asset actually charged.

Outputs contain counts and aggregate quantities, not position/order IDs.
`input_positions_match` reports agreement of the supplied static terms only.
Complete-snapshot, identity, fill-allocation, balance, protection, collector
certification and order-authorization flags remain false, including for empty
inputs. This adds an accounting comparison, not a production persistence owner,
margin-aware collector provider, account-risk publisher or startup binding.

## Remaining integration work

The November 14 live inspection found zero trade-ledger rows and zero strategy
intents, with 13 pending-close rows. Saved recovery evidence describes 13 orders
and 18 fills, but explicitly does not verify lots/fees, protection, or independent
identity. Both protected startup files were absent. These historical counts do
not establish current Kraken balances or holdings.

This component does not resolve the missing persistence owner, trade-to-position
allocation (including partial closes/settlements), protective exchange order ID
mapping, complete spot/margin balance reconciliation, account risk publisher,
durable submission inventory, or authentic startup receipts. The existing spot
provider continues to reject margin history. Its rejection must not be removed
until a complete margin-aware provider replaces its accounting assumptions.
Independent review and exact-release deployment checks remain required. No
production deployment should be requested for this helper alone.

## Offline validation

Run `NIJA_DEFER_RUNTIME_SITE_HOOKS=1 python -B -S -m unittest discover -s tests
-p test_kraken_margin_cash_reconciliation.py -v` on one line. Tests cover loss
and fees, tiny fees beside large amounts, distinct assets, missing/extra/duplicate
records, account and credential conflicts, malformed decimals, changed terms,
unknown types, nonzero rollover amounts, no input mutation, and non-certification.
Position tests additionally cover partial closes, duplicate/missing/extra lots,
shared opening orders, separate buy/sell totals, every static field, scope
conflicts, unsupported consolidation, row budgets, tiny remainders beside large
volumes and fixed errors that do not disclose position/order identifiers.
The existing offline recovery workflow runs this suite without dependencies.
