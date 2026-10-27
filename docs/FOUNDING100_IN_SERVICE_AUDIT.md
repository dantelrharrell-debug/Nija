# NIJA Founding 100 — private in-service read-only certification

This optional diagnostic avoids exposing the production billing Postgres database
to external connection tools. It **does not** repair missing identity bindings,
create/modify subscriptions, certify broker vault security, or activate trading.
It runs only when explicitly opted in on the trusted existing billing service.

The existing certification implementation is
`scripts/founding100_readonly_certification.py`. Its prerequisites are:

- The existing `BILLING_DATABASE_URL` from the isolated billing service, with
  a working internal PostgreSQL connection.
- The existing durable `NIJA_ONBOARDING_DB_PATH`, **already present and
  accessible inside that same trusted execution environment**. If this SQLite
  source is on a different host and not safely available, this audit **must
  fail closed**. Do not copy customer records into a public site, add an
  unreviewed mount, or expose the billing database publicly.
- The pre-existing live `STRIPE_SECRET_KEY` with retrieve/list capability,
  read only for this audit.
- The immutable NIJA member ID and original approved application ID established
  from independent verified application records, **not a person's name**.

After reviewing the PR and validating its synthetic CI, an authorized Render
operator may temporarily set these *private service environment variables* on
the existing `nija-billing-api` service:

```text
NIJA_FOUNDING100_AUDIT_ON_STARTUP=true
NIJA_FOUNDING100_AUDIT_USER_ID=<verified existing NIJA account ID>
NIJA_FOUNDING100_AUDIT_APPLICATION_ID=<verified existing application ID>
```

Do not add passwords, Stripe identifiers, or email addresses to logs or GitHub
workflow inputs. This audit is opt-in by default, starts on service startup in
a daemon thread to avoid blocking the billing API, and prints one masked
`NIJA_FOUNDING100_AUDIT` category record per process. With two Gunicorn
workers, two matching records may appear.

`result=membership_verified` means the authoritative application, registration,
entitlement, and live Stripe chain agree for the same immutable owner.
`result=blocked` means one or more prerequisites were missing, false, or
unavailable. The log includes only named boolean gate results and a fixed
allowlist of diagnostic categories, never source values or raw errors.

**This is not full onboarding certification.** Whether it succeeds or not,
`full_onboarding_certified=false` and `trading_authorized=false`. Before
notifying the member, independently verify a real authenticated dashboard login,
PocketBase owner-bound rules and negative cross-member tests, original
encryption-key custody, and a genuinely ready broker connection API. Merely
setting `NIJA_MEMBER_BROKER_*_VERIFIED=true` is **not evidence**.

After the restricted audit, disable
`NIJA_FOUNDING100_AUDIT_ON_STARTUP` to avoid repeated source reads at each
worker restart. Preserve the customer's existing subscription and billing
collection settings. Do not run Checkout, send mail or activate trading.

Safety tests: `python -m unittest discover -s tests -p 'test_founding100_boot_audit.py' -v`.
