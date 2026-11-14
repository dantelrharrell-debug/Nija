# Collector connection: margin reconciliation blocker

Inspected protected release `65e7482c4c245d6380f07884f3386882235ad87e`.
This is an offline diagnostic correction, not production installation or approval.

## Verified findings

- The production shell inspected during this conversation reported release
  `328c3fbc1c9e39898684ed15e3c297c437cc5976` and both protected collector files absent.
- Production logs sampled November 13 at approximately 4:15 PM Pacific reported
  `collector_installed=false`, thirteen missing observations and `allow_new_orders=false`.
- The existing November 13 reconciliation report records six nonzero-margin fills.
  Those historical records were not re-read or updated by this change.
- `bot/kraken_ledger_evidence.py` supports long BTC/USD and ETH/USD spot lots only
  and explicitly rejects margin history. Matching order totals cannot remove that restriction.
- The v489 gap audit previously omitted margin classification from its report.
  It now counts explicit nonzero margin separately from missing or malformed margin,
  reports fixed reconciliation blockers before pair normalization, and retains all
  existing non-certification flags. Neither zero margin nor matching totals certify spot basis.

## Validation

- Protected root, canonical factory/native pair, signed receipts, startup binding
  and risk publisher: 222 tests passed locally.
- Four-source construction and ledger/Redis/operator/risk readers: 199 tests and
  462 subtests passed; seven Redis-server-dependent tests skipped.
- Corrected gap audit: six tests plus two subtests passed; also passed unittest discovery.
- Changed Python files compile; diff whitespace validation passes.
- These are local offline checks, not authenticated production evidence or independent review.

Exact base-release hosted checks: CI, CodeQL, collector/history regression,
secret scanning, dedicated Bandit and dependency vulnerability checks passed.
Pre-commit still fails seven hooks; Docker scans and package behavioral scans fail.
The value-free pre-commit log does not identify file-specific findings, so this
inspection does not attribute those failures to particular source files.

- https://github.com/dantelrharrell-debug/Nija/actions/runs/43526283598
- https://github.com/dantelrharrell-debug/Nija/actions/runs/43526283556
- https://github.com/dantelrharrell-debug/Nija/issues/3800

## Required completion sequence

| Work | Evidence required | Responsible role |
| --- | --- | --- |
| Margin ledger support | Complete authenticated opening/closing, financing, transfers, fees and current obligations; reviewed separate accounting implementation with exact fill/position links | Broker/accounting integration engineer and independent reviewer |
| Durable intent inventory | All submission/retry routes and cutover boundary audited; complete unresolved-intent inventory under the canonical Redis writer/nonce owner | Runtime engineer and independent reviewer |
| Account risk publication | Current atomic capital, spot/margin exposure, pending commitments, limits and original timestamps | Runtime/risk owner |
| Operator/status trust | Real designated signer identities, public roots, current signed authorization and revocation status | Owner-designated signing authorities |
| Backup restoration | Approved off-host backup destination, verified isolated restore and current artifact identity | Backup custodian and independent verifier |
| Protected source | Actual canonical objects bound by resolve_sources; complete source ownership review, not an always-true callback | Integration engineer and independent reviewer |
| Signed manifest | Genuine independent_review, backup_restore and broker_ledger_exits receipts bound to exact source/release/image/account/key/provider IDs | Existing authorized signers |
| Rollout | Successful exact-release/image checks, independently reviewed package, approved provisioning and deployment | Deployment owner |
| Verification | Final-interpreter registration, atomic installation and all thirteen fresh observations; preserve disabled orders | Runtime operator |

The designated reviewers, signer custody, approved off-host destination and complete
margin evidence are not established by the available repository evidence. Do not
generate replacement signers or a passing manifest to fill those gaps. The proposed
diagnostic patch neither runs the audit against Kraken nor changes the live ledger,
protected files, startup chain, credentials, nonce ownership, deployment or order controls.
