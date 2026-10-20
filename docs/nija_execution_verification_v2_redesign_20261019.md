# NIJA execution-verification v2 — redesign proposal

**Status: REVIEW ONLY.** No current production gate, trading authority, order-routing permission, broker credential, or ledger should be changed by this proposal. It requires independent risk/security review, validated account-state evidence, and a separate controlled deployment plan.

## A. Root cause confirmed in NIJA source and production

NIJA's preactivation_readiness_convergence_v16_patch.py requires a genuine recent broker order/fill (stage ORDER_VERIFY/FILL_VERIFY, execution_probe provenance, <=1800 seconds old) as a condition of setting execution_ready. The engine is not allowed to dispatch orders while that gate remains false. A healthy idle bot may thus require a trade to authorize trading: a circular startup dependency.

2026-10-19 live logs reported execution_proof=verification_stale, producer=missing, trading_fail_closed=true. The old confirmed-fill timestamp is not evidence of PRESENT permissions or account readiness. Independently, the Kraken BABY-USD 0.00142000 position has unverified acquisition basis, and capital publication can fluctuate between 3/3 and 0/3 valid brokers. These independent blockers cannot be concealed or bypassed.

The preflight_operational_ready_observed boolean already exists in v16/v450. It is telemetry only, NOT a substitute for the current execution_ready gate. Pending PR #3200 adds a separate observability-only classifier, not trading authority.

## B. Architecture decision

Split the single global execution marker into THREE independent layers:

1. **PRE-TRADE OPERATIONAL PREFLIGHT:** authenticated read-only broker/account identity, permissions, current balances, open orders, positions, accepted current capital, authorized live deployment, strategy/risk policy, verified protective exits, kill switch, writer lease and nonce. A last trade or fill is NOT required. A passing preflight is necessary but by itself does NOT grant permission to trade.
2. **PER-ORDER EXECUTION EVIDENCE:** an order that separately passes reviewed authorization has an immutable intent, unique client order ID, correlated broker order ID, authenticated broker ACK/status, and zero or more individually identified fills. An ACK is not a fill; there need not be any fill while an order is merely working.
3. **CONTINUOUS RECONCILIATION:** broker open orders, trades, fees, positions and balances are reconciled against the durable NIJA ledger. Gaps, timeouts, orphan executions, unknown cost basis, stale snapshots and missing exits quarantine unsafe new exposure. A valid fill on one order does not grant authority to another order.

The last-unrelated-fill age must never decide operational preflight readiness. Freshness is attached to the relevant live account snapshot, lease, risk and individual order, with explicit versioned venue policy.

## C. Non-negotiable preflight predicates (for the exact tenant/account/portfolio)

All must be explicitly TRUE and CURRENT; unknown or stale means NOT READY:

- Independently recorded customer/operator live-trading authorization. Presence of API credentials alone is not approval to trade.
- Authenticated account and portfolio identity and correct key permissions to query orders/fills, manage needed orders, and cancel. No withdrawal privilege is required.
- Current read-only authenticated account, open-order, balance, buying-power and position snapshots.
- Capital publication accepted and fresh, including all registered brokers when using the platform's three-broker readiness policy; do not weaken v270.
- No unmatched exchange orders/fills, ambiguous orders, unresolved ledger gaps or unexplained transfers. Unknown BABY-USD basis must remain quarantined until real history validates it.
- Risk and strategy configuration current, live-mode approval, minimum notional/precision/market checks, approved account scope and maximum exposure.
- Protective exit coverage **verified against broker orders for outstanding exposure** under approved strategy rules. A dust exclusion or "coverage ready" log is not proof of an exchange-side order.
- Distributed single-writer lease and fencing generation, nonce sequencing, current writer heartbeat, clear kill switch, healthy broker and stable clock.
- Security and account isolation: tenant A's fill/proof may not authorize tenant B's orders.

No recent unrelated trade required. Conversely, an old genuine fill cannot compensate for missing current broker state.

## D. Account/order state machines

### Per-account
DISCONNECTED -> READ_ONLY_SYNC -> PREFLIGHT_CANDIDATE -> ELIGIBLE_FOR_REVIEW
and only after separately reviewed migration/authorization -> LIVE_ELIGIBLE.

Unknown or unsafe facts -> QUARANTINED, with new orders disallowed.
Idle periods with no signals/fills are normal: keep current account read-only checks, not an artificial recent-fill dependency.

