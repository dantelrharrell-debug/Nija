# NIJA lead-delivery independent verification — November 11, 2026

**NOT CERTIFIED.** Source preparation is review-only. No website publication, production deployment, dispatcher activation, historical replay, new live test, email/contact mutation, payment or trading action was performed.

## Exact source and changes

Starting main: `44ea9dee31db6479a481e650e9d9cd069f82fc88`. PR #3694 is now merged; that evidence merge is not deployment proof.

| File | Change |
| --- | --- |
| render_lead_intake.py | Hold ambiguous provider failures and expired sender leases in durable `uncertain` state; never automatically reclaim them. Add `forward_state` and accurately flag uncertain/unavailable states. Treat a failed completion write as an error. |
| tests/test_lead_forward_idempotency.py | Test ambiguous timeout holds, no expired-lease reclaim, stale-owner fencing, an unconfigured no-send retry, and provider acceptance followed by lost durable completion. |
| scripts/verify_ionos_lead_intake_offline.mjs | Independent VM harness using mocked storage/providers and blocked network primitives. |
| tests/fixtures/ionos/leadIntake.preview-20261111.js | Exact captured IONOS source fixture, not a runtime installation. SHA-256: `57b9aec939a5d12cf186ce3ea102318a5154b5f38fe486f7ab60a16ab6a38cc6`. |
| .github/workflows/lead-crm-recovery-ci.yml | Run the offline exported-source harness and include its paths in triggers. |
| This report | Current independent evidence, limitations and release hold. |

No production trading code, entrypoint, payment integration, secret, account permission or existing database row is changed by this PR.

## Independently verified tests

- Python targeted lead/CRM suite: **99 passed**.
- Exported current IONOS intake: **8 passed, 0 failed**.
- Prior exported intake: **4 passed, 4 failed** in the same eight-check harness. It suppressed distinct submission IDs and changed consent, and accepted conflicting reuse of one ID.
- Corrected export proves: storage failure cannot report success; overlapping same-ID requests store once; lost-response retry retains event/submission/consent timestamps; distinct IDs with identical fields remain separate; separate consent decisions remain separate; same-ID content/consent conflicts are rejected; no provider network I/O and no fabricated sent status.
- Python syntax and diff checks passed. Pinned detect-secrets 1.5.0 changed-file scan with no verification/baseline suppression returned no candidates.
- Repository-specific runtime-tools-secret_scanning and codeql_checker are not available locally. A substitute scan is not an assertion that those mandatory checks passed.
- Hosted CI/security on this PR must still be inspected; local success does not clear release gates.

Reproduce the fixture tests:
```sh
node --experimental-vm-modules scripts/verify_ionos_lead_intake_offline.mjs
```
Optional argument supplies another explicitly exported source file. The harness imports only mocked storage and visitor tracking; it does not submit an event to IONOS or any provider.

## Three form callers independently inspected

Current IONOS exports of FreeAssessment.jsx, FoundingWaitlist.jsx and Apply.jsx all import newSubmissionId and pass explicit submission_id. The assessment resets its ref on an explicit new assessment. Waitlist and application retain a ref through failed attempts; a new mounted form begins a new intent. Apply's follow-up retry reuses its saved intake arguments.

The intake header no longer claims browser Zapier/FormSubmit sends. Source confirmation is not an executed browser submission or live delivery acknowledgment. The pilot application persists its application row separately from its follow-up event; a partial save must remain visible rather than being counted as complete downstream delivery.

Version history now shows **Deploy v516, November 10 at 3:15 PM Pacific**, as the current previewed version, superseding the prior v493 snapshot. Exact deployed asset/source parity remains UNVERIFIED. No publication occurred during this verification.

## Production records and historical provenance

The November 6 authenticated LIVE review independently observed ten application rows, including the five affected records with blank created fields. Current association values matched the provider's report; that does not prove original provenance. No associations, consent, timestamps or application answers were changed.

The current index/backup/runtime status is being checked read-only; do not carry forward the older missing-index claim as a current fact without fresh evidence. Do not export private backup contents into this repository.

