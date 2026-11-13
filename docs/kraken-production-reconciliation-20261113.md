# Production recovery verification: 2026-11-13

## Exact runtime

Render service srv-d98dsr5aeets73fpbaqg, workspace
tea-d37fhe8gjchc73c8eo0g, deploy dep-dbrh0sbbc2fs73d2c800 is live on
c16f16c7ce0875aff175cecb74b3329ec5f892eb. Auto-deploy is off.
Latest inspected production logs at 14:49 UTC report collector_missing and
all thirteen observations unavailable. No order authority was changed.

Authenticated Render shell inspected existing private exact-order recovery
receipt 85648218fc7d4c61ae0d94d1ad07b75a.exact.evidence.json. The collection
is successful, with thirteen orders and eighteen individual fills. Its own
flags explicitly deny reconciled lots/fees, verified protective exits,
independent account identity, atomic broker/ledger snapshot and execution.
Successful collection alone does not override those denials.

## Actual order/fill comparison

Read-only SQLite access used file:/data/trade_ledger.db?mode=ro.
Per-order Decimal aggregation compared actual ordertxid-linked fill IDs,
vol_exec, cost and fee with each order and the corresponding pending row.
Quantity comparisons were exact; quote cost/fee comparisons allowed at most
0.0001 in the reported quote unit. This is arithmetic agreement on saved
records, not current broker reconciliation or fee-currency authentication.

| Comparison | Result |
| --- | --- |
| Orders / individual fills | 13 / 18 |
| Exact order-to-fill ID sets match | 13 / 13 |
| Aggregated filled quantities match vol_exec | 13 / 13 |
| Aggregated costs match order costs | 13 / 13 |
| Aggregated fees match order fees | 13 / 13 |
| Pending filled_usd and exit_fee amounts match | 13 / 13 |
| Nonempty matched_position_id on pending rows | 0 / 13 |
| Operational trade_ledger rows | 0 |
| Operational open_positions rows | 0 |
| Operational strategy_order_intents rows | 0 |
| Operational pending_kraken_closes rows | 13, all pending |
| Fills reporting nonzero margin | 6 |

Twelve saved orders use XBTUSD (seven buys, five sells); one sell order uses
ETHUSD:BTNL with six fills. The nonzero-margin fills cannot be relabeled as
long spot lots to fit the existing limited BTC/ETH spot evidence reader.
Order labels alone cannot prove position opening/closing ownership. Complete
opening trades, margin position/financing history, transfers, fee currency,
current balances, remaining obligations and protective-order readback are
still necessary. No opening positions were invented, pending rows cleared,
ledger rows inserted, holdings inferred from zero local rows, or protections
created. Historical receipt contents remain private on the production disk.

## Exact-release security

The exact deployed c16f16c7 Actions checks include:

- CI, CodeQL, isolated collector regressions, dependency vulnerability audit,
  Bandit and build passed.
- Security Scanning run 43440272047 failed. Its baseline-aware scan reports
  152 unbaselined candidates. This does not establish 152 exposed credentials.
  Pre-commit reports failed hooks bandit, check-docstring-first,
  detect-private-key, detect-secrets, end-of-file-fixer, gitleaks,
  name-tests-test and trailing-whitespace.
- Artifact Scanning run 43440272028 failed all four Dockerfile image jobs
  (Trivy/Grype) and GuardDog scans for root, billing and member-broker
  requirement sets. Package vulnerability audits passed; GuardDog capability
  and threat findings still require source/artifact classification.
- Root image output includes Debian packages with affected/fix_deferred
  status and no fixed version, including krb5, util-linux, sqlite, ncurses,
  systemd, perl and redis-tools findings. An apt upgrade alone is not proof
  of clearance. A reviewed patched base/dependency change must be rebuilt
  and rescanned; findings are not waived here.

Sources:
https://github.com/dantelrharrell-debug/Nija/actions/runs/43440272047
https://github.com/dantelrharrell-debug/Nija/actions/runs/43440272028

## Publisher and startup trust

The deployed account risk publisher implementation is present, but this
inspection does not establish genuine measurements, current owner revision,
source mutation/invalidation coverage or protected source registration.
Unresolved margin exposure prevents claiming complete spot-only exposure.
Never supply fabricated zero obligations or relaxed policy to publish green.

Authenticated shell presence checks confirm BOTH files absent:

- /etc/secrets/.render-kraken-startup-binding.json
- /etc/secrets/.render-kraken-startup-root.py

Genuine independent_review, backup_restore and broker_ledger_exits receipts
cannot truthfully be issued before their underlying reviews pass. This work
does not possess verified independent signer custody or a reviewed complete
provider manifest and does not generate substitutes. Provisioning remains
blocked by missing evidence and review, not a requirement to repeat a generic
owner instruction. Production is not certified and all thirteen checks have
not passed. A future exact-release deployment and bounded order approval are
separate steps after all required gates pass.
