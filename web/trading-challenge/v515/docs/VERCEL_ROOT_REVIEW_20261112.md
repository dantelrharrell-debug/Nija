# Vercel deployment-root correction — review only (2026-11-12)

## Scope and source of truth
Existing Vercel project: `nija-trading-challenge` (`prj_C9IE49lnLbO1CE62ZXKBUMu9CZs8`).
Existing GitHub repository: `dantelrharrell-debug/Nija`.
Approved game: `web/trading-challenge/v515` (Vite/React; six challenges times twelve rounds = 72 decisions).

**Set Root Directory in Vercel Project Settings to `web/trading-challenge/v515` for Git-connected deployments**, once separately approved. Framework preset: Vite. Existing `v515/vercel.json` already defines `npm ci`, `npm run build`, `dist`, protective response headers, and only a limited game-page rewrite. Preserve this config; do not replace it with a minimal config. Do not point Vercel to `main.py` or `api_gateway:app`.

The sibling `web/trading-challenge/package.json` launches the *legacy* six-answer HTTP server; it is not the approved 72-decision experience. The standalone v515 build uses `vite build` and has its own locked dependencies.

## Deployment-record caveat
A separately inspected Vercel failure `dpl_6xsRBbYQJipFV9u6SLXJ1pWim5kB` reports `NOW_SANDBOX_WORKER_ROOTDIR_NOT_EXIST`: `web/trading-challenge` was absent from that deployment's uploaded files. This may reflect manual-upload layout rather than a Git-connected repository checkout. Confirm Git source, commit and deployment file layout before changing project settings. A Git-connected project root is relative to repository root; if deploying a prepackaged subdirectory instead, do not prepend its parent directory.

## Review tests
From the **v515 directory** on a reviewed checkout, run:
```sh
npm ci
npm test
npm run build
test -f dist/index.html
```
The new `tests/vercel-deployment.test.mjs` validates the Vite build config, 72-decision invariant, protective headers, API routing isolation, and fail-closed responses for checkout/results/recovery/webhook even with an enabling environment flag. Existing `tests/standalone.test.mjs` verifies pinned game sources and payment holds.

After a separately approved preview deployment, verify: free 72-decision play on desktop/mobile, `/api/health` reports unavailable checkout, paid endpoints return 503, application assets return 200, security headers persist, and no live transactions can occur. Use a reviewed exact commit and hosted CI/security status. A successful static build alone is not production certification.

## Safety and approvals
This PR intentionally does **not** change project settings, `main.py`, trading services, Stripe, payment flags, approved game source, or production routing. **Do not merge or deploy without a new explicit owner approval.** Be aware Git-connected repositories may auto-build branch previews when a PR is opened; any resulting preview is not authority to merge or promote. Production payment functions stay disabled.
