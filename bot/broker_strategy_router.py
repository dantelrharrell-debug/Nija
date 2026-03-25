"""
NIJA Broker Strategy Router
================================

Central routing layer that selects the correct broker-specific optimizer
and enforces per-broker trade-filtering rules based on a rich BROKER_PROFILES
dictionary.

Architecture
------------
::

    BrokerStrategyRouter.get_optimizer(broker_name)
        │
        ├─ "kraken"   → KrakenParamsOptimizer   (scalp, fee=0.62%, min_move=0.8%)
        ├─ "coinbase" → CoinbaseParamsOptimizer  (swing, fee=1.40%, min_move=1.5%)
        ├─ "binance"  → BinanceParamsOptimizer   (scalp, fee=0.28%, min_move=0.5%)
        └─ default    → falls back to KrakenParamsOptimizer

    BrokerStrategyRouter.should_skip_trade(expected_move_pct, broker_name)
        │
        └─ True when expected_move_pct < BROKER_PROFILES[broker]["min_move"]
           Prevents:
             • Coinbase overtrading on marginal moves (1.5 % threshold)
             • Kraken undertrading on genuine but small moves (0.8 % threshold)
             • Binance missing fast scalps (0.5 % threshold)

BROKER_PROFILES
---------------
Each profile contains:
  fee       – estimated round-trip trading cost as a fraction (e.g. 0.0062)
  style     – preferred trading style ("scalp", "swing")
  min_move  – minimum expected price move to enter a trade (fraction, e.g. 0.008)
  speed     – suggested scan/trade frequency ("fast", "medium", "slow")
  confidence_boost – added to the raw confidence signal for this broker
    (positive = easier to qualify, negative = harder)

Usage
-----
::

    from bot.broker_strategy_router import get_broker_strategy_router

    router = get_broker_strategy_router()

    # Get the right optimizer for the active broker
    optimizer = router.get_optimizer("kraken")
    optimizer.update_regime("bull", confidence=0.8)
    params = optimizer.get_params()

    # Before placing a trade, check the expected move
    if router.should_skip_trade(expected_move_pct=0.006, broker_name="coinbase"):
        return  # Skip — move too small for Coinbase fees

    # Update all optimizers with the current regime at once
    router.broadcast_regime("bull", confidence=0.75)

    # Record a completed trade to the appropriate optimizer
    router.record_trade(broker_name="kraken", pnl_usd=1.20, is_win=True)

Author: NIJA Trading Systems
Version: 1.0
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional, Union

logger = logging.getLogger("nija.broker_strategy_router")

# ---------------------------------------------------------------------------
# BROKER_PROFILES — single source of truth for per-broker characteristics
# ---------------------------------------------------------------------------

BROKER_PROFILES: Dict[str, Dict[str, Any]] = {
    "kraken": {
        # Round-trip trading cost (taker × 2 + spread): 0.26% × 2 + 0.10% = 0.62%
        "fee": 0.0062,
        # Low fees enable fast scalp trades
        "style": "scalp",
        # Minimum expected gross price move to justify entry (must clear fees + buffer)
        # 0.8% = 0.62% round-trip + 0.18% net-profit buffer
        "min_move": 0.008,
        # Kraken offers good liquidity and fast execution — medium scan cadence
        "speed": "medium",
        # Slightly easier confidence gate — low fees make borderline trades viable
        "confidence_boost": 0.02,
    },
    "coinbase": {
        # Round-trip trading cost (taker × 2 + spread): 0.60% × 2 + 0.20% = 1.40%
        "fee": 0.0140,
        # High fees demand wide swings — only swing-style moves clear fee overhead
        "style": "swing",
        # Minimum expected gross price move: 1.5% = 1.4% fees + 0.1% net-profit floor
        "min_move": 0.015,
        # Coinbase fee pressure → trade less frequently, wait for quality setups
        "speed": "slow",
        # Harder confidence gate — high fees demand only the best signals
        "confidence_boost": -0.05,
    },
    "binance": {
        # Round-trip trading cost (taker × 2 + spread): 0.10% × 2 + 0.08% = 0.28%
        "fee": 0.0028,
        # Very low fees make tight scalps highly profitable
        "style": "scalp",
        # Minimum expected gross price move: 0.5% = 0.28% fees + 0.22% net-profit floor
        "min_move": 0.005,
        # Binance has best-in-class liquidity — aggressive fast scanning
        "speed": "fast",
        # Easiest confidence gate — very low fees make marginal trades net-positive
        "confidence_boost": 0.05,
    },
    "alpaca": {
        # Round-trip trading cost: ~0.30% for crypto (0.15% per side)
        "fee": 0.0030,
        # Low fees → scalp viable but Alpaca skews toward equities/swing
        "style": "swing",
        # Minimum expected gross price move
        "min_move": 0.006,
        "speed": "medium",
        "confidence_boost": 0.00,
    },
    "okx": {
        # Round-trip: ~0.20% fees (0.10% taker × 2) + ~0.08% spread ≈ 0.28% effective
        # Using 0.0020 as fee component; effective round-trip close to Binance
        "fee": 0.0020,
        "style": "scalp",
        "min_move": 0.004,
        "speed": "fast",
        "confidence_boost": 0.03,
    },
    # Conservative fallback for any unknown exchange
    "default": {
        "fee": 0.0140,   # Use most expensive estimate to be safe
        "style": "swing",
        "min_move": 0.015,
        "speed": "slow",
        "confidence_boost": -0.05,
    },
}

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_kraken_optimizer():
    """Lazy-import the Kraken optimizer."""
    try:
        from bot.kraken_params_optimizer import get_kraken_params_optimizer
        return get_kraken_params_optimizer()
    except ImportError:
        pass
    try:
        from kraken_params_optimizer import get_kraken_params_optimizer
        return get_kraken_params_optimizer()
    except ImportError:
        logger.warning("KrakenParamsOptimizer not available — Kraken routing degraded")
        return None


def _load_coinbase_optimizer():
    """Lazy-import the Coinbase optimizer."""
    try:
        from bot.coinbase_params_optimizer import get_coinbase_params_optimizer
        return get_coinbase_params_optimizer()
    except ImportError:
        pass
    try:
        from coinbase_params_optimizer import get_coinbase_params_optimizer
        return get_coinbase_params_optimizer()
    except ImportError:
        logger.warning("CoinbaseParamsOptimizer not available — Coinbase routing degraded")
        return None


def _load_binance_optimizer():
    """Lazy-import the Binance optimizer."""
    try:
        from bot.binance_params_optimizer import get_binance_params_optimizer
        return get_binance_params_optimizer()
    except ImportError:
        pass
    try:
        from binance_params_optimizer import get_binance_params_optimizer
        return get_binance_params_optimizer()
    except ImportError:
        logger.warning("BinanceParamsOptimizer not available — Binance routing degraded")
        return None


# ---------------------------------------------------------------------------
# BrokerStrategyRouter
# ---------------------------------------------------------------------------


class BrokerStrategyRouter:
    """
    Central router that maps broker names to their dedicated parameter
    optimizers and enforces per-broker minimum-move trade filters.

    The router is the single place where new brokers should be registered:
    1. Add an entry to :data:`BROKER_PROFILES`.
    2. Add a loader branch in :meth:`_load_optimizers`.
    3. Done — all callers using :func:`get_broker_strategy_router` benefit
       immediately.

    Thread-safe singleton via :func:`get_broker_strategy_router`.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()

        # Lazy-loaded optimizer instances keyed by broker name
        self._optimizers: Dict[str, Any] = {}

        # Load all available optimizers at construction time
        self._load_optimizers()

        logger.info(
            "✅ BrokerStrategyRouter initialized — profiles: %s",
            ", ".join(BROKER_PROFILES.keys()),
        )
        for name, profile in BROKER_PROFILES.items():
            if name == "default":
                continue
            logger.info(
                "   %-12s fee=%.2f%%  style=%-6s  min_move=%.1f%%  speed=%s",
                name,
                profile["fee"] * 100,
                profile["style"],
                profile["min_move"] * 100,
                profile["speed"],
            )

    # ------------------------------------------------------------------
    # Public API — optimizer access
    # ------------------------------------------------------------------

    def get_optimizer(self, broker_name: str) -> Optional[Any]:
        """
        Return the optimizer instance for *broker_name*.

        Falls back to the Kraken optimizer when no dedicated optimizer
        exists for the requested broker (Kraken has the most permissive
        fee structure among crypto exchanges tracked here).

        Args:
            broker_name: Exchange name, e.g. ``"coinbase"``, ``"kraken"``.

        Returns:
            Optimizer instance, or ``None`` if no optimizer could be loaded.
        """
        key = (broker_name or "").lower()
        with self._lock:
            optimizer = self._optimizers.get(key)
            if optimizer is None:
                # Fall back to kraken optimizer for unknown brokers
                optimizer = self._optimizers.get("kraken")
                if optimizer is not None:
                    logger.debug(
                        "BrokerStrategyRouter: no optimizer for '%s' — using kraken fallback",
                        broker_name,
                    )
            return optimizer

    def get_profile(self, broker_name: str) -> Dict[str, Any]:
        """
        Return the BROKER_PROFILES entry for *broker_name*.

        Falls back to ``"default"`` for unknown brokers.

        Args:
            broker_name: Exchange name.

        Returns:
            Profile dict with keys: fee, style, min_move, speed,
            confidence_boost.
        """
        key = (broker_name or "").lower()
        return BROKER_PROFILES.get(key, BROKER_PROFILES["default"])

    # ------------------------------------------------------------------
    # Public API — trade filtering
    # ------------------------------------------------------------------

    def should_skip_trade(
        self,
        expected_move_pct: float,
        broker_name: str,
    ) -> bool:
        """
        Return ``True`` when the expected price move is too small to clear
        the broker's fee structure and deliver a meaningful net profit.

        This is the core dynamic trade filter described in the architecture
        document.  It prevents:
          • Coinbase overtrading on marginal 0.5% moves (fees ~1.4%)
          • Binance undertrading by skipping profitable 0.6% scalps

        Args:
            expected_move_pct: Estimated gross price move as a fraction
                               (e.g. ``0.012`` for 1.2%).
            broker_name: Active exchange name (e.g. ``"coinbase"``).

        Returns:
            ``True`` → skip the trade; ``False`` → proceed.

        Example::

            if router.should_skip_trade(0.008, "coinbase"):
                return  # 0.8% move won't clear Coinbase's 1.5% threshold
        """
        profile = self.get_profile(broker_name)
        min_move = profile["min_move"]
        if expected_move_pct < min_move:
            logger.debug(
                "🚫 skip_trade: broker=%s expected_move=%.2f%% < min_move=%.2f%%",
                broker_name,
                expected_move_pct * 100,
                min_move * 100,
            )
            return True
        return False

    def apply_confidence_boost(
        self,
        raw_confidence: float,
        broker_name: str,
    ) -> float:
        """
        Adjust a raw confidence score by the broker-specific boost/penalty.

        Coinbase penalises borderline signals (−0.05) to reduce overtrading.
        Binance relaxes the gate (+0.05) to capture fast low-fee scalps.

        Args:
            raw_confidence: Original confidence in [0.0, 1.0].
            broker_name: Active exchange name.

        Returns:
            Adjusted confidence, clamped to [0.0, 1.0].
        """
        profile = self.get_profile(broker_name)
        boost = profile.get("confidence_boost", 0.0)
        return max(0.0, min(1.0, raw_confidence + boost))

    # ------------------------------------------------------------------
    # Public API — broadcast helpers
    # ------------------------------------------------------------------

    def broadcast_regime(self, regime: str, confidence: float = 0.5) -> None:
        """
        Propagate a market regime update to *all* loaded optimizers at once.

        Call this once per scan cycle after the market-regime engine runs so
        that every broker optimizer reflects the latest regime classification.

        Args:
            regime: ``"bull"``, ``"chop"``, ``"crash"``, or ``"normal"``.
            confidence: Regime detector confidence in [0.0, 1.0].
        """
        with self._lock:
            optimizers = dict(self._optimizers)  # snapshot under lock

        for name, opt in optimizers.items():
            if opt is not None and hasattr(opt, "update_regime"):
                try:
                    opt.update_regime(regime, confidence)
                except Exception as exc:
                    logger.warning(
                        "BrokerStrategyRouter: regime broadcast failed for %s: %s",
                        name, exc,
                    )

        logger.debug(
            "BrokerStrategyRouter: regime '%s' (conf=%.2f) broadcast to %d optimizers",
            regime, confidence, len(optimizers),
        )

    def record_trade(
        self,
        broker_name: str,
        pnl_usd: float,
        is_win: bool,
    ) -> None:
        """
        Forward a completed trade result to the appropriate broker optimizer.

        Args:
            broker_name: Exchange the trade executed on.
            pnl_usd: Realised profit/loss in USD.
            is_win: ``True`` if the trade closed above break-even.
        """
        optimizer = self.get_optimizer(broker_name)
        if optimizer is not None and hasattr(optimizer, "record_trade"):
            try:
                optimizer.record_trade(pnl_usd=pnl_usd, is_win=is_win)
            except Exception as exc:
                logger.warning(
                    "BrokerStrategyRouter: record_trade failed for %s: %s",
                    broker_name, exc,
                )

    def get_report(self, broker_name: str) -> Dict:
        """
        Return the performance report from *broker_name*'s optimizer.

        Returns an empty dict if no optimizer is available.

        Args:
            broker_name: Exchange name.
        """
        optimizer = self.get_optimizer(broker_name)
        if optimizer is not None and hasattr(optimizer, "get_report"):
            try:
                return optimizer.get_report()
            except Exception as exc:
                logger.warning(
                    "BrokerStrategyRouter: get_report failed for %s: %s",
                    broker_name, exc,
                )
        return {}

    def get_params(self, broker_name: str) -> Optional[Any]:
        """
        Return the current optimized parameters for *broker_name*.

        This is the primary method callers should use to get profit targets,
        stop losses, and position-size multipliers calibrated for the broker.

        Args:
            broker_name: Exchange name (e.g. ``"kraken"``).

        Returns:
            A typed params dataclass (e.g. :class:`KrakenOptParams`),
            or ``None`` if no optimizer is available.
        """
        optimizer = self.get_optimizer(broker_name)
        if optimizer is not None and hasattr(optimizer, "get_params"):
            try:
                return optimizer.get_params()
            except Exception as exc:
                logger.warning(
                    "BrokerStrategyRouter: get_params failed for %s: %s",
                    broker_name, exc,
                )
        return None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_optimizers(self) -> None:
        """Load all broker-specific optimizer singletons."""
        kraken_opt = _load_kraken_optimizer()
        if kraken_opt is not None:
            self._optimizers["kraken"] = kraken_opt

        coinbase_opt = _load_coinbase_optimizer()
        if coinbase_opt is not None:
            self._optimizers["coinbase"] = coinbase_opt

        binance_opt = _load_binance_optimizer()
        if binance_opt is not None:
            self._optimizers["binance"] = binance_opt

        loaded = [k for k, v in self._optimizers.items() if v is not None]
        logger.info(
            "BrokerStrategyRouter: loaded optimizers — %s",
            ", ".join(loaded) if loaded else "none",
        )


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_router: Optional[BrokerStrategyRouter] = None
_router_lock = threading.Lock()


def get_broker_strategy_router() -> BrokerStrategyRouter:
    """
    Return the process-wide :class:`BrokerStrategyRouter` singleton.

    Thread-safe — safe to call from multiple threads simultaneously.
    """
    global _router
    if _router is None:
        with _router_lock:
            if _router is None:
                _router = BrokerStrategyRouter()
    return _router


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    "BROKER_PROFILES",
    "BrokerStrategyRouter",
    "get_broker_strategy_router",
]
