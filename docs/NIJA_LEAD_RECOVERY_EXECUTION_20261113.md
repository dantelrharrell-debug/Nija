# Production lead recovery execution and rollback runbook

Status: PARTIALLY COMPLETE; production recovery and delivery remain BLOCKED.
This is a review-only source change. It authorizes no production release.

## Verified evidence and access limits

- PR #3831 merged as `fc81548e871b4f772eb673faecd62ec7fc7511bc`.
- Render connector: service `srv-d98dsr5aeets73fpbaqg`, workspace
  `tea-d37fhe8gjchc73c8eo0g`, Docker, one instance, disk
  `dsk-db4kk21srm7s7382vadg`, 1 GB at `/data`, auto-deploy off.
- Last inspected live deployment: `dep-dbqth6jbc2fs73fcd2vg`, commit
  `632405228ff2dabb053eecf7dacc35db9325a454`, live since
  2026-11-12T15:20:30.404663Z. This is not the merged main preflight.
- Connector exposes neither effective environment values nor filesystem contents.
  Browser reached Render login; secure sign-in request timed out without verified
  success. Opera connector was unavailable. SSH with isolated client configuration
  failed DNS resolution for the connector-provided `ssh.oregon.render.com`.
  No key was created, registered, disclosed or requested in chat.
- Actual production lead paths, historical records, consent history, protected
  backup, checksum, snapshot timestamp and isolated restoration: UNVERIFIED.
  No production database was opened. No missing file was interpreted as zero.
- IONOS published-source parity and Zapier published hook ownership remain
  unverified. Public retrieval of `/free`, `/founding-waitlist`, `/apply` failed;
  this does not prove the forms are broken or absent. Available browser profiles
  do not record an authenticated Render/IONOS/Zapier session for those domains.

## Safe next inspection

1. Restore authenticated access to the existing running service. Confirm service,
   deployment, instance and revision before commands. Do not deploy this PR to
   obtain a diagnostic. Do not import application startup code.
2. Review `scripts/nija_lead_metadata_inventory.py`, then execute its exact reviewed
   source via `python -B -S -` in the existing Shell/SSH session, or use the file
   only if independently verified present at that runtime revision. This tool
   uses stat/lstat and bounded, nonrecursive directory enumeration only. It never
   opens file contents, SQLite, application code or network connections.
3. Privately retain the three lead path overrides, explicit candidates, metadata,
   sidecar metadata, timestamp, actual mount and runtime identity. The inventory
   is deliberately incomplete: inspect additional owner-identified lead-only
   directories without recursively inventorying trading data. Do not select an
   authoritative source until every candidate and workflow owner is reconciled.
4. Do not run a SQLite diagnostic on the live file as a substitute for recovery.
   WAL/SHM/journal presence requires an established consistent snapshot procedure.
   Never delete, truncate, checkpoint, rename or move sidecars to make a probe pass.

## Lead-only consistent backup procedure: gated, not executed

Prerequisites: actual paths and writer ownership; all candidate inventory; an
existing approved encrypted destination with restricted access; validated capture
method that cannot modify live files, sidecars or the trading environment.

- Prefer an existing application-owned consistent backup interface if its exact
  implementation, authorization and read/write behavior have been reviewed.
- A standard read-only SQLite connection is NOT automatically acceptable: it can
  create live SHM state. Immutable mode is NOT a safe online WAL snapshot. A plain
  copy of an active DB and sidecars is NOT a certified consistent backup.
- If no existing safe method satisfies the source-preservation boundary, prepare
  a lead-writer-only quiescence/snapshot plan and request explicit production
  approval. Never stop/restart the shared trading process as an implied CRM step.
- Capture every relevant lead database at a coordinated boundary. Preserve all
  tables/indexes/triggers/metadata, original submissions, IDs, timestamps, consent
  evidence, aliases, attempts, provider acknowledgments and delivery states.
  Record the consistency boundary between separate intake and forwarding stores.
- Encrypt copies before off-host transfer using existing approved facilities;
  restrictive file/directory permissions (0600/0700), least-privilege access,
  encryption in transit, no public links and no PII in chat/GitHub/logs.
- Record SHA-256 of each completed consistent snapshot and encrypted artifact,
  capture UTC time, source revision/instance, schema versions, encryption method,
  object version and retention/access-control verification. Hashes of an active
  changing database are not consistency proof. Do not expose row-level hashes.

## Independent isolated restore and reconciliation

1. Use a separate disposable host with no production credentials, outbound sends
   disabled and no trading data or runtime. Download only lead backup artifacts.
2. Verify encrypted artifact checksum, decrypt with existing secure credentials,
   verify snapshot checksums, restore into a new restricted directory. Do not
   point any production application at it.
3. On isolated copies run full `PRAGMA integrity_check`, foreign-key checks where
   applicable, inventory all schemas/indexes/triggers and compare against the
   protected consistent source snapshot, not the concurrently changing live DB.
4. Compare complete logical table contents privately using deterministic typed
   serialization and an order-independent multiset comparison. Include duplicate
   multiplicity, NULL/blob values, all identifiers, timestamps, consent payloads,
   aliases and historical delivery/ack states. Record aggregate pass/fail only.
