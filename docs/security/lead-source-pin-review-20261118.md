# Lead storage reviewed-source mismatch — 2026-11-18

Status: **REVIEW REQUIRED; NOT APPROVED FOR PRODUCTION**.

## Reproducible failure
GitHub Security Scanning run 44133962001, job 134218304358:
`tests/test_exact_source_secret_review.py::test_review_adds_only_the_exact_142_reviewed_identities` fails with
`tests/test_nija_lead_storage_preflight.py=committed_source_review_pin_mismatch`.
The baseline scanner then fails closed with `scanner_error`; this is **not** evidence of secret clearance.

## Source comparison
Compared `tests/test_nija_lead_storage_preflight.py` at earlier commit
`6774fe96eb8ca9bf59c8508fa0f6bb9fcfa8bec2` (blob `12dbcc7acd1d9abfff3cd2692a5aab9a1ea4e8a6`)
against `main` on 2026-11-18 (blob `34887bbb7d7414555cafc20a6c4a5b06abb15dfa`).

Observed changes:
1. Synthetic forwarding URL changed from `https://hooks.zapier.com/hooks/catch/secret_value` to `https://hooks.zapier.com/hooks/catch/123456/syntheticQA_token/`.
2. Diagnostic redaction assertion changed from `secret_value` to `syntheticQA_token`.
3. Added `test_rollback_journal_refuses_sqlite_and_preserves_files`, asserting that a rollback journal prevents SQLite opening and leaves disk contents unchanged.

The existing exact-source manifest `docs/security/exact-source-secret-review-20261117.json`
contains a source identity for this test file and an isolated-test-fixture entry at line 160.
These changes appear consistent with synthetic fixture and storage-safety coverage, but
**the source comparison is not an independent security approval**.

## Required reviewer decisions
- Confirm the URL and token are synthetic, not usable production credentials.
- Confirm the rollback-journal test cannot access live storage and that the test remains offline.
- Review the exact diff and current file contents for unintended changes.
- If approved, update only the affected source identity using the existing exact-source review process; retain all reviewed entries, detector settings, and fail-closed behavior.
- Run the exact-source review tests, baseline secret scan, full pre-commit, Security Scanning and Artifact Scanning on the candidate branch.
- Resolve unrelated Docker/package scan failures separately; do not suppress them.

No secret-scanner bypass, production activation, live payment, trading order, or manifest fingerprint change is included in this review record.
