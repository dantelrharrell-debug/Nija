# NIJA Kraken protection + accounting recovery runbook (2026-10-08)

**Status:** repair code in PR #2977, not deployed. Zero new orders or reactivation are authorized by this runbook.

## 1. Kraken protection proof, exact owner scope

Audit platform Kraken and every connected Kraken user account **separately**. Compare:
- API connection, authenticated private account identity, read/query permissions and nonce authority
- `OpenPositions` private response and the authoritative *spot* balance/positions snapshot (empty margin positions do not prove spot is empty)
- deployed tracker quantities vs broker positions, snapshot generation/age and stop-loss/take-profit/trailing-exit attachment
- exact broker-local health/position proof; do not rely on a global or stale `connected` flag

`KRAKEN_OPENPOSITIONS_DIAGNOSTIC_V410` now identifies `broker_disconnected_or_unconfigured` for the adapter's generic not-connected exception. Other errors remain classified/redacted. A failed read is **unproven**, not an authenticated empty position list.

If read permissions or credentials are missing, correct them in Kraken/Render secrets via the operator-approved secure channel. Use a dedicated non-withdrawal key scoped to necessary private read functions and an appropriate trading key only where explicitly authorized. Avoid exposing secrets in logs or GitHub. Recheck the existing bounded reconnect supervisor; do not reset nonce, lease or emergency stops to force success. The owner must separately confirm that protective exits exist or are actively enforceable for every actionable real position before any new entry is allowed.

## 2. Persistent ledger prerequisite

Render `nija-trading-bot` currently reports no attached disk while accounting defaults to `/app/data/trade_ledger.db` under Docker `WORKDIR /app`. The service may lose SQLite and execution-journal data on deploy/restart. **Never merge this repair on the assumption local data are durable.**

Operator: back up any surviving runtime SQLite/journal files, then attach a supported persistent disk to the trading service and verify its mount, write permissions for Docker UID 1000 and backup/restore policy. Either:
- mount at `/app/data` to preserve all relative `./data` artifacts, or
- mount at a durable directory and set `NIJA_TRADE_LEDGER_DB_PATH` to its database file, `NIJA_EXECUTION_JOURNAL_PATH` for the journal, and `NIJA_KRAKEN_PENDING_FILL_PROOF_PATH` for Kraken pending recovery.

Before switch-over, reconcile/migrate existing files with immutable backup + integrity check; an empty new database is **not proof of no previous trades**. A Postgres-backed unified trading ledger is a stronger later architecture if multiple writers/replicas are planned. Do not reuse the billing database as a shortcut.

## 3. Orphan fill reconciliation

A Kraken QueryOrders `closed`/filled order without a ledger position is not sufficient to assume entry cost/owner. Read Kraken `QueryOrders`, `TradesHistory` and any applicable authenticated position history. Require exact order ID, account identity, security, direction, amount, executed quantity, weighted fill prices and actual entry/exit fees. Separate spot fills from margin positions. Resolve partial fills and one-to-many exits without grouping unrelated positions.

PR #2977 atomically writes **future or verifiably replayed opening** QueryOrders fills, fixes short-entry SELL to ledger OPEN, and allows repair of a single exact orphan OPEN row. It intentionally does not construct unknown historical positions, guess missing fees or post synthetic realized P&L. Flag unresolved histories `pending` until verifiably matched.

## 4. Heartbeat and per-security short selling

Keep `NIJA_ALLOW_LIVE_HEARTBEAT_ORDERS=false` and `HEARTBEAT_TRADE=false` in production. LIVE startup and an expired heartbeat proof never imply consent to a paid verification order. Check logs for `LIVE_HEARTBEAT_POLICY_V433_DENIED` when older code attempts to re-arm.

For Alpaca equity shorts, require `shortable is True` on *that symbol* plus live account permission, current borrow proof and open market session. Missing/false/stale values block research eligibility and do not authorize orders.

## 5. Strategy outcome audit

New `strategy_order_intents` rows are pipeline **order intents**, not fills. Performance reporting attributes outcomes only on an exact broker+account+order link to an authenticated Kraken opening transaction and an independently confirmed, fee-consistent closed trade. A strategy performance sample must show both attributed and unattributed counts; old trades without exact provenance remain unknown.

## 6. Release verification / rollback

Review PR #2977 as **high risk**, require human approval, Python compile, targeted unit tests, branch/security CI and isolated broker-mock tests. Confirm Render still deploys `main` only. On approved deploy verify readiness snapshots, exact per-owner protective-exit evidence and that there is **no** heartbeat order re-arm. A startup `READY` marker is not proof of broker access or exits. Keep failed gates blocked. Roll back by reverting repair commits while retaining backed-up accounting data.

If proof remains incomplete, do not turn on live entries or use a test order to manufacture readiness.
