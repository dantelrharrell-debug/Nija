# NIJA Shopify commerce onboarding — review-only implementation pack
Prepared: 2026-11-05. Status: **PLANNING ONLY — NO SHOPIFY ACCOUNT, STORE, DOMAIN, BILLING, PAYMENT OR PRODUCTION CONFIGURATION CREATED OR CHANGED BY THIS FILE**.

## Decision and system boundaries
- Preserve `nijaaitrading.com` on IONOS as brand, free assessment, lead funnels, and Academy navigation.
- Propose `shop.nijaaitrading.com` for Shopify storefront only after DNS conflict checks, account claim, and operator approval.
- Preserve `game.nijaaitrading.com` and the free 72-decision Trading IQ experience on isolated game infrastructure. Existing Stripe *sandbox* payment/report entitlement remains the source of truth; **do not replace with Shopify checkout** until a separate payments architecture and provider eligibility review approves the change.
- Keep Kraken trading, production credentials, broker authorization, kill switch, risk limits and live execution completely segregated from Shopify. No orders or production deploys in this rollout.
- Avoid parallel paid product catalogs or duplicated receipts between existing Printful Quick Store, Stripe, ClickBank, and Shopify; reconcile before switching any customer-facing purchase destination.

## Shopify draft store brief (copy into the official Shopify plugin)
**Store name:** NIJA AI Trading | NIJA Store
**Storefront theme:** premium, restrained, dark navy/black with gold highlights; accessible contrast and readable mobile UX; no unverified performance claims.
**Business positioning:** NIJA-branded apparel and financial-literacy education. Merchandise and education are not investment advice, assurances of investment profits, managed accounts or access to broker trading.
**Audience:** adults exploring NIJA's brand and educational offerings.
**Domain:** Shopify-generated preview initially, `shop.nijaaitrading.com` only after approval.
**Navigation:** Home | Shop All | Hoodies | Jerseys & Tops | Academy | About NIJA | FAQ | Contact.
**Homepage:** Brand hero, browse apparel, educational offerings marked "Coming Soon" until verified, link to free Trading IQ challenge, separate safety disclaimer.
**Footer:** Shipping & Returns | Privacy | Terms | Contact | Educational Disclaimer. Policies require real business, shipping, tax and fulfillment details; do not invent them.
**Checkout:** Preview/password-protected only until product legitimacy, ownership, fulfillment, payment, taxes and policies are configured. No live orders/test purchases on the public domain.

## Draft catalog — no fabricated prices, images or availability
| Product | Product type | Draft status | Data required before publish |
|---|---|---|---|
| NIJA Branded Hoodie | Physical / print-on-demand | Draft concept | Existing Printful SKU, size/color variants, production cost, retail price, photos, fulfillment profile |
| NIJA Cropped Hoodie | Physical / print-on-demand | Draft concept | Confirm existing item, sizing, SKU and availability |
| NIJA Baseball Jersey | Physical / print-on-demand | Draft concept | Style/source assets, print specs, vendor, sizing, price |
| NIJA Button-Up Shirt | Physical / print-on-demand | Draft concept | Style/source assets, print specs, vendor, sizing, price |
| NIJA Academy Course | Digital education | Hold / no checkout | Confirm exact $99 offer, content delivery, existing ClickBank/Stripe relationships, refund policy, tax handling and processor eligibility |
| Trading IQ Personalized Report | Digital education | Hold / no Shopify checkout | Confirm 100-cent one-time offer is eligible; preserve game_sandbox Stripe entitlement until separate approved migration |

Do not migrate inventory or fulfill orders until live Printful inventory/integration is verified. Products should be hidden/unpublished where product source data is missing.

