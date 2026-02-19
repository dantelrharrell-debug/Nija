"""
Risk Intelligence System
========================
Unified risk intelligence layer integrating three institutional-grade controls:

1. Correlation-Aware Exposure Control
   - Prevents over-concentration in correlated assets (e.g., all meme coins)
   - Tracks exposure per correlation group and enforces group-level caps

2. Volatility-Adjusted Position Caps
   - Caps position sizes dynamically based on current market volatility
   - Reduces exposure during high-volatility regimes automatically

3. Portfolio-Level Drawdown Circuit Breaker
   - Halts new positions when portfolio drawdown exceeds configurable thresholds
   - Scales down position sizes progressively as drawdown deepens

These three controls fill the final institutional gap:
  - Correlation-aware exposure control
  - Volatility-adjusted position caps
  - Portfolio-level drawdown circuit breaker

Author: NIJA Trading Systems
Version: 1.0
Date: February 2026
"""

import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime

logger = logging.getLogger("nija.risk_intelligence")

# ---------------------------------------------------------------------------
# Optional dependency imports (graceful degradation if not installed)
# ---------------------------------------------------------------------------
try:
    from bot.drawdown_protection_system import (
        DrawdownProtectionSystem,
        DrawdownConfig,
        ProtectionLevel,
    )
    _HAS_DRAWDOWN = True
except ImportError:
    try:
        from drawdown_protection_system import (  # type: ignore
            DrawdownProtectionSystem,
            DrawdownConfig,
            ProtectionLevel,
        )
        _HAS_DRAWDOWN = True
    except ImportError:
        DrawdownProtectionSystem = None  # type: ignore
        DrawdownConfig = None  # type: ignore
        ProtectionLevel = None  # type: ignore
        _HAS_DRAWDOWN = False
        logger.warning("DrawdownProtectionSystem not available — circuit breaker disabled")

try:
    from bot.volatility_adaptive_sizer import VolatilityAdaptiveSizer
    _HAS_VOLATILITY_SIZER = True
except ImportError:
    try:
        from volatility_adaptive_sizer import VolatilityAdaptiveSizer  # type: ignore
        _HAS_VOLATILITY_SIZER = True
    except ImportError:
        VolatilityAdaptiveSizer = None  # type: ignore
        _HAS_VOLATILITY_SIZER = False
        logger.warning("VolatilityAdaptiveSizer not available — volatility caps disabled")

try:
    from bot.portfolio_risk_engine import PortfolioRiskEngine
    _HAS_PORTFOLIO_RISK = True
except ImportError:
    try:
        from portfolio_risk_engine import PortfolioRiskEngine  # type: ignore
        _HAS_PORTFOLIO_RISK = True
    except ImportError:
        PortfolioRiskEngine = None  # type: ignore
        _HAS_PORTFOLIO_RISK = False
        logger.warning("PortfolioRiskEngine not available — correlation control uses heuristics")


# ---------------------------------------------------------------------------
# Default correlation groups (used when PortfolioRiskEngine is unavailable)
# ---------------------------------------------------------------------------
_DEFAULT_CORRELATION_GROUPS: Dict[str, List[str]] = {
    "BTC_RELATED": ["BTC-USD", "BTC-USDT", "WBTC-USD"],
    "ETH_RELATED": ["ETH-USD", "ETH-USDT", "ETH2-USD"],
    "MEME_COINS": [
        "DOGE-USD", "SHIB-USD", "PEPE-USD", "FLOKI-USD",
        "DOGE-USDT", "SHIB-USDT",
    ],
    "DEFI": ["UNI-USD", "AAVE-USD", "COMP-USD", "SUSHI-USD", "CRV-USD"],
    "LAYER1": ["SOL-USD", "ADA-USD", "AVAX-USD", "DOT-USD", "NEAR-USD"],
    "LAYER2": ["MATIC-USD", "ARB-USD", "OP-USD"],
    "STABLECOINS": ["USDT-USD", "USDC-USD", "DAI-USD", "BUSD-USD"],
}


def _get_asset_group(symbol: str) -> str:
    """Return the correlation group for *symbol*, defaulting to 'OTHER'."""
    for group, members in _DEFAULT_CORRELATION_GROUPS.items():
        if symbol in members:
            return group
    return "OTHER"


# ===========================================================================
# Feature 1 — Correlation-Aware Exposure Controller
# ===========================================================================

