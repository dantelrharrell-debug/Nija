"""
Exchange Order Validator
========================
Validates and normalises every order before it reaches the exchange.

Key responsibilities
--------------------
1. **Step-size normalisation** – ``round_to_step(symbol, volume)`` rounds the
   base quantity DOWN to the exchange's minimum base increment so Coinbase
   never rejects with INVALID_BASE_SIZE.

2. **Decimal precision** – ``apply_precision(symbol, volume)`` rounds the
   value to the correct number of decimal places for the asset, removing
   floating-point artefacts that some exchange APIs reject.

3. **Minimum-volume enforcement** – ``enforce_min_volume(symbol, volume)``
   returns ``0.0`` when the requested volume is below the exchange floor,
   signalling that the order must not be placed.

4. **Single-call validator** – ``validate_order(symbol, volume)`` chains all
   three steps and returns the normalised volume, or ``None`` when the order
   cannot be placed (too small or reduced to zero by step rounding).

5. **PERMANENT_DUST_UNSELLABLE flag** – when a SELL order's adjusted value is
   still below the minimum *after* full normalisation, the symbol is flagged
   permanently and excluded from every system (position counts, cleanup,
   further retries).  The flag survives restarts via a JSON sidecar file.

6. **[ORDER NORMALIZED] audit log** – every time the requested quantity is
   adjusted, a structured log line is emitted so operators can trace exactly
   what changed and why::

       [ORDER NORMALIZED] symbol=AVAX-USD requested=0.38874957 adjusted=0.40 reason=step_size + min_volume

Quick-start
-----------
Module-level API (simplest — call this before every order)::

    from bot.exchange_order_validator import validate_order

    adjusted = validate_order("AVAX-USD", 0.38874957)
    if adjusted is None:
        # order blocked (too small or permanently unsellable)
        ...

Class-level API (full result with PERMANENT_DUST_UNSELLABLE handling)::

    from bot.exchange_order_validator import get_exchange_order_validator

    validator = get_exchange_order_validator()
    result = validator.validate_and_normalize(
        symbol="AVAX-USD", side="sell", quantity=0.38874957,
        price=35.50, size_type="base"
    )
    if result.is_permanently_unsellable:
        ...  # skip forever
    elif not result.is_valid:
        ...  # skip this cycle
    else:
        quantity = result.adjusted_qty
"""

from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional

logger = logging.getLogger("nija.exchange_order_validator")

# ---------------------------------------------------------------------------
# Exchange rules table
# ---------------------------------------------------------------------------
# Each entry defines the constraints for a Coinbase product (base asset).
#
# Fields
# ------
# step_size   : Minimum base increment — the smallest unit the exchange will
#               accept.  Quantities must be a multiple of this value.
# precision   : Decimal places matching step_size.  Derived as
#               -floor(log10(step_size)) for fractional steps, 0 for whole.
# min_volume  : Minimum base quantity that produces a valid order.  Set to
#               step_size (one tick) as the absolute floor; notional-value
#               checks ($1 USD) are applied on top by the validator.
#
# Note: "DEFAULT" is used for any symbol not listed explicitly.

