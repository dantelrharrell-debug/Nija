"""

Thread-safe, JSON-backed singleton for persisting entry prices with full
metadata: price, UNIX timestamp, and source label.

Storage format (data/entry_prices.json)
---------------------------------------
::

    {
      "BTC-USD": {
        "price": 87543.21,
        "timestamp": 1711430000,
        "source": "execution",
        "quantity": 0.00123
      },
      ...
    }

``source`` values:
    - ``"execution"``  – price captured at trade execution time (most reliable)
    - ``"api"``        – price recovered from broker fills API (repair job)
    - ``"override"``   – manually set or safety-default value

Sync Repair Job
---------------
Call :func:`start_sync_repair_job` once at startup to launch a background
thread that periodically re-fetches entry prices from the broker API for any
symbol that is missing or has a stale record.  When the API returns a real
fill price it overwrites the stored value (``source="api"``), making the
system self-healing.

Usage
-----
::

    from bot.entry_price_store import get_entry_price_store

    store = get_entry_price_store()

    # Record at execution time
    store.save("BTC-USD", 87543.21, source="execution")

    # Retrieve
    record = store.get("BTC-USD")
    if record:
        print(record.price, record.timestamp, record.source)

    # Retrieve just the price (backward-compat helper)
    price = store.get_price("BTC-USD")  # float or None

    # Clear on position exit
    store.clear("BTC-USD")

    # Start self-healing background job
    # broker_getter must be a zero-arg callable that returns a broker with
    # get_real_entry_price(symbol) and get_all_positions() methods.
    store.start_sync_repair_job(broker_getter=lambda: my_broker, interval_secs=300)

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass
from typing import Callable, Dict, Optional

logger = logging.getLogger("nija.entry_price_store")

# ---------------------------------------------------------------------------
# Default file path (relative to process cwd; typically the repo root)
# ---------------------------------------------------------------------------
_DEFAULT_DATA_FILE = os.path.join("data", "entry_prices.json")

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class EntryPriceRecord:
    """One entry-price record for a single symbol."""

    price: float
    """The entry price (USD)."""

    timestamp: int
    """UNIX epoch seconds when the record was created / last updated."""

    source: str
    """Where the price came from: 'execution', 'api', or 'override'."""

    quantity: float = 0.0
    """Size of the position in base-asset units (e.g. BTC, HBAR)."""

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict) -> "EntryPriceRecord":
        return cls(
            price=float(d["price"]),
            timestamp=int(d["timestamp"]),
            source=str(d.get("source", "unknown")),
            quantity=float(d.get("quantity", 0.0)),
        )


# ---------------------------------------------------------------------------
# Core store
# ---------------------------------------------------------------------------

class EntryPriceStore:
    """
    Thread-safe, JSON-backed store for entry price records.

    Acquire the singleton via :func:`get_entry_price_store`.
    """

    def __init__(self, data_file: str = _DEFAULT_DATA_FILE):
        self._data_file = os.path.abspath(data_file)
        self._records: Dict[str, EntryPriceRecord] = {}
        self._lock = threading.Lock()
        self._repair_thread: Optional[threading.Thread] = None
        self._stop_repair = threading.Event()

        self._ensure_data_dir()
        self._load()
        logger.info(
            f"EntryPriceStore initialised: {len(self._records)} records "
            f"from {self._data_file}"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save(self, symbol: str, price: float, source: str = "execution",
             quantity: float = 0.0) -> None:
        """
        Persist an entry price record for *symbol*.

        Args:
            symbol:   Trading symbol (e.g. ``'BTC-USD'``).
            price:    Entry price in USD.
            source:   Origin of the price – ``'execution'``, ``'api'``, or
                      ``'override'``.
            quantity: Position size in base-asset units (e.g. 41.54 HBAR).
        """
        record = EntryPriceRecord(
            price=float(price),
            timestamp=int(time.time()),
            source=source,
            quantity=float(quantity),
        )
        with self._lock:
            self._records[symbol] = record
            self._persist()
        logger.debug(
            f"[EntryPriceStore] saved {symbol}: ${price:.4f} "
            f"qty={quantity} (source={source})"
        )

    def get(self, symbol: str) -> Optional[EntryPriceRecord]:
        """
        Return the :class:`EntryPriceRecord` for *symbol*, or ``None``.
        """
        with self._lock:
            return self._records.get(symbol)

    def get_price(self, symbol: str) -> Optional[float]:
        """
        Convenience wrapper – return just the price as a ``float``, or ``None``.
        """
        record = self.get(symbol)
        return record.price if record else None

    def clear(self, symbol: str) -> None:
        """Remove the record for *symbol* (call on full position exit)."""
        with self._lock:
            if symbol in self._records:
                del self._records[symbol]
                self._persist()
                logger.debug(f"[EntryPriceStore] cleared {symbol}")

    def all(self) -> Dict[str, EntryPriceRecord]:
        """Return a shallow copy of all stored records."""
        with self._lock:
            return dict(self._records)

    def all_as_dicts(self) -> Dict[str, Dict]:
        """Return all records serialised to plain dicts (useful for logging)."""
        with self._lock:
            return {sym: rec.to_dict() for sym, rec in self._records.items()}

    # ------------------------------------------------------------------
    # Sync Repair Job
    # ------------------------------------------------------------------

    def start_sync_repair_job(
        self,
        broker_getter: Callable,
        interval_secs: int = 300,
        symbols_getter: Optional[Callable] = None,
    ) -> None:
        """
        Launch a background daemon thread that periodically re-fetches entry
        prices from the broker API and overwrites stale / missing records.

        Args:
            broker_getter:   Zero-arg callable that returns the active broker
                             object.  The broker must expose
                             ``get_real_entry_price(symbol) -> Optional[float]``.
            interval_secs:   How often to run the repair sweep (default: 300 s).
            symbols_getter:  Optional zero-arg callable returning a list of
                             symbols to check.  If omitted the job checks only
                             symbols already in the store that were saved with
                             source ``'override'`` or missing API confirmation.
        """
        if self._repair_thread and self._repair_thread.is_alive():
            logger.debug("[EntryPriceStore] sync repair job already running")
            return

        self._stop_repair.clear()

        def _repair_loop() -> None:
            logger.info(
                f"[EntryPriceStore] sync repair job started "
                f"(interval={interval_secs}s)"
            )
            while not self._stop_repair.wait(timeout=interval_secs):
                self._run_repair(broker_getter, symbols_getter)
            logger.info("[EntryPriceStore] sync repair job stopped")

        self._repair_thread = threading.Thread(
            target=_repair_loop,
            name="entry-price-repair",
            daemon=True,
        )
        self._repair_thread.start()

    def stop_sync_repair_job(self) -> None:
        """Signal the background repair thread to exit on its next wakeup."""
        self._stop_repair.set()

    def _run_repair(
        self,
        broker_getter: Callable,
        symbols_getter: Optional[Callable],
    ) -> None:
        """Single repair sweep – called by the background thread."""
        try:
            broker = broker_getter()
            if broker is None:
                logger.debug("[EntryPriceStore] repair: broker not available")
                return

            # Determine which symbols to try repairing
            if symbols_getter:
                symbols = list(symbols_getter())
            else:
                # Fall back to symbols already in the store
                symbols = list(self.all().keys())

            if not symbols:
                return

            repaired = 0
            for symbol in symbols:
                try:
                    existing = self.get(symbol)
                    # Skip symbols already confirmed via execution
                    if existing and existing.source == "execution":
                        continue

                    if not hasattr(broker, "get_real_entry_price"):
                        continue

                    api_price = broker.get_real_entry_price(symbol)
                    if api_price and api_price > 0:
                        # Preserve quantity from the existing record when upgrading
                        preserved_qty = existing.quantity if existing else 0.0
                        self.save(symbol, api_price, source="api",
                                  quantity=preserved_qty)
                        logger.info(
                            f"[EntryPriceStore] repair: {symbol} → "
                            f"${api_price:.4f} qty={preserved_qty} (source=api)"
                        )
                        repaired += 1
                except Exception as sym_err:
                    logger.debug(
                        f"[EntryPriceStore] repair error for {symbol}: {sym_err}"
                    )

            if repaired:
                logger.info(
                    f"[EntryPriceStore] repair sweep done: {repaired} record(s) updated"
                )

        except Exception as err:
            logger.warning(f"[EntryPriceStore] repair sweep failed: {err}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_data_dir(self) -> None:
        """Create parent directory for the data file if it doesn't exist."""
        parent = os.path.dirname(self._data_file)
        if parent:
            os.makedirs(parent, exist_ok=True)

    def _load(self) -> None:
        """Load records from the JSON file (called once at init)."""
        try:
            if os.path.exists(self._data_file):
                with open(self._data_file, "r") as fh:
                    raw: Dict = json.load(fh)
                for sym, val in raw.items():
                    if isinstance(val, dict) and "price" in val:
                        # New rich format
                        self._records[sym] = EntryPriceRecord.from_dict(val)
                    elif isinstance(val, (int, float)):
                        # Legacy flat-price format – migrate transparently
                        self._records[sym] = EntryPriceRecord(
                            price=float(val),
                            timestamp=int(time.time()),
                            source="override",
                            quantity=0.0,
                        )
                logger.info(
                    f"[EntryPriceStore] loaded {len(self._records)} record(s)"
                )
            else:
                logger.debug("[EntryPriceStore] no existing data file – starting empty")
        except Exception as err:
            logger.error(f"[EntryPriceStore] failed to load data: {err}")
            self._records = {}

    def _persist(self) -> None:
        """Write current records to disk (assumes self._lock is held)."""
        try:
            payload = {sym: rec.to_dict() for sym, rec in self._records.items()}
            tmp = self._data_file + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(payload, fh, indent=2)
            os.replace(tmp, self._data_file)
        except Exception as err:
            logger.error(f"[EntryPriceStore] failed to persist data: {err}")


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_store_instance: Optional[EntryPriceStore] = None
_store_lock = threading.Lock()


def get_entry_price_store(data_file: str = _DEFAULT_DATA_FILE) -> EntryPriceStore:
    """
    Return the process-wide singleton :class:`EntryPriceStore`.

    The instance is created lazily on the first call.  Subsequent calls with
    the same or no ``data_file`` return the same object.
    """
    global _store_instance
    if _store_instance is None:
        with _store_lock:
            if _store_instance is None:
                _store_instance = EntryPriceStore(data_file=data_file)
    return _store_instance
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
