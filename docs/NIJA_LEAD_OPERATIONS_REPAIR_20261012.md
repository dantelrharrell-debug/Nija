# NIJA lead operations repair handoff — October 12, 2026

## Verified live findings
- 18 distinct candidate website email addresses were found from 24 detailed NIJA form notifications; a form submission is not proof of identity, marketing consent, or a paid customer.
- All 18 already existed in Apollo; 16 were not enrolled in sequences. Two had prior sequence activity; one had an active sequence.
- Apollo list `NIJA Website Leads` was reconciled to contain the 18 candidates (plus an existing QA/test contact); the separate `NIJA Website - Qualification Pending` list contains 16 contacts.
- 16 Apollo qualification tasks were created and assigned to the NIJA account owner; each requires history/permission review before contact.
- Gmail labels distinguish detailed NIJA submissions, automatic marketing, diagnostics, system notifications, and email warm-up.
- NIJA production Render lead intake at `render_lead_intake.py` already has persisted event replay and outbound-forward fencing. Its deduplication handles canonical stable timestamps for forwarding but cannot prevent independently generated FormSubmit notification messages originating in IONOS forms.
- Render production service `nija-trading-bot` uses manually initiated deployment (`autoDeploy=no`) and persistent `/data` storage. Do not deploy trading infrastructure to solve website email routing.
- Apollo has a linked default business email account, but two historic campaign-enrollment records retained the personal Gmail sender. Do not re-enroll active contacts blindly; sender repair must preserve campaign history and opt-outs.
- Production logs show repeated feeder sync summaries with zero scanned in sampled Oct 12 windows; this is not proof that the CRM integration is healthy and should be investigated using paginated/targeted logs and service configuration without exposing credentials.

## Remaining corrective actions (not certified complete)
1. In IONOS AI website editor, inspect starter-kit and lead-gate form submit handlers; check whether a single submission fires multiple FormSubmit POSTs/notification templates. Produce exactly **one operator notification per form event**, preserving a single contact record with an immutable submission/event ID and stable timestamp. Do not drop separate *real* submissions. Confirm whether using two notifications is an intentional design first.
2. In Zapier `NIJA: New Lead → Intake Normalization & Account Check`, verify dynamic JSON mapping of `email`, `name`, `form_name`, `submitted_at` and a stable `event_id` where available. Keep existing authenticated endpoint and headers. Remove a redundant Apollo Create Contact step *only after* verifying Render's CRM sync works and other tasks do not depend on it.
3. Run synthetic QA submission and exact replay. Expect first 201, replay 200, one Apollo record, one notification, zero unexpected outbound messages.
4. Investigate why `APOLLO_NIJA_FEEDER_SYNC scanned=0` appeared repeatedly in Render logs. Compare actual live Apollo contacts API responses, logs, access/scopes, and pagination. Preserve fail-closed consent/DNC gates.
5. Inspect existing sequence-enrolled contacts that retained `dantelrharrell@gmail.com`; migrate to connected business email in Apollo interface if supported without restarting steps or duplicating messages, and verify changes.
6. Set permanent Gmail incoming filter for `subject:wbx` to label `NIJA/Email Warm-Up` and skip inbox. This connector does not expose Gmail filter creation; connected browser or Gmail UI is needed. Keep genuine enquiries visible.
7. Verify opt-in evidence before marketing email enrollment; separate form-submission confirmations from promotional sequences. Respect unsubscribes, suppression, and calling consent.

## Release boundaries
- Do not merge this handoff into the bot's main branch automatically. No trading, brokerage, billing, or live order changes are authorized.
- No sales messages or calls were sent as part of this repair audit.
- Website/IONOS and Zapier editor access is required for their settings; do not claim those changes were executed until demonstrated.
