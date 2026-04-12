"""
NIJA Coinbase Controller — Micro-Cap Execution Path
=====================================================

Enforces Coinbase-specific trading policy:
- Only micro-cap symbols may be traded on Coinbase
- Capital floor is $1 (COINBASE_MIN_CAPITAL), not Kraken's $25
- Minimum order is $1 (COINBASE_MIN_ORDER)
- exit_only_mode is permanently OFF — Coinbase is the active execution path

Symbol universe
---------------
Default list targets lower-to-mid market-cap tokens available on Coinbase
that are NOT BTC/ETH/SOL/DOGE (the mega/large-cap coins).  Override at
runtime via the NIJA_COINBASE_SYMBOLS environment variable
(comma-separated, e.g. ``ALGO-USD,XLM-USD,ATOM-USD``).

Singleton access
----------------
    from bot.coinbase_controller import get_coinbase_controller
    ctrl = get_coinbase_controller()
"""

from __future__ import annotations

import logging
import os
import threading
from typing import List, Optional

logger = logging.getLogger("nija.coinbase_controller")

# ---------------------------------------------------------------------------
# Import capital constants from the central profile registry
# ---------------------------------------------------------------------------
try:
    from bot.broker_profiles import (
        COINBASE_MIN_CAPITAL, COINBASE_MIN_ORDER, COINBASE_MICRO_CAP_MODE,
    )
except ImportError:
    from broker_profiles import (  # type: ignore[no-redef]
        COINBASE_MIN_CAPITAL, COINBASE_MIN_ORDER, COINBASE_MICRO_CAP_MODE,
    )

# ---------------------------------------------------------------------------
# Default micro-cap symbol universe
# Coins below the BTC/ETH/SOL tier; all available on Coinbase Advanced Trade.
# Override via NIJA_COINBASE_SYMBOLS env var.
# ---------------------------------------------------------------------------
COINBASE_MICRO_CAP_SYMBOLS: List[str] = [
    "ADA-USD",    # Cardano
    "ALGO-USD",   # Algorand
    "ATOM-USD",   # Cosmos
    "AVAX-USD",   # Avalanche
    "BCH-USD",    # Bitcoin Cash
    "DOT-USD",    # Polkadot
    "LINK-USD",   # Chainlink
    "LTC-USD",    # Litecoin
    "MATIC-USD",  # Polygon
    "UNI-USD",    # Uniswap
    "XDC-USD",    # XDC Network
    "XLM-USD",    # Stellar
]

# Allow full override from the environment
_env_symbols_raw: str = os.getenv("NIJA_COINBASE_SYMBOLS", "").strip()
if _env_symbols_raw:
    COINBASE_MICRO_CAP_SYMBOLS = [
        s.strip().upper() for s in _env_symbols_raw.split(",") if s.strip()
    ]


class CoinbaseController:
    """Controls all Coinbase execution with micro-cap-only policy.

    Parameters
    ----------
    symbols:
        Explicit micro-cap symbol universe.  When *None* the module-level
        ``COINBASE_MICRO_CAP_SYMBOLS`` list is used.
    min_capital:
        Minimum USD balance required to open new positions.
    min_order:
        Minimum USD order size.
    """

    #: Execution mode label used by GlobalController routing.
    EXECUTION_MODE: str = "active"

    def __init__(
        self,
        symbols: Optional[List[str]] = None,
        min_capital: float = COINBASE_MIN_CAPITAL,
        min_order: float = COINBASE_MIN_ORDER,
    ) -> None:
        self._symbols: frozenset = frozenset(
            s.upper() for s in (symbols or COINBASE_MICRO_CAP_SYMBOLS)
        )
        self._min_capital: float = min_capital
        self._min_order: float = min_order
        self._lock = threading.Lock()

        logger.info("=" * 60)
        logger.info("🟢 CoinbaseController initialised (micro-cap mode)")
        logger.info("   Execution mode : ACTIVE")
        logger.info("   Min capital    : $%.2f", self._min_capital)
        logger.info("   Min order      : $%.2f", self._min_order)
        logger.info("   Symbol universe: %s", ", ".join(sorted(self._symbols)))
        logger.info("=" * 60)

    # ------------------------------------------------------------------
    # Symbol policy
    # ------------------------------------------------------------------

    def is_symbol_allowed(self, symbol: str) -> bool:
        """Return *True* if *symbol* is in the micro-cap universe."""
        return symbol.upper() in self._symbols

    def filter_symbols(self, candidates: List[str]) -> List[str]:
        """Return only the symbols from *candidates* that are in the universe."""
        return [s for s in candidates if s.upper() in self._symbols]

    # ------------------------------------------------------------------
    # Execution policy
    # ------------------------------------------------------------------

    def can_execute_entry(self, balance: float = 0.0) -> bool:
        """Return *True* — Coinbase is the active execution path.

        The optional *balance* argument allows callers to perform the
        capital-floor check in one call.
        """
        if balance > 0 and balance < self._min_capital:
            logger.debug(
                "Coinbase entry blocked: balance $%.2f < min_capital $%.2f",
                balance, self._min_capital,
            )
            return False
        return True

    def is_order_size_valid(self, usd_size: float) -> bool:
        """Return *True* if *usd_size* meets the Coinbase minimum order floor."""
        return usd_size >= self._min_order

    # ------------------------------------------------------------------
    # Broker integration
    # ------------------------------------------------------------------

    def apply_to_broker(self, broker) -> None:
        """Apply Coinbase policy to a *BaseBroker* instance.

        Ensures ``exit_only_mode`` is **off** so the active execution path
        is never accidentally blocked.
        """
        if broker is None:
            return
        if getattr(broker, "exit_only_mode", None):
            broker.exit_only_mode = False
            logger.info(
                "✅ CoinbaseController: exit_only_mode cleared on %s",
                getattr(broker, "broker_type", broker),
            )

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def min_capital(self) -> float:
        return self._min_capital

    @property
    def min_order(self) -> float:
        return self._min_order

    @property
    def symbols(self) -> frozenset:
        return self._symbols

    def get_status(self) -> dict:
        return {
            "execution_mode": self.EXECUTION_MODE,
            "micro_cap_enabled": True,
            "min_capital_usd": self._min_capital,
            "min_order_usd": self._min_order,
            "symbol_count": len(self._symbols),
            "symbols": sorted(self._symbols),
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_instance: Optional[CoinbaseController] = None
_instance_lock = threading.Lock()


def get_coinbase_controller() -> CoinbaseController:
    """Return (or create) the process-wide :class:`CoinbaseController` singleton."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = CoinbaseController()
    return _instance
