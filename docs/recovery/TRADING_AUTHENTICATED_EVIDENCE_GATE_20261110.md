# Trading execution evidence gate — DRAFT, not certified

Source: PR #3725 (merged with zero changed files). Runtime claims from November 9 require fresh Render read-back.

## Production-vs-repository reconciliation
- Compare live Render deploy SHA (previously 2466cb3) to current reviewed main SHA; inspect the actual secret-file bootstrap chain without reading or exposing secrets.
- Prove whether scripts/nija_kraken_readonly_history_collector_v441.py is installed in the *production composition root*, with trusted authenticated account-scoped private_read, bounded pagination, deduplication and nonce owner.
- Never fabricate, replay or create an order/fill as proof. Distinguish pretrade readiness from posttrade authenticated fill verification.

## Independent evidence required
- Broker-authoritative open orders, fills, pending closes, ledger, balances, positions and protective-order ID mapping.
- Position synchronization, risk limits and account freshness, operator authorization scope, writer/nonce single-owner proof and kill-switch versus Redis attestation.
- Explicitly record execution_ready, execution_authority, allow_new_orders, trading_fail_closed, proof freshness, and reason codes. Unknown is NOT passed.

## Acceptance and safety
- Run deterministic collector failure tests (API error, incomplete page, stale evidence, duplicate ID, wrong scope, nonce conflict) and startup drift tests.
- Security, branch-policy, CI and artifact scanning must pass or be independently adjudicated.
- Keep allow_new_orders=false and trading_fail_closed=true; no forced activation, deployment or production modifications. Separate owner authorization is required for any live trading.
