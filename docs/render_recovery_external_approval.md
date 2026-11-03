# NIJA read-only Render recovery approval (single-owner compatible)

## Problem
Render automatically deploys commits to `release/justcall-handoff-only-20261017`.
Previously, `ops/recovery/render_readonly_baseline.json` contained the operator
approval fields. Updating those fields on the auto-deployed release branch
caused a new deployment, invalidating the just-approved deployment identity.
Do **not** modify the committed manifest to approve production.

## Control boundary (this change)
- The committed manifest is a **source-pin template only**. It must permanently
  have `operator_approved=false` and null `approval_reference`, `commit`,
  and `deployment_id`. Its exact source SHA-256 map must match the production
  source files before approval.
- The reusable `.github/workflows/render-production-baseline.yml` job uses the
  `nija-render-recovery-readonly` GitHub Actions environment. It imports the
  *environment-only* secret `NIJA_RENDER_READONLY_APPROVAL_JSON`.
- The two recovery callers forward only the required Render API, SSH and
  `NIJA_RENDER_READONLY_APPROVAL_JSON` secrets **by explicit name**. GitHub
  requires a reusable-workflow caller to pass an environment-scoped secret even
  when the called job declares `environment: nija-render-recovery-readonly`.
  The called job must use the protected environment version. Do not use
  `secrets: inherit`, and never create a repository- or organization-scoped
  copy of `NIJA_RENDER_READONLY_APPROVAL_JSON` (such a copy would undermine
  the environment-only authorization boundary). The `workflow_call` secret is
  marked `required: true` to enforce caller wiring; the verifier still rejects
  an empty, malformed, stale or unapproved record before any Render API or SSH.
  Do not place the secret value in GitHub logs or a public issue.
- A sole repository owner may authorize **read-only recovery diagnostics** after
  deliberate, documented review. Record a genuine owner authorization reference
  separately from Git; do not label it as a second-person or independent human
  review. The independent checks here are **technical**: Render's current
  deployment identity, immutable source hashes and a read-only runtime report.
  A Git push, issue comment, merge, observed SHA or this document alone does
  **not** grant operator approval. Live trading requires its own separate
  authenticated authorization and all independent safety evidence.
- The verifier rejects missing/malformed/duplicate-key approvals, different
  source pins, unreviewed committed manifests, stale Render deployment identity,
  unexpected branch, changed source, unverified instance, or missing SSH access.
  It never clears a stop, writes ledger rows, installs a collector, or authorizes
  an order. `BROKER_EVIDENCE_VERIFIED` and `CERTIFICATION_COMPLETE` remain false.

## One-time administrative configuration (authenticated sole owner)
1. In GitHub `dantelrharrell-debug/Nija` open **Settings > Environments**.
2. Create **nija-render-recovery-readonly**. For a **sole-owner repository**,
   leave **Required reviewers** unchecked; do not invent another user or bypass
   an imaginary second-person requirement. Leave **Wait timer** unchecked if
   unnecessary. You may disable **Allow administrators to bypass configured
   protection rules**. Under **Deployment branches and tags**, select
   **Selected branches and tags** and allow only
   `release/justcall-handoff-only-20261017`.
   Save and confirm that these settings are applied. Do not claim a second
   human independently reviewed this environment.
   A created environment is not, by itself, a recovery approval.
