# Kraken HTTP identity field diagnostic

The existing recovery receipt observes the parsed GetApiKeyInfo reply. A missing
field there does not establish that the native HTTP response also omitted it.
Kraken's [GetApiKeyInfo contract](https://docs.kraken.com/api/docs/rest-api/get-api-key-info)
documents `apiKey` and `validUntil`. Do not substitute the configured key or an
assumed expiration for a missing authenticated response field.

The explicitly requested identity diagnostic now compares field presence at two
boundaries. Existing timing captures inspect the newly assigned native
`requests.Response` after the same existing `query_private` call, with no extra
request. Only an unredirected successful POST to the exact Kraken identity
endpoint and at most 64 KiB of unambiguous JSON can produce the HTTP diagnostic.
Unrequested captures do not inspect the response body. Gateway, stale, replaced,
oversized or malformed responses yield no HTTP diagnostic.

On failed identity verification, the private one-shot receipt may contain two
boolean-only maps: `http_identity_field_presence` and
`parsed_identity_field_presence`. Only `apiKey` and `validUntil` are exported.
Headers, values, response bodies and exception contents are never recorded.

| HTTP presence | Parsed presence | Interpretation |
| --- | --- | --- |
| Present | Missing | Investigate transformation between the HTTP body and parsed provider reply |
| Missing | Missing | Investigate the exchange response/endpoint compatibility; the parsed reply alone did not lose that field |
| Unavailable | Missing | The HTTP diagnostic could not bind a qualifying response; no transport conclusion |

These maps are diagnostics, not account evidence or independent certification.
The provider still rejects missing parsed identity fields. They cannot repair
identity, refresh execution proof, install the collector or authorize an order.
The same immutable one-shot claim, existing broker, nonce owner, rate admission,
freshness checks and replay denial remain in place.

Offline tests reproduce fields lost after HTTP parsing, genuinely missing HTTP
fields, foreign/stale/redirected responses, API errors, duplicate JSON keys,
oversized bodies, noninspection by default, sanitized receipt serialization and
one-shot replay denial. They establish diagnostic behavior only.

Deployment still requires exact-release checks, independent review, verified
backup/restore and owner approval. A fresh diagnostic request is an explicit
operator step after an approved deployment. Never replay consumed requests.
The request publisher's existing production consumer hashes are unchanged;
they deliberately reject the modified consumer until its new hash receives
independent approval. Offline publisher tests use isolated synthetic sources
and explicit fixture pins, never an automatic production approval refresh.
Credential rotation, full ledger/open-order/protective-exit reconciliation,
authenticated release receipts and all thirteen collector observations remain
separate prerequisites for trading readiness.
