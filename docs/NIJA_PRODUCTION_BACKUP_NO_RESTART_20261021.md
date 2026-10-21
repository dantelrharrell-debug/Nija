# NIJA production recovery: current backup and isolated restore, without restart

**Operator-only, fail-closed recovery runbook (2026-10-21).**

This runbook does **not** authorize live trading or let a health check, successful
SQLite backup, historical archive, or runtime "HOLD" label grant order admission.
The current recovery must begin by preserving the **running** Render instance;
do **not** deploy, restart, migrate data, change trading flags, clear emergency
stops, place test orders, or manufacture execution proof.

## Evidence and change boundary

- Render service: \`srv-d98dsr5aeets73fpbaqg\` in workspace
  \`tea-d37fhe8gjchc73c8eo0g\`, dedicated 1 GiB disk mounted at \`/data\`.
- At 2026-10-21 22:13 UTC, a deployment of commit \`135759b7\` became live,
  after the previously observed \`89b38c1\` build. It was a JustCall/Apollo
  change, **not** recovery certification. Future restarts are **not** permitted
  merely to make a recovery status green.
- The deployed source at \`135759b7\` includes all three read-only scripts
  listed below; the Dockerfile checks their presence at image build time.
  **Verify file presence on the actual running instance anyway.** If missing,
  stop; use a separately reviewed, content-hash-pinned secure operator handoff.
  Do not deploy merely to copy a script into the container.
- Runtime observations: SQLite integrity \`ok\` but 13 pending Kraken closes,
  no trade/position rows; \`TRADE_LEDGER_V435_STORAGE_EVIDENCE\` reported
  \`backup_restore_verified=false\`, \`restart_persistence_verified=false\`.
  Execution producer missing, freshness invalid and live authority withheld.
- The October 11 off-host archive passed historical integrity checks. **It
  does not certify or replace the October 21 live ledger and JSON state.**

## A. Capture from the existing, live Render owner shell

Only execute these commands in the **existing instance** using the operator's
authorized Render shell/SSH access. The Render API connector supports logs and
deployment metadata, not live file access or command execution.

First inspect paths, executable script presence and current mount identity.
Record the output privately without exposing account contents or credentials:

~~~bash
set -euo pipefail
umask 077
cd /app

test -s scripts/nija_state_store_persistence_audit_v441.py
test -s scripts/nija_trade_ledger_snapshot_v436.py
test -s scripts/nija_account_state_offhost_evidence_v449.py
test -f /data/trade_ledger.db
test -d /app/data/positions
test -d /app/data/entry_prices

python -S - <<'PY'
from pathlib import Path

root = Path("/data").resolve(strict=True)
for label, raw in (
    ("ledger", "/data/trade_ledger.db"),
    ("positions", "/app/data/positions"),
    ("entry_prices", "/app/data/entry_prices"),
):
    resolved = Path(raw).resolve(strict=True)
    if not (resolved == root or root in resolved.parents):
        raise SystemExit(f"FAIL CLOSED: {label} is outside /data")
    print(f"{label}: resolved on persistent root: {resolved}")
PY

python -S scripts/nija_state_store_persistence_audit_v441.py \
  --persistent-root /data \
  --ledger /data/trade_ledger.db \
  --positions-dir /app/data/positions \
  --entry-prices-dir /app/data/entry_prices

sha256sum scripts/nija_state_store_persistence_audit_v441.py \
  scripts/nija_trade_ledger_snapshot_v436.py \
  scripts/nija_account_state_offhost_evidence_v449.py
~~~

Do not proceed if the audit returns nonzero, resolves a scoped store outside
the actual dedicated disk, finds an unverified ledger or unstable JSON state,
or finds unknown files/collisions. A symlinked \`/app/data\` parent can be valid
only when its verified resolved paths remain inside the mounted \`/data\`.
Never move or overwrite the existing state to force the audit to pass.

Then capture both **separate** archive types. The new local directory is
private and intentionally outside the production disk. These scripts do not
place broker orders or mutate the live ledger; \`v436\` uses SQLite's online
backup API to capture a transactionally consistent SQLite snapshot including
WAL content; \`v449\` independently checks account JSON read stability.

~~~bash
out="$(mktemp -d /tmp/nija-current-recovery-XXXXXXXX)"
test -d "$out"
test "$(stat -c %a "$out")" = "700"

python -S scripts/nija_trade_ledger_snapshot_v436.py backup \
  --source /data/trade_ledger.db \
  --output-dir "$out"

python -S scripts/nija_account_state_offhost_evidence_v449.py snapshot \
  --persistent-root /data \
  --positions-dir /app/data/positions \
  --entry-prices-dir /app/data/entry_prices \
  --output-dir "$out"

sha256sum "$out"/nija-trading-ledger-*.tar.gz \
  "$out"/nija-account-state-*.zip
~~~

**Do not delete the private archives or restart after this step.** Inspect
the \`v436\` manifest for missing or unstable companion evidence. A successful
local archive is still **not** a verified off-host backup; the two stores are
**not** cross-store atomic; no user balances, cost basis, exit coverage or
trading permission is certified.

## B. Preserve off-host and verify a disposable restore

Using an independently approved encrypted transfer method (e.g. SFTP/SCP)
copy the exact two private archives to a restricted, **independent** storage
system. Limit access to operators authorized to see account holdings; never
publish archives as GitHub attachments, Actions artifacts, normal issue
comments, general chat messages, or public website files.

Preserve the **original source-reported SHA-256 values**, source script
hashes, capture UTC time, source instance/deploy identity, independent
destination object IDs, copy completion time and reviewer identity in a
restricted recovery receipt. Verify both digests independently after copy.

On a **disposable, off-host** machine, with reviewed copies of the v436/v449
scripts, run (replace placeholder paths and digests with the actual copies):

~~~bash
python -S scripts/nija_trade_ledger_snapshot_v436.py restore-test \
  --archive /restricted/offhost/ledger-copy.tar.gz \
  --expected-sha256 ORIGINAL_LEDGER_SHA256

python -S scripts/nija_account_state_offhost_evidence_v449.py verify \
  --archive /restricted/offhost/account-state-copy.zip \
  --expected-sha256 ORIGINAL_ACCOUNT_SHA256
~~~

A passing \`v436\` restore performs an isolated SQLite restoration plus
\`PRAGMA integrity_check\` and count verification. A passing \`v449\` check
validates JSON account inventory and member hashes. **Neither command
attests independent custody by itself**: the operator must retain separate
verified transfer and access-control evidence.

## C. Hold criteria and remaining production repairs

Continue holding trading permission, regardless of whether an operator UI
labels this state "HOLD" rather than "BLOCKED", until separate reviewers have:

1. Confirmed a **current**, original-source-hash-matched off-host copy and
   isolated restoration of both archive types, with no missing/unstable
   companions and known capture window; investigated any unverified
   cross-store snapshot timing.
2. Independently reconciled 13 pending Kraken closes and fees with genuine
   authenticated account/order/fill history, preserving BABY-USD quantity and
   the unresolved entry basis instead of fabricating P&L.
3. Verified authoritative account ownership, broker balances and eligible
   capital publication for all registered brokers; reconciled all current
   positions and open protective orders on the correct broker/account side.
4. Verified writer/nonce ownership, duplicate-order fencing, operator
   authorization and an independently reviewed account-scoped pre-trade
   attestation **actually integrated into live admission**. Do not make a
   stale 1,800-second post-trade verifier fresh by altering timestamps, and
   do not use historical proof as startup authorization.
5. Reviewed and approved the production change, then, only in a separately
   authorized maintenance window, tested restart durability and production
   admission with all gates still fail-closed on missing proof.

**Safe terminal state today:** no new deployment, no restart, no test trade,
no execution authority change. This document and its checks are an operator
runbook, not a production recovery certificate.