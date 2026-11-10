# Trading IQ canonical certification — HOLD

Baseline main: `0045a98020039770f653fcee1176f1fdcb061df7`. This document does not certify or publish a game.

## Known source boundary
- `game_sandbox/ionos_parity.test.mjs` verifies the recovered public six-challenge x twelve-decision (72-decision) reducer/report, not the latest inaccessible IONOS preview.
- Canonical candidate `nija-tiq-028b3006`, reportedly at `app/exports/nija-trading-iq-028b3006.zip`, must be obtained as actual bytes and SHA-256 verified before equivalence can be claimed.
- Do not substitute the separate Vercel five/six-round implementation or the isolated advanced simulator.
- Preserve existing IONOS branding, approved eagle-logo checksum, typography, animations, scorecard, and four Practice Lab modules; record exact approved reference assets and screenshots before changing visuals.

## Evidence intake
Record export origin, authenticated download method, byte length, SHA-256, build ID, source-file inventory, asset checksums, approved design reference, reviewer, UTC collection time, and rollback archive location. Never commit credentials, customer data, or the nested 180 MB backup. If export is unavailable, status remains BLOCKED.

## Browser acceptance — pending source
Use Playwright Chromium and WebKit at widths 320, 375, 390, 768, 1280; capture screenshots and compare approved reference. Verify complete intended round structure from export (do not assume whether twelve means total or per challenge), all four Practice Lab modules, scorecard, keyboard-only flow, storage denied, reduced motion, and anonymous free play. Conduct separate manual VoiceOver and TalkBack tests on devices. Verify no brokerage orders, no paid checkout, no soliciting minors, and no simulated-return contribution to Trading IQ scoring.

## Release gate
Do not publish, change DNS, enable payments, or touch live trading. Owner must approve the exact source hash and browser evidence, then separately authorize free-game-only publication. Preserve `rollback-pre-tiq-launch-20261109` off-project and smoke-test after separately approved release.

## Regression commands (existing)
`node --test game_sandbox/ionos_parity.test.mjs`
`node --test web/trading-challenge/tests/*.test.mjs`

No browser certification can pass solely from the recovered served-build parity tests.
