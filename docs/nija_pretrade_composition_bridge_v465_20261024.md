# v465: Audited independent pretrade composition adapter

Purpose: make the existing audited v452/v453 evidence validation usable by
NIJA's v450/v456 independent pretrade inspector, **without promoting an order,
changing an execution gate, or claiming broker certification**.

## Why activation is not yet possible

Current production's PRETRADE_INDEPENDENT_CERTIFICATION_V6 says
account_scope_configured=false, collector_installed=false,
producer_status=scope_missing_or_invalid. The pretrade observer is separate
from the old posttrade FILL_VERIFY 1,800-second gate; passing an observation
does not permit new orders. The collector cannot be populated by a config flag.

This change exposes a strict composition-root API:
install_audited_collector(providers_by_account, trusted_provider_ids=...).

* The trusted, separately reviewed application composition root must explicitly
  bind **13 authenticated provider functions** per allowed canonical account.
* Trusted provider IDs come from a separately audited registry, never from
  request data, env booleans, or observations returned by those providers.
* Different authority classes (broker, ledger, writer, operator, risk) must not
  share the same producer identity. Per-account source identity must be exact.
* v452 requires source-specific, account-scoped, independently authenticated
  provenance, complete pagination for broker/ledger fields, and observations no
  older than 60 seconds.
* The bridge re-evaluates timing after sequential provider calls and retains
  the earliest observation time. Failure/partial data raises; the v450
  independent inspector catches errors and returns a redacted refusal.
* There is **no automatic installation or default producer**, and this bridge
  remains diagnostic-only. Never install placeholder lambdas in production.

## Acceptance before any runtime wiring

1. Independently review which live Kraken/Coinbase/OKX/Alpaca client and
   credential fingerprint own the account; verify scopes and permissions.
2. Implement real per-account collectors and register them from one trusted
   composition root, preserving the existing single nonce-writing client.
3. Reconcile the 13 pending platform:kraken ledger close records against
   exchange-authenticated opening orders, exact fills, fees, and position lots.
   A read-only archived ledger with 0 trade rows is NOT proof of no positions.
4. Reconcile existing three tracked JSON positions with current authenticated
   exchange holdings and protect every non-dust quantity with independently
   read-back stop/exit orders. Missing or ambiguous records deny new entries.
5. Verify approved operating capital, writer lease, nonce, duplicate order fence,
   kill switch, risk/circuit breakers, secure independent restore, and account
   authorization. Never infer these from process liveness.
6. Independently review the actual two-phase **pretrade admission** integration
   into the canonical dispatch path. Cold-start pretrade evidence may replace the
   logically impossible "a new fill must exist before the first order" condition
   only if all other facts are freshly verified. Do not replace or weaken strict
   posttrade order/fill verification (1,800 seconds) after a real order occurs.
7. Require full hosted CI, secret scanning, owner/broker/security review and
   separately approved release deployment. Keep production fail closed while
   any prerequisite is missing.

The scope of this PR is intentionally *only* the audited producer adapter. It
does NOT include fake authenticated providers, config changes, live broker calls,
ledger writes, an API-key collector, state-machine mutation, test orders,
kill-switch clears, or new execution authorization.

## Offline verification

Run: python -m pytest -q tests/test_pretrade_composition_bridge_v465.py
Local offline synthetic regressions: 15 passed using mirrored v452/v453
dependencies; hosted CI must independently validate exact repository
dependencies and scan changed files.

Do not claim these tests demonstrate live account certification.
