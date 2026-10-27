# Founding 100: authorized read-only membership certification

Use \`scripts/founding100_readonly_certification.py\` only inside the existing trusted billing environment, never from a public website. It needs the existing \`BILLING_DATABASE_URL\` (internal Postgres), \`NIJA_ONBOARDING_DB_PATH\` (durable existing SQLite onboarding outbox), and a live read-only-capable \`STRIPE_SECRET_KEY\`. Run with the already trusted NIJA user ID and application ID:

\`\`\`bash
python -B scripts/founding100_readonly_certification.py --user-id '<existing-nija-user-id>' --application-id '<existing-application-id>'
\`\`\`

The script uses read-only transactions and only Stripe retrieve/list calls. It does not instantiate storage constructors, create tables, start Checkout, generate trials, modify an entitlement, send notifications, replace broker credentials, or activate trading. Output contains booleans and fixed-category error labels, not customer emails, tokens, or Stripe identifiers.

It verifies the immutable NIJA owner/application binding and email agreement across onboarding and billing, approved registration, a current ledger entitlement, Stripe live customer verified-email metadata, matching subscription price/product and status, exactly one subscription for that Stripe customer, and the historical generic Payment Link checkout exception. **Stripe trialing alone is never sufficient.** Exit 0 means only the authoritative membership chain passed. Exit 2 means a required record, identity, payment or source check failed or was unavailable.

The script deliberately leaves \`full_onboarding_certified=false\`, \`authenticated_dashboard_verified=false\` and \`secure_broker_onboarding_verified=false\` regardless of membership status. A separate authenticated acceptance check must establish an actual usable NIJA dashboard login, owner-bound member vault permissions, verified key custody and secure broker workflow. Require independent security review and genuine member-broker \`/readyz\` HTTP 200; do not simply flip review flags.

**Production prerequisites:** Confirm that the trusted billing runtime already has the onboarding outbox path and internal database connectivity. If they are not colocated, use a separately approved restricted execution environment; do not expose Postgres publicly or copy customer records to a developer laptop. Existing Stripe subscription/trial billing remains unchanged. No mail or success notification until every member-onboarding criterion is actually verified.

Offline synthetic tests: \`pytest -q tests/test_founding100_readonly_certification.py\`. Neither synthetic tests nor code merge is production certification.
