# Kraken issue #3890: protected startup provisioning and production acceptance

This is a non-secret, non-executing release handoff. **Merging this document does not install private Render Secret Files, certify Kraken, or enable orders.** Never commit the actual source resolver, manifest, private keys, signed receipts, account identifiers, or credential values.

## Production target

- Existing Render service: `srv-d98dsr5aeets73fpbaqg`
- Release branch: `release/justcall-handoff-only-20261017`
- Preserve startup command: `python -S /etc/secrets/.render-ledger-bootstrap.py`
- Preserve `allow_new_orders=false`, kill switch, writer lease, and nonce protections.

## Required independent evidence before provisioning

- [ ] Record exact deployed commit and immutable image digest, approved account/key fingerprints and 13 reviewed provider IDs.
- [ ] Review genuine canonical runtime objects and six source owners: ledger reconciliation, complete durable duplicate-order inventory, operator authorization/revocation, kill-switch state, atomic account risk, and position synchronization.
- [ ] Reconcile authenticated Kraken history, open orders, positions, fills, margin/rollover fees, pending closes and protective exits against independently persisted records.
- [ ] Independently verify backup restore and exact release security findings; obtain three genuine role-signed, current receipts: `independent_review`, `backup_restore`, `broker_ledger_exits`. Verify public key custody and receipt scopes.
- [ ] Privately review the complete Python resolver `resolve_sources(*, manager, strategy, broker, trust, receipts)` and reviewer `review_sources(sources, *, trust)`. Ensure they bind existing real sources; never create a second Kraken client/nonce writer or return unconditional approval.
- [ ] Confirm manifest trust pins and signed `independent_review.payload.artifact_sha256` match the exact approved source bytes.

## Private Render provisioning — separate owner approval required

- [ ] Owner approves the exact reviewed artifact hashes, target service and release.
- [ ] Add **both** private Secret Files in Render Environment > Secret Files (not GitHub):
  - `/etc/secrets/.render-kraken-startup-root.py`
  - `/etc/secrets/.render-kraken-startup-binding.json`
- [ ] Keep the three existing ledger/recovery Secret Files and startup command unchanged.
- [ ] After approval, deploy exact certified release and verify `KRAKEN_PROTECTED_STARTUP_ROOT status=protected_startup_factory_registered` in the final interpreter.
- [ ] Independently verify `collector_installed=true` and all **13/13** fresh, account-scoped authenticated observations. Factory registration alone is insufficient.
- [ ] Verify risk/position/exit/nonce/order safety, security certification, rollback and monitoring before any **separate bounded** authorization to enable live orders.

## Failure behavior

If any private artifact, signed receipt, provider, ledger reconciliation or approval is missing or invalid, leave orders disabled and report the exact failing gate. Do not synthesize files, signatures, observations, empty inventories or success logs.

Reference: issue #3890; `docs/kraken-protected-startup-root.md`, `docs/kraken-signed-startup-receipts.md`, `bot/kraken_protected_startup_root.py`.
