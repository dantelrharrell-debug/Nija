# NIJA AI Trading Group — Current Success State

**Status date:** July 2026

NIJA has reached a new success point: mobile-app readiness work is now connected to the live-execution protection stack and dashboard sizing workflow.

This README is the current recovery anchor for NIJA.

---

## Current Success Point

NIJA now includes:

- Broker venue cash guard.
- Position close with realized P&L calculation.
- Stop-loss and take-profit auto-exit.
- Trailing stop-loss.
- Breakeven stop-loss.
- Combo breakeven-to-trailing protection.
- Trailing take-profit.
- Combined trailing take-profit plus trailing stop-loss manager.
- Combined trailing position-size calculator.
- Dashboard trade execution panel with one-click fill.
- Mobile app blueprint for iPhone and Android development.

---

## Mobile App Blueprint Added

The NIJA mobile app blueprint has been added to this success state.

The mobile app direction is:

- Education-first user experience.
- Demo / Education Mode as the default starting point.
- Live Mode locked behind user consent and broker readiness.
- No profit guarantees.
- No investment-advice claims.
- No live trading by default.
- Broker secrets handled server-side only.
- Every user account trades independently.
- Clear risk disclosures.
- Emergency pause / kill switch required.
- Apple and Google review path defined.

---

## Mobile App Screens

The app structure is planned around five bottom tabs:

1. **Home** — account status, broker status, system status, open positions, risk state, and emergency pause.
2. **Signals** — market signal cards explaining confidence, ADX, volume, spread, fee impact, broker readiness, and why trades were approved or skipped.
3. **Trades** — completed, failed, skipped, and simulated trade history, clearly separating Education Mode and Live Mode.
4. **Risk** — daily loss limit, weekly hard stop, max position size, max leverage, minimum balance checks, disclosure history, and consent history.
5. **Profile** — user account, connected brokers, disclosures, support, privacy policy, terms, and delete account.

---

## Education Mode

Education Mode is the default experience.

It should include:

- Simulated signals.
- Simulated trades.
- Signal explanations.
- Trade pass/fail reasons.
- AI confidence score.
- Trend strength.
- Volume check.
- ADX check.
- Spread check.
- Fee impact check.
- Beginner lesson cards.

Education Mode lets users understand NIJA before using live capital.

---

## Live Mode Requirements

Live Mode must stay locked until:

- User account is created.
- Risk disclosure is accepted.
- No-financial-advice disclosure is accepted.
- Broker is connected.
- Broker balance is verified.
- Execution permissions are confirmed.
- Live trading consent is signed.
- Audit log is created.
- Emergency pause is enabled.

Live Mode should never activate automatically.

Required user confirmation:

> I understand trading involves risk and I can lose money.

---

## Broker And Security Rules

Initial broker placeholders:

- Kraken.
- Coinbase.

Rules:

- Broker API keys are never stored in the mobile frontend.
- Broker secrets are handled server-side only.
- Mobile app only talks to secure backend APIs.
- Read-only balance sync should happen before execution permissions.
- Execution requires explicit user consent.
- All live actions must create audit logs.
- Users must be able to disconnect brokers and delete their account.

---

## Apple And Google Readiness

NIJA is being structured for future release on:

- Apple App Store.
- Google Play Store.

Best launch path:

1. Phase 1 — Education app.
2. Phase 2 — Broker dashboard.
3. Phase 3 — Controlled live trading after compliance review.
4. Phase 4 — App Store and Google Play public release.

Public release is not declared complete until iOS/Android builds, store assets, privacy policy, terms, support URL, demo credentials, and financial declarations are finished and verified.

---

## Protection Stack Modules

Key modules:

```text
bot/broker_venue_cash_guard_patch.py
bot/position_close_pnl_runtime_patch.py
bot/auto_exit_sl_tp_runtime_patch.py
bot/trailing_stop_loss_runtime_patch.py
bot/breakeven_stop_loss_runtime_patch.py
bot/combo_breakeven_trailing_runtime_patch.py
bot/trailing_take_profit_runtime_patch.py
bot/combined_trailing_tp_sl_runtime_patch.py
bot/combined_trailing_position_size_calculator.py
frontend/static/js/app.js
```

Combined trailing defaults:

```bash
NIJA_COMBINED_TRAILING_TP_SL_ENABLED=true
NIJA_COMBINED_TRAILING_POLL_SECONDS=5
NIJA_COMBINED_TRAILING_SL_ACTIVATION_PCT=0.003
NIJA_COMBINED_TRAILING_SL_DISTANCE_PCT=0.006
NIJA_COMBINED_TRAILING_TP_ACTIVATION_PCT=0.008
NIJA_COMBINED_TRAILING_TP_CALLBACK_PCT=0.003
NIJA_COMBINED_SIZE_RISK_PCT=0.005
```

---

## Dashboard One-Click Fill

The dashboard trade execution panel now supports:

- Calculate Size.
- One-Click Fill.
- Calculated notional.
- Calculated quantity.
- Protection stop price.
- Risk budget.
- Full sizing preview.

Browser console signal:

```text
COMBINED_TRAILING_PANEL_ONE_CLICK_FILL
```

---

## Deployment Verification Logs

After redeploy, confirm:

```text
BROKER_VENUE_CASH_GUARD_IMPORT_HOOK_INSTALLED
POSITION_CLOSE_PNL_IMPORT_HOOK_INSTALLED
AUTO_EXIT_SL_TP_IMPORT_HOOK_INSTALLED
TRAILING_STOP_BRIDGE_INSTALLED
BREAKEVEN_STOP_BRIDGE_INSTALLED
COMBO_BE_TRAILING_BRIDGE_INSTALLED
TRAILING_TP_BRIDGE_INSTALLED
COMBINED_TRAILING_BRIDGE_INSTALLED
COMBINED_TRAILING_SIZE_ENGINE_PATCHED
AUTO_EXIT_SL_TP_MONITOR_STARTED
COMBINED_TRAILING_MONITOR_STARTED
```

---

## Final Product Vision

NIJA AI Trading is being built to become a trusted mobile AI trading system that helps users understand the market, control risk, and make informed trading decisions before using live capital.

NIJA is education-first, user-controlled, broker-direct, and risk-transparent.

---

## Important Disclaimer

NIJA AI Trading is not financial advice.

Trading involves risk and may result in financial loss. Users are responsible for their own trading decisions. NIJA AI Trading does not guarantee profits, returns, income, or trading success.