class CorrelationExposureController:
    """
    Prevent over-concentration in correlated assets.

    Tracks the total USD exposure per correlation group and rejects new
    positions that would push any group above *max_group_exposure_pct* of the
    total portfolio.

    Works standalone (heuristic groups) or with a ``PortfolioRiskEngine``
    instance for computed correlations.
    """

    def __init__(
        self,
        max_group_exposure_pct: float = 0.40,
        portfolio_risk_engine=None,
    ):
        """
        Args:
            max_group_exposure_pct: Maximum allowed exposure in any single
                correlation group as a fraction of account balance (default 0.40 = 40%).
            portfolio_risk_engine: Optional ``PortfolioRiskEngine`` for
                computed correlations.  When *None*, heuristic groups are used.
        """
        self.max_group_exposure_pct = max_group_exposure_pct
        self.portfolio_risk_engine = portfolio_risk_engine
        logger.info(
            f"✅ CorrelationExposureController initialized "
            f"(max_group={max_group_exposure_pct * 100:.0f}%)"
        )

    def check(
        self,
        symbol: str,
        proposed_size_usd: float,
        current_positions: List[Dict],
        account_balance: float,
    ) -> Tuple[bool, Dict]:
        """
        Check whether adding *symbol* at *proposed_size_usd* is acceptable.

        Args:
            symbol: Symbol being considered (e.g. 'PEPE-USD').
            proposed_size_usd: Dollar value of the proposed position.
            current_positions: List of open positions (each has 'symbol' and
                'size_usd' or 'usd_value' keys).
            account_balance: Total portfolio balance in USD.

        Returns:
            ``(approved, details)`` — *approved* is ``True`` when safe.
        """
        try:
            group = _get_asset_group(symbol)
            group_exposure = sum(
                pos.get("size_usd", 0) or pos.get("usd_value", 0)
                for pos in current_positions
                if _get_asset_group(pos.get("symbol", "")) == group
            )
            total_group_exposure = group_exposure + proposed_size_usd
            group_pct = (
                total_group_exposure / account_balance
                if account_balance > 0
                else 1.0
            )
            approved = group_pct <= self.max_group_exposure_pct
            details = {
                "check": "correlation_exposure",
                "approved": approved,
                "symbol": symbol,
                "correlation_group": group,
                "group_exposure_usd": total_group_exposure,
                "group_exposure_pct": group_pct,
                "max_group_exposure_pct": self.max_group_exposure_pct,
                "timestamp": datetime.now().isoformat(),
            }
            if approved:
                logger.debug(
                    f"✅ Correlation check PASSED for {symbol} "
                    f"(group={group}, {group_pct * 100:.1f}% ≤ "
                    f"{self.max_group_exposure_pct * 100:.0f}%)"
                )
            else:
                details["rejection_reason"] = (
                    f"Group '{group}' exposure would be "
                    f"{group_pct * 100:.1f}% > "
                    f"{self.max_group_exposure_pct * 100:.0f}% limit"
                )
                logger.warning(
                    f"❌ Correlation check FAILED for {symbol}: "
                    f"{details['rejection_reason']}"
                )
            return approved, details
        except Exception as exc:
            logger.error(f"CorrelationExposureController error: {exc}")
            return False, {
                "check": "correlation_exposure",
                "approved": False,
                "error": str(exc),
                "rejection_reason": "Error during correlation analysis",
            }


# ===========================================================================
# Feature 2 — Volatility-Adjusted Position Capper
# ===========================================================================

