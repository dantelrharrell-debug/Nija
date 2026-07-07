# NIJA AI Trading Group — Current Success State

**Status date:** July 2026  
**Current repository success point:** mobile-app readiness work + live-execution protection stack + trade execution panel sizing integration.

> **Important:** NIJA is closer to Apple App Store and Google Play readiness, but public store submission is not declared complete until iOS/Android builds, reviewer demo flow, privacy/legal pages, and store compliance declarations are finished and verified.

---

## Current Success Point

NIJA has advanced from core trading-runtime hardening into app-readiness work.

The current successful milestone includes:

- Broker venue cash guard to prevent aggregate capital from authorizing trades that the selected broker venue cannot fund.
- Position closing with automatic realized P&L calculation.
- Runtime stop-loss and take-profit auto-exit monitor.
- Runtime trailing stop-loss.
- Runtime breakeven stop-loss.
- Combo breakeven-to-trailing stop mode.
- Trailing take-profit.
- Combined trailing take-profit + trailing stop-loss protection manager.
- Position-size calculator for combined trailing protection.
- Dashboard trade execution panel with combined trailing calculator and one-click fill.
- Education/live-mode positioning and risk-control language maintained for app-store compliance direction.

This README is now the recovery anchor for the current successful NIJA state.

---

## App Store / Google Play Readiness Status

### Current honest status

NIJA is **closer to mobile release**, but it is **not yet declared public App Store / Google Play complete**.

Recommended release path:

1. Build iOS TestFlight version.
2. Build Android internal testing version.
3. Verify app on real iPhone and Android devices.
4. Confirm login, dashboard, education mode, broker connection, risk consent, and one-click fill.
5. Prepare privacy policy, terms of service, support URL, screenshots, icons, and review demo credentials.
6. Complete Apple and Google financial-services declarations.
7. Submit to TestFlight / internal testing first.
8. Submit public review only after testing is clean.

### Safe product positioning

NIJA should be positioned as:

- Education-first trading automation dashboard.
- User-controlled trading software.
- Broker-direct execution.
- No custody of user funds.
- No exchange operation by NIJA.
- No investment advice.
- No profit guarantees.
- Live trading only after explicit user consent.

### Not allowed language

Do not claim:

- Guaranteed profit.
- Guaranteed passive income.
- Guaranteed win rate.
- Risk-free trading.
- Investment advice.
- Exchange or custodial services unless NIJA is properly licensed for that role.

---

## Current Protection Stack

### 1. Broker venue cash guard

Prevents NIJA from using total platform capital to approve a trade when the selected execution venue cannot fund it.

Key runtime logs:

```text
BROKER_VENUE_CASH_GUARD_IMPORT_HOOK_INSTALLED
BROKER_VENUE_CASH_ENGINE_GUARD_PATCHED
BROKER_VENUE_CASH_PIPELINE_GUARD_PATCHED
BROKER_VENUE_CASH_GUARD_BLOCKED
BROKER_VENUE_CASH_GUARD_CLAMPED
BROKER_VENUE_CASH_GUARD_SKIPPED
```

Default environment controls:

```bash
NIJA_BROKER_VENUE_CASH_GUARD=true
NIJA_BROKER_VENUE_CASH_GUARD_CLAMP=true
NIJA_BROKER_VENUE_CASH_FEE_BUFFER_PCT=0.02
```

---

### 2. Position close + realized P&L

Adds a runtime close helper that calculates realized P&L after confirmed exits.

Key module:

```text
bot/position_close_pnl_runtime_patch.py
```

Key runtime logs:

```text
POSITION_CLOSE_PNL_IMPORT_HOOK_INSTALLED
POSITION_CLOSE_PNL_LEDGER_PATCHED
POSITION_CLOSE_PNL_ENGINE_PATCHED
POSITION_CLOSED_PNL
```

---

### 3. Stop-loss and take-profit auto-exit

Polls open positions, checks stored `stop_loss` and `take_profit_1/2/3`, submits a close order when levels are hit, then records P&L.

Key module:

