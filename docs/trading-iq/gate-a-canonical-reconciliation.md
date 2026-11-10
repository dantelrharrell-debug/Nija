# NIJA Trading IQ Gate A — canonical source reconciliation
Status: DOCUMENTATION ONLY / REVIEW / NOT CERTIFIED (2026-11-10)

## Non-negotiable boundary
No code changes, publishing, DNS edits, deployments, payment activation, brokerage connections, trading controller changes, or source replacement. The IONOS canonical 12-round game is not represented by the GitHub six-round web MVP, five-round Python billing game, or 72-decision sandbox.

## Source intake checklist
- [ ] Obtain authenticated export from IONOS AI Builder project aibuilder-4dfdf, with original archive, provenance, timestamp, SHA-256, build identifier and export procedure. Exclude secrets and customer data.
- [ ] Obtain separately labeled published and preview build identifiers and source/content digests; record exact route and release dates.
- [ ] Identify canonical 12 ordered scenario IDs, question copy, answer choices, feedback, scoring rules, age handling, Academy links, progress storage, chart assets and responsive styles.
- [ ] Compare exported code with live and preview behavior; record each discrepancy as verified/provisional/blocked/unverified with screenshots and source references.
- [ ] Produce a server-owned, versioned manifest with exactly 12 unique ordered IDs, 2–6 choices per round, scoring, feedback and lesson mappings. Verify digest against independently inspected source; do not invent rounds.
- [ ] Compare scoring with private tiq12-contract.mjs and ensure simulated P&L cannot influence educational score.
- [ ] Identify existing 5-round, 6-round, 72-decision and IONOS variants explicitly; never silently substitute.
- [ ] Verify backup and rollback steps and source custody before proposing any implementation.

## Evidence ledger template
| Item | Current evidence | Status | Owner | Required proof |
|---|---|---|---|---|
| IONOS canonical export | Not available in GitHub | BLOCKED | IONOS/owner | Authenticated archive + SHA-256 |
| Published/preview parity | Not independently verified | UNVERIFIED | QA | Build IDs + side-by-side evidence |
| Twelve-round manifest | Private contract only; content missing | BLOCKED | Engineering | Exported canonical content + digest |
| GitHub alternatives | Explicitly different products | VERIFIED IN REPO | Engineering | TIQ12_INTEGRATION_HANDOFF.md |
| Payment certification | No live authorization | BLOCKED | Security | Separate Stripe test-mode evidence |

## Source references
- web/trading-challenge/TIQ12_INTEGRATION_HANDOFF.md
- docs/trading_iq_unified_upgrade_plan_20261108.md
- docs/trading_iq_free_launch_gate_20261108.md
- web/trading-challenge/server/tiq12-contract.mjs
- GitHub issue #3703

Gate A passes only after independent source authentication, exact canonical content parity, approved visual baseline and explicit owner signoff. This document is not proof of completion.
