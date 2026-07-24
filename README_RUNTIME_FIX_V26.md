# NIJA Runtime Fix v26

This release addresses the live startup failure documented by repeated runtime markers such as `broker_manager_not_initialized`, zero capital, zero brokers, and `LIVE_PENDING_CONFIRMATION`.

The production launcher now installs canonical broker startup convergence before importing `main.py` or `bot.bot_main`. See `docs/CANONICAL_STARTUP_RECOVERY_V26.md` for the root cause, exact startup proof, and safety boundaries.
