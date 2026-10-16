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

## Research update: precise authenticated API budget and remote execution (2026-10-15)

Kraken's August 2026 limit guidance says per-key **private spot REST** calls have different weights: `TradesHistory`, `ClosedOrders`, and `Ledgers` increase the private call counter by **4**, while `Balance`/`TradeBalance` typically increase it by **1**. Avoid solving position refresh staleness by issuing repeated unthrottled history reads; preserve per-key serialized admission, bounded freshness checks, and documented backoff. https://support.kraken.com/articles/206548367-what-are-the-api-rate-limits-?mode=consumerapp

Render supports SSH to the **actual** running service, including `render ssh SERVICE_ID -- COMMAND ...` via Render CLI, provided the operator has authenticated CLI/SSH access. This is distinct from a separate ephemeral instance, which cannot read the service's mounted disk. An operator may use the existing running-instance session to *inspect* the already completed backup's archive inventory and source checksum. Do not print private data or attach archives to PRs. https://render.com/tutorials/render-cli-power-user/ssh-and-psql and https://render.com/docs/ssh

Kraken conditional close orders for spot margin are **not** comprehensive OCO stop-loss + take-profit coverage, and closing independently can leave an active conditional close that may open the inverse exposure. Any protective-exit audit must read actual open orders and current exposure; absence of open margin positions cannot certify another venue or account. https://support.kraken.com/au/articles/360038640052-conditional-close

The production log `backup_restore_verified=false` is emitted by v435 mount-observation code with a deliberately constant false value. It is not evidence that a completed operator restore test failed; neither is it evidence that one passed. Match existing operator reports to the archive source SHA-256, restoration results, and independent custody records before changing an attestation layer.
