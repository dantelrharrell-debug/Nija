# BREAK_RETEST volume-gate backtest — 2026-09-20

## Scope

This backtest validates only the BREAK_RETEST entry-condition change that rejects unavailable or non-positive volume. It does not claim profitability or production readiness.

## Method

A deterministic 120-scenario fixture exercises the actual `BreakRetestDetector` with identical price geometry across positive-volume and zero-volume cases:

- 30 long, positive-volume break-and-retest setups
- 30 short, positive-volume break-and-retest setups
- 30 long, zero-volume versions of the same setup geometry
- 30 short, zero-volume versions of the same setup geometry

For emitted signals the backtest also validates stop and first-target geometry relative to the retest close.

## Expected/required result

- Positive-volume setups emitted: 60 / 60
- Positive-volume long setups preserved: 30 / 30
- Positive-volume short setups preserved: 30 / 30
- Zero-volume setups emitted: 0 / 60
- Protection geometry invalid: 0

The executable regression is `bot/tests/test_break_retest_volume_gate_backtest.py`. CI must pass this test before merge.

## Interpretation

The stricter gate is intentionally non-degrading for otherwise-identical setups with valid volume data and fail-closed for missing/zero-volume evidence. This evidence covers the entry-condition delta only; BREAK_RETEST remains disabled by default and is not promoted to LIVE or LIMITED_LIVE by this change.
