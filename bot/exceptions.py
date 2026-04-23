"""
NIJA Trading Bot - Custom Exceptions

Custom exception classes for error handling and safety checks.
"""


class CapitalIntegrityError(RuntimeError):
    """Raised when a capital safety invariant is violated.

    Specifically raised by:

    * ``CapitalCSMv2.wait_for_hydration()`` — no snapshot arrived in time.
    * ``CapitalCSMv2.wait_for_ready()`` — READY state not reached in time.

    These are **blocking errors**: the caller must not proceed with trading.
    The canonical definition lives in :mod:`bot.capital_csm_v2`; this alias
    allows consumers that import from :mod:`bot.exceptions` to use the same
    exception class.
    """


class ExecutionError(Exception):
    """
    Critical execution error that should halt trade execution.

    This exception is raised when safety checks fail to prevent:
    - Broker mismatches (cycle_broker != execution_broker)
    - Recording rejected orders as successful trades
    - Recording positions without valid txid
    - Invalid fill prices (zero or negative)
    - Other critical execution failures
    """
    pass


class BrokerMismatchError(ExecutionError):
    """Raised when cycle broker doesn't match execution broker"""
    pass


class InvalidTxidError(ExecutionError):
    """Raised when order lacks valid transaction ID (txid)"""
    pass


class InvalidFillPriceError(ExecutionError):
    """Raised when fill price is zero or negative"""
    pass


class OrderRejectedError(ExecutionError):
    """Raised when attempting to record a rejected order"""
    pass


class ExecutionFailed(ExecutionError):
    """
    Raised when Kraken does not confirm order execution.

    This exception is raised when Kraken fails to return:
    - txid (transaction ID)
    - descr.order (order description)
    - cost > 0 (order cost)

    Prevents ledger writes and position increments for unconfirmed orders.
    """
    pass


class CapitalIntegrityError(RuntimeError):
    """
    Raised when the capital hydration barrier times out or capital pipeline
    integrity cannot be confirmed before the trading loop starts.

    This exception is a hard stop: the trading loop must not proceed until
    CapitalAuthority has received at least one broker balance snapshot.

    Root causes that trigger this exception:
    - Broker connection failed before the hydration timeout (default 30 s)
    - CapitalAuthority was never refreshed (coordinator not running)
    - Bootstrap sequence did not complete in time

    Callers that catch this exception should log it as CRITICAL and either
    retry with back-off or abort the trading loop entirely.
class CapitalIntegrityError(Exception):
    """
    Raised when the capital source is invalid or unreliable.

    This exception prevents fallback-to-STARTER behavior when capital
    cannot be fetched or verified.  Trading MUST NOT proceed when this
    exception is raised — the capital pipeline has failed and no tier or
    position-sizing logic may produce a meaningful result.

    Typical causes:
    - CapitalAuthority has not been hydrated (no balance fetched yet)
    - All broker balance fetches returned None / failed
    - Capital system gate not yet released (startup incomplete)
    """
    pass