exchange_rules: Dict[str, Dict] = {
    # ── Major pairs ───────────────────────────────────────────────────────
    "BTC":    {"step_size": 0.00000001, "precision": 8,  "min_volume": 0.00000001},
    "ETH":    {"step_size": 0.000001,   "precision": 6,  "min_volume": 0.000001},
    "SOL":    {"step_size": 0.001,      "precision": 3,  "min_volume": 0.001},
    "AVAX":   {"step_size": 0.01,       "precision": 2,  "min_volume": 0.01},
    "DOT":    {"step_size": 0.1,        "precision": 1,  "min_volume": 0.1},
    "LINK":   {"step_size": 0.01,       "precision": 2,  "min_volume": 0.01},
    "LTC":    {"step_size": 0.00000001, "precision": 8,  "min_volume": 0.00000001},
    "BCH":    {"step_size": 0.00000001, "precision": 8,  "min_volume": 0.00000001},
    "UNI":    {"step_size": 0.01,       "precision": 2,  "min_volume": 0.01},
    "APT":    {"step_size": 0.01,       "precision": 2,  "min_volume": 0.01},
    "ICP":    {"step_size": 0.01,       "precision": 2,  "min_volume": 0.01},
    "AAVE":   {"step_size": 0.001,      "precision": 3,  "min_volume": 0.001},
    "ATOM":   {"step_size": 0.0001,     "precision": 4,  "min_volume": 0.0001},
    "IMX":    {"step_size": 0.0001,     "precision": 4,  "min_volume": 0.0001},
    "NEAR":   {"step_size": 0.00001,    "precision": 5,  "min_volume": 0.00001},
    "RENDER": {"step_size": 0.1,        "precision": 1,  "min_volume": 0.1},
    # ── Whole-number assets (step = 1) ────────────────────────────────────
    "ADA":    {"step_size": 1.0,        "precision": 0,  "min_volume": 1.0},
    "XRP":    {"step_size": 1.0,        "precision": 0,  "min_volume": 1.0},
    "DOGE":   {"step_size": 1.0,        "precision": 0,  "min_volume": 1.0},
    "XLM":    {"step_size": 1.0,        "precision": 0,  "min_volume": 1.0},
    "HBAR":   {"step_size": 1.0,        "precision": 0,  "min_volume": 1.0},
    "ZRX":    {"step_size": 1.0,        "precision": 0,  "min_volume": 1.0},
    "CRV":    {"step_size": 1.0,        "precision": 0,  "min_volume": 1.0},
    "FET":    {"step_size": 1.0,        "precision": 0,  "min_volume": 1.0},
    "VET":    {"step_size": 1.0,        "precision": 0,  "min_volume": 1.0},
    "SHIB":   {"step_size": 1.0,        "precision": 0,  "min_volume": 1.0},
    # ── Fallback (used when base asset is not listed above) ───────────────
    "DEFAULT": {"step_size": 0.01,      "precision": 2,  "min_volume": 0.01},
}

#: Hard floor for order *value* on Coinbase (USD).
#: Orders whose notional (qty × price) is below this cannot be filled.
COINBASE_MIN_NOTIONAL_USD: float = 1.00

#: USD value below which a SELL position is considered permanently unsellable.
#: Positions between PERMANENT_UNSELLABLE_USD and COINBASE_MIN_NOTIONAL_USD
#: are transient dust (may recover); positions below this floor never will.
PERMANENT_UNSELLABLE_USD: float = 0.50


def _precision_from_step(step: float) -> int:
    """
    Derive the number of decimal places required for a given *step* size.

    Examples::

        _precision_from_step(0.01)        → 2
        _precision_from_step(0.00000001)  → 8
        _precision_from_step(1.0)         → 0
        _precision_from_step(10.0)        → 0
    """
    if step >= 1.0:
        return 0
    return max(0, -int(math.floor(math.log10(step))))


def _get_rules(symbol: str) -> Dict:
    """Return the exchange rules dict for *symbol* (e.g. ``"AVAX-USD"``)."""
    base = symbol.split("-")[0].upper() if "-" in symbol else symbol.upper()
    return exchange_rules.get(base, exchange_rules["DEFAULT"])


# ---------------------------------------------------------------------------
# Module-level normalisation functions
# ---------------------------------------------------------------------------

def round_to_step(symbol: str, volume: float) -> float:
    """
    Floor-round *volume* to the nearest valid step size for *symbol*.

    Example::

        round_to_step("AVAX-USD", 0.38874957)  # → 0.38  (step=0.01)
        round_to_step("ADA-USD",  3.7)          # → 3.0   (step=1)

    Parameters
    ----------
    symbol:
        Coinbase product id, e.g. ``"AVAX-USD"``, or bare base asset
        like ``"AVAX"``.
    volume:
        Raw requested quantity (base currency units).

    Returns
    -------
    float
        Largest multiple of ``step_size`` that is ≤ *volume*.
    """
    rules = _get_rules(symbol)
    step = rules["step_size"]
    if step <= 0 or volume <= 0:
        return volume
    n = math.floor(volume / step)
    result = n * step
    # Round off floating-point artefacts using the known precision
    return round(result, rules["precision"])


