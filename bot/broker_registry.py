"""
NIJA Global Broker State Registry
==================================

A thread-safe, nested-dictionary registry for tracking per-broker runtime state.

Usage
-----
    from bot.broker_registry import broker_registry

    # Mark a broker as the platform (Nija-owned) account
    broker_registry["kraken"]["platform"] = True

    # Check if kraken is configured as a platform broker
    is_platform = broker_registry["kraken"].get("platform", False)

    # Store any arbitrary broker-level state
    broker_registry["coinbase"]["connected"] = True
    broker_registry["kraken"]["last_error"] = "nonce invalid"

Design
------
- ``broker_registry`` is a module-level singleton (imported by reference).
- Each broker key maps to a :class:`BrokerStateDict` — a ``dict`` subclass that
  records a last-modified timestamp and fires an optional callback whenever a
  value is set.  Regular dict operations (get/set/delete/contains/iterate) work
  transparently so callers never need to know about the wrapper.
- A :class:`BrokerRegistry` wrapper provides ``__missing__`` so that accessing
  an unknown broker key auto-creates an empty :class:`BrokerStateDict` instead
  of raising ``KeyError``.
- All mutations are protected by a ``threading.Lock`` for safe concurrent use.
"""

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterator, Optional

logger = logging.getLogger("nija.broker_registry")


class BrokerStateDict(dict):
    """
    A ``dict`` subclass that adds last-modified tracking to a single broker's
    state entries.

    Behaves exactly like a plain dict for all read operations.  Write and
    delete operations also update ``last_modified`` and log the change.

    Args:
        broker_name: Human-readable broker identifier used in log messages.
        on_change: Optional callback invoked as ``on_change(broker_name, key,
            value)`` whenever a key is set.
    """

    def __init__(
        self,
        broker_name: str,
        on_change: Optional[Callable[[str, str, Any], None]] = None,
    ) -> None:
        super().__init__()
        self._broker_name = broker_name
        self._on_change = on_change
        self.last_modified: Optional[datetime] = None

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def __setitem__(self, key: str, value: Any) -> None:
        super().__setitem__(key, value)
        self.last_modified = datetime.now(tz=timezone.utc)
        logger.debug(
            "broker_registry[%r][%r] = %r", self._broker_name, key, value
        )
        if self._on_change is not None:
            try:
                self._on_change(self._broker_name, key, value)
            except Exception:
                logger.exception(
                    "broker_registry on_change callback raised for [%r][%r]",
                    self._broker_name,
                    key,
                )

    def __delitem__(self, key: str) -> None:
        super().__delitem__(key)
        self.last_modified = datetime.now(tz=timezone.utc)
        logger.debug(
            "broker_registry[%r][%r] deleted", self._broker_name, key
        )

    def update(self, other=(), **kwargs) -> None:  # type: ignore[override]
        """Delegate to ``__setitem__`` so that timestamps and callbacks fire."""
        if hasattr(other, "items"):
            for k, v in other.items():
                self[k] = v
        else:
            for k, v in other:
                self[k] = v
        for k, v in kwargs.items():
            self[k] = v


class BrokerRegistry(dict):
    """
    Thread-safe nested registry keyed by broker name.

    Accessing an unknown broker key via ``broker_registry["kraken"]``
    auto-creates an empty :class:`BrokerStateDict` for that broker rather than
    raising a ``KeyError``.

    Example::

        broker_registry["kraken"]["platform"] = True
        broker_registry["coinbase"]["connected"] = False

    Args:
        on_change: Optional callback fired on every state change:
            ``on_change(broker_name, key, value)``.
    """

    def __init__(
        self, on_change: Optional[Callable[[str, str, Any], None]] = None
    ) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._on_change = on_change

    # ------------------------------------------------------------------
    # Auto-create inner dict on first access
    # ------------------------------------------------------------------

    def __missing__(self, broker_name: str) -> "BrokerStateDict":
        """Auto-create a :class:`BrokerStateDict` for unknown broker names."""
        with self._lock:
            # Double-checked locking: another thread may have already inserted
            # this key while we were waiting for the lock.
            if broker_name not in self:
                state = BrokerStateDict(broker_name, on_change=self._on_change)
                super().__setitem__(broker_name, state)
            return super().__getitem__(broker_name)

    # ------------------------------------------------------------------
    # Thread-safe write helpers
    # ------------------------------------------------------------------

    def set_state(self, broker_name: str, key: str, value: Any) -> None:
        """
        Explicitly set a state key for a broker (thread-safe helper).

        Equivalent to ``broker_registry[broker_name][key] = value`` but wraps
        the outer-dict lookup in the registry lock.

        Args:
            broker_name: Broker identifier, e.g. ``"kraken"``.
            key: State key, e.g. ``"platform"``.
            value: Value to store.
        """
        # Delegate to __getitem__ / __missing__ which handles locking internally
        self[broker_name][key] = value

    def get_state(self, broker_name: str, key: str, default: Any = None) -> Any:
        """
        Retrieve a state value for a broker.

        Args:
            broker_name: Broker identifier.
            key: State key.
            default: Value to return when the key is absent.

        Returns:
            Stored value or *default*.
        """
        broker_state = super().get(broker_name)
        if broker_state is None:
            return default
        return broker_state.get(key, default)

    def get_all_states(self) -> Dict[str, Dict[str, Any]]:
        """
        Return a shallow snapshot of the entire registry.

        Returns:
            ``{broker_name: {key: value, ...}, ...}`` plain-dict copy.
        """
        with self._lock:
            return {name: dict(state) for name, state in self.items()}

    def reset(self, broker_name: Optional[str] = None) -> None:
        """
        Clear state for one broker or all brokers.

        Args:
            broker_name: If provided, clears only that broker's state dict.
                If ``None``, clears the entire registry.
        """
        with self._lock:
            if broker_name is None:
                self.clear()
                logger.info("broker_registry: all broker states cleared")
            else:
                broker_state = super().get(broker_name)
                if broker_state is not None:
                    broker_state.clear()
                    logger.info("broker_registry[%r]: state cleared", broker_name)

    def is_platform(self, broker_name: str) -> bool:
        """
        Convenience check: is this broker configured as a platform account?

        Returns ``True`` if ``broker_registry[broker_name]["platform"]`` is
        truthy, ``False`` otherwise.

        Args:
            broker_name: Broker identifier, e.g. ``"kraken"``.
        """
        return bool(self.get_state(broker_name, "platform", False))

    def summary(self) -> str:
        """
        Return a human-readable one-line summary of all broker states.

        Useful for logging at startup or on status requests.
        """
        parts = []
        for name, state in sorted(self.items()):
            kv_pairs = ", ".join(f"{k}={v!r}" for k, v in sorted(state.items()))
            parts.append(f"{name}: {{{kv_pairs}}}")
        return "BrokerRegistry{" + "; ".join(parts) + "}"


# ---------------------------------------------------------------------------
# Module-level singleton — import and use directly
# ---------------------------------------------------------------------------

#: Global broker state registry.
#:
#: Access or mutate broker state anywhere in the codebase::
#:
#:     from bot.broker_registry import broker_registry
#:     broker_registry["kraken"]["platform"] = True
broker_registry: BrokerRegistry = BrokerRegistry()
