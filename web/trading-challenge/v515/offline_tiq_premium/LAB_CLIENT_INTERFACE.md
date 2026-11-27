# Practice Lab and client interface (preview only)

Written 9 Nov 2026. Preview only: nothing here is published, connected, charged or sent anywhere.

## What the Practice Lab is
`/trading-iq-challenge` has a free Practice Lab with four fictional exercise families:
multi-asset allocation, financial-news judgement, risk exercises (position size, maximum loss, stop-loss plan) and emotional discipline.
Code: `offline_tiq_premium/tiq_lab.mjs` (exercises, scoring, scorecard merge), `tiq_coach.mjs` (`buildLabCoach`), `tiq_achievements.mjs`
(`LAB_ACHIEVEMENTS`), `tiq_lab_store.mjs` (optional browser storage), UI `src/components/TiqLab.jsx`.

## Scoring rules
- Scores measure process only. No function reads simulated profit, loss or return. Stress figures are display only (tested).
- Diversification is **Not scored** unless an allocation exercise was completed with at least 20% invested.
- If a lab diversification score exists it replaces the game's single-asset estimate; risk, research and discipline average game and lab when both exist.
- The existing Trading IQ headline (game rules in `tiq_engine.mjs`) is unchanged.

## Browser-local progress (optional)
Off by default. When the player turns it on, only their exercise answers are saved under `nija_tiq_lab_v1` in `localStorage`.
The page shows the disclosure that it can be lost when browser data is cleared. No PII, payment or account data; never used to unlock anything.

## Backend client stub
`src/lib/tiqBackendClient.js` has `fetchDaily()` and `submitRun()` — the only two calls the integration spec names (section 2).
Both return `{ ok:false, reason:"not_available" }` with no network request. No endpoints exist for lab, progress, classroom, analytics or payments in the spec, so none are stubbed.
No secrets belong in the client. Connecting requires the spec's release gates (section 12) and owner approval.
