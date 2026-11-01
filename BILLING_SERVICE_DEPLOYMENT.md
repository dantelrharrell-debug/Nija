# NIJA Standalone Billing Service Deployment

## Scope

The production billing process is intentionally separate from the NIJA trading
runtime.  Deploy `billing_service:app` as its own HTTPS web service with its own
durable PostgreSQL database.  Do not use the trading process, `users.db`, or
broker execution state as the billing system of record.

The service grants no broker execution authority.  Trading safety and protected
entry/exit gates remain independent.

## Founding 100 transactional onboarding (release gated)

The standalone service can host the Founding 100 outbox independently of Stripe
webhook processing. **This is not evidence of a live rollout.** Issue #3081 must
remain open until the upstream approved-member hookup, security review, current
CI, deployment, staging and real-recipient acceptance evidence are recorded.
Email acceptance/delivery never activates a member or authorizes trading.

### Storage and provider prerequisites

Set server secrets/configuration on the billing host, not in the browser, Zapier
form data, source control, or email:

```text
NIJA_ONBOARDING_DB_PATH=/var/lib/nija-onboarding/outbox.sqlite3
NIJA_ONBOARDING_IDENTITY_SECRET=<dedicated lifecycle/status assertion secret>
NIJA_ONBOARDING_OPERATOR_SECRET=<separate operator assertion secret>
RESEND_API_KEY=<existing transactional provider server credential>
RESEND_ONBOARDING_WEBHOOK_SECRET=<Resend Svix whsec_ signing secret>
NIJA_ONBOARDING_SENDER=support@nijaaitrading.com
NIJA_ONBOARDING_DOMAIN_VERIFIED=true
NIJA_ONBOARDING_SEND_MODE=disabled
NIJA_ONBOARDING_TEST_RECIPIENTS=<controlled verified recipient only>
```

Mount `/var/lib/nija-onboarding` on a **durable local volume**, readable/writable
only by the service account. The outbox contains personal email data: restrict
access, encrypt the volume/backups, and apply the customer-data retention policy.
Back up and restore the SQLite database consistently; never run with an ephemeral
container filesystem. All web/worker processes must use the **same database
file on one host** (no separate per-service volumes or network-filesystem SQLite).
If the host cannot share a local volume between processes, use the scheduled
authenticated work endpoint on that web service instead of a separate worker
service. Horizontal/multi-host deployment needs a shared-SQL outbox migration
first. The absolute path is mandatory; no configured path means no onboarding
routes. Startup serializes schema migration and preserves old invitations.

Verify SPF, DKIM and DMARC for `nijaaitrading.com` and Resend domain verification
before setting `NIJA_ONBOARDING_DOMAIN_VERIFIED=true`; this flag is an operator
attestation, not an automated DNS test. Sender is restricted to that domain.
Register the deployed HTTPS `/api/onboarding/resend/webhook` in Resend for
`email.sent`, `email.delivered`, `email.bounced`, `email.complained`, `email.failed`
and `email.delivery_delayed`. The route verifies raw-body Svix v1 signatures,
timestamp tolerance (300 seconds) and accepts key-rotation signature lists.
Never proxy/re-encode the signed JSON body. Synchronize the host clock.

### Authoritative lifecycle hookup

The approved application/identity server must call `POST /api/onboarding/events`
**after committing** its authoritative state. Use a durable upstream event
dispatcher and retry until HTTP 202; the outbox atomically saves the identity
binding and event-specific mail. This repository does not establish approval or
email ownership from Stripe, Gmail, a browser form, or Zapier. Deploying the
receiver alone does not complete this upstream integration.

Use a short-lived (at most 300 seconds) HS256 bearer assertion signed with
`NIJA_ONBOARDING_IDENTITY_SECRET`, with:

```text
iss=nija-identity
aud=nija-onboarding-events
sub=<immutable NIJA owner ID, same owner as the existing billing ledger>
application_id=<immutable approved-application ID>
email=<canonical identity-provider verified email>
email_verified=true
event_type=application.received | enrollment.approved | identity.registered
approved=true  (required for enrollment.approved)
iat=<now>
exp=<now + at most 300 seconds>
```

Only the identity server holding independent approval and mailbox-verification
proof may mint these assertions. Do not share that signing secret with Zapier or
the browser. JSON body flags are ignored. Unverified receipt addresses are not
mailed: persist them upstream and emit the receipt only after ownership proof.
Approval queues a separate invitation; registration updates identity state only.
Stable application + event keys survive Stripe replays, Zapier retries, repeated
approval assertions and process restarts. Email/owner changes fail closed for
manual verified reconciliation; a resend cannot retarget an existing event.

