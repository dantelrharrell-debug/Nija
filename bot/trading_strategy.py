import asyncio
import logging
from typing import Callable, Any, Optional
from functools import wraps

logger = logging.getLogger(__name__)


class TimeoutError(Exception):
    """Raised when a function call times out."""
    pass


def call_with_timeout(
    func: Callable,
    timeout_seconds: int = 30,
    *args,
    **kwargs
) -> Any:
    """
    Call a function with a timeout.
    Increased default to 30s for production API latency
    
    Args:
        func: The function to call
        timeout_seconds: Maximum time to wait for the function to complete
        *args: Positional arguments to pass to the function
        **kwargs: Keyword arguments to pass to the function
    
    Returns:
        The result of the function call
    
    Raises:
        TimeoutError: If the function doesn't complete within the timeout
    """
    import signal
    
    def timeout_handler(signum, frame):
        raise TimeoutError(f"Function call timed out after {timeout_seconds} seconds")
    
    # Set the signal handler and alarm
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(timeout_seconds)
    
    try:
        result = func(*args, **kwargs)
        signal.alarm(0)  # Cancel the alarm
        return result
    except TimeoutError:
        logger.error(f"Timeout calling {func.__name__}")
        raise
