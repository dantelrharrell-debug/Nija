# NIJA website-to-CRM restored-access completion evidence

Date: November 6, 2026. This report supersedes the earlier exhausted-browser-credit limitation in website_crm_repair_evidence_20261106.md. It records source remediation and read-only production evidence, not release authorization.

## CURRENT CERTIFICATION STATUS — November 6, 2026

**OPEN — NOT CERTIFIED.** PR [#3693](https://github.com/dantelrharrell-debug/Nija/pull/3693) merged at 20:30:45 UTC as `9f82b06d77217f9f11cee55301e8c0dc0d417502`. Source changes are merged; production delivery remains inactive.

### Restored access: independently observed
- Authenticated IONOS project LIVE database has two known internal-QA events. Website `/admin/settings` now independently verified under **Administrator**: exact event `evt_74b942c9-c4a2-4656-88fa-573ac78e80c6` returns one saved row. Both QA rows remain excluded from real-applicant totals even though stored is_qa flags are false; no records changed.
- LIVE `nija_lead_delivery`: **two rows**, both for waitlist QA `evt_70eb30e2-65ae-446b-82cb-3c13b9df18a2`. Email failed (“mail service did not accept it”), Zapier pending (“Zapier address not set”), each attempt 1. LIVE `nija_lead_dispatch`: **zero claims**.
- Production admin shows no private hook saved and sending switched off. Read-only delivery checks cannot count missed/stuck items because activation/safety settings are absent. No send/retry button was used.
- Zapier business **28290328**: Pro, 0/750 plan tasks, published Zap **378270777 v10 ON**. Existing draft's private Catch Hook was inspected without disclosure; owner segment **28448233** is distinct from business account ID and matches the source allowlist. Published-trigger identity matching remains to be proven before configuration.
- Published Zap step 3 forwards raw JSON to Render intake; step 6 account check uses normalized customer email; step 8 sends `lead.received` to Resend with normalized email/name/form/source/submitted_at. No source-event/idempotency mapping was visible at that send step. Existing six-step draft differs from eight-step published Zap; neither was changed.
- Resend enabled transactional receipt workflow has one email action and terminal exit. State-sync workflow updates contact properties only. Receipt run evidence remains historical (three October 20 runs), not a current acknowledgment.
- IONOS first preview repair completed: environment-aware /free and /apply storage, stable consent timestamp on retry, application confirmation failure notice and admin store labels. New offline suite reported 34 passes. Environment selection helper independently reviewed in Code UI. Full diff/test execution remains provider-reported pending export and independent review.
- Further DRAFT-ONLY source hardening requested after independently observing browser-readable private-hook lookup in intake source. No hook has been populated. Production dispatch remains held.

### Source checks and release blockers
Local source suite: **129 tests + 3 subtests passed**. Exact merged commit dedicated CRM run **42288974426**, general CI **42288974719**, CodeQL **42288974469** passed. Security **42288974384** and Artifact **42288974376** failed. No suppression or broad production dependency change.

1. Finish independent full published/preview source comparison and draft hardening review. Verify secure server-only secret configuration and one delivery owner per purpose across IONOS/Zapier/Render.
2. IONOS reports missing unique(event_id,purpose) dispatch index and no activation settings; independently verify schema and prepare an additive migration only after immutable backups, duplicate audit and tested restore. No schema/config writes authorized or executed.
3. Verify pilot provenance read-only with provider evidence; preserve five affected records and all timestamps/consent. Do not reassociate or backfill from name matching.
4. Resolve mandatory security/CI gates on exact release commit; verify published version, backups and rollback. No trading-bot redeploy.
5. Separate owner approval required for the exact reviewed lead-only release/migration, then separately for a new nonmarketing test. Verify LIVE row/admin ID/durable claim/provider acknowledgment/exact Apollo identity/single Resend receipt; same-event retry must not send twice, intentional separate submissions remain distinct. No new event, replay, email/contact write, publication or deployment occurred.

### Reconciliation
Window **Nov 3 17:00 UTC–Nov 6 17:00 UTC**: no matching notification/receipt mail in accessible Gmail; no new Apollo contact creations observed; no Resend sends; no matching accessible Render intake logs. These do **not** establish zero website submissions. Unique real applicants, missing identities and duplicate identities remain **UNVERIFIED** without complete upstream evidence. Allow two hours for Apollo; preserve October 7–20 baseline without repetitive alerts.

Browser access/credit blocker is resolved. Do not interpret prior blocked-access notes below as current.


## Exact source changes already merged

PR #3689: SQLite persistence exception returns 503 without forwarding or exposing internals.

PR #3693:
- render_lead_intake.py: preserves canonical upstream source_event_id/source_submitted_at alongside legacy forwarding identity; independent marketing-email, SMS, AI voice and program consent fields; conflicting aliases fail closed.
- tests/test_lead_forward_idempotency.py: original provenance, same-event retries, intentional separate events and missing-source evidence.
- tests/test_lead_phone_consent_evidence.py: independent channels and conflicting inputs.
- .github/workflows/lead-crm-recovery-ci.yml: includes persistence-failure regression suite in triggers/execution.
- docs/website_crm_repair_evidence_20261106.md: original evidence and release procedure.

Local verification: 129 tests plus 3 subtests, syntax/diff checks; pinned changed-file detect-secrets scan found no candidates. Full-repository security backlog is not cleared.

## IONOS preview change inventory

Provider-reported commit 06d60294:
- src/lib/pb.js — environment-aware helper/store labels; helper source independently inspected in Code UI.
- src/lib/leadIntake.js — preserve first consent timestamp on retry.
- src/pages/FreeAssessment.jsx — replace always-LIVE client with environment-aware client.
- src/pages/Apply.jsx — same storage isolation; show confirmation-record failure with stable retry identity.
- src/pages/AdminSettings.jsx — display LIVE/PREVIEW store label.
- offline_lead_intake_tests/admin_settings_test.mjs — updated import assertion.
- offline_lead_intake_tests/lead_pipeline_repair_test.mjs — new offline mock regression suite (34 passes reported).
- AGENTS.md — provider task notes.

No live DB/schema writes or source publication. Full source export/download was not successfully obtained. Do not treat provider-reported tests as independent execution. Published repository version reported as Deploy v493 (Nov 5 18:30 UTC), not independently verified deployed source hash.

## Provider ownership and activation contract

The published Zap contains a Resend event action in addition to Render intake/account-check actions. Browser mail and any Render forwarding must be reconciled before choosing one sender. Do not delete a path merely because source contains it; prove reachability and deployed configuration first.

A safe server-only owner must:
1. Read the authoritative saved event by ID under authorized server scope; never trust a browser-supplied customer identity for dispatch.
2. Insert one durable unique claim per upstream event ID plus message purpose before external I/O. A conflicting claim must not call providers.
3. Preserve original submission and consent timestamps on every retry; distinct upstream events from one email remain separate.
4. Record provider request/idempotency identity and acknowledgment separately from acceptance and final delivery.
5. Hold uncertain sends for operator reconciliation rather than blind resend after timeout. Retry only with provider-supported stable idempotency; never replay this existing QA/history.
6. Keep hook/provider secrets server-only and return status metadata only. Require admin authorization for configuration/status review. No public configuration record containing a private hook.
7. Reconcile Apollo by normalized exact email; update consent only from explicit evidence; no marketing enrollment, calls, SMS or duplicate contact creation.

## Additive migration and rollback preparation — NOT EXECUTED

Before requesting release approval:
- Export immutable current LIVE schemas, access rules, records and published source/config versions under private owner-controlled storage. Record backup IDs, timestamps, counts/checksums and retention; demonstrate restore in an isolated environment.
- Verify all five affected application IDs, original provenance and association evidence. Preserve records byte-for-byte; investigate only. Do not backfill timestamp or name associations from guesses.
- Inspect the actual event_id and dispatch purpose fields, existing indexes and duplicates. Capture exact production schema. If missing, prepare a reviewed unique index on (event_id,purpose) without rewriting records. Stop on duplicates; do not auto-delete.
- Document exact server-only secret location, provider owner, endpoint contract, durable mount/database, single writer and deployment revision. An unset hook and disabled dispatch are intentional holds.
- Apply the minimal reviewed schema/source/config release only after separate owner authorization. Do not restart/redeploy the trading bot.
- Set an explicit future activation boundary; keep historical events and existing claims held. No catch-up worker against prior rows.
- Roll back reviewed source/config while retaining all newer records, claims and provider acknowledgment markers. Never restore an older DB over later submissions. If unique-index creation must be undone, require separate reviewed schema procedure; never delete claims.
- Request a separately approved nonmarketing test only once mandatory security, backup, ownership and rollback gates pass. No such approval is inferred from “merged” or “restored.”

## Reconciliation limits

Known real-applicant total is UNVERIFIED. An empty downstream search does not prove zero upstream attempts, and two known LIVE QA rows are not customers. The five pilot association/date discrepancies remain an IONOS provenance investigation, not a data correction instruction. Historical October 7–20 evidence is preserved without new duplicate alarms.

## Production status

No website publish, hook save, dispatcher activation, subscription purchase, historical replay, new synthetic production submission, customer email/contact mutation, payment change or trading-service operation occurred. **NOT CERTIFIED**.
