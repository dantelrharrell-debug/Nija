# NIJA Platform v2 — Architecture and phased migration
Status: PROPOSAL ONLY | 2026-11-14 | Owner approval required for executable releases

## Objectives and non-goals
Build one coherent customer experience across nijaaitrading.com, the Academy, the canonical 12-round/72-decision Trading IQ Challenge, Founding 100, $99 course, $1 paid report, Shopify, support and operations. Reduce duplicated flows, failures, cost and page weight. Preserve existing customer records and purchased entitlements. This proposal does not activate payments or trading, migrate databases, provision credentials, or deploy code.

**Hard boundary:** Customer education, marketing, payments and admin code must not import an order executor or mutate live-trading state. The Render trading service is a separate protected control plane with its own approvals, credentials, nonce/writer lease, collector, ledger, position and protective-exit reconciliation, risk policies and kill switch. The documented 13/13 authenticated observations and independent certification remain mandatory. No fallback from missing source, stale evidence or failed verification to live-order authorization.

## Observed system inventory (verification scope)
- Public marketing and customer funnel: IONOS site at nijaaitrading.com; connected form delivery is not fully certified; authoritative deployment/source parity must be rechecked.
- Canonical Trading IQ: 12 rounds, six scenarios, 72 decisions. Existing IONOS game is canonical until exported source and deployment parity are proven. The Vercel game domain must not be treated as authoritative merely because DNS validates.
- Commerce: Stripe-backed $99 course and separately gated $1 IQ report; signed webhook, refund/dispute entitlement reconciliation and hosted release evidence remain acceptance criteria. Shopify runs the merchandise storefront at shop.nijaaitrading.com.
- Lead delivery: IONOS -> selected Zapier flow -> Render intake -> downstream CRM. Explicit submission IDs, consent/provenance and provider outcome fencing must survive retries.
- Trading: Render service srv-d98dsr5aeets73fpbaqg on protected release/justcall-handoff-only-20261017. On 2026-11-14 Render reported live deploy dep-dbs7tg2fngtc73bvsta0 (commit acdeaec3e56bcdb7091082ec31422ae157bb9c34). Deployment live is not evidence of trading certification. Auto-deploy is off. The actual Render docker command is python -S /etc/secrets/.render-ledger-bootstrap.py while render.yaml describes bash scripts/render_entrypoint.sh: flag as DRIFT; never reconcile by blindly overwriting either entrypoint.
- Repo: dantelrharrell-debug/Nija, main; the production trading branch is separately protected. Security/CI concerns have been documented; obtain exact-commit check status before release.

## Target bounded contexts
1. **Customer Web** — accessible responsive marketing pages, FAQ, conversion funnels, SEO and analytics. No direct customer-facing secrets; links show actual feature availability.
2. **Identity & Entitlements** — one customer ID, verified login, roles, consent, purchase and access state. Stores source references, not card details. Server-side authorization; migration preserves historical identifiers and purchases.
3. **Academy** — course catalog, lessons, enrollment, progress, youth/adult access rules; only trusted entitlement service grants paid content.
4. **Trading IQ** — canonical state machine for 12 rounds and 72 decisions; immutable run schema/version, server-authoritative scoring (risk, research/verification, patience/discipline, diversification, decision consistency); illustrated portfolio deltas are not actual returns.
5. **Billing** — Stripe checkout/session creation, signed and idempotent webhook inbox, ordered state machine, $99 course fulfillment and separately versioned $1 report fulfillment, refunds/disputes/reconciliation. No grant on client redirect alone. Production enablement needs distinct evidence and owner authorization.
6. **Leads/CRM** — lead IDs, explicit consent, event provenance, one authoritative delivery sender, delivery receipts, uncertain outcomes held for review (no blind replay).
7. **Merchandise** — Shopify remains system of record for inventory, product catalog, orders and checkout. NIJA web links to Shopify; never duplicate payment ledger.
8. **Admin/Observability** — role-limited overview, health indicators with exact freshness times, audit events, payments/entitlements and lead status. Trading may expose strictly read-only, redacted evidence summaries to admin; never a general-purpose execute-order API.
9. **Isolated Trading Control Plane** — separate service, secret scope, deployment pipeline, writer authority, independent reviewer/owner gates; no deployment from website/commerce merges.

## Canonical contracts
- `customer_id`: opaque permanent ID. Maintain a mapping table from existing platform IDs; never rewrite or drop source IDs.
- `assessment_run_id`: immutable run ID with `schema_version`, `decision_count=72`, adult eligibility state and five-area score result; no checkout initiated until validated.
- `purchase_id`: internal unique purchase attempt; unique constraint on `provider,event_id` and `provider,checkout_session_id` as applicable, stable idempotency key. Statuses: initiated -> awaiting_payment -> paid -> fulfilled; exceptional refund, dispute, canceled, failed, uncertain. Out-of-order events reconcile against trusted provider state.
- `entitlement`: (customer_id, product_key, source_purchase_id, granted_at, revoked_at, reason) with audit/history. Reconciliation is safe to retry. Refund/dispute policies must be approved before production enablement.
- `lead_submission_id`: source event ID, consent decision and timestamp, normalized payload fingerprint and durable dispatch state; replay of identical ID is idempotent, conflict is rejected.
- `operational_evidence`: recorded_at, source, build_commit, image_digest when available, freshness deadline, review status; unknown or stale is displayed as UNKNOWN/NOT VERIFIED, not READY.

