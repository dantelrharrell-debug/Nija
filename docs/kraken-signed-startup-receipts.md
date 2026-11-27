# Authenticated Kraken startup receipts

`bot/kraken_startup_receipts.py` supplies a concrete verifier and explicit
registration adapter for the existing `ReviewedStartupBinding` startup API.
It creates no broker, providers, signing keys, approvals, receipts or orders.
It does not install anything at import or discover trust through environment
flags, receipt-provided public keys or executable configuration.

The protected composition owner must supply the existing reviewed factory and a
`StartupReceiptTrust` after independently verifying the actual service, deployed
commit/image digest, account IIBAN fingerprint, API-key fingerprint, complete
provider-ID registry, signer custody and maximum receipt age. Constructing this
data object does not establish that review. No production pins or issuer are
provided by this change.
The actual Render service ID and Git commit must match before and after
verification. The deployed image digest must be independently verified before
constructing the trusted context; no environment flag attests to the image.

Three immutable serialized JSON envelopes are required, keyed by
`independent_review`, `backup_restore` and `broker_ledger_exits`. Each envelope
has exactly `payload` and `signature` fields. The signature is strict base64 of
an Ed25519 signature over UTF-8 JSON with sorted keys, compact separators and
nonfinite numbers forbidden, using the existing operator-approval verifier.
Duplicate JSON keys, excessive data, missing/extra fields and unsigned objects
deny. Public verification keys are independently provisioned raw 32-byte public
keys selected by receipt role, never keys taken from the receipt itself.

Every signed payload must contain exactly:

| Field | Required binding |
| --- | --- |
| `contract` | `nija.kraken-startup-certification.v1` |
| `kind` | The receipt role |
| `status` | `certified` |
| `evidence_id` | A distinct external audit reference for each role |
| `artifact_sha256` | Digest of the actual externally reviewed artifact |
| `service_id` | The existing authoritative Render service |
| `release_id` | Exact deployed Git commit |
| `image_sha256` | Exact independently verified deployed image digest |
| `account` | `platform:kraken` |
| `account_iiban_sha256` | Independently approved account fingerprint |
| `api_key_sha256` | Independently approved current credential fingerprint |
| `provider_registry_sha256` | SHA-256 of canonical JSON for the full field-to-provider-ID map |
| `approved_at_epoch`, `expires_at_epoch` | Signed validity bounds; maximum approved age also enforced |

Signatures authenticate statements, not the underlying events by themselves.
The reviewer must inspect the actual backup restore, broker/ledger/exit evidence
and exact provider objects/source code. Provider IDs and signed artifact hashes
are not substitutes for those artifacts. The existing atomic installer still
observes and validates all thirteen independent providers. Reused callbacks,
scope/registry substitutions, expired/future receipts and clock rollback deny.
Validity is checked again after all three signatures are verified.

The reviewed production root calls
`register_signed_kraken_startup(factory, trust)` in the SAME Python interpreter
that subsequently enters canonical main. Calling it in the outer protected
bootstrap and then executing Bash/a new Python interpreter loses registration.
Do not bypass shell preparation, writer-first acquisition, native broker/nonce
ownership, rejection provenance, protective exits or any admission gate to
reach this API. The existing startup chain must be independently reviewed
before inserting that call.

This change does not edit the protected Render bootstrap or complete its
production composition. The actual factory/source bindings, genuine receipts,
trusted public keys, verified runtime pins, independent review and release
checks remain required before installation. No production signing interface
or synthetic positive receipt is supplied. Tests generate ephemeral signing
keys and synthetic evidence entirely offline, solely to verify wiring and
denials. Passing those tests is not a production certificate.

No ledger schema or state migration is involved. Source rollback removes this
adapter through the normal reviewed deployment process. Preserve external audit
records and existing recovery claims. First live orders and autonomous trading
retain their separate approval requirements.
