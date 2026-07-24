## Canonical startup launcher v26

- Installs v24 convergence before `main.py` and `bot.bot_main` imports.
- Rewrites Render startup idempotently.
- Fails closed if startup ordering is already unsafe.
- Adds focused tests and CI.
- Does not bypass writer, capital, broker, activation, risk, notional, or order-admission gates.
