"""
NIJA Global Broker State Registry
==================================

A thread-safe, nested-dictionary registry for tracking per-broker runtime state.

Usage
-----
    from bot.broker_registry import broker_registry, BrokerCriticality

    # Mark a broker as the platform (Nija-owned) account
    broker_registry["kraken"]["platform"] = True

    # Check if kraken is configured as a platform broker
    is_platform = broker_registry["kraken"].get("platform", False)

    # Store any arbitrary broker-level state
    broker_registry["coinbase"]["connected"] = True
    broker_registry["kraken"]["last_error"] = "nonce invalid"

    # Read / write standardized criticality (single source of truth)
    broker_registry.set_criticality("kraken", BrokerCriticality.CRITICAL)
    level = broker_registry.get_criticality("coinbase")   # → BrokerCriticality.PRIMARY
    critical_brokers = broker_registry.brokers_at_criticality(BrokerCriticality.CRITICAL)

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
- :class:`BrokerCriticality` is the **single source of truth** for how
  important each broker is across all system layers.  Every module that needs
  to gate on broker priority should read from
  ``broker_registry.get_criticality()`` rather than maintaining its own notion
  of "primary" or "platform".
"""

import logging
import threading
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, Iterator, Optional
from typing import Any, Callable, Dict, Iterator, List, Optional

logger = logging.getLogger("nija.broker_registry")

# ---------------------------------------------------------------------------
# Broker Criticality
# ---------------------------------------------------------------------------


class BrokerCriticality(str, Enum):
    """Importance tier for a broker in the execution pipeline.

    CRITICAL : A primary production venue (Coinbase, Kraken).  Its failure
               blocks new BUY orders on that broker until it recovers.  At
               least one CRITICAL broker must be connected for the trading
               cycle to proceed.
    OPTIONAL : A supplementary / degraded venue (OKX, Binance, Alpaca).
               Its failure is explicitly tolerated.  An OPTIONAL failure
               MUST NEVER block execution, reduce active_account_count to
               zero, or invalidate trading-cycle eligibility.
    """

    CRITICAL = "CRITICAL"
    OPTIONAL = "OPTIONAL"


#: Default criticality keyed by lowercase broker name.
#: Override at runtime: ``broker_registry["okx"]["criticality"] = BrokerCriticality.CRITICAL``
_DEFAULT_CRITICALITY: Dict[str, BrokerCriticality] = {
    "coinbase": BrokerCriticality.CRITICAL,
    "kraken": BrokerCriticality.CRITICAL,
    "okx": BrokerCriticality.OPTIONAL,
    "binance": BrokerCriticality.OPTIONAL,
    "alpaca": BrokerCriticality.OPTIONAL,
}


# ---------------------------------------------------------------------------
# Broker criticality levels — single authoritative enum for the whole system
# ---------------------------------------------------------------------------

class BrokerCriticality(Enum):
    """
    Standardized broker criticality levels for NIJA's multi-broker stack.

    Levels (highest → lowest priority):

    - **CRITICAL** – Must be connected before any user broker or trading begins.
      A failure blocks the entire system (e.g. platform Kraken whose nonce
      ordering affects every account).
    - **PRIMARY** – First-choice execution broker.  The system degrades but
      continues if PRIMARY fails (e.g. Coinbase acting as a live fallback).
    - **OPTIONAL** – Supplemental broker.  Skipped on failure without affecting
      the core trading flow.
    - **DEFERRED** – Low-priority; only connected after CRITICAL + PRIMARY
      brokers are stable.

    Using this enum as the single source of truth prevents hidden cross-layer
    gating bugs where one module treats a broker as "primary" while another
    treats it as "optional".
    """

    CRITICAL = "critical"
    PRIMARY  = "primary"
    OPTIONAL = "optional"
    DEFERRED = "deferred"


