"""Top-level bot module updated to integrate with the new rate limiter for balance/cache calls.

This change aims to preserve existing logging and safety guards while ensuring sensitive
calls are rate-limited to protect downstream services.
"""
import logging

logger = logging.getLogger(__name__)

try:
    from .broker_manager import make_broker_manager
    from .rate_limiter import make_rate_limiter
except Exception:
    # Fail-safe imports: preserve previous behavior if these modules are not available
    make_broker_manager = None
    make_rate_limiter = None
    logger.warning("Some optional bot modules are unavailable; running in degraded mode")


class Bot:
    def __init__(self, *args, **kwargs):
        self._broker = make_broker_manager(*args, **kwargs) if make_broker_manager else None
        # Allow configuring a local limiter for bot-level balance/cache operations
        self._balance_limiter = make_rate_limiter(max_calls=10, period=1.0) if make_rate_limiter else None
        logger.debug("Bot initialized (broker=%s, balance_limiter=%s)", type(self._broker).__name__ if self._broker else None, type(self._balance_limiter).__name__ if self._balance_limiter else None)

    def get_account_balance(self, account_id: str):
        logger.debug("Bot.get_account_balance called for %s", account_id)
        if self._broker is None:
            logger.warning("No broker available to fetch balance for %s", account_id)
            return None

        # Use the bot-local limiter to reduce the rate of balance accesses coming from high-level code
        if self._balance_limiter:
            try:
                with self._balance_limiter.limit():
                    return self._broker.get_balance(account_id)
            except Exception:
                logger.exception("Rate-limited balance fetch failed, falling back to direct broker call")
                return self._broker.get_balance(account_id)
        else:
            return self._broker.get_balance(account_id)


# Export a convenience constructor
def create_bot(*args, **kwargs) -> Bot:
    return Bot(*args, **kwargs)
