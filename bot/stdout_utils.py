"""
Stdout Utilities for NIJA Trading Bot
======================================

Utility functions for managing stdout/stderr redirection.

This module provides context managers for suppressing print() statements
from third-party libraries that don't use proper logging.
"""

import sys
import io
from contextlib import contextmanager


@contextmanager
def suppress_pykrakenapi_prints():
    """
    Context manager to suppress pykrakenapi's print() statements.

    The pykrakenapi library prints retry attempts to stdout instead of using
    logging. This creates log pollution that cannot be controlled via log levels.

    Example messages that are suppressed:
        attempt: 463 | ['EQuery:Unknown asset pair']
        attempt: 464 | ['EQuery:Unknown asset pair']
        ...

    Usage:
        with suppress_pykrakenapi_prints():
            result = kraken_api.query_private('Balance')

    Returns:
        Context manager that suppresses stdout during execution
    """
    original_stdout = sys.stdout
    try:
        # Redirect stdout to a null device
        sys.stdout = io.StringIO()
        yield
    finally:
        # Restore original stdout
        sys.stdout = original_stdout
