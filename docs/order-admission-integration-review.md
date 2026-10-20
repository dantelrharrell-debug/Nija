# Order admission replacement: integration review

Status: admission policy remains unconnected; actual Kraken recovery paths now
have persistence hardening in this branch. NOT a completed deadlock repair.
Do not deploy this as an activation fix or interpret policy eligibility as
permission to place an order.

## Integration review findings and runtime repairs, October 20

Reviewed the canonical pipeline dispatch/ACK timeout, execution journal, Kraken
private-call recovery v430, deferred-fill recovery v363, and ledger storage/
inventory contracts. The execution journal's memory fallback is telemetry, not
a durable submission lock. The outer ACK timeout can leave a running worker;
the mutation deadline bounds a late send but does not undo a request already
accepted by the broker. Neither property proves at-most-once execution.

The actual v430 pre-submit recorder swallowed storage exceptions, then reported
success. Its direct ACK path discarded the client ID even when v363 handoff
failed. Both recovery queues evicted unresolved records at capacity or expiry.
These runtime defects are corrected in this branch:

- Atomic file replacement with file and directory fsync; errors propagate.
- Corruption and unreadable files no longer masquerade as empty queues.
- Generated-client-ID submission stops if persistence fails or account scope
  is missing. Existing client IDs/userrefs retain their separate behavior.
- ACK handoff clears the client ID only if every txid was successfully recorded
  by v363; a v363 write failure retains the original recovery identity.
- Capacity rejects new records instead of evicting old ones; expired unresolved
  records remain quarantined. Validation-only calls create no submission record.
- Recovery refuses a broker with a missing or mismatched account scope.

153 focused tests passed including the real v430-to-v363 handoff with injected
storage failure, file/directory fsync failure, corruption, queue capacity,
timeout retention, and existing proof/freshness regressions. Two obsolete
log-text assertions were removed from the existing wiring test; its actual
canonical installer and required-flag assertions remain.

Remaining critical findings: these JSON stores still rely on process-local
serialization and existing writer fencing; they are NOT the required atomic
account-wide order reservation. Pre-existing client/user references and
non-Kraken venues need their own covered paths. A missing file alone cannot
prove that durable history was never lost. No operational certification can
be derived from the ledger inventory script or mount detection. The Render
connector exposes logs/deployments but no shell or SQLite query, so live
ledger contents and process-local collectors were not independently inspected.

No new live admission path was connected and no service was restarted.
Source: https://docs.kraken.com/api-reference/account-data/get-closed-orders
confirms client-ID filtering; exact broker verification remains required.

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

No admission integration is present in this PR. All items above are release blockers,
not optional follow-ups. AGENTS.md requires human review for the eventual
startup/authority/broker changes and hosted CI/security checks before merge.
Do not clear a stop, reset attempt history, manufacture reconciliation or
refresh old evidence to obtain a green status. Reverting the policy files has
no runtime effect because they have no live callers. Reverting the recovery
changes restores the previous lossy persistence behavior; do not remove state
files as a rollback. Storage errors can now block generated-ID submissions,
which is intentional and requires deployment review.

## Validation

59 focused tests passed, including policy cases and existing proof/independent
certification regressions. Parameterized unittest subcases cover all 16 required
controls, invalid values, timestamps and candidate identity changes. Python
compilation and detect-secrets passed with zero findings. The locally unavailable
runtime-tools-secret_scanning and codeql_checker were not run; hosted review is
still required. No backtest applies to this pure, unconnected policy component;
any later strategy change would need one.

## Account reservation boundary, follow-up review

Added `bot/account_order_admission.py` with an explicit migration on the existing
canonical ledger, SQLite BEGIN IMMEDIATE/FULL synchronous commits, an account-wide
unique unresolved reservation and permanent account/intent replay uniqueness.
Separate processes, credentials and symbols cannot obtain simultaneous entry
reservations for the same canonical broker account. Missing/corrupt databases
fail closed; the component never creates an empty replacement ledger.

The reservation boundary obtains facts through an installed collector, supplies
a read-only view of its ledger transaction, evaluates every mandatory policy
control, checks the writer fence, and commits before returning a reservation.
Single-use consume repeats these checks and persists submitting before returning.
An exception, timeout or process restart never releases the account. This is not
a substitute for the terminal transport's writer/nonce checks. Canonical account
identity must be stable across credential rotation and all entry routes must use
the same persistent database; neither property is established merely by this API.

27 new offline tests pass, including six concurrent processes, restart/old-state
retention, credential rotation, identity substitution, collector write rejection,
and loss of every required fact between reservation and consume. Test collectors
are synthetic and provide no production evidence.

**Not installed in production:** audited broker account/ledger collectors, terminal
reconciliation/release, route coverage and the coordinated startup authorization
replacement remain unfinished. There is deliberately no generic release method.
Installing this component alone would leave an account blocked after its first
reservation; do not wire or deploy it as a complete solution. No new authorization
consumer was changed. Existing protective exits are unaffected.

Live inspection access: Render connector has no process exec/SQLite interface.
Opera connector was attempted and returned Browser not connected. A connected
authenticated Render browser shell or approved shell access is required to inspect
the current ledger; no live ledger certification was obtained.
