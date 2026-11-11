# NIJA authenticated read-only trading evidence — HOLD

Baseline main: `0045a98020039770f653fcee1176f1fdcb061df7`. This package is not trading authorization.

## Verified repository boundary
- `bot/pretrade_independent_attestation.py` pins a single collector snapshot and returns `authorizes_orders=False` unconditionally.
- `tests/test_pretrade_collector_snapshot_20261110.py` already covers missing/replaced collector.
- `scripts/nija_kraken_readonly_history_collector_v441.py` requires a trusted account-scoped private reader; source presence is not runtime installation.
- Do not change existing order dispatch, kill-switch, risk, protective exits, or authorization gates.

## Production evidence required (read-only)
Record current Render service, deployed commit, exact actual startup command, Blueprint command, bootstrap chaining attestation without exposing secret-file contents, collector registration point, canonical broker/account identity, private-read provenance, nonce/writer ownership, fresh order/fill observations, persistent dedup, and broker reconciliation. Compare open orders, historical fills, pending closes, protective-order IDs, positions, balances and ledger. Record independent Redis kill-switch and operator authorization scope. All unknowns are BLOCKED, not PASS.

Last documented Render release: `2466cb384a605d0ce159166f369ba45c6bfc50b6`; it is not assumed current. Document evidence timestamps, expiry, account scope and redacted audit signatures.

## Regression acceptance
1. Missing collector, malformed result, collector replacement and exception: fail closed.
2. Stale/future observation, expired evidence, wrong account, untrusted source, missing provenance: fail closed.
3. Missing or partial broker history, duplicate fill, nonce mismatch, ledger/position mismatch, unresolved protective mapping, Redis kill-switch inconsistency: never authorize orders.
4. Production startup-command drift: report mismatch without changing the secret bootstrap.
5. CI, branch-policy, secret and artifact scans must pass before any release review; existing historical failures cannot be waived by this package.

Run `python -m pytest tests/test_pretrade_collector_snapshot_20261110.py tests/test_pretrade_failclosed_additional_20261110.py -q`.
No new orders or synthetic fill replay. Preserve `allow_new_orders=false`, `trading_fail_closed=true`; deployment and any later activation require distinct explicit approvals.
