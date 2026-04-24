"""
Emergency Symbol Resolver for NIJA Trading Bot

Handles the case where a price fetch fails for a symbol (e.g., due to
delisting, renaming, or ticker mapping issues on Kraken).

Resolution pipeline (attempted in order):
  1. Alternate pair mapping  (AUT-USD → AUT/USD, AUTUSD, AUT-USDT, …)
  2. Base/quote inversion    (if the pair might be quoted differently)
  3. USD bridge valuation    (ASSET → BTC, BTC → USD to estimate value)
  4. DelistedAsset           (classify asset as non-tradeable residual)

Delisted Asset Protocol:
  - Remove from active position cap count
  - Mark as "Non-Tradeable Residual"
  - Exclude from exposure modeling
  - Attempt a market sell whenever liquidity re-appears
  - Classify as permanent dust if sell is impossible

Usage (inside KrakenBroker.get_current_price):
    from bot.emergency_symbol_resolver import EmergencySymbolResolver
    resolver = EmergencySymbolResolver(kraken_api_ref)
    result = resolver.resolve(symbol)
    if result.price:
        return result.price
    if result.status == SymbolStatus.DELISTED:
        # trigger delisted-asset protocol
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from threading import Lock
from typing import Dict, List, Optional, Set

logger = logging.getLogger("nija.emergency_symbol_resolver")


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

class SymbolStatus(str, Enum):
    """Resolution outcome for a symbol lookup attempt."""
    OK = "ok"                          # price found via normal or alternate path
    ALTERNATE_PAIR = "alternate_pair"  # price found via alternate ticker mapping
    USD_BRIDGE = "usd_bridge"          # price estimated via USD bridge
    DELISTED = "delisted"              # confirmed non-tradeable / delisted
    UNKNOWN = "unknown"                # fetch failed but not confirmed delisted


@dataclass
class ResolvedSymbol:
    """Outcome returned by EmergencySymbolResolver.resolve()."""
    original_symbol: str
    resolved_symbol: Optional[str] = None   # symbol that actually returned a price
    price: Optional[float] = None           # price if found, else None
    status: SymbolStatus = SymbolStatus.UNKNOWN
    reason: str = ""                        # human-readable explanation


# ---------------------------------------------------------------------------
# Delisted Asset Registry  (thread-safe singleton)
# ---------------------------------------------------------------------------

class DelistedAssetRegistry:
    """
    Tracks assets that are confirmed delisted or non-tradeable.

    Thread-safe singleton — share one instance across the whole bot session.
    """

    _instance: Optional["DelistedAssetRegistry"] = None
    _lock: Lock = Lock()

    def __init__(self) -> None:
        self._delisted: Dict[str, Dict] = {}   # symbol → metadata dict
        self._registry_lock = Lock()

    @classmethod
    def get_instance(cls) -> "DelistedAssetRegistry":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
        return cls._instance

    def mark_delisted(
        self,
        symbol: str,
        reason: str = "Price fetch failed after all resolution attempts",
    ) -> None:
        """Record a symbol as delisted / non-tradeable residual."""
        with self._registry_lock:
            if symbol not in self._delisted:
                logger.warning(
                    f"🚫 DELISTED ASSET PROTOCOL: {symbol} classified as "
                    f"Non-Tradeable Residual — {reason}"
                )
            self._delisted[symbol] = {
                "symbol": symbol,
                "status": "Non-Tradeable Residual",
                "reason": reason,
                "detected_at": time.time(),
                "sell_attempted": self._delisted.get(symbol, {}).get("sell_attempted", False),
                "permanent_dust": self._delisted.get(symbol, {}).get("permanent_dust", False),
            }

    def mark_sell_attempted(self, symbol: str) -> None:
        """Record that we attempted a market sell for a delisted asset."""
        with self._registry_lock:
            if symbol in self._delisted:
                self._delisted[symbol]["sell_attempted"] = True
                logger.info(f"   ↪ Sell attempted for delisted asset: {symbol}")

    def mark_permanent_dust(self, symbol: str) -> None:
        """Mark a delisted asset as permanent dust (sell is no longer possible)."""
        with self._registry_lock:
            if symbol in self._delisted:
                self._delisted[symbol]["permanent_dust"] = True
                logger.warning(f"♻️  {symbol} classified as permanent dust (no liquidity)")

    def is_delisted(self, symbol: str) -> bool:
        with self._registry_lock:
            return symbol in self._delisted

    def get_delisted_symbols(self) -> Set[str]:
        with self._registry_lock:
            return set(self._delisted.keys())

    def get_metadata(self, symbol: str) -> Optional[Dict]:
        with self._registry_lock:
            return dict(self._delisted.get(symbol, {}))

    def get_all(self) -> Dict[str, Dict]:
        with self._registry_lock:
            return {k: dict(v) for k, v in self._delisted.items()}


# ---------------------------------------------------------------------------
# Alternate ticker variants generator
# ---------------------------------------------------------------------------

def _alternate_kraken_tickers(standard_symbol: str) -> List[str]:
    """
    Generate a list of Kraken ticker variants to try when the primary lookup fails.

    Args:
        standard_symbol: Symbol in standard format, e.g. "AUT-USD"

    Returns:
        List of Kraken ticker strings to probe, in priority order.
    """
    parts = standard_symbol.upper().split("-")
    if len(parts) != 2:
        return []

    base, quote = parts

    # BTC ↔ XBT (Kraken uses XBT internally)
    base_variants: List[str] = [base]
    if base == "BTC":
        base_variants.append("XBT")
    elif base == "XBT":
        base_variants.append("BTC")

    quote_variants: List[str] = [quote]
    if quote == "USD":
        quote_variants.extend(["USDT", "ZUSD"])
    elif quote == "USDT":
        quote_variants.extend(["USD", "ZUSD"])
    elif quote == "ZUSD":
        quote_variants.extend(["USD", "USDT"])

    candidates: List[str] = []
    for b in base_variants:
        for q in quote_variants:
            # Plain concatenation (most common Kraken format)
            candidates.append(f"{b}{q}")
            # With X prefix (Kraken legacy format for crypto)
            candidates.append(f"X{b}Z{q}")
            candidates.append(f"X{b}{q}")

    # Deduplicate while preserving order
    seen: Set[str] = set()
    unique: List[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            unique.append(c)

    return unique


# ---------------------------------------------------------------------------
# Main resolver
# ---------------------------------------------------------------------------

class EmergencySymbolResolver:
    """
    Multi-stage price resolution for Kraken symbols.

    Pass the raw krakenex.API instance (self.api in KrakenBroker) so the
    resolver can query the Ticker public endpoint directly without needing
    authentication.
    """

    # Minimum number of consecutive failures before a symbol is marked delisted
    FAILURES_BEFORE_DELISTED = 3

    def __init__(self, kraken_api) -> None:
        """
        Args:
            kraken_api: A krakenex.API instance (already connected).
        """
        self._api = kraken_api
        self._failure_counts: Dict[str, int] = {}
        self._failure_lock = Lock()
        self._registry = DelistedAssetRegistry.get_instance()

    # ------------------------------------------------------------------
    # Public entry-point
    # ------------------------------------------------------------------

    def resolve(self, standard_symbol: str) -> ResolvedSymbol:
        """
        Attempt all resolution stages for *standard_symbol*.

        Args:
            standard_symbol: e.g. "AUT-USD"

        Returns:
            ResolvedSymbol with .price set if found, or .status == DELISTED.
        """
        logger.debug(f"🔎 EmergencySymbolResolver: trying to resolve {standard_symbol}")

        # Stage 1 — alternate pair mapping
        result = self._try_alternate_pairs(standard_symbol)
        if result.price is not None:
            self._reset_failure(standard_symbol)
            return result

        # Stage 2 — USD bridge valuation
        result = self._try_usd_bridge(standard_symbol)
        if result.price is not None:
            self._reset_failure(standard_symbol)
            return result

        # All stages failed — increment failure counter
        count = self._increment_failure(standard_symbol)

        if count >= self.FAILURES_BEFORE_DELISTED:
            self._registry.mark_delisted(
                standard_symbol,
                reason=f"Price fetch failed after {count} consecutive attempts "
                       f"(all resolution stages exhausted)",
            )
            return ResolvedSymbol(
                original_symbol=standard_symbol,
                status=SymbolStatus.DELISTED,
                reason=(
                    f"Symbol {standard_symbol} could not be resolved after "
                    f"{count} attempts — classified as Non-Tradeable Residual"
                ),
            )

        return ResolvedSymbol(
            original_symbol=standard_symbol,
            status=SymbolStatus.UNKNOWN,
            reason=f"Resolution failed (attempt {count}/{self.FAILURES_BEFORE_DELISTED})",
        )

    # ------------------------------------------------------------------
    # Stage 1: Alternate pair mapping
    # ------------------------------------------------------------------

    def _try_alternate_pairs(self, standard_symbol: str) -> ResolvedSymbol:
        """Try alternate Kraken ticker variants for the symbol."""
        variants = _alternate_kraken_tickers(standard_symbol)
        for ticker in variants:
            price = self._fetch_ticker_price(ticker)
            if price is not None:
                logger.info(
                    f"✅ EmergencyResolver [Stage 1]: {standard_symbol} resolved via "
                    f"alternate ticker '{ticker}' → ${price:.6f}"
                )
                return ResolvedSymbol(
                    original_symbol=standard_symbol,
                    resolved_symbol=ticker,
                    price=price,
                    status=SymbolStatus.ALTERNATE_PAIR,
                    reason=f"Resolved via alternate Kraken ticker '{ticker}'",
                )
        return ResolvedSymbol(original_symbol=standard_symbol, status=SymbolStatus.UNKNOWN,
                              reason="No alternate pair succeeded")

    # ------------------------------------------------------------------
    # Stage 2: USD bridge valuation
    # ------------------------------------------------------------------

    def _try_usd_bridge(self, standard_symbol: str) -> ResolvedSymbol:
        """
        Estimate USD value via an intermediate BTC or ETH bridge.

        e.g.  AUT-USD fails  →  try AUT-XBT × BTC-USD
        """
        parts = standard_symbol.upper().split("-")
        if len(parts) != 2:
            return ResolvedSymbol(original_symbol=standard_symbol, status=SymbolStatus.UNKNOWN,
                                  reason="Cannot parse symbol for bridge")
        base, quote = parts
        if quote not in ("USD", "USDT", "ZUSD"):
            return ResolvedSymbol(original_symbol=standard_symbol, status=SymbolStatus.UNKNOWN,
                                  reason="Non-USD quote — bridge not applicable")

        bridges = [
            ("XXBT", "XXBTZUSD"),  # via BTC
            ("XETH", "XETHZUSD"),  # via ETH
        ]

        for bridge_asset, bridge_usd_pair in bridges:
            # Try to get ASSET/BTC (or ASSET/ETH) price
            asset_bridge_ticker = f"X{base}{bridge_asset}"
            asset_price_in_bridge = self._fetch_ticker_price(asset_bridge_ticker)

            if asset_price_in_bridge is None:
                # Try without X prefix
                asset_bridge_ticker = f"{base}{bridge_asset.lstrip('X')}"
                asset_price_in_bridge = self._fetch_ticker_price(asset_bridge_ticker)

            if asset_price_in_bridge is None:
                continue

            # Get bridge asset price in USD
            bridge_usd_price = self._fetch_ticker_price(bridge_usd_pair)
            if bridge_usd_price is None:
                continue

            estimated_price = asset_price_in_bridge * bridge_usd_price
            bridge_name = "BTC" if "XBT" in bridge_asset else "ETH"
            logger.info(
                f"✅ EmergencyResolver [Stage 2]: {standard_symbol} estimated via "
                f"{bridge_name} bridge → ${estimated_price:.6f} "
                f"({asset_bridge_ticker}={asset_price_in_bridge:.8f}, "
                f"{bridge_usd_pair}={bridge_usd_price:.2f})"
            )
            return ResolvedSymbol(
                original_symbol=standard_symbol,
                resolved_symbol=f"{asset_bridge_ticker}→{bridge_usd_pair}",
                price=estimated_price,
                status=SymbolStatus.USD_BRIDGE,
                reason=f"Estimated via {bridge_name} bridge (informational — not tradeable at this price)",
            )

        return ResolvedSymbol(original_symbol=standard_symbol, status=SymbolStatus.UNKNOWN,
                              reason="USD bridge resolution failed")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_ticker_price(self, kraken_ticker: str) -> Optional[float]:
        """
        Query Kraken public Ticker endpoint and return last-trade price.

        Returns None on any failure (no exception raised).
        """
        try:
            result = self._api.query_public("Ticker", {"pair": kraken_ticker})
            if not result or "result" not in result:
                return None
            ticker_data = result["result"].get(kraken_ticker, {})
            if not ticker_data:
                # Some pairs appear under a slightly different key in the response
                # (Kraken normalises the key); try first available key
                if result["result"]:
                    ticker_data = next(iter(result["result"].values()))
            if ticker_data:
                last_price = ticker_data.get("c", [None])[0]
                if last_price:
                    return float(last_price)
        except Exception as exc:
            logger.debug(f"   Ticker probe '{kraken_ticker}' failed: {exc}")
        return None

    def _increment_failure(self, symbol: str) -> int:
        with self._failure_lock:
            self._failure_counts[symbol] = self._failure_counts.get(symbol, 0) + 1
            return self._failure_counts[symbol]

    def _reset_failure(self, symbol: str) -> None:
        with self._failure_lock:
            self._failure_counts.pop(symbol, None)


# ---------------------------------------------------------------------------
# Delisted Asset Protocol helpers
# ---------------------------------------------------------------------------

def attempt_delisted_asset_sell(
    broker,
    symbol: str,
    quantity: float,
    registry: Optional[DelistedAssetRegistry] = None,
) -> bool:
    """
    Attempt a market sell for a delisted asset when liquidity might have appeared.

    This is step 4 of the Delisted Asset Protocol:
      → Try to exit the position; if it fails, mark as permanent dust.

    Args:
        broker: The broker instance (must have place_market_order).
        symbol: Symbol to sell (standard format).
        quantity: Number of base units to sell.
        registry: DelistedAssetRegistry instance (uses global singleton if None).

    Returns:
        True if sell succeeded, False otherwise.
    """
    if registry is None:
        registry = DelistedAssetRegistry.get_instance()

    logger.info(f"💸 Delisted Asset Protocol: attempting market sell for {symbol} qty={quantity}")
    try:
        result = broker.place_market_order(
            symbol=symbol,
            side="sell",
            size=quantity,
            size_type="base",
        )
        if result and result.get("status") in ("filled", "assumed_filled"):
            registry.mark_sell_attempted(symbol)
            logger.info(f"✅ Delisted asset {symbol} successfully sold — position closed")
            return True
        else:
            registry.mark_sell_attempted(symbol)
            logger.warning(f"⚠️ Delisted asset sell for {symbol} returned unexpected status: {result}")
            return False
    except Exception as exc:
        logger.warning(f"⚠️ Delisted asset sell failed for {symbol}: {exc}")
        registry.mark_permanent_dust(symbol)
        return False


def is_excluded_from_exposure(symbol: str) -> bool:
    """
    Return True if symbol should be excluded from exposure modeling
    (because it is a confirmed delisted / Non-Tradeable Residual).

    Args:
        symbol: Standard format symbol (e.g. "AUT-USD").
    """
    return DelistedAssetRegistry.get_instance().is_delisted(symbol)


def get_active_position_symbols(all_symbols: List[str]) -> List[str]:
    """
    Filter out delisted assets from a position symbol list for cap-count purposes.

    Args:
        all_symbols: Full list of symbols with open positions.

    Returns:
        List of symbols that are still considered active (not delisted).
    """
    registry = DelistedAssetRegistry.get_instance()
    active = [s for s in all_symbols if not registry.is_delisted(s)]
    excluded = len(all_symbols) - len(active)
    if excluded:
        logger.debug(f"   ℹ️  {excluded} delisted asset(s) excluded from active cap count")
    return active
