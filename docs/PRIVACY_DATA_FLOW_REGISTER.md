# NIJA privacy and data-flow register

**Review date:** November 26, 2026 (America/Los_Angeles).

**Source baseline:** `2864e8f997a618d69f61b266d3b6b80ba34b2330`.

**Status:** Source inventory and evidence-gap register; production verification remains open.

## Scope and evidence rules

This register connects the website, mobile account, broker connections, lead
operations, billing, course delivery and supporting business systems. Read it
with the [mobile inventory](../mobile/DATA_INVENTORY.md),
[privacy policy](../PRIVACY_POLICY.md) and
[account-deletion implementation](../account_deletion_api.py).
It is a technical review, not a determination of which privacy laws apply.

The source baseline establishes what inspected code can store or transmit. It
does not establish which code, configuration, schema or provider features are
running in production. Proposed action owners below are responsibilities to
assign, not claims that somebody has accepted or completed an action.

The original scope correction limits sensitive logging and clarifies partial
failures. Subsequent source changes add account-existence checks and this
follow-up expands cleanup inside the configured account database. Production
verification remains open.

Use these evidence labels when updating a row:

| Label | Meaning |
|---|---|
| **Source verified** | The linked implementation or schema contains the described behavior. Runtime enablement, destination and operation still need evidence. |
| **Conditional** | The source requires configuration, a caller or feature activation. Its presence does not prove transmission. |
| **Provider statement** | A dated statement from private provider correspondence; scope and date are preserved. It is not independent technical verification. |
| **Unverified** | The reviewed evidence does not establish the item. This does not mean the control is absent or that retention is unlimited. |

Maintain detailed evidence in the approved private operational record. Repository
updates must contain only sanitized conclusions, source references and review
status. Do not add customer records, private correspondence links, mailbox/message
IDs, account-specific export links, credentials, support attachments or raw logs.
An email address hash, contact identifier or pseudonymous client ID can still be
linkable data; do not treat hashing alone as anonymization.

## Render inquiry: recorded scope and remaining questions

**Provider statement, November 20, 2026 Pacific:** Render support stated that the
four newly named providers were not receiving data from NIJA's services at that
time. It described Anthropic and TypeSafe AI as intended for AI features that
were not yet released. The support threads were subsequently closed on
November 24 Pacific. The evidence source is private provider correspondence;
its contents and account identifiers are not reproduced here.

This is dated assurance about service data. It does not establish future
activation rules, mandatory opt-in, a disable control, no-training terms,
prompt/output retention, or the treatment of account, usage and support data.
It is not an independent test of NIJA's application controls. Preserve those
distinctions in public-facing descriptions and vendor decisions.

