# Kraken four-source / same-interpreter review gate (2026-11-12)

Status: **REVIEW ONLY — NOT PRODUCTION CERTIFIED**. References #3800 and #3820.

This branch adds offline regression coverage, not a production binding, resolver,
signer, receipt, migration, configuration change, deployment, or trading authority.

| Source | Existing code | Required protected provenance / reviewer |
| --- | --- | --- |
| Ledger | `make_kraken_ledger_evidence_provider` | Independent ledger owner: authenticated account/key attribution, complete history and protective-order IDs |
| Duplicate fence | `RedisEvidenceReader.collect` | Writer authority and independent coverage reviewer: signed complete durable inventory, cutover, nonce and lease scope |
| Operator | `make_general_operator_authorization_provider` | Authorized operator and independent key custodian: two separate Ed25519 roots, signed approval plus fresh active status |
| Risk | `make_kraken_risk_limits_provider` | Independent risk reviewer: atomic, complete, account/key-specific capital/exposure/policy snapshot |

All observations must retain their original timestamps and stricter expiries;
the family collection checks a maximum 60-second age. Redis evidence expires
earlier if the shortest relevant lease/fence expires. No missing provenance
may be inferred from an environment variable or a global status report.

## Protected startup review

1. Read the current Render service release SHA and image digest; compare with
   `main` and the protected release branch. Do not assume merge means deploy.
2. Inspect the complete protected bootstrap privately; it is not in GitHub.
   `os.execvpe` discards prior Python in-memory registration.
3. Identify the *final* Python interpreter running `bot.bot_main.main`.
   Independently review where its trusted composition root would call
   `register_signed_kraken_startup(factory, trust)` before
   `install_from_canonical_startup(manager, strategy)`.
4. Validate real account/API key pins, 13 unique providers, external reviewer
   custody and three genuine signed startup certifications. Never fabricate
   approvals, receipts, identities or evidence.
5. Test absent/revoked/stale/wrong-scope providers and restart/exec handoffs
   offline. A failed source must deny atomic installation.
6. Only after separately approved protected deployment, inspect sanitized
   `KRAKEN_STARTUP_EVIDENCE` logs and 13 fresh authenticated observations.
   Installation is diagnostic, not authorization to trade.

## Validation

Run `python -m unittest tests.test_kraken_source_startup_contract_review -v`
and existing startup/source suites. These are offline structural and process
boundary tests, **not** authenticated runtime certification. Hosted checks
must be read back on this exact PR head.

## Approval gates

No merge, deployment, protected file edits, new signed approvals, Redis writes,
kill-switch clearance, order submissions or activation. Preserve
`allow_new_orders=false`, `fail_closed=true`, and all existing admission
checks. Obtain independent human review and explicit owner approval for any
subsequent consequential change.


## Hosted CI evidence on PR #3827

Head `41a8d27f41918b02fa9ee5d618c4d3aa1461c95e`.
- Main CI: success, run 43294540529. This does **not** prove the newly added unittest was invoked; inspect job steps for exact test selection.
- Zero-Trust CI: success, run 43294540224.
- CodeQL: success, run 43294540151.
- Preflight/lint: success, run 43294540465.
- Import smoke: success, run 43294540493.
- Manual release hold: success, run 43294540211.
- Security scanning: failure, run 43294540269. Secret scan reports 154 unbaselined candidates; pre-commit reports failed hooks: bandit, check-docstring-first, detect-private-key, detect-secrets, end-of-file-fixer, gitleaks, name-tests-test, trailing-whitespace.
- Artifact scanning: failure, run 43294540587. Member-broker GuardDog reports 39 findings across eight packages; package and Docker jobs also fail. Findings need artifact-specific classification, not broad suppression.
- Branch policy: corrected `test/*` branch passed run 43294540140; failing run 43294558802 is attributable to superseded `review/*` PR #3826.

**Unresolved**: No authoritative proof of the four real source dependencies, approved signer custody, same-interpreter registration in protected production composition root, or 13 fresh authenticated collector observations. No independent receipt issuance. No trading authority.

### Remediation boundaries

Security findings should be triaged in a separately scoped security review, preserving scanner enforcement. No global ignore patterns, baseline resets, fabricated attestations, or changes to production safety state. Obtain approval for any consequential production modification.