`GET /api/onboarding/status` requires a separate assertion audience
`nija-onboarding-status` for the authenticated owner's `sub`. Proxy this from
the authenticated member server; never mint a status assertion from a submitted
email. It reports `queued`, `accepted`, `delivered`, or `failed` per message
(`suppressed` is separately identified), plus approval, registration and
entitlement-link status. Billing is read only by immutable owner ID. A checkout
email difference returns `identity_reconciliation_required`, not a new checkout
or an email-based subscription attachment. Establish proof of both identities
in the authoritative identity/billing system before reconciling; this mail API
cannot perform that reconciliation. Existing trials, subscriptions and dates
are not changed. `broker_connection_ready` and `member_activated` remain false
with `requires_independent_authenticated_readiness` until a separately tested
authoritative readiness integration exists. Do not treat them as mail statuses.
The templates offer register/login and official brokerage choices, no checkout,
and prohibit emailing secrets or entering keys before production-tested secure
credential intake. This change does not enable credential intake.

### Durable worker, alerts and recovery

On the same host/volume, supervise and automatically restart:

```text
flask --app billing_service onboarding-worker
```

It processes bounded batches every 30 seconds; `--once` runs one batch. Alternatively
schedule `POST /api/onboarding/operator/work` every 30 seconds from an external
supervisor. Both paths enforce `disabled` (default), `controlled` (only explicit
test recipients), or `enabled` send mode and verified sender/provider prerequisites.
Do not start the continuous worker in disabled mode. A persistent queue without
a supervised worker/scheduler and external monitoring is **not production ready**.

Operator endpoints require HS256 assertions with `iss=nija-identity`,
`aud=nija-onboarding-operator`, operator `sub`, `scope=onboarding:operate`,
`iat`, and `exp` at most 300 seconds later, using the separate operator secret.
Monitor authenticated `GET /api/onboarding/operator/alerts` every minute from
outside the worker host; **page on HTTP 503, missing response, or authentication
failure**. It returns durable dead-letter/bounce/complaint/delay alerts and creates
an alert if queued or accepted mail has no delivery proof after one hour. Route
`nija.onboarding` error logs to the on-call destination too. Verify an actual
page is received, not merely that the API returns JSON.

Transient network/408/429 errors retry with exponential backoff; permanent 4xx
or eight failed attempts dead-letter. Resend acceptance is not delivery.
Webhooks arriving before the send response are persisted for reconciliation;
bounces/complaints suppress the address across all current and future events
and can never be overwritten by delivered events.

After fixing a transient configuration/provider problem, an operator may
`POST /api/onboarding/operator/redrive` with JSON `{"key":"<alert message key>"}`.
Re-drive retains the identical provider key/payload and never clears a
suppressed address. Resend's idempotency retention is 24 hours: at 23 hours from
the first attempt, ambiguous sends fail closed with `reconcile_before_redrive`.
Legacy in-flight/retry rows without first-attempt proof also fail closed.
For these cases, inspect Resend's records by the message key and recover delivery
evidence through signed events; do not delete/requeue rows or mint a fresh event
to force a resend. Cases lacking provider proof require a separately audited
manual reconciliation, not an automatic retry. Keep the alert open until resolved.

### Required acceptance evidence (not yet performed here)

Repository-only validation checkpoint (2026-10-16): 82 targeted onboarding and
existing billing regression tests passed, Python syntax/whitespace checks passed,
secret scans were clean, and the actual Flask worker CLI/route registration
passed an isolated smoke test. A dedicated read-only static security review found
no vulnerabilities in scope. The parallel validator's automated code-review
binary was unavailable; its Python CodeQL analysis was skipped because the
database was too large (zero reported alerts is **not** a completed scan).
GitHub workflows for this PR require approval (`action_required`, no jobs in the
onboarding run). No external send, deployment or recipient acceptance was performed.
These limitations remain release blockers, not passing production evidence.

1. Record approved-member source owner, durable upstream dispatcher and immutable
   owner mapping; confirm an actual approved+verified event reaches the receiver.
2. Record security review and current-head CI URLs. Local mocked tests and the
   historical #3082 CI checkpoint are not deployment or delivery evidence.
