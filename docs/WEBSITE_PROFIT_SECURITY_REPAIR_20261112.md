# Website-profit collector security repair: evidence and gates (2026-11-12)

Scope: review-only follow-up to merged PR #3829. This document records observed hosted failures, **not** a waiver, certification, production activation, or claim that vulnerabilities are fixed.

## Reproduced hosted evidence (PR #3829 head c7a62f021bc1e6d7c5e0a7d638803a00d166ba56)

- Website revenue/net profit workflow passed: run 43296539549. Local PR report: 80 website tests passed.
- Security Scanning run 43296539767: Dependency Vulnerability Scan and Bandit passed; Pre-Commit Hook Validation and Secret Scanning failed.
- Pre-commit job 131456246592: report categories `hook_modified_files`, `source_diff_emitted`; failed hook identifiers `bandit`, `check-docstring-first`, `detect-private-key`, `detect-secrets`, `end-of-file-fixer`, `gitleaks`, `name-tests-test`, `trailing-whitespace`. The report is intentionally redacted; investigate the private artifact and exact changed-file set before changing source or baseline.
- Secret scanning job 131456246757: `unbaselined_candidates`, 154 candidates. This is a repository scan result, not proof that 154 new secrets were introduced by PR #3829. Inspect private candidate report under restricted access, distinguish legacy baseline from newly introduced findings, rotate/revoke any genuine exposed credentials before remediation, and never paste values into a PR.
- Artifact Scanning run 43296539864: integrity and license jobs passed; three package scans and four image scans failed. Billing requirements scan job 131456246523 reported 41 GuardDog findings across 9 packages, with scanner exit 1. Rules include network/process/filesystem capabilities in packages such as Flask, gunicorn, requests, setuptools, Stripe, SQLAlchemy and PyJWT. These are triage signals, not automatic malware verdicts. Review private reports, package versions, provenance, and reachable behavior; do not blanket-suppress.
- The collector itself is not invoked by production runtime. No authenticated GA4/Stripe observations or signed closed-month evidence exist from this merge.

## Repair acceptance criteria

1. Inspect the complete private scan artifacts and job logs without disclosing secret candidates or customer data.
2. Attribute each failure to collector changes, inherited repository state, scanner configuration, or an actual vulnerability. Record package/version/CVE and exploitability when applicable.
3. Remediate confirmed issues with minimal source/dependency changes; add regression tests. Preserve fail-closed behavior and least-privilege provider reads.
4. Run focused website-profit tests, pre-commit validation, secret scanning, package and image scans on the new head. Record both successful and failed hosted checks.
5. Do not modify the baseline or weaken security gates solely to obtain green CI.
6. Keep production GA4/Stripe connection, signing, deployment, payments, marketing and trading separately approval-gated.

## Provider collection follow-up (not authorized in this PR)

Verify GA4 property 546929929, its timezone, exact production host coverage, consent and cross-domain identity. Verify the expected Stripe live account and restricted key's actual read permissions. Run `python -m scripts.collect_website_profit_sources` only in a protected authenticated finance environment with credentials injected as environment variables. Reconcile Shopify/Printful, affiliate/other revenue, refunds, expenses, settlement and bank records before signing a complete closed-month envelope. Missing data must remain NULL/UNVERIFIED.

References:
- https://github.com/dantelrharrell-debug/Nija/pull/3829
- https://github.com/dantelrharrell-debug/Nija/actions/runs/43296539767
- https://github.com/dantelrharrell-debug/Nija/actions/runs/43296539864
- https://github.com/dantelrharrell-debug/Nija/issues/3537
- https://github.com/dantelrharrell-debug/Nija/issues/3547
