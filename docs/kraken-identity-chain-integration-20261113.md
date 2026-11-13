# Kraken identity chain integration and recovery evidence — 2026-11-13

## Implementation awaiting independent review

PR #3858 now threads the explicit `native_signed_request_v1` selection from
`ReviewedCanonicalKrakenSources` through permissions, account identity,
balances, open-order reconciliation, protective readback and position sync.
The frozen `ReviewedLedgerBinding` carries the same selection; canonical
construction denies a different ledger method before reading any source.
The default remains `response_echo`. Nothing selects a production alternative
implicitly or installs a collector.

The permission reader requires independently approved account and credential
pins when selecting native proof. It verifies the same fresh native request
signature and returned account fingerprint, retains required read permissions,
and still requires unrestricted queryFrom/queryTo. A missing expiry proves
validity at that authenticated read only. Present bad expiry or echoed keys
still deny. Ledger identity uses the same exact transport proof, actual
response timing and frozen-result comparison on both sides of collection.
Ledger accounting, supported assets, history completeness and protection
requirements are unchanged; this integration does not make margin accounting
supported by the existing spot-only ledger reconciliation contract.

The latest protected release merge b5bbbb12f84e3aa587b820aae3007b654efc3e54
is integrated into the candidate, including diagnostic redaction and scoped
readback-test isolation. Its fixture accepts the explicit strict-default
method and rejects unsupported methods, rather than leaking a global stub.

## Executed verification

- 488 tests pass together across native request proof, permissions, ledger,
  canonical/native startup composition, balance, open orders, protection,
  position sync, diagnostics, timing, identity recovery, signed startup
  receipts and protected startup root. Tests use synthetic data and signers.
- Eight affected provider suites also passed separately (113 tests).
- Changed-file detect-secrets 1.5.0 baseline hook passes; no baseline edits.
  Synthetic wrong-key/invalid-pin fixtures and inspected public diagnostic
  format/placeholder lines have narrow documented inline exceptions. No
  credential material was accepted or added to the repository baseline.
- Bandit 1.7.5 with repository configuration reports zero findings in the
  ten changed production modules. Python compilation and diff checks pass.
- Local runtime-tools-secret_scanning and codeql_checker are unavailable.
  These alternatives do not claim those commands ran. Mandatory hosted
  checks on the new commit/image and independent security review are pending.

Kraken's official REST authentication documentation was checked against the
request signature formula used by the proposal:
https://docs.kraken.com/exchange/guides/rest/authentication
This does not establish that Kraken guarantees the missing response fields
or independently approve NIJA's native transport and trust boundary.

## Actual production work and limits

Authenticated Render inspection confirms service srv-d98dsr5aeets73fpbaqg
remains on c16f16c7ce0875aff175cecb74b3329ec5f892eb, with auto-deploy off.
Both protected startup files are absent. Fresh logs report no installed
collector and all thirteen observations missing.

An online SQLite backup of /data/trade_ledger.db was made before any repair:
`/data/kraken-history-recovery/pre-repair-4e0eabdc12734122b464c4486989e565.sqlite3`.
The snapshot integrity_check returned `ok`; SHA-256:
`195d080e27f3450457e9f80ba51e651d03b836a03f14db1f0b1e70d8d20df595`.
This is a local snapshot, not an off-host restore certification.

A single private expiring cursor-history request was submitted under
collector.lock for platform:kraken, max_pages=100, using the running canonical
broker's existing recovery consumer. Request ID:
`20a17d1c1df1473da18e5d81cb24757e`.
The consumer claimed it; inspected progress reached TradesHistory read 4.
No completion receipt existed at that observation. Do not replay the claim
or create a second broker/nonce writer while it runs.

Existing October 12 authenticated audit archives were inspected read-only.
One contains 1,483 distinct ledger entries, including margin, rollover,
deposit, transfer, withdrawal and trade types. Across both audit directories,
542 trade IDs were discoverable. Six of the eighteen saved exact-fill rows
have postxid references found in these archives. Archive summaries explicitly
say all_account_reconciliation_complete=false. References in older private
responses are candidate historical links, not proof of current account,
complete opening basis, current holdings, financing totals or protection.
No operational ledger rows were inserted, pending rows cleared or holdings
inferred from an empty local ledger.

## Remaining release gates

The old PR head c0635a12 passed collector tests, CI, CodeQL, imports, build,
preflight and balance checks. Its Security Scanning run 43448001158 failed
baseline candidates and pre-commit; Artifact Scanning run 43448001046 failed
container Trivy/Grype and package GuardDog checks. Dependency audit and
Bandit passed. These results do not certify the new candidate.

GuardDog member-broker output reports 39 findings across Flask, requests,
Gunicorn, setuptools, SQLAlchemy and Stripe; capability findings need exact
artifact/source review, not a blanket exception. Root container findings
include affected/fix_deferred Debian packages without listed fixed versions.
No scanner was disabled, broad baseline accepted, unsupported CVE waiver
issued or security success asserted.

Real risk publication remains dependent on complete current account capital,
spot/margin exposure, outstanding obligations, approved policy and mutation
revision coverage. Historical archives or generic governor configuration
cannot serve as a current authenticated account snapshot.

Independent review, backup/restore and broker/ledger/exits receipts must be
issued by actual authorized reviewers only after the underlying work passes.
This session has not verified independent signer custody or a complete
reviewed production provider manifest. No approval receipt or protected
startup file was fabricated. No deployment or order authority was changed.
