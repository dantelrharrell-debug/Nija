# Website-to-CRM repair evidence — November 6, 2026

**Determination: NOT CERTIFIED. No production release or new test submission was performed.**

## Applied review-branch fixes

PR #3689 merged at 16:51:15 UTC as `b07d6b0615139c56e5afa778a3012087fcda3bee`.
Its SQLite persistence failure handling and HTTP 503/no-forwarding regression remain intact.
This follow-up is based on `40386b00a01bbbacc8be94bcfaf0f60647b3aa8e` and changes:

| File | Change |
| --- | --- |
| `render_lead_intake.py` | Preserve upstream `source_event_id` and valid original `source_submitted_at` separately from the existing forwarding `event_id` hash and receive-time fallback. Preserve native IONOS email, SMS, AI-voice and program-consent restrictions independently; conflicts fail closed. |
| `tests/test_lead_forward_idempotency.py` | Mocked-provider integration verifies same-event retry sends once, separate upstream IDs remain distinct at the same timestamp, original stored payloads survive, and missing provenance stays empty. |
| `tests/test_lead_phone_consent_evidence.py` | Verify native consent channels, explicit denials, alias conflicts, and no inferred channel permission from a generic form checkbox. |
| `.github/workflows/lead-crm-recovery-ci.yml` | Include `tests/test_lead_intake_review_regressions.py` in path triggers and execution; the persistence regression was previously omitted. |
| This report | Evidence, limitations and release/rollback instructions. |

No database migration, historical replay, new contact, email, webhook configuration,
payment setting, trading code, safety gate or production environment variable is changed.
The existing downstream `event_id` hash is retained for compatibility. Providers must
retain the new source-provenance fields when their mappings are independently reviewed.
These fields do not themselves verify the truth of an upstream claim.

## Validation

The targeted offline suite passed **129 tests and 3 subtests**, including a rerun on
the latest base `40386b00a01bbbacc8be94bcfaf0f60647b3aa8e`. Coverage
includes synthetic intake/CRM integration, SQLite persistence failures, concurrent
duplicate claims, retry backoff, restart persistence, exact-email acknowledgments,
consent, storage preflight and read-only reconciliation. Providers are mocked and
SQLite fixtures are disposable. No production endpoint receives test data.

Changed-file detect-secrets 1.5.0 scanning, syntax and whitespace checks are performed
before commit. The repository-requested
`runtime-tools-secret_scanning` and `codeql_checker` executables are unavailable locally;
the available pinned scanner is used and exact-head hosted CodeQL remains required.

Original PR #3689 Security Scanning run `42253875317`, job `128015736671`, failed
baseline enforcement with **268 unbaselined candidates**. Its Gitleaks and TruffleHog
PR scans passed. This is not a security clearance. Later merged PR #3692 documents
the existing backlog and makes pre-commit failures visible; the backlog remains a
release gate. No baseline is regenerated or weakened in this follow-up.

## Independently observed IONOS evidence

Authorized sign-in reached project `aibuilder-4dfdf`. The editor and its database
administration interface were inspected using the explicitly selected **Live database**
tab, not the initially selected Test database.

- LIVE `nija_lead_events` displayed **2 total records**, both previously known internal QA.
- Exact authenticated database-admin search
  `event_id = "evt_74b942c9-c4a2-4656-88fa-573ac78e80c6"` returned **1 record**:
  record ID `85sa896c4yqgls6`, form `hero_starter_kit`, submitted
  `2026-10-29T15:55:56.690Z`, stored `2026-10-29 15:55:56.777Z`.
- The other event was `evt_70eb30e2-65ae-446b-82cb-3c13b9df18a2`, form
  `founding_100_waitlist`, submitted `2026-10-30T02:23:13.686Z`.
- Both rows display `is_qa=false` despite independently established internal-QA
  identities. Exclude them from real applicant counts without altering those rows.
- The schema visibly separates `consent_marketing_email`, `consent_sms`,
  `consent_ai_voice`, `consent_detail`, payload, timestamps and event ID.
- This verifies the platform's authenticated LIVE database administration search.
  It does **not** verify the separately served website `/admin/settings` role/readback.

The published `/free` assessment landing page, `/founding-waitlist` form and `/apply`
pilot form rendered. No form was filled or submitted. Waitlist marketing consent is
optional; the page says leaving it unticked still joins the waitlist and includes no
calls/texts. The pilot has separate voice and program-update wording. Rendered UI is
not proof that its production save/dispatch handlers work.

