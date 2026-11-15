# NIJA Foundations $99 — scoped security triage (2026-11-15)

## Scope and release hold
Read-only evidence review of the isolated course sandbox at Render service `srv-dbc4oe5g1s2s73925fb0`, source merge commit `edebbd100ae429e922477a7b09fadf065df06d64` (PR #3932). This document is evidence and remediation planning **only**; no environment settings, entitlements, Stripe endpoints, secrets, database rows, or Kraken controls are modified. Do not merge or deploy this documentation PR without independent review.

## Successful tests, not production certification
- Foundations course delivery workflow 43676796408: 143 passed; 47 warnings; test job sets `NIJA_COURSE_DELIVERY_ENABLED=false`.
- Branch policy, manual release hold, CodeQL, CI, zero-trust, threat-modeling and image-build workflows returned success on the PR head.
- Render reports sandbox deployment `dep-dbsj5vei0phs73da57v0` live at the approved merge commit.
- The production course hotfix is independently deployed at `8c34e2da00541e7e596b8bc6bbdd2475c6066cfe` on `srv-dasn1mbbc2fs738036gg`. Neither deployment is proof that the course ZIP is installed or a full TEST checkout succeeded.

## Failing checks and exact evidence
1. Security Scanning workflow 43676796573:
   - Pre-commit job 132698610172: `hook_modified_files`, `source_diff_emitted`; nine hooks identified in its report, including Bandit, detect-secrets, gitleaks, whitespace and EOF.
   - Secret-scanning job 132698610194: 124 tests passed, 1 failed. `test_exact_source_secret_review.py` identified `committed_source_review_pin_mismatch` for `tests/test_course_sandbox_isolation.py` and `tests/test_tiq72_commerce_integration.py`. The follow-on scanner result was `scanner_error`, candidates=0, exit=2; this **does not** constitute secret clearance.
   - The review manifest `docs/security/exact-source-secret-review-20261113.json` includes one synthetic/test-fixture Secret Keyword entry for each affected file. Retain all 142 reviewed entries, 78 file identities, the original detector configuration and fail-closed checks. The reviewed file digest is stale; an unreviewed digest replacement is not approved.
2. Artifact Scanning workflow 43676796581:
   - Billing requirements GuardDog job 132698610230: 9 packages, 41 capability/threat findings, 0 scanner errors; packages reported include PyJWT, Gunicorn, Flask, requests, setuptools, SQLAlchemy and Stripe. Evaluate provenance, actual package behavior and exploitability; do not automatically suppress.
   - Dockerfile scan job 132698610015: Trivy and Grype high-or-higher vulnerabilities. Triage the specific affected image/base packages, fixed versions, and applicability; do not broadly upgrade the trading stack.
   - Build Artifact Integrity Check passed, but does not waive the package/image findings.

## Narrow remediation plan
1. Independently inspect the *full committed bytes* of both synthetic test fixtures, historical reviewed candidate contexts, baseline identities and actual source diffs. Revalidate candidate classifications before updating source-review pins. A digest-only change without review is prohibited.
2. Correct any actual pre-commit formatting/hooks failures in a separate scoped source PR. Do not disable or downgrade hooks.
3. Investigate GuardDog findings and Docker CVEs in the **billing** runtime separately from unrelated trading images. Record exact package, severity, exploitability and fixed-version rationale with no undocumented exceptions.
4. Repeat all mandatory exact-head checks after changes. Do not infer success from source tests alone.
5. Complete isolated Stripe TEST purchase -> signed webhook -> durable entitlement -> simulator-only Resend delivery -> guarded access -> refund/dispute -> unrelated-purchaser access, using `delivered@resend.dev` only. Confirm private bundle SHA and private database isolation before any purchase.
6. Independently verify production `/course-portal/readyz` boolean fields and preserve production rollback `dep-dbsij8dg1s2s73fa0uf0` (`e9a33bb2eab43f8119b2c83f756fd5440d901ea1`). HTTP 200 alone is insufficient.
7. Obtain separate explicit owner approval before production deploy, Stripe webhook edits, live billing activation, or entitlement mutation. Kraken remains unchanged.

## Release decision
**NO-GO for live $99 customer activation.** This PR contains only a reviewable evidence record and remediation plan, not a fix, completed security sign-off, or authorization to deploy.
