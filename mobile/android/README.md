# Android App Store Configuration

This directory documents Android-specific configuration for the NIJA mobile app. The generated Capacitor Android project is not committed here yet; after generation, treat the requirements below as release gates.

## Google Play release baseline - August 2026

For new apps and updates submitted after August 31, 2026, NIJA must target Android 16 / API level 36 or higher.

Required generated Gradle configuration:

```gradle
android {
    compileSdkVersion 36

    defaultConfig {
        applicationId "REPLACE_WITH_FINAL_NIJA_APPLICATION_ID"
        minSdkVersion 23
        targetSdkVersion 36
        versionCode 1
        versionName "1.0.0"
    }
}
```

Do not lock the placeholder application ID until the permanent NIJA Android application ID has been approved. Signing, Firebase registration, app links, and Play developer verification must all use that permanent ID.

Run the repository release check after generating Android:

```bash
python scripts/validate_mobile_store_readiness.py --strict
```

The check must report `compileSdk >= 36` and `targetSdk >= 36` before a Play release is created.

## Required permissions

Keep permissions minimal and tied to shipping features:

```xml
<uses-permission android:name="android.permission.INTERNET" />
<uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />
<uses-permission android:name="android.permission.POST_NOTIFICATIONS" />
<uses-permission android:name="android.permission.VIBRATE" />
<uses-permission android:name="android.permission.USE_BIOMETRIC" />
```

Add camera only if QR scanning actually ships. Do not add legacy broad external-storage permissions or call-log permissions unless a reviewed production feature has a documented need and store/privacy declarations have been updated.

## Application security baseline

Production must use TLS/HTTPS only and disable cleartext traffic. Development-only localhost exceptions must not be shipped accidentally.

Example application configuration:

```xml
<application
    android:allowBackup="false"
    android:usesCleartextTraffic="false"
    android:networkSecurityConfig="@xml/network_security_config">
</application>
```

## Push notifications

Firebase Cloud Messaging requires:

1. Final permanent Android application ID.
2. Firebase project/app registration using that ID.
3. Production `google-services.json` supplied through the secure build process.
4. FCM service credentials configured server-side, never embedded as secrets in the client repository.
5. NIJA device registration through the authenticated mobile API.
6. Account deletion/logout to remove applicable persisted push-device records.

NIJA's backend now persists push tokens in encrypted storage through `mobile_device_store.py`; production must place the configured device database on durable storage or replace it with an equivalent durable database implementation.

## Google Play account and policy gates

Before production submission:

- [ ] Permanent Android application ID finalized.
- [ ] Organization/developer verification completed in Play Console as applicable.
- [ ] Financial-features declaration completed accurately.
- [ ] Google Data Safety answers reconciled to the shipping binary/backend and `mobile/DATA_INVENTORY.md`.
- [ ] Any third-party AI/LLM integration audited for user-data transmission and disclosed where required.
- [ ] Privacy policy URL is public and matches actual production processing.
- [ ] Account deletion is available in-app and through the required external/web mechanism.
- [ ] Reviewer/test credentials are supplied if authentication blocks review.
- [ ] Signed AAB built with Play App Signing or approved signing process.
- [ ] Release tested on Android 16 / API 36 physical device or representative emulator plus supported minimum SDK devices.

## Third-party AI rule

`education_system.py` currently contains an AI explanation placeholder/TODO rather than an enabled outbound provider call in the inspected path. If NIJA later adds OpenAI or another AI/LLM provider, that change must include, in the same release:

- data-flow inventory update;
- processor/vendor record;
- privacy policy and Google Data Safety review;
- consent/disclosure review where required;
- retention/deletion design;
- explicit prevention of broker/API credentials and unnecessary financial data entering prompts.

## Signing

Never commit keystores, key passwords, service-account credentials, or Firebase server secrets. Google Play App Signing is recommended for production. Keep upload/signing material in the appropriate secure store.

## Build commands after Capacitor generation

```bash
npm run cap:sync
cd android
./gradlew bundleRelease
```

Before upload, run:

```bash
python scripts/validate_mobile_store_readiness.py --strict
```

See also `mobile/APP_STORE_POLICY_DELTA_2026-08-27.md`, `mobile/DATA_INVENTORY.md`, `mobile/PRODUCTION_SECURITY_CHECKLIST.md`, and `mobile/ACCOUNT_DELETION.md`.
