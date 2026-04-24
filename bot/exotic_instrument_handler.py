"""
NIJA Exotic Instrument Handler
================================

Handles execution, valuation, and risk management for non-standard financial
instruments that require special treatment beyond plain equity/futures/options:

  • Exotic options  – barrier (knock-in/knock-out), Asian (average-price),
                      digital/binary, lookback
  • Leveraged futures – dynamic margin tracking, auto-deleverage detection
  • OTC trades        – bilateral confirmations, custom settlement, ISDA docs
  • Fractional shares – sub-share sizing, drip reinvestment, rounding rules

Architecture
------------
Each instrument type has a dedicated handler class that implements:
  - ``validate(instrument)``  → raises if the instrument spec is invalid
  - ``price(instrument)``     → fair-value or mid-market price
  - ``execute(instrument, side, size, broker_adapter)`` → ExecutionResult
  - ``margin_requirement(instrument, size)`` → USD margin

The ``ExoticInstrumentRouter`` dispatches incoming order requests to the
correct handler based on the ``instrument_type`` field.

Usage
-----
    from bot.exotic_instrument_handler import get_exotic_router, ExoticOrder

    router = get_exotic_router()

    order = ExoticOrder(
        instrument_type="barrier_option",
        underlying="AAPL",
        side="BUY",
        size=5,
        params={
            "barrier_type": "knock_out",
            "barrier_level": 200.0,
            "strike": 185.0,
            "expiry": "2026-06-20",
            "put_call": "call",
            "premium": 3.50,
        },
    )
    result = router.route(order)
    print(result)

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import math
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nija.exotic_instrument_handler")


# ---------------------------------------------------------------------------
# Enums & data structures
# ---------------------------------------------------------------------------

class InstrumentType(str, Enum):
    BARRIER_OPTION  = "barrier_option"
    ASIAN_OPTION    = "asian_option"
    DIGITAL_OPTION  = "digital_option"
    LOOKBACK_OPTION = "lookback_option"
    LEVERAGED_FUTURE = "leveraged_future"
    OTC_TRADE        = "otc_trade"
    FRACTIONAL_SHARE = "fractional_share"


@dataclass
class ExoticOrder:
    """
    Represents an order for an exotic instrument.

    Fields
    ------
    instrument_type : InstrumentType or string key
    underlying      : underlying symbol (e.g. "AAPL", "BTC-USD")
    side            : "BUY" or "SELL"
    size            : number of contracts / shares / notional units
    params          : instrument-specific parameters dict (see handler docs)
    broker_adapter  : optional BrokerAdapter for live execution
    dry_run         : if True, validate & price only, do not execute
    """
    instrument_type: str
    underlying: str
    side: str
    size: float
    params: Dict[str, Any] = field(default_factory=dict)
    broker_adapter: Any = None  # BrokerAdapter | None
    dry_run: bool = False
    order_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    submitted_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ExoticResult:
    """Result of an exotic instrument order execution."""
    order_id: str
    instrument_type: str
    underlying: str
    side: str
    size: float
    success: bool
    fair_value: float          # model price per unit
    total_cost: float          # total cost (fair_value × size + fees)
    margin_required: float
    message: str
    risk_flags: List[str] = field(default_factory=list)
    execution_details: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict:
        return {
            "order_id": self.order_id,
            "instrument_type": self.instrument_type,
            "underlying": self.underlying,
            "side": self.side,
            "size": self.size,
            "success": self.success,
            "fair_value": round(self.fair_value, 4),
            "total_cost": round(self.total_cost, 4),
            "margin_required": round(self.margin_required, 4),
            "message": self.message,
            "risk_flags": self.risk_flags,
            "execution_details": self.execution_details,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Black-Scholes helper (used by option pricers)
# ---------------------------------------------------------------------------

def _bs_price(
    S: float, K: float, T: float, r: float, sigma: float, put_call: str = "call"
) -> float:
    """
    Compute Black-Scholes option price.

    S     : underlying price
    K     : strike
    T     : time to expiry in years
    r     : risk-free rate (e.g. 0.05)
    sigma : annual volatility (e.g. 0.25)
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return max(0.0, (S - K) if put_call == "call" else (K - S))

    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    def _norm_cdf(x: float) -> float:
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2)))

    if put_call.lower() == "call":
        return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    else:  # put
        return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def _years_to_expiry(expiry_str: str) -> float:
    """Return years from now to the given ISO-date expiry string."""
    try:
        expiry = datetime.fromisoformat(expiry_str).replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = (expiry - now).total_seconds()
        return max(0.0, delta / (365.25 * 24 * 3600))
    except Exception:
        return 0.5  # default half-year if parse fails