3. In staging, use `controlled` mode and record event/message/provider IDs.
   Exercise sign-up, registered member, mismatched checkout email, replay,
   outage/backoff/crashed lease, bounce/complaint, stale/invalid signatures,
   missing-delivery page and safe operator re-drive. Verify no trial, billing,
   checkout, broker credentials or trading state changed.
4. Deploy the durable store, signed webhook, supervisor and external alert monitor.
   Record release SHA, host/volume/backup evidence, verified domain and alert page.
5. In production `controlled` mode, send to a consenting verified recipient.
   Record signed `email.delivered` plus the recipient's actual inbox confirmation,
   correct register/login links, authenticated registration and owner-bound
   entitlement linkage separately. Test email mismatch with verified identity
   proof without creating another subscription. Do not include personal addresses,
   assertion tokens or secrets in public acceptance records.
6. Only after those gates pass, authorize `enabled` mode. Record rollback to
   `disabled` and verify it stops submissions without discarding queued records.
   Do not close #3081 or claim activation/live readiness while any gate is pending.

## Required runtime

Start command:

```text
gunicorn --workers 2 --threads 4 --timeout 60 billing_service:app
```

Health endpoint:

```text
GET /healthz
```

Production must return HTTP 200 with:

```json
{"service":"nija-billing","status":"ok"}
```

## Required environment variables

Secrets must be set in the hosting platform, never committed.

```text
BILLING_DATABASE_URL=<durable PostgreSQL connection URL>
STRIPE_SECRET_KEY=<live Stripe restricted/secret key with required Checkout read/write>
STRIPE_WEBHOOK_SECRET=<set only after the deployed HTTPS webhook endpoint is registered>
NIJA_BILLING_IDENTITY_SECRET=<shared server-side identity assertion secret>

NIJA_PUBLIC_SITE_URL=https://nijaaitrading.com
NIJA_BILLING_ALLOWED_ORIGINS=https://nijaaitrading.com,https://www.nijaaitrading.com

STRIPE_PRICE_FOUNDING_BETA=<expected recurring Price ID>
STRIPE_PRODUCT_FOUNDING_BETA=<expected Product ID>
STRIPE_PRICE_STANDARD_BETA_LEGACY_75=<legacy $75 recurring Price ID; required only while a locked legacy assignment exists>
STRIPE_PRICE_STANDARD_BETA_V2_99=<current $99 recurring Price ID>
STRIPE_PRODUCT_STANDARD_BETA=<expected Product ID>

STRIPE_CHECKOUT_SUCCESS_URL=https://nijaaitrading.com/beta-success?session_id={CHECKOUT_SESSION_ID}
STRIPE_CHECKOUT_CANCEL_URL=https://nijaaitrading.com/apply
```

### Render staging database binding and recovery (#3530)

`BILLING_DATABASE_URL` must be a connection URL, not a database name such as
`nija_billing_staging_db`. Use the existing staging database's exact Render
**Internal Database URL**, with a supported `postgresql://` or
`postgresql+psycopg2://` scheme. Do not construct a URL from the database name,
paste credentials into GitHub/chat/logs, or fall back to ephemeral SQLite.

For the existing resources, perform this repair only in the authenticated
Render dashboard:

1. Open staging PostgreSQL resource `dpg-dbhtsmqjnfac73cbblmg-a`
   (`nija-billing-staging-db`) and its connection settings. Keep the private
   network and empty external IP allowlist unchanged.
2. Open **Environment** on staging web service `srv-dasmtjfpn0mc73948r10`
   (`nija-billing-api-staging`). Check its effective `BILLING_DATABASE_URL`,
   including linked environment-group overrides. Replace only that binding with
   the staging resource's exact Internal Database URL, then Save/Deploy.
   Preserve other settings and all existing data; do not edit a shared group
   in a way that changes production. A first-class Render database reference
   must resolve `property: connectionString`, not the database name.
3. Verify the resulting deployment builds, starts, and becomes `live`. Inspect
   authenticated startup logs for successful initialization and absence of the
   prior SQLAlchemy URL parsing exception. Resolve the active deployment's full
   source SHA in Render; a health response does not identify a commit.

Do not add a replacement staging database/service to `render.yaml` as a repair:
the existing staging resources are not declared there. Production already uses
`fromDatabase` with `property: connectionString`; leave that binding and its
`autoDeployTrigger: checksPass` unchanged. Do not manually trigger production or
bypass CI.

Before closing, an authorized operator must independently attest the binding:

- Use an internal restricted SQL session connected through the **staging
  process's effective URL**, not merely a console opened on the intended DB.
  Do not import the billing app to obtain it (app startup initializes schema),
  print the URL, or enable shell/SQL connection-string tracing.
