"""Broker manager with safe rate-limited access to balance-related calls.

This file adds a lightweight integration with bot.rate_limiter.RateLimiter while preserving
logging and safety guards so repository behavior remains robust if the limiter misbehaves.
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Try to import the rate limiter, but don't fail if it isn't available
try:
    from .rate_limiter import make_rate_limiter
except Exception:
    make_rate_limiter = None
    logger.warning("RateLimiter not available; continuing without rate limiting")

# Module-level limiter: tuned conservatively. Callers may override on an instance if needed.
if make_rate_limiter:
    _BALANCE_RATE_LIMITER = make_rate_limiter(max_calls=10, period=1.0)
else:
    class _NoOp:
        def __init__(self, *_, **__):
            pass
        def limit(self):
            from contextlib import contextmanager
            @contextmanager
            def _c():
                yield
            return _c()
    _BALANCE_RATE_LIMITER = _NoOp()


class BrokerManager:
    """Simplified broker manager that demonstrates safe, rate-limited balance calls.

    The real repository likely has many responsibilities; this module focuses only on
    introducing the rate-limiter integration in a non-disruptive way.
    """

    def __init__(self, *args, **kwargs):
        # Preserve any expected initialization semantics
        self._internal = {}
        self._limiter = _BALANCE_RATE_LIMITER
        logger.debug("BrokerManager initialized with rate limiter=%s", type(self._limiter).__name__)

    def _fetch_balance_from_provider(self, account_id: str) -> Any:
        """Placeholder for the actual provider call. Replace/extend in the real code base.

        This method intentionally isolates the external balance call so we can wrap it with
        rate-limiting and error handling here without mutating upstream logic.
        """
        # In the real implementation this would perform network IO / provider SDK calls.
        # Keep conservative behavior: if something goes wrong, log and raise so callers can decide.
        raise NotImplementedError("_fetch_balance_from_provider should be implemented by the real broker manager")

    def get_balance(self, account_id: str) -> Any:
        """Public method to retrieve a balance with rate-limiting and safety guards.

        This method will use the module-level limiter to avoid overloading balance caches or
        provider APIs. It preserves logging and returns None on handled errors so callers can
        safely continue.
        """
        logger.debug("get_balance called for account_id=%s", account_id)
        try:
            # Use the limiter's context manager to restrict frequency
            with self._limiter.limit():
                try:
                    result = self._fetch_balance_from_provider(account_id)
                    logger.debug("Successfully fetched balance for %s", account_id)
                    return result
                except NotImplementedError:
                    # Preserve behavior: bubble up NotImplementedError so test/dev environments are explicit
                    logger.exception("Balance provider not implemented for account_id=%s", account_id)
                    raise
                except Exception as exc:
                    # Preserve safety: do not allow provider errors to crash the process
                    logger.exception("Failed to fetch balance for %s: %s", account_id, exc)
                    return None
        except Exception:
            # If the limiter itself throws, we do not want to break the caller unexpectedly.
            logger.exception("Rate limiter failed while getting balance; falling back to direct call")
            try:
                return self._fetch_balance_from_provider(account_id)
            except Exception:
                logger.exception("Fallback direct balance fetch also failed for %s", account_id)
                return None


# Backwards-compatible utility function for code that expects a module-level manager
def make_broker_manager(*args, **kwargs) -> BrokerManager:
    return BrokerManager(*args, **kwargs)