## Current provider access

Apollo saved-contact search works again. The newest returned contact creation remains October 20; no new creation in the audit window was observed. This resolves the earlier connector-access failure for this read operation, not every deployed worker's credentials or billing condition.

Zapier sign-in succeeded for the selected Google account, but it exposes only a separate Individual account (28465613, Free). Searching available accounts for NIJA returned no accounts. **This is not authorized business account 28290328** and must not be used to infer that business's current plan, Zap status or downgrade. The business billing URL initially failed and redirected to the Individual context. The November 6 business Pro/ON result is historical. Current authorized-account eligibility, trigger ownership, tasks and provider acknowledgments remain UNVERIFIED pending access to that specific business account. No plan, Zap, task or connection was changed.

## Overlapping 72-hour reconciliation

Window: **November 8 07:00 PST through November 11 07:00 PST** (15:00 UTC endpoints).

- Both accessible Gmail accounts returned no matching FormSubmit/lead-notification/customer-receipt messages. Neither connector proves complete dedicated business-mailbox access.
- Apollo saved contacts sorted newest first: newest creation October 20; no new creation observed in the window.
- Resend lists four recent investor-outreach messages on November 11, excluded from website intake/receipt counts. Latest matching production lead/receipt messages remain October 20.
- Authorized Render workspace Nija_Trading_Bot read-only log queries returned no matching intake request or selected lead/feeder app errors in the window (hasMore false). This is limited log visibility, not zero website attempts.

**Unique real applicants, missing identities and duplicate identities remain UNVERIFIED.** Normalize exact customer email and pair it with source form plus upstream event ID/original time once complete upstream evidence is available. Allow two hours for Apollo insertion. Internal QA is excluded. Preserve the October 7–20 baseline without repetitive alerts.

## Uncertain-forward recovery and release boundary

A timeout or process death can occur after a provider accepts a request. A timed lease alone does not authorize sending it again. The new source holds those outcomes; it does not claim exactly-once provider delivery.

Legacy `sent` means a successful forwarding HTTP response under the pre-existing contract, not inbox delivery or verified Apollo identity. No provider message ID/receipt is fabricated. Completion-write failure and expired leases require independent provider reconciliation. The PR introduces no auto-release endpoint and no historical replay.

Before a lead-only release:
1. Verify the exact source/security/CI results and independent review.
2. Identify one authoritative sender per message purpose; match the actual published business Zap, private hook and stable upstream event ID/time mapping. Browser credentials are prohibited.
3. Verify current protected configuration, immutable backups/counts/checksums and isolated restore; preserve all five disputed pilot records.
4. Identify the exact lead-only deployment target and approved revision/config/rollback. Do not deploy/restart the trading bot.
5. Keep historical queues, pending rows and uncertain claims held. Prior `pending` records may include ambiguous outcomes created before this fix; this PR cannot retroactively classify them.
6. Obtain separate approval for the exact reviewed release/configuration. Preserve new records and provider markers on rollback.
7. Only then obtain separate approval for a new nonmarketing live test. Verify one LIVE record, authenticated exact-event admin readback, one durable claim, provider acknowledgment, exact Apollo identity, intended single Resend receipt and no duplicate on retry. A distinct approved submission remains distinct.

No operational server-mail replacement or end-to-end certification is claimed. The remaining production work cannot be completed by merging this PR.

## Final read-only platform refresh

Independent LIVE database UI now again shows exactly the two known internal-QA event IDs, including the exact saved event requested. Both stored is_qa flags remain false; exclude them by known provenance without rewriting them. LIVE delivery UI independently shows two receipts for the waitlist QA event: email failed (“mail service did not accept it”), Zapier pending (“Zapier address not set”), attempt one each. No new event was submitted.