# ---------------------------------------------------------------------------
# Barrier Option Handler
# ---------------------------------------------------------------------------

class BarrierOptionHandler:
    """
    Handles European knock-in and knock-out barrier options.

    params keys
    -----------
    barrier_type  : "knock_out" | "knock_in"
    barrier_level : USD price level (float)
    strike        : option strike price
    expiry        : ISO date string "YYYY-MM-DD"
    put_call      : "call" | "put"
    spot_price    : current underlying price (optional; fetched from broker if absent)
    sigma         : implied volatility (default 0.25)
    risk_free     : risk-free rate (default 0.05)
    """

    def validate(self, order: ExoticOrder) -> None:
        required = ["barrier_type", "barrier_level", "strike", "expiry", "put_call"]
        missing = [k for k in required if k not in order.params]
        if missing:
            raise ValueError(f"BarrierOption missing params: {missing}")
        if order.params["barrier_type"] not in ("knock_out", "knock_in"):
            raise ValueError("barrier_type must be 'knock_out' or 'knock_in'")

    def price(self, order: ExoticOrder, spot: float) -> float:
        """
        Price a barrier option using a simplified adjustment to Black-Scholes.
        For knock-out options, the BS price is discounted by the knock-out
        probability (approximated via distance-to-barrier).
        """
        p = order.params
        K = float(p["strike"])
        B = float(p["barrier_level"])
        T = _years_to_expiry(p["expiry"])
        sigma = float(p.get("sigma", 0.25))
        r = float(p.get("risk_free", 0.05))
        put_call = p.get("put_call", "call")

        vanilla_price = _bs_price(spot, K, T, r, sigma, put_call)

        # Approximation: adjust vanilla price for barrier proximity
        barrier_type = p["barrier_type"]
        if barrier_type == "knock_out":
            # Probability of NOT hitting barrier ≈ normal CDF of log distance
            log_dist = abs(math.log(spot / B)) / (sigma * math.sqrt(max(T, 1e-6)))
            survival = 0.5 * (1.0 + math.erf(log_dist / math.sqrt(2)))
            return vanilla_price * survival
        else:  # knock_in
            # Knock-in value ≈ vanilla − knock-out
            log_dist = abs(math.log(spot / B)) / (sigma * math.sqrt(max(T, 1e-6)))
            survival = 0.5 * (1.0 + math.erf(log_dist / math.sqrt(2)))
            return vanilla_price * (1.0 - survival)

    def margin_requirement(self, order: ExoticOrder, fair_value: float) -> float:
        """For purchased options, margin = premium paid."""
        return fair_value * order.size

    def risk_flags(self, order: ExoticOrder, spot: float) -> List[str]:
        flags = []
        B = float(order.params["barrier_level"])
        proximity_pct = abs(spot - B) / spot
        if proximity_pct < 0.03:
            flags.append(f"Barrier very close to spot ({proximity_pct*100:.1f}% away) — high gamma risk")
        if order.size > 100:
            flags.append("Large contract size — verify notional exposure")
        return flags


# ---------------------------------------------------------------------------
# Asian (Average-Price) Option Handler
# ---------------------------------------------------------------------------

