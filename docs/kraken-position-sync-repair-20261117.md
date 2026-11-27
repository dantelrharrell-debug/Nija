# Position-sync receipt stability repair

Status: independently peer-reviewed engineering candidate; hosted checks and
human review remain required before merge. Base source:
`6774fe96eb8ca9bf59c8508fa0f6bb9fcfa8bec2`.

## Defect and bounded repair

`kraken_ledger_evidence.observe` creates a fresh UUID `evidence_id` for every
successful read. `kraken_position_sync_evidence.observe` previously compared its
two complete ledger dictionaries. Consequently, the canonical native ledger
reader could report unchanged, fully reconciled positions twice and still be
rejected with `position_sources_changed` solely because its receipt IDs differed.

The 11-line production change validates an optional top-level receipt identifier
and normalizes its value only in a detached comparison copy. Its presence must
remain consistent. Every other supplied field remains compared: snapshot digest,
revision, scope and source attribution, supplied key/account fingerprints,
original timestamps, expiry, positions, orders, reconciliation flags, provenance
and unknown metadata. Nested fields named `evidence_id` remain compared too.

The source receipts retain their fresh IDs, and the position-sync result still
gets its own new ID. Consistently ID-free legacy ledger interfaces remain
supported; malformed supplied IDs and changes in field presence deny. No source
timestamp, ledger row, cached receipt or identity binding is rewritten.

## Verification

The position-sync and native ledger suites passed **125 tests**: 62 position-sync
cases and 63 ledger cases. A second agent independently reran the same tests with
an empty environment, Python site startup suppressed, a stub application package
and network connection/name-resolution primitives denied; all passed.

The positive integration test uses the actual read-only native ledger provider,
an isolated SQLite ledger and a synthetic broker. It verifies distinct original
receipt IDs, identical substantive snapshots, unchanged database bytes, preserved
oldest timestamps/expiry and `authorizes_orders=false`. The identical test fails
against the clean base source with `position_sources_changed`.

Negative cases cover persisted revision/as-of changes, stale history, account/key
provenance conflicts, changed positions and order terms, other metadata changes,
malformed receipt IDs and changed ID presence. Changed-file Gitleaks,
detect-secrets and Bandit each report zero findings. Compilation, private-key
checking, the existing reviewed-source validator and diff checks pass.

After integration with the reviewed flat-account protection repair, a combined
12-module run passed **508 tests** under the same empty-environment, startup-stub
and denied-network conditions, with repository conftest hooks disabled. It covers
both repaired providers, native ledger reads, collector composition, native and
canonical source construction, identity proof, atomic multi-account registration,
startup evidence binding, signed startup receipts and pretrade validation.

## Pins and operational limits

No repository source pin, secret baseline, provider identity or approved account
binding was changed. Neither modified source file is bound by the existing
reviewed-secret source manifest, and no embedded reference to either original
complete-file hash was found. The reviewed position-sync module SHA-256 is
`375bfa69f6956e7cd8851c93c090b4228c6c9f9529c9b0f8748e9d8ae980aec5`.

This repair adds no broker request, collector installation, schema migration,
position adoption or order authority. It does not establish actual ledger
completeness, account permissions, production reconciliation, backup/restore or
protective-order execution. The native full-collection request budget and
60-second freshness constraint remain separate operational requirements.

Before deployment, the exact candidate release/image and protected source
ownership still need genuine review and valid release/image-bound startup
receipts. Existing receipts cannot approve a changed release. Human review under
AGENTS.md, mandatory hosted checks and separate production authorization remain
required; live orders require their independent authorization.
