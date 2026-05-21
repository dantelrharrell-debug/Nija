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


class BrokerAuthError(ExecutionError):
    """Raised when the broker rejects the request due to authentication failure.

    Covers:
    - 401 / 403 HTTP responses
    - Invalid API key / expired key
    - ECDSA / HMAC signature mismatch
    - IP-address whitelist violations

    Unlike transient errors, auth failures should trigger a cooldown and
    operator alert rather than an immediate retry.
    """
    pass


class ACKTimeoutError(ExecutionError):
    """Raised when the exchange does not acknowledge an order within the
    configured timeout window.

    The order may or may not have been accepted by the exchange; the caller
    must reconcile open-order state before issuing a replacement.
    """
    pass


class PostOnlyRejectError(ExecutionError):
    """Raised when a post-only limit order is rejected because it would
    immediately cross the order book and become a taker fill.

    This is a *normal* exchange response, not a bug.  The appropriate
    response is to cancel the order and retry at an adjusted price, or
    switch to a market order if conditions permit.
    """
    pass


class SlippageGuardError(ExecutionError):
    """Raised when the pre-trade slippage estimate exceeds the configured
    maximum-cost threshold.

    This is a soft block: the order was never submitted to the exchange.
    The caller may retry on the next cycle when market conditions improve.
    """
    pass


class RiskGovernorBlockedError(ExecutionError):
    """Raised when the GlobalRiskGovernor returns a RED gate decision that
    prevents new position entries.

    Examples: daily-loss limit, consecutive-loss cascade breaker, exposure
    concentration cap, volatility spike suspension.
    """
    pass


class ReconciliationGateError(ExecutionError):
    """Raised when a reconciliation failure prevents the execution pipeline
    from dispatching new orders.

    The bot must re-run reconciliation and confirm clean state before
    trading is permitted to resume.
    """
    pass