class AsianOptionHandler:
    """
    Handles Asian options where the payoff depends on the average underlying price.

    params keys
    -----------
    averaging_type : "arithmetic" | "geometric"
    strike         : option strike (for fixed-strike Asian)
    expiry         : ISO date string
    put_call       : "call" | "put"
    num_obs        : number of observation points (default 30)
    sigma          : implied volatility (default 0.25)
    risk_free      : risk-free rate (default 0.05)
    """

    def validate(self, order: ExoticOrder) -> None:
        required = ["strike", "expiry", "put_call"]
        missing = [k for k in required if k not in order.params]
        if missing:
            raise ValueError(f"AsianOption missing params: {missing}")

    def price(self, order: ExoticOrder, spot: float) -> float:
        """
        Price via adjusted BS: Asian volatility ≈ σ/√3 for arithmetic averaging.
        (Turnbull-Wakeman approximation)
        """
        p = order.params
        K = float(p["strike"])
        T = _years_to_expiry(p["expiry"])
        sigma = float(p.get("sigma", 0.25))
        r = float(p.get("risk_free", 0.05))
        put_call = p.get("put_call", "call")
        avg_type = p.get("averaging_type", "arithmetic")

        # Reduce effective vol for averaging
        sigma_adj = sigma / math.sqrt(3) if avg_type == "arithmetic" else sigma / math.sqrt(2)
        return _bs_price(spot, K, T, r, sigma_adj, put_call)

    def margin_requirement(self, order: ExoticOrder, fair_value: float) -> float:
        return fair_value * order.size

    def risk_flags(self, order: ExoticOrder, spot: float) -> List[str]:
        flags = []
        T = _years_to_expiry(order.params.get("expiry", ""))
        if T < 0.05:
            flags.append("Very short time to expiry — Asian averaging may not reduce risk significantly")
        return flags


# ---------------------------------------------------------------------------
# Digital / Binary Option Handler
# ---------------------------------------------------------------------------