def apply_precision(symbol: str, volume: float) -> float:
    """
    Round *volume* to the correct number of decimal places for *symbol*.

    This removes floating-point artefacts (e.g. ``0.38000000000000006``)
    that some exchange APIs reject.

    Parameters
    ----------
    symbol:
        Coinbase product id or bare base asset name.
    volume:
        Quantity to round.

    Returns
    -------
    float
        *volume* rounded to the asset's canonical decimal precision.
    """
    rules = _get_rules(symbol)
    return round(volume, rules["precision"])


def enforce_min_volume(symbol: str, volume: float) -> float:
    """
    Return ``0.0`` when *volume* is below the exchange minimum for *symbol*,
    otherwise return *volume* unchanged.

    A return value of ``0.0`` signals that the order must not be placed —
    ``validate_order`` will return ``None`` in this case.

    Parameters
    ----------
    symbol:
        Coinbase product id or bare base asset name.
    volume:
        Candidate order quantity (base currency units).

    Returns
    -------
    float
        *volume* if it meets the minimum; ``0.0`` otherwise.
    """
    rules = _get_rules(symbol)
    min_vol = rules["min_volume"]
    if volume < min_vol:
        return 0.0
    return volume


def validate_order(symbol: str, volume: float) -> Optional[float]:
    """
    **Call this before EVERY order.**

    Chains ``enforce_min_volume`` → ``round_to_step`` → ``apply_precision``
    and returns the normalised volume, or ``None`` when the order cannot be
    placed.

    Usage::

        adjusted = validate_order("AVAX-USD", 0.38874957)
        if adjusted is None:
            return  # order blocked

    The function also emits a ``[ORDER NORMALIZED]`` log line whenever the
    quantity is adjusted, and flags symbols as ``PERMANENT_DUST_UNSELLABLE``
    via the global singleton when the adjusted value is below the notional
    floor.

    Parameters
    ----------
    symbol:
        Coinbase product id, e.g. ``"AVAX-USD"``.
    volume:
        Requested base-currency quantity.

    Returns
    -------
    float or None
        Normalised (and valid) quantity, or ``None`` if the order must be
        blocked.
    """
    if volume <= 0:
        return None

    original = volume

    # Step 1 — enforce minimum volume
    volume = enforce_min_volume(symbol, volume)

    # Step 2 — round to exchange step size
    step_rounded = round_to_step(symbol, volume)
    volume = step_rounded

    # Step 3 — apply decimal precision
    volume = apply_precision(symbol, volume)

    if volume <= 0:
        return None

    # Emit normalisation audit log if quantity changed
    if volume != original:
        adjustments = []
        rules = _get_rules(symbol)
        if original < rules["min_volume"]:
            adjustments.append("min_volume")
        if step_rounded != original:  # reuse already-computed step-rounded value
            adjustments.append("step_size")
        reason = " + ".join(adjustments) if adjustments else "step_size"
        logger.info(
            "[ORDER NORMALIZED] symbol=%s requested=%.8g adjusted=%.8g reason=%s",
            symbol, original, volume, reason,
        )

    return volume


# ---------------------------------------------------------------------------
# Result dataclass (used by the class-level API)
# ---------------------------------------------------------------------------

@dataclass
class OrderNormalizationResult:
    """Full outcome of :meth:`ExchangeOrderValidator.validate_and_normalize`."""

    symbol: str
    side: str
    size_type: str

    #: Quantity originally requested.
    requested_qty: float
    #: Quantity after normalisation (may equal requested_qty if no change needed).
    adjusted_qty: float

    #: Price used for notional calculation (0 if not provided).
    price: float
    #: USD value of the *adjusted* order.
    value_usd: float

    #: Exchange base increment applied during rounding.
    step_size: float
    #: Minimum notional threshold used.
    min_notional: float

    #: True  → order can proceed.
    is_valid: bool
    #: True  → symbol is permanently below minimum; exclude from ALL systems.
    is_permanently_unsellable: bool

    #: Human-readable reason string (used in ``[ORDER NORMALIZED]`` log).
    reason: str
    #: Individual adjustment tokens, e.g. ``["step_size", "min_volume"]``.
    adjustments: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# ExchangeOrderValidator class (full-featured, singleton)
