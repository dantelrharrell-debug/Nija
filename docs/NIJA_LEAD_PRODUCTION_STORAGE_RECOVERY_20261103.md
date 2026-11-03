# NIJA lead persistence and forwarding recovery — production gate

Status: **diagnostics prepared, live data not yet certified.**

## Safety boundary
- Target Render workspace: Nija_Trading_Bot; service: srv-d98dsr5aeets73fpbaqg.
- The production bot auto-deploys from release/justcall-handoff-only-20261017. **Do not merge or trigger a redeploy merely to discover database paths.**
- Runtime disk mount: /data. Lead code currently defaults to /app/data/nija_outreach.sqlite3 if neither NIJA_LEAD_DB_PATH nor NIJA_OUTREACH_DB_PATH is configured. That default may be ephemeral.
- Preserve IONOS lead records, published v450, authorized Zapier account 28290328, existing databases, all opt-outs, payments and trading protections.
- Never print tokens, webhook URLs, customer names/emails, source payloads or protected payment/account information.

## Phase A: inspect active production WITHOUT deployment

In the *existing* authenticated Render service Shell/SSH, run this bounded stdlib probe. It does not write, move files, or send a network request. If access is unavailable, **stop** and report blocked. Running it in a GitHub checkout is not production evidence.

Do not use the earlier inline probe: its database-path precedence did not match the intake runtime. Before invoking any SQLite inspection, verify the active service identity, mounted disk and raw configuration precedence using a reviewed, non-mutating probe. The intake path is selected as the first truthy raw NIJA_LEAD_DB_PATH, NIJA_OUTREACH_DB_PATH or default, then stripped; do not expand ~. A whitespace-only primary override takes precedence and yields an invalid/empty path. Never print raw environment values or secrets.

For live WAL databases, **stop SQLite inspection**. Capture and verify a consistent, independently approved offline snapshot first; do not use immutable=1 against live WAL files, because committed WAL data may be omitted. The corrected preflight returns a fixed WAL failure code rather than opening such a database.

If the service is not verified, the disk is not mounted, the active database is missing, or the active database is outside /data, **STOP**. Do not change database-path environment variables, overwrite an existing copy, reset any table, or redeploy. Reconcile immutable submission IDs after preserving original files and performing a verified backup.

## Phase B: reviewed preflight

Once the reviewed script is safely available in the *running* instance, run:

~~~sh
python3 -B -S scripts/nija_lead_storage_preflight.py
~~~

Do not deploy just to make the script available; use authenticated read-only access to inspect the existing instance first. The corrected script rejects WAL-mode databases and existing WAL/SHM sidecars before connecting, and uses SQLite immutable read-only inspection only for rollback-journal databases. A live concurrent database is not a certified consistent snapshot. It performs bounded aggregate counting and reports fixed technical issue codes without printing secrets.

- lead_db_on_mounted_disk=false: **block release**; possible ephemeral storage.
- multiple_potential_lead_databases_require_reconciliation: **block release**; preserve both copies.
- lead_intake_auth_configured=false: auth must be securely configured.
- forwarding_destination_category=zapier: confirms only the host category; it does **not** verify the expected account 28290328, Zap 378270777, or Apollo receipt.
- Even a clean preflight **does not certify end-to-end lead delivery**.

## Phase C: certification, only after storage verification

1. Verify IONOS LIVE forms and saved submissions. Unpublished IONOS draft referencing Zapier account 28448233 is unsafe; do not publish.
2. Verify HTTPS route and authenticated POST /api/leads/intake using the actual protected configuration, never an exposed token.
3. Send one internal, consent-aware test event with stable submission ID. First authorized request should persist once and return HTTP 201. Exact replay should return 200 with duplicate=true.
4. Reconcile one database row, one known forwarding receipt (or honestly unconfirmed), one Apollo CRM record, one operator notification and zero unauthorized marketing messages.
5. Audit original IONOS records, Zapier execution history, and Apollo consent history before declaring the pipeline certified.
6. Deploy only narrowly scoped fixes after backup, rollback readiness, and separate verification. No trading changes.

## Startup HTTP 502

Observed GET / 502 requests were temporally associated with Render redeploys. Render disk-backed deployments and previously observed out-of-memory events require availability review. No 502 was verified against the protected intake route. Do not modify trading-bot runtime or safety controls to address unverified website routing.

## Blockers

The connected Render tool cannot inspect runtime environment values, persistent file contents, or execute a shell command. IONOS editor access and Zapier task history are also not independently available. No authenticated first-submit/replay evidence or complete end-to-end reconciliation exists. Treat the project as **not certified** until these checks pass.
