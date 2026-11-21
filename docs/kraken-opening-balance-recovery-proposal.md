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