```text
bot/auto_exit_sl_tp_runtime_patch.py
```

Key runtime logs:

```text
AUTO_EXIT_SL_TP_IMPORT_HOOK_INSTALLED
AUTO_EXIT_SL_TP_ENGINE_PATCHED
AUTO_EXIT_SL_TP_MONITOR_STARTED
AUTO_EXIT_TRIGGERED
AUTO_EXIT_CLOSED
POSITION_CLOSED_PNL
```

---

### 4. Trailing stop-loss

Tracks favorable price movement and moves stop-loss behind the best price seen.

Key module:

```text
bot/trailing_stop_loss_runtime_patch.py
```

Default environment controls:

```bash
NIJA_TRAILING_STOP_ENABLED=true
NIJA_TRAILING_STOP_POLL_SECONDS=5
NIJA_TRAILING_STOP_PCT=0.006
NIJA_TRAILING_STOP_ACTIVATION_PCT=0.003
```

Meaning:

- Activates after price moves 0.30% in NIJA's favor.
- Trails 0.60% behind the best favorable price.

Key runtime logs:

```text
TRAILING_STOP_IMPORT_HOOK_INSTALLED
TRAILING_STOP_ENGINE_PATCHED
TRAILING_STOP_BRIDGE_INSTALLED
TRAILING_STOP_MONITOR_STARTED
TRAILING_STOP_MOVED
TRAILING_STOP_TRIGGERED
TRAILING_STOP_CLOSED
```

---

### 5. Breakeven stop-loss

Moves stop-loss to entry price after the trade reaches a configured profit threshold.

Key module:

```text
bot/breakeven_stop_loss_runtime_patch.py
```

Default environment controls:

```bash
NIJA_BREAKEVEN_STOP_ENABLED=true
NIJA_BREAKEVEN_STOP_POLL_SECONDS=5
NIJA_BREAKEVEN_PROFIT_THRESHOLD_PCT=0.004
NIJA_BREAKEVEN_STOP_OFFSET_PCT=0.0002
```

Meaning:

- At +0.40% profit, stop-loss moves to breakeven.
- Offset defaults to +0.02% for long positions and -0.02% for short positions.

Key runtime logs:

```text
BREAKEVEN_STOP_IMPORT_HOOK_INSTALLED
BREAKEVEN_STOP_ENGINE_PATCHED
BREAKEVEN_STOP_BRIDGE_INSTALLED
BREAKEVEN_STOP_MONITOR_STARTED
BREAKEVEN_STOP_MOVED
```

---

### 6. Combo breakeven-to-trailing stop

Starts with breakeven protection, then switches to trailing stop protection after a stronger profit threshold.

Key module:

```text
bot/combo_breakeven_trailing_runtime_patch.py
```

Default environment controls:

```bash
NIJA_COMBO_BE_TRAILING_ENABLED=true
NIJA_COMBO_BE_TRAILING_POLL_SECONDS=5
NIJA_COMBO_BREAKEVEN_THRESHOLD_PCT=0.004
NIJA_COMBO_BREAKEVEN_OFFSET_PCT=0.0002
NIJA_COMBO_TRAILING_SWITCH_PCT=0.007
NIJA_COMBO_TRAILING_STOP_PCT=0.005
```

Meaning:

- At +0.40% profit, move stop-loss to breakeven.
- At +0.70% profit, switch to trailing stop.
- Trail 0.50% behind the best favorable price.

Key runtime logs:

```text
COMBO_BE_TRAILING_IMPORT_HOOK_INSTALLED
COMBO_BE_TRAILING_ENGINE_PATCHED
COMBO_BE_TRAILING_BRIDGE_INSTALLED
COMBO_BE_TRAILING_MONITOR_STARTED
COMBO_BE_TRAILING_MODE_SWITCH
COMBO_BE_TRAILING_STOP_MOVED
```

---

### 7. Trailing take-profit

Arms after a favorable move, tracks the best price, and closes when price pulls back by a callback amount.

Key module:

```text
bot/trailing_take_profit_runtime_patch.py
```