The authenticated preview showed a different homepage/game draft. Exact current
published version, source-level live/preview handler comparison and rollback snapshot
remain **UNVERIFIED**. Export was initiated but no usable synchronized source artifact
was available. A strictly scoped draft-only repair request was submitted in the IONOS
editor; its completion and exact file changes could not be observed. Do not treat the
request as an applied fix or publish any resulting changes without inspection.

The next attempt to open LIVE `nija_lead_delivery` was **not executed**: automatic
approval review failed because the workspace was out of credits. No alternate browser
route was used to bypass that refusal. LIVE delivery states, provider acknowledgments,
and the five pilot rows remain unverified in this execution.

## Zapier: authenticated account, plan and published route

- Billing URL resolved to account **28290328**, matching the authorized account.
  The assets URL's `owners=28448233` is the signed-in user/owner filter, not evidence
  of a different billing account.
- Account shows **Pro**, **0/750 plan tasks** and **0/1,500 pay-per-task allowance**.
  A separate visible banner reports a problem with the last payment. This observation
  does not prove suspension; continued eligibility still requires owner billing review.
- Zap **378270777** is ON; published version **v10**, titled
  "Stop empty webhook events before NIJA intake; restore raw_body parsing", is in use.
  A separate draft already exists. Latest run shown in the asset list is October 20.
- Published trigger: **Catch Raw Hook** in Webhooks by Zapier (Premium).
- Published step 3: POST Custom Request to the existing Render `/api/leads/intake`,
  JSON Content-Type, raw-body mapping and a server authentication header. Secret
  values are intentionally omitted from this report.
- Later published steps include JavaScript, Tables lookup and two POST actions.
  Their complete mappings and sender ownership are **UNVERIFIED**. Private Catch Hook
  URL was not independently retrieved/verified. No sender was disabled speculatively.
- No plan purchase, paid activation, draft publication, test run or historical replay.

## 72-hour overlapping reconciliation

Window: **November 3, 2026 09:00 PST through November 6, 2026 09:00 PST**
(`2026-11-03T17:00:00Z` through `2026-11-06T17:00:00Z`).

| Source | Observed result | Interpretation |
| --- | --- | --- |
| Accessible Gmail | No matching customer-receipt or New NIJA Lead messages in the targeted notification search. Support correspondence is separate. | Zero matching notifications, not zero website submissions. |
| Apollo | Existing contacts search sorted descending by creation time; newest contact is October 20. Account reports 319 contacts. | No new contact creations visible in the audit window. Does not exclude updates to existing identities or prove no upstream submissions. |
| Resend | 72 sent records returned; newest is a November 3 03:36 UTC support message, before this window. No sent-message record in the window. | No observed transactional sends in this account/window. Preserve October 7–20 baseline without renewed duplicate alerts. |
| Render | Text-filtered application query and `/api/leads/intake` request-log query returned no entries, `hasMore=false`. | No matching accessible logs; not proof of no website submissions. |
| IONOS LIVE lead events | Two known QA records, both before the window. | Excluded from real-applicant count. Other upstream collections/handlers were not fully verified. |

**Unique real applicants across all three forms: UNVERIFIED. Missing/duplicate real
identities: UNVERIFIED; none asserted.** No current applicant email was independently
established for exact-email contact comparison. The two-hour Apollo insertion allowance
must be applied from an actual upstream submission time once available. Do not infer
missing contacts from notification counts or compare contacts using names alone.

## Five pilot applications and association discrepancy

IONOS Support's November 4 message (Gmail `1a1a7c29d3e4c878`) reports recovered date-only
values for five application IDs and a reversed association between `bm26ihe3a5pj4mn`
and `yxd6w322my8vpcz`. Its November 5 follow-up says the evidence request was escalated.
The owner response explicitly withheld authorization for reassignment/backfill.
These are provider-reported findings, not independently verified original provenance.
No application, association, timestamp, consent record or survey answer was edited.

## Render and production boundary

Read-only workspace inspection confirmed **Nija_Trading_Bot**
`tea-d37fhe8gjchc73c8eo0g`. Trading service `srv-d98dsr5aeets73fpbaqg` has auto-deploy
OFF and was reported live at deployment `dep-dbmv0dmc6qcc73ckp22g`, commit
`b7bbb706af86ca413e2b5ce750216a4ec129a7a0`. This is an observed snapshot, not release
authorization or a claim that the lead fixes are installed.

