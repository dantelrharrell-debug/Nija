# Kraken startup evidence handoff

Canonical `bot.bot_main.main()` now calls `install_from_canonical_startup`
after publishing the strategy and before starting the core engine. It passes
the existing manager and strategy. This is a diagnostic collector handoff,
not order authorization or proof of a successful deployment.

The protected, independently reviewed deployment composition root must call
`register_reviewed_startup_binding(factory, verify_receipts=verifier)` in the
same interpreter before entering canonical main. Importing a module does not
register anything. No environment-variable factory loader is provided.

The factory receives the actual manager and strategy as keyword arguments and
returns `ReviewedStartupBinding` with those same objects, the manager's exact
connected native platform Kraken broker, the existing thirteen reviewed source
callbacks and their independently approved provider identities. Reuse the
existing `compose_authenticated_kraken_collector_sources` or
`compose_reviewed_kraken_providers` interfaces; do not create a second broker,
nonce generator, writer, ledger, risk authority or order adapter.

The binding also contains the three opaque receipts `independent_review`,
`backup_restore` and `broker_ledger_exits`. The supplied verifier must
authenticate their signatures, expiry, exact deployed release/image, account,
credential identity and reviewed callback registry before returning literal
`True`. This change does not supply a verifier, signing authority, producer
identities, approval records, positive source observations or production
receipts. A placeholder verifier or readiness flag is not acceptable. Registry
copies are frozen before verification; opaque receipt validation remains the
trusted verifier's responsibility.

Only then does the handoff call the existing
`install_reviewed_kraken_collector`. Its existing atomic registration observes
and validates all thirteen providers before replacing the collector. Stale,
future, mismatched, unverified or authorizing observations remain denied. The
handoff never writes execution proof, clears a kill switch, reconciles a ledger
by inference, sends an order, or grants commissioning authority. Later reads
continue to use the existing freshness and admission checks.

Missing registration returns `trusted_startup_binding_missing`. Invalid
bindings/receipts return fixed denial diagnostics without private exception
contents. Failure preserves the existing registry; it does not certify it.
Monitoring startup continues, and existing fail-closed admission and execution
proof gates remain responsible for blocking new orders.

## Release dependencies

This repository hook is not an installed production collector. Before rollout,
the operator must verify that the actual protected startup chain reaches this
canonical module and supplies the reviewed factory and authenticated receipt
verifier in the same interpreter. Without access to that chain and the real
independent sources, production installation cannot be certified.

Retain the existing release requirements: exact-commit/image checks,
independent human review, verified backup/restore, and separate exact-release
approval. Do not replace a protected bootstrap or enable auto-deploy to reach
the hook. Reverting this change removes the handoff without schema or ledger
migrations. Source rollback still requires the normal deployment process.

The offline startup suite uses synthetic observations with the real existing
atomic installer. Its successful outcome demonstrates wiring and denial
behavior only, not authenticated Kraken reconciliation or live readiness.
