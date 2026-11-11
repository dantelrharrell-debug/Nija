# Upgrade 5B — review of the reusable Trading IQ server code (preview only)

Status: review and plan only. Nothing here is deployed, promoted to the live site, or connected to payments.

## 1. What was inspected

Source: `dantelrharrell-debug/Nija`, `main` (commit 163b6d3), files
- `web/trading-challenge/server/scoring.mjs` (55 lines)
- `web/trading-challenge/server/index.mjs` (159 lines)
- `web/trading-challenge/api/checkout.mjs` (wrapper around the same handler)

No code was copied into the app. Findings below.

## 2. Can it support the IONOS game? — No (not as-is)

| Need | GitHub code | IONOS game |
|---|---|---|
| Decision model | One of 3 fixed answers to 6 scenarios | Buy 25% / Sell all / Hold / optional 5% stop-loss, 12 rounds per challenge |
| Scenarios | 6 fixed, from `public/scenarios.js` | 6 standard + 3 extra daily-rotation scenarios |
| Difficulty levels | None | Beginner / Intermediate / Advanced (price swings differ) |
| Daily challenges | None | Daily rotation, UTC day numbers |
| Score basis | Answer points per category | Portfolio value path, drawdown, trades, stop-loss use |

So the scoring cannot be reused for the current game. A server engine must replay the same portfolio rules over the same seeded price paths.

## 3. Security problems found (must be fixed before any use)

1. **Browser controls the score.** The checkout sends the player's answers in the request, and they are stored in the Stripe session metadata. The results route re-scores whatever the metadata contains. The browser therefore controls the premium score. This breaks the requirement that the browser must not control scores or payment authorization.
2. **Payment is not tied to a person or a run.** Any holder of a paid session ID can read the report. There is no duplicate-purchase check and no link to a server-issued run.
3. **Answer validation is weak.** Only the shape of the answers is checked, not that they came from a real run of the game.
4. **Positive:** the checkout requires an allowed origin, rate-limits by IP, rejects non-test/unpaid/wrong-currency sessions, and sends the secret key only from the environment. Keep these ideas.

## 4. Plan for the IONOS game (requires owner approval for the server part)

- **Server run record.** At run start the server issues a run ID, the scenario seed and level, and stores the price paths it generated. Decisions are sent per round and checked against that record.
- **Authoritative score.** The server replays the portfolio rules from the stored paths. The browser's displayed score is not used for the report.
- **Checkout.** One-time $1 Stripe Checkout in test mode, with the run ID in the session reference (not the answers). Secret key only as a server environment setting, provided by the owner. No key in chat or code.
- **Verification.** Report released only when the server confirms: paid, USD, $1.00, test or live matching the environment, run ID matches, and no earlier report already delivered for this payment (duplicate purchase blocked).
- **Storage.** Any server record needs a new store for paid runs. That store is a schema change and needs separate approval.

## 5. Current state of the IONOS game

- Free play, daily challenge, levels, progress saving: unchanged.
- Premium report: shown as **locked** with a plain-language description. No purchase button, no payment, no unlock from local storage.
- Storage tests 44/44 and game tests 43/43: rerun required after any change.

## 6. Missing integrations (blocking)

- Server route for run records and authoritative scoring (not built).
- Stripe test-mode key in the server environment (owner action).
- Store for paid runs and duplicate-purchase control (needs approval).
- Browser checks at phone, tablet and desktop widths (no browser tool here; UNVERIFIED).
