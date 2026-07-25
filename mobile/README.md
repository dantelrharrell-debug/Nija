# NIJA AI Trading Mobile

> The mobile companion for NIJA AI Trading LLC

**Product status:** Pre-beta foundation  
**Mobile architecture:** Capacitor 5.7 wrapper today; Expo React Native conversion planned  
**Supported targets:** iOS and Android  
**Official website:** [nijaaitrading.com](https://nijaaitrading.com)

NIJA AI Trading Mobile is being built as a secure, mobile-first control and visibility layer for the NIJA trading platform. It is intended to help users understand system status, review signals and account activity, manage risk controls, and pause trading from an authenticated device.

The mobile app does not guarantee trades, profits, returns, income, order fills, or trading success. Live trading must remain locked until identity, consent, broker readiness, risk, and server-side execution checks all pass.

---

## Current Progress

This repository contains a real mobile foundation, but it is not yet a production mobile release.

| Area | Status | Current evidence |
|---|---|---|
| Capacitor mobile wrapper | Implemented | `package.json`, `capacitor.config.json`, `ios/`, and `android/` |
| Shared web interface | Implemented/prototype | `frontend/` is the current Capacitor web asset source |
| Mobile setup and build guides | Implemented | `setup-mobile.sh` and `mobile/BUILD_GUIDE.md` |
| Mobile backend routes | Prototype | `mobile_api.py` provides mobile-oriented endpoints |
| Native store projects | Generated | Native iOS and Android projects are present |
| Official black-and-gold mobile design | Defined; integration incomplete | Legacy dark-blue/purple values still need replacement |
| Five-tab mobile experience | Defined; implementation incomplete | Home, Signals, Trades, Risk, and Profile |
| Production authentication | Blocked | Mobile routes still contain authentication TODOs |
| Secure token and secret storage | Blocked | Must be implemented and verified on both platforms |
| Push notifications and biometrics | Dependencies/plans only | End-to-end production behavior is not yet verified |
| Automated mobile testing | Blocked | Unit, integration, accessibility, and end-to-end suites remain |
| App Store and Play release | Not submitted | Signing, privacy review, store assets, testing, and approval remain |

“Implemented” means code or project assets are present in this repository. It does not mean the feature has passed production security review, device QA, or store approval.

---

## Product Experience

The planned mobile navigation has five primary tabs:

1. **Home** — account status, connected brokers, system state, open positions, risk summary, and emergency pause.
2. **Signals** — confidence, ADX, volume, spread, fees, readiness, and clear pass/skip reasons.
3. **Trades** — completed, failed, skipped, and simulated activity with broker-scoped details.
4. **Risk** — loss limits, position size, balance checks, disclosures, consent, and Live Mode requirements.
5. **Profile** — account, connected brokers, privacy, terms, support, notification settings, and account deletion.

Education and simulation states should explain what NIJA is evaluating without presenting simulated or historical output as guaranteed future performance.

---

## Official NIJA Brand System

The official NIJA identity is the black-and-gold sword-and-laurel emblem. Mobile screens, store assets, icons, splash screens, and marketing previews must use approved NIJA artwork.

### Core colors

| Token | Value | Use |
|---|---|---|
| NIJA Black | `#050505` | Primary background |
| NIJA Surface | `#111111` | Cards, sheets, and navigation |
| NIJA Gold | `#D4AF37` | Primary accent and selected states |
| NIJA Light Gold | `#F4D06F` | Highlights and accessible accent text |
| NIJA White | `#F7F7F7` | Primary text |
| NIJA Muted | `#A7A7A7` | Secondary text |
| NIJA Danger | `#D64545` | Emergency and destructive actions |

### Brand rules

- Keep the emblem’s proportions unchanged.
- Use the gold emblem on black or near-black backgrounds.
- Do not recolor the official emblem with legacy blue or purple accents.
- Keep enough clear space around the emblem to prevent crowding.
- Use gold for emphasis, not for long body text.
- Use red only for danger, emergency stop, or destructive confirmation.
- Never use branding to imply guaranteed investment performance.

The current Capacitor configuration still contains legacy dark-blue and purple UI values. Replacing those values and installing final icon/splash assets is a required release milestone.

---

## Current Repository Structure

```text
Nija/
├── package.json                 # Capacitor dependencies and native commands
├── capacitor.config.json        # Current native wrapper configuration
├── setup-mobile.sh              # Mobile setup helper
├── ios/                         # Generated iOS project
├── android/                     # Generated Android project
├── frontend/                    # Current web interface bundled by Capacitor
├── mobile/
│   ├── README.md                # This mobile source of truth
│   ├── BUILD_GUIDE.md           # Native build instructions
│   ├── PRIVACY_POLICY.md        # Draft policy requiring legal review
│   ├── TERMS_OF_SERVICE.md      # Draft terms requiring legal review
│   ├── ios/                     # iOS-specific guidance
│   ├── android/                 # Android-specific guidance
│   └── assets/                  # Mobile brand and store assets
├── mobile_api.py                # Prototype mobile API blueprint
└── api_server.py                # Backend API integration
```

The current bundle identifier is `com.nija.trading`. The planned Expo package identifier previously defined for both platforms is `com.nijaaitrading.app`. One identifier must be selected and locked before signing, deep-link configuration, push certificates, or store records are finalized.

---

## Planned Expo React Native Target

The next mobile architecture is planned as an Expo React Native application. This is a target structure, not a claim that these files already exist:

```text
mobile-expo/
├── app/
│   ├── (auth)/
│   ├── (tabs)/
│   │   ├── index.tsx            # Home
│   │   ├── signals.tsx
│   │   ├── trades.tsx
│   │   ├── risk.tsx
│   │   └── profile.tsx
│   └── _layout.tsx
├── src/
│   ├── components/
│   ├── features/
│   ├── hooks/
│   ├── services/                # Authenticated backend client only
│   ├── store/
│   ├── theme/                   # NIJA black-and-gold tokens
│   ├── types/
│   └── tests/
├── assets/
├── app.json
├── eas.json
├── package.json
└── .env.example
```

Expo conversion must preserve the existing server-side trading and safety boundaries. Mobile clients may request authorized actions; they must never become an independent trading engine.

---

## Local Setup: Current Capacitor App

### Prerequisites

- Git
- Node.js 18 or newer
- npm
- Xcode on macOS for iOS builds
- Android Studio and a supported JDK/Android SDK for Android builds
- A separately running NIJA backend for authenticated integration testing

### Install

```bash
git clone https://github.com/dantelrharrell-debug/Nija.git
cd Nija
npm install
./setup-mobile.sh
```

### Sync and open native projects

```bash
npm run cap:sync
npm run cap:open:ios
npm run cap:open:android
```

Read [BUILD_GUIDE.md](BUILD_GUIDE.md) before creating native release builds.

### Environment and endpoint guidance

The current frontend uses its runtime origin for API calls. Production mobile work must add an explicit, validated HTTPS API configuration contract before release.

Mobile builds must never contain:

- Kraken, Coinbase, OKX, Alpaca, or other broker secrets.
- Private signing material.
- Database credentials.
- Redis credentials.
- Writer-authority or Live Mode bypass values.
- Administrative backend tokens.

Only public mobile configuration—such as an HTTPS API base URL, app environment label, and public observability identifiers—may be compiled into the client.

---

## Security and Trading Boundaries

### Server-side only

The backend remains the authority for:

- Broker credentials and connection state.
- Capital and balance verification.
- Writer lease and fencing authority.
- Signal qualification and order admission.
- Position sizing and exchange minimums.
- Live order submission.
- Take-profit, stop-loss, and emergency controls.
- Audit logs and broker-scoped execution evidence.

### Mobile responsibilities

The mobile client may:

- Authenticate a user.
- Display server-authoritative status and activity.
- Request an allowed state transition.
- Record explicit risk acknowledgment and consent.
- Request an emergency pause.
- Register a push-notification device after authentication.

The mobile client must not:

- Store broker API secrets on the device.
- Decide that trading is live based only on a local toggle.
- Bypass backend risk, authority, or readiness checks.
- Treat a successful request as proof of an order fill.
- expose sensitive credentials or tokens in logs.

### Known security blockers

`mobile_api.py` currently identifies authentication and persistent device-token storage as TODOs. Those endpoints must not be exposed publicly until authentication, authorization, rate limits, durable encrypted storage, audit logging, and abuse controls are complete.

---

## Live Mode Gate

Live Mode must stay unavailable until every required condition is satisfied:

1. The user is authenticated.
2. Required disclosures are displayed.
3. Risk acknowledgment and consent are recorded.
4. Broker permissions are valid and withdrawals are disabled.
5. Spendable balance and broker readiness are verified server-side.
6. Writer authority and runtime state are valid.
7. Risk limits and emergency pause are active.
8. Audit logging is available.
9. The device request is authorized.
10. The backend confirms the requested transition.

The interface must clearly distinguish **Off**, **Education**, **Simulation**, **Monitor**, **Live Pending**, **Live**, **Degraded**, and **Emergency Paused** states.

---

## Six-Stage Mobile Roadmap

### Stage 1 — Foundation and truth audit

- Reconcile current Capacitor assets, native projects, API routes, and documentation.
- Remove unsupported completion claims.
- Lock the application identifier and release ownership.
- Apply the official NIJA black-and-gold design system.

### Stage 2 — Secure backend contract

- Protect every mobile endpoint with production authentication and authorization.
- Define versioned request/response schemas.
- Add durable device registration, token rotation, rate limits, and audit logs.
- Add a safe production API configuration contract.

### Stage 3 — Core mobile experience

- Implement Home, Signals, Trades, Risk, and Profile.
- Add explicit loading, empty, degraded, offline, and error states.
- Build disclosure, consent, broker connection, and account-deletion flows.
- Keep Education/Simulation as the safe default experience.

### Stage 4 — Native integration

- Complete Expo React Native conversion or formally retain Capacitor.
- Implement secure token storage, biometrics, push notifications, deep links, and accessibility.
- Install approved icons, splash screens, and store artwork.

### Stage 5 — Verification and compliance

- Add unit, integration, end-to-end, security, accessibility, and device tests.
- Complete threat modeling and penetration testing.
- Obtain legal review of privacy, terms, disclosures, retention, and account deletion.
- Run TestFlight and Google Play internal testing with production-like backend controls.

### Stage 6 — Store release and operations

- Complete Apple and Google privacy disclosures and store metadata.
- Submit signed builds for review.
- Monitor crashes, authentication, API health, and emergency actions.
- Establish incident response, support, release, and rollback procedures.

---

## Next Ten Development Milestones

1. Choose and lock `com.nija.trading` or `com.nijaaitrading.app`.
2. Replace legacy blue/purple native styling with approved black-and-gold assets.
3. Authenticate and authorize every route in `mobile_api.py`.
4. Add durable encrypted device-token storage and token revocation.
5. Implement the five-tab mobile navigation and server-authoritative states.
6. Complete disclosure, consent, Live Mode gating, and emergency pause flows.
7. Implement and verify secure local session storage, biometrics, and push delivery.
8. Add unit, API-contract, end-to-end, accessibility, offline, and device tests.
9. Complete legal/privacy review and prepare accurate Apple/Google store metadata.
10. Ship verified builds to TestFlight and Google Play internal testing before public submission.

---

## Testing Expectations

Release candidates must verify at minimum:

- First launch without credentials or a session.
- Login, logout, expiration, refresh, revocation, and account deletion.
- Safe behavior during offline, slow, and failed API states.
- Accurate broker-specific balance, position, trade, and readiness displays.
- Explicit Simulation versus Live presentation.
- Live Mode denial when any required gate fails.
- Emergency pause confirmation and server acknowledgment.
- Push notification opt-in, delivery, tap routing, and token revocation.
- No credentials, tokens, or sensitive financial data in logs.
- Screen-reader, contrast, text scaling, touch-target, and reduced-motion behavior.

Do not describe the app as store-ready until these checks pass on supported physical devices and the signed builds are accepted by the relevant stores.

---

## Documentation

- [Mobile build guide](BUILD_GUIDE.md)
- [Privacy policy draft](PRIVACY_POLICY.md)
- [Terms of service draft](TERMS_OF_SERVICE.md)
- [Repository issues](https://github.com/dantelrharrell-debug/Nija/issues)

Privacy, terms, disclosures, pricing, and store declarations require qualified legal and compliance review before release.

---

## Contribution and Ownership

- NIJA AI Trading LLC owns the NIJA name, sword-and-laurel emblem, and official brand assets.
- The repository license is governed by the root `LICENSE` file; the license does not transfer NIJA trademark rights.
- Use focused branches and reviewed pull requests for mobile changes.
- Never commit `.env` files, broker credentials, signing keys, certificates, provisioning profiles, keystores, or production tokens.
- Keep backend trading controls separate from mobile presentation code.
- Update this README when an implementation milestone is actually verified.

---

## Risk Disclosure

NIJA AI Trading is software, not financial, investment, tax, or legal advice. Cryptocurrency trading involves substantial risk and may result in partial or total loss. Users remain responsible for their accounts, permissions, risk choices, and trading outcomes.