Default environment controls:

```bash
NIJA_TRAILING_TP_ENABLED=true
NIJA_TRAILING_TP_POLL_SECONDS=5
NIJA_TRAILING_TP_ACTIVATION_PCT=0.008
NIJA_TRAILING_TP_CALLBACK_PCT=0.003
```

Meaning:

- At +0.80% profit, trailing take-profit arms.
- If price pulls back 0.30% from the best favorable price, NIJA closes the position.

Key runtime logs:

```text
TRAILING_TP_IMPORT_HOOK_INSTALLED
TRAILING_TP_ENGINE_PATCHED
TRAILING_TP_BRIDGE_INSTALLED
TRAILING_TP_MONITOR_STARTED
TRAILING_TP_ARMED
TRAILING_TP_TRACK
TRAILING_TP_TRIGGERED
TRAILING_TP_CLOSED
```

---

### 8. Combined trailing take-profit + trailing stop-loss

Runs one unified manager for both protections so trailing take-profit and trailing stop-loss do not fight each other.

Key module:

```text
bot/combined_trailing_tp_sl_runtime_patch.py
```

Default environment controls:

```bash
NIJA_COMBINED_TRAILING_TP_SL_ENABLED=true
NIJA_COMBINED_TRAILING_POLL_SECONDS=5
NIJA_COMBINED_TRAILING_SL_ACTIVATION_PCT=0.003
NIJA_COMBINED_TRAILING_SL_DISTANCE_PCT=0.006
NIJA_COMBINED_TRAILING_TP_ACTIVATION_PCT=0.008
NIJA_COMBINED_TRAILING_TP_CALLBACK_PCT=0.003
```

Meaning:

- At +0.30% profit, combined trailing stop-loss arms.
- Stop trails 0.60% behind best favorable price.
- At +0.80% profit, combined trailing take-profit arms.
- If price pulls back 0.30% from best favorable price, NIJA closes and records realized P&L.

Key runtime logs:

```text
COMBINED_TRAILING_IMPORT_HOOK_INSTALLED
COMBINED_TRAILING_ENGINE_PATCHED
COMBINED_TRAILING_BRIDGE_INSTALLED
COMBINED_TRAILING_MONITOR_STARTED
COMBINED_TRAILING_SL_ARMED
COMBINED_TRAILING_SL_MOVED
COMBINED_TRAILING_TP_ARMED
COMBINED_TRAILING_TP_TRACK
COMBINED_TRAILING_TP_TRIGGERED
COMBINED_TRAILING_CLOSED
POSITION_CLOSED_PNL
```

---

## Combined Trailing Position Size Calculator

NIJA now includes a position-size calculator designed for the combined trailing protection system.

Key module:

```text
bot/combined_trailing_position_size_calculator.py
```

Exposed engine method:

```python
calculate_combined_trailing_position_size(...)
```

Formula:

```text
risk_budget = account_equity × risk_pct
raw_notional = risk_budget ÷ stop_distance_pct
quantity = final_notional ÷ entry_price
```

Default environment controls:

```bash
NIJA_COMBINED_SIZE_RISK_PCT=0.005
NIJA_COMBINED_SIZE_MIN_NOTIONAL_USD=${MIN_TRADE_USD:-10}
NIJA_COMBINED_SIZE_MAX_NOTIONAL_USD=available_cash_fallback
NIJA_COMBINED_TRAILING_SL_DISTANCE_PCT=0.006
```

Meaning:

- Risk 0.50% of account equity per trade by default.
- Size is based on the combined trailing stop-loss distance.
- Size is clamped by available cash and max notional.
- Minimum notional is applied only when safe and allowed.
- Trade is rejected when the final notional cannot satisfy minimum requirements.

Key runtime logs:

```text
COMBINED_TRAILING_SIZE_CALCULATOR_READY
COMBINED_TRAILING_SIZE_ENGINE_PATCHED
COMBINED_TRAILING_SIZE_CALCULATED
COMBINED_TRAILING_SIZE_ENGINE_RESULT
```

