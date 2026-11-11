# Kraken read-only recovery research — 11 November 2026

Software review only. No deployment, order, collector registration, account change
or trading authorization. Private runtime findings are excluded from this document.

## Current primary sources

- [TradesHistory](https://docs.kraken.com/api-reference/account-data/get-trades-history):
  supports cursor pagination and consolidate_taker, default true. The existing
  collector's fixed 50-record pages and explicit offset/cursor choice are retained.
- [Executions](https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/executions):
  account-specific authenticated snapshots; snap_trades defaults false and includes
  the last 50 fills when enabled. This alone is not full historical completeness.
- [REST authentication](https://docs.kraken.com/exchange/guides/rest/authentication):
  increasing nonces are per API key. Reuse the existing serialized private reader.
- [Invalid nonce explanation](https://support.kraken.com/au/articles/360001148063-why-am-i-getting-invalid-nonce-errors-):
  concurrent calls and arrival ordering can cause failures. This research alone
  does not establish nonce failure in any running service.
- [AddOrder](https://docs.kraken.com/api-reference/trading/add-order): validate=true
  validates without trading in the matching engine. It is not a fill proof.
- [Reconnection](https://docs.kraken.com/exchange/guides/websockets/reconnection):
  reauthenticate, obtain snapshots and reconcile state, with bounded backoff.
- [REST rate limits](https://docs.kraken.com/exchange/guides/rest/ratelimits):
  history reads consume API budget. Developer/support rate tables differ in their
  stated weights; no rate limit or conservative operator budget is weakened here.
- [Key permissions](https://support.kraken.com/articles/how-to-create-an-api-key-on-kraken-pro):
  distinguish read permissions from trading/withdrawal permissions. This patch
  changes neither keys nor their permissions.

Spot and Futures docs were distinguished during research. Older support history
examples describe offset pagination; compatibility decisions use the current
Spot endpoint reference. No private API payloads or runtime identifiers are quoted.

## Correction

The collector omits consolidate_taker and therefore relies on the exchange default.
Per-execution reconciliation needs individual fill identifiers, so the correction
explicitly requests consolidate_taker=false for TradesHistory only. The flag is
preserved on every page and both repeat-verification passes. The request allowlist
accepts only the fixed false value. Direct krakenex forms send lowercase "false";
gateway JSON keeps the boolean false. Other endpoints, nonce ownership, request
counts, retries and page budgets are unchanged.

This is an evidence-quality correction. It does not prove that any particular
private receipt was consolidated or that consolidation caused an activation denial.
Reading old fills cannot refresh their broker event time. Neither a successful
transport connection nor validation-only order can certify an execution.

## Verification

Ten synthetic regression cases cover individual IDs, subsequent pages, both
pagination/transport modes, input/nonce isolation, preserved event timestamps and
API rejection without retry/fallback. An additional real krakenex signing/form
test intercepts POST before any network call.

250 local tests pass in the existing isolated workflow groups (236 + 14), covering
history, identity, reconciliation, wire format, independent pretrade failures and
cold-start/posttrade policy. Changed Python compiles; Bandit, changed-file secret
scanning and diff checks pass. Hosted checks and independent review remain required.
No scanner or safety gate is removed. No new production dependency is added.

The independent OpenOrders test suite installs an identity-module stub during
collection. Its existing workflow deliberately runs it in a separate Python
process; preserve that isolation rather than combining it with real-identity tests.

## Release and operator requirements

- Review changed source and any exact-source digest/approval bindings independently.
  Protected diagnostic approval pins are not auto-rewritten by this patch.
- Verify the canonical broker, account scope, private reader and nonce owner.
- Supply real independently reviewed evidence providers; source presence or health
  booleans do not establish trusted collector installation.
- Reconcile pending orders, individual fills, native protective IDs, positions,
  balances, ledger and durable duplicate inventory using authenticated readbacks.
- Preserve the separation between pretrade controls and genuine posttrade proof.
  No fake fill, replayed timestamp, nonce shortcut or forced activation is permitted.
- Require actual hosted test/security results and release review before deployment.
  Failed statuses without executed steps are not successful source scans.
- Production deployment/activation remains an operator-controlled process. This
  assistant does not place trades or enable unattended live trading.

No trading strategy, position sizing, risk/exit behavior, admission, kill switch,
startup composition root, approval signing or production state is modified.
A larger unaggregated history may exceed the existing page cap and must fail closed.
Rollback is a normal source revert; no database migration is involved.
