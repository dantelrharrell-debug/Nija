# Credential-test fixture review

This proposed review classifies exactly 14 keyword-detector identities in three existing test files. It does not classify the rest of the repository or certify production credentials. Independent security review is still required before acceptance for release.

## Source evidence

| Test module | Exact identities | Reviewed behavior |
| --- | ---: | --- |
| `tests/test_kraken_native_runtime_connection.py` | 6 | Short, descriptive labels in credential-alias and account-isolation fixtures. Native exchange transport is replaced by FakeAPI; writer/nonce state and broker-manager publication are mocked. The alias checks run only the existing shell normalization helper with an explicit synthetic environment. |
| `tests/test_account_ownership.py` | 5 | Descriptive personal/business fixture labels used to prove account separation, incomplete-key rejection and disabled staging. Environment mappings are explicitly supplied or cleared. Dashboard requests use the Flask test client and mocked controls/trackers. |
| `tests/test_credential_diagnostics.py` | 3 | Descriptive short/full-alias labels passed to the shell diagnostic helper; assertions require values to stay out of diagnostic output. No broker is contacted. |

Each detector candidate hash was matched to an exact Python AST string literal in its source file, and that literal was matched to the explicitly reviewed fixture set. Repeated occurrences share one exact file-scoped candidate identity. These are static fixture labels, not discovered runtime keys. Test source and fixture literals are unchanged.

The baseline adds only filename, existing detector type and exact candidate hash, marked `is_secret: false`. All previous baseline records and every scanner setting remain unchanged. No detector, whole-file exclusion, regex allowlist, scan threshold, credential or runtime setting changes.

## Validation

- All 46 affected tests and seven subtests pass in an isolated test environment using the repository's Redis/Kraken dependency versions. Socket connect/connect_ex/create_connection are denied during the run; zero network attempts were recorded.
- An initial run lacked the repository's Redis/Kraken dependencies and produced setup errors. Installing those already-declared dependencies in the test environment resolved those setup errors; no application requirements were changed.
- All three complete files pass the pinned baseline-aware detect-secrets hook.
- A new randomly generated synthetic candidate appended to a reviewed file still fails the hook with exit 1.
- An already reviewed fixture value placed in another filename still fails with exit 1. Approval is not global by value or pattern.
- Previous baseline entries and scanner/plugin/filter settings are byte-equivalent as parsed data. Only 14 exact records in three new file groups are added.

The complete hosted scan before this proposal examined 4,009 tracked files and reported 214 remaining candidates with exit 1 and unchanged baseline. This is authoritative evidence from main `3efc734429b6a9ab9b469443c560badbed118c82`, workflow run 43110948358, artifact 13896806335. The downloaded artifact's digest matched GitHub's recorded digest. The 14 dispositions above do not approve the other 200 findings from that snapshot. A fresh complete scan of the final proposal is required; arithmetic is not a scan result.

A fresh full local scan subsequently completed over the same 4,009 tracked files with the proposed baseline: **200 unreviewed candidates, exit 1, baseline unchanged**. The exact reduction is 14. Remaining categories are 139 keyword, 30 basic-authentication, 23 private-key-marker, six base64-entropy and two hexadecimal-entropy candidates. The new review document separately passes the complete baseline-aware file hook. This is a measured reduction, not a clean full-scan result; every remaining candidate stays blocking.

## Release boundary

YAML and JSON validation passed in the latest hosted all-file run. The remaining pre-commit report lists secret/private-key scanners and whitespace/end-of-file corrections; its nonzero status remains enforced. Container and package scans remain separate blockers. No image exception, severity reduction, broad scanner bypass or reconstructed historical evidence is included here.

This change does not install a collector, supply authenticated Kraken identity or ledger observations, change nonce/writer/risk/kill-switch state, reconcile pending closes, certify backup/restore, authorize a deployment or submit an order. Keep new orders disabled and retain separate exact-release and first-order approval requirements.
