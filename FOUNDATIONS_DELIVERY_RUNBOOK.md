# NIJA Trading Foundations: checkout and protected-delivery runbook

STATUS (verified 2026-11-01): **$99 LIVE Stripe Payment Link is active, not a completed-sale certification.** The production billing API and course portal report healthy/ready; protected files, signing-key presence, and email-provider configuration are reported ready. Stripe confirms the course product/price and verified webhook endpoint. **No successful captured payments exist in the connected live Stripe account, and no real purchase-to-email-to-access flow has been independently certified.** Treat revenue as unverified across providers. The browser-based customer checkout inspection is blocked by an exhausted automation wallet. Do not represent checkout flow as fully validated or promise $1 profit per unique visitor.

## Authoritative product and course access

- Stripe live payment link: `plink_1UEtWDI0gfJjTf3E5L0wb3K9` at `https://buy.stripe.com/bJe6oH36x4X1axJdsEc7u02`.
- One-time $99 live price: `price_1U02soI0gfJjTf3EFtISyrYf`; product: `prod_V01AbvtwLMQPkn`.
- The Stripe product is titled **NIJA Trading Foundations**, but the existing Payment Link line-item description is the older **NIJA Trading Discipline Blueprint**. Do not create another price or change the payment link without reconciling `course_fulfillment.py`'s strict product/price/link IDs and testing the entire flow.
- Customer-facing purchase page: `https://nijaaitrading.com/trading-foundations`; course recovery: `https://nija-billing-api.onrender.com/course-portal/`.
- Payment Link after-completion redirect is already set to `https://nija-billing-api.onrender.com/course-portal/thank-you?session_id={CHECKOUT_SESSION_ID}`.
- Private customer bundle: `NIJA_Foundations_Customer_Package.zip` (original manifest 8 assets), stored only in private billing PostgreSQL. Portal `/course-portal/readyz` reports `assets_present=true`; verify SHA-256 before any replacement.
- Actual contents: 12-chapter eBook, workbook, 12-week journal, full MP3 audiobook, video/audio *scripts PDF only*, certificate template, Start Here, and bonus Starter Kit. Never advertise nonexistent finished videos or performance guarantees.
- Live billing Stripe webhook: `https://nija-billing-api.onrender.com/api/billing/webhook` is enabled with required subscription and course checkout events. Another endpoint with the same URL is disabled; do not enable duplicate delivery.
- Course portal `/course-portal/readyz`: `ready=true`, `access_ready=true`, `assets_present=true`, `email_configured=true`, `access_key_configured=true`; `checkout_access_enabled=false` refers to the *separate server-created Checkout flow*, not the active Stripe-hosted Payment Link.
- Access verification is server-side: matching live Session, Payment Link, price/product, paid status, PaymentIntent and Charge, tax, refunds/disputes and private access token. Email is sent via Resend only after provider-confirmed payment.
- No course sale directly grants brokerage authorization or access to real trading.

## Current independent checks

1. Public website sales page, billing `/healthz` and `/readyz`, and `/course-portal/readyz` respond ready.
2. Private paid-asset URLs return 403 anonymously; invalid one-time claims are rejected.
3. The connected live Stripe account has zero captured successful charges, zero refunds, zero disputes, zero payouts in the inspected provider records; the course Payment Link has many open/expired *unpaid* sessions. These facts do not establish zero NIJA earnings through ClickBank, affiliates, merchandise or other processors.
4. `NIJA public course commerce readiness` runs on a daily scheduled GitHub Actions workflow and on relevant PRs. PR #3536 adds isolated *mocked* paid checkout, one-time delivery, private-content, and refund-revocation tests to that schedule. It never creates real Stripe charges or sends real emails.
5. The separately deployed `nija-course-sandbox` responds `/healthz` 200 after warm-up but reports `/course-portal/readyz` `ready=false`, `assets_present=false`, `email_configured=false`; its general `/readyz` responds 503. It is **not certified for real Stripe test-mode payments**. The connected Stripe API account currently grants live mode only; test-mode account permissions and isolated secrets remain unavailable.
6. Email service failure on some IONOS website lead forms (HTTP 521) is a separate flow from the course portal's Resend configuration. Do not infer a successful site lead-notification handoff from course portal readiness.
7. GA4 October traffic denominator remains unverified due to inconsistent total/new user numbers. Google Ads remains PAUSED, and its old primary lead-form event must not substitute for actual saved leads.

## Pending provider-safe release gates

1. Reconnect isolated Stripe **test mode** with test-account permissions and verify that the sandbox references its *own* PostgreSQL DB, test keys, sender, and sandbox origin. Do not copy production secrets or customer records into it; keep `NIJA_COURSE_SANDBOX_MODE=true` and `NIJA_COURSE_SANDBOX_DB_ISOLATED=true` only after independent readback.
2. Complete one synthetic provider test-mode checkout, signed webhook, exact $99 identity/total, entitlement, one email, one-time claim link and private asset retrieval; verify duplicate webhook/no duplicate email and refund/dispute revocation.
3. Confirm mail provider response and actual delivery to a designated operator-controlled inbox, **not a customer or marketing list**, separately from the IONOS lead form mail outage.
4. Inspect live Stripe hosted checkout customer-visible product description and $99 amount, without entering real payment details. Correct a legacy name only through a versioned change that preserves `course_fulfillment.py` identity checks.
5. Review the customer's thank-you and course-access pages with valid paid evidence. Do not display `payment received` from a mere success URL or open checkout session.
6. Reconcile actual bank/Stripe/ClickBank settlements, processing fees, refunds, Google Ads, IONOS, Render, fulfillment, software and taxes for a *closed* reporting period; activate `website_profit_reporting_api.py` only with privately signed evidence and complete provider/cost coverage.
7. Keep Founding 100 as the **free waitlist** until its separate enrollment release and first-verified-trade trial terms are correctly implemented. Do not confuse the $99 one-time course with $50 monthly membership.

## Course service endpoints (existing)

- `GET /course-portal/`: generic email-based recovery (non-enumerating)
- `POST /course-portal/recover`: rate-limited recovery email
- `GET /course-portal/claim`: single-use short-lived token to secure session
- `GET /course-portal/library`: paid authenticated library
- `GET /course-portal/file/<name>`: private protected PDFs, MP3, or ZIP
- `GET /course-portal/thank-you`: verified or pending payment status only
- `GET /course-portal/readyz`: nonsecret readiness flags
- `POST /course-portal/admin/import`: verified private package upload, protected bearer
- `POST /course-portal/admin/retry`: protected mail outbox dispatch
- `GET /course-portal/admin/preview`: dry-run provider history preview
- `POST /course-portal/admin/reconcile`: one authorized historical session

Admin APIs require dedicated secrets and must never reveal customer data to a public client. ClickBank is not wired into the Stripe ledger. Resend accepted status is not inbox-delivered proof. The $1 net profit/unique visitor business target remains **UNVERIFIED** until complete reconciled accounts and a certified visitor denominator are available.