- Run only read-only checks, for example:

  ```sql
  BEGIN READ ONLY;
  SELECT current_database();
  SELECT to_regclass('billing_customers') IS NOT NULL AS billing_schema_present;
  ROLLBACK;
  ```

- Confirm `current_database()` is `nija_billing_staging_db` and privately match
  the connection host/resource to `dpg-dbhtsmqjnfac73cbblmg-a`. Independently
  compare with production's effective binding using the same restricted method;
  names alone do not prove different resources. Record only a redacted
  separation attestation, not credentials, customer rows, or private hosts.
- Check staging and production `GET /healthz` for HTTP 200 and the documented
  JSON response. On staging, check `GET /api/admin/website-profit?period=2026-10`
  without authorization and with an invalid bearer token: configured reporting
  must return 401 without financial data. A 503
  `profit_reporting_not_configured` is fail-closed but is **not** successful
  configured reporting acceptance. An authorized operator should separately
  make an authenticated read-only GET using the existing dashboard credential
  without exposing it. Missing reconciliation evidence must remain `unverified`;
  never generate or sign financial evidence to make the smoke test pass.
- Do not create checkouts/payments, change memberships, send leads, or change
  trading controls. Record UTC timestamps, redacted Render startup logs/event
  IDs, live deployment ID/SHA, HTTP statuses, and database separation attestation.

The issue's 2026-11-01 12:12 UTC operator report records staging deployment
`dep-dbjionh42hec73d4uesg` and production deployment `dep-dbjckenavr4c73bufo3g`
as live on `a8c1cc634521b5d9af1ea2d24bc99df2bd061c3c`, with healthy endpoints.
This is reported startup recovery, **not independently verified database identity**.
Keep #3530 open until binding/separation and reporting acceptance are recorded.
Consent, provider payouts, CRM comparison, and October expense completeness
remain separate certification gates.

The identity assertion used by `POST /api/billing/checkout` must be minted
server-side and include immutable claims:

```text
iss=nija-identity
aud=nija-billing
sub=<NIJA application/user ID>
email=<authoritative customer email>
offer_code=<immutable NIJA offer assignment>
iat=<issued-at>
exp=<short expiration>
```

Browser-controlled user IDs, emails, prices, products, and offer codes are not
billing authority.

Do not point both standard-beta environment variables at the same Stripe Price. The legacy `standard_beta` code and current `standard_beta_v2` code are intentionally distinct so an old locked $75 assignment cannot be silently charged $99.

## Stripe webhook order

The IONOS route
`https://nijaaitrading.com/.sfs-be/api/webhooks/stripe` now exists and its
local hook tests may pass, but it is **not** the standalone billing authority.
A bare HTTP 400 only proves the route is reachable and rejects the request; it
does not prove a valid Stripe signature, immutable NIJA identity, expected
Price/Product, durable idempotency, or entitlement lifecycle are working
end-to-end.

Do not register that IONOS route as NIJA's authoritative Stripe entitlement
webhook while the standalone service contract below is in force.  If the IONOS
hook remains registered for legacy telemetry, it must not independently grant
membership, emit `customer.paid`, activate a Verified Member badge, or unlock
broker access.

Deployment order:

1. Create the durable PostgreSQL database.
2. Deploy the standalone billing web service.
3. Configure all required environment variables except the webhook secret.
4. Confirm `GET /healthz` is HTTP 200.
5. Confirm `POST /api/billing/webhook` with no `Stripe-Signature` returns HTTP 400.
6. Register the **actual deployed HTTPS URL** ending in `/api/billing/webhook` in Stripe.
7. Subscribe to:
   - `checkout.session.completed`
   - `checkout.session.async_payment_succeeded`
   - `checkout.session.async_payment_failed`
   - `checkout.session.expired`
   - `customer.subscription.created`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
   - `invoice.paid`
   - `invoice.payment_succeeded`
   - `invoice.payment_failed`
8. Set the resulting `STRIPE_WEBHOOK_SECRET` on the billing service and redeploy/restart.
9. Send a Stripe test event and confirm a 2xx response only for a valid signature.

## Entitlement contract

Checkout creation is server-side only.  NIJA writes the immutable application/user
ID to both `client_reference_id` and metadata.  The backend also pins the
expected Stripe Price ID and Product ID.

A Checkout Session does **not** grant membership by itself.  The success page
stays pending until:

