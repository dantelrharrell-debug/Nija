# NIJA AI outbound voice consent and eligibility — IONOS implementation handoff (2026-10-23)

**Status: implementation instructions only; NOT deployed or consent certification.**
Tracking: [JustCall recovery issue #3324](https://github.com/dantelrharrell-debug/Nija/issues/3324).
Current calling goal: 300 provider-confirmed outbound attempts per **weekday**, bounded by recipient eligibility, local calling hours, suppression and JustCall authorization. A 300/day cap is not proof that 300 calls were placed.

## Provider findings as of October 23

- Account Manager Kunal Ramchandani confirmed NIJA's AI-assisted trading education and brokerage-related **use case** is eligible for outbound AI calling, **conditional upon adding appropriate AI-call disclosure to the website intake**. Use-case eligibility is NOT account activation, consent certification or permission to call.
- Quote: 1,000 committed minutes at $750/month; 2,000 at $1,200; 5,000 at $2,500; 8,000 at $3,200; 10,000 at $3,500. Overage $0.99/minute, unused minutes do not roll over; cancellation effective next billing cycle. NIJA requested 1,000-minute option for review, not purchase.
- API integration details and an independently proven staffed human transfer/fallback remain outstanding.
- October 23 provider-history audit: **0 confirmed, gap 300**. Apollo feeder scanned 319, **0 call_ready / 0 queued**. Missing AI voice consent, evidence reference, legal basis, DNC verification, recipient timezone and jurisdiction in the audit; overlapping counts must not be added.

## IONOS AI website editor: implementation request

Apply to NIJA-owned contact/lead capture flows at `/apply` and `/free` **and any other form that collects phone numbers for potential AI sales follow-up**. Inspect actual live components first. Do not modify the trading engine, subscriptions, Stripe purchase eligibility, education access, or other unrelated features.

**Proposed disclosure for counsel review, not a legal certification:**

> I agree that NIJA AI Trading LLC may call me at the phone number I provide about NIJA products and services, including using an artificial or AI-generated voice. Consent is not required to purchase. I may revoke consent at any time.

- Add a **separate, optional, initially unchecked** checkbox adjacent to the phone input and clear links to Privacy Policy and Terms; don't combine it with general email, SMS, terms, enrollment, or marketing opt-in. Do not hide it or imply consent from submission, past Apollo possession, a generic “contact me” checkbox, phone number entry or a prior checkbox value.
- Give the exact reviewed wording an immutable `disclosure_version` (e.g. `NIJA-AIVA-VOICE-2026-10-v1`) plus a hash of the full wording; preserve the version actually displayed for each submission. Don't treat a proposed draft version as legally approved until reviewed.
- Store evidence in a **durable, authenticated, access-controlled, auditable** IONOS-managed source: immutable record/submission ID, provided phone, affirmative checked/unchecked state, actual source form URL, timestamp of the user's submission from the source system (UTC), disclosure version + exact wording or immutable lookup, IP and user agent only if disclosed and lawful to collect, and receipt/withdrawal history. Never invent a timestamp, signature, jurisdiction or consent.
- Provide a withdrawal mechanism that immediately suppresses any pending/eligible calls and preserves an audit event. Retention, authorized access, deletion handling and authentication must be documented.
- Source payloads must remain distinguishable: `communications_consent` / generic `consent` are **not** `ai_voice_consent`. Name any **unverified** form claim `ai_voice_consent_claimed`; don't set Apollo's authorization fields just because a browser posted a checked value.
- If validation fails, preserve an ordinary application/education submission where safe, but leave AI-call eligibility **false** and mark the claim for review. Do not pre-check, silently repair or retroactively backfill historic prospects.

## Integration boundary and existing code

- The NIJA repository's `render_lead_intake.py` already stores original lead payload JSON in `website_leads`, but its `communications_consent` normalization is **generic only**; it does not authorize AI calls.
- `render_lead_crm_sync.py` intentionally mirrors name/verified phone to Apollo for CRM-only purposes without adding AI consent, triggering calls, or enrolling sequences.
- `render_apollo_feeder.py` requires documented AI-voice consent, evidence reference, legal basis, genuinely screened DNC + timestamp, suppression review, recipient timezone, jurisdiction and phone; do not substitute employer timezone or inferred geographic data. Maintain fail-closed default. **No direct automatic promotion from a web form into Apollo's `NIJA AI Voice Consent` custom field without independent evidence validation.**
- Once the source receipt system is truly deployed and proved with redacted authentic examples, design a reviewed mapping from the receipt's record ID to Apollo custom fields; validate ownership/consent scope, timestamp and retraction. Never use lead count to populate consent.
- Keep `NIJA_AUTODIAL_WEEKDAYS_ONLY` enabled and all existing recipient-local calling hours, anti-duplicate, rate limits and human-handoff checks.

## Acceptance tests before declaring the form done

1. On each relevant **published** phone collection form, verify a separate unchecked AI-call checkbox, full disclosure, links and mobile rendering; retain a screenshot with any personal data redacted.
2. Submitting without checking creates **no AI-voice consent receipt**, does not mark Apollo AI Voice Consent, and remains ineligible to call.
3. Submitting with checking creates exactly one independently retrievable versioned receipt with actual source timestamp, phone, form URL, acceptance and disclosure text/hash. Replay has the same receipt ID; no duplicate authorizations.
4. Conflicting flags, missing disclosure/version, missing/invalid phone, no real submission timestamp, manipulated payloads and withdrawn consent all fail closed for calling; ordinary form submission and existing purchases are preserved.
5. Query Apollo in read-only mode and confirm zero pre-existing unverified prospects were upgraded; perform an authentic DNC/suppression and jurisdiction/timezone review before any future eligible queue population.
6. The provider/agent setup and transfer must be separately certified with a real JustCall provider call ID from a **separately authorized supervised test**. No self-generated test call, invented call ID or toggling `NIJA_JUSTCALL_HUMAN_HANDOFF_VERIFIED`.
7. After authorized integration/deployment, read-only logs must report actual provider-accepted calls in the relevant Pacific day, not fabricated submissions, worker readiness, queue size or Apollo analytics.

## Rollout and governance

**This document does not authorize calling, site publication, new monthly charges, production deployment, testing via real phones, or trading changes.** IONOS implementation must be reviewed/published separately by its authorized operator. Live trading Render service has `autoDeploy` off and should not be restarted or redeployed for this website-only task. Do not merge infrastructure changes into the trading service while its preservation/certification prerequisites remain unresolved.

Requested post-implementation evidence: published form URLs/screenshots, disclosure/version text, redacted source receipt metadata, QA outcomes, independent Apollo field mapping review, provider written activation, approved call-test record, and day-scoped JustCall provider history.
