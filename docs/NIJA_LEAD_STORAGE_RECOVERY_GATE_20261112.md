# NIJA P0 lead durability preflight and release hold — 2026-11-12

**Scope:** independently check *read-only* the Render website-lead intake and forwarding database locations, SQLite integrity, and minimum expected schema. This is a preflight, **not** a deployment or end-to-end lead-delivery certification.

## Source-verified mismatch requiring inspection

- NIJA's Render service `srv-d98dsr5aeets73fpbaqg` mounts a 1-GB persistent disk at `/data` (verified with the connected Render service descriptor on 2026-11-12). It also runs the trading bot. **Never restart, reconfigure, or share the trading volume solely to repair CRM** without independent safety review.
- Current `render_lead_intake.py::_db_path()` defaults the original `website_leads` database to `/app/data/nija_outreach.sqlite3` unless `NIJA_LEAD_DB_PATH` or `NIJA_OUTREACH_DB_PATH` is set.
- Current `render_lead_intake.py::_forward_db_path()` defaults the `website_lead_forwarding` / `website_lead_forward_aliases` database to `/data/nija_lead_forwarding.sqlite3` when `/data` is present (unless overridden).
- **The actual live environment-variable overrides and actual database files have not been inspected.** Therefore the original intake database's deployment persistence is **UNVERIFIED**, not established as lost or definitely ephemeral. A future release cannot assume its original records are already on the persistent disk.

## Safe inspection procedure (authorized read-only runtime only)

From the checkout containing this script, running in the **explicitly approved** runtime/container with read access to the lead stores:

```sh
python scripts/verify_nija_lead_storage_readonly.py \
  --expected-persistent-root /data
```

When operator evidence identifies the real files, specify exact absolute paths:

```sh
python scripts/verify_nija_lead_storage_readonly.py \
  --intake-db /VERIFIED/LEAD/INTAKE/FILE \
  --forward-db /VERIFIED/LEAD/FORWARD/FILE \
  --expected-persistent-root /data
```

Only aggregate counts, database paths and schema/integrity statuses appear in the JSON. `mode=ro&immutable=1` is used **only after rejecting WAL headers and WAL/SHM/rollback-journal sidecars**; missing files and SQLite sidecars are never created by this probe. Active WAL or changing databases require an independently approved online-consistent snapshot before inspection. An inaccessible or missing database yields `UNVERIFIED` and a nonzero exit code, **not zero records**. The tool intentionally never prints stored customer email, payload, consent, passwords, or webhook URLs. It refuses to inspect files named like the trading ledger.

The forwarding verification also requires `website_lead_forward_aliases` with `source_key`, `legacy_key` and `created_at`; absence is **UNVERIFIED**, never evidence that aliases do not exist elsewhere. A whitespace-only primary intake override is invalid and must not silently select the secondary path.

The result `local_placement_and_integrity=checked` means **local placement and checks only**, not that the Render disk or backup has been verified independently. `production_pipeline_certified` is always `false`. Independent backup/restore, IONOS runtime, private delivery rules, sender identity and provider acknowledgments remain external gates.

## Data-safe migration sequence — NOT performed here

1. Preserve dispatch `OFF` and historical `pending`, `uncertain`, and `sent` markers. Do not replay or reclassify any event.
2. Independently identify the production runtime, immutable deployed commit, actual configured lead database paths, file owners, WAL/journal mode, outstanding writes, storage volume and backup mechanism. Inventory the original intake and forwarding schemas, rows and unique event IDs without exposing customer data.
3. Obtain an **online-consistent SQLite snapshot**, using SQLite's supported backup mechanism or a deliberately stopped writer during an approved maintenance window. Preserve the original intake, forwarding and alias tables as separate evidence when they reside in different database files. Copy the encrypted artifact to independent restricted storage; verify hash, object retention and access controls. Never treat a simple directory copy or unverified working-folder archive as sufficient.
4. Independently restore to a disposable, isolated host. Validate SQLite integrity, all required tables, row counts, unique upstream event IDs, event/source timestamps, consent history, forwarding states and aliases, and matching source/restore hashes. Quarantine conflicts for review. Do not touch actual customer records or trading ledger.
5. Only after an approved, reversible cutover: configure a dedicated durable lead store or isolated storage root; restore and reconcile authoritative records; verify no duplicate dispatch claims. Do not silently switch `/app/data` to `/data` or start an empty store. Do not reuse existing billing, course, game, or trading databases as an unreviewed substitute.
6. Confirm the IONOS **published** build and receipt-create rules against the approved source, including the `completeReceiptPage` and untrusted reason-label protections. IONOS support says App & Site Builder does **not** provide restorable production data backups or loaded runtime details, while project-version rollback exists; version rollback alone is insufficient. An independently operated recoverable first-party lead-capture path may be required.
7. Verify exact *published* Zapier business-account `28290328` / Zap `378270777` hook ownership and ON status, single authorized sender, server-only credentials, provider idempotency and acknowledgments, Apollo exact-email insertion and Resend nonmarketing transactional receipts.
8. Obtain hosted security/CI and independent review on the exact release revision, then separate scoped approval for any production deployment or rule/config migration. Obtain separate approval for **one** new nonmarketing end-to-end form submission via `/free`, `/founding-waitlist` or `/apply` as appropriate, plus controlled retry/distinct-event tests. Verify source/original timestamp and event ID, actual LIVE readback, Apollo identity after allowing two hours, and no duplicates.

## Source-of-truth and counting

Continue overlapping 72-hour Gmail/Apollo/Resend read-only reconciliation. Count **unique real applicants** using normalized email + actual form + immutable upstream ID (or original timestamp when no ID); count notifications separately. Do not conflate identical emails from intentional distinct submissions. Exclude the known internal QA events, including `evt_74b942c9-c4a2-4656-88fa-573ac78e80c6`. The Oct 7–20 historical 15-applicant baseline is **closed for alerting**. Inaccessible provider evidence or no notification matches means `UNVERIFIED`, not `zero website leads`.

**Release verdict:** P0 OPEN / production dispatch OFF; no live input, production write, migration, contact update, payment, order or trade is authorized by this document.