#!/usr/bin/env python3
"""
DelistedAssetRegistry - Persistent registry for delisted/invalid trading symbols.

Tracks symbols that have been identified as invalid or delisted from the exchange,
surviving bot restarts so that:
  - Re-resolution attempts are not repeated unnecessarily
  - Delisted symbols are not re-scanned after restart
  - Dust-flagged and sell-attempted metadata is preserved across sessions

Stored as a JSON file with per-symbol records containing:
  - symbol: Trading pair symbol (e.g., 'BTC-USD')
  - timestamp: ISO-8601 timestamp when the symbol was first registered
  - permanent_dust: Whether the position has been classified as permanent dust
  - sell_attempted: Whether a sell was attempted for this symbol
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Dict, Optional

logger = logging.getLogger("nija.delisted_asset_registry")

# Default storage path (relative to working directory)
DEFAULT_REGISTRY_FILE = "./data/delisted_asset_registry.json"


class DelistedAssetRegistry:
    """
    Thread-safe, persistent registry for delisted/invalid trading symbols.

    Persists to a JSON file so that registry state survives bot restarts.
    Uses atomic file writes to prevent corruption on crash.

    Each registry entry stores:
        symbol         (str)  - Trading pair, e.g. 'XYZ-USD'
        timestamp      (str)  - ISO-8601 time the symbol was first registered
        permanent_dust (bool) - True if position is confirmed permanent dust
        sell_attempted (bool) - True if a sell order was attempted for this symbol
    """

    def __init__(self, registry_file: str = DEFAULT_REGISTRY_FILE):
        """
        Initialize the registry.

        Args:
            registry_file: Path to the JSON persistence file.
        """
        self._file = Path(registry_file)
        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        # Internal store: symbol -> {timestamp, permanent_dust, sell_attempted}
        self._registry: Dict[str, dict] = {}
        self._load()

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load registry from disk. Silently creates empty registry on first run."""
        if not self._file.exists():
            logger.info("DelistedAssetRegistry: no existing file found (first run)")
            return
        try:
            with open(self._file, "r") as f:
                data = json.load(f)
            self._registry = data.get("symbols", {})
            logger.info(
                f"DelistedAssetRegistry: loaded {len(self._registry)} symbol(s) from {self._file}"
            )
        except Exception as e:
            logger.error(f"DelistedAssetRegistry: failed to load from {self._file}: {e}")

    def _save(self) -> bool:
        """
        Persist registry to disk atomically.

        Returns:
            True on success, False on failure.
        """
        try:
            payload = {
                "updated_at": datetime.utcnow().isoformat(),
                "count": len(self._registry),
                "symbols": self._registry,
            }
            tmp = self._file.with_suffix(".tmp")
            with open(tmp, "w") as f:
                json.dump(payload, f, indent=2)
            tmp.replace(self._file)
            logger.debug(f"DelistedAssetRegistry: saved {len(self._registry)} symbol(s)")
            return True
        except Exception as e:
            logger.error(f"DelistedAssetRegistry: failed to save: {e}")
            return False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(
        self,
        symbol: str,
        permanent_dust: bool = False,
        sell_attempted: bool = False,
    ) -> bool:
        """
        Register a symbol as delisted/invalid.

        If the symbol is already registered, only the provided flags are
        updated (existing True flags are never reverted to False).

        Args:
            symbol:         Trading pair symbol (e.g. 'BTC-USD').
            permanent_dust: Mark as confirmed permanent dust.
            sell_attempted: Mark that a sell was attempted.

        Returns:
            True if the registry was modified and persisted successfully.
        """
        with self._lock:
            existing = self._registry.get(symbol)
            if existing is None:
                self._registry[symbol] = {
                    "timestamp": datetime.utcnow().isoformat(),
                    "permanent_dust": permanent_dust,
                    "sell_attempted": sell_attempted,
                }
                logger.warning(
                    f"🚫 DelistedAssetRegistry: registered new symbol {symbol} "
                    f"(permanent_dust={permanent_dust}, sell_attempted={sell_attempted})"
                )
            else:
                changed = False
                if permanent_dust and not existing["permanent_dust"]:
                    existing["permanent_dust"] = True
                    changed = True
                if sell_attempted and not existing["sell_attempted"]:
                    existing["sell_attempted"] = True
                    changed = True
                if not changed:
                    return True  # Already up-to-date; no write needed
                logger.info(
                    f"DelistedAssetRegistry: updated {symbol} "
                    f"(permanent_dust={existing['permanent_dust']}, "
                    f"sell_attempted={existing['sell_attempted']})"
                )
            return self._save()

    def is_registered(self, symbol: str) -> bool:
        """
        Check whether a symbol is in the registry.

        Args:
            symbol: Trading pair symbol.

        Returns:
            True if the symbol is registered as delisted/invalid.
        """
        with self._lock:
            return symbol in self._registry

    def get(self, symbol: str) -> Optional[dict]:
        """
        Return the registry entry for a symbol, or None if not registered.

        Args:
            symbol: Trading pair symbol.

        Returns:
            dict with keys {timestamp, permanent_dust, sell_attempted}, or None.
        """
        with self._lock:
            entry = self._registry.get(symbol)
            return dict(entry) if entry is not None else None

    def mark_sell_attempted(self, symbol: str) -> bool:
        """
        Convenience method: mark sell_attempted=True for an already-registered symbol.
        Registers the symbol if it is not yet present.

        Args:
            symbol: Trading pair symbol.

        Returns:
            True on success.
        """
        return self.register(symbol, sell_attempted=True)

    def mark_permanent_dust(self, symbol: str) -> bool:
        """
        Convenience method: mark permanent_dust=True for an already-registered symbol.
        Registers the symbol if it is not yet present.

        Args:
            symbol: Trading pair symbol.

        Returns:
            True on success.
        """
        return self.register(symbol, permanent_dust=True)

    def remove(self, symbol: str) -> bool:
        """
        Remove a symbol from the registry (manual override / re-listing).

        Args:
            symbol: Trading pair symbol.

        Returns:
            True if the symbol was found and removed successfully.
        """
        with self._lock:
            if symbol not in self._registry:
                logger.warning(f"DelistedAssetRegistry: {symbol} not in registry")
                return False
            del self._registry[symbol]
            logger.info(f"DelistedAssetRegistry: removed {symbol}")
            return self._save()

    def all_symbols(self) -> Dict[str, dict]:
        """
        Return a copy of all registry entries.

        Returns:
            dict mapping symbol -> {timestamp, permanent_dust, sell_attempted}.
        """
        with self._lock:
            return {sym: dict(entry) for sym, entry in self._registry.items()}

    def get_stats(self) -> dict:
        """
        Return summary statistics.

        Returns:
            dict with total count and per-flag counts.
        """
        with self._lock:
            total = len(self._registry)
            dust_count = sum(1 for e in self._registry.values() if e.get("permanent_dust"))
            sell_count = sum(1 for e in self._registry.values() if e.get("sell_attempted"))
            return {
                "total": total,
                "permanent_dust": dust_count,
                "sell_attempted": sell_count,
                "file": str(self._file),
            }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_registry_instance: Optional[DelistedAssetRegistry] = None
_registry_lock = Lock()


def get_delisted_asset_registry(
    registry_file: str = DEFAULT_REGISTRY_FILE,
) -> DelistedAssetRegistry:
    """
    Return the global singleton DelistedAssetRegistry instance.

    Args:
        registry_file: Path to JSON file (only used on first call).

    Returns:
        DelistedAssetRegistry singleton.
    """
    global _registry_instance
    with _registry_lock:
        if _registry_instance is None:
            _registry_instance = DelistedAssetRegistry(registry_file=registry_file)
        return _registry_instance
