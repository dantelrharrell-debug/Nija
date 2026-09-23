# Power of 3 Confluence — 2026-09-22

## Purpose

Add an ICT-style Power of 3 context model to the existing NIJA liquidity-reversal
strategy without making the pattern a mandatory live-entry requirement.

The model is treated as:

1. **Accumulation** — a contained pre-sweep range relative to ATR with limited
   close-to-close drift.
2. **Manipulation** — the already-required liquidity sweep pierces that range
   and closes back inside it.
3. **Distribution** — the already-required directional displacement/FVG leg.

Power of 3 does **not** create a trade on its own and does not replace NIJA's
mandatory execution sequence.

## Mandatory sequence remains unchanged

A liquidity-reversal entry still requires:

- Wick sweep of prior liquidity with a close back inside.
- No full-body structural-break substitution.
- Directional displacement within 1–3 candles.
- Fresh three-candle FVG.
- First retracement into the FVG.
- Stop beyond the sweep wick.
- Target geometry meeting the configured minimum risk/reward.
- Existing execution, risk, capital, broker, writer-authority, and protection
  gates.

## Confluence behavior

When all three Power of 3 phases are present, the strategy adds a configurable
confidence bonus (default 0.05). The final confidence remains capped.

Default controls:

- `po3_enabled = true`
- `po3_accumulation_lookback = 6`
- `po3_accumulation_max_atr = 2.5`
- `po3_max_close_drift_fraction = 0.60`
- `po3_confidence_bonus = 0.05`

The detector records phase evidence in signal metadata, including the
accumulation range, normalized range width, close drift, and the three phase
booleans.

## Safety and interpretation

The implementation does not claim to observe institutional intent, hidden order
flow, or an exchange algorithm. It classifies observable OHLC structure only.

Power of 3 is deliberately optional. If its accumulation criteria are absent, a
valid sweep → displacement → fresh-FVG → first-retrace setup can still trade.

## Regression coverage

Tests verify that:

- Bullish and bearish qualifying sequences can receive Power of 3 confirmation.
- Power of 3 increases context confidence but is not required for a valid entry.
- Power of 3 cannot substitute for a missing displacement/core sequence.
- The Power of 3 layer can be disabled without disabling the strategy.
- Existing fail-closed sweep/FVG/retrace tests remain in place.

No profitability claim is made by this change. Performance impact must be
evaluated from backtests and live telemetry after deployment.
