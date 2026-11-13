# NIJA lead-only protected backup and isolated restore

Status: PARTIALLY COMPLETE. A consistent encrypted point-in-time backup and
isolated restore succeeded, including retrieval of all recovery inputs from Drive. Ongoing retention,
required release security gates, published routing and approved live delivery QA
remain uncertified. Do not enable dispatch, marketing or trading from this report.

## Production observations

On November 12, 2026 (PST), authenticated Shell verified `/app/data -> /data`,
with `/data` an actual mount. The intake is `/data/nija_outreach.sqlite3`
(192512 bytes); forwarding is `/data/nija_lead_forwarding.sqlite3` (20480 bytes).
Both files were regular, owned by uid/gid 1000/1000, permissions 0600. No lead path
overrides were present in the inspected Shell environment. No WAL/SHM/journal
sidecars were observed, and header read/write versions were 1 (rollback mode).

An unrelated manual deployment changed the running instance during preparation.
The verifier stopped input, then rechecked service identity, mount, symlink,
paths, permissions and sidecars before capture. Current observed deployment:
`dep-dbr5p18u01pc73a8ui20`, commit
`ca2a55a492abfc4be644469bd0ac92782df9aa4f`, instance
`srv-d98dsr5aeets73fpbaqg-cd99f7655-qqmdr`. The verifier did not deploy or restart.
Both files remained present after that deployment; byte counts alone do not
prove preservation of every historical record across that separate deployment.

## Capture controls and evidence

Capture time: **2026-11-13T00:52:18.775895Z** (November 12, 4:52:18 PM PST).

The capture subprocess loaded a libseccomp kernel filter before SQLite source
connections. Writable/creating/truncating file opens, filesystem mutations,
network and process execution were denied. A negative control confirmed file
creation was denied before any SQLite source connection. No protections in the
running application were weakened. No production packages were installed.

Sources used SQLite `mode=ro`, not immutable live reads. Sidecars, WAL headers,
missing files, symlink inputs and unreviewed tables fail closed. Read transactions
for both rollback-mode stores remain open through capture, providing a shared
stable interval. SQLite's supported Online Backup API copies each source into
memory; integrity and full typed-row/schema comparisons precede export.

The two initially unreviewed table names were independently traced to
`render_apollo_feeder.py`: `outreach_apollo_field_mappings` and
`outreach_apollo_sync_state`. Only those exact names were added. This is a data
scope check, not a secret-scan exemption. No trading tables are permitted.

Public source references:
- https://www.sqlite.org/backup.html
- https://man7.org/linux/man-pages/man3/seccomp_rule_add.3.html

The original diagnostic source SHA-256 was
`6e355493fad576c629d40db4a264556763a01a26af8d213ebf154be9fbdb5723`.
The successful capture used that pinned source with only the two reviewed Apollo
table names added. The committed reusable tool includes those names and clearer
fixed failure categories. It was not deployed into the application startup path.

Only encrypted copies and the public recipient certificate were written under
`/tmp/nija-lead-backup-dtzsv9k7/`, with directory 0700 and encrypted file 0600.
Plaintext snapshots/archive existed only in memory. AES-256-GCM CMS encryption
completed before ciphertext transfer. The private key never entered Render.
No customer values or row-level content fingerprints were printed or posted.

## Off-host custody and hashes

