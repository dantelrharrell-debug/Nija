# Trading IQ staging recovery — 11 November 2026

Base inspected: `44ea9dee31db6479a481e650e9d9cd069f82fc88`.
No production changes, live payments, real orders or customer charges.

## Confirmed CI blocker

GitHub's annotation for CI job `130581727542`, run `43037947570`, states:

> The job was not started because your account is locked due to a billing issue.

The CodeQL jobs on the same main SHA also have no executed steps. A retry of the
existing minimal runner diagnostic `42957322995` produced job `130614625582`
with no steps and the same explicit billing-lock annotation. Changing application
code, reducing tests, changing runner labels or disabling scanners cannot clear
this account restriction. The owner must resolve the GitHub account billing lock;
then rerun the minimal runner diagnostic before the full release checks.

Do not interpret the current failed statuses as completed vulnerability scans.
Earlier genuine scanner findings remain subject to their own checks after runners
work. No payment method or GitHub account setting was changed here.

## Verified Render state

The original selected Nija workspace is no longer suspended for billing. That
corrects the historical November 5 provisioning blocker; it does not authorize
spending or establish successful provisioning.

The separate free `nija-iq72-staging` service in Nija_Trading_Bot still runs
commit `827e2ba`, before merged client PR #3665. Its actual `/healthz` responded
on 11 November with `staging_holding`, `checkout_available=false`, and
`live_payments=false` after a longer request allowance. Earlier 15/25-second
requests timed out; they did not establish an application crash. Logs show
Gunicorn start/stop cycles, not a verified payment-enabled deployment.

That service is Python/free with no attached persistent disk or configured health
path. It cannot host the approved enabled sandbox. The reviewed plan remains one
new dedicated Node+Python Docker service, Starter compute, one private 1 GB disk,
manual deploys and /healthz in the originally selected Nija workspace. A provider
plan must be reviewed and cost/apply approved before provisioning; never convert
or reuse production billing, course or trading resources.

## Concrete correction in this branch

The enabled entrypoint previously built the API without installing the actual
same-origin UI. `preview_assets.py` now loads an independently pinned manifest and
only public, allowlisted files from an already integrated existing UI export.
Missing assets, changed bytes, traversal, private extensions, symlinks and wrong
game-manifest identity prevent startup. Verified bytes are cached, so replacing
files after validation cannot change what is served. No source fetch or scoring
rewrite occurs at runtime. `/` redirects to `/trading-iq-challenge`; API, assets
and the report return route share one HTTPS origin. Its static CSP permits the
existing same-origin modules without adding CORS or exposing private files.

Disabled operation and health remain available without a UI package. Enabled
health can only report `ui_installed=true` after verified installation. Existing
private-mount, non-root, ownership, ingress, Stripe test-mode, CSRF, one-per-run
checkout and entitlement/refund checks remain intact.

## Exact UI package contract

Put the already reviewed and client-integrated existing 72-decision web build in
`game_sandbox/private_ui/` within the dedicated Docker build context. Obtain this
from the original source/build owner; no new game is required. Do not insert the
newer TIQ12/Upgrade 6 game into this older 72-decision contract.

`manifest.json` contains exactly:

```json
{
  "version": 1,
  "game_manifest": "<PublishedGame().digest>",
  "files": {
    "index.html": "<SHA-256 of index.html>",
    "assets/<existing-built-asset>.js": "<SHA-256 of those bytes>"
  }
}
```

List all required public files, at most 256 files and 32 MiB total. Only index.html
and allowed assets/ extensions are served; manifest.json, Python files, databases,
credentials, unlisted files and unrelated routes are never served. Configure
`NIJA_IQ_SANDBOX_UI_ROOT=/app/game_sandbox/private_ui` and independently review/set
`NIJA_IQ_SANDBOX_UI_MANIFEST_SHA256` to the manifest's SHA-256. Hash checks establish
byte identity, not scoring parity or design approval; original-source parity and
browser acceptance remain separate mandatory gates. No latest editable IONOS
export or complete matching frontend build was obtained in this work.

## Local verification and limits

98 Python tests pass across the existing service, source pins, provider receipts,
staging/rootless preflight, return API and 12 new asset/startup regressions. The
64 original JavaScript client, orchestration and parity tests pass. Changed Python
compiles, Bandit and changed-file secret scans are run before pushing.

Four browser cases are prepared in `tests/test_game_sandbox_browser.py`: original
server-generated report at 375/768/1280 widths; owner-only return, page refresh,
report download, refund after display, pending payment and stolen-link denial.
They call only a loopback HTTPS fixture and FakeStripe, never external services.
They are wired into the existing sandbox workflow without reducing other checks.

Browser execution is still unverified locally: Chromium is installed but startup
is denied by the host (`socket() failed: Operation not permitted`). No sandbox
escalation or security workaround was attempted. CI's existing browser install can
run these checks after the GitHub billing lock is cleared; a browser pass must not
be claimed before that happens. Docker/container execution and CodeQL are also
unavailable locally; their existing CI jobs remain required.

## Completion order

1. Owner resolves the GitHub billing lock; minimal runner diagnostic executes.
2. Exact-branch unit, browser, container and security checks pass, followed by review.
3. Obtain and certify the matching existing UI build; supply the pinned package.
4. Review and approve the concrete isolated Render plan and its recurring costs.
5. Verify private disk ownership/mount, Node, protected test API/signing credentials,
   reviewed ingress identity and a dedicated Stripe test webhook. Never repoint the
   $99 course's webhook. No credential values belong in Git or chat.
6. Authorized hosted staging deploy; exercise real test-mode Checkout, signed
   delivery, ownership, refresh/reopen, cancellation, refund/dispute and restore.
7. Separate production checks and explicit live-payment authorization.

Rollback: revert this branch and keep NIJA_IQ_SANDBOX_ENABLED=false. There are no
schema migrations, provider setting edits or new billing/processor accounts.
