# Release format validation recovery — review candidate

The hosted pre-commit report now identifies actual failed hooks. This change repairs the JSON and YAML failures without changing trading formulas, authorizations, risk limits, collector registration, or production settings.

## YAML

An inactive nested workflow had a colon in an unquoted step name. Quoting the name changes no command or execution behavior. Seven existing Kubernetes manifests contain valid multi-document YAML. The existing pinned check-yaml hook now uses its supported multi-document mode; safe loading remains enabled for every document. No unsafe mode, new exclusion, or ignored malformed document is introduced.

The actual pre-commit-hooks 4.5.0 validators pass all 107 applicable YAML files and all 69 JSON files. Malformed later YAML documents and duplicate keys remain rejected.

## Incomplete historical reports

Two committed February reports were truncated in the middle of a value. They cannot be reconstructed from the available fragments:

- `data/alpha_validation/alpha_validation_20260218_141638.json`
- `data/stability_analysis/stability_analysis_20260215_010835.json`

Each file now contains an explicit incomplete-report envelope with `valid_for_certification=false`. The original fragment is preserved exactly as JSON-escaped UTF-8, with its byte length. Decoding that field reproduces the original committed bytes, including the unfinished final field and trailing space. Missing metrics, test outcomes, and approvals have not been invented. These records remain unusable for certification.

The two existing analysis exporters previously opened the destination before serialization completed. Both now call one strict atomic persistence helper. Unsupported values and non-finite numbers fail before a destination is opened. A complete report is written and flushed to a private temporary file before replacement. Serialization, flush, or replacement failures propagate; temporary files are cleaned up and earlier reports are preserved. This is not backup/restore certification or a power-loss durability guarantee.

Rejecting non-finite values can expose an existing undefined statistic as an error instead of emitting nonstandard JSON. No calculation is changed or invalid metric coerced into a passing value. AST comparisons verify that all non-persistence analysis, decision, and readiness methods remain unchanged.

## Validation and release hold

Nine filesystem/integration tests cover finite round trips, unsupported values, non-finite values, failed flush/replacement, both actual exporter methods, and exact preservation of the historical fragments. The full security regression group, including these tests, passes locally: 54 tests and seventeen subtests. The mandatory security workflow runs the added regressions. Both package and legacy sibling-import contexts are covered without importing the bot startup graph.

The previous full scan still blocks 214 unreviewed candidates. This candidate does not dispose of those findings, image/package findings, remaining whitespace-hook failures, missing Kraken identity evidence, collector installation, ledger/exit certification, independent review, or production backup/restore requirements. New hosted checks on the exact candidate and separate release approval remain required. No deployment or order activation is performed.

The candidate also integrates the merged Bandit bootstrap repair from main. The real pinned hook boots successfully against safe synthetic code and rejects the unsafe synthetic probe with B301; the probe is scanned as text and never executed. Combined local checks pass on main base `c26aa02a878a6a40069a606b111ea0f83f4d7145`. This does not constitute an approved production release.