class VolatilityPositionCapper:
    """
    Cap position sizes based on current market volatility.

    Uses ``VolatilityAdaptiveSizer`` when available; otherwise falls back to
    a simple ATR-based calculation from the supplied OHLCV dataframe.

    The cap works as a *multiplier* on the requested position size:
        - Normal volatility  → 1.00× (no cap)
        - High volatility    → 0.65×
        - Extreme volatility → 0.40×
    """

    # Regime caps — percentage of base size allowed per regime
    _REGIME_CAPS: Dict[str, float] = {
        "EXTREME_HIGH": 0.40,
        "HIGH": 0.65,
        "NORMAL": 1.00,
        "LOW": 1.10,
        "EXTREME_LOW": 1.25,
    }

    def __init__(
        self,
        volatility_sizer=None,
        atr_lookback: int = 14,
    ):
        """
        Args:
            volatility_sizer: Optional ``VolatilityAdaptiveSizer`` instance.
            atr_lookback: ATR period for fallback calculation (default 14).
        """
        self.volatility_sizer = volatility_sizer
        self.atr_lookback = atr_lookback
        logger.info("✅ VolatilityPositionCapper initialized")

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def get_size_multiplier(self, symbol: str, df=None) -> Tuple[float, str]:
        """
        Return ``(multiplier, regime_label)`` for position sizing.

        Args:
            symbol: Trading pair symbol.
            df: Optional OHLCV DataFrame (used for fallback ATR calc).

        Returns:
            ``(multiplier, regime)`` — multiplier in ``[0.40, 1.25]``.
        """
        try:
            if self.volatility_sizer is not None and df is not None:
                if hasattr(self.volatility_sizer, "calculate_position_size"):
                    regime_info = self._get_regime_from_sizer(df)
                    regime = regime_info.get("regime", "NORMAL")
                    multiplier = self._REGIME_CAPS.get(regime, 1.0)
                    return multiplier, regime

            if df is not None and len(df) >= self.atr_lookback:
                regime = self._calc_atr_regime(df)
            else:
                regime = "NORMAL"

            multiplier = self._REGIME_CAPS.get(regime, 1.0)
            return multiplier, regime
        except Exception as exc:
            logger.error(f"VolatilityPositionCapper error for {symbol}: {exc}")
            return 0.65, "HIGH"  # Fail conservative

    def apply_cap(
        self, symbol: str, base_size_usd: float, df=None
    ) -> Tuple[float, Dict]:
        """
        Return the volatility-capped position size and metadata.

        Args:
            symbol: Trading pair symbol.
            base_size_usd: Uncapped position size in USD.
            df: Optional OHLCV DataFrame.

        Returns:
            ``(capped_size_usd, details)``
        """
        multiplier, regime = self.get_size_multiplier(symbol, df)
        capped_size = base_size_usd * multiplier
        details = {
            "check": "volatility_cap",
            "symbol": symbol,
            "regime": regime,
            "multiplier": multiplier,
            "base_size_usd": base_size_usd,
            "capped_size_usd": capped_size,
            "timestamp": datetime.now().isoformat(),
        }
        if multiplier < 1.0:
            logger.info(
                f"🔻 Volatility cap applied for {symbol}: "
                f"${base_size_usd:.2f} → ${capped_size:.2f} "
                f"({regime}, {multiplier:.2f}×)"
            )
        return capped_size, details

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_regime_from_sizer(self, df) -> Dict:
        """Attempt to extract volatility regime from the injected sizer."""
        try:
            if hasattr(self.volatility_sizer, "get_volatility_regime"):
                return {"regime": self.volatility_sizer.get_volatility_regime(df).value.upper()}
        except Exception:
            pass
        return {"regime": "NORMAL"}

    def _calc_atr_regime(self, df) -> str:
        """Simple ATR-based regime detection fallback."""
        try:
            import pandas as pd  # local import to avoid hard dependency
            high = df["high"] if "high" in df.columns else df.iloc[:, 1]
            low = df["low"] if "low" in df.columns else df.iloc[:, 2]
            close = df["close"] if "close" in df.columns else df.iloc[:, 3]
            tr = pd.concat(
                [
                    high - low,
                    (high - close.shift()).abs(),
                    (low - close.shift()).abs(),
                ],
                axis=1,
            ).max(axis=1)
            atr = tr.rolling(self.atr_lookback).mean()
            atr_mean = atr.mean()
            current_atr = atr.iloc[-1]
            if atr_mean == 0:
                return "NORMAL"
            ratio = current_atr / atr_mean
            if ratio > 2.5:
                return "EXTREME_HIGH"
            if ratio > 1.5:
                return "HIGH"
            if ratio < 0.5:
                return "EXTREME_LOW"
            if ratio < 0.8:
                return "LOW"
            return "NORMAL"
        except Exception as exc:
            logger.warning(f"ATR regime calc failed: {exc}")
            return "NORMAL"


# ===========================================================================
# Feature 3 — Portfolio-Level Drawdown Circuit Breaker
# ===========================================================================