## Integrations and anti-duplication requirements
1. **Merchandise:** Audit whether existing Printful Quick Store has an active independent checkout, whether Shopify-Printful integration supports the products, and what will happen to previous orders; migrate catalog only after source data and ownership are checked. No forced redirection until destination checkout passes.
2. **Academy $99:** Identify the existing production product/checkout processor, entitlement store, content access and refunds. Shopify webhooks must never grant access from redirect URLs or browser claims. Use server-side verified paid transactions and revocation for refunds/disputes. Do not offer two live checkout routes for the same entitlement without an approved reconciliation design.
3. **Trading IQ $1:** Existing `game_sandbox/README.md` and `game_sandbox/STRIPE_SANDBOX_VERIFICATION.md` document isolated Stripe sandbox proof, **not live installation**. Keep unchanged. Shopify Payments and Shop-channel eligibility for investment-related products must be reviewed in writing before listing.
4. **CRM:** Only consented, minimised customer attributes may flow to Apollo/Zapier; separate transactional necessity from marketing consent. Never forward full order/billing records or financial data to marketing tools. No automatic lead-creation on a preview store.
5. **Accounting:** Deduplicate Shopify, Stripe, Printful and ClickBank using provider-level identifiers; processor fees, refunds, shipping, taxes, fulfillment and ad spend must be included in net-profit computation. `docs/WEBSITE_NET_PROFIT_PER_VISITOR.md` explicitly forbids double counting Printful payments also represented by Stripe.

## Preconditions to creating/claiming store
- User installs **official Shopify plugin for ChatGPT** and explicitly authorizes store creation/claim, or creates owner account at Shopify. Do not use guessed credentials, owner identity, business address, or bank details.
- User chooses/approves account email, legal business identity, billing and tax details; retain ownership in user's account. Verify administrator MFA.
- Use Shopify preview/password mode. Select paid plan, remove password, configure Shopify Payments or other provider, and connect custom DNS only after separate explicit approval and provider eligibility check.
- Confirm custom `shop` DNS label has no conflicting A/AAAA/CNAME before changing it. Do not modify `@`, `www`, `game`, MX, SPF, DKIM or existing site records.
- Review Shopify merchant/payment policies for financial education products; keep restricted products out of Shop channel if disallowed. No guaranteed earnings claims.

## Release gates and evidence to collect
- [ ] Official plugin installed and new account/store ID verified in Shopify admin, owned by NIJA.
- [ ] Preview store URL, password protection and theme inspected at phone/tablet/desktop widths.
- [ ] Approved product variant/price/SKU/image source and fulfillment mapping for each publishable item.
- [ ] Shipping zones, returns policy, privacy terms, tax and business identity set from verified real information.
- [ ] Payment-provider eligibility confirmed; no real-card test transactions.
- [ ] Test-mode/order lifecycle verification where provider supports it: webhook signature verification, idempotency, successful fulfillment, refunds and dispute handling.
- [ ] Marketing consent handling and restricted CRM payload verified.
- [ ] Financial reconciliation tested with existing Printful, Stripe and ClickBank evidence; no duplicate revenue.
- [ ] DNS connected only after written owner authorization; HTTPS, redirects and original IONOS site verified.
- [ ] Explicit go-live approval before lifting storefront password or enabling real payments.
- [ ] Production read-back after launch: store reachable, checkout valid, original IONOS pages and game unchanged.

## Current verified repository evidence
- `docs/WEBSITE_NET_PROFIT_PER_VISITOR.md` describes Printful Quick Store settlement, Stripe and ClickBank as separate sources, not certified collectors.
- `game_sandbox/README.md` identifies 72-decision game and disabled isolated Stripe sandbox integration.
- `game_sandbox/STRIPE_SANDBOX_VERIFICATION.md` documents sandbox checkout, refund and dispute checks; hosted game service and production report flow remain unverified.
These records do not establish whether Shopify exists, any Shopify payment capability, or the live IONOS/Printful storefront state.

## Ownership/action matrix
| Action | Responsible party |
|---|---|
| Prepare brand brief, rollout controls, integration proposal | NIJA engineering / assistant |
| Install Shopify plugin and approve creation/claim | NIJA account owner |
| Supply/approve company identity, address, tax, bank, admin MFA | NIJA account owner |
| Configure products and preview once Shopify access connected | Authorized Shopify operator / assistant |
| Review compliance and payment eligibility | Shopify/payment provider + NIJA owner |
| Approve DNS, publish, and production checkout | NIJA owner, as separate explicit changes |

Official docs: https://help.shopify.com/en/manual/ai-powered-tools/connecting-ai-tools/shopify-plugin-for-chatgpt ; https://help.shopify.com/en/manual/payments/shopify-payments/onboarding/eligibility .
