# Production commissioning gate — independent review required

**Not deployed, not installed, and not live-order authorization.** The proposed
`bot/commissioning_gate.py` boundary has no production registration, transport,
environment fallback, activation callback, or execution-marker publisher.
Importing it does not migrate a database or start a worker.

## Confirmed cold-start dependency

`preactivation_readiness_convergence_v16_patch._collect_proofs()` requires
`_genuine_execution_marker_proof()` before setting `execution_ready`.
`_mark_proven_readiness()` refuses the activation iteration when that proof is
missing. Canonical `TradingStateMachine.commit_activation()` also evaluates
heartbeat execution verification and the live/system readiness gates;
`can_execute()` requires authorized `LIVE_ACTIVE`, writer/nonce readiness,
heartbeat verification, the live gate and coordinator permission. Pipeline
dispatch independently requires enabled authority and a durable entry
reservation.

Consequently, a cold account with no qualifying execution cannot obtain its
first order through those gates to produce the evidence they require. This is
an **order-or-fill** dependency, not strictly a fill-only dependency:
v16 accepts independently verified `heartbeat_trade` at `ORDER_VERIFY` or
`FILL_VERIFY`, and canonical confirmed fills at `FILL_VERIFY`. Existing genuine
fresh evidence can satisfy the legacy gate; it need not be a new order in every
activation cycle. A cold start cannot assume that evidence exists.

`PRETRADE_INDEPENDENT_CERTIFICATION_V6` is not itself circular. Its thirteen
checks require no new fill, but its result is explicitly diagnostic-only and
does not replace the legacy gate. Recovery's `allow_new_orders=false` is likewise
not the authoritative dispatch switch. Changing that diagnostic would not fix
activation and would misrepresent authorization.

## Implemented review-only stages

| Stage | Requirements | Permission |
|---|---|---|
| PRETRADE_READY | Independently sourced, account-bound broker permissions, identity, balances, position/ledger reconciliation, protective-exit capability/readback, open-order reconciliation, duplicate fence, writer lease, nonce ownership, signed general operator authorization with current revocation status, kill-switch clearance, risk limits and position sync. All existing candidate controls also pass. | No order; no new execution evidence required. |
| CONTROLLED_FIRST_TRADE | PRETRADE_READY plus a separate Ed25519-signed exact plan and independently signed active status, bound to account/key, writer generation, release, all order terms and a reviewed all-in cash ceiling. Approval lifetime is at most 300 seconds; status is at most 60 seconds old. | One durably consumed opening intent, not general automation. |
| POSTTRADE_VERIFIED | Authenticated canonical fill for that exact attempt/client order/account, event after the consumed boundary and within 1,800 seconds, matching independently reconciled ledger outcome, exact bounded entry terms, actual protective order readback and complete owned-quantity coverage. Current pretrade controls must still pass. | Eligibility for subsequent canonical activation review, not automatic LIVE authority. |

The initial envelope reuses `StartupVerificationPlan`: Kraken USD spot only,
limit/FOK entry, fixed quantity/price, fee-inclusive cash debit, approved stop
prices and broker quantity/quote minimums. Margin and other broker routes remain
unsupported, not silently authorized. The general approval does not imply the
exact-order approval, and the exact-order approval does not imply general
authorization.

Every candidate control in `order_admission_policy.REQUIRED_CONTROLS` is retained:
authenticated account, trade permissions, writer lease, nonce owner, balances
and holds, positions/open orders, ledger and startup-attempt reconciliation,
protective exits, kill switch, circuit breaker, strategy signal, risk/sizing,
market data, venue minimums and pipeline readiness. These must come from reviewed
runtime collectors; request booleans and test fixtures are not evidence.

The commissioning latch and `account_entry_reservations` are committed together
in the existing canonical ledger before transport. Every account fingerprint,
alias and approval is single-use. No timeout, rejected order, ambiguous ACK,
restart, key rotation, writer handoff, cancellation or expiry releases it.
Broker/ledger reconciliation must resolve an uncertain attempt; the gate has
no reset API. Posttrade verification does not release the entry reservation or
publish `execution_ready`. Stored completion alone never passes a fresh check.
Existing protective-close routes remain untouched.

## Gates still requiring an approved production migration

The new boundary deliberately **does not change production admission**. Independent
review must approve the composition root, trustworthy collectors, signing-key
custody, durable ledger migration and all entry transports before installation.

The migration must separate commissioning from broad `LIVE_ACTIVE` at the v16
activation iteration, canonical FSM/live gate, coordinator/authority context
and terminal pipeline/broker guards. Execution-proof owners and v361/v362
authority/stale-live guards must remain strict for broad automation; do not
mark `execution_ready` during PRETRADE_READY or use an unconditional missing-fill
exception. The controlled route must consume the exact permission once and
retain the existing terminal ECEL, sizing, writer generation/nonce, capital,
broker-connectivity, minimum-notional and kill-switch checks. Calling the
unchanged pipeline today will still deny a cold first order.

After the controlled trade, the existing authenticated fill/protection marker
chain and startup-attempt reconciliation must independently publish real
execution evidence before canonical broad activation. Neither this policy's
decision nor its SQLite state substitutes for that chain. Historical, simulated,
synthetic, replayed or refreshed old fills must never become commissioning proof.

Deployment approval and actual first-order approval are separate decisions.
This change issues neither, makes no broker calls, and must not be merged into a
deployment branch as a substitute for independent review.

## Offline regression coverage

`NIJA_DEFER_RUNTIME_SITE_HOOKS=1 python -m unittest bot.tests.test_commissioning_gate -v`
checks the no-fill pretrade transition, separate approvals, every pretrade and
order-level control, exact signature/account/key/plan/release binding, budget,
expiry during slow verification, durable replay denial, unresolved ledger
denial, and exact fresh fill/ledger/protective-exit verification. All fixtures
and ephemeral signing keys are offline-only; no test invokes a broker.