#: Default criticality for each well-known broker.
#:
#: These defaults are used by :meth:`BrokerRegistry.get_criticality` when no
#: runtime override has been stored.  Callers can promote or demote a broker at
#: runtime via :meth:`BrokerRegistry.set_criticality`.
BROKER_DEFAULT_CRITICALITY: Dict[str, BrokerCriticality] = {
    "kraken":   BrokerCriticality.CRITICAL,  # platform engine; nonce-sensitive
    "coinbase": BrokerCriticality.PRIMARY,   # primary fallback / user broker
    "binance":  BrokerCriticality.OPTIONAL,
    "okx":      BrokerCriticality.OPTIONAL,
    "alpaca":   BrokerCriticality.OPTIONAL,
}


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

    # ------------------------------------------------------------------
    # Criticality helpers — single source of truth across all layers
    # ------------------------------------------------------------------

    def set_criticality(self, broker_name: str, level: BrokerCriticality) -> None:
        """
        Store the criticality level for a broker in the registry.

        This is the **authoritative** write path.  All system layers (startup,
        connection manager, verifier, fallback controller) should call this
        method instead of maintaining their own private notion of broker
        priority.

        Args:
            broker_name: Broker identifier, e.g. ``"kraken"``.
            level: One of the :class:`BrokerCriticality` enum members.
        """
        self[broker_name]["criticality"] = level
        logger.debug(
            "broker_registry[%r]['criticality'] = %r", broker_name, level.value
        )

    def get_criticality(self, broker_name: str) -> BrokerCriticality:
        """
        Return the criticality level for a broker.

        Resolution order:
        1. Runtime value stored via :meth:`set_criticality` (highest priority).
        2. Static default from :data:`BROKER_DEFAULT_CRITICALITY`.
        3. :attr:`BrokerCriticality.OPTIONAL` (safe fallback for unknown brokers).

        Args:
            broker_name: Broker identifier, e.g. ``"kraken"``.

        Returns:
            :class:`BrokerCriticality` level.
        """
        stored = self.get_state(broker_name, "criticality")
        if isinstance(stored, BrokerCriticality):
            return stored
        return BROKER_DEFAULT_CRITICALITY.get(broker_name, BrokerCriticality.OPTIONAL)

    def brokers_at_criticality(self, level: BrokerCriticality) -> List[str]:
        """
        Return all broker names whose criticality equals *level*.

        Considers both brokers already present in the registry **and** those
        listed in :data:`BROKER_DEFAULT_CRITICALITY` that haven't been touched
        at runtime yet.

        Args:
            level: :class:`BrokerCriticality` level to filter by.

        Returns:
            Sorted list of broker names at the given level.
        """
        all_names: set = set(self.keys()) | set(BROKER_DEFAULT_CRITICALITY.keys())
        return sorted(name for name in all_names if self.get_criticality(name) == level)

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

    def is_critical(self, broker_name: str) -> bool:
        """Return ``True`` if *broker_name* is a CRITICAL-tier broker.

        Checks a runtime override stored in the registry first
        (``broker_registry[name]["criticality"]``), then falls back to
        :data:`_DEFAULT_CRITICALITY`.  Unknown brokers return ``False``
        (treated as OPTIONAL) so unrecognised venues are never blocking.

        Args:
            broker_name: Broker identifier, e.g. ``"kraken"``.
        """
        name = broker_name.lower().strip()
        override = self.get_state(name, "criticality")
        if override is not None:
            try:
                crit = BrokerCriticality(override) if isinstance(override, str) else override
                return crit == BrokerCriticality.CRITICAL
            except ValueError:
                pass
        return _DEFAULT_CRITICALITY.get(name, BrokerCriticality.OPTIONAL) == BrokerCriticality.CRITICAL


# ---------------------------------------------------------------------------
# Module-level singleton — import and use directly
# ---------------------------------------------------------------------------

#: Global broker state registry.
#:
#: Access or mutate broker state anywhere in the codebase::
#:
#:     from bot.broker_registry import broker_registry, BrokerCriticality
#:     broker_registry["kraken"]["platform"] = True
#:     broker_registry.set_criticality("kraken", BrokerCriticality.CRITICAL)
broker_registry: BrokerRegistry = BrokerRegistry()


def get_broker_criticality(broker_name: str) -> BrokerCriticality:
    """Return the :class:`BrokerCriticality` for *broker_name*.

    Checks a runtime override in the live registry first
    (``broker_registry[name]["criticality"]``), then falls back to
    :data:`_DEFAULT_CRITICALITY`.  Unknown brokers default to
    ``BrokerCriticality.OPTIONAL`` so unrecognised venues are always
    treated as non-blocking.

    Args:
        broker_name: Broker identifier (case-insensitive), e.g. ``"kraken"``.

    Returns:
        :class:`BrokerCriticality` – ``CRITICAL`` or ``OPTIONAL``.
    """
    name = broker_name.lower().strip()
    override = broker_registry.get_state(name, "criticality")
    if override is not None:
        try:
            return BrokerCriticality(override) if isinstance(override, str) else override
        except ValueError:
            pass
    return _DEFAULT_CRITICALITY.get(name, BrokerCriticality.OPTIONAL)
