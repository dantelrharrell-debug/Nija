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
- [ ] Verify the backup restore and exact release security findings. For an owner-only release, obtain the owner's current `certified` signature over the exact protected source, verified backup restore, and verified broker, ledger, and exit reconciliation artifact digests. For an existing role-pinned manifest, verify the three current receipts `independent_review`, `backup_restore`, and `broker_ledger_exits`. Use the format selected by the protected trust manifest and verify custody and scope of the signing keys.
- [ ] Privately review the complete Python resolver `resolve_sources(*, manager, strategy, broker, trust, receipts)` and reviewer `review_sources(sources, *, trust)`. Ensure they bind existing real sources; never create a second Kraken client/nonce writer or return unconditional approval.
- [ ] Confirm the signed source digest matches the exact approved source bytes. Use the owner envelope's `payload.artifacts.protected_source` or the role-pinned `independent_review.payload.artifact_sha256` as applicable.

The optional owner `diagnostic` envelope supports a separately approved read-only startup sample. It binds only the protected source. Collector installation requires certified evidence, and order admission uses its separate execution controls.

## Private Render provisioning — separate owner approval required

- [ ] Owner approves the exact reviewed artifact hashes, target service and release.
- [ ] Add **both** private files in the [Render Environment > Secret Files](https://render.com/docs/configure-environment-variables#secret-files) settings. Render mounts them at these runtime paths:
  - `/etc/secrets/.render-kraken-startup-root.py`
  - `/etc/secrets/.render-kraken-startup-binding.json`
- [ ] Keep the three existing ledger/recovery Secret Files and startup command unchanged.
- [ ] After approval, deploy exact certified release and verify `KRAKEN_PROTECTED_STARTUP_ROOT status=protected_startup_factory_registered` in the final interpreter.
- [ ] Independently verify `collector_installed=true` and all **13/13** fresh, account-scoped authenticated observations. Factory registration alone is insufficient.
- [ ] Verify risk/position/exit/nonce/order safety, security certification, rollback and monitoring before any **separate bounded** authorization to enable live orders.

## Failure behavior

If any private artifact, signed receipt, provider, ledger reconciliation or approval is missing or invalid, leave orders disabled and report the exact failing gate. Do not synthesize files, signatures, observations, empty inventories or success logs.

Reference: issue #3890; `docs/kraken-protected-startup-root.md`, `docs/kraken-signed-startup-receipts.md`, `bot/kraken_protected_startup_root.py`.
