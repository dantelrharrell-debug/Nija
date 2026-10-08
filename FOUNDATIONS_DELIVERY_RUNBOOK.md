# NIJA Foundations: protected delivery runbook

STATUS: GATED — NOT LIVE. Keep the official $99 Stripe checkout inactive until end-to-end verification.

## Assets and price
Stripe course link: plink_1UEtWDI0gfJjTf3E5L0wb3K9.
One-time $99 base price: price_1U02soI0gfJjTf3EFtISyrYf; product: prod_V01AbvtwLMQPkn.
Billing API: https://nija-billing-api.onrender.com.
Private ZIP: NIJA_Foundations_Customer_Package.zip (42.6 MB), stored only in private billing Postgres.
Contents: eBook (12 chapters), workbook, interactive 101-page journal, final MP3, scripts PDF, certificate template, Start Here, bonus Starter Kit.
Scripts are not finished videos; certificate is a template. Do not claim unavailable lessons or videos are included. Do not publish paid assets on public IONOS/GitHub URLs.

## Environment
Retain existing billing Postgres, Stripe and webhook secrets. Configure ONLY on billing-only Render service:
NIJA_COURSE_DELIVERY_ENABLED=false
NIJA_COURSE_SESSION_SECRET=<new random strong key 48+ chars>
NIJA_COURSE_UPLOAD_SECRET=<different random strong key>
NIJA_COURSE_PUBLIC_URL=https://nija-billing-api.onrender.com
RESEND_API_KEY=<domain-restricted sending key>
NIJA_COURSE_SENDER=NIJA AI Trading <support@nijaaitrading.com>

## Activation sequence
1. Approve a safe production window. Merging to main also triggers the unrelated TRADING BOT auto deploy; obtain explicit restart authorization when needed.
2. Merge only after CI and security checks pass. Confirm billing /healthz=200 and that course /course-portal/readyz is initially gated.
3. Upload the exact private ZIP over HTTPS to POST /course-portal/admin/import; multipart name package; Authorization Bearer NIJA_COURSE_UPLOAD_SECRET. Response must confirm eight files and SHA-256 digest.
4. Enable NIJA_COURSE_DELIVERY_ENABLED=true only after assets, secret, sender and authenticated download checks pass. Verify /course-portal/readyz ready=true.
5. Set official Stripe payment link's after-completion redirect to https://nija-billing-api.onrender.com/course-portal/thank-you?session_id={CHECKOUT_SESSION_ID}. Keep duplicate $99 link disabled and $50 Founding 100 unchanged.
6. Test in provider sandbox or against an explicitly authorized already-paid test purchase, not a live customer charge. Verify webhook signature, correct course identity, line item price, tax-inclusive full amount, payment intent/charge status and all refund checks.
7. Confirm a successful payment grants one course entitlement, queues one email, authenticates via one-use secure claim link, serves private PDFs/ZIP and streams MP3. Check browser-two recovery, expiry and form saving.
8. Verify invalid signature, wrong product, unpaid, failed, pending, refunded, disputed, duplicate event and anonymous file request cannot grant or leak content. Retry email failures independently of course access.
9. Review GET /course-portal/admin/preview before any historical reconciliation. POST /course-portal/admin/reconcile with a single verified session ID per request. Do not send bulk messages without review.
10. Correct IONOS sales page provider copy (Stripe versus ClickBank); preserve $99 one-time product. IONOS /course-thank-you must not claim payment received without verification. Link /course-access to the secure portal recovery flow. Do not set ENROLLMENT_OPEN=true until all steps pass.

## Endpoints
GET /course-portal/ — generic email-based recovery.
POST /course-portal/recover — rate-limited, non-enumerating email link.
GET /course-portal/claim — one-time, short-lived access token to secure cookie.
GET /course-portal/library — paid authenticated library.
GET /course-portal/file/<name> — private protected PDFs, MP3 and ZIP.
GET /course-portal/thank-you — verified or pending status only.
GET /course-portal/readyz — nonsecret readiness status.
POST /course-portal/admin/import — verified private package upload.
POST /course-portal/admin/retry — recoverable mail outbox dispatch.
GET /course-portal/admin/preview — history dry run, no email.
POST /course-portal/admin/reconcile — one authorized historical session.
All admin routes require a dedicated secret bearer token.

## Limitations
ClickBank is NOT wired to the Stripe ledger. ClickBank sales must not be marked automatically fulfilled without an authoritative verified ClickBank integration.
Resend accepted status is not inbox delivered status. Confirm delivery with provider evidence and a controlled end-to-end recipient test.
The $99 course has no connection to broker execution permissions. Never unlock trading access from this purchase.