No restart, redeploy or modification of that trading service was performed.
The repository's existing server-only CRM queue has synthetic coverage, but it is
not a complete independently verified replacement for IONOS capture and customer-email
delivery. Its automatic recent-lead recovery and any pending historical sends must
remain held when preparing an isolated alternative; do not start a worker against
existing data without explicit replay authorization.

## Required release and rollback procedure

1. Restore browser review credits, then inspect the pending IONOS task result and
   its exact source diff. Authenticate separately to website admin; prove exact-event
   readback there as well as the platform LIVE database.
2. Read LIVE delivery and dispatch/outbox records; map exactly one owner per receipt
   and operator notice across IONOS, Zapier and Render. Verify the private hook's
   account/Zap provenance privately. Review every customer-email/event/time mapping.
3. Verify published version and full draft delta; obtain immutable exports/snapshots,
   counts/checksums, retention and tested restore evidence. Protect the five pilot rows.
4. Complete independent source/security review and all mandatory CI on the exact
   release commit. Resolve genuine security findings privately; never suppress gates.
5. Prepare a lead-only deployment destination or website release, not a trading-bot
   redeploy. Keep dispatch disabled and historical queues held until ownership and
   receipt/idempotency controls are proven. Record exact configuration and rollback.
6. Obtain separate owner approval for the exact website/lead-only release and any
   migration; do not infer approval from a merge or this report. Roll back by reverting
   the reviewed source release/configuration, preserving live data and sent markers.
   Never restore an older database over newer submissions or erase delivery claims.
7. Only after those gates, request approval for one new nonmarketing QA event.
   Verify exactly one LIVE record, website-admin exact ID, durable claim, provider
   acknowledgment, exact Apollo identity and intended single Resend receipt.
   Retry the same event without duplicate delivery; test a separately approved distinct
   submission remains distinct. No such live tests were authorized or executed here.

Until these gates pass, keep issue #3421 open and the pipeline **NOT CERTIFIED**.

## Completion follow-up: hosted checks on the tested source

Exact source commit: `b00eae639083d667f4879b8f917019c39d20b65b`.
PR #3693 remains draft and unmerged; this follow-up changes evidence only.

| Hosted check | Result | Evidence |
| --- | --- | --- |
| Dedicated lead/CRM recovery | PASS — 97 tests, including persistence-failure regression | Run 42283714715; job 128119010576 |
| General CI | PASS | Run 42283714653 |
| CodeQL | PASS | Run 42283714683 |
| Imports, preflight/lint, image build, branch policy and manual release hold | PASS | Exact-commit workflow results |
| Dependency vulnerability scan and Bandit | PASS | Security run 42283714636 |
| PR-diff Gitleaks and TruffleHog | PASS | Secret job 128119011340 |
| Full baseline-aware secret scan | FAIL — 268 unbaselined candidates | Job 128119011340; value-free artifact 13536832325 |
| Pre-commit hook validation | FAIL; detailed job log unavailable after two transport failures | Job 128119010716 |
| Artifact scans | FAIL | Run 42283714735 |

The member-broker package job passed pip-audit, then failed GuardDog. Its log includes a
connection-refused error; without reading the retained structured report, that error
does not prove whether the final exit came from scanner operation or package findings.
Report artifact 13536452379 is retained for independent examination.

The dashboard container job built successfully, then Trivy and Grype both failed.
Grype explicitly reported vulnerabilities at or above HIGH. Trivy's table includes
affected Debian OS packages and some entries with no fixed version displayed.
No broad container/production dependency change is made as a website-delivery repair,
and none of these findings is suppressed or declared harmless.

The 268 secret-scan count matches the previously observed backlog, but matching counts
alone do not establish identical candidate identities. Private classification of the
retained evidence is still required. No new credentials were exposed in this follow-up.

**All source changes that were independently verified and safe to apply within this
execution are saved on the draft branch. Production completion remains blocked.**
There has been no new browser access, IONOS draft-result verification, private-hook
verification, provider acknowledgment, website-admin login, customer replay, contact
write, live QA event, publication, deployment or trading change in this follow-up.
The last browser action was rejected by automatic approval review because workspace
credits were exhausted; no bypass was attempted. Restoring review credits is the next
owner action for browser continuation. Do not request or infer live-release/test
authorization before the source, ownership, backup and rollback gates are satisfied.
