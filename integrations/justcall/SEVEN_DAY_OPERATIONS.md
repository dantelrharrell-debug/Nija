# NIJA JustCall: 7-day AI + human campaign launch gates (2026-10-09)

**Status: staged only. Do not infer production activation from this document.**

This patch permits **consideration** of Saturday and Sunday calls; it does not authorize
calling every person seven days per week. The daily cap of 300 is a **maximum** number
of submissions (not a guaranteed minimum or an estimate of real JustCall calls).
It does not count attempted queue checks as actual calls. Maintain separate
consented consumer outreach and screened business outreach, with manual
person-to-person campaigns independently reviewed under applicable laws.

## Security and compliance controls

1. All JustCall AI outbound calls must be submitted through the protected
   `POST /api/justcall/autodial-queue` API. Both `POST /api/justcall/calls`
   implementations intentionally reject direct calls with HTTP 409. Do not
   re-enable the legacy paths.
2. For every automated call require verified, traceable AI-call consent and
   legal basis, fresh recipient-level DNC checks, local suppression clearance,
   specific campaign authorization, a validated recipient timezone, and the
   recipient's actual **calling jurisdiction**. Email opt-in, Apollo verified
   email, place of employment, area code and website-lead presence are not proof
   of AI-call consent or location.
3. Pacing is persisted in the daily quota ledger and defaults to one submission
   every 120 seconds (`NIJA_AUTODIAL_MIN_SUBMISSION_INTERVAL_SECONDS=120`).
   This prevents an unmanageable burst of hundreds of simultaneous AI calls
   and allows up to about 30 per hour when eligible recipients exist.
4. The quota timezone is `America/Los_Angeles`, while the call-hour window
   is evaluated in the recipient's verified local timezone. Defaults are
   09:00–20:00 local. More restrictive state/municipal rules always prevail.
4. For seven-day consideration set `NIJA_AUTODIAL_WEEKDAYS_ONLY=0` **only
   after** this change passes CI, is deliberately deployed, and signed
   jurisdiction-specific weekend authorizations are operational. A recipient
   without a valid reviewed weekend authorization remains blocked.
5. The code conservatively denies **Sunday** outreach to Alabama, Mississippi
   and Pennsylvania recipients. PA Act 47 (effective October 18, 2026) limits
   telephone solicitation after 7 p.m. and before 9 a.m.; the code enforces the
   evening cutoff for all days. These rules are only a baseline: check
   municipal restrictions, holidays, business/consumer classification and
   current law before every approval.
6. Human handoff is required by default via
   `NIJA_JUSTCALL_REQUIRE_HUMAN_HANDOFF=1` and is fail-closed unless
   `NIJA_JUSTCALL_HUMAN_HANDOFF_VERIFIED=1`. Mark verification true **only**
   after manually proving in JustCall that the selected AI Voice Agent has a
   warm transfer configured to a staffed team member/group with fallback
   behavior. The backend environment variable is an operator attestation,
   not a substitute for provider verification.
7. A protected signing key must be installed as
   `NIJA_JUSTCALL_WEEKEND_CLEARANCE_SECRET` (minimum 32 characters, secret,
   not committed). A compliance reviewer records each recipient-specific
   approval, and an independent trusted signer uses this key to issue the
   HMAC-SHA256 signature. An API caller setting `approved=true` is
   insufficient; altering campaign, phone, date, state, consent ID or timestamp
   invalidates the signature.

### Per-contact weekend evidence

```json
{
  "record_id": "apollo:<real-contact-id>",
  "contact_number": "+1<verified-number>",
  "campaign": "NIJA Apollo Outbound",
  "contact_timezone": "America/Los_Angeles",
  "has_consent": true,
  "consent_record_id": "<real-documented-record>",
  "legal_basis": "<documented-AI-calling-basis>",
  "dnc_clear": true,
  "dnc_checked_at": "<fresh-ISO8601>",
  "suppression_clear": true,
  "campaign_enabled": true,
  "weekend_evidence": {
    "recipient_jurisdiction": "US-WA",
    "approved": true,
    "clearance_id": "<compliance-review-id>",
    "cleared_local_date": "2026-10-11",
    "checked_at": "<reviewed-ISO8601>",
    "signature": "<trusted-signer-HMAC-hex>"
  }
}
```

