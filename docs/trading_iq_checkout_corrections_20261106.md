# Trading IQ checkout corrections and separate release review

Review base: main `8225d874bd5f740afa5b26a3f152e4ad8cf71900`;
protected release `b7bbb706af86ca413e2b5ce750216a4ec129a7a0`.
A fresh fetch showed main ahead by one merge commit, release ahead by zero.
No later checkout corrective PR was open at inspection.

## Review findings

| PR #3681 finding | Latest base | Correction in this patch |
| --- | --- | --- |
| Public hosted checkout has no application throttle | Unresolved | Persisted global, trusted-client, owner and attempt quotas before Price or Checkout calls |
| Lost responses/double submissions create extra sessions | Unresolved | Private durable reservation, stable Stripe key/proof, lease and cached redirect |
| Proxy clients share sandbox IP bucket | Unresolved | Explicit direct/proxy identity policy; exact allowlisted peer and single overwritten forwarding address |
| Legacy report cookie rejected | Gateway fixed in `51ab2481a`; hosted route still missing | Hosted fallback to original `__Host-nija-report`; all existing proof/payment/refund checks retained |
| README bypasses staging bootstrap | Already fixed in `d30e7775f` | Preserve guarded `python -m game_sandbox.staging_bootstrap` command |

Comments: https://github.com/dantelrharrell-debug/Nija/pull/3681.
This patch touches educational checkout/report controls only. No deployment,
flags, trading authority, existing customer entitlements, $99 pricing, or free
gameplay is changed. Gateway checkout remains separately authenticated and
unchanged; this does not claim to add durable gateway retries.

## Hosted checkout contract

The first submission without a valid private ownership cookie returns a
same-origin $1 confirmation form and sets an HttpOnly/Secure ownership cookie;
**it makes no Stripe call**. This ensures ownership reaches the browser before
a session can exist. Owner cookie uses SameSite=None to survive subsequent
cross-site top-level game-form submissions; payment/report receipts remain
SameSite=Lax. Exact allowed Origin remains required, but is not treated as bot
identity or abuse prevention. Test actual Safari/browser cookie behavior before
release. Cookie loss or clearing cannot be treated as verified ownership and
requires an authenticated recovery policy, never an automatic replacement charge.

One browser owner + canonical validated five-decision attempt maps to one durable
reservation. Identical replay of those decisions reopens the same checkout,
including from the external origin or same-origin confirmation. It does not buy
the same deterministic report again. Different valid decisions get a distinct
reservation, subject to owner/global quotas. There is no browser-chosen Stripe
key. An immutable random reservation ID produces the provider key; its random
proof is saved before calling Stripe and reused byte-for-byte on retries.

Reservation lease is 120 seconds; concurrent submissions return 409 with
Retry-After. Provider I/O happens outside SQLite write transactions. If a process
crashes or loses the provider response, the committed reservation remains, and
after the lease a retry uses exactly the same key and parameters. At most three
provider attempts are allowed; unresolved reservations older than 23 hours
require operator reconciliation, never a fresh session. This is below Stripe's
minimum 24-hour v1 idempotency retention boundary:
https://docs.stripe.com/api/idempotent_requests.
A saved successful redirect is reused without provider calls. Expired/canceled
checkouts are not automatically replaced. A late result can save the same
session, but conflicting results fail closed.

| Persisted allowance | Limit |
| --- | --- |
| All checkout submissions, global | 300/minute |
| All checkout submissions, verified client | 30/minute |
| Provider attempts, global | 100/hour |
| Provider attempts, verified client | 10/hour |
| Provider attempts, browser owner | 5/hour |
| Provider attempts, one reservation | 3, within 23 hours |
| Total journal reservations | 10,000, then operator review |

Fixed-window limits are shared across workers and survive restarts. Request
buckets older than two hours are pruned. Reservations are not automatically
deleted: deletion could recreate an already charged attempt. Plan retention,
capacity monitoring and authenticated reconciliation before production use.
The journal holds a private browser proof; backups must be private/encrypted.

## Explicit ingress and durable storage prerequisites

These are new **required configuration**, not settings applied by this PR:

- Hosted: `NIJA_GAME_INGRESS_MODE=direct` only for a reviewed direct connection;
  ignore all forwarding headers. If behind a reverse proxy, set `proxy` and
  `NIJA_GAME_TRUSTED_PROXY_CIDRS` to actual network peer ranges. The trusted
  ingress MUST strip incoming X-Forwarded-For and overwrite it with exactly one
  verified original client address. Missing/malformed/multiple addresses or an
  untrusted peer fail closed. A forged Origin is not a client identity.
- Sandbox: same policy using `NIJA_IQ_SANDBOX_INGRESS_MODE` and
  `NIJA_IQ_SANDBOX_TRUSTED_PROXY_CIDRS`. Health probes retain their exact GET
  `/healthz` exemption. Paid report verification and webhook ownership remain
  authoritative. Webhook retains its raw signature check and separate exemption;
  dedicated ingress must bound webhook traffic too.
- Do not apply global ProxyFix to rewrite REMOTE_ADDR before these checks. Review
  Gunicorn/framework proxy settings and verify the actual socket peer. Do not
  allowlist the entire public Internet or guess Render proxy ranges. If the
  platform cannot prove this contract, leave checkout disabled and arrange a
  controlled ingress; do not use direct mode behind an unreviewed proxy.
