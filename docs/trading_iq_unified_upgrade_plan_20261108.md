# NIJA Trading IQ — Unified Upgrade Implementation Plan (2026-11-08)

Status: PROPOSED; no production deployment or payment activation authorized by this document.

## Non-negotiable product contract
- Twelve fictional educational decisions free without registration; adults 18+ may optionally buy a one-time $1 personalized report only after certified fulfillment.
- Keep youth education free and avoid purchase solicitation to minors.
- No real brokerage connectivity, real orders, cash prizes, investment recommendations, profit promises, or volume-based incentives.
- Never use simulated P&L as a skill score. Reward risk discipline, research, patience, diversification, and consistency.
- Preserve existing Academy, $99 Foundations, customer records, trading controller and kill-switch protections.

## P0: Reconcile sources and deployment
1. Export canonical IONOS project aibuilder-4dfdf source and verify its live versus preview game version. Do not assume GitHub six-round MVP, Python five-round billing, IONOS twelve-round contract, and 72-decision sandbox are interchangeable.
2. Confirm exact Vercel project and DNS ownership for game.nijaaitrading.com. Repair only after verifying expected record and rollback.
3. Establish one versioned, server-owned manifest with scenario IDs, choices, scoring, coaching, age rules and content digest.
4. Record browser QA for guest entry, progress/resume, restart, responsive screens, keyboard/VoiceOver and Android/iOS.
5. Certify $1 Stripe test-mode flow: fixed amount/product, server-owned score, idempotency, signed webhook, durable entitlement, receipt recovery, refund/dispute revocation and no duplicate charge. Keep live checkout disabled until certification and owner approval.

## P1: Gameplay improvements (feature-flagged)
- Animated fictional chart sequences with pause/replay, accessible text alternatives and reduced-motion support.
- Position sizing, risk-budget and stop-loss sandbox with deterministic simulated outcomes.
- Coach feedback grounded in a reviewed lesson bank; AI explanation optional and never authoritative for scores or financial advice.
- Five-dimensional scorecard: risk controls, information verification, patience, diversification and consistency. Include explanation and next lesson for each score.
- First twelve rounds as onboarding; optional deeper beginner/intermediate/advanced scenarios without modifying paid report promises.
- Practice portfolio tracking drawdown, exposure, correlation and risk limits; no broker keys or live data required.

## P2: Retention and Academy
- Optional daily scenarios and learning streaks, with no penalties for taking breaks.
- Skill badges and classroom-friendly comparisons; never rank by simulated profit or trading frequency.
- Personalized links to free Academy lessons, with clearly optional $99 Foundations offer for eligible adults.
- Approved NIJA eagle logo and black/navy/gold mobile design; WCAG-oriented accessibility review.

## Analytics and acceptance
Instrument consent-aware events: game_start, round_complete, game_complete, adult_eligible_checkout_view, checkout_start, verified_payment, report_delivered, refund, repeat_visit and academy_lesson_open. Deduplicate events and label all unverified revenue provisional.

Release gates: exact SHA CI/security pass; accessibility/device QA; server-owned scoring tests; webhook/entitlement/reversal tests; privacy and age-policy approval; verified domain; rollback plan; explicit production approval. No deploy, publish, Stripe live charge or trading setting change in this proposal.

## Recommended delivery sequence
PR A canonical manifest and version reconciliation; PR B accessible interactive chart and scoring; PR C coaching and learning paths; PR D secure payment/report certification; PR E analytics and retention. Stage and review each independently.

References: web/trading-challenge/README.md; web/trading-challenge/TIQ12_INTEGRATION_HANDOFF.md; game_sandbox/README.md; issues #3696 and #3644.
