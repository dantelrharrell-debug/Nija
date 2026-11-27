# Proposed recovery when historical strategy attribution is unavailable

Status: design for review under issue #3890. The current release still requires historical reconciliation. No startup or execution path consumes this proposal.

## Accounting boundary

Preserve all unresolved closes and their original execution references in the historical ledger. Keep their strategy attribution and realized strategy P&L unknown. Retain the original backup and its manifest in private custody. An opening entry in a separate accounting period requires its own provenance and must never settle a historical close or turn it into a new fill.

Before opening a period, fence all submissions and retries through the existing writer. Obtain a complete outstanding-intent inventory and an authenticated, exhausted broker history cursor for the exact account. Bound the observation interval before and after the proposed opening. Reject a fill, deposit, withdrawal, transfer, fee, rollover, or pending intent crossing that interval until independently reconciled. A matching wallet total alone cannot detect offsetting movements.

## Read-only comparison

Supply the independently calculated default-wallet USD opening balance as exact decimal text to rehearse_cash_only_baseline via expected_usd. Derive it from an independently retained opening statement and complete cash movements, with auditable source references and a matching cutoff. Keep the amount and underlying evidence private. The rehearsal checks it against both authenticated BalanceEx reads on the existing broker and requires an explicit USD row. It also checks empty open orders, empty margin positions and the supported wallet exposure. supplied_usd_matched records numerical agreement only. The caller must separately verify origin, completeness, account, scope and freshness.

Any noncash exposure, unsupported wallet, missing movement history or unresolved outstanding intent blocks this path. No liquidation or order cancellation is part of recovery.

## Before any production implementation

Independently review the accounting boundary and restore a copy in isolation. Demonstrate that historical losses, order IDs, and fences survive rollback. Specify unique period and event identities, a durable transactional cutover and restart behavior. Exercise duplicate, late and replayed pre-boundary events, a crash during cutover, stale observations, and simultaneous balance changes. A late historical event must halt new submissions pending review.

Adoption would require an explicitly reviewed change to the provisioning contract defining which facts the ledger receipt certifies for each period. Keep the existing receipt requirements in force until then. Release-specific security and artifact checks, signed source review and owner rollout approval remain prerequisites. A separate owner execution decision follows successful collector and live-execution verification.

## Isolated USD, BTC and BABY rehearsal

Run `python -B -S -m scripts.rehearse_kraken_opening_period --help` from the
checkout. Use separate standalone ledger and historical backup copies. Keep
the following evidence private. Supply a SHA-256 pin for each JSON input and
the historical backup. Obtain the pins from the reviewed evidence inventory.

The before and after files use the current-inventory format proposed in PR
#4086. Both must contain completed observations for the platform account.
The independently prepared boundary JSON contains:

- `account_scope` set to `platform:kraken` and `wallet` set to `default`.
- `cutoff`, `coverage_start` and `coverage_end` as UTC epoch seconds.
  The history and writer fence must span both complete observations.
- `opening_balances` with independently derived USD, BTC and BABY quantities
  as exact decimal strings. Derive the values from retained financial records.
- `history_cursor_exhausted`, `intent_inventory_complete` and
  `writer_fenced_through_interval` from verified private source evidence,
  plus the actual `movements` and `outstanding_intents` lists for the interval.
- `inventory_sha256` as the ordered pair of inventory file hashes and
  `historical_sha256` as the historical backup hash.

The rehearsal rejects holds, credit, unsupported nonzero assets, open orders,
open margin positions, crossing activity, outstanding intents, and changes to
the 13 historical exceptions. It models opening quantities in memory with
unknown cost basis and strategy ownership. It prints a count and comparison
status. The caller must establish provenance, independent account identity,
source completeness and freshness for an actual cutover. A pinned input can
still contain an incorrect assertion. This command issues no signed receipt
and implements no production cutover, ledger write or live activation.
