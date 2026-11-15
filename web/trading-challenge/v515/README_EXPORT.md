# NIJA Trading IQ Challenge — game-only source export (derived from v515)

Export ID: **nija-tiq-gameonly-4a64f74c** · Exported (UTC): **2026-11-11T15:46:05Z**
Derived from saved version **v515** = git commit `4a64f74cfef32ea6830ec9b100fcbb897c32929b` (2026-11-10 01:51:50 UTC), the canonical owner reference.
This is a **separate export**. The original archives (`nija-trading-iq-028b3006.zip`, `nija-trading-iq-4227f20c.zip`, and 081be40b) were not touched.

## What is inside
- `src/pages/TradingIQChallenge.jsx` — the 12-round, six-scenario, 72-decision game, results and four-module Practice Lab host
- `src/components/` — BrandMark + NIJALogoAnimated (approved eagle emblem, drawn in code), TiqResults, TiqLab, TiqLabVisuals, TiqReport, TiqCoach, TiqAchievements
- `src/lib/` — tiqNews (news for every decision), tiqProgress (guest progress saved in the browser), tiqReportClient / tiqLabClient / tiqExtrasClient, tiqReportReopen, tiqBackendClient (switched OFF stub), adultDeclaration, gameAnalytics, visitorTracking, seo, pb (same-origin client setup, no credentials)
- `offline_tiq_premium/` — scoring (tiq_scoring), engine, Lab logic, coach, achievements, report logic, age gate, offline payment-flow model (simulated only) and their tests, plus design/spec notes
- `offline_tiq_tests/` — saving, progress, visual-element, launch-safety and integration tests
- `src/index.css` — the site's whole stylesheet (the game's `.tiq-*` rules are inside it; other site rules come with it)
- `index.html`, `public/favicon.svg`, `package.json`, `vite.config.js`, `tailwind.config.cjs` — app shell and config exactly as in v515
- `run-tests.mjs` — ADDED for this export (not in v515): runs all included tests
- `MANIFEST.sha256` — SHA-256 of every file in this archive (the archive's own SHA-256 is published beside the .zip, never inside it)
- `PROVENANCE.md` — exact derivation, verified facts vs historical claims, omissions

## Run the included tests (Node 20+, no packages, no network)
`node run-tests.mjs`

## Build limits (read this)
- `vite.config.js` imports the editor's own build configuration at `/usr/lib/sfs-assistant-dev/platform-config.js`; it will not run outside that editor. `package.json` lists the platform's SDK dependency exactly as in v515 and does not declare React, React Router, Vite, Tailwind, pocketbase or lucide-react (the editor provides them).
- Imports of the form `icon:...` are resolved by the editor. This archive was **not** rebuilt or browser-run outside the editor.
- The game page imports a few site files that are included only as far as the game needs them (`pb.js`, `visitorTracking.js`, `gameAnalytics.js`, `seo.js`). They contain no credentials; they point at same-origin paths.

## Safety content
No credentials, keys, tokens, webhook addresses, customer or lead records, databases, backup archives, payment settings or unrelated website pages are included. The  personalised report is disabled ("Coming Soon") and no checkout exists here. The backend client is a stub that makes no network request.
