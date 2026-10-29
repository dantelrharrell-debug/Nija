# Alternative Render recovery access

The GitHub-hosted runner checks its own DNS/TCP route to the Render Oregon SSH
endpoint, then uses a dedicated SSH credential to run a fixed read-only preflight
through `command python -S -`. It verifies the deployed preflight module's exact
SHA-256 before loading it directly, avoiding application startup imports. It
opens the real SQLite ledger in read-only/query-only mode and emits only integrity
status and an allowlist of fixed technical issue labels. Counters, rows, holdings,
account identifiers and credential values are never printed.

It does not deploy, restart, modify trading controls or ledger records, install
the independent certification collector, or execute arbitrary input. Network reachability is
reported separately from authenticated access. A passing network job alone is
not proof of SSH authentication or collector installation.

## One-time credential setup

An authorized account owner must generate a dedicated Ed25519 SSH key on a
trusted device, register the PUBLIC key in Render Account Settings → SSH Public
Keys, and save the PRIVATE key as the encrypted GitHub Actions repository secret
`NIJA_RENDER_RECOVERY_SSH_PRIVATE_KEY` in `dantelrharrell-debug/Nija`.

Never put a private key in chat, a repository file, an issue, a workflow input,
or a log. Do not reuse a GitHub dependency/deploy key. This runner requires a key
that is available non-interactively; it does not support a passphrase prompt.
Registration grants SSH access and must be completed or approved by the owner.
No account key or Actions secret is created by this PR.

## Run and interpret

The feature-branch push performs the initial probe. If credentials are missing,
the authenticated job intentionally fails with a fixed setup message. After
owner setup, rerun the failed job and inspect its result. A manual dispatch is
also defined for when the workflow is available on the repository default branch.

The approved PR #3491 was merged and deployed as commit
`37cf08a504a0ea31401aefbdd3aa71d13e943b5d`. That deployment interrupted the
unfinished full-history attempt `997eae3f9df551e06ffab7a9cf0dc60d`; its claim
remains preserved and is never replayed. The earlier cursor request
`91cefe76c2c7d7164608bb4ffb195532` failed with `api_failure` at TradesHistory;
its claim and failure receipt remain preserved too.

The current workflow verifies exact source hashes for the deployed history
request handler and repaired exit observer. The post-deploy single-use cursor
probe `d7baa71731e633d1c6f4c9848505ab98` returned `api_failure` at TradesHistory
with the newly captured reason `invalid_arguments` at 13:53:26Z. A separate
operator-selected offset probe `97dbb6dc01e97936829e0e3656fdbcf1` successfully
crossed that API boundary and stopped at its deliberate one-page budget at
13:59:25Z (`page_limit`, TradesHistory). This establishes offset compatibility;
it does not establish the cause of the cursor-parameter rejection or complete
historical reconciliation.

After reviewing both terminal receipts, the operator selected the explicit full
offset request `aec7c56e2aa9cff292f1f6ffe94829d4`, with the previously approved
100-page budget per endpoint/pass. Its submission requires the preserved cursor
failure and bounded offset receipt, including an observed first-endpoint page
requirement within the approved budget. This remains one immutable single-use
request. It is not automatic fallback, replay, or trading certification. All
prior claims and receipts remain preserved.

The private request is created exclusively under the collector lock after
checking that no other recovery request is queued. Repeated workflow runs only
inspect the same immutable request ID. When a claim has no terminal receipt,
a nonblocking shared lock probe reports busy/free; a busy lock alone is not a
progress certificate. Fixed allowlisted API failure reasons can be reported
without upstream free text, credentials, holdings, or account identifiers.
All broker reads use NIJA's existing client and nonce/rate controls. The runner
never changes ledger rows, orders, protections, or trading authorization.

The SSH server fingerprint must match Render's published Oregon Ed25519
fingerprint, checked October 29, 2026:
`SHA256:KkZPgnApmttFYSkdJsCi7B01sgZPMI6kY53MDbbanGM`.
The runner refuses a mismatch, verifies host keys strictly, and deletes temporary
credential files at exit. It has no checkout step and grants only contents:read
to its GitHub token. The dedicated SSH secret is exposed only to its SSH step.

References:
- https://render.com/docs/ssh
- https://docs.github.com/en/actions/security-for-github-actions/security-guides/using-secrets-in-github-actions

## Remaining recovery work

Once the preflight identifies blockers, review the complete production repair command
before adding it to a separately reviewed workflow. Do not change this probe to
accept arbitrary shell input. Complete the genuine ledger, broker, writer,
operator and risk evidence, then install the audited collector in the canonical
running process. No readiness flag or shell marker can replace that evidence.

## Verified access result

Run 40868246451, attempt 2, authenticated successfully and returned the fixed
`NIJA_SHELL_ACCESS_VERIFIED` marker after owner credential setup. This proves the
GitHub runner access path works; it does not certify the ledger or enable trading.
