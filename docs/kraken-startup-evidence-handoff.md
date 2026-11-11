# Kraken startup evidence handoff

Canonical `bot.bot_main.main()` now calls `install_from_canonical_startup`
after publishing the strategy and before starting the core engine. It passes
the existing manager and strategy. This is a diagnostic collector handoff,
not order authorization or proof of a successful deployment.

The protected, independently reviewed deployment composition root must call
`register_reviewed_startup_binding(factory, verify_receipts=verifier)` in the
same interpreter before entering canonical main. Importing a module does not
register anything. No environment-variable factory loader is provided.

Registration must occur after the last process replacement, inside the final
canonical Python interpreter. A registration made before `os.execvpe`, a shell
handoff, or a new Python process is lost. Preserve the ledger recovery bootstrap
and canonical entrypoint chain; add the reviewed binding at the final Python
composition boundary rather than registering in the earlier restore process.

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

### Production observation: November 11, 2026, 23:35–23:44 UTC

Read-only Render inspection identified the existing service
`srv-d98dsr5aeets73fpbaqg` in workspace `tea-d37fhe8gjchc73c8eo0g`.
Deployment `dep-dbqfl6on74is73c24ki0` reports commit
`e1b0736cfe77665b30208d301bcb50b9d1d33a53`, live at 23:34:34 UTC.
At 23:35:30 UTC the running startup hook reported
`trusted_startup_binding_missing`. At 23:44:47 UTC independent certification
still reported `ready=false`, `collector_installed=false`, and all thirteen
observations missing because `producer_status=collector_missing`. These are
missing observations, not thirteen independently confirmed safety failures.
Separate current logs retained `verification_stale` and `allow_new_orders=false`.

The dashboard command is `python -S /etc/secrets/.render-ledger-bootstrap.py`.
Read-only AST inspection (without executing that script or printing credential
values) identified bootstrap SHA-256
`24c993b6f8a46989953bfe14f9f8cc0304a2117475cabc36e8875d289399b0dd`.
Its final handoff is
`os.execvpe('bash', ['bash', 'scripts/render_entrypoint.sh'], child_env)`.
The inspected script did not name the startup binding registration or module.
The live missing-binding diagnostic confirms registration was absent when the
canonical hook ran. Another deployment of this same code alone cannot supply it.

The remaining correction requires real production callback bindings, approved
provider and account/credential identities, and an authenticated receipt verifier
registered in the final interpreter. The three receipts must cover independent
review, backup/restore, and broker/ledger/protective exits for the exact deployed
release/image and callback registry. Neither this observation nor synthetic
tests supplies those receipts or proves any callback's authenticated result.

The existing validator must accept fresh authenticated evidence from all thirteen
providers before pretrade certification. Then a separately authorized bounded
commissioning attempt must produce genuine matching order/fill/fee, ledger and
protective-exit evidence to replace stale execution proof. Heartbeats, cached
positions, timestamp rewrites, and successful HTTP health checks cannot do so.
Exact-commit hosted security checks also remain release dependencies: the
observed deployed commit has failed container/package, secret and precommit jobs.
Render currently reports auto-deploy enabled; this read-only review did not
change it, the startup command, credentials, safeguards or order permissions.

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
