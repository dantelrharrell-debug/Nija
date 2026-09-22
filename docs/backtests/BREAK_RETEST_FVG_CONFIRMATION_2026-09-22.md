# BREAK_RETEST Fair Value Gap confirmation — 2026-09-22

## Scope

NIJA's BREAK_RETEST detector now requires directional Fair Value Gap (FVG) confirmation by default as an additional entry-quality condition. This change does not enable BREAK_RETEST globally, does not bypass execution authorization, and does not relax any stop-loss/take-profit protection requirement.

## Definition

The detector uses a three-candle imbalance definition over completed candles before the retest:

- Bullish FVG: candle[i].low > candle[i-2].high
- Bearish FVG: candle[i].high < candle[i-2].low

The newest qualifying directional FVG inside the configured lookback is used.

## Default controls

- `NIJA_BREAK_RETEST_REQUIRE_FVG=true`
- `NIJA_BREAK_RETEST_FVG_LOOKBACK=6`
- `NIJA_BREAK_RETEST_FVG_MIN_ATR=0.05`

The minimum gap is expressed as a fraction of current ATR to reject negligible imbalances. `NIJA_BREAK_RETEST_REQUIRE_FVG=false` is an explicit rollback switch for controlled testing.

## Entry behavior

A BREAK_RETEST signal requires all existing structure-break, retest, close-confirmation, and positive-volume conditions plus:

- long: a recent bullish FVG that has not been invalidated by the retest close;
- short: a recent bearish FVG that has not been invalidated by the retest close.

Emitted signal metadata records the FVG direction, bounds, size, age, and whether FVG confirmation was required.

## Safety

BREAK_RETEST remains disabled by default through its existing feature flag and remains subject to NIJA's fail-closed protected-entry routing. FVG confirmation is signal qualification only; it cannot authorize a real-money order or substitute for verified SL/TP protection.

## Regression coverage

`bot/tests/test_break_retest_fvg_gate.py` verifies:

- bullish FVG acceptance and metadata;
- bearish FVG acceptance and metadata;
- rejection when required FVG evidence is absent;
- explicit rollback behavior when the FVG gate is disabled.

Existing deterministic BREAK_RETEST volume-gate fixtures were updated to include valid directional FVG geometry so the volume and protection regressions remain meaningful under the stricter default.