## Information architecture / visual design system
Navigation: Home | Academy | Trading IQ | Membership | Shop | About. Separate account, support, partnership and investor pages.
Primary home CTA: Get My Free Trading Score. Secondary CTA: Explore Trading Foundations. Membership copy must reflect real billing readiness; unavailable offerings use explicit coming-soon labels, not contradictory promises.
Design tokens (provisional; test WCAG contrast before release):
- ink `#10131B`; surface `#1B202C`; gold `#C8A65D`; light text `#FFFFFF`; muted text `#B9C0CB`.
- Semantic states not communicated by color alone. Reusable components: navigation, primary/secondary CTA, content card, progress stepper, accessible form, inline field errors, status table, receipt panel, empty/error states.
- Mobile first; keyboard focus visible; reduced-motion support; server-side form validation. WCAG 2.2 AA acceptance target.
- Core Web Vitals at p75: LCP <= 2.5s, INP <= 200ms, CLS <= 0.1. Measure on deployed site; no claims without RUM/synthetic evidence.

## Migration sequence with zero customer-data loss
P0 **Inventory and backups**: Identify actual owners for hosting, domains, data, secrets and webhook endpoints; produce source-to-deployment matrix. Export signed configuration manifests to private storage, take off-host backups, restore-test in isolated environment. Record baseline page/performance and financial ledger snapshots.
P1 **Unified product semantics**: Resolve Founding 100 trial contradictory text and establish authoritative pricing/trial policy; define account/entitlement mappings; no actual billing mutation.
P2 **Payment correctness**: Complete $99 course and $1 IQ independent staging acceptance (webhooks, duplicate/out-of-order, refunds, disputes, checkout authorization, paid delivery); verify original production URLs and signing subscriptions before separate approvals.
P3 **Frontend redesign**: Build parallel responsive, accessible pages, maintain old routes and SEO redirects; add content parity and anonymous/mobile tests. Do not replace canonical IQ run or enrolled courses without side-by-side validation.
P4 **CRM/admin**: Move to one durable lead delivery owner, preserve unknown outcomes, expose permissions/audit/health dashboards, compare pre/post migration event counts.
P5 **Platform modernization**: Add contract tests, dependency/security gates, trace IDs, release artifacts, rollback, backup drills. Optimize cost only after traffic, capacity and billed-resource inventory.
P6 **Native apps**: Only after stable versioned APIs, entitlement support and privacy review; no duplicate business logic.
Parallel **Trading**: Continue independent issue #3890/reconciliation certification with separate approval gates; no coupling to web/commerce upgrade.

## Release gates (each phase)
- Exact target branch/commit and deployment artifact, independent source review, security scan and CI pass; no required-check bypass.
- Database migration with reversible plan, backup-and-restore evidence, old/new count parity and access-control audit.
- Contract tests: duplicate/out-of-order webhook, ambiguous delivery, denied unauthorized access, refund/dispute, 72-decision scoring, customer migration, accessibility and mobile viewport.
- Canary/pilot limited traffic with synthetic non-billable tests; no real charge/test order without separate approval.
- Metrics: completed course access from paid purchases, paid-report fulfillment, form acceptance-to-ack ratios, user journeys, crash/error budgets and page Core Web Vitals.
- Production roll forward/rollback documented per subsystem. Rollback must never roll back ledger payments without reconciliation or change trading authority.
- No launch claims until operators have independently observed acceptance evidence.

## First implementation slices (small, reviewable PRs)
1. Public IA and copy inventory + explicit availability/pricing truth table; no live checkout links changed without review.
2. Reusable UI tokens/components in the existing actual frontend owner after source inspection (not a new unconnected app); screenshot and WCAG tests.
3. Contract-only entitlement API and model backed by current source owner; stage-only tests.
4. Existing Stripe course webhook reconciliation/hardening; independent IQ purchase flow tests, separate release.
5. Internal read-only admin operations dashboard; redacted evidence.
6. Only then migrate pages with route parity, traffic measurement and rollback.

## Verified references
- Repo: https://github.com/dantelrharrell-debug/Nija
- Render service: https://dashboard.render.com/web/srv-d98dsr5aeets73fpbaqg
- Trading evidence tracking: https://github.com/dantelrharrell-debug/Nija/issues/3890
- Existing independent CRM verification: docs/website_crm_independent_verification_20261111.md
- OWASP ASVS: https://owasp.org/www-project-application-security-verification-standard/
- WCAG 2.2: https://www.w3.org/TR/WCAG22/
- Core Web Vitals: https://web.dev/articles/vitals
- Stripe webhook guide: https://docs.stripe.com/webhooks
