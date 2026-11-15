# Trading IQ Challenge — Upgrade 5D: Storage Design (for owner review)

Status: DESIGN ONLY. No schema change has been applied. Preview only.
Nothing here is live. Payments stay disabled. No production data is touched.
Any protected schema change must go through IONOS's approval process first.

## 1. Scope

Stores only what the $1 optional personalised report needs:
server-issued runs, validated decisions, server-calculated scores, checkout
attempts, verified payments, report entitlements, and refund/dispute status.
Basic free play and guest progress stay in the visitor's browser (unchanged).

Out of scope (must not change): existing customer records, course purchases
(entitlement records), Academy records, trading accounts, production payment
settings, Zapier routes, lead intake stores.

## 2. Proposed new tables (all new, all empty on creation)

Preview-only names are prefixed `tiq_` so they cannot collide with any
existing store.

### 2.1 `tiq_runs`
| Field | Type | Notes |
|---|---|---|
| id | text, server-generated 128-bit random | primary key; never derived from user input |
| owner_hash | text | SHA-256 of the ownership credential (credential itself never stored) |
| mode | text | `standard` or `daily` |
| level | text | `beginner` / `intermediate` / `advanced` |
| day_num | number, nullable | UTC day number; null for standard |
| challenge_version | text | engine version string, e.g. `tiq-engine-1` |
| decisions_json | text, bounded (max 6 challenges × 12 rounds) | validated by the engine's `validateRun` before save |
| score_json | text | server-calculated via `replayRun` only |
| total_score | number | server-calculated |
| status | text | `open` / `completed` / `expired` |
| created_at, completed_at, expires_at | datetime | expires_at set at creation |

Indexes: unique(id); index(status, expires_at) for cleanup; index(owner_hash).

### 2.2 `tiq_checkouts`
| Field | Type | Notes |
|---|---|---|
| id | text, server-generated | primary key |
| run_id | relation → tiq_runs.id | one run may have at most one active checkout |
| owner_hash | text | copied from run; checked on every request |
| stripe_session_id | text | stored for reconciliation only; never an access credential |
| idempotency_key | text | deterministic per run (e.g. `tiq-report-<run_id>`) |
| status | text | `created` / `paid` / `expired` / `canceled` / `failed` |
| amount_cents | number | must equal 100 |
| currency | text | must equal `usd` |
| livemode | bool | must match server mode setting |
| created_at, updated_at | datetime | |

Indexes: unique(stripe_session_id); unique(run_id) WHERE status IN ('created','paid');
index(status, created_at).

### 2.3 `tiq_payments` (verified payments only)
| Field | Type | Notes |
|---|---|---|
| id | text | primary key |
| checkout_id | relation → tiq_checkouts.id | |
| payment_intent_id | text | Stripe payment reference |
| stripe_event_id | text | webhook event that verified it |
| status | text | `paid` / `refunded` / `disputed` |
| amount_cents, currency, livemode | number, text, bool | copied from verified Stripe object |
| verified_at, updated_at | datetime | |

Indexes: unique(payment_intent_id); unique(stripe_event_id).

### 2.4 `tiq_entitlements` (report access)
| Field | Type | Notes |
|---|---|---|
| id | text | primary key |
| run_id | relation → tiq_runs.id | UNIQUE — one report per run |
| payment_id | relation → tiq_payments.id | UNIQUE |
| status | text | `active` / `refunded` / `disputed` / `revoked` |
| report_hash | text | hash of the report contents, for integrity |
| created_at, status_changed_at | datetime | |

Indexes: unique(run_id); unique(payment_id).

No email address, name, card detail or IP address is stored in any tiq_ table.
Buyer contact details remain only inside Stripe.

## 3. Access-control rules

- All four tables: **no public list, view, create, update or delete.** Only the
  server routes (running with server privileges) read or write them.
- Admin: read-only view for support, with owner_hash and any Stripe reference
  masked. No admin delete.
- Report access requires BOTH the run id AND the ownership credential, and the
  entitlement status must be `active`. A Stripe session id alone never opens a
  report.
