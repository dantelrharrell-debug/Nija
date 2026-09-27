# NIJA Standalone Billing Service Deployment

## Scope

The production billing process is intentionally separate from the NIJA trading
runtime.  Deploy `billing_service:app` as its own HTTPS web service with its own
durable PostgreSQL database.  Do not use the trading process, `users.db`, or
broker execution state as the billing system of record.

The service grants no broker execution authority.  Trading safety and protected
entry/exit gates remain independent.

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
STRIPE_PRICE_STANDARD_BETA=<expected recurring Price ID>
STRIPE_PRODUCT_STANDARD_BETA=<expected Product ID>

STRIPE_CHECKOUT_SUCCESS_URL=https://nijaaitrading.com/beta-success?session_id={CHECKOUT_SESSION_ID}
STRIPE_CHECKOUT_CANCEL_URL=https://nijaaitrading.com/apply
```

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

## Stripe webhook order

Do not register the current IONOS
`https://nijaaitrading.com/.sfs-be/api/webhooks/stripe` endpoint.  It is not the
standalone billing service and has previously returned HTTP 404.

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
