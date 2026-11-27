# Existing Trading IQ preview client integration

Status, 2026-11-05: implemented on a review branch; no IONOS installation,
Render deployment, live payment enablement, or customer charge in this change.

## Implementation

`preview-controller.mjs` orchestrates the existing `SandboxReportClient`.
`preview-panel.mjs` is a React factory accepting the existing game reducer state
and original report component. It sends only mode, difficulty, day and ordered
72 action/stop choices to the existing isolated backend. Reports come only from
the protected report endpoint. It never computes an entitlement in the browser.

The game remains free. No run is created until an adult explicitly chooses the
optional USD 1 test checkout. One pending operation is shared across double
clicks. A saved run is resumed before attempting Checkout. An old immutable run,
missing cookie, pending webhook, invalid purchase or provider error does not
cause a replacement run or second charge. The backend retains the durable
per-run Stripe idempotency and refund/dispute controls introduced in #3642.

`/report` now serves a same-origin return page. It does not trust URL payment
claims. It resumes cookie ownership, requests the protected report, and displays
the original server-generated HTML in a sandboxed iframe. Each download performs
another entitlement/refund check. A page refresh falls back to the saved opaque
run ID and still requires the HttpOnly cookie. Only the four named browser
modules are served under `/sandbox-ui/`; server files/databases are excluded.
The original React panel uses the original report component, without a new
report format. The existing $99 course and trading processes are untouched.

Ownership is the existing browser-bound capability, not a new account system.
A lost/expired cookie or a different device remains locked; authenticated
cross-device recovery is not implemented. Contact support without paying again.
Downloaded files cannot be revoked after delivery. New refunds/disputes block
subsequent server access/downloads, as in the existing backend.

## Install into the matching isolated UI copy

Prefer installing in the editable exported existing game source:

```jsx
import {makeSandboxReportPanel} from './preview-panel.mjs';
const SandboxReportPanel = makeSandboxReportPanel(React);
// Inside the EXISTING game component, alongside its existing completion UI:
<SandboxReportPanel game={state} Report={OriginalReportComponent} />
```

Use the actual reducer state (`screen`, `restored`, `mode`, `level`, `dayNum`,
`decLog`), and existing report component (`report`, `preview`, `onClose`).
Serve the existing free UI and `/sandbox/`, `/sandbox-ui/`, `/report` from one
HTTPS origin. Never embed this against cross-origin IONOS cookies or put Stripe
keys into the client. The API factory does not install the website at `/`.

A deterministic compiled-build installer is also supplied for development:

```sh
node game_sandbox/install-preview.mjs INPUT_GAME_ASSET NEW_OUTPUT_GAME_ASSET
```

It requires the exact current public `TradingIQChallenge-B_br_2w4.js` bytes,
refuses overwrite and any different source hash, and adds the panel using the
actual game state and its original `ze` report component. Put the generated
asset only into an isolated copy of that website build, retaining its same-name
asset reference and matching other original assets. This is a temporary,
version-specific development adapter; source integration is preferable before
production. The existing Coming Soon and sample-preview sections remain intact;
the added panel explicitly labels itself test-only. Do not publish this build.

## Current evidence

- Repository base inspected: `6c3f8bf59a02aa08107a5f50df89258ce030a02a`.
- IONOS support message dated 2026-11-05 16:33 UTC read directly. No automatic
  processor-to-IONOS database link is supplied by the provider.
- Current public website entry: `index-CaA2tz2p.js`; game asset above. The old
  `TradingIQChallenge-xoOHPSFe.js` returns 404. The current 9,725-byte pure game
  reducer exactly matches `tests/fixtures/ionos_served_ui_reference.mjs`.
- The installer was applied to a separate local copy of the current game asset.
  Syntax passed and both reducer and original report-component bytes remained
  unchanged. No editable latest IONOS preview source was obtained.
- 67 Python tests pass, including real API ownership, return-link denial,
  signed simulated webhook, refund and replay tests. 64 JS tests pass, including
  the original reducer completion-to-client bridge and both parity suites.
- Bandit, changed-path detect-secrets scanning, compile and diff checks pass.
  The specifically named runtime secret-scanner and CodeQL executables are not
  available locally; hosted required checks must still run on the PR head.
- Local HTTPS development setup prepared with the existing website assets and
  patched game. Browser execution is UNVERIFIED: Playwright's Chromium executable
  is absent and its download returned invalid archives. No phone/tablet/desktop
  visual verification or hosted Stripe checkout is claimed by these tests.

## Verified hosting dependencies — do not bypass

The original owner-selected **Nija** workspace (`tea-d3qjmmc9c44c73cqvpug`)
still has its sole service suspended with suspender `billing`. That paid
provisioning dependency remains unresolved.

Read-only inspection also found an already-existing dedicated
`nija-iq72-staging` service (`srv-dbmgc7u1egvs73f9i1h0`) in the previously
confirmed **Nija_Trading_Bot** workspace (`tea-d37fhe8gjchc73c8eo0g`). It has
manual deploys and a Render deployment marked live at commit `827e2ba`, but:

- Its HTTPS `/healthz` actually reports `staging_holding`, `environment=disabled`,
  `checkout_available=false`, `live_payments=false`.
- It is a free Python service with no attached persistent disk and no configured
  health-check path. This differs from the reviewed Docker Node 22 + Python,
  single-instance, dedicated-disk Blueprint. Node availability is unverified.
- No protected Stripe environment values were requested or exposed, and no new
  service, disk, alternate workspace or deployment was created in this work.
- Dedicated sandbox signing-secret/API-key installation and webhook subscription
  readiness remain unverified. An operational disabled health endpoint does not
  establish any of those prerequisites.

Before hosted end-to-end verification: resolve the billing hold for the selected
paid staging plan, or explicitly approve a concrete alternative workspace/plan;
provision the reviewed isolated durable storage and Node runtime, install protected
test-only credentials and a separate webhook, and install the matching UI copy.
Then test hosted Checkout/webhook, refresh/reopen, cancel, lost cookie, replay,
refund/dispute, disk restart/off-host restore, and 375/768/1280 browser layouts.
The current test-only backend rejects live keys regardless of flags. Production
release and any live payments require their separate release checks and owner
authorization. No billing-suspension workaround was attempted.

Rollback: remove the preview-panel insertion/revert this review commit; keep
`NIJA_IQ_SANDBOX_ENABLED=false`. No migrations or production state edits occur.
