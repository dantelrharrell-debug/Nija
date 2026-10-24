# NIJA Kraken v464 private failed-history receipt triage

**Diagnostic only; no order authorization or broker calls.** This script is for the
operator's existing private production recovery directory, after preserved
current-instance backup and offline restore verification. It does not issue or
repeat Kraken requests, change the existing claim, edit the ledger, or install
execution certification. It does not expose raw account history, request IDs,
account owner IDs, symbols, or fee/position information in its output.

## Verify the source and use only a known failed request

Run from the **existing** production SSH session as the service owner. Before
running it, review the PR, hosted tests, secret scanning and actual source
revision. Do not deploy or restart production just for this diagnostic. The
command is appropriate only once the reviewed script is present in the
operator's verified local path, for example `/private/scripts/...`.

```sh
# Read only; do NOT create/edit request.json or reuse a consumed request ID.
# Use an independently verified existing failed request ID from Render logs.
test -n "${NIJA_KRAKEN_HISTORY_RECOVERY_DIR:-}" || { echo 'STOP: recovery dir not configured'; exit 1; }
python -S -B /private/scripts/nija_kraken_failure_receipt_triage_v464.py \
  --recovery-dir "$NIJA_KRAKEN_HISTORY_RECOVERY_DIR" \
  --request-id ACTUAL_FAILED_32_HEX_REQUEST_ID
```

The `ACTUAL_FAILED_32_HEX_REQUEST_ID` placeholder must be replaced by the
real ID from the operator's previously recorded `KRAKEN_HISTORY_COLLECTION_FAILED`
log. Do **not** print, paste, upload or email the contents of `.claimed.json`
or `.evidence.json`. If the directory is unknown, review the securely retained
service configuration separately; do not guess an alternate path.

A successful triage only proves a **failed historical collection receipt** is
well-formed and scope-matched against its claimed request. `required_pages`
is the broker-advertised minimum based on historical count, **not an approved
new request budget**. An older receipt without this field returns
`complete_page_budget_known=false` rather than guessing. Failed receipts are
never substituted for a successful complete authenticated collection.

A failed triage returns a fixed `FAILED_CLOSED` reason without broker data.
Leave the claim and receipt untouched. The operator must review API tier and
Kraken private REST rate limits, monitoring contention, timeouts, account
ownership, and the approved max-pages range before authorizing a *new*, unique,
one-shot request. Never automatically retry or change existing requests.

After a separate approved authenticated complete collection, the existing v463
read-only intake can compare exact historical order references against the
restored 13 pending Kraken-close IDs. Even a successful v463 report does not
reconcile fills, fees or opening lots, verify protective exits, authorize
trading, or generate a fresh post-trade execution proof.

Security: all private recovery files stay mode 0600 under an owner-only 0700
canonical directory. This script requires those permissions and explicitly
rejects changed/oversized/unknown data and user-account scopes.