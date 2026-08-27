# NIJA Mobile Store Policy Delta - 2026-08-27

This document records mobile-store policy changes that materially affect NIJA release readiness. It is an engineering/compliance checklist, not legal advice.

## P0 - Google Play target API

- New apps and app updates submitted after 2026-08-31 must target Android 16 / API level 36 or higher.
- NIJA's generated Android project must use `compileSdk >= 36` and `targetSdk >= 36` before release.
- The repository now includes `scripts/validate_mobile_store_readiness.py` and a CI workflow that rejects a generated Android project below API 36.
- The Android project is not currently generated in this repository, so the final SDK change must be applied immediately after Capacitor generates the project.

## P0 - Data Safety / third-party AI audit

Google Play's User Data requirements apply when user data is sent to third-party AI services. Before release:

- Inventory every AI/LLM provider used by the shipping app or backend.
- Record exactly which user data categories are transmitted to each provider.
- Do not send broker API credentials, authentication secrets, financial account credentials, or unnecessary trading/account data to an AI provider.
- Ensure the privacy policy, Google Data Safety form, consent/disclosure flow, retention policy, deletion flow, and vendor processor list match the shipping implementation.

### Current repository finding

`education_system.py` contains an AI Q&A placeholder and a TODO to integrate an AI provider; it does not currently implement an outbound OpenAI/LLM call in that path. Treat the feature as NOT ENABLED until an actual provider integration is added. Any future integration must update the data inventory and store declarations in the same pull request.

## P1 - Google developer verification

- Confirm NIJA is published from an organization developer account when required for financial features.
- Finalize the permanent Android application/package ID before verification.
- Confirm the Play Console developer-verification/registration status before production rollout.
- This is primarily a Google Play Console/account action and cannot be completed from repository code alone.

## P1 - Apple EU business/payment terms

Apple introduced updated EU App Store business/payment terms in August 2026 with an October 1, 2026 effective date.

Before distributing NIJA in EU storefronts:

- Account Holder reviews and accepts the applicable Apple Developer agreement.
- Counsel/product decide whether NIJA uses Apple In-App Purchase, permitted alternative payments, or another compliant subscription structure in the EU.
- Store metadata and user-facing purchase disclosures must match the selected implementation.

This is not treated as a U.S.-only launch blocker, but it is a blocker for an EU launch until the commercial/payment path is approved.

## P1 - Authentication permissions

NIJA should not introduce Android call-log permissions for account verification. The mobile app currently has no demonstrated need for `READ_CALL_LOG`; keep it absent from the production manifest.

## Permanent-ID dependency

Do not lock signing, associated domains, universal/app links, Firebase/APNs identifiers, or Google developer verification to a temporary app ID. The permanent iOS bundle identifier and Android application ID remain an owner decision and should be finalized before store registration/signing.

## External actions that remain outside the codebase

- Accept Apple Developer agreements.
- Complete Google Play organization/developer verification.
- Create production signing identities/keystores and provisioning configuration.
- Provide APNs/FCM production credentials.
- Perform physical-device testing and domain/associated-link verification.
- Obtain counsel's financial-services/regulatory classification and final legal-document approval.