- the Checkout Session was created by NIJA's billing service;
- the signed webhook was accepted;
- customer identity matches the server-issued NIJA identity;
- `client_reference_id`, metadata, Price ID, Product ID, and quantity match;
- Stripe reports the subscription in an authoritative entitled state.

Generic Stripe Payment Links do not create membership entitlement because their
Checkout Session IDs are absent from the NIJA-created session ledger.

Payment failure, cancellation, expiry, unpaid/past-due state, deleted customer,
or any identity/price/product mismatch keeps or moves entitlement to revoked.

## Bitcoin / BitPay rail

Bitcoin checkout is implemented as a second payment rail on the standalone
billing service. It does not route customer funds directly to a broker and it
does not grant broker execution authority.

The rail is disabled by default. Configure these values on the billing service:

```text
NIJA_BITCOIN_PAYMENTS_ENABLED=false
NIJA_BITCOIN_ENABLED_OFFERS=lessons
NIJA_BITCOIN_ALLOW_RECURRING_ONE_TIME_PAYMENTS=false
NIJA_BITCOIN_TRANSACTION_SPEED=medium
BITPAY_API_BASE_URL=https://bitpay.com
BITPAY_POS_TOKEN=<server-side BitPay POS token>
NIJA_BILLING_PUBLIC_URL=https://<actual deployed billing-service host>
```

Activation order:

1. Complete the BitPay business/merchant setup and obtain the POS token.
2. Set `BITPAY_POS_TOKEN` only on the billing service.
3. Set `NIJA_BILLING_PUBLIC_URL` to the billing service's actual public HTTPS
   origin. Do not point this at the old IONOS webhook path.
4. Keep `NIJA_BITCOIN_ENABLED_OFFERS=lessons` while recurring Bitcoin
   entitlement/renewal policy remains undefined.
5. Deploy and confirm `GET /healthz` returns HTTP 200.
6. Test `POST /api/billing/bitcoin/checkout` with a valid NIJA billing identity.
7. Confirm the returned provider invoice is forced to BTC and that the
   notification URL ends in `/api/billing/bitcoin/webhook`.
8. Confirm a forged IPN claiming `complete` cannot verify a payment when the
   provider retrieval still reports `new` or `paid`.
9. Confirm an authoritative `confirmed` or `complete` invoice becomes
   `payment_verified=true` through
   `GET /api/billing/bitcoin/verify?invoice_id=<BITPAY_INVOICE_ID>`.
10. Only after those checks pass, set `NIJA_BITCOIN_PAYMENTS_ENABLED=true`.

BitPay invoice notifications are **not** treated as payment authority. The
notification only supplies an invoice ID; NIJA retrieves the invoice from
BitPay using the server-side token and re-validates invoice ID, NIJA order ID,
USD price, currency, and provider status before advancing state.

A `paid` BitPay invoice remains pending. `confirmed` or `complete` may mark
the payment verified. Price/order/currency mismatches fail closed.

Bitcoin payment verification currently does **not** grant Stripe subscription
entitlement. Recurring NIJA offers therefore remain disabled for Bitcoin until
NIJA adopts an explicit manual-renewal entitlement policy. The one-time
`lessons` offer is the initial allowlisted offer.

Treasury state is intentionally separate:

```text
customer BTC
  -> BitPay invoice
  -> authoritative reconciliation
  -> NIJA merchant/treasury settlement
  -> accounting/reserve review
  -> separately approved brokerage funding
```

The billing service never stores brokerage deposit addresses, never sends
Bitcoin to a broker, and always returns `brokerage_sweep_allowed=false`.
Automated brokerage funding must be implemented as a separate treasury service
after settlement-to-NIJA is independently verified.

## IONOS success-page wiring

After IONOS site-builder source/admin access is available, `/beta-success` must
read the `session_id` query parameter and poll:

```text
GET https://<billing-service-host>/api/billing/verify?session_id=<CHECKOUT_SESSION_ID>
```

Only a response with:

```json
{"state":"verified","verified":true,"entitled":true}
```

may unlock the Verified Member badge or emit downstream conversion/customer
signals.

While the result is `pending`, the page must show pending verification.  For
`revoked`, `mismatch`, or failed verification, it must not emit GA4 checkout
completion, Zapier `customer.paid`, a paid badge, or broker access.

## Course Payment Link

The one-time $99 course remains independent from membership entitlement.  Its
price must not be changed.  Its active Payment Link must redirect to:

```text
https://nijaaitrading.com/course-thank-you
```

The course link must never be treated as proof of a NIJA subscription.
