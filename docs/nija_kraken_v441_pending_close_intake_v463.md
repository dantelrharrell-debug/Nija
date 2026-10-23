# Kraken v441 authenticated-history receipt to ledger intake (v463)

**Status:** Offline diagnostic implementation for review. No production activation or collector registration. This report is NOT a certificate and cannot authorize orders.

## Purpose

Take an **existing**, independently obtained, private mode-0600 v441 historical evidence receipt and an existing ledger database. Confirm the receipt's *unsigned integrity digest*, exact software account scope, complete bounded read contract, and SQLite integrity, then inventory pending Kraken close IDs against the broker's exact closed-order IDs and TradesHistory `ordertxid` references. Count matching IDs without inventing missing entry lots, reconciling fees, or changing ledger rows.

v441 is already opt-in and must be run against a unique connected Kraken client only through its reviewed one-shot recovery procedure. This v463 tool NEVER makes broker requests, creates requests, repeats consumed requests, or installs the independent attestation collector. **A matching broker order ID is not a verified ledger/position match or independently verified account ownership.**

## Operator procedure (only after the production backup is preserved)

1. Preserve the existing production account state and ledger, securely copy backups off-host, verify their hashes, and perform an isolated restore. Do not touch legacy files or restart the trading service to run this intake.
2. Review the existing v441 receipt's claim, completeness/failure status, broker account ownership, and access permissions. An old, missing, failed or partially paginated receipt must not be relabeled as current evidence.
3. Run on an isolated machine against preserved copies where possible. Do not change any execution-control setting:

```sh
python -S -B scripts/nija_kraken_history_ledger_intake_v463.py \
  --receipt /private/recovery/ACTUAL_REQUEST_ID.evidence.json \
  --ledger /private/recovery/trade_ledger.db \
  --account-scope platform:kraken
```

`ACTUAL_REQUEST_ID` must be replaced with the actual approved, 32-character lowercase hexadecimal request ID before running the command; it is not a literal filename. Never copy raw account data or private receipts into a pull request, CI artifact, application log or conversation.

## Scope and safety guarantees

- Requires an existing absolute, private, regular, single-link, owner-controlled receipt; rejects duplicate JSON keys, unexpected provenance claims, changed readback payloads, invalid cursor observation times, account-scope mismatches, and SHA-256 mismatches. The SHA-256 is **not a signature or independent authentication proof**.
- Opens the SQLite database in read-only mode, checks table presence and integrity, and selects only currently pending Kraken closes for the exact requested account. This intake cannot restore missing historical entries or certify accurate realized P&L.
- Reports aggregate counts: pending closes, exact broker closed-order IDs present, exact trade-to-order references present, and overlap. All pending closes remain **unresolved** until a separate independently authenticated, lot-specific and fee-exact reconciliation is completed.
- Explicitly returns `authenticated_account_owner_certified=false`, `fills_and_fees_reconciled=false`, `protective_exits_broker_verified=false`, `offhost_backup_restore_certified=false`, `execution_ready=false`, `execution_authority=false`, and `authorizes_orders=false`, including on a successful intake.
- Receipt observation time is a capture bound, not the timestamp of any fill and **cannot satisfy NIJA's 1,800-second post-trade execution freshness gate**.

## Follow-on certification

After this intake, the separately audited account-scoped producer still needs credential fingerprint and permissions evidence, complete ledger opening positions/fees, exact protective stop and take-profit readback, unresolved order fence, writer/nonce ownership, and operator authorization. Off-host recovery must be independently verified. Only then should the reviewed pre-trade admission integration be considered. No automatic trading transition is included in v463.
