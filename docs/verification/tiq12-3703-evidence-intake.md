# TIQ12 / issue #3703 — canonical evidence intake and provider handoff

Status: DRAFT ONLY. No export has been authenticated by this document. Do not import customer data or credentials.

## IONOS request
Project: aibuilder-4dfdf
Unpublished preview: https://aibuilder-4dfdf.preview.ai-builder.ionos.com/.sfs-dev/?lang=en-US
Game route: /trading-iq-challenge
Support ticket: 6aebeaf870f76ca9e19ceea2
Reference: https://github.com/dantelrharrell-debug/Nija/issues/3703

Request provider-written confirmation of:
1. Supported non-expiring exact saved-preview export method (is Code > Export all sufficient?), including source, assets, styles, animations, all twelve scenarios, four Practice Lab modules, five-area scorecards, achievements, coaching and scoring/feedback rules.
2. Authenticated exact saved-preview build/version ID, source revision, export creation time, file manifest, SHA-256 digest, and how exported source is proven identical to saved preview. No substitute Vercel or 72-decision game.
3. Dependency lockfiles, runtime/toolchain versions, build and offline test instructions, route configuration, reference screenshots/video and approved eagle logo asset/hash.
4. Available private preview storage and backup/rollback, isolation and preview-to-production migration approvals, or explicit unsupported status.
5. Secure external Stripe test-mode webhook/API, reverse proxy, first-party cookies and server-private storage support, or explicit unsupported status. These are not prerequisites for free game browser tests; checkout remains disabled.
6. Non-expiring off-project copy of rollback-pre-tiq-launch-20261109 and provider-confirmed restoration process without affecting live site, Academy, $99 course, leads or customers.

## Evidence register — fill only from authenticated source
| Field | Value | Evidence link/hash | Reviewer |
|---|---|---|---|
| Provider ticket | 6aebeaf870f76ca9e19ceea2 | IONOS email Nov 9 23:12 UTC | Pending independent confirmation |
| Canonical saved-preview build ID | MISSING | | |
| Canonical export archive path | MISSING | | |
| Export SHA-256 | MISSING | | |
| IONOS source revision | MISSING | | |
| Approved logo SHA-256 | MISSING | | |
| Canonical 12 ordered round IDs | MISSING | | |
| Choice/point/feedback/lesson manifest | MISSING | | |
| Five-area score formulas/rounding | MISSING | | |
| Four lab modules inventory | MISSING | | |
| Animations and reduced-motion behavior | MISSING | | |
| Reference visual screenshots/video | MISSING | | |
| Dependency lockfile/build instructions | MISSING | | |
| Rollback archive and restore proof | MISSING | | |
| Provider storage/integration answer | PENDING | | |
| Browser and device acceptance results | NOT EXECUTED | | |

## Existing separate materials — not canonical IONOS source
- web/trading-challenge/server/tiq12-contract.mjs: private contract validators; TIQ12_VERSION nija-trading-iq-12-v1 is a contract constant, not provider build ID.
- web/trading-challenge/tests/tiq12-contract.test.mjs: synthetic twelve-round fixtures and fake Stripe grants.
- web/trading-challenge/TIQ12_INTEGRATION_HANDOFF.md: review-only design; explicitly states canonical IONOS source absent.
- docs/trading_iq_ionos_preview_acceptance_20261108.md: user-supplied provider report, not independently verified; mentions state lost on reload.
- game_sandbox: separate 72-decision implementation, not an acceptable replacement.
- Reported nija-tiq-028b3006 ZIP and SHA-256 are candidate claims only; do not mark authenticated without IONOS source-to-preview confirmation.

## Chain of custody and comparison
Record download origin, authenticated provider confirmation, UTC acquisition time, exact archive size/hash, sanitized file inventory, excluded secret/customer-data paths, archive nesting/symlink inspection, and immutable copy location. Compare ordered scenarios, answer mapping, score formulas, category rules, animations, logos, labs, mobile layouts and age gates against approved IONOS reference. Independently rebuild with pinned dependencies and compare output hashes or documented reproducible-build differences. Bind each browser trace/screenshot and reviewer decision to the same source/build digest.

## Restrictions
No production publish, DNS, payments, Render provisioning, customer-data operations, GitHub merge, or trading-system changes. Any proposed correction requires separate explicit owner approval.
