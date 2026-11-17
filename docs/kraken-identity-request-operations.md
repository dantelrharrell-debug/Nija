# One-shot Kraken identity diagnostics

The existing instance diagnostic now accepts an explicit request ID for a new
authorized identity check. Previously it could only publish or inspect the
historical request `85c2521edd9754d6f6f7df677f8d6231`. That default remains
unchanged so existing automation still reads the same historical evidence.

Use the existing Render service and its running canonical broker. First confirm
the current deployment and process identity with the diagnostic's default mode,
using the independently verified full commit as `NIJA_APPROVED_RENDER_COMMIT`.
The configured private recovery directory, saved comparison binding and source
consumer hashes must pass the unchanged checks. Do not refresh those pins, change
the binding, start a broker, or import trading runtime merely to get a result.

For a separately requested check, select a new 32-character lowercase hexadecimal
request ID and retain it with the evidence record. Pass it explicitly:

```text
python -B -S scripts/nija_kraken_instance_diagnostic.py --request-identity --request-id REQUEST_ID
python -B -S scripts/nija_kraken_instance_diagnostic.py --identity-result --request-id REQUEST_ID
```

The first command publishes at most one private request. The running consumer
performs one `GetApiKeyInfo` read through its existing nonce owner and monitoring
budget. The second command reads only the matching sanitized receipt; it never
publishes a request. A pending or failed result is not success. Retain failed
claims and evidence, investigate the reason, and do not generate another ID in a
retry loop. The tool never generates IDs or retries automatically.

Receipt output includes the recorded identity method only when it is
`response_echo` or `native_signed_request_v1`. When present, the existing
consumer's HTTP and parsed field-presence maps show only actual boolean values
for `apiKey` and `validUntil`. Missing, malformed or unexpected metadata is
omitted without inventing defaults. These labels help diagnose response-shape
failures; they do not alter the account-match, freshness or certification result.
No response body, credential, account identifier or saved binding is displayed.

Every ID retains the original no-replay, source-pin, private-file, account-scope,
binding and collection-lock checks. Existing requests in any recovery mode are
preserved, even when a different ID is requested. Malformed IDs are rejected
before file access and their contents are not echoed. No source/receipt is
silently substituted, and the one-read budget cannot be increased through this
option.

Successful comparison is not independent approval, permissions certification,
collector installation, reconciliation or order authority. This operator-tool
change does not modify the broker consumer, startup, production settings,
credentials, signed approvals, safety gates or trading state. It needs no new
package. Runtime deployment remains a separate release action.
