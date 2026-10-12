# Operator ceiling for startup verification buys

The startup verification path already has a one-shot heartbeat buy/close flow.
Its explicit live-order opt-in and existing authority, nonce, capital, risk,
position, broker and exchange checks remain required.

`NIJA_HEARTBEAT_MAX_BUY_NOTIONAL_USD`, when configured, limits the **planned
quote notional** passed into the execution pipeline for a non-reducing heartbeat
buy. It grants no permission to submit an order. An invalid, empty, nonpositive
or nonfinite configured ceiling rejects the buy locally. A base-sized buy is
also rejected because a market price hint cannot establish a quote ceiling.

The check runs after Kraken's risk/minimum sizing, so an exchange-safe minimum
cannot silently increase the planned buy above the operator ceiling. If the
minimum exceeds that ceiling, no order is submitted; the minimum is not reduced.
Ordinary strategy orders and reducing/closing orders retain their existing
checks. Leaving the new variable absent preserves the prior sizing behavior.

This is a planned-order limit, **not an all-in spending guarantee**: market
execution prices, fees and slippage remain separate. It does not replace the
broker's final sizing and risk checks or constitute execution proof.

Deployment, any live-order opt-in and the actual verification trade require
operator review. An existing instruction prohibiting test trades remains in
effect until the operator explicitly changes it. Test fixtures submit no real
orders and do not establish production readiness.