### Per-order (durable transaction-bound)
INTENT_PERSISTED -> SUBMIT_ATTEMPTED -> ACKNOWLEDGED/WORKING
-> PARTIALLY_FILLED -> FILLED_RECONCILED
or REJECTED, EXPIRED, CANCELED (possibly WITH PARTIAL FILLS).

A network timeout/ambiguous order response -> UNKNOWN_SUBMISSION:
query by the same client_order_id and exchange order_id before any retry.
Do not blindly resubmit. Some exchanges enforce uniqueness only among open orders.
A state "filled" without uniquely correlated execution records remains
AWAITING_FILL_RECONCILIATION rather than creating synthetic fill evidence.

An authentic fill must match exact account, venue, normalized product, side,
client_order_id, broker order ID, independent execution ID, quantity and
positive finite price. Compare every fill to the corresponding durable intent.
Apply each execution ID at most once, including replays after restart.
Trade corrections/busts are compensating events, never silent deletion.

PARTIAL then CANCEL is not a zero-fill order. Check partial exposure and
protective exits, and reconcile the final position quantity. Duplicate
identical fill => one ledger credit. Conflicting duplicate, overfill,
unexpected account, sequence gap or unreconciled position => QUARANTINE.

A broker ACK alone cannot refresh the old global trade marker. A local env flag,
writer heartbeat, market-data event, REST 200, submitted order request,
validate-only order, mock fill or remembered historic fill cannot prove a live
trade was executed.

## E. Normalized broker evidence and durable storage

Persist an authenticated-source envelope for each observation:
tenant/account_fingerprint, venue, portfolio, intent_id, writer lease generation,
client_order_id, broker_order_id, raw and canonical symbol, side,
event_kind, execution_id (for fills), last_qty, cumulative_qty, fill_price,
fee amount/currency, broker event time, observation time, sequence/revision
if provider supports it, authenticated transport, source digest and reconciliation
status. Use Decimal for quantities/prices/fees. No raw credentials in events/logs.

Suggested tables on independently backed up durable storage:
- order_intents: UNIQUE(tenant, account, client_order_id), immutable risk
  decision digest, writer generation, request hash, explicit submit-attempt state.
- broker_orders: UNIQUE(venue, account, broker_order_id).
- execution_events: UNIQUE(venue, account, execution_id), append-only and
  immutable, with separate correction/bust linkage.
- reconciliation_checkpoints: latest verified order/fill cursor, snapshot
  hashes, gaps, resolved/unresolved positions, replay watermark.
- account_preflight_snapshots: policy version, source timestamps, explicit
  true/false/unknown predicates, observed failures.

Transactional inbox + ledger posting, writer fencing and per-account lock are
required. A relational database transaction cannot be atomic with a broker's
external order submit; therefore unknown submission requires read-only order
lookup and reconciliation before any retry. No exactly-once broker dispatch
claim without verified provider semantics.

## F. Venue adapters: minimum integration requirements

**Kraken Spot:** authenticated WebSocket v2 executions channel provides order
states, fills, exec_id, cl_ord_id, order_id, cumulative quantities and
stream sequence. Use private REST QueryOrders/TradesHistory/QueryTrades/
Ledgers for reconnect recovery. Kraken cl_ord_id uniqueness is enforced
among OPEN orders, not a universal replay/idempotency guarantee. Full
TradesHistory pagination is in 50-trade pages. Account permission evidence
is available via GetApiKeyInfo.

**Coinbase Advanced Trade:** authenticated user-order messages plus
REST order/fills history. Verify correct retail portfolio and scoped
credential; never apply portfolio A's events to portfolio B.

**Alpaca:** authenticated trade_updates stream for new, partial_fill,
fill, canceled, expired, rejected. Look up by client_order_id. Where
supported, treat trade_correct and trade_bust as ledger adjustments.

**OKX:** private orders channel and REST fills/order history. Deduplicate
tradeId per instrument and ignore duplicate terminal states. The separate
fills WebSocket channel is documented as VIP4-only, so do not require it for
ordinary accounts. Provider-specific event timestamps and IDs must be used.

Normalize provider differences in adapters; a single generic set of order
status strings cannot be assumed to carry identical fill semantics.

## G. Operational failure policy / metrics

