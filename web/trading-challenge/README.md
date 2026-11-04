# NIJA Trading IQ Challenge (isolated web MVP)

Six **fictional** market decisions, visual chart scenarios, a virtual-portfolio balance, immediate free feedback, and an optional **$1 one-time personalized educational report**. This is **not** a live or paper-exchange trading engine; there are no brokerage calls, trades, orders, prize payouts, account connections, or financial-performance forecasts.

## Scope and product promise

- Play the entire six-decision challenge free without registration.
- Every selection changes a **fictional** account balance. These outcomes are scripted and are intentionally *not* used to rank skill.
- The full decision score, three-category breakdown, tailored focus area, six coaching notes, and exportable report cost **one US dollar, once**. No subscription, no auto-renewal.
- Scores are **educational**, not investment advice, financial suitability advice, psychometric assessment, real trading performance, or a prediction of returns.
- The purchase is optional. No hidden price, fake countdown, gambling, wagering, or real-money prizes.

The application is self-contained under `web/trading-challenge/`. It neither imports nor changes NIJA's production trading controller, capital gates, kill switch, order routing, broker credentials, or live trading configuration.

## Local run

Requires **Node.js 20+**. No external npm dependencies are required.

```sh
cd web/trading-challenge
npm test
npm start
```

Open http://localhost:8787. Without a Stripe key, gameplay is usable and the checkout endpoint returns a controlled `503`. **Do not** display a purchase button in public marketing or claim that checkout is live until real end-to-end test transactions succeed.

## Live web payment setup

Deploy the **subdirectory** `web/trading-challenge` as its own Vercel project (Root Directory setting); leave the existing NIJA trading app and IONOS project alone. The `public/` directory is static, and `api/*.mjs` expose Vercel serverless endpoints. Alternatively host `npm start` on a separate Node web service.

Set environment variables in the deployment provider's **secret settings**, never in code or GitHub:

| Name | Requirement |
|---|---|
| `STRIPE_SECRET_KEY` | Required for **web** $1 Checkout and result verification; use a test-mode key first |
| `PUBLIC_BASE_URL` | Stable HTTPS origin, e.g. `https://game.nijaaitrading.com`, for production |
| `NODE_ENV` | Set to `production` in production; process fails closed without an HTTPS public URL |
| `PORT` | Optional for the standalone Node server; Vercel ignores it |
| `TRUSTED_PROXY_HOPS` | Optional for a standalone server behind a trusted reverse proxy; set to the exact number of proxies in front of the server |

The temporary Vercel preview hostname can be obtained from `VERCEL_URL` if `PUBLIC_BASE_URL` is not set in preview. Ensure preview and production have separate payment credentials.
Vercel checkout rate limits use its `x-vercel-forwarded-for` client-IP header. Standalone deployments use the socket address unless `TRUSTED_PROXY_HOPS` is set; only enable it when the server is reachable exclusively through the configured trusted proxy chain.

**Release checklist:**

1. Configure and verify the custom domain `game.nijaaitrading.com` on the correct **game project**, not NIJA's trading runtime. Review any existing DNS `game` record before modifying it.
2. Run `npm test` and review the CI result against the **exact PR head**; run accessibility, narrow-screen, iPhone Safari, and Android Chrome device tests.
3. Complete Stripe test-mode purchase (100 cents), return to `/?session_id=...`, verify the report renders, reload and verify again.
4. Confirm tampered or unpaid sessions are rejected; test retry, refunds, canceled Checkout, expired sessions, and payment-provider outage.
5. Complete privacy-policy and age/consent review; the assessment is not intended to solicit paid purchases from children without adult authorization.
6. After approved tests, switch to production Stripe secret, verify production domain, and do a controlled real $1 purchase.
7. Add Stripe event reporting and refund reconciliation to NIJA's **separate** revenue dashboard before claiming verified revenue-per-visitor performance. No revenue integration is claimed in this MVP.

### Payment security model

`POST /api/checkout` accepts only six bounded option indices, computes a one-time Stripe Checkout Session **server-side**, and attaches the choices as Stripe session metadata. It does not accept or store a browser-calculated score. `GET /api/results` retrieves the session from Stripe using a server-side secret, requires `payment_status=paid`, `mode=payment`, `amount_total=100`, `currency=usd`, and the matching game version. Only then is the private coaching report calculated by `server/scoring.mjs`. Static hosting exposes **only** files in `public/`.

This first MVP uses a **bearer-style session URL** for returning purchases; anyone obtaining the receipt URL might retrieve that report. Before broad release, bind reports to verified customer identity or a scoped signed entitlement, add durable purchase ledger and webhook idempotency, set Stripe rate limits at the edge, implement dispute/refund invalidation where needed, and establish secure data retention/privacy processes. The current in-memory IP rate limit is a supplementary local safeguard, not distributed production protection.

### Mobile store requirements

**Do not use the web Stripe purchase button inside a native iOS/Android app without a documented region/policy exception.** Apple and Google generally require their in-app billing mechanisms for native digital-content unlocks. This version detects native Capacitor and disables web checkout until StoreKit 2 and Google Play Billing products, verification, restoration and device QA are implemented.

A recommended path is to integrate the free challenge as a well-designed **Challenge** tab within NIJA's existing Capacitor/Expo app, instead of shipping an extra thin WebView app. Shared mission designs can coexist with native progress history, haptics, accessibility, achievements and replay. Do not submit until real native builds, signing, Apple developer/Play Console accounts, billing sandbox tests, privacy disclosures, age handling and app-review requirements are complete. Follow Apple's 4.2 minimum-functionality policy; a webpage wrapper alone might be rejected.

## UX, analytics and next product iterations

Test conversion rather than promise one dollar from every visitor. Measure unique visitors, game starts, first choice, completion, optional report CTA, verified checkout completed, refunds, net receipts and replay rate. The product's primary trust promise is free useful practice and transparently optional feedback.

Future phases: daily challenges, risk-plan builder, progressive achievement badges, on-device history, accessibility/narration, local language translations if reviewed, and verified-consent leaderboards based on game performance (not simulated profit). Never promote gambling, guaranteed earnings, or pressure purchases through false scarcity.

## Security and QA

`npm test` covers score validation, perfect/zero edge cases, public/client separation, rejection of invalid and cross-origin requests, Stripe amount/metadata, rejection of unpaid sessions, and successful server-verified results. GitHub Actions workflow `.github/workflows/trading-iq-challenge.yml` executes the tests. A PR alone is not a deployment or a production certification.

## Official references

- Apple App Review Guidelines: https://developer.apple.com/app-store/review/guidelines/
- Google Play Payments policy: https://support.google.com/googleplay/android-developer/answer/9858738
- Stripe Checkout fulfillment: https://docs.stripe.com/checkout/fulfillment
