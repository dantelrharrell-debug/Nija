# NIJA Track A — App Store Preparation

**Status date:** 2026-08-27  
**Scope:** $0 / low-cost preparation before paid store enrollment, signing, submission, or outside counsel.  
**Canonical mobile architecture today:** Capacitor iOS + Android shell using the existing `frontend/` application.

## Purpose

Track A prepares NIJA for Apple App Store and Google Play review without claiming that the application is already approved, signed, legally cleared, or production-secure. It deliberately separates work that can be completed in the repository from work that requires Apple/Google accounts, production infrastructure, physical-device QA, or licensed counsel.

## Track A completion matrix

| Workstream | Track A state | Evidence / next action |
|---|---|---|
| Existing iOS/Android shell | COMPLETE | `ios/`, `android/`, Capacitor config and frontend already exist |
| Education/simulation safe default | IMPLEMENTED / VERIFY ON DEVICE | Existing onboarding and simulation UI; must be device-tested |
| Data inventory | COMPLETE AS WORKING INVENTORY | `mobile/DATA_INVENTORY.md`; must be reconciled against production vendors before submission |
| Privacy disclosure worksheet | COMPLETE AS DRAFT | `mobile/STORE_PRIVACY_DISCLOSURES.md`; answer store questionnaires from actual release build only |
| Account deletion contract | IMPLEMENTED | Authenticated API endpoint plus in-app Settings deletion control |
| Public deletion instructions | CONTENT READY | `mobile/ACCOUNT_DELETION.md`; publish at a public HTTPS page before Google Play submission |
| Reviewer instructions | COMPLETE AS DRAFT | `mobile/REVIEWER_ACCESS.md`; provision actual reviewer account externally before review |
| Apple listing copy | COMPLETE AS DRAFT | `mobile/STORE_LISTING_MATERIALS.md` |
| Google Play listing copy | COMPLETE AS DRAFT | `mobile/STORE_LISTING_MATERIALS.md` |
| Screenshot / graphic shot list | COMPLETE | `mobile/STORE_LISTING_MATERIALS.md`; final images require a running release candidate |
| Privacy Policy | EXISTING, NEEDS COUNSEL + FACT CHECK | `mobile/PRIVACY_POLICY.md`; older claims must not be published unchanged |
| Terms of Service | EXISTING, NEEDS COUNSEL | `mobile/TERMS_OF_SERVICE.md` |
| Risk disclosure | EXISTING IN PRODUCT / NEEDS COUNSEL | Verify exact wording and placement in release build |
| Bundle/package identifier | BLOCKED DECISION | Repo contains `com.nija.trading` and a proposed `com.nijaaitrading.app`; select one before signing/store records |
| Production authentication for every mobile route | NOT COMPLETE | `mobile_api.py` still has unauthenticated prototype routes; release blocker |
| Secure durable push-token storage | NOT COMPLETE | Current mobile API contains in-memory placeholder storage; release blocker if push is enabled |
| Store developer enrollment | EXTERNAL / PAID | Apple and Google account actions are outside Track A repository work |
| Signing certificates / provisioning / keystore | EXTERNAL | Create only when identifiers and store ownership are locked |
| TestFlight / Play internal test | EXTERNAL | Requires signed build and store accounts |
| Legal approval | EXTERNAL | Counsel must approve privacy, terms, financial-risk disclosures, retention, deletion exceptions and regulatory positioning |

## Release-truth rules

1. Do not say NIJA is "App Store ready," "approved," "compliant," or "100% complete" until the actual signed release build and store declarations have been verified.
2. Store privacy answers must describe the exact release build and production backend, not roadmap features.
3. Do not state that broker credentials are "device-only." Current backend code supports encrypted server-side credential handling.
4. Do not state that account deletion removes legally required records if those records must be retained. The UI and policy must distinguish account closure from legally required retention.
5. Do not provide reviewers with real-money broker credentials. Review should use Education/Simulation mode and a dedicated reviewer account.
6. Never place reviewer passwords, broker keys, signing keys, or production secrets in this public repository.

## What is left after Track A

### Engineering release blockers

- Authenticate and authorize every mobile endpoint.
- Replace prototype/in-memory mobile data stores with production storage or disable the affected feature.
- Confirm deletion reaches every production data store and third-party processor that NIJA controls.
- Lock one application identifier.
- Run automated tests plus physical-device iOS/Android QA.
- Produce final icons, splash assets, screenshots and store graphics from the release candidate.

### External actions

- Publish Privacy Policy, Terms, support, and account-deletion pages at stable HTTPS URLs.
- Create the dedicated reviewer account in production/staging with non-expiring review access.
- Enroll / configure Apple Developer and Google Play Console accounts.
- Complete Apple App Privacy and Google Data safety questionnaires from the verified data inventory.
- Obtain counsel sign-off.
- Upload signed builds to TestFlight and Play internal testing before public review.

## Track A acceptance criteria

Track A is considered complete when this packet, the deletion flow, store copy, privacy worksheet and reviewer instructions are in the repo and no document falsely represents external approval or unverified implementation as complete.
