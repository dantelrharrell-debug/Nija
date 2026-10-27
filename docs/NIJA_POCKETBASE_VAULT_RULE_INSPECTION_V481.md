# NIJA PocketBase owner-rule verification v481 — restricted read-only utility

This code supplies a **structural** audit for the existing IONOS AI App Builder PocketBase collection, using an **existing authorized superuser bearer token**. It is not an OAuth bypass, superuser creation/recovery mechanism, data migration, key rotation, member enrollment, or live-trading activation.

## Why this tool exists

The IONOS-managed `/.sfs-be/_/` admin interface is inaccessible through the external unauthenticated access path (OAuth gateway login/timeout), while `/.sfs-be/api/health` responds normally. An account administrator (or IONOS after restoring the gateway) may have an explicitly authorized, short-lived PocketBase superuser token for the underlying REST Collections API. A trusted operator can run this tool **outside GitHub Actions and outside any browser bundle** using that legitimate token. If no valid token exists, do not generate or borrow one, and do not change production rules blindly; IONOS must resolve access first.

## Invocation (authorized server-side environment only)

Store the existing superuser token in the authorized process's secret environment. **Never paste tokens in chat, GitHub, logs, command arguments, frontend code, or CI secrets.** Export `NIJA_POCKETBASE_URL=https://nijaaitrading.com` and `NIJA_POCKETBASE_ADMIN_TOKEN` in the approved restricted environment; run `python -m scripts.nija_pocketbase_vault_rule_inspection_v481`. Remove the ephemeral token after the run according to the security runbook.

Only two HTTPS `GET` requests are permitted, to `/.sfs-be/api/collections/nija_broker_vault` and `/.sfs-be/api/collections/users` on the exact NIJA domain. Redirects are rejected, response sizes are limited, and response bodies/tokens are never printed. This does not access member records, ciphertexts or keys.

## Structural criteria

* The vault is the named base collection; `users` is the auth collection.
* List/view rules require a verified, authenticated, identical record owner.
* Create rule additionally requires `@request.body.user_id = @request.auth.id`.
* Update must be locked to superusers or additionally prevent reassignment to another owner. Delete must be locked or owner-bound. These are intentionally strict accepted rule forms, not a general PocketBase expression-equivalence parser.
* There is a **non-partial** unique SQL index covering `(user_id, broker, environment)` and the `user_id` field is a required single-valued relation to the actual `users` collection (legacy `schema.options` and current `fields` layouts supported).

`STRUCTURE_MATCH` means **only** that these server-reported structural fields match the strict reviewed contract. It does **not** prove effective access control. Superusers bypass PocketBase API rules. Before certification, use two separately authenticated **non-superuser** test members to verify unauthorized cross-user create/list/view/update/delete denial, including ownership reassignment; verify billing identity mapping and original AES-GCM key custody with an existing encrypted record; verify backup/recovery and gateway authentication; and independently approve any changes. Do not enable credential intake or flip the four security attestation environment flags based on this script alone.

## Current evidence and boundaries

As of October 26–27, 2026, public API health is 200, admin path is login-required/previous OAuth 504, member API `/readyz` is 503 with `security_review_incomplete`, and IONOS support has only confirmed escalation to back-office support. This code does not resolve the IONOS-managed OAuth gateway. Do not redeploy or replace the existing PocketBase database, re-create ciphertexts, or replace the original encryption key.

Offline regressions: `python -m unittest discover -s tests -p 'test_nija_pocketbase_vault_rule_inspection_v481.py' -v`. CI runs only synthetic tests and explicitly removes all production tokens.

Reference: https://pocketbase.io/docs/api-collections/ and https://pocketbase.io/docs/api-rules-and-filters/
