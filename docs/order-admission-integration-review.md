# Order admission replacement: integration review

Status: policy and offline tests only. NOT connected to live authority or
dispatch. NOT a completed deadlock repair. Do not deploy this as an activation
fix or interpret its eligible result as permission to place an order.

## Implemented contract

`bot/order_admission_policy.py` separates candidate operational eligibility from
historical execution evidence. Cold startup and an idle strategy can be eligible
without a recent fill. A real fill remains subject to the existing 1,800-second
freshness limit and independent ledger reconciliation. Every operational fact
is required, at most 30 seconds old, and bound to the account, credential,
writer generation and complete immutable intent digest. An unresolved, failed,
unknown or contradictory order state denies entry. This module performs no I/O.

The freshness limits are fixed policy inputs in this proposal, not new runtime
environment bypasses. The 30-second current-fact limit requires review against
actual authenticated read latency; the recent production history read took
115.613 seconds. Collectors must use each fact's actual observation time and
must not refresh timestamps when assembling a report.

## Integration work still required before activation

1. Implement audited collectors for all REQUIRED_CONTROLS. Constructing a
   CurrentFact with verified=True or a producer label is not evidence. Neither
   request JSON, environment flags nor a generic readiness table may manufacture
   these records. Preserve account ownership and member/platform isolation.
2. Certify account ledger completeness from broker order/trade/ledger records
   and local durable intents. Zero pending-close count alone cannot certify it.
   Existing startup diagnostics default independent attestations to false; they
   are not a collector. The legacy `_startup_reconciliation_gate` admits missing
   reconciliation for its first cycle and cannot serve as this certificate.
3. Read existing protective-exit authority and independently confirm applicable
   broker coverage. Tracker flags and an attached exit callback alone are not
   native-order confirmation. Respect the existing dust policy.
4. Add a durable account-scoped single-in-flight intent reservation, acquired
   atomically before dispatch. On timeout, process crash or unknown broker
   result retain the unresolved reservation. Recover by exact client/order ID;
   never blindly resubmit or expire an unresolved order into eligibility.
5. Immediately before the canonical strategy-selected dispatch, refresh the
   required facts, validate the reservation and recheck the writer fence, nonce
   owner, stops, risk, sizing, minimums and market data. Preserve the ordinary
   strategy entry/exit conditions. No heartbeat, probe or forced test order.
6. Feed exact authenticated order/fill results into existing canonical fill and
   ledger verification. Release a reservation only after a proven terminal
   outcome and reconciliation. Define zero-fill cancellation separately; this
   policy intentionally rejects an unrecognized cancellation state.
7. Replace the fill prerequisite at every authorization consumer together:
   preactivation v16, TSM activation/live authorization, v60/v113, snapshot
   bridge/v251, authority v231, v361/v362/v363, v133 proof-loss and v238/v347
   activation wakes. Keep genuine fill verifiers (v169/v328/v339/v346) unchanged.
   A process-global `execution_ready=True` or patched verifier return would
   incorrectly convert eligibility into execution evidence and is prohibited.
8. End-to-end tests must cover real collector failures, cross-account replay,
   concurrent reservations, crash recovery, uncertain submission, late/partial
   fills, writer loss and kill switch activation between eligibility and send,
   startup with no history, idle >30 minutes and stale account state.

## Release gate

No live integration is present in this PR. All items above are release blockers,
not optional follow-ups. AGENTS.md requires human review for the eventual
startup/authority/broker changes and hosted CI/security checks before merge.
Do not clear a stop, reset attempt history, manufacture reconciliation or
refresh old evidence to obtain a green status. Reverting the policy files has
no runtime effect because they have no live callers.

## Validation

59 focused tests passed, including policy cases and existing proof/independent
certification regressions. Parameterized unittest subcases cover all 16 required
controls, invalid values, timestamps and candidate identity changes. Python
compilation and detect-secrets passed with zero findings. The locally unavailable
runtime-tools-secret_scanning and codeql_checker were not run; hosted review is
still required. No backtest applies to this pure, unconnected policy component;
any later strategy change would need one.
