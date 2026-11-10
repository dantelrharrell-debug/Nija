# NIJA Trading IQ advanced simulator — isolated prototype
**Status:** development-only; not integrated, deployed, or certified.

This is a deterministic virtual-accounting engine for an educational trading simulator. It is **not** the canonical IONOS twelve-round Trading IQ game, the five-round billing game, or the 72-decision staging game.

Run locally with Node.js 20+:
```sh
node --test web/trading-challenge/advanced-simulator/engine.test.mjs
```

The engine exposes only the current virtual candle close, prevents access to future candles through its public handle, and does not import live trading, brokerage, Stripe, Render, or Vercel code. It implements market-style virtual buys/sells at the current close with configured spread and fee assumptions, no margin, and an exposure cap. It does **not** yet implement historical data ingestion, candlestick UI, limit/stop orders, partial fills, slippage models, drawdown limits, durable progress, accessibility, or deployment.

Release gate: add those features, verify approved NIJA visual assets from authenticated IONOS export, run independent QA and security checks, and review exact production target before deployment. Do not use this engine to score the canonical 12-round IQ game or issue paid reports.
