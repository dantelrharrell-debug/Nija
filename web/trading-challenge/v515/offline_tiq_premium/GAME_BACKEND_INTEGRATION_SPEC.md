# Trading IQ Challenge — Game Backend Integration Spec

**STATUS: SPECIFICATION ONLY. NOT IMPLEMENTED.** Nothing in this document exists in code, in storage, or on any server.
The in-site game (`/trading-iq-challenge`) is frontend-only: no decision, score, progress, analytics event or payment is sent anywhere.
Written 9 Nov 2026 for owner review. Nothing here may be built, deployed or linked without separate owner approval.

## 0. Ground rules

1. **Separate backend.** Not the website's existing database, hooks or Stripe webhook. Not the trading service. No shared secrets.
2. **Secrets only server-side.** Stripe secret key, webhook signing secret, HMAC/entitlement keys, admin credentials never reach the browser, source control, logs or analytics.
3. **Verified revenue and provisional figures are always separate.** Only a server-verified, live-mode, non-test, non-refunded, positive payment counts as revenue. Everything else is labelled PROVISIONAL or UNVERIFIED and is never added to the verified total.
4. **Admin-only reporting.** Aggregates and records are readable only by authenticated admins (server-checked role). No public leaderboard, no public analytics endpoint.
5. **Age safety.** Under-18 players never see paid offers and never reach checkout. Lesson links in coach notes stay adult-program only.
6. **Scores are recomputed server-side** from submitted decisions by the same engine (`tiq_engine.mjs` / `tiq_report.mjs`). Browser-sent scores are ignored.
7. **No claims of results.** Nothing stored or shown implies real returns. Prices and money are fictional.

## 1. Domain and deployment (verify before any link)

- Target address: `game.nijaaitrading.com`. **Not verified.** As of the last check it did not resolve (no DNS record).
- Before the website links to it, an authorised person must verify, and record dated evidence of:
  1. DNS record exists and resolves from at least two independent resolvers.
  2. Valid HTTPS certificate for exactly that hostname (no warnings; HSTS optional).
  3. The deployed build matches the reviewed release (version/hash shown on a health route).
  4. Health route returns OK; every protected route returns 401/403 without credentials.
  5. CORS allows only the website origins listed in section 10; no wildcard.
- Until all five pass, the website keeps linking only to the existing in-site game route. The current five-round Vercel game stays untouched.

## 2. Daily challenges

- Server publishes a **daily set** keyed by UTC day number (same rotation as `dailyList(dayNum)`), signed so clients cannot choose their own day.
- `GET /daily` → `{ day, scenarios[6], engine_version }` (public, cacheable, no personal data).
- Client plays locally, then `POST /runs/:id/submit` with decisions only; server replays and returns authoritative scores.
- One XP-eligible daily result per player per day; repeats are practice only (matches current in-site rule).
- Server rejects days more than ±1 from server UTC date.

## 3. Progress storage

- Optional and opt-in. Guest play continues to work with no account and no server storage.
- If a player signs in: store only XP, rank, badge IDs, streak, last daily day, completed-run summaries (scores, scorecard areas). **No decision logs retained beyond the report window** (see retention).
- No birthdates, no home address, no school name. Age eligibility is an attestation flag + version + time (section 7).
- Player can export and delete their data; deletion removes progress and unlinks analytics within 30 days.
- Guest progress already in the browser is never uploaded silently; import requires an explicit button.

## 4. Classroom mode (educators)

- Educator creates a class with a join code; no student personal data required (nickname only, no email for under-18s).
- Educator sees only aggregate class results: completion count, average scorecard areas, common coach focus points. No individual under-18 data without guardian consent.
- Class runs are free, never show paid offers, never link outside adult-only Academy rules (under-18 classes get no lesson links).
- Educator accounts require approval; join codes expire; classes can be closed and deleted by the educator.

## 5. Consented analytics

Events (only after the visitor accepts analytics; Do Not Track is respected; no email, no IP stored — salted hash at most, rotated):

| Event | Notes |
|---|---|
| `visit` | once per session |
| `run_started` | run id, mode, level |
| `round_completed` | run id, challenge index, round |
| `run_completed` | run id, Trading IQ |
| `returning_player` | derived server-side from the pseudonymous id, not a separate cookie |
| `checkout_started` | adults only; session id only |
| `purchase_verified` | emitted by the server from a verified Stripe event, never by the browser |
| `report_delivered` | server-side, after entitlement check |
| `refund_recorded` | server-side from a verified Stripe refund/dispute event |
| `academy_visit` | click-through to an Academy page (adult lessons only for coach links) |

- Browser-emitted events are **UNVERIFIED** and shown as such. `purchase_verified`, `report_delivered` and `refund_recorded` can only be written by server code.
- Minors: no analytics identifiers beyond what is needed to run a classroom; no advertising or marketing use.
- Retention: raw events 13 months, then aggregates only.

## 6. Stripe server-side verification (for the planned $1 adult report)

