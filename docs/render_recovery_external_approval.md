# Separate reviewed read-only recovery approval from Render release deployments

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
- No approval is valid without a real independent operator action and recorded
  review reference. A repository push, issue comment, automatic merge, observed
  Render SHA, or this document does **not** provide operator approval.
- The verifier rejects missing/malformed/duplicate-key approvals, different
  source pins, unreviewed committed manifests, stale Render deployment identity,
  unexpected branch, changed source, unverified instance, or missing SSH access.
  It never clears a stop, writes ledger rows, installs a collector, or authorizes
  an order. `BROKER_EVIDENCE_VERIFIED` and `CERTIFICATION_COMPLETE` remain false.

## One-time administrative configuration (independent human required)
1. In GitHub `dantelrharrell-debug/Nija` open **Settings > Environments**.
2. Create **nija-render-recovery-readonly**, and configure *required reviewers*
   who are independent of the operator proposing a deployment. Enable
   **Prevent self-review** and **disallow administrator bypass** where
   supported. Restrict deployment branches to the exact production release.
   **Do not add the approval secret unless those protections are confirmed.**
   An empty environment may be created automatically by a GitHub workflow
   without protections; its existence alone is not evidence of review.
3. Separately verify in Render which commit and deployment ID are **live**, and
   that the approved service, branch, source hashes and read-only recovery
   purpose are correct. Confirm the operator has reviewed all relevant changes
   and recorded the nonsecret independent approval reference.
4. Through GitHub's protected environment **Secrets**, store
   `NIJA_RENDER_READONLY_APPROVAL_JSON`: a JSON copy of
   `ops/recovery/render_readonly_baseline.json` containing exactly the same
   fields and `source_sha256` map, but with:
   - `operator_approved`: JSON boolean true, **only after actual approval**;
   - `approval_reference`: actual nonblank independent review record ID;
   - `commit`: the **already live** 40-character Git commit SHA;
   - `deployment_id`: that exact live `dep-...` ID.
   Never store this approved JSON in Git, issues, comments or chat. It is
   operational authorization metadata, not a Kraken API key or trading approval.
5. Only after independent review, dispatch the *existing* read-only recovery
   workflow from the production release ref. Environment review and exact
   runtime checks must pass. Inspect the sanitized verification artifact.
   A successful baseline only permits separately approved diagnostic work.
6. If the deployment changes, revoke/replace the environment approval after
   renewed review. Never simply copy the new SHA into the approval secret.
   Remove the secret when the authorized observation window ends.

## Prerequisites and limitations
- Existing `RENDER_API_KEY` and
  `NIJA_RENDER_RECOVERY_SSH_PRIVATE_KEY` credentials must be configured by
  authorized administrators; they are not accessible through issue comments.
- The recovery verifier does not make brokerage private calls. A separately
  authorized monitoring rate budget, exact account identity, and existing
  nonce-owner control remain required before reading Kraken private history.
- Protected environment review must be verified in the repository settings,
  not inferred from CI passing or code in this pull request.
- This procedure is **not general live trading approval**. Independently
  authenticate the ledger, protective orders, Redis writer/nonce/idempotency,
  kill-switch clearance, risk limits, backup/restore, and all 13 collector
  sources before any separately authorized live orders.