- Missing account identity, permissions, capital, protective exits,
  reconciliation, strategy/risk, writer lease/nonce, or kill switch clear:
  refuse NEW orders and keep current production safety gates authoritative.
- A stale stream or sequence gap triggers authenticated REST catch-up
  before resuming. Broker websocket delivery may be duplicated or missed.
- Unsupported or unknown provider event => quarantine; never coerce
  unknown -> filled or unknown -> ready.
- Publish by account: preflight_missing, latest_account_snapshot_age_s,
  last_broker_event_type, open_order_count, pending_ack_age_s,
  unresolved_submission_count, unreconciled_execution_count,
  last_reconciled_fill_id, protective_exit_coverage, writer_generation,
  trade_authority_approved, and capital_publication_freshness.
- Never emit raw API keys, account numbers or secret payloads.
- Kill-switch activation must be effective even if data feeds/recovery
  workers hang. It revokes new order authorization; any risk-reducing
  action requires separately reviewed controls.

## H. Staged migration (NO forced activation)

**P0**: operator-backed read-only inventory of current /data positions/ledger,
authenticated Kraken history/transfers and real protective exits; signed,
recoverable backups. Resolve BABY-USD with genuine evidence. Stabilize v270
capital publication separately.

**P1**: run this proposed reference classifier in SHADOW/OBSERVABILITY mode.
Reuse existing v450 metrics and PR #3200; never publish execution_ready from
shadow results or alter the trading state machine.

**P2**: normalize authenticated venue events, immutable per-order evidence
and REST catch-up. Compare against existing ledger without order submission.
Run 48+ hours of idle readiness, reconnect, error and duplicate-event tests.

**P3**: paper/simulation release with explicit CI coverage: cold startup
without historical fills; idle >30 minutes; wrong tenant; wrong symbol;
stale broker snapshot; capital 3/0 oscillation; unknown cost basis; active
kill switch; writer lease/nonce loss; ambiguous timeout; repeated fill;
partial fill + cancel; stream gaps; corrections/busts; unprotected exits.

**P4**: independent security/financial risk review. Operator approves an
account-scoped feature flag and staged rollout. Only this reviewed release
may replace the old startup fill-age dependency with a verified preflight
policy. Never synthesize fills or use a live test trade merely to prime
readiness.

**P5**: controlled monitored deployment after live state backup and rollback
verification. Only separately authorized trading intents may route orders.
Continually reconcile fills; on any unresolved fault, stop new exposure and
rollback fail-closed. Report actual verified broker fill IDs to prove operation,
not just Render deployment status.

## I. Acceptance criteria

- With zero recent fills, verified live account health can be a preflight
  CANDIDATE without granting dispatch authorization automatically.
- Idle longer than 30 minutes never expires eligibility on its own.
- Unknown BABY-USD basis, stale capital, missing protective exits, wrong
  account, unresolved orders, kill switch or missing permissions blocks.
- Broker ACK is not fill; verified execution must have broker fill ID,
  positive finite price/qty and matched durable order.
- Replayed fill applies once; conflict, overfill, cross-account fill,
  stream gap, timeout and partial cancel quarantine until reconciled.
- All state transitions are scoped to one account and durable across restarts.
- No changes to existing live order authorization before independent review
  of reference, code integration, tests and migration.

## Public research reviewed (October 2026)

1. Kraken v2 authenticated executions:
   https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/executions
2. Kraken client order IDs:
   https://docs.kraken.com/api/blog/cl-ord-id/
3. Kraken private history pagination:
   https://support.kraken.com/articles/360000912103-how-to-retrieve-your-account-s-trading-history
4. Kraken API permissions:
   https://docs.kraken.com/api/docs/rest-api/get-api-key-info
5. Coinbase official Advanced Trade Python SDK:
   https://coinbase.github.io/coinbase-advanced-py/coinbase.rest.html
6. Alpaca trade stream:
   https://docs.alpaca.markets/us/docs/websocket-streaming
7. Alpaca trade corrections/activities:
   https://docs.alpaca.markets/us/docs/activity-sse
8. OKX v5 API and private order channel:
   https://www.okx.com/docs-v5/en/
9. FIX execution-report lifecycle:
   https://fix.dev/organizations/fix-standards/specs/1000002/messages/8
10. AWS retries/idempotency:
   https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/

**Review is mandatory; this document does not authorize merge, deployment,
trading, ledger migration, or safety-gate modification.**
