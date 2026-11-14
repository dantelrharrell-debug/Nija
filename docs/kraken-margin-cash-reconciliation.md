# Margin cash comparison: first accounting component

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
The existing offline recovery workflow runs this suite without dependencies.
