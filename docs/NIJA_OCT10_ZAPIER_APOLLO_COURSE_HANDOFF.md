# NIJA lead intake / Apollo / $99 course repair — October 10, 2026

This checklist records remaining dashboard-only work without publishing customer identifiers, lead records, API keys, or other private data.

## Confirmed server-side behavior

- NIJA's authenticated Render lead intake normalizes lead email, name, form name, and submission timestamp and rejects empty/invalid JSON with HTTP 422.
- HTTP 201 indicates a newly accepted lead; HTTP 200 can indicate an accepted replay/duplicate.
- Render's lead-to-Apollo worker is already configured to deduplicate contact emails and retry through its persistent queue.
- The billing service passed 10/10 nonmutating live readiness/security probes. Its isolated checkout, entitlement, and secure-access tests passed 27/27 cases. These tests do not prove that a real purchase generates a delivered email.

## Zapier action — requires editor access

Workflow: NIJA: New Lead → Intake Normalization & Account Check.

1. Open the Webhooks by Zapier POST step that contacts the existing authenticated Render lead intake.
2. Retain its existing destination URL and authentication header without copying secret values.
3. Set the body mode to JSON, and map these fields using Zapier's **dynamic trigger tokens**, not literal placeholders:
   - `email`: original form email
   - `name`: original full name
   - `form_name`: original form name
   - `submitted_at`: original stable submission timestamp; do not substitute a new timestamp during retries.
4. Keep JSON Content-Type. Test with a single synthetic QA lead; require HTTP 201 and `accepted=true`, `crm_queued=true`.
5. Inspect downstream Apollo actions. Preserve any Find/Lookup Contact and legitimate task creation. Disable a separate Create Contact step **only after** confirming that tasks can resolve the Render-created contact.
6. Replay the *same* test event and verify a single Apollo contact, no duplicate task, and no additional customer-facing messages. Do not bulk-replay production leads.

## Apollo historical QA duplicate

Two historic internal QA contacts had the same email, one with prior sequence activity and one without. Preserve the record with sequence history; do not delete or merge in the absence of a supported history-preserving workflow. Do not publish Apollo contact IDs or the identifying email address.

## Course activation final test

- Verify the official $99 Stripe one-time Payment Link and the enabled signed billing webhook remain unchanged.
- The course portal reported `ready=true`, `assets_present=true`, `access_ready=true`, `email_configured=true`, and a signing key.
- Complete an **explicitly authorized** controlled test, using Stripe sandbox where supported or a verified already-paid order; never issue a charge without authorization.
- Confirm signed payment verification, exactly one course entitlement, exactly one provider-confirmed secure email, valid one-time claim, private PDF/audio access, replay idempotency, refund/revocation behavior.
- Keep trading and billing separated. Do not merge the audit pull request to main without an intentional production deployment window; NIJA trading auto-deploys on main changes.


## October 12 lead contract follow-up (review branch only)

The IONOS hero opt-in now uses `hero-email-optin`; keep the canonical
`form_name` or `source` and the original `submitted_at` and source
`event_id`/`submission_id` from the form. Never create a fresh event ID
during a retry. The Render handler on the proposed review branch:

- Retains the same normalized email, form, timestamp and explicit consent state.
- Uses `Website Visitor` *only* as a non-identifying fallback for the
  email-only hero form.
- Prefers explicit `marketingConsent`/`marketing_consent` or
  `communicationsConsent`/`communications_consent` fields over the
  older generic `consent` field. Conflicting explicit values fail closed.
- Sends a deterministic, opaque `event_id` to the configured HTTPS forward
  destination. That ID is stable for replay and across form-label aliases.
- Sends `communications_consent`, `consent_source` and
  `consent_recorded_at`. An empty consent timestamp means no reliable
  source submission time was supplied; do not infer permission from it.
- Preserves the original inbound JSON in `website_leads.source_payload_json`
  for audit evidence and retains the existing no-marketing CRM recovery flow.

**Zapier editor action:** Use dynamic trigger fields, not hardcoded strings,
to POST the source's `event_id` (when one exists), `email`, `name`,
`form_name`, `submitted_at` and the explicit marketing checkbox.
Keep Render's authenticated URL/header as-is. Never reinterpret a blank
checkbox as marketing permission. Validate one first submission (HTTP 201)
and exact replay (HTTP 200), one Apollo contact, no duplicate task, and
one operator notification. A localStorage guard is not a server-side
idempotency guarantee.

**Legacy notification migration (required before a lead-service rebuild):**
The temporary source database can disappear when Render replaces the container,
while historical sent markers are stored on the persistent forwarding disk.
Do not switch to source-ID-based forwarding until old sent markers have been
matched to historic source events or the unresolvable histories have been
explicitly reviewed. This is a deployment **gate**, not an automatic live edit.

1. Obtain a verified backup of the *lead intake* SQLite source database and
   confirm the persistent forwarding DB destination. Never use the trading
   ledger file for either path. Perform in a controlled maintenance window.
2. Run the reviewed code **offline**, with
   `NIJA_LEAD_DB_PATH` pointed to that pre-upgrade lead DB and
   `NIJA_LEAD_FORWARD_DB_PATH` pointed to the durable forwarding DB:
   `python -c 'from render_lead_intake import preseed_legacy_forward_aliases as seed; print(seed(dry_run=True))'`
3. Review the counts and unmatched legacy records; then repeat as
   `seed(dry_run=False)` only when approved. The preseed function writes
   proven aliases to the lead-forwarding store, not to trading systems.
4. Back up and verify the durable forwarding DB; confirm a replay with a
   changed form label and timestamp still creates **zero** extra notifications
   after intentionally simulating replacement of the intake DB.
5. A pre-upgrade event lacking a source ID cannot be mapped with certainty
   from an old sent marker alone. Do not label the migration 100% complete
   without recording that residual risk and the deployment decision.

**Do not assume this patch is live.** The Render trading service is manually
deployed and shares runtime with trading code. Confirm source SHA, tests,
verified ledger backup and safety gates before scheduling any deployment.
The existing $99 course Stripe Payment Links remain inactive; earlier
read-only course checks were green, but no authorized paid fulfillment test
has been performed. Do not re-enable paid course checkout as part of a
lead-routing update.