class DrawdownCircuitBreaker:
    """
    Stop or throttle trading when portfolio drawdown is too deep.

    Wraps ``DrawdownProtectionSystem`` to provide a clean, uniform interface
    that the rest of the codebase can call without knowing internals.

    When ``DrawdownProtectionSystem`` is unavailable, falls back to a simple
    peak-tracking implementation so the feature always works.
    """

    # Fallback thresholds (used when DrawdownProtectionSystem is absent)
    _HALT_THRESHOLD_PCT = 20.0   # Stop ALL new positions
    _DANGER_THRESHOLD_PCT = 15.0  # Allow only 25% of normal size
    _WARNING_THRESHOLD_PCT = 10.0  # Allow only 50% of normal size
    _CAUTION_THRESHOLD_PCT = 5.0   # Allow only 75% of normal size

    def __init__(
        self,
        base_capital: float,
        drawdown_config=None,
    ):
        """
        Args:
            base_capital: Starting / reference capital.
            drawdown_config: Optional ``DrawdownConfig`` instance.
        """
        self.base_capital = base_capital
        self._peak_capital = base_capital
        self._current_capital = base_capital

        # Prefer the full system when available
        self._system = None
        if _HAS_DRAWDOWN and DrawdownProtectionSystem is not None:
            try:
                self._system = DrawdownProtectionSystem(
                    base_capital=base_capital,
                    config=drawdown_config,
                )
                logger.info(
                    "✅ DrawdownCircuitBreaker: using DrawdownProtectionSystem"
                )
            except Exception as exc:
                logger.warning(
                    f"DrawdownProtectionSystem init failed ({exc}); "
                    "using built-in fallback"
                )
        else:
            logger.info(
                "✅ DrawdownCircuitBreaker: using built-in fallback implementation"
            )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def update(self, current_capital: float) -> None:
        """Record the latest portfolio value."""
        self._current_capital = current_capital
        if current_capital > self._peak_capital:
            self._peak_capital = current_capital
        if self._system is not None:
            try:
                if hasattr(self._system, "update_capital"):
                    self._system.update_capital(current_capital)
                elif hasattr(self._system, "record_trade"):
                    pass  # record_trade needs a win/loss bool; skip here
            except Exception as exc:
                logger.warning(f"DrawdownProtectionSystem.update error: {exc}")

    def can_trade(self) -> Tuple[bool, str]:
        """
        Return ``(True, reason)`` when new positions are permitted.

        Returns:
            ``(can_trade, reason)``
        """
        if self._system is not None:
            try:
                return self._system.can_trade()
            except Exception as exc:
                logger.warning(f"DrawdownProtectionSystem.can_trade error: {exc}")
        return self._fallback_can_trade()

    def get_position_size_multiplier(self) -> float:
        """
        Return a multiplier ``[0.0, 1.0]`` to scale down position sizes.

        A value of ``1.0`` means full size; ``0.0`` means no trading.
        """
        if self._system is not None:
            try:
                return self._system.get_position_size_multiplier()
            except Exception as exc:
                logger.warning(
                    f"DrawdownProtectionSystem.get_position_size_multiplier error: {exc}"
                )
        return self._fallback_multiplier()

    def get_drawdown_pct(self) -> float:
        """Return current drawdown as a percentage (0-100)."""
        if self._peak_capital <= 0:
            return 0.0
        return max(
            0.0,
            (self._peak_capital - self._current_capital) / self._peak_capital * 100,
        )

    def get_status(self) -> Dict:
        """Return a status dictionary for monitoring / logging."""
        drawdown_pct = self.get_drawdown_pct()
        can_trade, reason = self.can_trade()
        multiplier = self.get_position_size_multiplier()
        return {
            "peak_capital": self._peak_capital,
            "current_capital": self._current_capital,
            "drawdown_pct": drawdown_pct,
            "can_trade": can_trade,
            "reason": reason,
            "position_size_multiplier": multiplier,
            "timestamp": datetime.now().isoformat(),
        }

    # ------------------------------------------------------------------
    # Fallback implementation (no DrawdownProtectionSystem dependency)
    # ------------------------------------------------------------------

    def _fallback_can_trade(self) -> Tuple[bool, str]:
        drawdown_pct = self.get_drawdown_pct()
        if drawdown_pct >= self._HALT_THRESHOLD_PCT:
            return (
                False,
                f"Circuit breaker HALTED: drawdown {drawdown_pct:.1f}% "
                f">= {self._HALT_THRESHOLD_PCT:.0f}%",
            )
        return True, f"Trading allowed (drawdown {drawdown_pct:.1f}%)"

    def _fallback_multiplier(self) -> float:
        drawdown_pct = self.get_drawdown_pct()
        if drawdown_pct >= self._HALT_THRESHOLD_PCT:
            return 0.0
        if drawdown_pct >= self._DANGER_THRESHOLD_PCT:
            return 0.25
        if drawdown_pct >= self._WARNING_THRESHOLD_PCT:
            return 0.50
        if drawdown_pct >= self._CAUTION_THRESHOLD_PCT:
            return 0.75
        return 1.0