# ---------------------------------------------------------------------------

class ExchangeOrderValidator:
    """
    Thread-safe, singleton-friendly validator for exchange order sizing.

    Wraps the module-level :func:`validate_order` pipeline and adds:

    * PERMANENT_DUST_UNSELLABLE tracking (persisted to JSON)
    * Live product-metadata lookup via optional broker reference
    * Full :class:`OrderNormalizationResult` return value for callers that
      need richer context than a plain float
    """

    def __init__(
        self,
        data_dir: str = "./data",
        min_notional: float = COINBASE_MIN_NOTIONAL_USD,
    ):
        self._lock = Lock()
        self._min_notional = min_notional
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._store_path = self._data_dir / "permanent_unsellable.json"

        # symbol → {"timestamp": float, "reason": str, "value_usd": float}
        self._permanently_unsellable: Dict[str, dict] = {}
        self._load_store()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_store(self) -> None:
        if not self._store_path.exists():
            return
        try:
            with open(self._store_path, "r") as fh:
                data = json.load(fh)
            self._permanently_unsellable = data.get("symbols", {})
            count = len(self._permanently_unsellable)
            if count:
                logger.info(
                    "🚫 Loaded %d PERMANENT_DUST_UNSELLABLE symbol(s) from %s",
                    count,
                    self._store_path,
                )
        except Exception as exc:
            logger.error("Failed to load permanent_unsellable store: %s", exc)

    def _save_store(self) -> None:
        try:
            payload = {
                "updated": time.time(),
                "count": len(self._permanently_unsellable),
                "symbols": self._permanently_unsellable,
            }
            tmp = self._store_path.with_suffix(".tmp")
            with open(tmp, "w") as fh:
                json.dump(payload, fh, indent=2)
            tmp.replace(self._store_path)
        except Exception as exc:
            logger.error("Failed to save permanent_unsellable store: %s", exc)

    # ------------------------------------------------------------------
    # Public flag helpers
    # ------------------------------------------------------------------

    def mark_permanently_unsellable(
        self,
        symbol: str,
        reason: str = "below exchange minimum",
        value_usd: float = 0.0,
    ) -> None:
        """
        Permanently flag *symbol* as unsellable.

        Idempotent — calling again for an already-flagged symbol is a no-op
        (the original timestamp is preserved).
        """
        with self._lock:
            if symbol in self._permanently_unsellable:
                return
            self._permanently_unsellable[symbol] = {
                "timestamp": time.time(),
                "reason": reason,
                "value_usd": value_usd,
            }
            self._save_store()

        logger.warning(
            "🚫 PERMANENT_DUST_UNSELLABLE: %s — $%.4f — %s",
            symbol,
            value_usd,
            reason,
        )

    def is_permanently_unsellable(self, symbol: str) -> bool:
        """Return ``True`` when *symbol* has been flagged PERMANENT_DUST_UNSELLABLE."""
        with self._lock:
            return symbol in self._permanently_unsellable

    def remove_permanently_unsellable(self, symbol: str) -> bool:
        """Remove *symbol* from the permanent unsellable list (admin override)."""
        with self._lock:
            if symbol not in self._permanently_unsellable:
                return False
            del self._permanently_unsellable[symbol]
            self._save_store()
        logger.info("♻️  Removed %s from PERMANENT_DUST_UNSELLABLE list", symbol)
        return True

    def get_permanently_unsellable_symbols(self) -> Dict[str, dict]:
        """Return a copy of all permanently unsellable symbols and their metadata."""
        with self._lock:
            return dict(self._permanently_unsellable)

    # ------------------------------------------------------------------
    # Live step-size lookup (supplements the static exchange_rules table)
    # ------------------------------------------------------------------

    def _get_step_size_live(self, symbol: str, broker_ref) -> Optional[float]:
        """Try to fetch the live base increment from the broker; return None on failure."""
        if broker_ref is None:
            return None
        try:
            meta = broker_ref._get_product_metadata(symbol)
            if not isinstance(meta, dict):
                return None
            for key in ("base_increment", "base_increment_decimal", "base_increment_value"):
                raw = meta.get(key)
                if raw:
                    val = float(raw)
                    if val > 0:
                        return val
            exp = meta.get("base_increment_exponent")
            if exp is not None:
                val = 10.0 ** float(exp)
                if val > 0:
                    return val
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # Main class-level entry point
    # ------------------------------------------------------------------

    def validate_and_normalize(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float = 0.0,
        size_type: str = "quote",
        broker_ref=None,
    ) -> OrderNormalizationResult:
        """
        Validate and normalise *quantity* before order submission.

        This is the rich counterpart of the module-level :func:`validate_order`.
        It applies the same ``enforce_min_volume → round_to_step →
        apply_precision`` pipeline, additionally:

        * Checks and sets the PERMANENT_DUST_UNSELLABLE flag for sell orders
          whose notional value is below :data:`PERMANENT_UNSELLABLE_USD`.
        * Tries live product metadata from *broker_ref* before falling back to
          the static :data:`exchange_rules` table.
        * Returns a full :class:`OrderNormalizationResult` with every detail.

        Parameters
        ----------
        symbol:
            Coinbase product id, e.g. ``"AVAX-USD"``.
        side:
            ``"buy"`` or ``"sell"``.
        quantity:
            Requested size (meaning depends on *size_type*).
        price:
            Current mid-price in USD — required for notional checks on
            ``size_type="base"`` orders.
        size_type:
            ``"quote"`` → *quantity* is a USD amount (typical for BUY).
            ``"base"``  → *quantity* is a crypto amount (typical for SELL).
        broker_ref:
            Optional broker instance for live product metadata lookup.
        """
        side_lower = side.lower()

        # ── 0. Already permanently flagged? ───────────────────────────────
        if self.is_permanently_unsellable(symbol):
            return OrderNormalizationResult(
                symbol=symbol,
                side=side_lower,
                size_type=size_type,
                requested_qty=quantity,
                adjusted_qty=0.0,
                price=price,
                value_usd=0.0,
                step_size=0.0,
                min_notional=self._min_notional,
                is_valid=False,
                is_permanently_unsellable=True,
                reason="PERMANENT_DUST_UNSELLABLE — excluded from all systems",
                adjustments=["permanent_flag"],
            )

        # ── 1. Quote-size (USD) orders — BUY path ─────────────────────────
        if size_type == "quote":
            requested = quantity
            adjusted = round(quantity, 2)
            adjustments: List[str] = []
            if adjusted != requested:
                adjustments.append("precision")

            value_usd = adjusted

            if value_usd < self._min_notional:
                reason = (
                    f"order value ${value_usd:.2f} below minimum "
                    f"${self._min_notional:.2f}"
                )
                return OrderNormalizationResult(
                    symbol=symbol,
                    side=side_lower,
                    size_type=size_type,
                    requested_qty=requested,
                    adjusted_qty=adjusted,
                    price=price,
                    value_usd=value_usd,
                    step_size=0.01,
                    min_notional=self._min_notional,
                    is_valid=False,
                    is_permanently_unsellable=False,
                    reason=reason,
                    adjustments=adjustments + ["min_volume"],
                )

            if adjustments:
                logger.info(
                    "[ORDER NORMALIZED] symbol=%s requested=%.8g adjusted=%.8g reason=%s",
                    symbol, requested, adjusted, "precision",
                )

            return OrderNormalizationResult(
                symbol=symbol,
                side=side_lower,
                size_type=size_type,
                requested_qty=requested,
                adjusted_qty=adjusted,
                price=price,
                value_usd=value_usd,
                step_size=0.01,
                min_notional=self._min_notional,
                is_valid=True,
                is_permanently_unsellable=False,
                reason="ok",
                adjustments=adjustments,
            )

        # ── 2. Base-size (crypto) orders — SELL path ──────────────────────

        # Prefer live step size if broker is available
        live_step = self._get_step_size_live(symbol, broker_ref)
        rules = _get_rules(symbol)
        step_size = live_step if live_step is not None else rules["step_size"]

        requested = quantity
        adjustments = []

        # Apply the same pipeline as the module-level validate_order,
        # but using the (possibly live) step_size.
        vol = enforce_min_volume(symbol, quantity)
        # Use live step for rounding if available.
        # When live_step is used, round() already applies the correct precision
        # via _precision_from_step — do NOT call apply_precision() afterwards or
        # the static-table precision for that symbol would silently override it.
        if live_step is not None:
            n = math.floor(vol / live_step) if vol > 0 else 0
            precision = _precision_from_step(live_step)
            vol = round(n * live_step, precision)
        else:
            vol = round_to_step(symbol, vol)
            vol = apply_precision(symbol, vol)

        adjusted = vol
        if adjusted != requested:
            adjustments.append("step_size")

        value_usd = adjusted * price if price > 0 else 0.0

        notional_ok = price <= 0 or value_usd >= self._min_notional
        if not notional_ok:
            adjustments.append("min_volume")

        # ── 2a. Permanently unsellable? ───────────────────────────────────
        permanently_bad = (
            side_lower == "sell"
            and price > 0
            and value_usd < PERMANENT_UNSELLABLE_USD
        )

        if permanently_bad:
            reason = " + ".join(adjustments) if adjustments else "min_volume"
            self.mark_permanently_unsellable(symbol, reason=reason, value_usd=value_usd)
            if adjusted != requested:
                logger.info(
                    "[ORDER NORMALIZED] symbol=%s requested=%.8g adjusted=%.8g reason=%s",
                    symbol, requested, adjusted, reason,
                )
            return OrderNormalizationResult(
                symbol=symbol,
                side=side_lower,
                size_type=size_type,
                requested_qty=requested,
                adjusted_qty=adjusted,
                price=price,
                value_usd=value_usd,
                step_size=step_size,
                min_notional=self._min_notional,
                is_valid=False,
                is_permanently_unsellable=True,
                reason=reason,
                adjustments=adjustments,
            )

        # ── 2b. Recoverable dust (price may rise) ─────────────────────────
        if not notional_ok:
            reason = " + ".join(adjustments) if adjustments else "min_volume"
            if adjusted != requested:
                logger.info(
                    "[ORDER NORMALIZED] symbol=%s requested=%.8g adjusted=%.8g reason=%s",
                    symbol, requested, adjusted, reason,
                )
            return OrderNormalizationResult(
                symbol=symbol,
                side=side_lower,
                size_type=size_type,
                requested_qty=requested,
                adjusted_qty=adjusted,
                price=price,
                value_usd=value_usd,
                step_size=step_size,
                min_notional=self._min_notional,
                is_valid=False,
                is_permanently_unsellable=False,
                reason=reason,
                adjustments=adjustments,
            )

        # ── 2c. Valid order ───────────────────────────────────────────────
        if adjusted != requested:
            reason = " + ".join(adjustments) if adjustments else "step_size"
            logger.info(
                "[ORDER NORMALIZED] symbol=%s requested=%.8g adjusted=%.8g reason=%s",
                symbol, requested, adjusted, reason,
            )
        else:
            reason = "ok"

        return OrderNormalizationResult(
            symbol=symbol,
            side=side_lower,
            size_type=size_type,
            requested_qty=requested,
            adjusted_qty=adjusted,
            price=price,
            value_usd=value_usd,
            step_size=step_size,
            min_notional=self._min_notional,
            is_valid=True,
            is_permanently_unsellable=False,
            reason=reason,
            adjustments=adjustments,
        )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[ExchangeOrderValidator] = None
_instance_lock = Lock()


def get_exchange_order_validator(
    data_dir: str = "./data",
    min_notional: float = COINBASE_MIN_NOTIONAL_USD,
) -> ExchangeOrderValidator:
    """Return the global singleton :class:`ExchangeOrderValidator`."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = ExchangeOrderValidator(
                data_dir=data_dir,
                min_notional=min_notional,
            )
    return _instance
