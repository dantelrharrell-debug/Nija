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
- Callers explicitly pass only the Render API and recovery SSH credentials to
  the reusable workflow. The approval JSON is not a `workflow_call` secret and
  is never passed using `secrets: inherit`; do not provision a repository- or
  organization-level copy of `NIJA_RENDER_READONLY_APPROVAL_JSON`.
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