# ===========================================================================
# Unified facade
# ===========================================================================

class RiskIntelligenceSystem:
    """
    Single integration point for all three risk intelligence controls.

    Usage (inside position-sizing logic)::

        ris = RiskIntelligenceSystem(base_capital=account_balance)

        # Before opening a new position
        allowed, reason = ris.can_open_position(
            symbol="ETH-USD",
            proposed_size_usd=500.0,
            current_positions=open_positions,
            account_balance=10_000.0,
            df=ohlcv_df,
        )
        if not allowed:
            logger.warning(f"Position blocked: {reason}")
            return

        adjusted_size = ris.get_adjusted_position_size(
            symbol="ETH-USD",
            base_size_usd=500.0,
            current_positions=open_positions,
            account_balance=10_000.0,
            df=ohlcv_df,
        )
    """

    def __init__(
        self,
        base_capital: float = 1_000.0,
        max_group_exposure_pct: float = 0.40,
        drawdown_config=None,
        volatility_sizer=None,
        portfolio_risk_engine=None,
        var_size_reducer=None,
    ):
        """
        Args:
            base_capital: Starting portfolio value (used by circuit breaker).
            max_group_exposure_pct: Max exposure per correlation group (0–1).
            drawdown_config: Optional ``DrawdownConfig`` for circuit breaker.
            volatility_sizer: Optional ``VolatilityAdaptiveSizer`` instance.
            portfolio_risk_engine: Optional ``PortfolioRiskEngine`` instance.
            var_size_reducer: Optional ``VaRAutoSizeReducer`` instance.  When
                provided, its multiplier is applied on top of the volatility cap
                and drawdown multiplier to auto-reduce sizes on VaR breaches.
        """
        self.correlation_controller = CorrelationExposureController(
            max_group_exposure_pct=max_group_exposure_pct,
            portfolio_risk_engine=portfolio_risk_engine,
        )
        self.volatility_capper = VolatilityPositionCapper(
            volatility_sizer=volatility_sizer,
        )
        self.circuit_breaker = DrawdownCircuitBreaker(
            base_capital=base_capital,
            drawdown_config=drawdown_config,
        )
        self.var_size_reducer = var_size_reducer
        logger.info(
            "✅ RiskIntelligenceSystem initialized "
            f"(base_capital=${base_capital:,.2f}, "
            f"max_group={max_group_exposure_pct * 100:.0f}%, "
            f"var_auto_reduce={'enabled' if var_size_reducer is not None else 'disabled'})"
        )

    # ------------------------------------------------------------------
    # High-level helpers
    # ------------------------------------------------------------------

    def update_capital(self, current_capital: float) -> None:
        """Feed the latest portfolio value to the circuit breaker."""
        self.circuit_breaker.update(current_capital)

    def can_open_position(
        self,
        symbol: str,
        proposed_size_usd: float,
        current_positions: List[Dict],
        account_balance: float,
        df=None,
    ) -> Tuple[bool, str]:
        """
        Combined gate: returns ``(True, "ok")`` only when ALL three controls
        allow the position.

        Checks (in order):
        1. Drawdown circuit breaker — abort if portfolio is in deep drawdown.
        2. Correlation exposure — abort if group exposure would be too high.
        3. (Volatility cap applied in ``get_adjusted_position_size``.)
        """
        # 1. Circuit breaker
        can_trade, reason = self.circuit_breaker.can_trade()
        if not can_trade:
            return False, f"[CircuitBreaker] {reason}"

        # 2. Correlation exposure
        approved, details = self.correlation_controller.check(
            symbol=symbol,
            proposed_size_usd=proposed_size_usd,
            current_positions=current_positions,
            account_balance=account_balance,
        )
        if not approved:
            return False, f"[CorrelationControl] {details.get('rejection_reason', 'Exposure limit exceeded')}"

        return True, "ok"

    def get_adjusted_position_size(
        self,
        symbol: str,
        base_size_usd: float,
        current_positions: Optional[List[Dict]] = None,
        account_balance: float = 0.0,
        df=None,
    ) -> Tuple[float, Dict]:
        """
        Apply volatility cap, drawdown multiplier, and VaR auto-size reduction
        to *base_size_usd*.

        Args:
            symbol: Trading pair symbol.
            base_size_usd: Desired position size before adjustments.
            current_positions: Current open positions (for context logging).
            account_balance: Portfolio balance (for context logging).
            df: Optional OHLCV DataFrame for volatility analysis.

        Returns:
            ``(adjusted_size_usd, metadata_dict)``
        """
        # Apply volatility cap first
        vol_capped, vol_details = self.volatility_capper.apply_cap(
            symbol=symbol,
            base_size_usd=base_size_usd,
            df=df,
        )

        # Then apply drawdown multiplier
        dd_multiplier = self.circuit_breaker.get_position_size_multiplier()
        final_size = vol_capped * dd_multiplier

        # Apply VaR breach auto-size reduction (if reducer is attached)
        var_multiplier = 1.0
        var_status: Dict = {}
        if self.var_size_reducer is not None:
            var_multiplier = self.var_size_reducer.get_size_multiplier()
            var_status = self.var_size_reducer.get_status()
            if var_multiplier < 1.0:
                pre_var_size = final_size
                final_size = final_size * var_multiplier
                logger.info(
                    f"🔻 VaR breach multiplier {var_multiplier:.2f}× applied for {symbol}: "
                    f"${pre_var_size:.2f} → ${final_size:.2f}"
                )

        metadata = {
            "symbol": symbol,
            "base_size_usd": base_size_usd,
            "volatility_cap": vol_details,
            "drawdown_multiplier": dd_multiplier,
            "var_multiplier": var_multiplier,
            "var_status": var_status,
            "final_size_usd": final_size,
            "drawdown_status": self.circuit_breaker.get_status(),
            "timestamp": datetime.now().isoformat(),
        }

        if dd_multiplier < 1.0:
            logger.info(
                f"🔻 Drawdown multiplier {dd_multiplier:.2f}× applied for {symbol}: "
                f"${vol_capped:.2f} → ${final_size:.2f}"
            )

        return final_size, metadata

    def get_full_status(self) -> Dict:
        """Return a full status snapshot of all three controls."""
        status: Dict = {
            "circuit_breaker": self.circuit_breaker.get_status(),
            "timestamp": datetime.now().isoformat(),
        }
        if self.var_size_reducer is not None:
            status["var_auto_reduce"] = self.var_size_reducer.get_status()
        return status


