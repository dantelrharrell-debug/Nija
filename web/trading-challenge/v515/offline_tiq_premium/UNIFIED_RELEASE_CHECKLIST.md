# Unified Trading IQ + $1 results — release checklist (preview only, nothing published)

Product: one experience. Free 12-round game; eligible adults (18+ self-declared) see personal results locked behind one disclosed $1 payment, inside the game.

## Done (offline, mocked, passing)
- Server rules: adult confirmation, checkout planning, webhook signature + duplicate events, refunds/disputes, ownership credential, report access (127 + 71 + 69 checks).
- Analytics rules: admin-only (401/403), duplicate-safe events, UNVERIFIED when evidence missing (40 checks).
- Age rules: ages 5-12 no promotions; 13-17 free only, no payment offers (90 checks).

## Blocked on external approvals
1. IONOS protected storage: 4 areas (STORAGE_APPROVAL_REQUEST_6B.md) + events area (STORAGE_APPROVAL_REQUEST_9B.md). Not submitted.
2. Owner sets in server settings: Stripe TEST secret key, webhook signing secret, ownership key (32+ random chars).
3. Server routes for checkout, webhook, results unlock: need a backend restart after Publish; cannot be hot-loaded or tested end-to-end here.
4. Real-browser tests at 375/768/1280: no browser available here -> UNVERIFIED.
5. Owner decisions: payment-record retention, reopening purchased results, legal review of age wording.

## Release gate (all must pass before the owner publishes)
Stripe TEST purchase end-to-end; webhook verified; refund revokes access; no double charge; client-claimed scores and redirects never unlock; browser tests pass; dashboard shows verified purchases only.
