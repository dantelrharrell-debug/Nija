# NIJA production recovery: current backup and isolated restore, without restart

**Operator-only, fail-closed recovery runbook (2026-10-21).**

This runbook does **not** authorize live trading or let a health check, successful
SQLite backup, historical archive, or runtime "HOLD" label grant order admission.
The current recovery must begin by preserving the **running** Render instance;
do **not** deploy, restart, migrate data, change trading flags, clear emergency
stops, place test orders, or manufacture execution proof.

## Evidence and change boundary

- Render service: `srv-d98dsr5aeets73fpbaqg` in workspace
  `tea-d37fhe8gjchc73c8eo0g`, dedicated 1 GiB disk mounted at `/data`.
- At 2026-10-21 22:13 UTC, a deployment of commit `135759b7` became live,
  after the previously observed `89b38c1` build. It was a JustCall/Apollo
  change, **not** recovery certification. Future restarts are **not** permitted
  merely to make a recovery status green.
- The deployed source at `135759b7` includes all three read-only scripts
  listed below; the Dockerfile checks their presence at image build time.
  **Verify file presence on the actual running instance anyway.** If missing,
  stop; use a separately reviewed, content-hash-pinned secure operator handoff.
  Do not deploy merely to copy a script into the container.
- Runtime observations: SQLite integrity `ok` but 13 pending Kraken closes,
  no trade/position rows; `TRADE_LEDGER_V435_STORAGE_EVIDENCE` reported
  `backup_restore_verified=false`, `restart_persistence_verified=false`.
  Execution producer missing, freshness invalid and live authority withheld.
- The October 11 off-host archive passed historical integrity checks. **It
  does not certify or replace the October 21 live ledger and JSON state.**

## October 27 v4 verifier correction: independently pinned source deployment

The off-host verifier formerly compared the captured source deployment to one
hard-coded old release commit. That rejected newer legitimate captures even when
their source checksums, verifier blob pins and transfer seals were intact.

On an **independent off-host machine**, after the existing live-instance capture,
encrypted transfer and separately retained original source seal, verify which
Render deployment SHA was active **at the capture UTC time** using an
independent Render deployment record. Obtain this SHA independently of
`CAPTURE_CONTEXT.json`, its manifest and the copied archive. Do not copy it
out of the capture as the trusted argument. Run:

~~~bash
bash ops/recovery/nija_offhost_backup_verify_v4.sh \
  "/restricted/offhost/PRIVATE_CAPTURE_DIR" \
  "INDEPENDENT_SOURCE_CAPTURE_SEAL_SHA256" \
  "INDEPENDENTLY_CONFIRMED_RENDER_DEPLOY_COMMIT_40_HEX"
~~~

The third argument is mandatory. The verifier requires the captured commit
to match that independent pin and still enforces source-seal checks,
per-file hashes, pinned script blobs, private directories and isolated
SQLite/account/legacy restore validation. A verified SHA is **not**
independent proof of transfer custody, broker reconciliation, ledger
completeness, protective exits or authority to trade.

The companion regression test
`tests/test_nija_offhost_backup_verify_deployment_pin.py` uses only synthetic
invalid archives to prove matching-deployment validation can proceed to the
real restore checks, mismatched deployments stop, and missing/invalid
independent SHA arguments are denied. It cannot certify a production backup.

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
or finds unknown files/collisions. A symlinked `/app/data` parent can be valid
only when its verified resolved paths remain inside the mounted `/data`.
Never move or overwrite the existing state to force the audit to pass.

Then capture both **separate** archive types. The new local directory is
private and intentionally outside the production disk. These scripts do not
place broker orders or mutate the live ledger; `v436` uses SQLite's online
backup API to capture a transactionally consistent SQLite snapshot including
WAL content; `v449` independently checks account JSON read stability.

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

### Optional bounded legacy-state archive (future verified deployment only)

When the **actual running instance** already has
`scripts/nija_legacy_global_state_evidence_v462.py` available and independently
reviewed, it can supplement the explicit legacy-file preservation procedure
below. **Do not restart or redeploy just to install this utility.** It is
not present on older production images.

After the v436 and v449 steps, with the same private `"$out"` directory,
a qualified operator may run:

~~~bash
test -s /app/scripts/nija_legacy_global_state_evidence_v462.py
python -S /app/scripts/nija_legacy_global_state_evidence_v462.py snapshot \
  --persistent-root /data --output-dir "$out"
~~~

The command captures only existing default candidate legacy global files.
If a non-default source was verified by the original tracker/store's owner,
pass an explicit bounded `--source LABEL=/absolute/path` for that source;
labels are not account identities. The utility rejects absence of all
candidates and deliberately marks `legacy_path_inventory_complete=false`,
`off_host_custody_verified=false`, and `trading_authorized=false`.

