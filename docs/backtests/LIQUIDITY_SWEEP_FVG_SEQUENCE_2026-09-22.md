# Liquidity-sweep / displacement / FVG sequence — 2026-09-22

## Scope

NIJA's existing `LiquidityReversalStrategy` has been tightened so that RSI, volume,
or a large wick cannot create a trade signal by themselves.

A BUY/SELL signal now requires the complete price-action sequence:

1. **Liquidity sweep** — price pierces a prior swing high/low and closes back
   inside the range. A body close through the level is treated as a structure
   break, not a sweep.
2. **Displacement** — within the next 1–3 candles, price must make a directional
   move away from the sweep with a minimum ATR-normalized body.
3. **Fresh Fair Value Gap** — the displacement leg must create a directional
   three-candle FVG.
4. **First retrace entry** — NIJA waits for price to retrace into the fresh FVG;
   an FVG already mitigated before the current candle is rejected.
5. **Protection geometry** — the proposed stop is beyond the sweep wick and the
   target is opposing liquidity when that offers at least the configured
   risk/reward floor; otherwise the default target is the configured minimum
   risk/reward (2R by default).

## Secondary confluence

The following factors may raise confidence but cannot substitute for the required
sequence:

- RSI reversal context
- volume expansion
- CRT-style prior-candle sweep-and-close-back
- larger macro-window liquidity sweep
- previous-day high/low sweep when a DatetimeIndex is available

## Safety

This change does **not**:

- bypass broker execution authorization,
- lower broker minimums,
- bypass risk/capital/writer/nonce/circuit-breaker gates,
- claim that candles prove institutional or "smart money" sponsorship,
- guarantee profitability,
- force a trade when no qualifying setup exists,
- change the existing real-money protected-entry capability checks.

The change is intentionally fail-closed: missing displacement, missing FVG,
prior FVG mitigation, no FVG retrace, or a body-close structural break yields no
liquidity-reversal signal.

## Regression coverage

`bot/tests/test_liquidity_reversal_sequence.py` covers:

- valid bullish sequence,
- valid bearish sequence,
- body-close break rejection,
- missing displacement rejection,
- missing FVG rejection,
- already-mitigated FVG rejection,
- no-retrace rejection,
- RSI/volume remaining secondary rather than substitutes.
