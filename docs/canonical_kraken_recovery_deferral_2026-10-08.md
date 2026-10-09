# Canonical Kraken recovery deferral repair

Production commit 695ae159 reports V88 critical Kraken recovery deferred as test isolation. The canonical launcher deliberately sets NIJA_DEFER_RUNTIME_SITE_HOOKS=1 to suppress broad site-import fanout, even after the Render front door unsets it. v88 incorrectly assumes that flag can only appear in tests and skips its independently owned proof-producing recovery chain.

Allow that explicit chain after both canonical launcher flags are present, while retaining deferral in CI and active pytest cases. Keep the v318 prerequisite and all per-module proof requirements. Do not unset the global defer flag or enable broad import fanout. No strategy, position truth, capital TTL, execution proof, writer/nonce/risk/kill-switch or order behavior changes.

Four AST-isolated regression tests exercise the actual function: canonical recovery attempts all modules, CI/pytest stay isolated even with launcher flags, incomplete launcher handoff stays deferred, and pending prerequisites/module proofs remain false. No broker credentials or calls are used in tests.

This restores recovery attempts, not confirmed readiness. Kraken user OpenPositions and platform BTC cost basis remain unproven in production. A missing authenticated final order row cannot be replaced with market prices or synthetic fill evidence. Private customer API deployment is a separate unresolved dependency.

Human review is required before merge because this affects startup recovery.
