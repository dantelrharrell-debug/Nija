# Preserve interrupted history reads

The existing private history worker saves progress labels during collection,
but saves the actual broker records only after the entire two-pass history,
open-order and balance collection completes. A process exit during collection
leaves a permanent claim and progress file without the returned records.

The repair writes each successful private response before the collector can
make its next request. It uses the same existing broker and read category.
No second client, nonce generator, network endpoint or order operation is added.

## Private response journal

Files are written beside the claim, under the existing private recovery
directory, with names `<request_id>.response.<six-digit-sequence>.json`.
Files have mode 0600. The writer fsyncs the complete temporary file, publishes
the final name with an exclusive hard link, removes the temporary name, and
fsyncs the containing directory. Existing final files and symlinks cannot be
overwritten. A replaced or shared directory is rejected. A response is bounded
to 1 MiB and a journal instance to 64 MiB; any persistence or quota failure
stops collection. An exit can leave a temporary file or a final archive whose
directory sync did not finish; neither is completion evidence.

Each archive contains the caller-asserted account scope, request ID, sequence,
fixed endpoint label, original request interval and detached `result` data.
Headers, request credentials and free-text API errors are not archived.
Broker rows remain private and are never included in the public application log.

The callback is invoked before endpoint schema and whole-history consistency
validation. Its records explicitly contain `response_schema_verified=false`,
`complete_collection=false`,
`authenticated_identity_independently_verified=false`, and
`trading_authorized=false`. Malformed success envelopes can therefore be
preserved for investigation while collection still fails normally. An archive
does not establish account ownership, current holdings, history completeness,
opening-lot links, protective coverage or risk readiness.

## Recovery and release procedure

1. Review the exact change and its hosted checks before an approved deployment.
2. Preserve all old claims and outputs. The repair cannot recover records that
   an earlier process never persisted, and never replays consumed request IDs.
3. After approved deployment, issue one fresh bounded private history request.
   Inspect the response archives on the persistent disk as reads return. Keep
   account data out of GitHub and public logs.
4. Allow collection to reach a terminal receipt before another planned restart.
   A subsequent interruption preserves completed archive writes for offline
   investigation; it does not automatically resume or certify the collection.
5. For reconciliation, verify each archive's provenance and account binding
   independently. Compare duplicates across passes; never merge archives into
   an asserted current snapshot or refresh broker event timestamps.
6. Apply no ledger repair until complete opening/closing, financing, fee,
   transfer, holding and protective-order links are verified and the ledger
   backup is independently restored. Startup receipts and risk sources remain
   separate prerequisites.

Rollback removes the journaling callback and module. Retain existing private
archives and permanent claims. No ledger schema or strategy migration is made.

## Validation

Offline tests terminate a separate spawned process after its first returned
response. The response survives; the permanent claim remains; no terminal
success receipt appears; a subsequent worker invocation performs no replay.
Other cases cover private permissions, both fsync stages, exclusive final
names, symlinks, directory replacement, quotas, disk errors, callback mutation,
API-error redaction, malformed success schemas and account changes during reads.
All fixtures are synthetic and perform no broker network calls.

These tests establish archive behavior, not production reconciliation or live
trading permission. Existing exact-release security and independent review
requirements remain enforced.
