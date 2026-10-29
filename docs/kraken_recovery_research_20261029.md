# Kraken recovery findings — 29 October 2026

The production cursor request failed at TradesHistory with `api_failure`.
The old receipt discards the upstream error array, so it cannot distinguish
permissions, nonce ordering, request format, or throttling. No specific cause
has been established. The separate existing offset request remains single-use;
inspect its terminal receipt before any restart or new collection.

## Applied code repairs

- Preserve exact recognized Kraken errors as fixed diagnostic labels in private
  receipts and runtime logs. Never serialize upstream free text or response data.
- Recognize timestamped service throttles without exposing their timestamps.
- Require the documented empty error array on successful offset and Balance
  responses, matching the cursor collector's existing contract.
- Accept the optional explicit boolean `use_cursor` field in the offline failed
  receipt reader. Older claims remain valid; arbitrary fields remain denied.
- Fix the existing receipt test's module path and run both old and new tests in
  the existing Python 3.11 offline CI job.

These changes do not retry requests, construct clients, change nonce/rate controls,
repair the financial ledger, install an independent attestation collector, clear
stops, or enable orders. A deployment would interrupt the pending recovery thread;
do not deploy merely to change its diagnostic messages.

## Verified primary references

- https://docs.kraken.com/api-reference/account-data/get-trades-history
  documents `ofs` as deprecated, explicit cursor pagination, and the closed-trades
  query permission. Both supported pagination paths remain explicit choices.
- https://docs.kraken.com/exchange/guides/general/errors distinguishes permission,
  signature, key, nonce, throttling and service failures. An HTTP response alone
  is not success: the error array must be empty.
- https://docs.kraken.com/exchange/guides/rest/authentication requires a strictly
  increasing nonce per key. Existing serialized nonce ownership must be preserved.
- https://docs.kraken.com/exchange/guides/rest/ratelimits describes per-key counters,
  API rate limits and service throttle timestamps. Its history-call weight differs
  from the current support article below; no limiter change is justified by these
  conflicting documents or by an undifferentiated `api_failure`.
- https://support.kraken.com/ca/articles/206548367-what-are-the-api-rate-limits-
  documents another current history-call weight. Check observed fixed error labels
  and resolve the documentation discrepancy before changing budget calculations.
- https://docs.kraken.com/api/docs/rest-api/get-api-key-info documents authenticated
  key permissions, IIBAN, and query date restrictions. A user-approved binding is
  not itself a successful fresh readback of those properties.
- https://support.kraken.com/ca/articles/208267878-how-to-export-your-account-history
  provides an independent account-history export path. An exchange export can
  corroborate trades and ledger movements; it does not supply NIJA's missing
  original strategy journal or prove live risk/writer/operator authority.

## Completion boundary

The independent collector needs all thirteen genuine evidence providers and
canonical-process registration. Current SQLite checks still identify pending
close reconciliation and missing protective-order mappings. No report, API
export, environment toggle or shell-local setter is a substitute for those
verified integrations. This PR is a concrete diagnostic/compatibility repair,
not a declaration that production is ready to trade.