The public [Render subprocessor list](https://render.com/security) identifies
Anthropic and TypeSafe AI for AI/machine learning, Grafana Labs for observability,
and Temporal for workflow orchestration. Entity country is not a full processing
location map. Listing a vendor does not prove it received NIJA data.

The indexed [Render DPA](https://render.com/dpa), marked December 19, 2024,
distinguishes customer data from Render account/usage data and describes a
ten-day new-subprocessor objection process. The private notice's stated deadline
needs reconciliation with the applicable agreement version and receipt time.
Neither a closed ticket nor a request for clarification proves an objection was
accepted, waived or extended. Record the provider's written clarification and
the owner's resulting decision before marking that issue resolved.

## A. Data routes and purposes

The IDs in this table connect to retention/deletion and proof requirements in
the next sections. A default filesystem path identifies a source setting, not a
verified production mount or geographic region.

| ID / route | Data and purpose | Source and provider/destination | Evidence boundary |
|---|---|---|---|
| **A1 — Account and authentication** | User ID, email, password hash, session IDs/expiry, login IP and user agent, subscription tier, terms/risk acknowledgments; authentication, access and account security. | [`auth/user_database.py`](../auth/user_database.py), [`auth/storage.py`](../auth/storage.py), [`api_server.py`](../api_server.py), [`mobile_backend_server.py`](../mobile_backend_server.py). SQLite selected by `NIJA_AUTH_USER_DB_PATH`, with `users.db` fallback; configured application host. | **Source verified.** Production database path, volume, active gateways, access controls and region **unverified** by this review. |
| **A2 — Verification, reset and 2FA** | Email verification/reset tokens, user/email linkage, expiry/use state; TOTP secret, enabled state and backup-code hashes. | [`auth/email_service.py`](../auth/email_service.py), [`auth/two_factor.py`](../auth/two_factor.py). Shared auth database selector; configured SMTP provider for messages. | **Source verified / conditional mail delivery.** The TOTP write path persists the secret directly to SQLite; do not infer field encryption from the class description. Verify actual storage protections. |
| **A3 — Local broker credential vault** | Broker API credentials, user/broker association, credential audit metadata; authenticated broker connection. | [`vault/__init__.py`](../vault/__init__.py), [`auth/__init__.py`](../auth/__init__.py), [`account_deletion_api.py`](../account_deletion_api.py). Local encrypted vault plus legacy in-memory credential manager; selected broker when a caller authenticates. | **Source verified.** Local vault uses Fernet. Production vault path, key custody, runtime copies and broker permission scope **unverified**. Removing NIJA's copy does not revoke a provider key. |
| **A4 — Member broker vault** | Member ID, broker/environment, encrypted credential envelope; member-scoped broker onboarding. | [`member_broker_vault.py`](../member_broker_vault.py), [`member_broker_http_api.py`](../member_broker_http_api.py). HTTPS PocketBase `nija_broker_vault` collection selected by `NIJA_POCKETBASE_URL`; AES-GCM binds ciphertext to user/broker/environment. | **Source verified / conditional.** This is distinct from A3. Confirm the deployed collection rules, URL ownership, member/entitlement checks, key custody and region. Do not publish actual endpoints or keys in evidence. |
| **A5 — Broker state, trades and recovery** | Account-linked balances, positions, orders/fills, fees, position/order identifiers, P&L, durable submission intent and risk state; execution safety, reporting and reconciliation. | [`bot/trade_ledger_db.py`](../bot/trade_ledger_db.py), [`bot/trading_state_machine.py`](../bot/trading_state_machine.py), [`scripts/nija_kraken_journal_backup.py`](../scripts/nija_kraken_journal_backup.py), broker adapters. Selected broker APIs; configured NIJA databases, files and runtime logs. | **Source verified.** A configured ledger path is not restart/restore proof. Identify active stores and all account associations without changing trading guards or historical evidence. |
| **A6 — Mobile devices and push** | Authenticated user/device IDs, platform, device/app details, encrypted push token and token hash; device registration and notifications. | [`mobile_device_store.py`](../mobile_device_store.py), [`mobile_api.py`](../mobile_api.py), [`push_notifications.py`](../push_notifications.py). SQLite `MOBILE_DEVICE_DB_PATH`; APNs/FCM only with a configured provider implementation. | **Source verified / conditional.** Default providers explicitly report `not_configured`. Do not declare APNs/FCM delivery solely because the interface exists. |
| **A7 — Website source lead/consent records** | Form submissions and original consent/provenance, submission identifiers, delivery/dispatch state; responding to inquiries and controlling follow-up. | [`scripts/ionos_lead_readonly_export.mjs`](../scripts/ionos_lead_readonly_export.mjs), [`scripts/nija_ionos_lead_rule_audit.py`](../scripts/nija_ionos_lead_rule_audit.py). IONOS PocketBase collections `nija_lead_events`, `nija_lead_delivery`, `nija_lead_dispatch`, `nija_consent_events`. | **Source verified inventory targets.** Published form fields, collection schema/rules, actual routes, region and complete source-store coverage require authenticated evidence. This store is distinct from Render's mirror. |
| **A8 — Render lead intake and forwarding** | Name, email, optional phone, original submitted payload, source timestamp/ID, channel-specific consent and forwarding state; durable intake, deduplication and delivery. | [`render_lead_intake.py`](../render_lead_intake.py). SQLite `website_leads`, forwarding and alias tables; configured allowlisted server-side destination, including a Zapier hook only if configured and admitted by the destination guard. | **Source verified / conditional forwarding.** Original payload JSON can contain more data than the normalized fields. General form consent does not grant SMS/AI-voice consent. A disabled or missing webhook does not prove A9 is disabled. |
| **A9 — CRM recovery and outbound eligibility** | Lead contact details, event/Apollo contact IDs, synchronization attempts/state, consent/suppression/DNC evidence; CRM recovery and separately gated outreach eligibility. | [`render_lead_crm_sync.py`](../render_lead_crm_sync.py), [`render_apollo_feeder.py`](../render_apollo_feeder.py). SQLite mirror, Redis `nija:lead_crm` records, Apollo API; eligible records may feed the separate outreach queue. | **Source verified / conditional.** CRM sync defaults enabled in source but needs runtime credentials/worker configuration; it does not enroll contacts in campaigns or manufacture consent. Actual transfer history and all enabled workers remain **unverified** here. |
| **A10 — JustCall and outreach** | Contact numbers, call/provider IDs, webhook payloads, call state and suppression records; approved contact handling and delivery reconciliation. | [`justcall_client.py`](../justcall_client.py), [`render_outreach_store.py`](../render_outreach_store.py), [`integrations/justcall/eligibility.py`](../integrations/justcall/eligibility.py). JustCall API and NIJA SQLite outreach tables. | **Source verified / conditional.** Provider-held recordings/SMS/voicemail are an account-inventory question. Code that accepts provider events does not establish that every content type exists. |
| **A11 — Billing and entitlement** | User/email association, Stripe customer/subscription/session/payment IDs, offer/verification status, entitlement and event identity; payment verification and access. Optional Bitcoin-order schema includes invoice/provider status. | [`billing_service_store.py`](../billing_service_store.py), [`billing_store.py`](../billing_store.py), [`course_fulfillment.py`](../course_fulfillment.py). Configured billing SQL database and payment provider APIs. | **Source verified / conditional provider paths.** Schema presence does not establish a live BitPay or other payment route. No raw card fields were identified in these inspected schemas; assess other active routes separately. |
| **A12 — Course access and transactional delivery** | Buyer email/session association, magic-token hash and expiry/use, message-provider ID/status, recovery rate-limit hash derived from email/IP; private lesson delivery and access recovery. | [`course_portal.py`](../course_portal.py), [`course_private_video.py`](../course_private_video.py), [`resend_delivery.py`](../resend_delivery.py), [`founding_onboarding_mail.py`](../founding_onboarding_mail.py). Billing SQL, configured private-media storage and Resend when enabled. | **Source verified / conditional.** Lesson files are content assets; access tokens and buyer links are personal/security data. Payment entitlement, content availability and email delivery are separate facts to verify. |
| **A13 — Trading IQ and isolated tests** | Run/decision data, scoring/report records, entitlement expiry, payment-event identities and verification/revocation state; educational results and TEST verification. | [`web/trading-challenge/v515/server/sql/tiq72-v515-report-ledger.sql`](../web/trading-challenge/v515/server/sql/tiq72-v515-report-ledger.sql), [`web/trading-challenge/v515/server/v515-pg-report-store.mjs`](../web/trading-challenge/v515/server/v515-pg-report-store.mjs), [`founding_trial_stripe_test_readback.py`](../founding_trial_stripe_test_readback.py), [`billing_staging_database_binding.py`](../billing_staging_database_binding.py). Configured test database/Stripe TEST account where the guarded path is used. | **Source verified / conditional.** Isolated source guards do not prove current sandbox bindings or absence of copied customer data. Require synthetic fixtures and private runtime binding evidence. |
| **A14 — Support mail and archives** | Correspondence, addresses, attachments and possible customer/account references; support and service administration. | Business-process inventory, private provider correspondence; IONOS mailbox/archive services and any actually used mail/helpdesk account. [`auth/email_service.py`](../auth/email_service.py) covers transactional SMTP only. | **Provider statement / externally managed.** Repository source cannot establish mailbox contents, archive completeness, forwarding rules, provider retention or deletion. Keep business support separate from application-email mechanics. |
| **A15 — Exports, backups and recovery copies** | Copies of the data in other rows, schema/manifests and integrity metadata; recovery and verification. | [`scripts/nija_lead_protected_snapshot.py`](../scripts/nija_lead_protected_snapshot.py), [`scripts/nija_lead_isolated_restore_verify.py`](../scripts/nija_lead_isolated_restore_verify.py), [`scripts/ionos_lead_readonly_export.mjs`](../scripts/ionos_lead_readonly_export.mjs), [`scripts/nija_trade_ledger_snapshot_v436.py`](../scripts/nija_trade_ledger_snapshot_v436.py). Approved off-host storage and Render backup facilities when applicable. | **Source verified / conditional.** An IONOS logical export is expressly not a transactional backup. A folder, script or one successful rehearsal does not prove recurring backups, full scope or current recoverability. |
| **A16 — Education AI and analytics** | Potential questions/context/answers, usage/conversion identifiers, event data; education or measurement when a path is enabled. | [`education_system.py`](../education_system.py), [`education_pilot/provider.py`](../education_pilot/provider.py), [`analytics/conversion_delivery.py`](../analytics/conversion_delivery.py), [`analytics/conversion_outbox.py`](../analytics/conversion_outbox.py). Inspected education paths are placeholder/static mock; GA4 adapter requires explicit enablement/configuration/invocation. | **Source verified / conditional.** No outbound AI provider call is implemented in these inspected education paths. GA4 delivery is not wired to website/billing handlers in the inspected source. This does not audit IONOS tags, other deployed clients or provider-side AI features. |
| **A17 — Logs, diagnostics and administrative evidence** | Timestamps, request and account identifiers, IP/device metadata, errors and event outcomes; security, operations and incident investigation. | Logging in the modules above, host/request logs, deployment/CI artifacts and manually prepared support evidence; Render and any configured log destination. | **Source verified potential.** Some inspected authentication log calls include user/email identifiers. Check actual production logging and redaction. Do not infer that every vendor receives these logs or that every log line is anonymous. |

## B. Retention, location and deletion coverage

Unless a row states otherwise, geographic storage/processing locations,
provider-side retention, NIJA record expiry and backup erasure are **unverified**
for the deployed system. A validity period, retry lease or limited search window
is not a data-deletion schedule. Record numeric periods only when an approved
policy or actual mechanism establishes them.

| IDs | Known source behavior | Deletion coverage and proof still needed |
|---|---|---|
| **A1** | The coordinator deletes `users`, `sessions` and `login_history`. The current source Flask and FastAPI guards check the persisted subject, and the mobile request hook checks account existence and enablement. | Synthetic HTTP tests verify a previously issued access token is rejected after deletion and a second account stays authorized. The checked login issues no refresh token. Confirm deployed issuer and store bindings, re-registration and existing WebSocket sessions before broader revocation claims. |
| **A2** | The review branch deletes local verification/reset rows, TOTP secrets and backup-code hashes in the same account database transaction when the tables exist. | Synthetic SQLite tests verify target-only deletion, older schemas without these tables, rollback and retry. Separate stores, transactional email, external tokens and restored copies remain outside these tests. |
| **A3** | The coordinator removes local vault credentials/audit rows, legacy broker credential entries, runtime user/permission caches and per-user rule files. | Verify every active credential copy/key-custody path. A successful NIJA deletion response does not delete exchange accounts, revoke exchange keys or remove independent provider records. |
| **A4** | Member-vault source creates, lists and retrieves encrypted PocketBase records; the mobile coordinator targets a different local vault. | Separate member-vault lifecycle and record removal require an authenticated, owned-scope workflow and evidence. Do not claim coverage from A3 tests. |
| **A5** | Ledger/state files preserve account-linked financial and safety evidence. This review establishes no approved universal retention duration. | Outside the mobile deletion coordinator. Assess purpose, actual identity linkage and any required retention before a separately reviewed deletion/anonymization design. Never remove recovery evidence or weaken operational gates as a privacy shortcut. |
| **A6** | Device unregister and per-user registry deletion exist; provider-confirmed invalid tokens are removed. The coordinator calls per-user device deletion. | Prove removal on the deployed registry and inspect token-bearing logs/backups. Any configured provider's copies require separate retention/deletion verification. |
| **A7–A8** | Source lead stores preserve provenance/consent and forwarding states. Forwarding leases and retry backoff manage delivery, not retention. | No cross-store erasure is established by mobile account deletion. Map source IDs across IONOS, Render, aliases and any destination, and test deletion/withdrawal without replaying notifications or inventing consent. |
| **A9** | Apollo-acknowledged Redis contact hashes receive a 90-day TTL. A seven-day source recovery selection exists. | The 90-day TTL does not cover every pending/review record, SQLite mirror or Apollo contact. The seven-day query is not a purge. Establish scope-aware cleanup plus minimal suppression evidence where justified; prevent backup/recovery workers from recreating erased records. |
| **A10** | NIJA persists webhook payloads, call state and suppression records. Source presence does not establish a purge period. | Separate NIJA/provider deletion and export workflows needed. Preserve necessary suppression so deletion does not accidentally reauthorize contact. Review any recordings/transcripts only if account inventory establishes them. |
| **A11** | Billing stores retain customer, checkout, entitlement and event identities. Releasing an unprocessed event claim is retry handling, not a customer deletion policy. | Outside the mobile deletion coordinator. Define appropriate retention and user linkage with the business owner; preserve valid customer entitlements and refund/dispute evidence during any approved change. |
| **A12** | Course delivery magic links expire after 7 days; standard recovery links default to 48 hours. Token hashes, mail outbox and rate-limit records have separate persistence. | Expired access is not row deletion. Inventory buyer-linked tables, email-provider events, session/cookie handling and storage access logs; verify lifecycle and deletion without disrupting remaining entitlements. |
| **A13** | Report/access expiry and revocation fields exist. The report schema preserves refunded/disputed reservation state to keep access revoked. | Do not reinterpret revocation rules as a universal retention period. Verify TEST-only account/database/mode bindings, synthetic inputs, export custody and cleanup after each rehearsal. Never copy real customer or broker data merely to populate tests. |
| **A14** | Mailboxes and archives are managed outside the application deletion coordinator. Private provider correspondence establishes only the bounded status below. | Document who can access/forward/export mail, retention and restoration of archives, support-intake deletion handling, and independently controlled provider records. |
| **A15** | Protected capture/export tools use encryption and isolated verification mechanisms. They do not establish a deployed recurring schedule. | Inventory ciphertext and key custody separately; record source scope, destination/region, access, expiry, restore date and handling of previously erased data after restoration. Restrict temporary plaintext and remove it according to the approved exercise procedure. |
| **A16** | Inspected education mock does not call an AI vendor. GA4 delivery defaults disabled and whitelists outbound event parameters when explicitly invoked. | Before activation, verify exact payloads, legal/notice/consent decisions as applicable, provider terms, retention/deletion, budget and identity controls. Verify published browser tags separately. No-training or zero-retention promises require specific evidence. |
| **A17** | Application logging and host log retention are separate. Source contains account-linked log messages; runtime contents are not certified by source review. | Identify each log/artifact/export sink; inspect synthetic traces for sensitive fields, sanitize at source, restrict access and set approved expiry. Do not publish raw production samples or assume account deletion purges infrastructure logs. |

### Provider defaults are verification inputs, not NIJA configuration evidence

As reviewed on November 26 Pacific, Render documents log retention by workspace
plan (7/14/30 days), paid Postgres recovery windows by workspace plan (3/7 days),
seven-day logical-export retention, and daily persistent-disk snapshots retained
seven days. Logs and disk snapshots are documented as stored in the service
region. Audit-log availability and collection depend on an eligible plan.
Verify the current plan and resource type before applying any duration to NIJA.
External exports and support/AI data require separate schedules.

Primary references:
[service logs](https://render.com/docs/logging),
[audit logs](https://render.com/docs/audit-logs),
[Postgres recovery](https://render.com/docs/postgresql-backups),
[persistent disks](https://render.com/docs/disks),
[regions](https://render.com/docs/regions), and
[shared responsibility](https://render.com/docs/shared-responsibility-model).

### Dated preservation findings for externally managed systems

- **JustCall — provider statement, November 22 Pacific:** its inventory reported
  contacts and one number; it reported no call logs, SMS, recordings or voicemails
  at that time. A one-time export was offered. A later November 25 statement
  described cancellation associated with the December 5 unpaid-invoice deadline
  and eventual permanent deletion, without an exact deletion date or grace
  period. Conditional hibernation preservation is not evidence of activation.
  The November 26 check-in did not establish a delivered export. Bounded
  connected-file/mail checks did not verify a native JustCall export; a historical
  outreach CSV is not a certified replacement.
- **JustCall — updated provider confirmation, November 27, 2026 UTC:** a
  Product Support Engineer reported **1 JustCall contact and 25 SalesDialer
  contacts**, with no JustCall restricted/DNCA contacts. The provider said
  SalesDialer has no self-service contact export but offered a one-time backend
  export; a secured owner-verifiable backend export was requested in the
  existing support thread on November 27. Consent/opt-out history is not
  maintained as separate contact fields and may instead be reflected in SMS
  conversation exports. Exact call, SMS, recording and voicemail record counts
  could not be confirmed by provider support; do not infer that those records
  are empty. The provider specified **December 5, 2026** as the last date
  for customer account access if the invoice remains unpaid and **January 4,
  2027** as the last date data would be preserved under its stated policy.
  These are provider statements, **not independently verified retention
  guarantees**. No export bytes, field inventory, encrypted retrieval proof,
  cross-system consent reconciliation or backup/restore proof have been
  received. The offered export must not be treated as completed.
- **IONOS — provider statement, November 25 Pacific:** three mailboxes were
  described as active, but the reply did not establish an archiving ticket
  identifier, resolution time, interruption intervals, recovery of missed mail or
  later successful archive-job proof. Its setup explanation remained inconsistent
  with earlier failures/escalation. Mailbox availability therefore does not close
  archive completeness or recoverability.
- **Backup discovery limit:** a website-lead export folder title without files in
  its direct listing is not proof of an export, archive or backup. This bounded
  observation does not prove that no copies exist elsewhere.

These sanitized statements belong to **A10**, **A14** and **A15**. They are not
permission to pay, cancel, activate hibernation, change retention or delete data.

## C. Closure work and proposed owners

| Priority / gap | Proposed accountable owner | Evidence required to close |
|---|---|---|
| **High — Render assurance and future use** | NIJA owner with Render privacy/support | Applicable agreement/notice versions; written reconciliation of notice/deadline; definition of service versus account/usage/support data; feature triggers/defaults; payload categories; training/use, retention and deletion terms; available disable/objection route. Record decision separately from ticket state. |
| **High — Deletion scope and access revocation** | NIJA engineering; NIJA owner approves retention decisions | Exact deployed coordinator/schema and gateways; synthetic lifecycle tests proving issued-token rejection and preventing device re-registration after account removal; explicit covered/outside-coverage stores; authenticated workflows for uncovered stores; stable cross-store identity mapping and partial-failure handling. A partial-cleanup error does not confirm access revocation. Source disclosure corrections alone are not full erasure or a revocation repair. |
| **High — Secrets, access and support evidence** | NIJA engineering and account administrators | MFA/role and production-environment review, credential scope/custody, auth-token/TOTP storage protections, sanitized logs/support samples, and access evidence for backup exports. Record findings without secrets. |
| **High — JustCall preservation** | NIJA owner with provider support | Provider inventory/export scope, actual secured export, record/field reconciliation, restoration/readability, exact preservation/deletion conditions and deadline. An offer or conditional plan does not close this row. |
| **High — IONOS archiving** | NIJA owner with IONOS support | Consistent incident history, affected intervals, proof of recovered historical messages or explicit unrecoverable scope, and subsequent successful archive-job/restore evidence. |
| **High — Lead data and consent lineage** | NIJA engineering and outreach operator | Published field/routing/schema readback, source-to-mirror/destination joins, separately verified channel consent and withdrawal propagation, destination acknowledgments, restricted access and exact cleanup coverage. |
| **Medium — Retention/location register** | NIJA owner with engineering and each provider | Approved per-category purpose/period, actual region/transfer/access map, deployed job/configuration evidence, exception handling and backup expiry. Do not replace unknowns with invented statutory periods. |
| **Medium — Backup and sandbox isolation** | NIJA engineering | Exact source scope, encrypted off-host custody, independent readback and isolated restore, recurring schedule evidence where claimed, synthetic-only TEST binding evidence and cleanup; protection against reintroducing erased records. |
| **Medium — Rights and incident operations** | NIJA owner; designated support/security operator | Verified request intake, identity checks, response/escalation responsibilities, processor coordination, incident contacts and a documented exercise. Render's incident terms do not replace NIJA's application incident process. |
| **Before enabling — AI, analytics or additional providers** | NIJA owner with engineering | Exact enabled implementation, minimized payload trace, provider settings/terms, required notices/choices, retention/deletion and isolation tests; reconcile website and mobile disclosures against the actual release. |

## Evidence acceptance and update procedure

For each completed item, record the row ID, date/time, exact reviewed commit or
deployed artifact, resource scope, verification method, result, limitations,
reviewer and a private evidence reference. Only publish the sanitized conclusion
and source reference in this register. Do not treat missing evidence as a failed
control or a support closure as production certification.

Recheck affected rows whenever a provider, route, SDK, database, export destination,
retention rule, AI feature, consent flow or deletion handler changes. Review the
actual published release independently of the repository. Stop only the affected
data flow when a separately approved control requires it; do not expand this
documentation change into trading, payment, account or provider mutations.

## Review-branch follow-up

The original privacy suite passed on #4200. Its security and artifact runs
reported independent gates still open, including the historical source review,
repository-wide pre-commit, the container vulnerability thresholds, and package
heuristics. See [original Security Scanning](https://github.com/dantelrharrell-debug/Nija/actions/runs/45949642850)
and [original Artifact Scanning](https://github.com/dantelrharrell-debug/Nija/actions/runs/45949643291).
NIJA security engineering owns exact-source review and secret classification.
Platform and dependency maintainers own image and package remediation. Preserve
the existing integrity pins and scan thresholds. Current hosted results are
tracked on [the follow-up PR](https://github.com/dantelrharrell-debug/Nija/pull/4217).

| Stores | Evidence and owner |
| --- | --- |
| A1–A3, A6 | NIJA engineering. Isolated tests check the source auth guards and target-only active-store deletion. Production gateway and database bindings, runtime copies, and already-open sessions remain unverified. The same account can retry a partial deletion while its primary auth record still exists. |
| A4–A5 | NIJA owner and engineering. Member vault, provider keys and broker/ledger records remain outside the deletion coordinator. Map identity and confirm obligations before separate cleanup. |
| A7–A10 | NIJA owner and vendors. Website/lead, CRM, consent and outreach records remain outside the coordinator. JustCall confirmed one JustCall contact and 25 SalesDialer contacts. The vendor initially offered a backend export, then suggested an API workaround before resuming escalation if needed. No verified export or existing report was located. File readability, actual row counts and usable opt-out evidence remain unverified. |
| A11–A13 | Billing and education owners. Payment, dispute, entitlement and course-progress stores remain outside the coordinator. Preserve valid entitlements pending owner-approved lifecycle rules. |
| A14–A17 | NIJA owner, engineering and providers. Support mail, backups, analytics and logs remain outside the coordinator. IONOS acknowledged an investigation-only escalation to its Email Back-Office and requested preservation. Affected intervals, recovered or unrecoverable mail, and successful restore evidence remain outstanding. The Render privacy follow-up appears as sent in the existing private thread. No substantive reply was verified. |

### Retention proposals for owner approval

- Purge spent local verification and reset tokens within 30 days of expiry. Delete covered 2FA material with the account.
- Review inactive lead records after 12 months. Approve consent-evidence handling and keep only the minimum necessary to enforce suppression.
- Target 30 days for routine logs and 90 days for restricted incident logs, subject to approved holds and actual provider controls.
- Evaluate 30-day backup rotation where supported and reapply approved deletions and suppression before access to restored data. Billing, support and broker records require separate owner-approved schedules.

### Release and rollback sequence

After exact-candidate checks and independent review pass, verify that the target API and mobile entrypoints use the approved account store. Deploy the API first and verify the revised behavior using a separately approved synthetic production account. Then publish the approved website and mobile disclosures and verify actual published copies. If checks fail, roll back each surface to its last approved software or publication version. A software rollback cannot restore records already deleted.