3. As the authenticated owner, independently inspect Render's **currently
   live** commit and deployment ID (not merely the Git branch's head), and
   confirm the service, branch, source SHA-256 pins, and that the action is
   specifically **read-only recovery inspection**. Record an actual, dated,
   nonsecret **owner-readonly authorization reference** in a private audit
   record. A CI pass or a Git issue comment alone is not authorization.
4. Only **after your deliberate read-only authorization**, through this
   environment's **Secrets** (not repository or organization secrets), store
   `NIJA_RENDER_READONLY_APPROVAL_JSON`: a JSON copy of
   `ops/recovery/render_readonly_baseline.json` with the **same exact field
   names and `source_sha256` map**, changing only:
   - `operator_approved`: JSON boolean `true`, representing the owner's
     actual approval **of read-only recovery**, not trading;
   - `approval_reference`: the genuine nonblank owner-readonly audit ID;
   - `commit`: the already-live 40-character Render Git commit SHA;
   - `deployment_id`: that same live `dep-...` deployment ID.
   Do **not** invent an ID, guess a SHA, or have an AI agent silently authorize
   on your behalf. Do **not** put this approved JSON in Git, public issues,
   chat, or a workflow artifact. This is authorization metadata, not a Kraken
   API key or any live-trading approval.
5. After the owner's recorded read-only approval, dispatch the *existing*
   read-only recovery workflow from the exact production release ref. Verify
   the environment branch restriction and the exact approved current deployment,
   independent Render API evidence, and pinned source/runtime digests. Inspect
   the sanitized verification artifact. A successful baseline is **not**
   evidence of Kraken order safety or trading authority.
   A successful baseline only permits separately approved diagnostic work.
6. If Render deploys a different commit or instance, the existing approval
   becomes invalid. Revoke it; repeat the owner's explicit read-only review
   before updating the environment secret. Never auto-approve the latest SHA.
   Remove the approval secret when the authorized inspection is finished.

## Troubleshooting the named environment approval secret

- A baseline that stops with `independent_environment_approval_missing`
  **before reaching Render** can mean that the caller did not forward the
  environment secret, despite the secret being present in GitHub Settings.
  Both entrypoint workflows must explicitly pass the exact named approval
  secret to the reusable baseline. Review the sanitized `baseline / verify`
  job output; GitHub displays a masked value when the secret is available.
  Never diagnose this by printing, comparing or exposing the actual JSON.
- A successful baseline permits read-only diagnostics only; it is neither a
  Kraken credential check nor trading approval.

## SSH runtime read-only triage

A valid environment approval and exact Render deployment proof can advance the
baseline to the SSH stage while **still failing closed**. The original verifier
collapsed all nonzero SSH exits under `ssh_runtime_inspection_failed`, even
though the read-only remote inspector intentionally exits 2 when it has missing
evidence. The revised verifier distinguishes:

- `ssh_transport_or_authorization_failed`: SSH returned exit 255; inspect the
  matching **public key** in Render Account Settings, service compatibility and
  network access. Never paste or rotate a private key based only on this code.
- `ssh_connection_or_command_unavailable`: SSH binary or transport could not
  be run or timed out; diagnose network and execution path without weakening the
  approved host fingerprint.
- `ssh_remote_report_invalid` or `ssh_remote_report_exit_mismatch`: remote
  output did not match the strictly bounded read-only protocol.
- `ssh_runtime_deployment_identity_mismatch`: the running service/commit did
  not agree with the pinned deployment; do not repin without owner review.
- `runtime_evidence_incomplete` with optional **fixed allowlisted**
  `ssh_runtime_evidence_failures`: SSH reached and ran the protected instance
  inspector, which reported unresolved runtime evidence. Never print raw
  stdout, stderr, account IDs, balances, credentials or diagnostic payloads.

All of these are blocking outcomes; even a fully successful SSH baseline is
not Kraken ledger, protective-exit or 13-source trading certification.
After merging a diagnostic-only release change, Render auto-deploys a **new**
commit. Reconfirm the deployment and have the owner independently review and
repin the environment-only JSON; do not reuse or auto-renew the old approval.

## Render-managed stdout/stderr evidence (read-only fallback)

[Read-only recovery #25](https://github.com/dantelrharrell-debug/Nija/actions/runs/41665330600)
confirmed that SSH remote execution worked but produced the single failure
`current_process_log_evidence_unavailable`: the inspector searches local
regular files under `/app`, while Render captures live application stdout/
stderr via its separate managed log service. This is **not** proof that
application logging stopped.

With independently pinned deployment/source and exact SSH runtime identity,
the verifier may supplement **only this one exact local-log gap** using an
authenticated, bounded Render logs API query. It uses the existing API key,
fixed account owner, service ID, and the SSH-observed instance ID; `type=app`,
a maximum of 100 rows, and a narrow window after the inventoried process
start. At least two distinct, separated heartbeat events must come from the
specific runtime heartbeat logger with explicit `READ_ONLY_RECOVERY`,
`independent_attestations=unverified`, `allow_new_orders=false` and
`canonical_gate_unchanged=true`. Response labels must match the exact
service, instance, and app-log type. Stale, inconsistent, ambiguous or
unavailable evidence continues to fail closed. No raw app logs, account data
or credentials may be printed or included in verification artifacts.

Render instance-scoped log timestamps corroborate a live service instance;
they do **not** identify the emitting process PID or authenticate any Kraken
orders. Successful corroboration satisfies only the operational log-presence
check, not broker-readiness, ledger, protective exits, writer/nonce authority,
collector certification, kill switch clearance or live-order authorization.
The verifier must never create/modify local production log files merely to
pass this test.

References: https://api-docs.render.com/reference/list-logs and
https://render.com/docs/logging.

## Prerequisites and limitations
- Existing `RENDER_API_KEY` and
  `NIJA_RENDER_RECOVERY_SSH_PRIVATE_KEY` credentials must be configured by
  authorized administrators; they are not accessible through issue comments.
- The recovery verifier does not make brokerage private calls. A separately
  authorized monitoring rate budget, exact account identity, and existing
  nonce-owner control remain required before reading Kraken private history.
- Verify GitHub environment configuration in **Settings**, not from
  workflow YAML. For a sole owner, **no second-person human review is claimed**;
  this narrowly authorizes technical read-only baseline inspection only.
- This procedure is **not general live trading approval**. Independently
  authenticate the ledger, protective orders, Redis writer/nonce/idempotency,
  kill-switch clearance, risk limits, backup/restore, and all 13 collector
  sources before any separately authorized live orders.

## Non-negotiable scope separation

- The read-only environment approval **cannot** clear an active kill switch,
  fabricate missing attestations, reconcile the ledger by assertion, mutate
  orders, install unreviewed production providers, or enable live execution.
- Production order admission remains blocked until Kraken order/fill history,
  position and protective-exit readback, durable ledger, writer/nonce fencing,
  risk limits, stop clearance and **all 13** independent evidence sources are
  verified as current and tied to the right account. Independently authenticated
  operator execution authorization remains a separate requirement.
- Missing Render API/SSH secrets, an unverified account, a missing or malformed
  approval record, mismatched SHA/deployment, stale evidence, or unfinished
  reconciliation must fail **closed**. Never weaken these checks simply to get
  the workflow to pass.
