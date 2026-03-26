"""
Entry Price Store — local truth storage for position entry prices.

Saves entry prices to a JSON file the moment a trade executes so that
the bot never has to rely solely on the broker API to recover them.

Usage
-----
    from entry_price_store import get_entry_price_store

    store = get_entry_price_store()

    # On BUY fill:
    store.save(symbol, fill_price)

    # On position close:
    store.clear(symbol)

    # When broker API fails:
    price = store.get(symbol)   # returns float or None
"""

import json
import logging
import os
import time
from pathlib import Path
from threading import Lock
from typing import Dict, Optional

logger = logging.getLogger("nija.entry_price_store")

# Default persistence path (inside the data/ directory next to bot/)
_DEFAULT_STORE_PATH = Path(__file__).parent.parent / "data" / "entry_prices.json"


class EntryPriceStore:
    """
    Thread-safe, JSON-backed store for position entry prices.

    The store is loaded once at startup.  Every mutation is flushed to disk
    atomically (write-to-temp then rename) so the file is never left in a
    partial state.
    """

    def __init__(self, store_path: str = None):
        self._path = Path(store_path) if store_path else _DEFAULT_STORE_PATH
        self._lock = Lock()
        # { symbol -> {"price": float, "timestamp": float} }
        self._data: Dict[str, Dict] = {}
        self._load()

    # ─────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────

    def save(self, symbol: str, price: float, timestamp: float = None) -> None:
        """Persist an entry price for *symbol*.

        Overwrites any existing record for the symbol (e.g. on position add /
        average-in, call save() again with the new weighted-average price).

        Args:
            symbol:    Trading symbol, e.g. ``'HBAR-USD'``.
            price:     Fill / entry price.
            timestamp: Unix epoch (defaults to ``time.time()``).
        """
        if price <= 0:
            logger.warning(f"[EntryPriceStore] Refusing to save zero or negative price {price} for {symbol}")
            return

        ts = timestamp or time.time()
        with self._lock:
            self._data[symbol] = {"price": float(price), "timestamp": float(ts)}
            self._flush()

        logger.debug(f"[EntryPriceStore] Saved {symbol} entry=${price:.6g}")

    def get(self, symbol: str) -> Optional[float]:
        """Return the locally-stored entry price, or ``None`` if unknown.

        Args:
            symbol: Trading symbol.

        Returns:
            Entry price as a float, or ``None``.
        """
        with self._lock:
            record = self._data.get(symbol)
        if record:
            return float(record["price"])
        return None

    def clear(self, symbol: str) -> None:
        """Remove the entry price record when a position is fully closed.

        Args:
            symbol: Trading symbol.
        """
        with self._lock:
            removed = self._data.pop(symbol, None)
            if removed is not None:
                self._flush()

        if removed is not None:
            logger.debug(f"[EntryPriceStore] Cleared {symbol} (position closed)")

    def all(self) -> Dict[str, float]:
        """Return a snapshot of all stored entry prices as ``{symbol: price}``."""
        with self._lock:
            return {sym: float(rec["price"]) for sym, rec in self._data.items()}

    # ─────────────────────────────────────────────────────────────────
    # Internals
    # ─────────────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Load persisted data from disk (called once at init)."""
        try:
            if self._path.exists():
                content = self._path.read_text().strip()
                if not content:
                    logger.info("[EntryPriceStore] Entry price file is empty — starting fresh")
                    return
                raw = json.loads(content)
                # Accept both old format (plain {sym: price}) and new format
                for sym, val in raw.items():
                    if isinstance(val, dict):
                        self._data[sym] = val
                    else:
                        self._data[sym] = {"price": float(val), "timestamp": 0.0}
                logger.info(
                    f"[EntryPriceStore] Loaded {len(self._data)} entry price(s) from {self._path}"
                )
            else:
                logger.info("[EntryPriceStore] No existing entry price file — starting fresh")
        except Exception as exc:
            logger.error(f"[EntryPriceStore] Failed to load from {self._path}: {exc}")
            self._data = {}

    def _flush(self) -> None:
        """Write current data to disk (caller must hold self._lock)."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = Path(str(self._path) + ".tmp")
            with open(tmp, "w") as fh:
                json.dump(self._data, fh, indent=2)
            tmp.replace(self._path)
        except Exception as exc:
            logger.error(f"[EntryPriceStore] Failed to flush to {self._path}: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────────────────

_instance: Optional[EntryPriceStore] = None
_instance_lock = Lock()


def get_entry_price_store(store_path: str = None) -> EntryPriceStore:
    """Return the process-wide singleton EntryPriceStore.

    Args:
        store_path: Override the default JSON path (used in tests).

    Returns:
        The singleton ``EntryPriceStore`` instance.
    """
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = EntryPriceStore(store_path=store_path)
    return _instance