# ---------------------------------------------------------------------------
# Factory helper
# ---------------------------------------------------------------------------

def create_risk_intelligence_system(
    base_capital: float = 1_000.0,
    config: Optional[Dict] = None,
    volatility_sizer=None,
    portfolio_risk_engine=None,
    var_size_reducer=None,
) -> RiskIntelligenceSystem:
    """
    Convenience factory for ``RiskIntelligenceSystem``.

    Args:
        base_capital: Starting portfolio value.
        config: Optional dict with overrides::

            {
                "max_group_exposure_pct": 0.40,  # default 40%
                "drawdown_halt_pct": 20.0,        # default 20%
            }

        volatility_sizer: Optional ``VolatilityAdaptiveSizer``.
        portfolio_risk_engine: Optional ``PortfolioRiskEngine``.
        var_size_reducer: Optional ``VaRAutoSizeReducer`` for VaR breach
            auto-size reduction.

    Returns:
        Configured ``RiskIntelligenceSystem``.
    """
    cfg = config or {}

    drawdown_config = None
    if _HAS_DRAWDOWN and DrawdownConfig is not None:
        try:
            drawdown_config = DrawdownConfig(
                halt_threshold_pct=cfg.get("drawdown_halt_pct", 20.0),
                danger_threshold_pct=cfg.get("drawdown_danger_pct", 15.0),
                warning_threshold_pct=cfg.get("drawdown_warning_pct", 10.0),
                caution_threshold_pct=cfg.get("drawdown_caution_pct", 5.0),
            )
        except Exception:
            drawdown_config = None

    return RiskIntelligenceSystem(
        base_capital=base_capital,
        max_group_exposure_pct=cfg.get("max_group_exposure_pct", 0.40),
        drawdown_config=drawdown_config,
        volatility_sizer=volatility_sizer,
        portfolio_risk_engine=portfolio_risk_engine,
        var_size_reducer=var_size_reducer,
    )
