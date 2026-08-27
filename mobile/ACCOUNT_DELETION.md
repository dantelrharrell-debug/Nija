# NIJA Account Deletion

**Status date:** 2026-08-27

## In-app deletion path

The mobile experience must expose account deletion from an authenticated Settings/Profile screen. The user should not be forced to contact support solely to start deletion.

Recommended path:

**Settings → Privacy & Account → Delete Account**

The destructive flow must:

1. Explain that deletion is permanent.
2. Explain that active trading should be stopped before deletion.
3. Require an explicit confirmation phrase or equivalent deliberate confirmation.
4. Send an authenticated deletion request for the current user only.
5. Revoke the user's active session after acceptance.
6. Remove NIJA-held broker credentials and push/device tokens promptly.
7. Delete or de-identify other user-linked data where legally permitted.
8. Clearly disclose that limited transaction, tax, fraud-prevention, security, dispute, consent, or regulatory records may be retained when required by law or legitimate compliance obligations.
9. Confirm completion or provide a request/reference status when asynchronous cleanup is necessary.

## Public web-page copy

Publish a stable HTTPS page on the NIJA website before Google Play submission. Suggested page title: **Delete Your NIJA Account**.

### Delete Your NIJA Account

NIJA users can request deletion from inside the NIJA app:

1. Sign in to NIJA.
2. Open **Settings**.
3. Select **Privacy & Account**.
4. Select **Delete Account**.
5. Review the deletion notice and confirm the request.

When your deletion request is accepted, NIJA will disable access to the account and remove or de-identify personal data associated with the account where legally permitted. NIJA-held broker API credentials and registered device/push tokens are removed as part of the deletion process.

Some records may be retained when reasonably necessary for legal, tax, accounting, security, fraud-prevention, dispute-resolution, or regulatory obligations. Retained records are restricted from normal product use and are kept only for the applicable retention period.

If you cannot access the app, use NIJA's published support or privacy contact method to request assistance. NIJA may need to verify that you control the account before processing an off-app request.

Deleting your NIJA account does not automatically delete an account held directly with Coinbase, Kraken, OKX, Alpaca, Apple, Google, Stripe, or another third-party service. Manage those accounts directly with the applicable provider.

## Engineering acceptance tests

- [ ] unauthenticated request returns 401
- [ ] user cannot delete another user's account by supplying a different user ID
- [ ] confirmation is required
- [ ] repeated deletion requests are safe/idempotent
- [ ] active sessions are removed/revoked
- [ ] user auth record is deleted or moved to a documented deletion state
- [ ] broker credential store is cleared for the user
- [ ] broker runtime environment variables are cleared
- [ ] push/device tokens are cleared
- [ ] in-memory user cache is cleared/disabled
- [ ] retained records are documented by category and reason
- [ ] deletion does not claim to delete third-party brokerage accounts
- [ ] app signs the user out and clears local session data after successful acceptance

## Counsel questions

1. Which NIJA records must be retained after account deletion, and for exactly how long?
2. Does NIJA's business model create any broker-dealer, investment adviser, commodities, money-transmission, or other financial-services recordkeeping requirements?
3. Which trading/audit records can be de-identified instead of retained with user identifiers?
4. What identity verification is appropriate for deletion requests submitted outside an authenticated session?
5. What backup-retention window is defensible, and how should deletion from backups be described?