IONOS's read-only platform report (provider-reported, not an independent schema/backup restore execution) states:
- LIVE events/delivery/dispatch/consent counts **2 / 2 / 0 / 0**.
- The unique index is present: `CREATE UNIQUE INDEX idx_nija_lead_dispatch_event_purpose ON nija_lead_dispatch (event_id, purpose)`. Do not recreate it from stale missing-index notes.
- Lead settings are absent; enabled/activated/live mode and hook-configured flags are false, and no delivery owner is set. The authenticated site-admin status route returned 403 to the platform reader; missing access is not a zero-valued status response.
- Latest backup is `lead_backup_2026-11-07T00-51-21-542Z`; ten checksum lines reportedly match in both retained backups. A throwaway-file restore of the November 6 backup passed 84 checks. No separate November 7 restore or second running site restore is demonstrated.
- These backups are working-folder files, **not immutable copies**. Counts matching current LIVE is not immutable-backup or production-restore certification.
- Dispatcher source in root `pb_hooks/` matches the review copy, but documented `app/pb_hooks/` is absent. The runtime instance/environment and actual hook-directory ownership are not established. Handler-shaped forbidden responses support an installation inference, not certified runtime identity.
- No private secret vault is available to the platform reader; the proposed admin-only settings location's access rules were not independently verified. Never write hook/provider secrets into source/history.
- A prior publish removed the unique index and a later publish restored it; schema must be re-read after any future authorized release.
- Provider reports 326 dispatch and 355 intake mock checks passing today; these are separate provider-reported results, not the independent 99 Python / 8 JS results.

Captured caller SHA-256 values:
- FreeAssessment.jsx: `5979cae084046d3a0b3c270ea8e6727c90a5bf1bae04cec77b8d1d7e2862bd04`.
- FoundingWaitlist.jsx: `a5c6b281904d75dc477c506277c234962f88f3554a0c1de5c54621c216fa8095`.
- Apply.jsx: `fad5fd0bbde3f56b1e0da7b0279ca7aee7ce8bac5ab95f6676635bc19f1ec35a`.

## Hosted verification and owner actions

PR **#3745** is draft and unmerged. Source-bearing commit `52fe71aa4c8754cb9e5304f93f86075ca068626b` has failed hosted workflows. Dedicated CRM run **43048016858**, job **130617118351**, reports failure with no steps/log URL recorded. Branch policy run **43048017002**, job **130617119186**, also has no steps. Security run **43048017311** has failed Bandit/dependency/secret/pre-commit jobs, all with no recorded steps/log URLs. CodeQL **43048021745**, CI **43048016546** and Artifact **43048016688** also failed. This is not evidence that local checks ran on hosted runners or that the source caused the failures. Runner availability/account/repository restriction root cause remains unverified; do not bypass checks or merge.

Concrete owner dependencies:
1. Restore usable GitHub Actions runner execution/account access, then obtain passing mandatory checks and independent review on the exact release revision. No purchase, billing change or gate waiver was attempted.
2. Provide access to the Zapier login that actually exposes **business 28290328 / Zap 378270777**. Current chosen Google identity exposes only Individual 28465613; the observed Free plan does not describe the business account. Do not activate/pay/replace the Zap.
3. Obtain IONOS evidence for the actual backend hook directory, runtime owner/instance lifecycle, private settings access rules, immutable backup copy and isolated restore. Existing support cases: `6aebeaf870f76ca9e19ceea2` and `6a9cf94cfc6297d06dc09d9a`. Prepared question: “For aibuilder-4dfdf, identify the directory and revision loaded by the live lead dispatcher, its runtime owner, how admin-only hook configuration is protected from public reads/history, and the supported immutable backup/isolated restore procedure. Please provide evidence without publishing, restarting, changing records or sending leads.”
4. Resolve one authoritative sender and exact provider idempotency/acknowledgment mapping; no operational secure server-mail alternative is certified.
5. Only after these prerequisites, obtain the separately required exact-release authorization, followed by separate authorization for nonmarketing live QA. No such new authorization is inferred here.

This report is the completion of this safe source/independent-test pass, **not completion of production remediation**. The pipeline remains **NOT CERTIFIED**.
