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
