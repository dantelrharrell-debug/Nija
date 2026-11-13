# Native-request Kraken identity alternative: review required

The deployed GetApiKeyInfo diagnostic found both apiKey and validUntil absent
at the native HTTP and parsed boundaries. The official API reference still
documents both fields. Repeating the same parser or inserting configured-key
and zero-expiry defaults cannot resolve that discrepancy.

This patch offers an explicit `identity_method="native_signed_request_v1"`
on the account identity provider. Its default remains `response_echo`; no
production caller, recovery consumer, protected file or manifest is changed.
Independent human review is required before selecting this method.

## Proof and scope

The existing nonce-owning broker makes exactly one read. Call-scoped timing
must bind its native API object and the exact returned response. The alternative
checks an unredirected successful POST to the exact HTTPS GetApiKeyInfo endpoint,
the same native requests Session with TLS verification before and after,
unchanged credentials, and a new buffered Response. It recomputes HMAC-SHA512
over the actual prepared form body using the existing secret in memory; the
prepared API-Key must match the unchanged native client key and the independent
approved SHA-256 credential pin. It rejects extra/duplicate form fields, invalid
nonce, bad signature, oversized/malformed/duplicate-key JSON, API errors, and
wire/parsed disagreement. The returned account IIBAN must independently match
the approved account fingerprint.

No missing apiKey or validUntil field is inserted into a response. Successful
authenticated read establishes credential validity at that read, not an
indefinite expiry. Present malformed/expired expiry or mismatched echoed key
still denies. Existing 60-second read/freshness constraints remain. Downstream
certificates must continue to expire evidence and revalidate before admission.
Gateways and uninstrumented/cached reads cannot use this method.

The native client/session/transport code is trusted reviewed code, not an
adversarial sandbox. A forged requests object or replaced transport in a
compromised interpreter cannot be made trustworthy by this helper. Review native
client ownership, TLS invocation, request/response assignment and all wrappers
on the exact release before provisioning. Never turn diagnostic booleans into
cryptographic proof or self-approve a protected source manifest.

## Remaining production work

The permission provider and native ledger reader retain their own strict echo,
expiry and history-window checks. They have not been silently switched to this
method. Review the alternative at those boundaries before authorizing their
integration. Historical query restrictions must still be verified explicitly.
The risk publisher still needs authoritative current measurements and owner
revision/invalidation wiring; a publication implementation supplies no data.
Signed startup review/recovery receipts must come from the genuine authorized
review/signing roles after actual source and recovery verification.

No ledger mutation, risk-limit change, receipt generation, startup-file
provisioning, deployment, kill-switch clearance or order authorization is
performed by this patch. Its offline tests are transport-proof tests, not live
account certification. Rollback is reverting the patch before integration.

## Official references

- https://docs.kraken.com/api-reference/account-data/get-api-key-info
- https://docs.kraken.com/exchange/guides/rest/authentication

The first documents the key-info response; the second specifies API-Key and
API-Sign binding and HMAC-SHA512 of path plus SHA256(nonce + encoded POST data).
