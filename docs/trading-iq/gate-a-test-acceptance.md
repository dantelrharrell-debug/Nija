# NIJA Trading IQ Gate A — exact test and acceptance specification
Status: TEST PLAN ONLY; tests not executed or certified by this document.

## Canonical game parity
- Exactly 12 unique ordered IDs and 12 completed responses; reject missing, duplicate, reordered, out-of-range or extra answers.
- Pin manifest digest and scoring version; detect source drift between IONOS live, preview and server-owned rules.
- Deterministic score for same canonical responses; fictional profit changes must not alter IQ score.
- Free guest play completes without account, Stripe, brokerage, backend availability or optional storage.
- Existing Academy navigation, consent and age rules preserved; minors see no $1 solicitation.

## Simulator determinism and safety
- Identical scenario/version/seed/decision log produces identical fills, positions and report.
- Replay exposes no candle after virtual time; reject stale or out-of-order decisions.
- Reject negative/NaN/overflow order quantities and insufficient virtual buying power.
- Verify market/limit/stop triggers, gaps, spread, fees, slippage, partial fills and cancellations against fixtures.
- Enforce exposure, concentration, drawdown and position limits; no live broker import or network order dispatch.
- Reconcile cash + positions + fees and realized/unrealized P&L after each event.
- IQ score independent of simulator profit, frequency and speculative risk-taking.

## Accessibility and device matrix
- Screens at 320/375/390/768/1280 px: no horizontal overflow, clipping or inaccessible controls.
- Full 12 rounds and simulator smoke flow on iPhone Safari, Android Chrome, keyboard-only and VoiceOver/TalkBack.
- 200% text zoom, visible focus, semantic labels, chart text alternative, reduced-motion and no color-only indicators.
- Denied local storage and network interruption do not prevent free play.

## Paid-report security (separate certification, not enabled)
- Missing, tampered, unpaid, expired, mismatched, refunded, disputed, revoked or reversed entitlement -> deny.
- Signed webhook raw body and Stripe reconciliation; duplicate/reordered events are idempotent; reversal remains sticky.
- One run -> one checkout reservation; lost response retry cannot duplicate charge.
- Owner receipt required for report reopening; cross-user access denied; report server-side score only.
- Test-mode USD 100 cents and exact approved product/price; no live checkout without separate owner approval.

## Gate A documentary exit
- Authenticated IONOS export and checksum.
- Verified live/preview build IDs and screenshot baseline.
- Canonical twelve-round content/scoring/age parity matrix.
- Approved exact design tokens and asset provenance.
- Reviewed simulator threat model and module boundaries.
- Signed acceptance matrix with evidence links and open blockers.
- Explicit owner approval for any subsequent code changes.

No tests are claimed as run. GitHub checks on a documentation PR do not certify production behavior.
