# NIJA Account Deletion

**Status date:** 2026-11-26

**Status:** Source-level scope clarification. Production deployment, published
instructions and cross-system deletion remain unverified.

## Implemented cleanup boundary

`DELETE /api/account/deletion` operates on the authenticated user only. Its
`success: true` / `status: deleted` response means that the existing cleanup
steps completed for the stores below; it does not mean all NIJA-related data
was erased. These response fields and the confirmation phrase remain compatible
with existing clients.

| Covered by the current handler | Outside this handler's coverage |
|---|---|
| `users`, `sessions`, and `login_history` in the current authentication database | Other auth state, including `email_verification_tokens`, `two_factor_auth` and `two_factor_backup_codes` |
| `credentials` and user-linked `audit_log` rows in `vault/__init__.py`, plus the legacy in-memory credential cache | The separate PocketBase member broker vault (`nija_broker_vault`) and credentials held in other stores or runtime copies |
| Mobile device/push registrations in `mobile_device_store.py` | Other provider identities, device records and copies not managed by that store |
| Current user/permission caches and the per-user trading-rule file/cache | Trading history, ledgers, recovery journals and other trading state |
| No additional stores are deleted by this scope clarification | Website submissions, consent history, SQLite/Redis lead queues, CRM/marketing and support records, billing/course/progress records, exports/uploads, logs, provider copies and backups |

The API returns `deletion_scope`, `not_covered`, `retention_notice` and
`privacy_follow_up` before confirmation and after successful cleanup. Clients
must display the scope before confirmation and use the completion message
without changing it into a claim of system-wide erasure. The separate privacy
review is not automatically submitted by this endpoint.

There is no single transaction across all covered stores. A failed step returns
HTTP 500 without a success claim; earlier cleanup may already have completed.
The HTTP 400 confirmation failure remains unchanged. When a validly signed
JWT belongs to an account already removed, the shared auth decorator now
rejects it with HTTP 401 before the handler runs. The handler's HTTP 404
missing-account response can still occur if the account disappears between
its authentication check and its lookup. Repeated requests must not delete
another account or claim success.

The shared `require_auth` decorator now checks that the JWT subject still
exists and is enabled in the authoritative authentication database, in
addition to verifying signature and expiry. The mobile gateway still performs
its separate check. The exact deployed entrypoints, already-issued token
rejection and cross-gateway re-registration behaviour remain **unverified**
until an approved release and synthetic runtime acceptance tests. A failed
cleanup response does not establish that account access is blocked or that
earlier cleanup was rolled back.

This handler's completion log contains scope and counts instead of the user ID.
Its failure log contains the cleanup stage and exception class, without raw
exception details. Other modules can still log user identifiers; this change
does not certify complete log redaction or expiry.

## In-app deletion path

The mobile experience must expose account deletion from an authenticated Settings/Profile screen. The user should not be forced to contact support solely to start deletion.

Recommended path:

**Settings → Privacy & Account → Delete Account**

The destructive flow must:

1. Explain that deletion is permanent.
2. Explain that active trading should be stopped before deletion.
3. Require an explicit confirmation phrase or equivalent deliberate confirmation.
4. Send an authenticated deletion request for the current user only.
5. Remove sessions in the covered authentication store and sign the client out after successful cleanup.
6. Remove broker credentials and push/device tokens in the covered stores.
7. Clearly identify other NIJA records, provider copies and backups outside this request.
8. Explain how to request a separate privacy review. Do not imply it has been queued or completed.
9. Confirm only the covered cleanup, or report that complete cleanup could not be confirmed.

A future broader deletion process must define identity verification, store and
provider coverage, retention exceptions, expiry, retry/reconciliation and
completion evidence before making broader claims. A category being outside
this endpoint does not itself establish a legal basis or retention period.

## Public web-page copy

The following is proposed copy, not evidence that this route is published or
operational. Verify the shipped UI and support/privacy contact before publishing
a stable HTTPS page. Suggested page title: **Delete Your NIJA Account**.

### Delete Your NIJA Account

NIJA users can request deletion from inside the NIJA app:

1. Sign in to NIJA.
2. Open **Settings**.
3. Select **Privacy & Account**.
4. Select **Delete Account**.
5. Review the deletion notice and confirm the request.

When cleanup succeeds, the service removes your account records, sessions, broker
credentials, mobile push registrations and trading-rule state from its covered
active stores. The confirmation lists the scope. This request does not cover
all NIJA-related records.

Other authentication records, the separate member broker vault, website and CRM
records, billing/course/trading-history records, support records, logs, exports,
provider copies and backups may remain. This request does not confirm their
deletion or a retention period. Contact `support@nijaaitrading.com` to request a
separate review of those records. That review is not automatically submitted by
deleting this account. This action does not cancel a separately managed
subscription.

If you cannot access the app, use NIJA's published support or privacy contact method to request assistance. NIJA may need to verify that you control the account before processing an off-app request.

Deleting your NIJA account does not automatically delete an account held directly with Coinbase, Kraken, OKX, Alpaca, Apple, Google, Stripe, or another third-party service. Manage those accounts directly with the applicable provider.

## Engineering acceptance tests

- [ ] unauthenticated request returns 401
- [ ] user cannot delete another user's account by supplying a different user ID
- [ ] confirmation is required
- [ ] repeated requests preserve other users and correctly report missing-account state
- [ ] covered session rows are removed
- [ ] previously issued JWTs are denied after deletion at every deployed gateway
- [ ] re-registration cannot restore an old token's authority over the deleted account
- [ ] user auth record is deleted or moved to a documented deletion state
- [ ] broker credential store is cleared for the user
- [ ] separate member broker vault, additional auth stores and runtime credential copies are disclosed as outside this endpoint
- [ ] push/device tokens are cleared
- [ ] in-memory user cache is cleared/disabled
- [ ] covered cleanup succeeds for a synthetic user while a second user's records remain unchanged
- [ ] unsupported stores remain unchanged and are not claimed deleted
- [ ] partial failure never returns success and logs only the stage and error category from this handler
- [ ] broader retention periods, reasons and expiry are independently documented and verified
- [ ] deletion does not claim to delete third-party brokerage accounts
- [ ] app signs the user out and clears local session data after successful acceptance

## Counsel questions

1. Which NIJA records must be retained after account deletion, and for exactly how long?
2. Does NIJA's business model create any broker-dealer, investment adviser, commodities, money-transmission, or other financial-services recordkeeping requirements?
3. Which trading/audit records can be de-identified instead of retained with user identifiers?
4. What identity verification is appropriate for deletion requests submitted outside an authenticated session?
5. What backup-retention window is defensible, and how should deletion from backups be described?
