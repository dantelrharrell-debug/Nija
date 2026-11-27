# Verified flat-account protection evidence

## Candidate behavior

Based on release source `6774fe96eb8ca9bf59c8508fa0f6bb9fcfa8bec2`, the protective
exit provider previously rejected every empty ledger positions map. That prevents
a genuinely flat account from satisfying the protection check without an existing
position. Creating a real position to satisfy a diagnostic is inappropriate.

The candidate adds a conservative flat-account branch to
`bot/kraken_protective_exit_readback_v485.py`. Existing nonempty-position protection
checks and their private-read sequence are preserved. Empty local tables remain
insufficient. The flat branch requires all of the following:

- The injected independent ledger source has the approved account/provider scope,
  a complete reconciled positions snapshot, valid evidence/snapshot identifiers,
  literal verified/read-only/scope/provenance flags, and no order authority.
- Its outstanding intentions and pending closes are reconciled, its orders map
  is explicitly empty, and unresolved submissions are the integer zero.
- Both complete authenticated OpenOrders reads are empty. A first empty page
  with unfinished pagination is insufficient.
- Two authenticated BalanceEx/OpenPositions pairs use the same existing direct
  broker, client object, account scope, key fingerprint and monitoring category.
  No client, credentials, nonce owner or listener is created.
- The supported default-wallet inventory contains only unencumbered USD cash
  and zero BTC/ETH balances. Positive noncash balances, holds, credit, credit used,
  margin positions, unknown assets, duplicate aliases and malformed fields deny.
- Source snapshots and exposure remain consistent across reads. The oldest
  ledger timestamp and any stricter expiry survive the result; expired proof
  is never renewed by report generation.

Success is labeled `verified_flat_no_exits_required` and always retains
`authorizes_orders=false`. It proves that this supported flat inventory needs no
current exits. It does not test exchange order placement, cancellation, fill
behavior, or protective-order execution. It does not install the collector,
clear stops, reconcile the production ledger, approve a release or enable orders.

The flat branch adds four private read invocations: two BalanceEx and two
OpenPositions calls. They require an explicit reviewed production read budget
before runtime use. The candidate itself has made no private broker calls.

## Offline validation

The existing protective-exit suite now has 27 test cases, including 17 new cases
with adversarial subcases. The positive integration fixture runs the real
read-only native ledger provider against a separate temporary SQLite database
with the explicit certification schema and synthetic exchange history. It proves
compatibility with distinct per-read evidence IDs and preserves database bytes.
Deleting its source-state row makes the same empty schema fail. Fixture source
reviews and exchange responses are test doubles, never production approvals.

Missing provenance, false/truthy flags, missing tables/source state, unresolved
intentions, orphan orders, incomplete pagination, noncash holdings, encumbrances,
margin, unsupported assets, changing account/client/transport, changed snapshots,
malformed responses, stale timestamps and expiry during collection all deny.

The broader targeted ledger/composition/native-identity/native-four/registration
run passed 297 tests with the application package startup suppressed and network
connect/name-resolution calls denied. These are local engineering results;
hosted CI, actual runtime observations and genuine independent review are separate.

## Review and source pins

The original protective provider's SHA-256 was
`5874c9e801638d55399a27cad7a319ceede05dd18b43da99b6260f73a63d61d2`
(Git blob `967ece7cf4f148d50e391ab6fa2d27f646e3dd6f`). No existing hard-coded
reference to either digest was found in the source tree before this note.

This does not remove the external review requirements. The final candidate
release and container image must be independently reviewed and bound to the
actual Render service, approved account/key mapping, provider registry and
canonical source objects. Existing protected startup trust verifies exact
release/image pins and three externally issued receipts: `independent_review`,
`backup_restore`, and `broker_ledger_exits`. The protected root's source digest
must match its authentic independent-review artifact. No trust anchor, receipt,
provider identity, source pin, saved binding or protected file is regenerated
by this patch. Existing one-shot identity-consumer pins are untouched.

Because the branch changes broker evidence behavior, it requires genuine human
review under AGENTS.md before merge and a separately authorized exact release
before production deployment. Order authorization remains an independent step.

## Remaining collection cost and freshness constraint

The existing `use_native_ledger_readers=True` composition supplies the full
native reconciliation callable to the ledger, protection, open-order and
position-sync consumers. One thirteen-field collection invokes it seven times:
once directly and twice in each of the other three consumers.

Every native reconciliation brackets two complete TradesHistory/ClosedOrders/
Ledgers traversals and two complete OpenOrders traversals with Balance and
identity reads. With one page per endpoint, the seven reconciliations alone
require 84 existing-broker private-read invocations, before the surrounding
provider reads. Pagination increases that count. Native reconciliation retains
its ten-page limit per endpoint/traversal; the complete certificate retains its
60-second freshness limit.

This patch does not alter that composition, increase budgets or cache/renew old
observations. Do not start an expensive live collection to test this design.
Before operational use, establish a reviewed account-specific request/rate
budget and demonstrate that a coherent full collection fits the freshness
window. A separately reviewed source-publication design may be required; any
such design must retain provenance, original timestamps, revision continuity
and mutation invalidation. Backup success or historical receipts cannot be used
as fresh collector observations.
