# NIJA calling activation handoff — verified configuration, October 9, 2026

This is NOT evidence that NIJA can legally call any prospect. No outbound calling
can be enabled solely from this document.

## Apollo custom-field IDs verified in the connected account

| Purpose | Label | Field ID |
| --- | --- | --- |
| AI voice opt-in | NIJA AI Voice Consent | 6ac84c245637700018286799 |
| Evidence reference | NIJA Consent Record ID | 6ac84c269e7254000c9e3ac1 |
| Legal basis | NIJA Legal Basis | 6ac84c28bc691b0014b7177c |
| DNC status | NIJA DNC Status | 6ac84c2ae02a56001438fb74 |
| DNC checked timestamp | NIJA DNC Checked At | 6ac84c2d78d0e8000c837be7 |
| Campaign enabled | NIJA Campaign Enabled | 6ac84c3098c5a90010ab085d |

To map these existing fields to the Apollo feeder without reading secrets,
configure the matching environment variable keys with these IDs:

```text
NIJA_APOLLO_CONSENT_FIELD_ID=6ac84c245637700018286799
NIJA_APOLLO_CONSENT_RECORD_FIELD_ID=6ac84c269e7254000c9e3ac1
NIJA_APOLLO_LEGAL_BASIS_FIELD_ID=6ac84c28bc691b0014b7177c
NIJA_APOLLO_DNC_STATUS_FIELD_ID=6ac84c2ae02a56001438fb74
NIJA_APOLLO_DNC_CHECKED_AT_FIELD_ID=6ac84c2d78d0e8000c837be7
NIJA_APOLLO_CAMPAIGN_ENABLED_FIELD_ID=6ac84c3098c5a90010ab085d
```

Changing environment variables on Render can redeploy NIJA's LIVE trading service.
Coordinate change-control, CI and active trading safeguards. Never overwrite
unrelated environment variables.

The current custom field catalog does NOT contain fields for signed recipient
jurisdiction, timezone or weekend clearance. These must be created and mapped
using validated new Apollo field IDs; do not infer jurisdiction from company
location, area code or inferred timezone.

## NIJA IONOS form requirements

Create an optional, unchecked, standalone checkbox next to the phone number on
`/apply` and `/free` for AI-generated marketing calls. Proposed disclosure
for legal review, with links to Privacy Policy and Terms:

"I agree that NIJA AI Trading LLC may call me at the number I provide about
NIJA products and services, including using an artificial or AI-generated
voice. Consent is not required to purchase. I may revoke consent at any time."

Capture who consented; exact disclosure text and version; affirmative electronic
signature or equivalent evidence; timestamp; form URL/source; verified phone
number; IP and user agent if disclosed in the privacy policy; and consent scope.
Store this in a durable, access-controlled, auditable source. Do not equate a
general communications-consent box with this specific AI voice permission.
Provide withdrawal and suppression procedures. Counsel should review whether
the final mechanism meets applicable federal and state signature requirements.

Critical: the current website lead intake maps a generic `consent` value to
`communications_consent`. It does NOT prove AI calling consent. The existing
website-to-Apollo recovery mirror copies name/email, not phone or AI consent.
Do not auto-populate the AI Voice Consent field from this generic flag.

## JustCall human transfer acceptance test

1. Sign in to JustCall AI Voice Agent and select the actual outbound agent.
2. Set an explicitly staffed human transfer destination; test call routing and
   fallback when no representative accepts.
3. A consenting staff test recipient requests a human. The AI identifies itself
   and warm-transfers without dropping the call.
4. Capture a timestamped JustCall call ID, provider transfer event, final
   agent/user-group destination, human answer, disposition and opt-out test.
5. Only after this evidence exists may an authorized operator set
   `NIJA_JUSTCALL_HUMAN_HANDOFF_VERIFIED=1`.
6. The read-only agent inventory audit in `render_outreach_extension.py` will
   log aggregate setup metadata after successful webhook autoconfig. An action
   listed in metadata is NOT a verified successful human transfer.
7. Keep `NIJA_AUTODIAL_WEEKDAYS_ONLY=1` until legally reviewed, signed
   per-recipient weekend clearances exist and seven-day call handling has
   passed tests.

## Calling launch proof

- Provider JustCall accepted call IDs are counted (not queue scans or quota).
- Prospect records must have proven consent for AI voice calls and valid DNC,
  suppression, timezone, signed jurisdiction, hours and duplicate-call checks.
- Separate human-operated B2B calls from AI consumer outreach.
- The configured maximum is 300/day, NOT a promised minimum.
- As of the October 9 audit, 311 Apollo contacts were reviewed, 0 had evidenced
  AI calling consent, and no compliant automated calls were queued.
- The JustCall browser login / IONOS editing sessions were NOT accessible using
  connected tools. No transfer test or public consent form deployment was made.
