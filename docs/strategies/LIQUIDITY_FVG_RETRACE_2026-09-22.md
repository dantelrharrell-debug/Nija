# Daily FVG -> 1H Liquidity Retrace strategy — 2026-09-22

## Purpose

This strategy implements the two-timeframe sequence requested for NIJA without weakening any existing execution or protection controls.

Strategy identifier: `LIQUIDITY_FVG_RETRACE`

Feature flag: `FEATURE_LIQUIDITY_FVG_RETRACE_ENABLED`

Default: **OFF**. The strategy can be exercised in backtest, shadow, or paper modes before any live rollout.

## Long sequence

A long candidate is emitted only when all of the following are present:

1. Completed Daily candles contain a bullish Fair Value Gap.
2. The middle candle of that Daily three-candle structure closes above recent Daily structure.
3. No later completed Daily candle has touched the FVG.
4. The 1H setup occurs inside that Daily FVG.
5. Price sweeps Sell-Side Liquidity below the prior 1H swing/liquidity range and closes back above it.
6. The next 1H candle is bullish displacement with a large body relative to ATR and its own range.
7. The displacement sequence leaves a new bullish 1H FVG.
8. The next 1H candle retraces to and rejects the proximal/opening edge of that FVG.
9. Entry is a LIMIT price at that FVG edge.
10. Stop is placed below the liquidity-sweep low with a small ATR buffer.
11. Target is the previous completed Daily high.

The short path is the exact inverse: bearish Daily FVG, Buy-Side Liquidity sweep, bearish displacement, bearish 1H FVG retracement, stop above the sweep high, and target at the previous Daily low.

## Execution preservation

The detector records these fields in the canonical signal metadata:

- `order_type=limit`
- `limit_price`
- `price_hint_usd`
- `time_in_force=gtc`
- Daily FVG bounds
- 1H FVG bounds
- liquidity side and swept level
- sweep extreme
- stop basis
- target basis

The control pipeline calculates SL/TP percentages from the planned limit-entry price rather than from an unrelated current-market close.

ECEL then tick-aligns the limit price before dispatch.

## Live fail-closed rule

`LIQUIDITY_FVG_RETRACE` is a protected-entry strategy. Both stop-loss and take-profit distances are mandatory.

NIJA's currently verified atomic protected-entry broker contract is for MARKET entries. It does **not** prove an atomic protected LIMIT primitive. Therefore a live protected LIMIT request from this strategy fails closed instead of being silently converted to a market order.

That preserves the strategy specification and NIJA's existing capital-protection policy. Live activation should occur only after a broker adapter explicitly proves protected-limit capability.

## Configuration

- `NIJA_LFR_LIQUIDITY_LOOKBACK=12`
- `NIJA_LFR_DAILY_FVG_LOOKBACK=12`
- `NIJA_LFR_DAILY_STRUCTURE_LOOKBACK=3`
- `NIJA_LFR_DISPLACEMENT_BODY_ATR=0.80`
- `NIJA_LFR_DISPLACEMENT_BODY_RATIO=0.60`
- `NIJA_LFR_SWEEP_BUFFER_ATR=0.05`
- `NIJA_LFR_1H_FVG_MIN_ATR=0.05`
- `NIJA_LFR_RETRACE_TOLERANCE_ATR=0.10`
- `NIJA_LFR_STOP_BUFFER_ATR=0.10`

## Regression coverage

`bot/tests/test_liquidity_fvg_retrace_strategy.py` validates:

- complete bullish sequence;
- complete bearish sequence;
- exact FVG-edge limit entry;
- stop beyond the liquidity raid;
- target at previous Daily high/low;
- fail-closed behavior without the liquidity sweep;
- fail-closed behavior when the Daily FVG has already been mitigated;
- timestamped multi-timeframe data requirement.

`bot/tests/test_liquidity_fvg_retrace_execution_contract.py` validates:

- mandatory SL/TP;
- mandatory positive limit price;
- protected-entry classification;
- no silent limit-to-market downgrade;
- limit price and time-in-force preservation through the canonical submitter.

This strategy definition is a rules-based trading model, not a claim that institutional markets always follow this sequence or that the model is profitable.
