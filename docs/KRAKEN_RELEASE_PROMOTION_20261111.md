# Kraken release-branch recovery candidate — hold for review

Base: `e9b0a9e0b6a1d03ca7056eea2752e16267f90502` on `release/justcall-handoff-only-20261017`.
Source: selected merged fixes from main `0f787f8812a63d3023116e3c5b063c10b9efec80`.

The release branch now contains the approved collector startup backport from PR #3766. This candidate preserves it and supplies the remaining selected history, attestation and validation fixes for that branch. It is not a new service, a change of Render branch, or permission to deploy.

## Promoted behavior

- Canonical bot startup invokes the guarded existing Kraken evidence-binding integration. Only an explicitly registered trusted factory and authenticated receipt verifier can supply the canonical manager, strategy, broker, thirteen reviewed sources, and independent release receipts.
- The reviewed provider registry is validated before provider construction. Observation snapshots remain internally consistent, and any source claiming order authority is denied.
- Kraken history requests preserve individual fill IDs and the reviewed direct-mode wire encoding. Existing reconciliation, nonce ownership, pagination and receipt checks remain authoritative.
- Security validation retains complete secret scanning, fail-closed TruffleHog and GuardDog reporting, actual Bandit-hook verification, and value-free pre-commit diagnostics.
- JSON/YAML repair and atomic analysis-report persistence are carried over unchanged. Historical fragments stay explicitly incomplete and uncertifiable.

Game, checkout, course, website and education-pilot source remains byte-identical to the release base. Dockerfiles, Render configuration, protected start command, credential storage, writer locks, kill-switch controls and order authority are unchanged.

Most promoted files are exact existing main blobs. The candidate additionally enables the existing artifact and preflight workflows for pull requests targeting this release branch and adds connection/negative-evidence tests to the existing Kraken workflow. Every existing rule, error threshold and safety check remains active. No new scanner disposition is added; the baseline is the exact merged public main baseline, including metadata for source paths that are not part of this candidate.

## Validation

Local targeted Kraken/startup/history/attestation regressions pass: 160 tests and three subtests. Changed Python compiles, compliance preflight and diff checks pass. The security regression group passes 54 tests and seventeen subtests, including real pinned Bandit safe/unsafe detection. All 103 YAML and 65 JSON files in this candidate pass the pinned format validators. Changed-file baseline-aware secret scanning passes. The broader native-runtime suite passes 241 tests and 183 subtests; four real Redis nonce tests fail setup because this local environment lacks redis-server. The Docker startup regression also cannot run locally because Docker is absent. These are outstanding validation requirements, not passed or skipped acceptance checks. The hosted workflow retains its actual Redis installation and Docker startup jobs. All mandatory hosted checks must run on the exact candidate, with exact-image security checks and independent review.

## Production acceptance remains outstanding

A merge or deployment does not install a missing trusted factory, authenticate a missing account pin, reconstruct absent ledger lots or prove protective exits. The protected same-interpreter composition root still needs the actual approved source callbacks and independently authenticated review, backup/restore and ledger/exit receipts. Missing observations remain unknown; they are not individually proven failures or passes.

New orders must remain denied until every current account-specific pretrade observation and all release checks pass. Stale execution proof must follow the reviewed commissioning path; it must never be refreshed by rewriting a timestamp. Exact first-order approval remains separate and must identify pair, maximum amount and order type after readiness passes. Autonomous operation requires later execution verification and separate authorization.

Rollback is source-only before deployment. No production data, approvals, ledger, account pins or entitlements are migrated by this candidate. After all gates pass, obtain approval for the exact commit/image and use the existing service's release process; verify its actual deployed commit and protected startup. Keep automatic deployment off.

Before the PR #3766 rebase, the complete local baseline-aware scan of 3,864 tracked files reports 209 unreviewed candidates and exits 1, without changing the baseline: 150 keyword, 30 basic-authentication, 23 private-key-marker and six base64-entropy candidates. This differs from main because the candidate retains the older release's game/website tree; it is not evidence of additional candidate dispositions. No finding has been automatically approved. These findings continue to block release.