5. Compare source-to-backup capture evidence and high-water marks to ensure no
   missing interval between intake and forwarding captures. Preserve unresolved
   pending/uncertain states; never mark an uncertain send successful by inference.
6. Exercise isolated restart/deployment with those restored fixtures, no network
   sends; prove IDs and consent persist and repeat events do not add dispatch.
   Distinct legitimate events sharing an email remain distinct.
7. Record actual UTC times, object versions, checksums, aggregate counts and
   comparison results. Only then certify that specific backup as restorable.
   None of these production restore steps has been completed in this session.

## Proposed retention and failure detection: requires review

Use an existing approved off-host encrypted store, with immutability/versioning
and independently retained decryption access. Proposed policy: daily captures,
30 daily and 12 weekly retained copies; daily verification of job success, age,
checksums and object accessibility; periodic isolated restore. This is a proposal,
not an installed schedule, purchased service or verified retention policy.

Missing/late backup, failed checksum/decryption, changed schema, incomplete
consent/alias comparison or failed restore must keep recovery uncertified and
raise an operator incident through an approved existing channel. No new alert
recipients or external messages are configured by this PR.

## Storage cutover and rollback: separate approval required

Do not change a path or initialize a replacement database now. Once historical
records and independent restoration are certified, prepare an exact lead-only
migration with original path/new path, final source high-water mark, reviewed
commit/image, writer coordination and abort criteria. Keep lead state logically
separate from trading state. Require passing exact-release security/CI and owner
approval before cutover, env changes, restart or deployment.

Rollback must preserve both old and new lead snapshots and every event admitted
after cutover. Do not simply revert the environment to a stale old database:
quiesce the lead writer under a separately approved procedure, reconcile new
admissions and delivery claims privately, verify IDs/consent/aliases/outcomes,
then approve the precise return path. Never replay historical notifications or
reset sent/uncertain claims. Never restore a whole shared trading disk.

Current source-only PR rollback: close the unmerged PR. No production rollback
is needed because no production state was changed in this session.

## Release security evidence and disposition

PR #3831 head `de31cb682f48a01c776ef6080b96eb010330fa9b`:

- [CRM recovery](https://github.com/dantelrharrell-debug/Nija/actions/runs/43301353301):
  success; 18 storage tests and 99 CRM regressions in recorded hosted evidence.
- [CI](https://github.com/dantelrharrell-debug/Nija/actions/runs/43301353439) and
  [CodeQL](https://github.com/dantelrharrell-debug/Nija/actions/runs/43301353644): success.
- [Security](https://github.com/dantelrharrell-debug/Nija/actions/runs/43301353484): failure.
  Pre-commit job `131473072989`: failed hooks bandit, check-docstring-first,
  detect-private-key, detect-secrets, end-of-file-fixer, gitleaks,
  name-tests-test, trailing-whitespace; categories hook_modified_files and
  source_diff_emitted. Sanitized report lacks the per-file hook diffs; no defect
  is considered repaired from that summary alone.
- Secret job `131473073889`: 154 unbaselined candidates; detector counts 106
  Secret Keyword, 24 Private Key, 15 Basic Auth, 7 Base64 entropy, 2 Hex entropy.
  Gitleaks and TruffleHog PR diff scans succeeded. Retained value-free artifact
  [13982201709](https://github.com/dantelrharrell-debug/Nija/actions/runs/43301353484/artifacts/13982201709)
  identifies tested integration commit `97c35a7cfb2ba703a317c84327367b83931848df`;
  it must not be mislabeled as a direct head checkout.
- Comparing base `757eab4e22430fd7cdedc83742922ac666802b92` to the PR head shows
  all 154 candidates are in byte-identical unchanged files; zero candidates are
  in the three PR files. This establishes preexistence relative to this repair,
  NOT false-positive status or a waiver. All remain unresolved and blocking.
  Existing baseline reviewed findings are separate from these unbaselined items.
  No baseline entry, scanner, ignore rule or protection was changed here.
- [Artifact scanning](https://github.com/dantelrharrell-debug/Nija/actions/runs/43301353826):
  failure in all four container scan jobs and three GuardDog jobs. pip-audit,
  license and artifact-integrity jobs passed. Genuine-vulnerability versus
  heuristic disposition remains unresolved; no malware conclusion is inferred.

## Delivery QA release hold

For each of `/free`, `/founding-waitlist`, `/apply`, authenticate the IONOS
published handler/store owner and approved bundle hash; verify original event ID,
submission timestamp and consent; privately compare the published Zapier hook in
business 28290328, Zap 378270777, with server configuration; identify one sender
per purpose. Trace durable storage, claim, provider ack, Apollo and reconciliation.
Source fixtures and an ON Zap do not establish that published chain.

Keep historical events unreplayed and marketing/SMS/AI calls off. Require
separate owner authorization for an exact new live nonmarketing QA matrix after
storage, recovery and security gates pass. Storage certification never grants
marketing-dispatch authorization. Trading controls and allow_new_orders remain
unchanged; this work does not authorize trading.
