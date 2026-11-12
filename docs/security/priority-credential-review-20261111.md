# Priority credential-finding review protocol — November 11, 2026

## State and scope

This review is based on merged PRs #3756 and #3758 and the existing value-free detector summaries. The latter documents 222 unreviewed candidates: 23 private-key markers, 30 basic-authentication candidates, 161 keyword candidates, six base64-entropy and two hex-entropy candidates. These are *detector classifications*, not validated vulnerabilities or cleared false positives. The full baseline-aware scan must remain failing until individually reviewed.

## Review order: 53 priority candidates

1. Retrieve the exact-head, value-free `secret-scan-report.json` from a trusted hosted run. Compare path/line/type entries against the same commit's tracked source. Do not publish values, encoded values, secret hashes, or raw scanner output. Keep the full private review inside the designated restricted security environment.
2. Examine all 23 `Private Key` findings first. For each: identify source ownership, whether the source contains parseable real key material versus fixture or prose, how it entered history, and whether any public/private distribution occurred. A plausible authentic key requires owner-controlled investigation even if current use cannot be verified from GitHub.
3. Examine all 30 `Basic Auth Credentials` findings next. Distinguish synthetic test URLs/headers from working provider credentials; verify potential validity and privileges only via authorized owner-controlled channels. No live authentication attempts by reviewers and no candidate value in GitHub comments.
4. Assign one disposition per **exact candidate identity**: `confirmed-exposure`, `verified-inert`, or `owner-verification-required`. Unsupported guesses stay in the last category. Record only path/line/type, decision rationale, reviewer, and restricted evidence reference. Avoid copying credential-bearing text.
5. For confirmed exposure: invoke the incident owner to revoke/rotate, inspect access logs, update provider secret stores/consumers, and evaluate history-remediation risk. Do not rotate or rewrite Git history in this draft PR.
6. For verified-inert fixtures, prefer replacing misleading hard-coded strings with clearly synthetic data and test again. If source preservation is necessary, add only exact, file-scoped reviewed scanner identities after independent human approval. Never use directory exclusions, broad detector suppression, or auto-baseline acceptance.

## Verified repo-level enforcement

- `scripts/run_baseline_secret_scan.py` pins detect-secrets 1.5.0, scans tracked files, preserves the baseline, returns nonzero on unresolved candidates/errors, and writes no candidate values/digests.
- `.github/workflows/security-scan.yml` enforces the scan and retains sanitized evidence on failure. PR Gitleaks and TruffleHog checks and pre-commit checks are separate defenses.
- This draft adds `category_counts` to the sanitized report and regression assertions; it does not review, suppress, or mark any candidate safe. The scan status and release hold are unchanged.

## Required regression and release evidence

- Run the pinned local regression suite: `NIJA_DEFER_RUNTIME_SITE_HOOKS=1 python -m pytest -q tests/test_baseline_secret_scan_reporting.py`.
- On the exact PR head, check Security Scanning job step outcomes, including Gitleaks, TruffleHog, detect-secrets, Bandit, dependency audit, and pre-commit. Do not interpret infrastructure failure or missing results as passing.
- Inspect artifact/package and container vulnerability workflows separately.
- Compare exact candidate identities and counts with a fresh full tracked-file scan; any new unresolved finding or baseline drift fails closed. The category summary is diagnostic only, not a replacement for path/line/type evidence.
- Require independent security review, authorized credential-owner dispositions, and release-specific certification before any merge or deploy.

## Explicit non-actions

No credentials inspected or validated against live services. No credential values displayed. No baseline exceptions added, no secret rotation, no history rewrite, no approval to merge, no deployment, no payment activation, no broker order or trading authorization.