- Ownership credential: issued by the server when a run completes; 256-bit
  random; stored in the visitor's browser only; server keeps the hash only.
  Lost credential = no report access (support can re-issue after identity check).
- Browser never sends a score or a payment status. The server recalculates
  everything from the validated decisions.

## 4. Retention and deletion

| Data | Keep for | Then |
|---|---|---|
| Open runs never completed | 30 days | deleted |
| Completed runs with no checkout | 90 days | deleted |
| Checkouts `created`/`expired`/`canceled`/`failed` | 30 days | deleted |
| Paid runs and entitlements | while the report is offered, plus accounting period (owner to confirm length) | deleted on request or after period |
| Refund/dispute records | accounting period (owner to confirm) | deleted after period |

Deletion request: owner removes the run, checkout and entitlement by run id.
A scheduled cleanup job is NOT used (scheduled jobs are disabled in this
environment). Cleanup is a manual, owner-triggered admin action in preview.

## 5. Duplicate-payment prevention

1. Checkout creation is idempotent per run: one run = at most one open checkout.
   The provider idempotency key is derived from the run id.
2. `tiq_payments.payment_intent_id` and `stripe_event_id` are unique, so a
   repeated webhook delivery cannot create a second payment.
3. `tiq_entitlements.run_id` is unique, so one run can unlock at most one report.
4. Webhook handling is idempotent: a repeated event returns success without
   writing again.
5. Verification requires: signed webhook, status `paid`, amount 100, currency
   usd, livemode matching the server's mode setting, and a checkout that
   belongs to the run.

## 6. Payment states

- `paid` → entitlement `active` → report unlocks.
- `canceled` / `expired` / `failed` → checkout closed; no entitlement; run stays free.
- `refunded` / `disputed` → entitlement moved to that status; report access is
  blocked on the next request.
- Browser-side "success" screens never unlock anything.

## 7. Migration and rollback

Migration (after approval only):
1. Export a backup of the current preview store and record its checksum.
2. Create the four empty `tiq_` tables with the exact fields and indexes above.
3. Verify each table exists, fields match, indexes match, and rules deny public access.
4. Verify existing tables are unchanged (field count, rules, record counts).

Rollback:
- Turn off the game's premium routes (flag, no data change).
- Leave the four empty or low-volume tables in place; they are isolated and unused.
- Only if owner confirms zero paid rows: remove the four `tiq_` tables.
- Restore from the step-1 backup if any existing table was touched (should not happen).

## 8. Required server environment settings (names only, never values in chat or code)

| Name | Purpose | Current state |
|---|---|---|
| `STRIPE_TEST_SECRET_KEY` | server-side test key | NOT SET — owner to configure in the server environment |
| `STRIPE_TEST_WEBHOOK_SECRET` | verifies webhook signatures | NOT SET |
| `TIQ_STRIPE_MODE` | `test` or `live` | must be `test` until owner approves |
| `TIQ_PRICE_CENTS` | must equal `100` | to set |
| `TIQ_ALLOWED_ORIGIN` | origin check for requests | to set |
| `TIQ_PAYMENTS_ENABLED` | master switch | `false` |

Secret keys are never stored in the database, source code, logs, or browser.

## 9. Test coverage planned (offline, mocked provider, in-memory fixtures)

- Tampered decisions rejected; browser-sent score ignored.
- Duplicate checkout creation returns the same checkout.
- Repeated webhook delivery writes nothing new.
- Failed / canceled / expired checkouts never unlock a report.
- Refund and dispute move access off.
- Wrong run id, wrong owner credential, or session id alone → refused.
- Currency, amount and livemode mismatches → refused.
- Existing suites stay green: progress 44/0, game integration 43/0, engine parity 391/0.

## 10. Remaining approvals and configuration (owner)

1. Review and approve this design.
2. Submit the protected schema change through IONOS's approval process.
3. Set the Stripe TEST secret and webhook secret in the server environment (never in chat).
4. Confirm record-retention periods for paid records with your accountant.

Until these are complete: no real payments, no report purchases, no publish.
End-to-end Stripe test purchase: UNVERIFIED.
Browser and mobile checks: UNVERIFIED.
