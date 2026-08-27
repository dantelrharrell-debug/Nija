# NIJA Store Privacy Disclosure Worksheet

**Status date:** 2026-08-27  
**Purpose:** Pre-fill the factual work needed for Apple App Privacy and Google Play Data safety.  
**Rule:** Final answers must match the exact signed release build, production backend, enabled SDKs, and current store definitions at submission time.

## Release facts to lock before answering store forms

- App version/build: `[VERIFY BEFORE SUBMISSION]`
- Bundle/package identifier: `[LOCK ONE IDENTIFIER]`
- Production API hostname: `[VERIFY]`
- Authentication provider: NIJA backend JWT unless changed before release
- Payment channels enabled in mobile release: `[APPLE IAP / GOOGLE PLAY BILLING / OTHER — VERIFY]`
- Push notifications enabled: `[YES/NO — VERIFY]`
- Analytics SDK enabled: `[NAME OR NONE — VERIFY]`
- Crash/diagnostics SDK enabled: `[NAME OR NONE — VERIFY]`
- Advertising SDK or ad network: `[NAME OR NONE — VERIFY]`
- Third-party login provider: `[NAME OR NONE — VERIFY]`
- Support/helpdesk provider: `[VERIFY]`
- Cloud/database/observability processors: `[VERIFY PRODUCTION VENDORS]`

## Data category worksheet

| Data type | Does current NIJA architecture plausibly handle it? | Purpose | Linked to user? | Tracking / ads? | Final store answer |
|---|---|---|---|---|---|
| Email address | Yes | account creation, authentication, support | Yes | No unless separately integrated | VERIFY |
| User ID | Yes | account and authorization | Yes | No | VERIFY |
| Password credential | Password is received for authentication and stored as a hash server-side | authentication/security | Yes | No | VERIFY store treatment |
| Purchase / entitlement data | Yes when subscriptions/IAP are enabled | billing and feature access | Yes | No | VERIFY payment path |
| Broker API credentials | Yes, encrypted backend handling exists | connect user's broker | Yes | No | VERIFY store taxonomy and release behavior |
| Brokerage balances / positions | Yes for broker-connected functionality | product functionality and risk monitoring | Yes | No | VERIFY |
| Order / trade history | Yes | trading functionality, history, audit/support | Yes | No | VERIFY |
| Simulation activity | Yes | education/paper trading | Yes or local/session-linked | No | VERIFY |
| Risk acknowledgments / ToS acceptance | Yes | consent, safety, legal record | Yes | No | VERIFY |
| Device identifier / device metadata | Prototype mobile API supports it | push/device management, security | Potentially | No | VERIFY if enabled in release |
| Push token | Prototype support exists | notifications | Yes/pseudonymous | No | VERIFY if enabled |
| IP address | Authentication/security logging can process it | security/fraud/operations | Potentially | No | VERIFY current store taxonomy |
| User agent / app/device version | Yes in session/device paths | security, compatibility, diagnostics | Potentially | No | VERIFY |
| Crash data | Only if diagnostics collection is actually enabled | reliability | Depends on SDK | No unless vendor does otherwise | VERIFY SDK |
| Performance data | Only if diagnostics/telemetry is enabled | reliability | Depends | No unless vendor does otherwise | VERIFY SDK |
| Product interaction / analytics | Not assumed | analytics/product improvement | Depends | No unless separately configured | VERIFY SDK |
| Precise location | No known product requirement | — | — | — | Declare only if actually collected |
| Coarse location | May be inferable from IP; no dedicated collection should be assumed | security/regulatory if used | Potentially | No | VERIFY actual processing |
| Contacts | No known requirement | — | — | — | Expected NO unless feature added |
| Photos/videos/audio | No known requirement | — | — | — | Expected NO unless feature added |
| Health/fitness | No known requirement | — | — | — | Expected NO |
| Advertising data | No known requirement | — | — | — | Expected NO unless ad/attribution SDK added |

## Apple App Privacy preparation

For every data type Apple asks about, determine from the release implementation:

1. Is the data collected from the app or transmitted off-device?
2. Is it linked to the user's identity/account?
3. Is it used for third-party advertising or advertising measurement?
4. Is it used for analytics, product personalization, app functionality, developer advertising/marketing, or another purpose?
5. Does a third-party SDK collect it, even if NIJA does not directly read the raw value?

### Working NIJA stance

- Do not claim "data not collected" merely because NIJA does not sell data.
- Do not classify server-side broker data as device-only.
- Do not classify payment data as directly collected by NIJA if the app-store payment provider handles it and NIJA receives only transaction/entitlement metadata; verify the exact integration first.
- No tracking declaration should be made until every SDK/domain in the signed build is audited.

## Google Play Data safety preparation

Before submitting the Data safety form, verify:

- which data types are collected;
- which data types are shared with third parties;
- whether collection is required or optional;
- purposes for collection/sharing;
- whether data is encrypted in transit;
- whether users can request account/data deletion;
- whether any data is processed ephemerally;
- third-party SDK behavior and provider retention.

### Account deletion evidence

- In-app route: **Settings → Privacy & Account → Delete Account**
- Authenticated API: `DELETE /api/account/deletion`
- Public web instructions source: `mobile/ACCOUNT_DELETION.md`
- Production public deletion URL: `[PUBLISH AND ENTER IN PLAY CONSOLE]`

## Third-party processor audit

Complete this table before store submission. Do not infer vendors from old documentation.

| Provider | Service | Data received | Processing purpose | DPA/terms reviewed | Deletion/retention behavior verified | Included in store declarations |
|---|---|---|---|---|---|---|
| Apple | App distribution / IAP if enabled | `[VERIFY]` | distribution/payment | [ ] | [ ] | [ ] |
| Google | Play distribution / billing / FCM if enabled | `[VERIFY]` | distribution/payment/push | [ ] | [ ] | [ ] |
| Brokerage providers | user-authorized brokerage integration | credentials, account/trading requests as applicable | broker connection/execution | [ ] | [ ] | [ ] |
| Hosting/database provider | backend infrastructure | account and application data | app functionality/security | [ ] | [ ] | [ ] |
| Payment processor outside stores | only if present in release flow | `[VERIFY]` | payments | [ ] | [ ] | [ ] |
| Analytics/crash provider | only if enabled | `[VERIFY]` | analytics/reliability | [ ] | [ ] | [ ] |
| Support/email provider | if integrated | support identity/content | support | [ ] | [ ] | [ ] |

## Sign-off

- [ ] Engineering confirms this worksheet matches the signed binary and production backend.
- [ ] Security confirms SDK/network traffic inventory.
- [ ] Product confirms feature descriptions and optional/required collection.
- [ ] Counsel confirms privacy-policy language, retention, deletion exceptions, and financial-service disclosures.
- [ ] Apple App Privacy answers copied from verified facts, not historical documentation.
- [ ] Google Play Data safety answers copied from verified facts, not assumptions.