The HMAC signed message is a canonical JSON **object** encoded with UTF-8,
`sort_keys=True`, `separators=(",", ":")`, and `ensure_ascii=True`.
It contains seven keys: `phone_digits` (digits only), `campaign` (exact
campaign string), `consent_record_id` (exact ID), `jurisdiction` (uppercase
`US-XX`), `clearance_id`, `local_date` (recipient `YYYY-MM-DD`), and
`checked_at` (exact timestamp). No API caller may mint its own signature.
The signature is the lowercase hex HMAC-SHA256 output. Never sign a clearance
without an actual legal/consent audit record. Signature age must not exceed
24 hours, and approval is bound to a single recipient-local calendar date.
Weekday calls need the explicit recipient jurisdiction but not the weekend
HMAC. This patch currently supports US states and Washington, DC for
jurisdiction-based clearance; other countries must remain blocked until
their rules and coding are validated.

### Apollo custom-field mapping (optional feeder input)

These Render env vars map **real Apollo field IDs**; none can be invented or
populated from guessed data:

- `NIJA_APOLLO_RECIPIENT_JURISDICTION_FIELD_ID`
- `NIJA_APOLLO_WEEKEND_APPROVED_FIELD_ID`
- `NIJA_APOLLO_WEEKEND_CLEARANCE_ID_FIELD_ID`
- `NIJA_APOLLO_WEEKEND_LOCAL_DATE_FIELD_ID`
- `NIJA_APOLLO_WEEKEND_CHECKED_AT_FIELD_ID`
- `NIJA_APOLLO_WEEKEND_SIGNATURE_FIELD_ID`

The Apollo feeder does not create approvals, signing keys, consents or DNC
clearance; it only transports existing verified data. Without these fields,
a prospect cannot become call-ready.

## Launch order

1. Approve this PR only if the dedicated CI and the existing mandatory
   runtime checks pass. It touches the live trading service code repository;
   merging `main` automatically deploys the production trading service.
   Coordinate production deployment rather than forcing a restart.
2. Confirm provider credentials and AI add-on capacity; verify provider
   `/api/justcall/status`, agent ID, outbound caller ID and test-mode callbacks.
   Do not expose JustCall secrets or access tokens in logs.
3. Configure and test the actual JustCall AI Voice Agent, warm transfer to a
   reachable human rep or user group, fallback to callback, disposition and
   opt-out logging. Configure human-only manual B2B tasks separately.
4. Collect legitimately screened contacts and documented AI-consent records
   for the consumer AI campaign. Review business purpose and method of calling
   for B2B. Never turn on AI-generated or prerecorded speech for cold
   Apollo prospects merely because they have verified business details.
5. Validate local jurisdiction, state/weekend restrictions, fresh DNC screening,
   signed weekend review, daily quota and a **single** supervised permitted
   test call to an approved test recipient, then reconcile the provider's
   accepted call ID and call events with the local queue.
6. Only after live transfer and provider billing are verified, set the
   weekday override to 0 and human-handoff verification to 1; scale volume
   gradually subject to provider rate limits and the number of qualified
   recipients. Inspect actual JustCall calls per Pacific day, not queue
   attempts, and pause if opt-outs fail or calls lack valid provenance.

## Operational proof needed

- Deployment SHA, CI run and live service version for the outreach changes
- Provider-authenticated JustCall outbound call IDs and timestamped delivery
  events that reconcile with queue records (Apollo phone logs may not sync)
- Count of AI calls submitted, accepted, answered and transferred; separate
  human-operated calls and actual distinct contacts
- Documented recipient eligibility, weekend approval, DNC/suppression refresh,
  consent, human team availability, pause/opt-out handling
- No claims of 300/day unless provider-confirmed attempts show 300 or more

**Rollback:** leave `NIJA_AUTODIAL_WEEKDAYS_ONLY=1` or disable
`NIJA_JUSTCALL_AUTODIAL_ENABLED` in production while investigating.
Do not disable DNC, consent, local-time, caller-identification, or anti-repeat
protections to recover volume.