Existing [NIJA Production Recovery Backups - Private](https://drive.google.com/drive/folders/135QqjI6mVfmnCxvOBfsFsZ6ZjPdt60Ki)
was discovered and verified as not shared, with one owner permission. Folder
contents were inspected before use. No new permissions were granted.

[Encrypted backup](https://drive.google.com/file/d/1aQE_2x89tyFkg2372ngepjeVmrMSakka/view?usp=drivesdk):
`NIJA_Leads_20261113T005218Z.p7m`, 21189 bytes, uploaded
2026-11-13T00:56:32.797Z. File readback confirms the intended parent and owner-only
permissions. It was independently downloaded through Drive after upload.

| Object | SHA-256 |
|---|---|
| Encrypted archive, source/export/redownload | `c8d03661c272ecce4ed86f62f8cb1d761cd245592e0e2c14d4d25646441ba79d` |
| Intake SQLite snapshot | `524ee06ffaf55c19497387d1e2db50e4437227068db95ef68e728481b47c955e` |
| Forwarding SQLite snapshot | `83f91b71df3856c9f3d648bf21eb2b48c8916737ebd137db7ed74aaf480bf57a` |

The public recipient certificate is stored with the ciphertext. It cannot decrypt
the backup. The initial private-key upload was rejected because destination and
custody approval were not explicit; no alternate route was attempted. The owner
subsequently approved the exact separate private destination. On
**2026-11-13T01:17:02.885Z**, the key was saved as
`NIJA_Lead_Recovery_Key_20261113.pem` in the separate existing **NIJA Production
Backups** folder linked below. Folder and uploaded file metadata independently
confirmed not shared, sole-owner permissions and the intended parent. No
permission was added or changed. Private-key contents never entered Render,
GitHub, chat output or logs.

At **2026-11-13T01:17:47.499465Z**, all three recovery inputs (key, certificate,
encrypted backup) were freshly retrieved from Drive into a restricted directory
on the isolated host. Retrieved key bytes matched the original without exposing
the key or its fingerprint. Authenticated decryption, both snapshot checksums,
SQLite integrity/foreign-key checks and full typed-record/schema reconciliation
passed again. This clears the durable-key-custody blocker for this specific
point-in-time backup. Ongoing retention and production delivery remain separate.

## Independent restoration results

Restore verified at **2026-11-13T00:57:34.838559Z**, using the independently
redownloaded encrypted Drive artifact on a separate host. No Render disk restore
or production database replacement was used. Authenticated decryption occurred
in memory, as did both restored SQLite databases. No plaintext files were written.

- Encrypted and both snapshot SHA-256 values matched.
- Full SQLite integrity checks passed for both snapshots.
- Foreign-key checks returned no violations.
- Every schema object (including indexes/triggers) and every typed table value,
  NULL/blob value and duplicate multiplicity matched the capture manifest.
- The capture had separately matched that manifest to protected source read
  transactions. Thus identifiers, original timestamps, stored consent/payload
  fields, aliases, cursors and delivery states were preserved as stored.
- This proves preservation of existing stored consent evidence, not that missing
  consent can be invented or that any contact is eligible for outreach.

| Table | Restored rows |
|---|---:|
| website_leads | 87 |
| website_lead_crm_sync | 87 |
| website_lead_forwarding | 12 |
| website_lead_forward_aliases | 0 |
| outreach_apollo_field_mappings | 2 |
| outreach_apollo_sync_state | 1 |
| justcall_webhook_events | 2 |
| outreach_calls | 2 |
| outreach_suppressions | 0 |
| outreach_autodial_queue | 0 |
| outreach_autodial_daily_quota | 0 |
| sqlite_sequence | 1 |

87 records is not a certified count of unique real applicants; known QA events
must remain excluded from applicant totals. No historical record was replayed,
relabelled, re-associated or marked delivered by this work.

## Additional isolated reconciliation

All 87 stored event keys are unique; intake/CRM joins have zero missing rows in
both directions. All 87 payloads parse as JSON and contain a recognized source
timestamp field. None contains a recognized upstream submission-ID field. The
existing database identifiers were preserved; immutable upstream ownership is
not certified by those identifiers alone.

Recognized explicit consent-field presence in saved payloads: email 0, SMS 1,
AI voice 0. Presence alone is not affirmative or legally sufficient consent;
no field or history was synthesized. Missing explicit evidence keeps outreach
uncertified. The 12 forwarding records are all pending, with zero sending/sent/
uncertain records. CRM contains 86 synced states and one other state; a local
synced label is not independent provider acknowledgment evidence. This analysis
ran only against the off-host restored snapshots and changed no records.

## Reusable isolated verification

On an isolated host with the approved recovery key and public certificate,
without production credentials or outbound providers:

```sh
python -B -S scripts/nija_lead_isolated_restore_verify.py \
  --encrypted /PRIVATE/ENCRYPTED_BACKUP.p7m \
  --key /PRIVATE/APPROVED_RECOVERY_KEY.pem \
  --certificate /PRIVATE/PUBLIC_RECIPIENT_CERTIFICATE.pem \
  --expected-sha256 c8d03661c272ecce4ed86f62f8cb1d761cd245592e0e2c14d4d25646441ba79d
```

Never run a restore against a production path. The verifier decrypts/restores in
memory and emits aggregate evidence only. A checksum mismatch, GCM authentication
failure, unexpected archive entry, bad integrity, unreviewed table or content
mismatch returns failure. Keep the original encrypted copy unchanged on failure.

## Remaining decisions and operating limits

1. Completed: owner approved durable key custody in the separate existing private
   [NIJA Production Backups](https://drive.google.com/drive/folders/1vFAsMURwf036cI7t41DyEU4zXHywdbfq)
   folder; exact filename `NIJA_Lead_Recovery_Key_20261113.pem`. Independent
   retrieval and repeated restoration succeeded as documented above. Keep key
   access restricted; never paste it into chat or GitHub.
2. Proposed retention remains 30 daily/12 weekly encrypted copies with age,
   checksum, decryptability and periodic restore checks. No recurring production
   job, alert recipient, immutability policy or paid service was created. A folder
   and one verified backup do not establish an operational recurring policy.
3. Verify required security gates, published IONOS source/store ownership and
   published Zapier hook parity, sender ownership, Apollo/provider acknowledgments.
   Obtain separate authorization for exact production changes and new live QA.
4. Do not change DB paths: current source placement already reaches the persistent
   disk. No source migration or whole trading-disk rollback is justified here.

## Rollback

The sources were not modified by capture. No application rollback is required.
Keep the encrypted off-host file, public certificate and private key protected.
Do not delete originals or replay historical notifications. Closing this review PR
rolls back only the proposed reusable tooling; it does not erase the existing
backup or alter production. Any future lead-only production restore requires an
approved quiescence, reconciliation of post-capture admissions/claims and exact
cutover plan. Never restore the shared trading disk for CRM recovery testing.

## Hosted release checks and confirmed security repair

PR #3847 head a4375994a5bc4aa99bc5005cbe711677049a83b4 passed 9/9 direct-head
capture/restore tests (run43342249475), general CI43342249670 and
CodeQL43342249923. Security43342249416 and Artifact43342249397 failed.
Secret report14000106797 identifies152unbaselined candidates in86files, zero
in the six backup PR files; integration checkout
a1455b988c76e3c71adbdd52c5862bb405da99c1. Counts110Secret Keyword,
24Private Key,9Basic Auth,7Base64,2Hex. Preexistence is not dismissal; none was
approved, baselined or suppressed. Eight precommit hooks remain failed.

Separate review PR #3848 head a2e4236f6afdb5afee2b1e81afe6030384eaefc4
repairs the two identified Soup Sieve advisories. Direct-head parser tests3/3
(run43342755115), full resolved dependency audit131614769398, general
CI43342754519 and CodeQL43342754647 passed. Its precommit/secret checks still
failed. No merge/deployment occurred. Preserve the safety hold.
