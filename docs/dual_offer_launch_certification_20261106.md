# Dual-offer launch certification — REVIEW ONLY

Issue: #3696. This document does not authorize production deployment or payments.

## Verified live facts (2026-11-06)

- Stripe live account: `acct_1Tzy0bI0gfJjTf3E`.
- Foundations live product `prod_VP9qj2FNvpPJin` has metadata `nija_fulfillment_status=paused_pending_secure_delivery`. An active link `plink_1UEtWDI0gfJjTf3E5L0wb3K9` redirects to `https://nija-billing-api.onrender.com/course-portal/thank-you?session_id={CHECKOUT_SESSION_ID}`. Active payment link alone is **not** fulfillment certification.
- Old Foundations link `plink_1U0GhxI0gfJjTf3EGRXPR4mz` is inactive.
- Trading IQ personalized report product `prod_VZI9N8jDpFrQMt` exists in live Stripe, but no dedicated $1 payment link appeared in the payment-link list. Hosted checkout is a separate application flow.
- Production billing service `srv-dasn1mbbc2fs738036gg` uses `main`, `autoDeploy=yes`, `autoDeployTrigger=checksPass`, with latest inspected deployment from Nov 5. Do not merge unreviewed changes into `main`.
- Staging billing service `srv-dasmtjfpn0mc73948r10` had a live Nov 6 deployment, but that alone does not certify checkout.
- Current main `nija_game_hosted_routes.py` already has a same-origin referrer policy for checkout confirmation and allows validated Stripe checkout hosts in form-action CSP; `nija_game_checkout_store.py` rejects raw `..` path components and symlinked private storage paths. Verify behavior in deployed browser flows; do not reintroduce stale patches.

## Required before release

1. Confirm exact live price IDs, $99 and $1, one-time billing, tax collection/registrations, and the course content actually present in the entitlement-backed portal.
2. Confirm the Stripe checkout session cannot unlock either purchase before verified payment and that signed webhook replay, delayed delivery, refund/revocation, and duplicate attempts are handled correctly.
3. Stage browser checks in Safari and Chrome: form Origin, CSP redirect, cookie persistence, lost-cookie recovery, and server-side idempotency under retries.
4. Inspect the deployed runtime environment and dedicated persistent checkout journal mount without logging secrets. Confirm configuration and code SHA match the reviewed release.
5. Verify an eligible 18+ Trading IQ attempt can access its paid report only after successful payment; free gameplay must remain free.
6. Verify analytics purchase event fires exactly once per verified purchase; reconcile gross charges, refunds, Stripe fees and visitor counts without conflating events with unique customers.
7. Obtain independent approval for a guarded production release, record rollback procedure, then verify both live checkout -> receipt -> entitlement/report journeys with controlled transactions.
8. Keep live trading authority and brokerage settings unchanged.

## Status

**NOT CERTIFIED / DO NOT MARK LAUNCHED.** The above steps require runtime and browser evidence. This review document makes no production changes.
