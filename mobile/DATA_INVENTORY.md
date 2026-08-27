# NIJA Mobile Data Inventory

**Status date:** 2026-08-27  
**Purpose:** Working source of truth for privacy review, Apple App Privacy, Google Play Data safety, deletion testing, security review, and counsel.

> This is a technical inventory, not a legal conclusion. Before submission, reconcile it against the exact production release build, production database schema, observability stack, payment configuration, push provider, analytics SDKs, and vendor contracts.

## Data map

| Data category | Examples | Source | Purpose | Stored by NIJA? | Shared / transmitted to | Deletion handling | Retention status |
|---|---|---|---|---|---|---|---|
| Account identifiers | user ID, email | User | authentication, account management, support | Yes | hosting/database providers as processors | delete/anonymize with account except lawful retention | counsel to confirm |
| Authentication data | password hash, session identifiers, JWT-related state | User/system | authentication/security | Yes | infrastructure providers | revoke sessions and remove account auth records | security policy to confirm |
| Subscription state | tier, purchase/subscription identifiers, entitlement state | Store/payment system | access control, billing support | Yes | Apple/Google/Stripe depending channel | detach/delete user linkage where permitted; transaction records may require retention | counsel/accounting to confirm |
| Broker connection credentials | API key, API secret, passphrase, broker metadata | User | connect to user's broker and execute authorized actions | Yes in current backend architecture; encrypted handling exists | selected broker/exchange when authenticating | revoke/remove NIJA-held credentials and runtime copies on deletion | immediate removal expected unless legal/security exception |
| Broker account data | balances, positions, order/trade information, broker account metadata | Broker | dashboard, risk controls, execution reconciliation | May be cached/logged/stored | selected broker, infrastructure processors | delete user-linked copies except required records | counsel to confirm |
| Trading activity | orders, fills, simulated trades, positions, P&L, risk state | System/broker | product functionality, audit, support, safety | Yes / likely | infrastructure, selected broker | delete or de-identify where allowed; regulated/tax/audit records may be retained | exact period must be approved by counsel |
| Risk/consent records | ToS acceptance, risk acknowledgment, consent timestamp/version | User/system | legal consent, safety gating, audit | Yes | infrastructure processors | may require retention after account deletion | counsel to confirm |
| Device data | platform, device ID, model, OS/app version | Device | device management, security, diagnostics | Prototype mobile API currently supports collection | push provider/infrastructure if enabled | remove device records on account deletion | production design to confirm |
| Push notification token | FCM/APNs token | Device/provider | push notifications | Prototype storage exists; currently in-memory in `mobile_api.py` | Apple APNs / Google FCM if enabled | unregister/delete token on logout/deletion | immediate |
| Network/security logs | IP address, timestamp, user agent, login success/failure | System | security, fraud prevention, incident response | Yes in authentication database/logs | hosting/observability processors | rotate/delete according to security retention schedule; may survive account deletion temporarily | exact period to define |
| Support data | email, support messages, attachments | User | customer support | Depends on support system | email/helpdesk provider | delete where legally permitted; retain dispute/accounting evidence when required | vendor + counsel to confirm |
| Analytics/diagnostics | usage events, crash reports, performance telemetry | App/system | reliability and product improvement | Not fully verified for release build | analytics/crash vendor if enabled | follow vendor deletion APIs/retention | must verify SDKs before store declaration |
| Coarse location / region | IP-derived country/region if used | System | security, availability, regulatory restrictions | Not confirmed as a dedicated field | infrastructure/analytics vendors | follow log retention | do not declare collection unless release build actually collects/derives it |
| Marketing data | email campaign status, attribution/referral info | User/marketing systems | marketing, acquisition, affiliate attribution | Outside core mobile app unless integrated | CRM/email/affiliate providers | honor opt-out/deletion rights | verify before store release |

## High-sensitivity data rules

- Never compile broker API secrets, database credentials, signing material, administrative tokens, or writer-authority secrets into the mobile client.
- Broker credentials handled by the backend must be encrypted at rest and protected by authenticated/authorized server APIs.
- Withdrawal permissions should be disabled on broker API credentials wherever the broker supports permission scoping.
- Sensitive values must not appear in client logs, server logs, crash reports, screenshots, analytics events, or reviewer materials.

## Deletion dependency checklist

A production account-deletion job must inspect and clean every applicable store below:

- [ ] persistent user account database
- [ ] sessions / refresh tokens / auth state
- [ ] user-manager caches
- [ ] broker credential store and runtime environment copies
- [ ] device and push-token registry
- [ ] user-specific strategy/risk configuration
- [ ] education/progress data
- [ ] subscription entitlement linkage
- [ ] analytics identity / crash identity where deletion APIs exist
- [ ] support/CRM identity where controlled by NIJA and legally deletable
- [ ] object storage / exports / uploaded files, if any
- [ ] database backups according to documented backup expiry schedule

## Store questionnaire classification worksheet

The final Apple/Google answers must be generated from the exact release configuration. Likely categories that need review include:

- Contact Info: email address; possibly name/phone if actually collected.
- User Content: support submissions if captured inside the app.
- Identifiers: user ID and device identifier/token.
- Purchases: subscription/purchase/entitlement information.
- Financial Info: broker balances/positions/trading account information; evaluate each store's precise definitions.
- Usage Data: product interaction events if analytics is enabled.
- Diagnostics: crash/performance data if a diagnostics SDK is enabled.
- Other Data: broker order/trade history or risk/consent state when no narrower category applies.

Do not copy this worksheet directly into a store form without validating the current store definitions and the release binary.