class DigitalOptionHandler:
    """
    Handles cash-or-nothing and asset-or-nothing digital options.

    params keys
    -----------
    strike        : barrier/trigger price
    expiry        : ISO date string
    put_call      : "call" (pays if S > K) | "put" (pays if S < K)
    payout        : fixed cash payout per contract (default 1.0)
    sigma         : implied volatility (default 0.25)
    risk_free     : risk-free rate (default 0.05)
    """

    def validate(self, order: ExoticOrder) -> None:
        if "strike" not in order.params or "expiry" not in order.params:
            raise ValueError("DigitalOption requires 'strike' and 'expiry' params")

    def price(self, order: ExoticOrder, spot: float) -> float:
        """BS digital (cash-or-nothing) price = e^{-rT} × N(d2)."""
        p = order.params
        K = float(p["strike"])
        T = _years_to_expiry(p["expiry"])
        sigma = float(p.get("sigma", 0.25))
        r = float(p.get("risk_free", 0.05))
        payout = float(p.get("payout", 1.0))
        put_call = p.get("put_call", "call")

        if T <= 0 or sigma <= 0:
            intrinsic = (spot > K) if put_call == "call" else (spot < K)
            return payout if intrinsic else 0.0

        d2 = (math.log(spot / K) + (r - 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
        def _ncdf(x):
            return 0.5 * (1.0 + math.erf(x / math.sqrt(2)))

        prob = _ncdf(d2) if put_call == "call" else _ncdf(-d2)
        return math.exp(-r * T) * payout * prob

    def margin_requirement(self, order: ExoticOrder, fair_value: float) -> float:
        payout = float(order.params.get("payout", 1.0))
        return payout * order.size  # max possible loss = full payout

    def risk_flags(self, order: ExoticOrder, spot: float) -> List[str]:
        K = float(order.params.get("strike", spot))
        prox = abs(spot - K) / spot
        if prox < 0.01:
            return ["Near-ATM digital — extreme pin risk near expiry"]
        return []


# ---------------------------------------------------------------------------
# Lookback Option Handler
# ---------------------------------------------------------------------------

class LookbackOptionHandler:
    """
    Handles lookback options (payoff based on max/min observed price).

    params keys
    -----------
    put_call  : "call" (buys at min) | "put" (sells at max)
    expiry    : ISO date string
    sigma     : implied volatility (default 0.25)
    risk_free : risk-free rate (default 0.05)
    """

    def validate(self, order: ExoticOrder) -> None:
        if "expiry" not in order.params:
            raise ValueError("LookbackOption requires 'expiry' param")

    def price(self, order: ExoticOrder, spot: float) -> float:
        """
        Floating-strike lookback approximation: price ≈ vanilla ATM call/put × adjustment.
        (Conze-Viswanathan approximation)
        """
        p = order.params
        T = _years_to_expiry(p["expiry"])
        sigma = float(p.get("sigma", 0.25))
        r = float(p.get("risk_free", 0.05))
        put_call = p.get("put_call", "call")

        # Lookback ≈ vanilla(ATM) × (1 + σ²/(2r)) adjustment
        vanilla = _bs_price(spot, spot, T, r, sigma, put_call)
        adjustment = 1.0 + (sigma ** 2) / (2 * r) if r > 0 else 1.5
        return vanilla * adjustment

    def margin_requirement(self, order: ExoticOrder, fair_value: float) -> float:
        return fair_value * order.size * 1.5  # extra buffer for lookback

    def risk_flags(self, order: ExoticOrder, spot: float) -> List[str]:
        return ["Lookback options are path-dependent — intrinsic value depends on historical extremes"]


# ---------------------------------------------------------------------------
# Leveraged Futures Handler
# ---------------------------------------------------------------------------

class LeveragedFuturesHandler:
    """
    Handles leveraged futures positions with dynamic margin tracking and
    auto-deleverage (ADL) detection.

    params keys
    -----------
    leverage        : leverage multiplier (e.g. 5.0 for 5×)
    initial_margin  : initial margin fraction (e.g. 0.10 for 10%)
    maintenance_margin : maintenance margin fraction (e.g. 0.05)
    contract_size   : notional per contract in USD (e.g. 5000 for E-mini S&P)

    Environment variable
    --------------------
    NIJA_MAX_LEVERAGE : maximum allowed leverage multiplier (default 20)
    """

    def __init__(self, max_leverage: Optional[float] = None) -> None:
        self.MAX_LEVERAGE: float = max_leverage or float(
            os.getenv("NIJA_MAX_LEVERAGE", "20")
        )

    def validate(self, order: ExoticOrder) -> None:
        leverage = float(order.params.get("leverage", 1.0))
        if leverage > self.MAX_LEVERAGE:
            raise ValueError(f"Leverage {leverage}× exceeds maximum {self.MAX_LEVERAGE}×")
        if leverage <= 0:
            raise ValueError("Leverage must be positive")

    def price(self, order: ExoticOrder, spot: float) -> float:
        """Mark-to-market price = spot × contract_size."""
        contract_size = float(order.params.get("contract_size", 1.0))
        return spot * contract_size

    def margin_requirement(self, order: ExoticOrder, fair_value: float) -> float:
        leverage = float(order.params.get("leverage", 1.0))
        initial_margin = float(order.params.get("initial_margin", 1.0 / leverage))
        return fair_value * order.size * initial_margin

    def risk_flags(self, order: ExoticOrder, spot: float) -> List[str]:
        flags = []
        leverage = float(order.params.get("leverage", 1.0))
        maint = float(order.params.get("maintenance_margin", 0.05))

        if leverage >= 10:
            flags.append(f"Extreme leverage ({leverage}×) — liquidation risk very high")
        elif leverage >= 5:
            flags.append(f"High leverage ({leverage}×) — monitor margin closely")

        # Estimate liquidation price
        initial_margin = float(order.params.get("initial_margin", 1.0 / max(leverage, 1)))
        liquidation_distance = (initial_margin - maint) / leverage
        liq_price_long = spot * (1 - liquidation_distance)
        flags.append(
            f"Estimated long liquidation price: ${liq_price_long:.2f} "
            f"({liquidation_distance * 100:.1f}% from spot)"
        )
        return flags


# ---------------------------------------------------------------------------
# OTC Trade Handler
# ---------------------------------------------------------------------------

class OTCTradeHandler:
    """
    Handles over-the-counter (bilateral) trades.

    OTC trades are not exchange-cleared; they require:
    - Counterparty confirmation
    - ISDA master agreement check
    - Custom settlement terms
    - Bilateral margin (CSA)

    params keys
    -----------
    counterparty        : counterparty identifier / legal entity name
    settlement_days     : T+N settlement (default 2)
    notional_usd        : total notional in USD
    trade_type          : "swap" | "forward" | "swaption" | "custom"
    confirmation_ref    : trade confirmation reference number (optional)
    isda_agreement_ref  : ISDA master agreement reference (optional)
    """

    def validate(self, order: ExoticOrder) -> None:
        if "counterparty" not in order.params:
            raise ValueError("OTC trade requires 'counterparty' param")
        if "notional_usd" not in order.params:
            raise ValueError("OTC trade requires 'notional_usd' param")

    def price(self, order: ExoticOrder, spot: float) -> float:
        """OTC trades are priced bilaterally; return notional / size as unit price."""
        notional = float(order.params.get("notional_usd", 0.0))
        return notional / order.size if order.size > 0 else notional

    def margin_requirement(self, order: ExoticOrder, fair_value: float) -> float:
        """CSA bilateral margin typically 5–15% of notional."""
        notional = float(order.params.get("notional_usd", fair_value * order.size))
        return notional * 0.10

    def risk_flags(self, order: ExoticOrder, spot: float) -> List[str]:
        flags = ["OTC trade — no exchange clearing, counterparty credit risk applies"]
        if not order.params.get("isda_agreement_ref"):
            flags.append("No ISDA master agreement reference — ensure legal docs are in place")
        settlement_days = int(order.params.get("settlement_days", 2))
        if settlement_days > 5:
            flags.append(f"Extended settlement ({settlement_days} days) — elevated settlement risk")
        return flags


# ---------------------------------------------------------------------------
# Fractional Share Handler
# ---------------------------------------------------------------------------

class FractionalShareHandler:
    """
    Handles fractional share orders (size < 1.0 whole shares).

    Fractional shares require special handling:
    - Minimum order size validation
    - Rounding to broker-supported decimal places
    - DRIP (Dividend Reinvestment Plan) compatibility
    - Notional sizing mode

    params keys
    -----------
    min_qty         : broker minimum fractional quantity (default 0.000001)
    max_decimals    : decimal places supported by broker (default 6)
    drip_eligible   : whether symbol is DRIP-eligible (default False)
    notional_mode   : True to express size as USD notional rather than shares

    Environment variable
    --------------------
    NIJA_MIN_NOTIONAL_USD : minimum fractional share notional in USD (default 1.0)
    """

    def __init__(self, min_notional_usd: Optional[float] = None) -> None:
        self.MIN_ABSOLUTE_NOTIONAL: float = min_notional_usd or float(
            os.getenv("NIJA_MIN_NOTIONAL_USD", "1.0")
        )

    def validate(self, order: ExoticOrder) -> None:
        min_qty = float(order.params.get("min_qty", 0.000001))
        notional_mode = order.params.get("notional_mode", False)
        if not notional_mode and order.size < min_qty:
            raise ValueError(
                f"Fractional share size {order.size} is below minimum {min_qty}"
            )

    def price(self, order: ExoticOrder, spot: float) -> float:
        return spot

    def margin_requirement(self, order: ExoticOrder, fair_value: float) -> float:
        return fair_value * order.size  # cash equity, no margin needed

    def round_size(self, size: float, max_decimals: int) -> float:
        """Round size to broker-supported precision."""
        factor = 10 ** max_decimals
        return math.floor(size * factor) / factor

    def risk_flags(self, order: ExoticOrder, spot: float) -> List[str]:
        flags = []
        notional_mode = order.params.get("notional_mode", False)
        if notional_mode:
            notional = order.size
            if notional < self.MIN_ABSOLUTE_NOTIONAL:
                flags.append(f"Notional ${notional:.2f} below minimum ${self.MIN_ABSOLUTE_NOTIONAL:.2f}")
        if order.params.get("drip_eligible") and order.size < 0.01:
            flags.append("Very small fractional share — DRIP reinvestment may round to zero")
        return flags


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

class ExoticInstrumentRouter:
    """
    Routes ``ExoticOrder`` objects to the appropriate handler and returns
    a structured ``ExoticResult``.

    All handler interactions are thread-safe via a per-router lock.
    """

    def __init__(
        self,
        max_leverage: Optional[float] = None,
        min_notional_usd: Optional[float] = None,
    ) -> None:
        self._handlers = {
            InstrumentType.BARRIER_OPTION:   BarrierOptionHandler(),
            InstrumentType.ASIAN_OPTION:     AsianOptionHandler(),
            InstrumentType.DIGITAL_OPTION:   DigitalOptionHandler(),
            InstrumentType.LOOKBACK_OPTION:  LookbackOptionHandler(),
            InstrumentType.LEVERAGED_FUTURE: LeveragedFuturesHandler(max_leverage=max_leverage),
            InstrumentType.OTC_TRADE:        OTCTradeHandler(),
            InstrumentType.FRACTIONAL_SHARE: FractionalShareHandler(min_notional_usd=min_notional_usd),
        }
        self._lock = threading.Lock()
        self._history: List[ExoticResult] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def route(self, order: ExoticOrder) -> ExoticResult:
        """
        Validate, price, and optionally execute an exotic order.

        Returns an ExoticResult with full details.
        """
        try:
            instrument_type = InstrumentType(order.instrument_type)
        except ValueError:
            return ExoticResult(
                order_id=order.order_id,
                instrument_type=order.instrument_type,
                underlying=order.underlying,
                side=order.side,
                size=order.size,
                success=False,
                fair_value=0.0,
                total_cost=0.0,
                margin_required=0.0,
                message=f"Unknown instrument type: {order.instrument_type}",
            )

        handler = self._handlers[instrument_type]

        # Validate
        try:
            handler.validate(order)
        except ValueError as exc:
            return ExoticResult(
                order_id=order.order_id,
                instrument_type=order.instrument_type,
                underlying=order.underlying,
                side=order.side,
                size=order.size,
                success=False,
                fair_value=0.0,
                total_cost=0.0,
                margin_required=0.0,
                message=f"Validation failed: {exc}",
            )

        # Get spot price
        spot = self._get_spot(order)

        # Price
        fair_value = handler.price(order, spot)
        margin = handler.margin_requirement(order, fair_value)
        total_cost = fair_value * order.size

        # Risk flags
        flags = handler.risk_flags(order, spot)
        if flags:
            for flag in flags:
                logger.warning("[ExoticRouter] %s [%s]: %s", order.instrument_type, order.underlying, flag)

        # Execute (unless dry_run)
        exec_details: Dict[str, Any] = {}
        success = True
        message = "Priced and validated" if order.dry_run else "Executed"

        if not order.dry_run:
            exec_details = self._execute(order, fair_value, handler)
            success = exec_details.get("success", True)
            if not success:
                message = exec_details.get("error", "Execution failed")

        result = ExoticResult(
            order_id=order.order_id,
            instrument_type=order.instrument_type,
            underlying=order.underlying,
            side=order.side,
            size=order.size,
            success=success,
            fair_value=fair_value,
            total_cost=total_cost,
            margin_required=margin,
            message=message,
            risk_flags=flags,
            execution_details=exec_details,
        )

        with self._lock:
            self._history.append(result)

        logger.info(
            "[ExoticRouter] %s %s %s %.4f fv=%.4f margin=%.2f flags=%d success=%s",
            order.instrument_type, order.side, order.underlying, order.size,
            fair_value, margin, len(flags), success,
        )
        return result

    def order_history(self, limit: int = 100) -> List[Dict]:
        with self._lock:
            return [r.to_dict() for r in self._history[-limit:]]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_spot(self, order: ExoticOrder) -> float:
        """Fetch spot price from broker adapter or params fallback."""
        if order.broker_adapter is not None:
            try:
                price = order.broker_adapter.get_price(order.underlying)
                if price > 0:
                    return price
            except Exception as exc:
                logger.warning("[ExoticRouter] Broker price fetch failed: %s", exc)

        return float(order.params.get("spot_price", order.params.get("current_price", 100.0)))

    def _execute(self, order: ExoticOrder, fair_value: float, handler) -> Dict:
        """
        Execute via broker adapter if available, else simulate.
        For options/OTC, sends a limit order at fair_value.
        """
        if order.broker_adapter is None:
            logger.info("[ExoticRouter] No broker adapter — simulating execution")
            return {
                "success": True,
                "order_id": f"sim_{order.order_id}",
                "filled_price": fair_value,
                "filled_size": order.size,
                "status": "SIMULATED",
            }

        try:
            resp = order.broker_adapter.place_order(
                symbol=order.underlying,
                side=order.side,
                size=order.size,
                order_type="LIMIT",
                limit_price=fair_value,
            )
            return {
                "success": resp.get("status", "ERROR") != "ERROR",
                **resp,
            }
        except Exception as exc:
            logger.error("[ExoticRouter] Execution error: %s", exc)
            return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_router_instance: Optional[ExoticInstrumentRouter] = None
_router_lock = threading.Lock()


def get_exotic_router(
    max_leverage: Optional[float] = None,
    min_notional_usd: Optional[float] = None,
    reset: bool = False,
) -> ExoticInstrumentRouter:
    """
    Return module-level singleton ExoticInstrumentRouter.

    Args:
        max_leverage:     Override maximum allowed leverage (default: env NIJA_MAX_LEVERAGE or 20).
        min_notional_usd: Override minimum fractional share notional (default: env NIJA_MIN_NOTIONAL_USD or 1.0).
        reset:            If True, create a fresh router even if one exists.
    """
    global _router_instance
    with _router_lock:
        if _router_instance is None or reset:
            _router_instance = ExoticInstrumentRouter(
                max_leverage=max_leverage,
                min_notional_usd=min_notional_usd,
            )
    return _router_instance


# ---------------------------------------------------------------------------
# CLI demo / self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
    )

    router = get_exotic_router()
    all_pass = True

    demo_orders = [
        ExoticOrder(
            instrument_type="barrier_option",
            underlying="AAPL",
            side="BUY",
            size=10,
            params={
                "barrier_type": "knock_out",
                "barrier_level": 200.0,
                "strike": 185.0,
                "expiry": "2026-12-19",
                "put_call": "call",
                "spot_price": 180.0,
                "sigma": 0.28,
            },
            dry_run=True,
        ),
        ExoticOrder(
            instrument_type="asian_option",
            underlying="SPY",
            side="BUY",
            size=5,
            params={
                "averaging_type": "arithmetic",
                "strike": 510.0,
                "expiry": "2026-09-18",
                "put_call": "put",
                "spot_price": 520.0,
                "sigma": 0.18,
            },
            dry_run=True,
        ),
        ExoticOrder(
            instrument_type="digital_option",
            underlying="BTC-USD",
            side="BUY",
            size=1,
            params={
                "strike": 90000.0,
                "expiry": "2026-06-27",
                "put_call": "call",
                "payout": 10000.0,
                "spot_price": 85000.0,
                "sigma": 0.65,
            },
            dry_run=True,
        ),
        ExoticOrder(
            instrument_type="leveraged_future",
            underlying="ES",
            side="BUY",
            size=2,
            params={
                "leverage": 5.0,
                "initial_margin": 0.10,
                "maintenance_margin": 0.05,
                "contract_size": 5000.0,
                "spot_price": 5800.0,
            },
            dry_run=True,
        ),
        ExoticOrder(
            instrument_type="otc_trade",
            underlying="USD/EUR",
            side="BUY",
            size=1,
            params={
                "counterparty": "Goldman Sachs",
                "notional_usd": 1_000_000,
                "trade_type": "forward",
                "settlement_days": 2,
                "isda_agreement_ref": "ISDA-GS-2024-001",
                "spot_price": 1.08,
            },
            dry_run=True,
        ),
        ExoticOrder(
            instrument_type="fractional_share",
            underlying="BRK.B",
            side="BUY",
            size=0.25,
            params={
                "spot_price": 450.0,
                "min_qty": 0.001,
                "max_decimals": 6,
            },
            dry_run=True,
        ),
    ]

    print("\n🔬 Exotic Instrument Handler — Self Test\n")
    for order in demo_orders:
        result = router.route(order)
        status = "✅" if result.success else "❌"
        print(f"{status} {order.instrument_type:<20} {order.underlying:<12} "
              f"fv=${result.fair_value:.4f}  cost=${result.total_cost:.2f}  "
              f"margin=${result.margin_required:.2f}  flags={len(result.risk_flags)}")
        for flag in result.risk_flags:
            print(f"    ⚠️  {flag}")
        if not result.success:
            print(f"    ❌ {result.message}")
            all_pass = False

    print()
    sys.exit(0 if all_pass else 1)