- Hosted requires a precreated private file `NIJA_GAME_CHECKOUT_DATABASE` beneath
  the non-root mounted path `NIJA_GAME_CHECKOUT_MOUNT`; an actual mount, file and
  parent ownership, private modes, and absence of symlinks are checked. No
  ephemeral-directory fallback. Provisioning/schema creation on that dedicated
  volume, backup/restore, encrypted retention and separate storage approval are
  release work. SQLite FULL synchronization and BEGIN IMMEDIATE serialize shared
  workers on **one service instance/disk**. This is not a multi-node database;
  reject horizontal scale or introduce reviewed shared durable storage first.
- Missing prerequisites deny checkout only. Existing purchased reports continue
  to verify without the new journal, ingress settings or checkout feature flag.
  A legacy cookie never grants access by itself: it must match the session proof
  and pass the exact original $1 product/price, paid charge and revocation checks.

Rollback: disable hosted checkout first through separately authorized operational
change; retain the journal and paid receipts, then revert code if needed. Do not
delete reservations, revert to unprotected enabled checkout, or roll back paid
entitlements. This PR does not perform any operational change.

## Validation

Deterministic tests cover missing policy/mount, bootstrap without provider I/O,
per-client/global/owner/attempt bounds, forged forwarding, independent visitors
behind one proxy, concurrent requests, app restart, lost provider and redirect
responses, exact key/proof/parameter reuse, expired-window denial, and current
and legacy paid-report retrieval with refund denial while checkout is off.
The existing original 72-decision report parity/client tests remain included.
CI explicitly executes hosted tests and triggers for the root payment modules
and tests as well as sandbox paths; the test file is tracked despite the
repository's broad test ignore rule.

Local result: 113 Python tests and 64 JavaScript tests passed. Changed Python
compiled; changed-path detect-secrets and production-module Bandit passed;
`git diff --check` passed. The named runtime-tools-secret_scanning and
codeql_checker tools are unavailable here; exact-head hosted security/CodeQL
remain required. No live provider transaction or browser deployment was tested.

## Separate broad-release concerns

Read-only Render evidence in the confirmed Nija_Trading_Bot workspace
`tea-d37fhe8gjchc73c8eo0g` changes the initial assumption that deployment was
unverified:

| Service | Observed deployment/configuration |
| --- | --- |
| Trading `srv-d98dsr5aeets73fpbaqg` | Manual deploy `dep-dbmo8rp5efls73866a8g` for release `b7bbb706a`, live at 2026-11-06 07:43:02 UTC; auto-deploy off |
| Billing staging `srv-dasmtjfpn0mc73948r10` | Main `8225d874b`, live at 07:41:30 UTC; auto-deploy on each main commit |
| Production billing `srv-dasn1mbbc2fs738036gg` | Latest listed live deploy `e9a33bb2e`, from Nov 5; auto-deploy checksPass on main |
| IQ72 staging `srv-dbmgc7u1egvs73f9i1h0` | Free Python service, no listed disk/health-check path; command directly loads `staging_entrypoint:application`, bypassing guarded bootstrap; auto-deploy off |

These are provider deployment records/configuration, not authenticated trading
certification, runtime behavior proof or payment-route enablement evidence. No
configuration, credentials or deployment was changed by this task. The public
staging process must remain disabled until its actual configuration uses the
reviewed non-root Node/Python bootstrap and private durable disk. Fixing README
does not repair that live service configuration.

1. PR #3681 was merged despite its review-only/no-merge text. Review submissions
   retrieved for it contained only Copilot COMMENTED, no independent approval.
   Obtain accountable independent release/security review of the 84-file delta
   and actual deployed image; branch synchronization alone is not that review.
2. `requirements.txt` now pins scikit-learn 1.5.2 (PR #3676). The older security
   investigation and production checklist still describe 1.3.2 and demonstrate
   1.3.2-to-1.5.0 GradientBoosting load and RandomForest prediction failures.
   Exact 1.5.2 compatibility with authenticated deployed models and representative
   backtesting remain unverified here. Updating the vulnerability pin does not
   establish compatible artifacts. Review actual model load/fallback logs;
   do not silently revert to a vulnerable pin or weaken trading gates.
3. Obtain mandatory CI, CodeQL, dependency, credential-candidate dispositions and
   exact-image container scans. GitHub commit-workflow queries returned no runs
   for the inspected merge heads; the combined-status endpoint returned no
   statuses for the release merge. Those APIs do not establish all checks green
   or prove none ran. Existing security triage has 270 candidates needing review.
4. Confirm trusted production composition-root ownership, thirteen authenticated
   source/account bindings, durable reconciliation/nonce/writer/kill-switch/risk
   evidence and backup/restore on the deployed release. Deployment does not
   authorize live orders. Exact-order approval remains separate.
5. Before any payment release: provision reviewed ingress and journal on the
   correct isolated service, review schema/retention, rehearse backup/restore,
   verify actual hosted checkout/reopen/refund and mobile/browser flows, and
   secure separate owner release approval. Billing auto-deploy on main means
   merging a PR can ship source even while the educational feature flag is off;
   review release control before merge. This corrective PR is not merged or
   deployed by this task.
