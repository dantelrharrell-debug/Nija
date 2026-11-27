# Priority credential review queue

The full tracked-file detect-secrets 1.5.0 report now carries `priority_review_locations` in addition to the original `findings` and `category_counts`. This is a deterministic subset of the already-redacted path/line/type triples: `Private Key` first, then `Basic Auth Credentials`. It contains neither candidate literals nor hashes and cannot change the scanner's exit code or baseline.

The historical merged review (#3758) reported 23 private-key and 30 basic-authentication candidates out of 222 still unresolved findings. **These are not verified safe.** Fresh counts must come from a full exact-commit scan, not this note.

## Required reviewer action

1. Retrieve the latest sanitized `secret-scan-report.json` from the complete hosted workflow at the exact commit and check `exit_code`, `outcome`, and `baseline_would_change`.
2. Compare the number of priority locations to the sum of the two corresponding `category_counts` values. Any mismatch is an investigation blocker.
3. Examine every corresponding source location in a restricted environment with designated security personnel; source snippets that could contain credentials must not be posted in PR reviews or issue comments.
4. Assign an exact per-candidate disposition: `confirmed-exposure`, `verified-inert`, or `owner-verification-required`. An unverified finding stays blocking.
5. For a confirmed exposure, the credential owner handles provider-side invalidation, access-log review, new secrets in approved secret stores, downstream consumer updates, and an assessed history-remediation plan. Do not rotate through CI or PR comments.
6. For inert examples, prefer rewriting them as plainly synthetic test data, then apply independently reviewed exact-identity exceptions only if genuinely needed. No blanket suppression or automatic baselining.
7. Run baseline regression tests, complete secret scan, Gitleaks, TruffleHog, pre-commit, package and container scans on the exact reviewed commit. Maintain all release and trading gates.

This change is review instrumentation only. It certifies no credential, code release, paid checkout, or live order. It does not run hosted scans, merge or deploy.
