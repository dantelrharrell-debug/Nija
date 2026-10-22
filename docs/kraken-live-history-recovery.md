# Kraken historical evidence collection through the live client

Status: proposed opt-in recovery integration; human review and green hosted
security/recovery checks are required before deployment. This is not the
account-certification collector or a replacement order-admission controller.

The existing v363 worker can schedule a separate read-only collection thread
using the running multi-account manager's unique connected Kraken object and
canonical monitoring enum. It never constructs credentials or another client.
Pending-fill recovery continues independently of the historical read thread.

After review, set `NIJA_KRAKEN_HISTORY_RECOVERY_DIR` to a canonical absolute
directory owned by the service UID, mode 0700. Leaving it unset disables this
feature. Preserve and review existing production recovery state before any
deployment. Do not deploy merely to make a status display green.

An authorized operator places one mode-0600 `request.json` in that private
directory, with exactly these fields (example metadata only):

```json
{
  "request_id": "0123456789abcdef0123456789abcdef",
  "account_scope": "platform:kraken",
  "created_at": 1,
  "max_pages": 2
}
```

Use a newly generated 32-character lowercase hexadecimal ID and the actual
current epoch time. The example timestamp is deliberately invalid. The request
expires after 300 seconds before collection begins. Verify the account scope
against the operator-approved registry; software routing metadata alone does
not authenticate ownership. This interface does not grant member access.
Never place credentials, API keys or arbitrary endpoints in the request.

The consumer rejects malformed/shared/foreign-owned/symlinked request files,
duplicate JSON keys, out-of-range pages and ambiguous brokers before reads.
The maximum is 100 pages per endpoint per pass, but ONLY when an approved,
explicit one-shot request selects that budget via `max_pages`. An existing
request retains its original budget; the example uses two pages. Missing
client/category leaves
the request pending. A private process lock prevents simultaneous consumers.
A permanent, fsynced `<request_id>.claimed.json` is created before reading.
Interrupted or failed collections are not automatically replayed. Retain claims
and failure evidence for review; do not erase them to get a success result.

The collector reads only Balance, TradesHistory, ClosedOrders and Ledgers,
through the existing broker's private-call controls. Two complete historical
passes must agree and before/after balances must match. A changed count, row,
balance, incomplete page or API failure produces failure evidence. Output is
atomically committed as mode-0600 `<request_id>.evidence.json`. Error receipts
contain exception type and fixed allowlisted failure labels only. Raw history
is never emitted to application logs.

These are bounded page reads, not a global hard wall-clock timeout. A currently
running private read retains the broker transport's timeout. Monitoring reads
can still consume shared rate capacity; use this one-shot operation deliberately.
If a broker count shows that the history exceeds the explicit page budget,
collection fails on its first history page. Never treat partial data as complete
history, replay a consumed request, or automatically increase its budget.
Preserve the failed claim and evidence. A new request ID and separately approved
rate/budget plan are required for a new attempt.

Kraken private-history endpoints consume +4 units of the account's REST
rate counter per call. Standard-tier capacity replenishes 0.5 units/second
(see https://support.kraken.com/articles/206548367-what-are-the-api-rate-limits-).
Two passes across three paginated endpoints can take substantial time. Before
approving a request above ten pages, independently verify the broker's
monitoring throttles, rate budget, account scope and production impact.
This opt-in capability does not override broker throttles, safety gates,
backup/restore requirements, historical reconciliation or proof freshness.

No ledger writes, order placement/cancellation, kill-switch changes, execution
marker writes or authority promotion occur. Historical broker timestamps stay
unchanged. Repeat-read agreement is not an atomic broker snapshot, independent
account identity, current protective-order readback or ledger reconciliation.
The output explicitly preserves those unverified states.

After a successful collection, independently reconcile all historical fills
and fees against durable intents and positions. Classify buys/sells as opening
or closing only with proven position/lot links. Verify current protective
orders, all required accounts, complete recovery backups and the reviewed live
admission integration separately. This collector does not clear the unresolved
Kraken records or authorize trading.

Rollback: disable the optional directory setting through the reviewed release
process and revert this code if necessary. Preserve requests, claims and evidence;
do not remove ledger state, recovery queues or historical execution records.
