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

The latest release diagnostic-redaction fix is integrated into the candidate,
including diagnostic redaction and scoped
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

## Integration limits

This is a source integration proposal. Independent review of the actual
native transport and reviewed source binding remains required. Offline tests
use synthetic data and signers. They establish no production account identity,
complete ledger, current risk snapshot, startup installation, or trading
permission. Hosted checks must pass on the exact candidate commit and image.
No deployment or live order follows from this source change.