Transfer the archive through an approved encrypted channel and verify the
unchanged source hash against the off-host copy:

~~~bash
python -S scripts/nija_legacy_global_state_evidence_v462.py verify \
  --archive /restricted/offhost/nija-legacy-state-CAPTURE.zip \
  --expected-sha256 ORIGINAL_RECORDED_SHA256
~~~

The v462 verifier inspects pinned archive bytes without extraction or
mutation; a successful verification alone is not an isolated full-state
restoration. It does not prove source account identity, reconciliation,
ledger/JSON atomicity, or broker protection. Continue the no-restart HOLD.
On the **current deployed image**, follow the existing owner-shell procedure
below without triggering another deployment.

### Preserve unscoped legacy tracker evidence separately

The deployed diagnostics also report `legacy_global_file=true` with
`entry_on_persistent_root=false` for a tracker. Neither a scoped JSON
backup nor a SQLite archive captures every possible older global state
file. **Do not delete, migrate, overwrite or assume these files are
disposable.** The status is a diagnostic signal, not proof of a known
source location.

After the v436 and v449 snapshots, inventory and copy only existing
legacy global files from the original running instance into the same
private temporary directory. The known default candidates are
`/app/data/positions.json`, `/app/data/entry_prices.json`, and
`/app/positions.json`; inspect the trusted live configuration and
actual tracker/store paths for any additional non-default files.
Run this from the *same authorized owner shell*. It deliberately
refuses leaf symlinks, unstable files, special files, oversized source
files, shared output directories and overwrites:

~~~bash
NIJA_RECOVERY_OUT="$out" python -S - <<'PY'
import hashlib
import os
import stat
from pathlib import Path

root = Path("/data").resolve(strict=True)
output = Path(os.environ["NIJA_RECOVERY_OUT"])
if output.is_symlink():
    raise SystemExit("FAIL CLOSED: output symlink")
output = output.resolve(strict=True)
if (not output.is_dir() or output == root or root in output.parents
        or stat.S_IMODE(output.stat().st_mode) & 0o077):
    raise SystemExit("FAIL CLOSED: output must be private and off the live disk")

sources = {
    "data-positions.json": Path("/app/data/positions.json"),
    "data-entry_prices.json": Path("/app/data/entry_prices.json"),
    "app-positions.json": Path("/app/positions.json"),
}
limit = 4 * 1024 * 1024
flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
copied = 0

for label, source in sources.items():
    try:
        initial = source.lstat()
    except FileNotFoundError:
        print(label + ": not present at default path")
        continue
    if not stat.S_ISREG(initial.st_mode):
        raise SystemExit("FAIL CLOSED: unexpected legacy source type " + label)
    fd = os.open(source, flags)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise SystemExit("FAIL CLOSED: unsafe legacy file " + label)
        content = stream.read(limit + 1)
        stream.seek(0)
        second = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    current = source.lstat()
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
    if (len(content) > limit or len(content) != before.st_size
            or content != second or identity(initial) != identity(before)
            or identity(before) != identity(after)
            or identity(after) != identity(current)):
        raise SystemExit("FAIL CLOSED: unstable legacy file " + label)
    destination = output / ("legacy-" + label)
    dstfd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                    | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(dstfd, "wb") as saved:
        saved.write(content)
        saved.flush()
        os.fsync(saved.fileno())
    digest = hashlib.sha256(content).hexdigest()
    if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
        raise SystemExit("FAIL CLOSED: local copy hash mismatch " + label)
    actual = source.resolve(strict=True)
    in_mount = actual == root or root in actual.parents
    print(f"{label}: sha256={digest} bytes={len(content)} "
          f"on_persistent_disk={in_mount} account_provenance_verified=false")
    copied += 1

print(f"legacy_files_copied={copied} off_host_restore_verified=false "
      "trading_authorized=false")
PY
~~~

Securely transfer any `legacy-*.json` artifacts **alongside** the v436
and v449 backups. Recompute and compare their source SHA-256 on the
independent off-host system; retain the operator custody receipt.
A missing default file does not establish that a non-default file is
absent. Resolve any such paths with the trusted live runtime owner
before declaring backup coverage complete.

Do not restore legacy files into an account-scoped live store, infer
account ownership from filename alone, synthesize historical cost
basis, or authorize trades from checksum or archived CSV matches.

**Do not delete the private archives or restart after this step.** Inspect
the `v436` manifest for missing or unstable companion evidence. A successful
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

A passing `v436` restore performs an isolated SQLite restoration plus
`PRAGMA integrity_check` and count verification. A passing `v449` check
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