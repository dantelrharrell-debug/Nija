# Protected Storage Approval Request — Trading IQ Challenge optional $1 report (UPGRADE 6B)

Status: PROPOSAL ONLY. Not submitted. Not applied. No live data touched.
Project: NIJA AI Trading (aibuilder-4dfdf). Test mode only.
Machine-readable spec: `offline_tiq_premium/storage_spec_6b.mjs` (checked by `storage_payment_6b_test.mjs`).

## 1. Purpose

Four new, isolated storage areas for the optional $1 personalised report that follows a free, fictional-data trading game. They are used only by the game and its report. They hold no customer, course, Academy, trading-account or broker data.

## 2. The four areas (all new; nothing existing is altered)

| Area | Holds | Key constraints |
|---|---|---|
| `tiq_runs` | Run id (32 hex), owner hash, level, day, challenge version, validated decisions (capped), server-calculated score, status, expiry | Run id unique. Owner credential stored only as a keyed HMAC. |
| `tiq_checkouts` | Run link, per-attempt idempotency key, test session reference, $1.00 USD, status, minimal age-declaration evidence | Idempotency key unique. Session reference unique. **One open checkout per run** (partial unique). Amount fixed at 100 cents, currency fixed at usd. |
| `tiq_payments` | One row per processed Stripe event; exactly one `grant` row per paid checkout; refund and dispute status; test-mode flag | Event id unique (duplicate deliveries write nothing). Payment reference unique for `grant` rows. Test mode only (`livemode = false`). No card, name, email or customer data. |
| `tiq_entitlements` | Run ownership link, active or revoked, revoke reason, timestamps | One entitlement per run. Revoked rows are kept, never deleted, so a refund cannot be replayed into access. |

### Minimal age-declaration evidence (inside `tiq_checkouts`)
Only three fields: `age_gate_version` (text), `age_evidence_kind` (fixed to `self_attestation`), `age_confirmed_at` (time). No birthdate, identity document, date of birth, age number, name, email or address is collected or stored. This is a self-declaration that the purchaser is 18 or older. **It is not independent age verification.**

## 3. Permissions

- All five access rules on all four collections are **null** (server-side only). Browsers cannot list, view, create, update or delete any record directly.
- Only the server's verified routes and the platform administrator (superuser) can read these areas.
- Ownership credential: a 256-bit random value is shown to the browser once. Only `HMAC-SHA256(credential, server key)` is stored. The server key is a new secret that the owner must supply (see section 7). It is never in code or in chat.

## 4. Indexes and constraints (exact)

1. `tiq_runs` — unique(`run_id`)
2. `tiq_checkouts` — unique(`idempotency_key`)
3. `tiq_checkouts` — unique(`stripe_session_id`) where not empty
4. `tiq_checkouts` — unique(`run_id`) where `status = 'created'` (one open checkout per run)
5. `tiq_checkouts` — index(`run_id`, `status`)
6. `tiq_payments` — unique(`stripe_event_id`)
7. `tiq_payments` — unique(`payment_intent_id`) where `record_kind = 'grant'` and not empty
8. `tiq_entitlements` — unique(`run_id`)
9. `tiq_entitlements` — unique(`payment_intent_id`)
10. `tiq_runs` — index(`status`, `expires_at`)

Index 4 plus the per-attempt Stripe idempotency key prevent duplicate checkout sessions. Indexes 6–7 plus the single-transaction grant prevent duplicate payment processing.

## 5. Retention (owner decision required — section 6)

- Unpaid runs: deleted 90 days after expiry.
- Expired and failed checkout attempts: deleted 90 days after closing.
- Payment event rows and entitlements: kept for the period the owner sets for accounting records. Proposed default: keep, and do not delete without owner sign-off.
- No card or customer details exist to delete.

## 6. Decisions the owner must make

1. Retention period for paid payment and entitlement records (accounting advice may apply).
2. Whether the report is free to re-open after purchase (current design: yes, for the same run only).
3. Confirmation of the age-declaration wording with the business's legal adviser before any live use.

## 7. Required secrets (owner sets in the server environment; never in code or chat)

- `STRIPE_TEST_SECRET_KEY` — test-mode key only (not yet set).
- `STRIPE_WEBHOOK_SECRET` — signing secret for the test-mode webhook endpoint (not yet set).
- `TIQ_OWNER_HMAC_KEY` — new; at least 32 random characters (not yet set).

Existing live Stripe secret names were checked and are not used by this proposal.

## 8. Rollback

1. Before any change: export all four collections (they should be empty or contain test records only).
2. Delete in order: `tiq_entitlements`, `tiq_payments`, `tiq_checkouts`, `tiq_runs`.
3. Confirm no existing NIJA collection changed (compare against a pre-apply snapshot).

Rollback does not touch `nija_payments`, `nija_entitlements`, `nija_applications`, Academy, course or broker records.

## 9. Isolation

- No foreign keys into existing customer, course, Academy, lead or broker collections.
- No existing hook, route or rule is modified by this proposal.
- Existing payment webhooks (course and Founding 100) are not changed. This flow is a separate route.
- Live trading, broker credentials and the vault are out of scope.

## 10. What must NOT happen until approvals are complete

- Creating these collections on the live site.
- Setting live Stripe keys or live-mode webhooks.
- Enabling the checkout route (currently gated off: `checkoutGate` refuses unless storage is approved and test keys are configured).
- Publishing the site.

## 11. Where to submit

Submit as a **protected storage change request** to IONOS support for the NIJA project. Attach this document and `storage_spec_6b.mjs`. Reference: "UPGRADE 6B — optional $1 report storage (test mode, four new isolated areas, additive only)". The exact menu path inside the IONOS platform is confirmed by IONOS; this proposal does not assume one. Existing backend support case: 6a9cf94cfc6297d06dc09d9a (historical, for context only).

## 12. Separate approvals required

| Item | Who | Status |
|---|---|---|
| Protected storage migration (section 2) | IONOS platform approval | NOT SUBMITTED |
| Stripe test-mode key and webhook | Owner, in Stripe dashboard and server settings | NOT SET |
| Server key for ownership hashing | Owner | NOT SET |
| Retention and re-open decisions (section 6) | Owner | OPEN |
| Age-declaration wording review | Owner / legal adviser | OPEN |
| Publishing to the live site | Owner only (Publish button) | NOT REQUESTED |
| Browser checks at 375, 768 and 1280 px | Owner or a browser session | UNVERIFIED |
