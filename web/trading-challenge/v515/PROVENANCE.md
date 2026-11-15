# Provenance — nija-tiq-gameonly-4a64f74c

Exported (UTC): 2026-11-11T15:46:05Z. Created by the AI App & Site Builder inside project aibuilder-4dfdf, from `git archive 4a64f74c` limited to the paths listed in README_EXPORT.md. File set = every file reachable by relative imports from `src/pages/TradingIQChallenge.jsx`, plus the included offline tests/docs, plus app-shell files. No file content was edited. Added files: README_EXPORT.md, PROVENANCE.md, run-tests.mjs, MANIFEST.sha256.

## Independently verified today (commands run in this session)
1. Commit 4a64f74cfef32ea6830ec9b100fcbb897c32929b exists, subject "Deploy v515", dated 2026-11-10 01:51:50 UTC.
2. Game page, components, libs, offline_tiq_*, public/, index.html, package.json are byte-identical between commit 4227f20c (release candidate) and v515 4a64f74c (`git diff --quiet` on those paths printed no difference). The v515 commit's only other changes were the rebuilt site output.
3. `src/pages/TradingIQChallenge.jsx` SHA-256 in v515 = `262bc7d3113ebb0102a2d2924ac410c708262b33711f749971756bb566fac348`; identical inside `nija-trading-iq-4227f20c.zip`.
4. The 028b3006 archive's `src/pages/TradingIQChallenge.jsx` (SHA-256 `36f2458f…aed6`) equals git commit 028b3006 (2026-11-09 06:22:59 UTC) and **differs** from v515 — v515 additionally has the news-for-every-decision lesson (src/lib/tiqNews.js), risk check, progress tracker, scorecard, mobile fixes (git diff 028b3006..4a64f74c on the game files: 408 insertions, 10 deletions across 5 files).
5. Both original archive checksums match their .sha256 files: 028b3006 zip `b65df7237008808be10c5840be360fa8a4c71852ee93754ffac155e0100ac383`; 4227f20c zip `26a76be9eea78dd21778db12d04e45b54b5931f2a981645c875d0c3ffda72fa9`.
6. Game chunk committed in v515 `dist/`: `TradingIQChallenge-BY_PDlEm.js` SHA-256 `7f4e0133cb3ff361954b10dca342b829c45c53b956f87cb94b07207ad19f2bae` (same chunk is inside the 4227f20c zip). The working copy's current build (after Deploy v516, HEAD b6c2dba3) names the chunk `TradingIQChallenge-yGQxNpKO.js` (SHA-256 `63b26560…c973`); whether it is functionally identical was NOT proven.
7. Tests run inside THIS export directory (offline, Node): 14 files, **1,253 checks passed, 0 failed**. Four further suites cannot run here (they read Academy/lesson files that were left out) and were run in the full project at HEAD today: tiq_extras 102, tiq_report 78, adult_declaration 11, age_policy 90 (281 passed, 0 failed). Together = 1,534, matching the earlier reported total.

## Historical claims NOT re-verified
- "Build ID nija-tiq-028b3006, source commit 028b3006…, not published, game code identical to preview build" — written in that archive's BUILD_ID.txt on 2026-11-09. The commit and the page file hash were confirmed (items 4); the "identical to preview build" claim and the build output hashes were not rebuilt or compared.
- That the 028b3006 and 4227f20c archives were made from clean working trees: the 028b3006 README says three unrelated pages were scrubbed of member names before export, so its `dist/` differs from the committed one by design.
- Any statement that these builds look or behave correctly on devices: no browser was available; layout, animation, touch, keyboard and reduced-motion behaviour are unverified.
- No approval equivalence is claimed between this export and the owner-approved version beyond: it is byte-for-byte the v515 source for the files listed in MANIFEST.sha256.

## Why the original archives were not offered as the game-only download
Both original archives are whole-site exports: the 028b3006 zip holds 292 files (all site pages, admin and lead screens, Academy data, logo file, test and Playwright starters); the 4227f20c zip holds 361 files including internal project notes (`docs/notes/`, `AGENTS.md`), `.bak` copies of two pages and a review text file. They were left unchanged and are kept in the project's `exports/` folder.

## Omitted on purpose
Credentials/settings, databases, lead/customer data, backups (`offline_tiq_premium/backup_20261109/`), support-correspondence notes (IONOS_SUPPORT_COVER_NOTE.md, STORAGE_APPROVAL_REQUEST_9B.md), docs/notes, Academy, admin, lead, shop and payment pages, the Upgrade 6 contract (written after v515), dist/ output, rollback archives, the 1.4 MB logo file (the game draws the approved eagle emblem in code and does not reference a /static file).

## Credential scan result
A text scan of every file in this archive for key, token, webhook-secret, password, private-key and provider-address patterns found only deliberately fake test fixtures (strings such as "whsec_fixture_" plus repeated letters in tiq_premium_core_test.mjs and storage_payment_6b_test.mjs) and one pattern list inside launch_guard_test.mjs. No real credential was found. The scan is a text search, not a guarantee.
