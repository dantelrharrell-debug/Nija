# NIJA Platform v2 — Release and acceptance matrix
This file is a task tracker, **not** evidence that any production migration is completed.

| Area | Required proof before launch | Owner to identify | Failure posture |
| --- | --- | --- | --- |
| Site/IA | Exact IONOS deployed files, screenshots desktop/mobile, verified navigation and offer text, WCAG audit, Core Web Vitals RUM | Website publisher | Keep old site |
| Trading IQ | Canonical 12-round 72-decision content parity, scoring and accessibility tests, deployment parity, run persistence | Game source owner | Leave current canonical game |
| Course $99 | Signed payment webhook, idempotency, fulfilled authorized access, refunds and disputes, rollback, hosted security checks | Billing owner | Checkout unavailable |
| IQ results $1 | 72-decision gate, adult attestation, stage payment, report retrieval, duplicate/replay/refund and denied access proof | IQ billing owner | 503/not certified |
| Founding 100 | One verified pricing/trial policy, renewal/cancel/refund, legal copy, billing readiness | Product/billing owner | Waitlist only |
| CRM | Submission/provenance parity, consent, durable receipt, safe handling of uncertain sends, actual provider ACK | CRM owner | No silent resend |
| Shopify | Product policy, stock/order ownership, domain checkout navigation, mobile QA | Store owner | Keep existing store |
| Admin | Role-based authorization, audit records, private evidence redaction, dated health | Operations owner | Read-only |
| Trading | Exact protected startup sources and independent signed attestations, final-interpreter collector, 13/13 fresh account-scoped observations, ledger/recovery/nonce/lease/kill switch, CI/security, distinct go-live authorization | Independent trading reviewer and NIJA owner | allow_new_orders=false |
| Infrastructure | Exact deployed artifact + checks, secrets boundaries, backups/restores, rollback drill and alert owners | Release engineering | Hold release |

## Immediate source-ownership questions
1. Which IONOS build/version is actually published and what routes/components make its homepage?
2. Which backend service is authoritative for course fulfillment and IQ fulfillment, and are they intentionally separate?
3. What persistent identity key and entitlement table can be reused without recreating accounts?
4. Which exact deployment/secret owner controls webhook endpoints?
5. What is the live-vs-render.yaml trading startup divergence and which revision is approved? Do not alter either startup in this project without a separate trading review.
6. Who has authority to approve individual marketing, billing, database and trading production releases?

## Change-control rules
- This architecture PR is docs-only; no scripts, infrastructure or trading files.
- Convert each matrix row to one or more narrowly scoped issues and PRs after exact code ownership is verified.
- Use explicit release checklists and independent reviewer sign-off.
- Customer-facing, paid, and trading activation each require separate explicit approval.
