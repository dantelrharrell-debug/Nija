# TIQ12 / issue #3703 — independent browser acceptance specification

Status: DRAFT ONLY. All cases NOT EXECUTED. No certification or publication authorized.

## Preconditions and identity
- Obtain authenticated export from IONOS project aibuilder-4dfdf for unpublished /trading-iq-challenge preview.
- Record provider-confirmed saved preview build ID, export SHA-256, exact source commit/archive, lockfile hashes, build command, generated artifact SHA-256, and approved eagle logo checksum.
- Do not substitute Vercel five/six-round game, 72-decision sandbox, or synthetic TIQ12 contract manifest.
- Test isolated local build with synthetic data only. No customer data, live Stripe, broker API, trading runtime or production URLs.
- For every case log status NOT RUN/PASS/FAIL/BLOCKED, timestamp UTC, build hash, browser/device/version, viewport, expected and actual outcome, screenshots/traces and reviewer.

## Cases
| ID | Steps | Expected evidence |
|---|---|---|
| GAME-01 | New private browser session; open game; start without account | Anonymous entry works; no authentication dependency |
| GAME-02 | Complete 12 rounds sequentially | Twelve unique ordered scenarios, correct choices, feedback, animations and progress |
| GAME-03 | Try blank answer, duplicate click, back navigation and skip | No accidental duplicate completion, bypass or invalid state |
| GAME-04 | Run all-best, all-lowest and mixed canonical answer fixtures | Score and each category exactly match independently calculated canonical manifest |
| GAME-05 | Restart, replay, reload during round and after completion | Behavior matches approved persistence/resume spec; report any lost state |
| LAB-01 | Enter and complete each of four Practice Lab modules | All four modules present, navigable, functional with correct feedback |
| LAB-02 | Reset modules, use keyboard, inspect simulation outputs | Reset consistent; no real brokerage or trading activity |
| SCORE-01 | Finish known-answer fixtures and inspect five-area scorecard | Each formula, category and rounding matches canonical scoring specification |
| SCORE-02 | Inspect eight achievements, NIJA Coach, lesson links and replay comparison | Match approved content, eligibility and deterministic triggers |
| SCORE-03 | Inspect fictional profit examples | Simulated returns excluded from scoring; no promised returns |
| UI-01 | Screenshots at 320, 375, 390, 768 and 1280 CSS px | No horizontal overflow, clipping, obscured controls or broken text |
| UI-02 | Chromium, WebKit/Safari, iPhone/iPad and Android Chrome | Touch, orientation and responsive interactions function |
| A11Y-01 | Keyboard-only complete journey | Logical tab order, focus visible, no traps, all controls usable |
| A11Y-02 | Inspect semantics, labels, contrast and dynamic feedback | Accessible names, headings, announcements and contrast verified |
| A11Y-03 | Enable prefers-reduced-motion | Nonessential motion suppressed; content and function preserved |
| A11Y-04 | Manually complete journey with iPhone VoiceOver and Android TalkBack | Real-device assistive-technology record, not just automated audit |
| SAFE-01 | Complete all rounds in clean anonymous session | No registration, paid backend or brokerage needed |
| SAFE-02 | Block optional billing network requests | Free game still usable |
| SAFE-03 | Inspect all payment links/buttons and network requests | No functional checkout, payment collection or live Stripe invocation |
| SAFE-04 | Exercise youth flows and age controls | No purchase solicitation to minors |
| SAFE-05 | Inspect requests/storage under free-play journey | No trade orders, customer-data writes, sensitive data or secret leakage |
| SAFE-06 | Deny browser storage and reload | Graceful failure/recovery without sensitive data in local storage |

## Execution phases
1. NOW: review pure contract tests and schema tests with synthetic fixtures, document results separately as contract-only; do not claim IONOS gameplay parity.
2. AFTER EXPORT: static inventory, source-to-preview provenance, scoring manifest extraction, build in isolated workspace, Chromium/WebKit Playwright tests, screenshots and traces.
3. MANUAL: iPhone Safari/VoiceOver, Android Chrome/TalkBack, iPad, actual visual comparison with IONOS approved reference.
4. RELEASE GATE: reviewer confirms exact tested artifact and independently verified rollback; owner separately approves free-game-only publication. Paid report stays disabled.

## Hard stop
Missing canonical export, unmatched build/asset hash, incomplete rounds or labs, inaccessible game, functional checkout, broker calls, or uncertain rollback = BLOCKED. Never convert NOT EXECUTED to PASS.
