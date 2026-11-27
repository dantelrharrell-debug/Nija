# NIJA Trading IQ free-game production release gate — 2026-11-08

Status: HOLD pending independent QA and explicit owner publish approval.

## Evidence supplied by IONOS (not independently verified)
- Unified five-area score excludes fictional profit, including original 12 rounds.
- Practice Lab with portfolio mix, news verification, risk plan, discipline.
- NIJA Coach, achievements, progress preservation, optional practice saving.
- Automated tests reportedly pass; 320/375/390px visual and real device tests not run.
- $1 checkout remains disabled; no backend or verified game subdomain.
- IONOS preview path: /trading-iq-challenge; no public preview URL.

## Required pre-publish acceptance
- [ ] Independently inspect preview and capture screenshots at 320, 375, 390, 768 and 1280px; verify no horizontal overflow, clipping or inaccessible controls.
- [ ] Complete one full 12-round run and all four Practice Lab modules on iPhone Safari and Android Chrome, plus keyboard-only and VoiceOver/screen reader.
- [ ] Confirm free guest play without account, payment, broken external game domain or server dependency.
- [ ] Verify score invariance to fictional market return; consistent scoring and historical score labels.
- [ ] Verify age handling and that minors never see a paid solicitation.
- [ ] Confirm practice storage opt-in defaults off and denied storage does not break play.
- [ ] Confirm approved logo and all Academy links resolve; no secrets or customer data in browser storage.
- [ ] Obtain export, backup, rollback instructions, IONOS preview build identifier, and evidence for all tests.
- [ ] Ensure $1 checkout is disabled and no real brokerage/order connections exist.
- [ ] Owner explicitly approves publishing free game only.

## Release scope
Publish only verified free IONOS game route after owner approval. Do not alter Stripe, DNS, Vercel, trading controller, Shopify, $99 course or existing customer records. Report actual live URL and perform post-publish smoke test. Stop and roll back on failed checks.

Related: PR #3702, issue #3696.
