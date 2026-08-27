# NIJA Reviewer Access Package

**Status date:** 2026-08-27  
**Use for:** Apple App Review and Google Play review/testing instructions.

## Reviewer environment

Reviewers must receive a dedicated account that:

- is created specifically for store review;
- does not contain real user data;
- does not require the reviewer to create a brokerage account;
- can enter Education/Simulation mode immediately;
- is not blocked by MFA, email links, geo restrictions, paywalls, expired subscriptions, or manual founder approval during the review window;
- contains stable representative simulated data sufficient to exercise core screens;
- never contains production broker API credentials or real-money trading authority.

**Do not commit reviewer passwords to GitHub.** Store the credentials only in App Store Connect / Play Console review-access fields or another approved secure review channel.

## Reviewer account fields

Complete these immediately before submission:

- Review username/email: `[PROVISION EXTERNALLY]`
- Review password: `[PROVISION EXTERNALLY]`
- MFA requirement: `Disabled for dedicated review account, or provide a review-safe bypass approved by security`
- Environment/API base URL: `[PRODUCTION OR REVIEW ENVIRONMENT]`
- Account tier/entitlements: `[VERIFY]`
- Review account expiration: `[DATE AFTER REVIEW WINDOW]`

## Reviewer walkthrough

1. Launch NIJA.
2. Sign in with the dedicated reviewer account.
3. Confirm the app identifies Education/Simulation mode and that no real capital is used.
4. Open the dashboard and inspect simulated status, activity and risk information.
5. Open Brokers to see the broker-connect experience. Do not require real credentials to complete the review path.
6. Open Settings and verify Privacy Policy, Terms, support, and account deletion access.
7. Open the account deletion flow, review the confirmation screen, and cancel unless the reviewer specifically wants to test deletion.
8. Verify Live Mode remains server-gated and cannot be activated merely by changing a local mobile toggle.
9. Verify the emergency pause/stop control is clearly visible where applicable.

## App Review Notes draft

NIJA is an education-first trading software application with optional broker-connected functionality. The review account is configured for Education/Simulation mode and does not place real-money orders or require exchange credentials. Simulated results are clearly labeled and are not guarantees of future performance.

The mobile client is not an independent execution engine. Broker credentials and live-trading authority are controlled server-side. Live functionality is gated by authentication, user consent, broker readiness, risk controls, runtime authority and backend confirmation.

Account deletion is available from Settings and can be initiated in-app. The deletion request applies only to the NIJA account; it does not delete accounts held directly with third-party brokerages or app-store providers.

If the review team requires access to an additional feature, contact NIJA through the support contact entered in the store listing. Do not use real brokerage credentials during review.

## Pre-submission reviewer verification

- [ ] reviewer credentials actually work on a clean device
- [ ] no email verification or MFA loop blocks review
- [ ] Education/Simulation mode loads without broker credentials
- [ ] sample data is clearly labeled simulated
- [ ] no screen promises guaranteed profits, income or returns
- [ ] Privacy Policy and Terms links are reachable over public HTTPS
- [ ] account deletion starts inside the app
- [ ] support URL/contact works
- [ ] subscriptions/IAP do not block the review path unexpectedly
- [ ] all backend endpoints needed for the reviewer are operational
- [ ] no production secrets appear in logs or UI

## Important correction to older reviewer documents

Older NIJA review material described broker credentials as stored only on the device. That statement must not be used unless the release architecture is changed and verified to work that way. Current NIJA backend code includes encrypted server-side handling of user broker credentials, so review notes and privacy disclosures must reflect the actual release implementation.
