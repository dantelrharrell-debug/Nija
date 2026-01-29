"""
NIJA Kraken Nonce Generator (OPTION A - Best Practice)
========================================================

Per-user nonce generator for Kraken API.

Each Kraken user must have its own nonce source. This class provides
a simple, thread-safe implementation that guarantees monotonically
increasing nonces.

Usage:
    # Create one instance per user (not shared)
    user_nonce = KrakenNonce()

    # Get next nonce
    nonce = user_nonce.next()

Best Practice:
    Each Kraken user MUST have its own KrakenNonce instance.
    Do NOT share instances between users - this will cause nonce collisions.
"""

import time
import threading


class KrakenNonce:
    """
    Per-user nonce generator for Kraken API.

    CRITICAL: Each user MUST have its own instance (not shared between users).
    Guarantees strictly monotonic increasing nonces.

    Implementation (OPTION A - Best Practice):
    - One instance per user
    - Thread-safe (uses lock)
    - Monotonically increasing
    - Simple and reliable

    The nonce starts at current time in milliseconds and increments by 1
    with each call to next(). This ensures each nonce is unique and strictly
    increasing, which is required by Kraken's API.
    """

    def __init__(self):
        """
        Initialize nonce generator.

        Sets initial nonce to current time in milliseconds.
        Each subsequent call to next() increments by 1.
        """
        self.last = int(time.time() * 1000)
        self._lock = threading.Lock()

    def next(self):
        """
        Get next nonce.

        Thread-safe: Uses lock to prevent race conditions.
        Monotonic: Each nonce is strictly greater than the previous.

        Returns:
            int: Next nonce value (milliseconds since epoch)
        """
        with self._lock:
            self.last += 1
            return self.last

    def set_initial_value(self, value):
        """
        Set the initial nonce value.

        Thread-safe: Uses lock to prevent race conditions.
        Useful for restoring from persisted state.

        Args:
            value: Initial nonce value (will be set if greater than current)
        """
        with self._lock:
            if value > self.last:
                self.last = value

    def jump_forward(self, milliseconds):
        """
        Jump the nonce forward by specified milliseconds.

        Thread-safe: Uses lock to prevent race conditions.
        Useful for error recovery when nonce window needs to be cleared.

        Args:
            milliseconds: Number of milliseconds to jump forward

        Returns:
            int: New nonce value after jump
        """
        with self._lock:
            # Calculate two candidate nonces and use the larger one
            time_based = int(time.time() * 1000) + milliseconds
            increment_based = self.last + milliseconds
            self.last = max(time_based, increment_based)
            return self.last


__all__ = ['KrakenNonce']