Checkout is disabled today and stays disabled until the owner approves, in writing, test-mode then live-mode release.

1. **Server creates the Checkout Session** (price ID fixed server-side, one-time, amount 100 cents, client never sends price or amount). Metadata: run id, owner-credential hash, age-declaration version.
2. The age gate runs **before** a session is created (section 7).
3. **Webhook** (signature verified with the signing secret; reject otherwise): handle `checkout.session.completed` and `checkout.session.async_payment_succeeded`; record only when `payment_status = paid`, `livemode = true`, `amount_total = 100`, currency expected, and the session's price/product match the configured IDs.
4. **Idempotent writes:** unique index on Stripe event id and on payment intent id; one transaction writes payment + entitlement; duplicates are no-ops.
5. Test-mode events are stored only in a separate test store and never count as revenue.
6. The browser success page never grants access; it polls the server, which answers from the entitlement record only.
7. Reconciliation job (daily, read-only): lists recent Stripe payments and compares with stored payments; mismatches go to an admin review list, never auto-fixed.

## 7. Age eligibility

- Adult declaration (current text and version in `src/lib/adultDeclaration.js`) is **re-validated on the server** before any checkout session is created (`age_gate_core.mjs`: missing/outdated/text mismatch/extra fields such as a birthdate all rejected).
- Self-declaration is not independently verified age; the spec stores only version + time as evidence.
- Under-18 or undeclared: no paid offer is rendered, no checkout endpoint is reachable (server returns 403 for the flow).
- Parents/guardians: any future youth purchase is out of scope and prohibited by this spec.

## 8. Entitlement recovery

- At purchase the player receives a **report code** (random, shown once, only a hash stored server-side). The report opens only with: active entitlement + matching code hash + matching run id (`tiq_report_access.mjs`).
- Recovery without the code: via the email on the Stripe receipt, a single-use time-limited link sent by the server to that address only; rate-limited; the response never reveals whether an address has a purchase.
- No access is granted from browser storage, URL parameters or a Stripe redirect alone.
- Lost code and no receipt email: manual support review by an admin with evidence; every grant is logged with admin identity and time.

## 9. Refunds and duplicate payments

- A verified refund or dispute event revokes the entitlement immediately (status `revoked`); the report no longer opens; revenue is reduced by the refunded amount in the verified total; the event is idempotent.
- Duplicate payment prevention: one open checkout per run; one entitlement per run; second payment for an already-entitled run is flagged `duplicate_payment` for admin refund review (never silently kept); unique indexes as in section 6.
- Partial refunds are recorded as such and shown as a separate line; entitlement stays unless the full amount is refunded.
- Chargebacks are tracked separately from refunds.

## 10. Security and access

- Admin API requires an authenticated admin account (server-side role check); superuser/integration tokens are separate and never exposed to the browser.
- All storage areas created for this backend have **no public rules**; only server code writes. Public clients talk only to the narrow endpoints above.
- CORS allow-list: `https://nijaaitrading.com`, `https://www.nijaaitrading.com` and `https://game.nijaaitrading.com` only.
- Rate limits on run start/submit, code entry and recovery.
- Logs never contain secrets, report codes, card data or full emails.
- Backups before every schema change; restore tested before release.

## 11. Admin reporting

- Two clearly separated panels:
  - **Verified revenue**: live-mode, webhook-verified, non-refunded payments only; net of refunds and fees entered by an admin.
  - **Provisional / unverified**: browser events, test-mode purchases, pending sessions, unreconciled items. Never summed into verified revenue.
- Funnel: visits → starts → round completion → run completion → checkout started → verified purchase → report delivered → refund. Missing stages display UNVERIFIED, not zero.
- Academy visits shown as click-throughs only (adult lessons only for coach links).

## 12. Release gates (all must pass before any link or checkout)

1. Domain/HTTPS/health verification (section 1) recorded with dates.
2. Test-mode end-to-end purchase, report delivery, refund and duplicate-payment tests pass against the real backend (offline fixtures in this repository do **not** count).
3. Admin-only access tested with a non-admin account (expect 403).
4. Under-18 flow tested: no paid offer, no checkout, no lesson links.
5. Backup + rollback plan agreed.
6. Owner's written approval for each step. Publishing is done by the owner only.

## 13. What exists today (for reference, none of it is this backend)

- Frontend game, scorecard (five areas), deterministic coach, session achievements: in the website preview only.
- Offline fixtures: `tiq_engine.mjs`, `tiq_report.mjs`, `tiq_report_access.mjs`, `age_gate_core.mjs`, `payment_flow_6b.mjs`, `analytics_server_core.mjs`, `storage_spec_6b.mjs` — in-memory tests with mocked Stripe. Not run against a real server.
- **Not implemented:** daily-challenge service, progress storage, classroom mode, analytics ingestion, Stripe server integration, entitlement recovery, refund handling, admin reporting, `game.nijaaitrading.com`.
