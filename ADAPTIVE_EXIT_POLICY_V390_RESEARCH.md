# NIJA Adaptive Exit Policy v390 — Research Basis

Date: 2026-09-06

## Objective

Replace overly tight universal fallback exits with a research-informed adaptive policy while preserving explicit existing live protections and all NIJA safety gates.

## Evidence used

- Fidelity ATR guidance: ATR measures volatility, is commonly calculated over 14 periods, and ATR multiples such as 1.5x adapt stops to changing volatility better than fixed percentage/dollar stops.
- FINRA stop-order guidance: stop prices are trigger prices, not guaranteed execution prices; short-lived volatility can trigger stops and produce materially different fills.
- 2026 JRFM study on volatility-adaptive algorithmic exits: ATR-based TP/SL effectiveness is conditional on model structure and market regime, supporting adaptive rather than universal fixed percentages.
- 2023 Journal of Behavioral and Experimental Finance study across 147 cryptocurrencies: stop-loss momentum strategies improved downside-risk management and risk-adjusted outcomes versus benchmark momentum strategies in the tested sample.
- Kraken, Coinbase, OKX, and Alpaca current order documentation: native TP/SL/trailing capabilities vary by venue and asset class, so NIJA must keep a universal software protection layer while preferring native protection where supported.

## Applied baseline

- ATR period: 14.
- Strategy stop baseline: 1.25 ATR ranging/choppy, 1.50 ATR default/trending, 1.75 ATR volatile; existing NIJA 3% hard cap remains.
- Runtime missing/adopted stop fallback: never wider than the pre-v390 hard fallback; explicit stops are never moved by v390.
- Missing TP ladder: max(NIJA minimum floor, 2R / 3R / 4R). Minimums remain 1.5% / 2.5% / 4.0%.
- Trailing stop: distance 1.25 ATR; activation is at least the original risk distance and at least the trail distance.
- Trailing take-profit/profit lock: activation approximately 1.5R and at least 2 ATR; callback 1.0 ATR.
- Strategy trailing tightens progressively at larger gains: 1.5 ATR, 1.2 ATR, 1.0 ATR, 0.8 ATR at increasing profit levels.

## Migration safety

- Existing explicit stop-loss and take-profit prices are preserved.
- Missing stop fallback may tighten but is never widened.
- No native order, fill, balance, position, or connectivity proof is fabricated.
- Writer, nonce, capital, risk, kill-switch, broker-health, minimum-order, and fill-confirmation gates remain unchanged.
- Profit is not guaranteed.

## Validation

Automated tests cover ATR parsing, R-multiple geometry, minimum TP floors, migration no-widen behavior, canonical bootstrap ordering, and scenario backtests comparing the old 0.35% callback against adaptive ATR trailing under normal noise and trend-reversal paths.