---

## Dashboard Trade Execution Panel

The dashboard now includes a trade execution panel with combined trailing sizing and one-click fill.

Updated file:

```text
frontend/static/js/app.js
```

Panel features:

- Symbol input.
- Side selector.
- Entry price input.
- Equity input.
- Available cash input.
- Risk percentage input.
- Trailing stop distance input.
- Minimum notional input.
- Maximum notional input.
- Calculate Size button.
- One-Click Fill button.
- Calculated notional output.
- Calculated quantity output.
- Protection stop price output.
- Risk budget output.
- Full sizing result preview.

One-click fill populates these fields:

```text
trade-notional-usd
trade-quantity
trade-stop-price
trade-risk-budget
```

It also attempts to populate common execution form IDs if another panel exists:

```text
order-symbol
order-side
order-notional-usd
order-quantity
order-stop-loss
position-size-usd
position-quantity
```

Browser console signal:

```text
COMBINED_TRAILING_PANEL_ONE_CLICK_FILL
```

---

## Current Mobile Build Readiness

NIJA has app-readiness structure in place:

- Frontend dashboard exists.
- Auth flow exists.
- Dashboard stats/status controls exist.
- Broker management UI exists.
- Education-mode and risk-disclosure copy exist.
- Trade execution panel now includes risk-based one-click sizing.
- Backend FastAPI interface exists.

Still required before public submission:

- Verified iOS build.
- Verified Android AAB build.
- TestFlight upload.
- Google Play internal testing upload.
- App icon and screenshots.
- Privacy policy URL.
- Terms of service URL.
- Support URL and support email.
- Reviewer demo credentials.
- Financial features declarations.
- Confirmation backend is live during review.
- Device testing on real iPhone and Android.

---

## Compliance-Safe User Messaging

Use this language in app copy and store listings:

```text
NIJA is an education-first trading automation dashboard. Users connect their own broker accounts and remain in control of trading permissions and risk settings. NIJA does not custody user funds, does not operate as an exchange, does not provide investment advice, and does not guarantee profit or performance. Trading involves substantial risk of loss.
```

---

## Deployment Checklist

After redeploy, confirm these logs appear:

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

Then verify dashboard behavior:

1. Log in.
2. Open dashboard.
3. Confirm Trade Execution Panel appears.
4. Enter symbol, side, entry price, equity, cash, risk %, and stop distance.
5. Click **Calculate Size**.
6. Confirm notional, quantity, stop price, and risk budget populate.
7. Click **One-Click Fill**.
8. Confirm execution fields are populated.
9. Do not enable live trading until risk acknowledgement and broker setup are correct.

---

## Safety Notes

- These protections are runtime monitors, not native exchange OCO/stop/trailing orders unless broker-native order support is added later.
- Runtime protection depends on the NIJA process staying alive and broker APIs being reachable.
- Do not claim guaranteed profits.
- Do not claim App Store or Google Play approval until those reviews are actually complete.
- Do not claim tests or deployment passed unless the relevant CI/deploy/build logs confirm it.

---

## Next Required Work

Highest-priority next steps:

1. Run backend and frontend smoke tests.
2. Verify the dashboard panel in browser/mobile web.
3. Connect one-click fill to the final live order-confirmation flow if a separate execution submit endpoint is added.
4. Build iOS TestFlight artifact.
5. Build Android AAB artifact.
6. Prepare privacy policy, terms, support URL, demo account, screenshots, and app-review notes.
7. Submit to internal testing before public app-store review.

---

## Current Success Summary

NIJA now has:

- Live capital safety guard.
- Venue-level cash guard.
- Stop-loss automation.
- Take-profit automation.
- Trailing stop-loss.
- Breakeven stop.
- Combo breakeven-to-trailing stop.
- Trailing take-profit.
- Combined trailing take-profit + stop-loss manager.
- Position-size calculator tied to trailing risk distance.
- Dashboard one-click fill for calculated trade sizing.
- App-readiness direction for Apple and Google testing.

This is the current operating success point.
