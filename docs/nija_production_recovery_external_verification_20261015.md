# NIJA production recovery: externally verified constraints (2026-10-15)

Status: operator runbook, NOT a readiness attestation. Do not run trading or merge/deploy this change merely because this checklist exists.

## Persistent ledger: existing runtime only

Render documents that persistent disks are available to the attached **running service instance only**, not to builds, predeploys, or one-off jobs. Moving a snapshot job to a separate Render instance **cannot read /data/trade_ledger.db**. Render automatic disk snapshots are useful disaster recovery but do not alone prove a consistent application-level restore. Never restore a full disk snapshot into the live running ledger for investigation, because changes after that snapshot may be lost.

References:
- https://render.com/docs/disks
- https://render.com/docs/ssh

Use the v436 source-preserving SQLite online backup from the EXISTING running instance after confirming the actual script and database paths. SQLite's online backup API captures a consistent transactional snapshot even with WAL and concurrent writers; do not substitute a raw `cp` of a live .db file. Securely transfer the resultant archive off-host and compare to the original recorded SHA-256, then run v436 `restore-test` on an ISOLATED host. Do not post archive, private journal, or credentials to GitHub Actions logs or PR artifacts.

Reference: https://sqlite.org/backup.html

## Kraken reconciliation and position/exit proof

Do not attempt `AddOrder`, `CancelOrder`, `CancelAll` or any other write to fix an observational discrepancy. Capture only read-only exact-account historical order and trade-fills evidence for unmatched closes. Account-history REST calls (e.g. `TradesHistory`, `ClosedOrders`) cost MORE rate-limit budget than basic balance calls; keep per-API-key throttling and retry/backoff intact. Confirm account identity, order/fill IDs, asset/side, timestamps, fees, quantities and entry linkage before any historical P&L correction.

Reference: https://support.kraken.com/articles/206548367-what-are-the-api-rate-limits-?mode=consumerapp

For *spot margin*, Kraken says a conditional close is placed after the entry fills; if the position is closed independently, the conditional close does not automatically cancel and may later OPEN a reverse position. Do not infer exit coverage just from an attached conditional-close descriptor. Verify actual open orders, side/quantity, account identity and current position exposure. Kraken **futures** use different conditional/OTO capabilities; do not treat futures semantics as interchangeable with spot margin.

References:
- https://support.kraken.com/articles/360038640052-conditional-close
- https://www.kraken.com/learn/futures-trading-conditional-orders

## Canonical readiness and release constraints

- Treat `execution_ready=false`, `execution_authority=false`, `trading_engine_ready=false` and `proof.execution_ready` pending as a denial of new-order authorization.
- Do not refresh an old proof timestamp, substitute capital hydration for execution proof, or extend proof TTL just to make the gate green.
- Preserve all operator kill switches and protective exit requirements.
- Require independent verified off-host retention, isolated restore integrity, exact-account Kraken reconciliation, position-sync freshness, confirmed protective exits, and legitimate fresh canonical execution provenance before any separately authorized rollout.
- This PR does not install a new verification record or set any production flag. An offline report does NOT prove custody or historical fill completeness.
