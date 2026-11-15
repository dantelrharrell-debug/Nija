# IONOS Trading IQ preview acceptance and next implementation handoff

Status: USER-SUPPLIED IONOS REPORT; not independently verified. Preview remains unpublished.

## Reported as implemented in IONOS preview
- Five-area scorecard with disclosed formulas; simulated profit excluded.
- Deterministic NIJA Coach and adult-confirmed adult-program lesson links.
- Eight educational achievements, including inactivity/patience-positive Calm Hands, and replay comparisons.
- Build and logic tests reported passing by IONOS; not independently reproduced.
- State lost on reload.

## Outstanding acceptance tests
1. Obtain full source export and identify canonical IONOS round manifest, age gate, score formulas and achievements. Compare preview to current live page. Never silently overwrite canonical source with GitHub six-round MVP.
2. Add a multi-asset fictional diversification round: at least three assets, distinguish correlation from number of holdings, explicitly score diversification only where evidence exists; no live market feed.
3. Add misinformation/news-source verification round with source provenance, timing and uncertainty; do not use real issuer-specific trading recommendations.
4. Add deterministic risk-budget scenarios and boundary tests; score decision process, not fictional profit.
5. Persist free progress with an explicitly disclosed privacy-safe local mechanism as an optional interim convenience, or defer to backend; do not store payments or sensitive user data in browser storage.
6. Validate adult age confirmation and prevent paid offers to minors; no report checkout until backend verified.
7. Device/browser accessibility tests: iPhone Safari, Android Chrome, iPad, desktop, keyboard, VoiceOver, reduced motion, 375/768/1280 widths.
8. No publish until explicit owner approval and verified rollback.

## Separate backend implementation plan
- Standalone HTTPS service isolated from trading runtime, with staging/live separation, protected secrets, durable database and authenticated ownership.
- Server-authoritative game version, score and manifest; immutable run completion, idempotent checkout, verified Stripe signature webhooks, fixed $1 price and verified charge/refund/dispute status.
- Durable report entitlement and receipt recovery, privacy/age enforcement, consent-aware deduplicated analytics and limited admin access.
- Test Stripe sandbox only until full end-to-end certification and owner approval.
- Verify game.nijaaitrading.com DNS before routing traffic.

## Release policy
Do not claim completion based on IONOS narrative alone. Collect export, preview QA, backend test logs, deployment SHA and approved owner signoff. Preserve Academy, $99 course, Shopify, customer records and NIJA trading fail-closed controls.
