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

A previous revision submitted one explicit private history-recovery request
using the deployed existing-client protocol. Its fixed request ID is permanently
single-use, and the page budget is 100 per endpoint/pass. The current workflow
only inspects that existing request and cannot submit a new one.
It verifies the reviewed request implementation's source hash and preserves all
claims and receipts. When a claim has no terminal receipt, it performs a
nonblocking shared lock probe and reports whether the collector lock is busy or
free. A busy lock is not a completion or progress certificate. Never force-unlock
or replay a claimed request. Repeated workflow runs only report
pending/claimed/terminal status for this request; they never replay it or create
a new request ID. History responses remain private on the Render disk. This is
read-only broker collection, not independent certification or trading activation.

The first cursor request (`91cefe76c2c7d7164608bb4ffb195532`) completed with
`api_failure` at TradesHistory. Its claim and failure receipt are preserved.
After reviewing that terminal failure, the operator selected the existing offset
implementation for a separate explicit request (`997eae3f9df551e06ffab7a9cf0dc60d`,
`use_cursor: false`). This is a deliberate compatibility attempt, not an automatic
fallback, a replay, or a certification. It also has a permanently single-use ID.

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
