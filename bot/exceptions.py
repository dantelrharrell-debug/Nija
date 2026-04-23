"""
NIJA Trading Bot - Custom Exceptions

Custom exception classes for error handling and safety checks.
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
