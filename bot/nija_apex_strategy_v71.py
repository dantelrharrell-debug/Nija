"""
NIJA APEX STRATEGY v7.1
Unified algorithmic trading strategy with advanced market filters and risk management

Author: NIJA Trading Systems
Version: 7.1
Date: December 2024

ENHANCEMENTS:
- Enhanced entry scoring system (0-100 weighted score)
- Market regime detection and adaptive strategy switching
- Regime-based position sizing and thresholds
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple, List
import logging
import os

from indicators import (
    calculate_vwap, calculate_ema, calculate_rsi, calculate_macd,
    calculate_atr, calculate_adx, calculate_bollinger_bands, scalar
)
from risk_manager import RiskManager, EXTREME_VOLATILITY_ATR_PCT, _ATR_POSITION_SIZE_REFERENCE
from execution_engine import ExecutionEngine

# Import profitability assertion for configuration validation
# Initialize logger before any imports that might use it
logger = logging.getLogger("nija")

try:
    from profitability_assertion import assert_strategy_is_profitable, ProfitabilityAssertionError
    PROFITABILITY_ASSERTION_AVAILABLE = True
except ImportError:
    PROFITABILITY_ASSERTION_AVAILABLE = False
    logger.warning("Profitability assertion module not available - configuration validation disabled")

# Import exchange capabilities for SHORT entry validation and fee-aware profit targets
try:
    from exchange_capabilities import can_short, get_broker_capabilities, get_min_profit_target as _get_exchange_min_profit_target
    EXCHANGE_CAPABILITIES_AVAILABLE = True
except ImportError:
    EXCHANGE_CAPABILITIES_AVAILABLE = False
    logger.warning("Exchange capabilities module not available - SHORT validation and fee-aware targets disabled")

# Import position sizer for minimum position validation
try:
    from position_sizer import MIN_POSITION_USD, calculate_position_size as _calc_position_size
    _CALC_POSITION_SIZE_AVAILABLE = True
except ImportError:
    MIN_POSITION_USD = 2.0  # Default to $2 minimum (lowered from $5 on Jan 21, 2026)
    logger.warning("Could not import MIN_POSITION_USD from position_sizer, using default $2.00")

# Import small account constants from fee_aware_config
try:
    from fee_aware_config import (
        SMALL_ACCOUNT_THRESHOLD,
        SMALL_ACCOUNT_MAX_POSITION_PCT
    )
except ImportError:
    SMALL_ACCOUNT_THRESHOLD = 100.0  # Fallback
    SMALL_ACCOUNT_MAX_POSITION_PCT = 0.30  # Fallback — aligned with MAX_POSITION_SIZE hard limit
    logger.warning("Could not import small account constants from fee_aware_config, using defaults")

# Broker-specific minimum position sizes (Jan 24, 2026)
KRAKEN_MIN_POSITION_USD = 10.0  # Kraken requires $10 minimum trade size per exchange rules

# Minimum order sizes per broker (USD).  Keeps all four check-sites in sync
# and prevents sub-minimum orders from being scored, sized, or submitted.
# Lowered from $10 → $5 (Apr 2026) to allow micro-account setups to pass the notional gate.
BROKER_MIN_ORDER_USD: Dict[str, float] = {
    'coinbase': 5.0,    # Coinbase operational minimum — allows micro accounts ($50+) to trade
    'kraken':   5.0,    # Kraken minimum (exchange floor is ~$1; $5 is our fee-efficiency target)
    'binance':  5.0,    # Binance minimum notional
    'okx':      5.0,    # OKX minimum notional
    'alpaca':   1.0,    # Alpaca (stocks/crypto) minimum
}
_DEFAULT_MIN_ORDER_USD = 5.0   # Conservative fallback for any unlisted broker (was $10)

# Trade quality thresholds — loosened to fix 0-trade issue (entry filters too strict)
# NOTE: Kraken is the active broker; kraken_min_confidence was blocking all trades at 0.70
# (score >= 3/5 → confidence = 0.60, below 0.70 threshold).
# THRESHOLD REDUCTION (Apr 2026): Lowered from 0.50 → 0.30 to match user-account activity.
# Platform was stuck waiting while users traded on lower-confidence signals.
MIN_CONFIDENCE = 0.20  # DEBUG TEMP: relaxed confidence floor to force pipeline visibility
MAX_ENTRY_SCORE = 5.0  # Maximum entry signal score used for confidence normalization

# Volume gate for entry confirmation in check_long/short_entry.
# Widened from 0.6x to 0.4x to unlock quieter markets (where most scalps occur).
ENTRY_VOLUME_MIN_MULTIPLIER: float = 0.4

# Minimum number of the 5 legacy entry conditions that must be met to generate
# a signal.  Lowered from 3 → 2 to allow entries when only partial confirmation
# is available (e.g. price pullback + MACD tick without candlestick pattern).
LEGACY_SIGNAL_THRESHOLD: int = 2

# Borderline ATR multiplier: ATR between (BORDERLINE_ATR_FLOOR × min_atr) and min_atr
# is treated as borderline volatility — allowed with reduced position size.
BORDERLINE_ATR_FLOOR: float = 0.35  # 35% of minimum → borderline zone (was 50%)

# NIJA_MICROCAP_RELAX_SIDEWAYS: when True (default), apply a small extra
# gate_score_reduction in consolidation/ranging/sideways regimes so the bot
# stays active in low-volatility conditions without abandoning edge discipline.
import os as _os_apex  # local alias — avoids shadowing any existing `os` import
_relax_sw_raw = _os_apex.getenv("NIJA_MICROCAP_RELAX_SIDEWAYS", "true").lower()
_MICROCAP_RELAX_SIDEWAYS: bool = _relax_sw_raw not in ("0", "false", "no")
# Extra fraction added to gate_score_reduction in sideways regimes (capped at 0.20 total).
# At 0.08 a threshold of 48 becomes 48 × (1 − 0.08) = 44.2 — FAIR signals can just cross.
_MICROCAP_SIDEWAYS_GATE_REDUCTION: float = float(
    _os_apex.getenv("NIJA_MICROCAP_SIDEWAYS_GATE_REDUCTION", "0.08")
)

# ── DIAGNOSTIC / TESTING BYPASS FLAGS ────────────────────────────────────────
# NIJA_DISABLE_MARKET_FILTER=true  → skip check_market_filter entirely and allow
#   entries based purely on RSI direction.  Use ONLY for pipeline diagnostics;
#   remove or set to "false" once you confirm the signal path is working.
_DISABLE_MARKET_FILTER: bool = (
    _os_apex.getenv("NIJA_DISABLE_MARKET_FILTER", "false").lower() in ("1", "true", "yes")
)

# NIJA_BYPASS_SMART_FILTER=true  → skip check_smart_filters() (volume, candle timing,
#   news, chop/ADX) in analyze_market.  Allows signals through even in low-volume or
#   choppy markets.  Step 4 diagnostic bypass: use to confirm the smart filter is the
#   first gate that drops all signals.
#   Also activated automatically when NIJA_DEBUG_BYPASS_MODE=true.
#
# NOTE: NIJA_DEBUG_BYPASS_MODE is intentionally re-read here rather than imported
# from trading_strategy.py.  nija_apex_strategy_v71 is imported BY trading_strategy,
# so a reverse import would create a circular dependency.  The env-var read is the
# correct pattern for this architecture.
_BYPASS_SMART_FILTER: bool = (
    _os_apex.getenv("NIJA_BYPASS_SMART_FILTER", "false").lower() in ("1", "true", "yes")
    or _os_apex.getenv("NIJA_DEBUG_BYPASS_MODE", "false").lower() in ("1", "true", "yes")
)

# NIJA_CONSOLIDATION_SCALP=true  (default) — when check_market_filter returns
#   'none' (no clear trend), use RSI to pick a direction and attempt a scalp entry
#   instead of immediately returning 'hold'.  RSI > _SCALP_RSI_LONG → try long;
#   RSI < _SCALP_RSI_SHORT → try short.
_CONSOLIDATION_SCALP: bool = (
    _os_apex.getenv("NIJA_CONSOLIDATION_SCALP", "true").lower() not in ("0", "false", "no")
)

# RSI thresholds used by the bypass and consolidation scalp paths.
# Kept as named constants so both code sites stay in sync.
_SCALP_RSI_LONG: float = float(_os_apex.getenv("NIJA_SCALP_RSI_LONG", "52"))   # RSI above this → long scalp
_SCALP_RSI_SHORT: float = float(_os_apex.getenv("NIJA_SCALP_RSI_SHORT", "48")) # RSI below this → short scalp

# Import adaptive minimum sizing engine (Mar 2026)
try:
    from adaptive_minimum_sizing import get_adaptive_minimum_sizer, AdaptiveMinimumSizer
    ADAPTIVE_MIN_SIZING_AVAILABLE = True
except ImportError:
    try:
        from bot.adaptive_minimum_sizing import get_adaptive_minimum_sizer, AdaptiveMinimumSizer
        ADAPTIVE_MIN_SIZING_AVAILABLE = True
    except ImportError:
        ADAPTIVE_MIN_SIZING_AVAILABLE = False
        get_adaptive_minimum_sizer = None  # type: ignore
        AdaptiveMinimumSizer = None  # type: ignore
        logger.warning("Adaptive minimum sizing module not available – using static broker minimums")

# Import emergency liquidation for capital preservation (FIX 3)
try:
    from emergency_liquidation import EmergencyLiquidator
    EMERGENCY_LIQUIDATION_AVAILABLE = True
except ImportError:
    EMERGENCY_LIQUIDATION_AVAILABLE = False
    logger.warning("Emergency liquidation module not available")

# Import enhanced entry scoring and regime detection
try:
    from enhanced_entry_scoring import EnhancedEntryScorer
    from market_regime_detector import RegimeDetector, MarketRegime
    ENHANCED_SCORING_AVAILABLE = True
except ImportError:
    ENHANCED_SCORING_AVAILABLE = False
    logger.warning("Enhanced scoring and regime detection modules not available - using basic scoring")

# Import entry optimizer (RSI divergence, Bollinger Band zone, volume pattern)
try:
    from entry_optimizer import get_entry_optimizer, EntryOptimizer
    ENTRY_OPTIMIZER_AVAILABLE = True
except ImportError:
    try:
        from bot.entry_optimizer import get_entry_optimizer, EntryOptimizer
        ENTRY_OPTIMIZER_AVAILABLE = True
    except ImportError:
        ENTRY_OPTIMIZER_AVAILABLE = False
        get_entry_optimizer = None  # type: ignore
        EntryOptimizer = None  # type: ignore
        logger.warning("Entry optimizer not available – running without RSI divergence / BB zone optimizations")

# Import AI Intelligence Hub (AI Market Regime Detection + Portfolio Risk Engine +
# Capital Allocation AI).  All three components are optional – the strategy degrades
# gracefully when any of them is unavailable.
try:
    from ai_intelligence_hub import get_ai_intelligence_hub, AIIntelligenceHub
    AI_HUB_AVAILABLE = True
except ImportError:
    AI_HUB_AVAILABLE = False
    get_ai_intelligence_hub = None  # type: ignore
    AIIntelligenceHub = None  # type: ignore
    logger.warning("AI Intelligence Hub not available – running without AI regime / risk / allocation layer")

# Import profit optimization stack (all three are optional – graceful degradation)
# ProfitHarvestLayer: ratchet-tier profit locking + partial harvests
# PortfolioProfitFlywheel: compound-growth multiplier driven by cumulative wins
# CapitalRecyclingEngine: routes harvested profits to top-performing strategies
try:
    from bot.profit_harvest_layer import get_profit_harvest_layer, ProfitHarvestLayer
    from bot.portfolio_profit_flywheel import get_portfolio_profit_flywheel, PortfolioProfitFlywheel
    from bot.capital_recycling_engine import get_capital_recycling_engine, CapitalRecyclingEngine
    PROFIT_STACK_AVAILABLE = True
except ImportError:
    try:
        from profit_harvest_layer import get_profit_harvest_layer, ProfitHarvestLayer
        from portfolio_profit_flywheel import get_portfolio_profit_flywheel, PortfolioProfitFlywheel
        from capital_recycling_engine import get_capital_recycling_engine, CapitalRecyclingEngine
        PROFIT_STACK_AVAILABLE = True
    except ImportError:
        get_profit_harvest_layer = None  # type: ignore
        get_portfolio_profit_flywheel = None  # type: ignore
        get_capital_recycling_engine = None  # type: ignore
        PROFIT_STACK_AVAILABLE = False
        logger.warning("Profit optimization stack not available – running without harvest/flywheel/recycling")

# Import Safe Profit Mode (daily gate that blocks new entries once profit is locked)
try:
    from bot.safe_profit_mode import get_safe_profit_mode, SafeProfitModeManager
    SAFE_PROFIT_MODE_AVAILABLE = True
except ImportError:
    try:
        from safe_profit_mode import get_safe_profit_mode, SafeProfitModeManager
        SAFE_PROFIT_MODE_AVAILABLE = True
    except ImportError:
        get_safe_profit_mode = None  # type: ignore
        SafeProfitModeManager = None  # type: ignore
        SAFE_PROFIT_MODE_AVAILABLE = False
        logger.warning("Safe Profit Mode not available – running without daily profit gate")

# Import Smart Reinvest Cycles (re-deploys locked profits only when conditions are perfect)
try:
    from bot.smart_reinvest_cycles import get_smart_reinvest_engine, SmartReinvestCycleEngine
    SMART_REINVEST_AVAILABLE = True
except ImportError:
    try:
        from smart_reinvest_cycles import get_smart_reinvest_engine, SmartReinvestCycleEngine
        SMART_REINVEST_AVAILABLE = True
    except ImportError:
        get_smart_reinvest_engine = None  # type: ignore
        SmartReinvestCycleEngine = None  # type: ignore
        SMART_REINVEST_AVAILABLE = False
        logger.warning("Smart Reinvest Cycles not available – running without condition-gated reinvestment")

# ── Industry Principle #2: Adaptive multi-regime strategy bridge ───────────
# Maps detected regime → complete parameter set (RSI, confidence, sizing, SL/TP)
try:
    from bot.regime_strategy_bridge import get_regime_strategy_bridge, RegimeTradingParams, StrategyType
    REGIME_BRIDGE_AVAILABLE = True
    logger.info("✅ Regime Strategy Bridge loaded — adaptive multi-regime strategy active")
except ImportError:
    try:
        from regime_strategy_bridge import get_regime_strategy_bridge, RegimeTradingParams, StrategyType
        REGIME_BRIDGE_AVAILABLE = True
        logger.info("✅ Regime Strategy Bridge loaded — adaptive multi-regime strategy active")
    except ImportError:
        get_regime_strategy_bridge = None  # type: ignore
        RegimeTradingParams = None  # type: ignore
        StrategyType = None  # type: ignore
        REGIME_BRIDGE_AVAILABLE = False
        logger.warning("⚠️ Regime Strategy Bridge not available — using static RSI ranges")

# ── Industry Principle #3: Risk-per-trade position sizer (ATR-based) ──────
# Sizes positions based on stop-loss distance, not raw balance percentage
try:
    from bot.risk_per_trade_sizer import get_risk_per_trade_sizer, RiskSizingResult
    RISK_PER_TRADE_SIZER_AVAILABLE = True
    logger.info("✅ Risk-Per-Trade Sizer loaded — ATR-based position sizing active")
except ImportError:
    try:
        from risk_per_trade_sizer import get_risk_per_trade_sizer, RiskSizingResult
        RISK_PER_TRADE_SIZER_AVAILABLE = True
        logger.info("✅ Risk-Per-Trade Sizer loaded — ATR-based position sizing active")
    except ImportError:
        get_risk_per_trade_sizer = None  # type: ignore
        RiskSizingResult = None  # type: ignore
        RISK_PER_TRADE_SIZER_AVAILABLE = False
        logger.warning("⚠️ Risk-Per-Trade Sizer not available — using balance-percentage sizing")

# ── Industry Principle #5: Scalp mode optimizer (high-frequency micro-trades) ─
# Activates tight-stop, quick-TP scalping when regime is CONSOLIDATION/RANGING
try:
    from bot.scalp_mode_optimizer import get_scalp_mode_optimizer, ScalpConfig
    SCALP_MODE_OPTIMIZER_AVAILABLE = True
    logger.info("✅ Scalp Mode Optimizer loaded — high-frequency micro-scalp mode active")
except ImportError:
    try:
        from scalp_mode_optimizer import get_scalp_mode_optimizer, ScalpConfig
        SCALP_MODE_OPTIMIZER_AVAILABLE = True
        logger.info("✅ Scalp Mode Optimizer loaded — high-frequency micro-scalp mode active")
    except ImportError:
        get_scalp_mode_optimizer = None  # type: ignore
        ScalpConfig = None  # type: ignore
        SCALP_MODE_OPTIMIZER_AVAILABLE = False
        logger.warning("⚠️ Scalp Mode Optimizer not available — standard entry logic in use")

# ── 5-Gate AI Entry Confirmation ─────────────────────────────────────────────
# All 5 gates must pass: AI score / volume / volatility / spread / regime
try:
    from bot.ai_entry_gate import get_ai_entry_gate, GateResult
    AI_ENTRY_GATE_AVAILABLE = True
    logger.info("✅ AI Entry Gate loaded — 5-gate entry confirmation active")
except ImportError:
    try:
        from ai_entry_gate import get_ai_entry_gate, GateResult
        AI_ENTRY_GATE_AVAILABLE = True
        logger.info("✅ AI Entry Gate loaded — 5-gate entry confirmation active")
    except ImportError:
        get_ai_entry_gate = None  # type: ignore
        GateResult = None  # type: ignore
        AI_ENTRY_GATE_AVAILABLE = False
        logger.warning("⚠️ AI Entry Gate not available — single-pass entry logic in use")

# ── Centralized Execution & Exit Configuration ───────────────────────────────
# Hard SL 1–1.2%, trailing activate 1.8%, buffer 0.6%, 4 strategy profiles
try:
    from bot.execution_exit_config import get_execution_exit_config, ExitParams, StratProfile
    EXECUTION_EXIT_CONFIG_AVAILABLE = True
    logger.info("✅ Execution Exit Config loaded — regime-aware SL/TP/trailing active")
except ImportError:
    try:
        from execution_exit_config import get_execution_exit_config, ExitParams, StratProfile
        EXECUTION_EXIT_CONFIG_AVAILABLE = True
        logger.info("✅ Execution Exit Config loaded — regime-aware SL/TP/trailing active")
    except ImportError:
        get_execution_exit_config = None  # type: ignore
        ExitParams = None  # type: ignore
        StratProfile = None  # type: ignore
        EXECUTION_EXIT_CONFIG_AVAILABLE = False
        logger.warning("⚠️ Execution Exit Config not available — using legacy SL/TP logic")

# ── Drawdown Risk Controller ──────────────────────────────────────────────────
# Max drawdown halt + daily loss limit + ATR dynamic sizing + market conditions
try:
    from bot.drawdown_risk_controller import get_drawdown_risk_controller, RiskEnvelopeResult
    DRAWDOWN_RISK_CONTROLLER_AVAILABLE = True
    logger.info("✅ Drawdown Risk Controller loaded — 4-layer risk envelope active")
except ImportError:
    try:
        from drawdown_risk_controller import get_drawdown_risk_controller, RiskEnvelopeResult
        DRAWDOWN_RISK_CONTROLLER_AVAILABLE = True
        logger.info("✅ Drawdown Risk Controller loaded — 4-layer risk envelope active")
    except ImportError:
        get_drawdown_risk_controller = None  # type: ignore
        RiskEnvelopeResult = None  # type: ignore
        DRAWDOWN_RISK_CONTROLLER_AVAILABLE = False
        logger.warning("⚠️ Drawdown Risk Controller not available — basic drawdown logic only")

# ── Nija AI Engine — unified rank-first entry coordinator ────────────────────
# Aggregates EnhancedEntryScorer + EntryOptimizer + AIEntryGate into one call,
# ranks all candidate symbols, and returns top-N with adaptive thresholds.
try:
    from bot.nija_ai_engine import get_nija_ai_engine, NijaAIEngine, AIEngineSignal
    NIJA_AI_ENGINE_AVAILABLE = True
    logger.info("✅ Nija AI Engine loaded — rank-first adaptive entry coordinator active")
except ImportError:
    try:
        from nija_ai_engine import get_nija_ai_engine, NijaAIEngine, AIEngineSignal
        NIJA_AI_ENGINE_AVAILABLE = True
        logger.info("✅ Nija AI Engine loaded — rank-first adaptive entry coordinator active")
    except ImportError:
        get_nija_ai_engine = None  # type: ignore
        NijaAIEngine = None  # type: ignore
        AIEngineSignal = None  # type: ignore
        NIJA_AI_ENGINE_AVAILABLE = False
        logger.warning("⚠️ Nija AI Engine not available — falling back to sequential gate logic")

# ── Nija Core Loop — rebuilt single-pass scan / rank / enter loop ─────────────
try:
    from bot.nija_core_loop import get_nija_core_loop, NijaCoreLoop
    NIJA_CORE_LOOP_AVAILABLE = True
    logger.info("✅ Nija Core Loop loaded — clean single-pass loop active")
except ImportError:
    try:
        from nija_core_loop import get_nija_core_loop, NijaCoreLoop
        NIJA_CORE_LOOP_AVAILABLE = True
        logger.info("✅ Nija Core Loop loaded — clean single-pass loop active")
    except ImportError:
        get_nija_core_loop = None  # type: ignore
        NijaCoreLoop = None  # type: ignore
        NIJA_CORE_LOOP_AVAILABLE = False
        logger.warning("⚠️ Nija Core Loop not available — using legacy run_cycle dispatch")

# ── Trade Frequency Controller — minimum trade safeguard ─────────────────────
# Tracks trade cadence and relaxes filters when no trade in drought_window hours.
try:
    from bot.trade_frequency_controller import (
        get_trade_frequency_controller, DroughtRelaxation,
    )
    TRADE_FREQ_CTRL_AVAILABLE = True
    logger.info("✅ Trade Frequency Controller loaded — drought safeguard active")
except ImportError:
    try:
        from trade_frequency_controller import (
            get_trade_frequency_controller, DroughtRelaxation,
        )
        TRADE_FREQ_CTRL_AVAILABLE = True
        logger.info("✅ Trade Frequency Controller loaded — drought safeguard active")
    except ImportError:
        get_trade_frequency_controller = None  # type: ignore
        DroughtRelaxation = None  # type: ignore
        TRADE_FREQ_CTRL_AVAILABLE = False
        logger.warning("⚠️ Trade Frequency Controller not available — no drought safeguard")

# ── Momentum Entry Filter — simple 2-3 condition OR-logic entries ─────────────
# Fires when institutional check misses: RSI momentum + volume/breakout confirm.
try:
    from bot.momentum_entry_filter import (
        check_momentum_long, check_momentum_short,
        check_breakout_long, check_breakout_short,
    )
    MOMENTUM_ENTRY_AVAILABLE = True
    logger.info("✅ Momentum Entry Filter loaded — fast RSI+breakout entries active")
except ImportError:
    try:
        from momentum_entry_filter import (
            check_momentum_long, check_momentum_short,
            check_breakout_long, check_breakout_short,
        )
        MOMENTUM_ENTRY_AVAILABLE = True
        logger.info("✅ Momentum Entry Filter loaded — fast RSI+breakout entries active")
    except ImportError:
        check_momentum_long = None   # type: ignore
        check_momentum_short = None  # type: ignore
        check_breakout_long = None   # type: ignore
        check_breakout_short = None  # type: ignore
        MOMENTUM_ENTRY_AVAILABLE = False
        logger.warning("⚠️ Momentum Entry Filter not available — institutional entry only")

# True Profit Tracker — realized P&L after fees, account growth, daily PnL,
# win rate, avg profit/trade.  Logs NET PROFIT and NEW CASH BALANCE after
# every full close.
try:
    from true_profit_tracker import get_true_profit_tracker as _get_true_profit_tracker
    TRUE_PROFIT_TRACKER_AVAILABLE = True
except ImportError:
    try:
        from bot.true_profit_tracker import get_true_profit_tracker as _get_true_profit_tracker
        TRUE_PROFIT_TRACKER_AVAILABLE = True
    except ImportError:
        _get_true_profit_tracker = None  # type: ignore
        TRUE_PROFIT_TRACKER_AVAILABLE = False
        logger.warning("⚠️ TrueProfitTracker not available — true P&L logging disabled")

# ── Cycle Barrier Scheduler — atomic 4-signal capture per tick ───────────────
# Ensures RSI_9, RSI_14, MACD histogram, and market regime are all read from
# the same DataFrame snapshot before any entry gate runs, eliminating the
# one-cycle lag that previously made activation non-deterministic.
try:
    from cycle_barrier_scheduler import get_cycle_barrier_scheduler, CycleBarrierScheduler
    CYCLE_BARRIER_AVAILABLE = True
    logger.info("✅ Cycle Barrier Scheduler loaded — atomic 4-signal capture active")
except ImportError:
    try:
        from bot.cycle_barrier_scheduler import get_cycle_barrier_scheduler, CycleBarrierScheduler
        CYCLE_BARRIER_AVAILABLE = True
        logger.info("✅ Cycle Barrier Scheduler loaded — atomic 4-signal capture active")
    except ImportError:
        get_cycle_barrier_scheduler = None  # type: ignore
        CycleBarrierScheduler = None  # type: ignore
        CYCLE_BARRIER_AVAILABLE = False
        logger.warning("⚠️ Cycle Barrier Scheduler not available — regime may lag by one cycle")


class NIJAApexStrategyV71:
    """
    NIJA Apex Strategy v7.1 - Unified Algorithmic Trading System

    Features:
    1.  Market Filter (uptrend/downtrend using VWAP, EMA9/21/50, MACD, ADX>20, Volume)
    2.  Entry Logic (pullback to EMA21/VWAP, RSI, candlestick patterns, MACD tick, volume)
    3.  Enhanced Entry Scoring (0-100 weighted multi-factor scoring)
    4.  Market Regime Detection (trending/ranging/volatile)
    5.  Adaptive Strategy Switching (regime-based parameters via RegimeStrategyBridge)
    6.  Dynamic Risk Management (ATR-based risk-per-trade sizing, stop loss)
    7.  Exit Logic (opposite signal, trailing stop, trend break, time-based)
    8.  Smart Filters (news, volume, candle timing)
    9.  Optional: AI Momentum Scoring (skeleton)
    10. Profit Optimization Stack (harvest layer + flywheel compounding + capital recycling)
    11. Scalp Mode (high-frequency micro-trades in CONSOLIDATION/RANGING regimes)
    12. 5-Gate AI Entry Confirmation (Score / Volume / Volatility / Spread / Regime)
    13. Centralized SL/TP/Trailing Config (4 profiles: SCALP/SWING/BREAKOUT/MEAN_REVERSION)
    14. 4-Layer Drawdown Risk Controller (CB + daily loss + ATR sizing + market conditions)
    """

    def __init__(self, broker_client=None, config: Optional[Dict] = None):
        """
        Initialize NIJA Apex Strategy v7.1

        Args:
            broker_client: Broker API client (Coinbase, Alpaca, Binance, etc.)
            config: Strategy configuration dictionary
        """
        self.broker_client = broker_client
        self.config = config or {}

        # PROFIT OPTIMIZATION: Load enhanced configuration if not provided
        # Check if a comprehensive config was provided by looking for key optimization settings
        has_comprehensive_config = (
            'use_enhanced_scoring' in self.config or
            'use_regime_detection' in self.config or
            'enable_stepped_exits' in self.config
        )

        if not has_comprehensive_config:  # If basic/empty config, use optimized defaults
            try:
                from profit_optimization_config import get_profit_optimization_config
                self.config = get_profit_optimization_config()
                logger.info("🚀 Loaded profit optimization configuration")
            except ImportError:
                logger.warning("⚠️  Profit optimization config not available, using defaults")

        # PROFIT-TAKING ENFORCEMENT: Always enabled, cannot be disabled
        # This ensures profit-taking works 24/7 on all accounts, brokerages, and tiers
        self.config['enable_take_profit'] = True

        # Initialize components with optimized parameters
        self.risk_manager = RiskManager(
            min_position_pct=self.config.get('min_position_pct', 0.02),
            max_position_pct=self.config.get('max_position_pct', 0.10),  # OPTIMIZED: 10% max for more positions (was 20%)
            soft_position_limit_pct=0.25,   # Warn at 25% — aligned with MAX_POSITION_SIZE = 0.30
            hard_position_limit_pct=0.30,   # Block above 30% — MAX_POSITION_SIZE hard limit
        )
        self.execution_engine = ExecutionEngine(broker_client)

        # Cycle-level P&L accumulator: reset each cycle by TradingStrategy.run_cycle()
        self._cycle_pnl = 0.0

        # Initialize enhanced scoring and regime detection
        # PROFIT OPTIMIZATION: Enable by default if available
        enable_enhanced = self.config.get('use_enhanced_scoring', True)  # Default to True
        enable_regime = self.config.get('use_regime_detection', True)  # Default to True

        if ENHANCED_SCORING_AVAILABLE and (enable_enhanced or enable_regime):
            self.entry_scorer = EnhancedEntryScorer(self.config)
            self.regime_detector = RegimeDetector(self.config)
            self.use_enhanced_scoring = True
            logger.info("✅ Enhanced entry scoring and regime detection enabled")
        else:
            self.entry_scorer = None
            self.regime_detector = None
            self.use_enhanced_scoring = False
            if not ENHANCED_SCORING_AVAILABLE:
                logger.warning("⚠️  Enhanced scoring modules not available - using legacy scoring")
            else:
                logger.info("ℹ️  Enhanced scoring disabled by configuration")

        # Entry optimizer: RSI divergence, Bollinger Band zone, volume pattern
        if ENTRY_OPTIMIZER_AVAILABLE and get_entry_optimizer is not None:
            self.entry_optimizer = get_entry_optimizer()
            logger.info("✅ Entry optimizer enabled (RSI divergence + BB zone + volume pattern)")
        else:
            self.entry_optimizer = None

        # Nija AI Engine: unified rank-first adaptive entry coordinator
        if NIJA_AI_ENGINE_AVAILABLE and get_nija_ai_engine is not None:
            self.nija_ai_engine = get_nija_ai_engine()
            logger.info("✅ Nija AI Engine enabled — rank-first adaptive scoring active")
        else:
            self.nija_ai_engine = None

        # Trade Frequency Controller — minimum trade safeguard + drought detection
        if TRADE_FREQ_CTRL_AVAILABLE and get_trade_frequency_controller is not None:
            try:
                self._freq_ctrl = get_trade_frequency_controller()
                logger.info("✅ Trade Frequency Controller enabled — drought safeguard active")
            except Exception as _freq_err:
                logger.warning("Trade Frequency Controller init error: %s", _freq_err)
                self._freq_ctrl = None
        else:
            self._freq_ctrl = None

        # Strategy parameters - OPTIMIZED FOR HIGH WIN RATE
        # OPTIMIZATION (Jan 29, 2026): Rebalance filters for quality trades
        # Previous emergency relaxations prioritized quantity over quality (ADX=6, volume=0.1%)
        # New strategy: Moderate filters to capture trending markets with real volume
        # Target: 60-65% win rate with 5-10 quality trades per day
        self.min_adx = min(self.config.get('min_adx', 5), 5)  # DEBUG TEMP: cap ADX threshold at 5 to force trade flow
        self.volume_threshold = min(self.config.get('volume_threshold', 0.005), 0.005)  # DEBUG TEMP: MIN_VOLATILITY 0.5% equivalent for easier entries
        self.volume_min_threshold = self.config.get('volume_min_threshold', 0.002)  # OPTIMIZED: Filter very low volume (was 0.001, 2x stricter)
        self.min_trend_confirmation = self.config.get('min_trend_confirmation', 1)  # TUNED: Lowered from 2 → 1 (Apr 2026) so a single confirmed condition (e.g. VWAP or MACD) is enough to attempt an entry; the AI scoring layers downstream still gate quality
        self.candle_exclusion_seconds = self.config.get('candle_exclusion_seconds', 2)  # OPTIMIZED: Re-enabled to avoid false breakouts (was 0)
        self.news_buffer_minutes = self.config.get('news_buffer_minutes', 5)

        # PROFIT OPTIMIZATION: Stepped profit-taking configuration
        # Default targets are conservative Coinbase-compatible values used only for
        # profitability validation.  The execution engine dynamically selects the
        # actual broker-specific thresholds at runtime (1.0%/1.5%/2.5%/4.0% for Kraken,
        # 2.0%/2.5%/3.5%/5.0% for Coinbase) — see execution_engine.check_stepped_profit_exits.
        self.enable_stepped_exits = self.config.get('enable_stepped_exits', True)
        self.stepped_exit_levels = self.config.get('stepped_exits', {
            0.030: 0.10,  # Exit 10% at 3.0% profit  (TP upgrade — Apr 2026)
            0.040: 0.15,  # Exit 15% at 4.0% profit
            0.055: 0.25,  # Exit 25% at 5.5% profit
            0.070: 0.50,  # Exit 50% at 7.0% profit  (gross R:R = 7.0/1.2 = 5.8:1 at -1.2% stop)
        })

        # AI Momentum Scoring (optional, skeleton for future)
        self.ai_momentum_enabled = self.config.get('ai_momentum_enabled', False)

        # AI Intelligence Hub: Market Regime Detection + Portfolio Risk Engine +
        # Capital Allocation AI.  Enabled by default when the module is available.
        enable_ai_hub = self.config.get('use_ai_intelligence_hub', True)
        if AI_HUB_AVAILABLE and enable_ai_hub:
            ai_hub_config = self.config.get('ai_hub_config', {})
            self.ai_hub = get_ai_intelligence_hub(ai_hub_config)
            self.use_ai_hub = True
            logger.info("✅ AI Intelligence Hub: ENABLED (Regime AI + Portfolio Risk + Capital Brain)")
        else:
            self.ai_hub = None
            self.use_ai_hub = False
            if not AI_HUB_AVAILABLE:
                logger.warning("⚠️  AI Intelligence Hub not available")
            else:
                logger.info("ℹ️  AI Intelligence Hub disabled by configuration")

        # PROFIT OPTIMIZATION STACK
        # Three cooperative engines that turn every realised profit into compounding growth:
        #   1. ProfitHarvestLayer  – ratchet-tier locks + on-tier-upgrade partial harvests
        #   2. PortfolioProfitFlywheel – cumulative-profit-driven position-size multiplier
        #   3. CapitalRecyclingEngine  – routes harvested amounts to top-performing strategies
        # All three degrade gracefully when unavailable.
        enable_profit_stack = self.config.get('enable_profit_stack', True)
        if PROFIT_STACK_AVAILABLE and enable_profit_stack:
            try:
                self.profit_harvest_layer = get_profit_harvest_layer()
                self.portfolio_profit_flywheel = get_portfolio_profit_flywheel()
                self.capital_recycling_engine = get_capital_recycling_engine()
                logger.info("✅ Profit Optimization Stack: ENABLED")
                logger.info("   ├─ ProfitHarvestLayer  (ratchet-tier locks + partial harvests)")
                logger.info("   ├─ PortfolioProfitFlywheel (compound-growth multiplier)")
                logger.info("   └─ CapitalRecyclingEngine  (harvest → best-strategy routing)")
            except Exception as _pstack_err:
                logger.warning(f"⚠️  Profit stack init failed – degrading gracefully: {_pstack_err}")
                self.profit_harvest_layer = None
                self.portfolio_profit_flywheel = None
                self.capital_recycling_engine = None
        else:
            self.profit_harvest_layer = None
            self.portfolio_profit_flywheel = None
            self.capital_recycling_engine = None
            if not PROFIT_STACK_AVAILABLE:
                logger.warning("⚠️  Profit optimization stack not available")

        # SAFE PROFIT MODE: Protects ratchet-locked profits by blocking new entries
        # once ≥ 80% of today's accumulated P&L is already secured in the harvest layer.
        # NOTE: Dollar-target-based activation is DISABLED.  The system follows EDGE only
        # and never stops trading because it "hit a number".  The only valid activation
        # path is the locked-profit fraction guard (lock_fraction_threshold).
        enable_safe_profit_mode = self.config.get('enable_safe_profit_mode', True)
        if SAFE_PROFIT_MODE_AVAILABLE and enable_safe_profit_mode:
            try:
                self.safe_profit_mode = get_safe_profit_mode(
                    target_pct_threshold=self.config.get('safe_profit_target_pct_threshold', 1.0),
                    lock_fraction_threshold=self.config.get('safe_profit_lock_fraction_threshold', 0.80),
                )
                logger.info("✅ Safe Profit Mode: ENABLED (locked-profit guard only — no dollar target)")
            except Exception as _spm_err:
                logger.warning(f"⚠️  Safe Profit Mode init failed – degrading gracefully: {_spm_err}")
                self.safe_profit_mode = None
        else:
            self.safe_profit_mode = None
            if not SAFE_PROFIT_MODE_AVAILABLE:
                logger.warning("⚠️  Safe Profit Mode not available")

        # Running daily P&L tracker — used only for locked-profit computation.
        # _last_daily_target_usd is permanently 0: target-ratio activation is disabled
        # so SafeProfitModeManager's Condition 1 (target-based block) never fires.
        self._daily_pnl_usd: float = 0.0
        self._last_daily_target_usd: float = 0.0   # always 0 — edge-driven, not target-driven

        # True Profit Tracker — realized net P&L, account growth, win rate.
        if TRUE_PROFIT_TRACKER_AVAILABLE and _get_true_profit_tracker is not None:
            try:
                self._true_profit_tracker = _get_true_profit_tracker()
            except Exception as _tpt_init_err:
                logger.warning("TrueProfitTracker init failed: %s", _tpt_init_err)
                self._true_profit_tracker = None
        else:
            self._true_profit_tracker = None

        # SMART REINVEST CYCLES: Re-deploy locked profits only when conditions are perfect.
        # Gates capital redeployment through 7 simultaneous condition checks:
        #   1. Regime Gate       – regime not in blocked list
        #   2. Volatility Gate   – no SEVERE/EXTREME shock
        #   3. Risk Governor     – no circuit breakers active
        #   4. Strategy Health   – strategy is tradeable (≥ WATCHING)
        #   5. Win Rate Gate     – rolling win rate ≥ floor
        #   6. Pool Gate         – recycling pool has minimum balance
        #   7. Cooldown Gate     – minimum cooldown elapsed since last deploy
        enable_smart_reinvest = self.config.get('enable_smart_reinvest', True)
        if SMART_REINVEST_AVAILABLE and enable_smart_reinvest:
            try:
                self.smart_reinvest_engine = get_smart_reinvest_engine()
                logger.info("✅ Smart Reinvest Cycles: ENABLED (re-deploy locked profits when conditions are perfect)")
            except Exception as _sri_err:
                logger.warning(f"⚠️  Smart Reinvest Cycles init failed – degrading gracefully: {_sri_err}")
                self.smart_reinvest_engine = None
        else:
            self.smart_reinvest_engine = None
            if not SMART_REINVEST_AVAILABLE:
                logger.warning("⚠️  Smart Reinvest Cycles not available")

        # PROFITABILITY ASSERTION: Validate strategy configuration (CRITICAL GUARD RAIL)
        # This prevents deployment of unprofitable configurations that would lose money after fees
        # Added as part of profitability assertion pass (Feb 2026)
        self._validate_profitability_configuration()

        # Track last candle time for timing filter (per-symbol to avoid cross-market contamination)
        self.last_candle_times = {}  # symbol -> timestamp

        # Track current regime for logging
        self.current_regime = None

        # ── Industry Principle #2: Regime Strategy Bridge ────────────────────
        # Provides complete parameter sets per detected regime (RSI, confidence,
        # position multiplier, SL/TP) so the strategy adapts dynamically.
        if REGIME_BRIDGE_AVAILABLE and get_regime_strategy_bridge is not None:
            try:
                self.regime_bridge = get_regime_strategy_bridge()
                logger.info("✅ Regime Strategy Bridge: ENABLED (adaptive multi-regime)")
            except Exception as _rb_err:
                logger.warning("⚠️  Regime Strategy Bridge init failed: %s", _rb_err)
                self.regime_bridge = None
        else:
            self.regime_bridge = None

        # ── Industry Principle #3: Risk-Per-Trade Sizer ──────────────────────
        # Sizes every position by stop-loss distance, not raw balance percentage.
        if RISK_PER_TRADE_SIZER_AVAILABLE and get_risk_per_trade_sizer is not None:
            try:
                self.risk_per_trade_sizer = get_risk_per_trade_sizer()
                logger.info("✅ Risk-Per-Trade Sizer: ENABLED (ATR-based sizing)")
            except Exception as _rpts_err:
                logger.warning("⚠️  Risk-Per-Trade Sizer init failed: %s", _rpts_err)
                self.risk_per_trade_sizer = None
        else:
            self.risk_per_trade_sizer = None

        # ── Industry Principle #5: Scalp Mode Optimizer ──────────────────────
        # Activates tight-stop, quick-TP micro-scalping when regime permits.
        if SCALP_MODE_OPTIMIZER_AVAILABLE and get_scalp_mode_optimizer is not None:
            try:
                self.scalp_optimizer = get_scalp_mode_optimizer()
                logger.info("✅ Scalp Mode Optimizer: ENABLED (micro-scalp in CONSOLIDATION/RANGING)")
            except Exception as _smo_err:
                logger.warning("⚠️  Scalp Mode Optimizer init failed: %s", _smo_err)
                self.scalp_optimizer = None
        else:
            self.scalp_optimizer = None

        # ── 5-Gate AI Entry Confirmation ─────────────────────────────────────
        # Gates: AI Score / Volume Liquidity / Volatility Range / Spread / Regime
        if AI_ENTRY_GATE_AVAILABLE and get_ai_entry_gate is not None:
            try:
                self.ai_entry_gate = get_ai_entry_gate()
                logger.info("✅ AI Entry Gate: ENABLED (5-gate entry confirmation)")
            except Exception as _aeg_err:
                logger.warning("⚠️  AI Entry Gate init failed: %s", _aeg_err)
                self.ai_entry_gate = None
        else:
            self.ai_entry_gate = None

        # ── Centralized Execution & Exit Config ───────────────────────────────
        # Hard SL 1–1.2%, trailing @ 1.8%, 4 profiles: SCALP/SWING/BREAKOUT/MEAN_REV
        if EXECUTION_EXIT_CONFIG_AVAILABLE and get_execution_exit_config is not None:
            try:
                self.exit_config = get_execution_exit_config()
                logger.info("✅ Execution Exit Config: ENABLED (regime-aware SL/TP/trailing)")
            except Exception as _exc_err:
                logger.warning("⚠️  Execution Exit Config init failed: %s", _exc_err)
                self.exit_config = None
        else:
            self.exit_config = None

        # ── 4-Layer Drawdown Risk Controller ─────────────────────────────────
        # CB + daily loss limit + ATR-dynamic sizing + market condition pre-filter
        if DRAWDOWN_RISK_CONTROLLER_AVAILABLE and get_drawdown_risk_controller is not None:
            try:
                self.drawdown_risk_ctrl = get_drawdown_risk_controller()
                logger.info("✅ Drawdown Risk Controller: ENABLED (4-layer risk envelope)")
            except Exception as _drc_err:
                logger.warning("⚠️  Drawdown Risk Controller init failed: %s", _drc_err)
                self.drawdown_risk_ctrl = None
        else:
            self.drawdown_risk_ctrl = None

        # ── Cycle Barrier Scheduler — atomic 4-signal capture ────────────────
        # One scheduler instance per strategy so barrier captures are scoped
        # to this symbol's analysis and do not interfere with concurrent instances.
        if CYCLE_BARRIER_AVAILABLE and get_cycle_barrier_scheduler is not None:
            try:
                self._cycle_barrier = get_cycle_barrier_scheduler()
                logger.info("✅ Cycle Barrier Scheduler: ENABLED (atomic 4-signal capture)")
            except (TypeError, AttributeError, RuntimeError) as _cb_err:
                logger.warning("⚠️  Cycle Barrier Scheduler init failed: %s", _cb_err)
                self._cycle_barrier = None
        else:
            self._cycle_barrier = None

        # Per-call state: risk envelope multiplier from drawdown controller
        # Updated at start of each analyze_market call and used in position sizing
        self._risk_envelope_multiplier: float = 1.0

        # Per-call state: active exit params resolved per analyze_market call
        self._active_exit_params = None   # ExitParams | None

        # Per-symbol cooldown tracking (re-entry cooldown from exit config)
        self._symbol_last_trade_time: dict = {}   # symbol → float (unix timestamp)
        
        # Kraken-specific tuning parameters (Jan 30, 2026)
        # These can be adjusted via environment variables for safe tuning
        # Kraken-specific safety thresholds — loosened to fix 0-trade issue.
        # Previous values (RSI 35-65, confidence 0.70, ATR 0.6%) were blocking
        # all signals since legacy_score=3 → confidence=0.60 < 0.70.
        self.kraken_min_rsi = float(os.getenv('KRAKEN_MIN_RSI', '28'))
        self.kraken_max_rsi = float(os.getenv('KRAKEN_MAX_RSI', '72'))
        self.kraken_min_confidence = float(os.getenv('KRAKEN_MIN_CONFIDENCE', '0.30'))
        self.kraken_min_atr_pct = float(os.getenv('KRAKEN_MIN_ATR_PCT', '0.4'))
        
        # Track first trade for sanity check logging
        self.first_trade_attempted = False

        logger.info("=" * 70)
        logger.info("NIJA Apex Strategy v7.1 - HIGH WIN-RATE OPTIMIZED")
        logger.info("✅ PROFIT-TAKING: ALWAYS ENABLED (cannot be disabled)")
        logger.info("✅ Multi-broker support: Coinbase, Kraken, Binance, OKX, Alpaca")
        logger.info("✅ All tiers supported: SAVER, INVESTOR, INCOME, LIVABLE, BALLER")
        if self.use_enhanced_scoring:
            logger.info("✅ Enhanced entry scoring: ENABLED (0-100 weighted scoring)")
            logger.info("✅ Regime detection: ENABLED (trending/ranging/volatile)")
            min_score = self.config.get('min_score_threshold', 40)  # TUNED: Relaxed from 60 to 40 for higher signal frequency (range 40-75)
            logger.info(f"✅ Minimum entry score: {min_score}/100 (relaxed threshold — more signals, 40-75 range)")
        if self.enable_stepped_exits:
            logger.info("✅ Stepped profit-taking: ENABLED (aggressive partial exits)")
            logger.info(f"   Exit levels: {len(self.stepped_exit_levels)} profit targets (3.0%, 4.0%, 5.5%, 7.0%)")
        logger.info(f"✅ Position sizing: {self.config.get('min_position_pct', 0.02)*100:.0f}%-{self.config.get('max_position_pct', 0.10)*100:.0f}% (capital efficient)")
        logger.info(f"✅ Confidence threshold: {MIN_CONFIDENCE*100:.0f}% (balanced quality)")
        logger.info(f"✅ Minimum ADX: {self.min_adx} (soft score contribution; drought relaxation active when idle 2h+)")
        if self.use_ai_hub:
            logger.info("✅ AI Intelligence Hub: ENABLED")
            logger.info("   ├─ AI Market Regime Detection (7-class classifier)")
            logger.info("   ├─ Portfolio Risk Engine (correlation + VaR)")
            logger.info("   └─ Capital Allocation AI (dynamic Sharpe-weighted routing)")
        logger.info("=" * 70)

    def _validate_profitability_configuration(self):
        """
        Validate that strategy configuration is profitable after fees.
        
        This is a CRITICAL GUARD RAIL that prevents deployment of unprofitable
        trading configurations. Validates:
        1. Profit targets exceed exchange fees by minimum margin
        2. Risk/reward ratios are favorable after fees
        3. Configuration would be profitable at reasonable win rates
        
        Raises:
            ProfitabilityAssertionError: If configuration is unprofitable
        """
        if not PROFITABILITY_ASSERTION_AVAILABLE:
            logger.warning("⚠️ Profitability assertion unavailable - skipping validation")
            return
        
        # Determine exchange from broker client
        broker_name = self._get_broker_name() if hasattr(self, 'broker_client') else 'coinbase'
        if broker_name == 'unknown':
            broker_name = 'coinbase'  # Default to Coinbase (most conservative)
        
        # Extract profit targets from stepped exit levels
        profit_targets = sorted(self.stepped_exit_levels.keys())
        profit_targets_pct = [pt * 100 for pt in profit_targets]  # Convert to percentages
        
        # Estimate stop loss percentage (tightened to 1.2% — Option B Apr 2026)
        stop_loss_pct = 1.2
        
        # Use the highest profit target as primary target
        primary_target_pct = profit_targets_pct[-1] if profit_targets_pct else 6.0
        
        try:
            logger.info("🛡️ Validating strategy profitability configuration...")
            logger.info(f"   Exchange: {broker_name.upper()}")
            logger.info(f"   Profit targets: {profit_targets_pct}")
            logger.info(f"   Estimated stop loss: {stop_loss_pct}%")
            
            # Validate configuration
            assert_strategy_is_profitable(
                profit_targets=profit_targets_pct,
                stop_loss_pct=stop_loss_pct,
                primary_target_pct=primary_target_pct,
                exchange=broker_name
            )
            
            logger.info("✅ PROFITABILITY VALIDATION PASSED")
            logger.info("   Strategy meets profitability criteria")
            logger.info("   (based on assumed win-rate conditions)")
            
        except ProfitabilityAssertionError as e:
            logger.error("❌ PROFITABILITY VALIDATION FAILED")
            logger.error(f"   {str(e)}")
            logger.error("   CRITICAL: This configuration would lose money after fees!")
            logger.error("   Strategy initialization blocked to prevent losses.")
            raise

    def _get_broker_name(self) -> str:
        """
        Get broker name from broker_client.

        Returns:
            str: Broker name (e.g., 'kraken', 'coinbase') or 'unknown'
        """
        if not self.broker_client or not hasattr(self.broker_client, 'broker_type'):
            return 'unknown'

        broker_type = self.broker_client.broker_type
        if hasattr(broker_type, 'value'):
            # It's an Enum
            return broker_type.value.lower()
        elif isinstance(broker_type, str):
            # It's already a string
            return broker_type.lower()
        else:
            # Fallback to string representation
            return str(broker_type).lower()

    def _get_broker_fee_aware_target(self, symbol: str, use_limit_order: bool = True) -> float:
        """
        Get minimum profit target for current broker/symbol to overcome fees.

        Formula: min_profit_target = broker_fee * 2.5

        This ensures trades are profitable after fees with a safety buffer.

        Args:
            symbol: Trading symbol
            use_limit_order: True for maker fees, False for taker fees

        Returns:
            Minimum profit target as decimal (e.g., 0.035 = 3.5%)
        """
        if not EXCHANGE_CAPABILITIES_AVAILABLE:
            # Fix 1+2: floor raised to 3.5%; fee-aware calc used as secondary floor.
            from apex_config import get_min_profit_target
            return max(0.035, get_min_profit_target())  # 3.5% minimum profit target

        broker_name = self._get_broker_name()
        try:
            min_target = _get_exchange_min_profit_target(broker_name, symbol, use_limit_order)
            logger.debug(f"Fee-aware profit target for {broker_name}/{symbol}: {min_target*100:.2f}%")
            return min_target
        except Exception as e:
            logger.warning(f"Could not get fee-aware target for {broker_name}/{symbol}: {e}")
            from apex_config import get_min_profit_target
            return max(0.035, get_min_profit_target())  # 3.5% fallback

    def _get_broker_capabilities(self, symbol: str):
        """
        Get exchange capabilities for current broker and symbol.

        Args:
            symbol: Trading symbol

        Returns:
            ExchangeCapabilities object or None
        """
        if not EXCHANGE_CAPABILITIES_AVAILABLE:
            return None

        broker_name = self._get_broker_name()
        try:
            return get_broker_capabilities(broker_name, symbol)
        except Exception as e:
            logger.warning(f"Could not get capabilities for {broker_name}/{symbol}: {e}")
            return None

    def update_broker_client(self, new_broker_client):
        """
        Update the broker client for this strategy and its execution engine.

        This is critical when switching between multiple brokers (e.g., KRAKEN to COINBASE)
        to ensure that the execution engine uses the correct broker for placing orders.

        CRITICAL FIX (Jan 26, 2026): Prevents broker mismatch where trades are calculated
        for one broker's balance but executed on another broker. This was causing significant
        losses when KRAKEN detected a trade with $57.31 balance but execution used COINBASE's
        $24.16 balance instead.

        Args:
            new_broker_client: The new broker client to use
        """
        if new_broker_client:
            self.broker_client = new_broker_client
            if hasattr(self, 'execution_engine') and self.execution_engine:
                self.execution_engine.broker_client = new_broker_client
                logger.debug(f"Updated execution engine broker to {self._get_broker_name()}")

    def _validate_trade_quality(self, position_size: float, score: float,
                                account_balance: float = 0.0) -> Dict:
        """
        Validate trade quality based on position size and confidence threshold.

        Implements adaptive minimum sizing (Mar 2026):
            min_order = max(broker_min, strategy_min_based_on_edge)

        • High-confidence signals may be bumped up to broker_min rather than
          skipped, ensuring strong setups are never missed due to sizing.
        • Low-confidence signals require a *larger* minimum than the raw
          broker floor, preventing weak trades that technically clear the
          exchange minimum.

        Args:
            position_size:    Calculated position size in USD
            score:            Entry signal quality score (higher = better)
            account_balance:  Current account balance in USD (used for bump safety)

        Returns:
            Dictionary with 'valid' (bool), 'reason' (str), 'confidence' (float),
            and optionally 'recommended_size' (float, when a bump was applied).
        """
        # Normalize position_size in case it's a tuple
        position_size = scalar(position_size)

        broker_name = self._get_broker_name()
        broker_minimum = BROKER_MIN_ORDER_USD.get(broker_name.lower(), _DEFAULT_MIN_ORDER_USD)

        # Normalise confidence early (needed for adaptive minimum calculation)
        confidence = min(score / MAX_ENTRY_SCORE, 1.0)
        confidence = float(scalar(confidence))

        # ── Adaptive minimum sizing (Mar 2026) ──────────────────────────────
        # Use the adaptive minimum sizer when available; fall back to the
        # original static broker-minimum check for robustness.
        if ADAPTIVE_MIN_SIZING_AVAILABLE:
            sizer = get_adaptive_minimum_sizer()
            validation = sizer.validate_trade(
                position_size_usd=float(position_size),
                score=float(score),
                max_entry_score=MAX_ENTRY_SCORE,
                broker_name=broker_name,
                account_balance=float(account_balance) if account_balance else 0.0,
            )
            adaptive_min = validation["adaptive_min"]

            if not validation["valid"]:
                logger.info(
                    f"   ⏭️  Adaptive minimum gate: {validation['reason']}"
                )
                return {
                    "valid": False,
                    "reason": validation["reason"],
                    "confidence": confidence,
                    "adaptive_min": adaptive_min,
                }

            # Bump applied: use the recommended (bumped) size downstream
            if validation["bumped"]:
                logger.info(
                    f"   🔼 Minimum bump applied: ${position_size:.2f} → "
                    f"${validation['recommended_size']:.2f} "
                    f"(confidence={confidence:.2f})"
                )
                return {
                    "valid": True,
                    "reason": validation["reason"],
                    "confidence": confidence,
                    "recommended_size": validation["recommended_size"],
                    "adaptive_min": adaptive_min,
                }
        else:
            # ── Fallback: original static broker-minimum check ───────────────
            if float(position_size) < broker_minimum:
                logger.info(
                    f"   ⏭️  Skipping trade: Position ${position_size:.2f} below "
                    f"{broker_name} minimum ${broker_minimum:.2f}"
                )
                return {
                    "valid": False,
                    "reason": (
                        f"Position too small: ${position_size:.2f} < "
                        f"${broker_minimum:.2f} minimum for {broker_name} "
                        f"(increase account size for better trading)"
                    ),
                    "confidence": 0.0,
                }

        # ── Confidence threshold gate ────────────────────────────────────────
        # Logged as advisory — no longer a hard block.
        _effective_min_confidence = getattr(self, '_hf_min_confidence', MIN_CONFIDENCE)
        if confidence < _effective_min_confidence:
            logger.info(
                f"   ⚠️  Low confidence advisory: {confidence:.2f} < "
                f"{_effective_min_confidence:.2f} (proceeding with reduced size)"
            )

        logger.info(
            f"   ✅ Trade approved: Size=${position_size:.2f}, "
            f"Confidence={confidence:.2f}"
        )
        return {
            "valid": True,
            "reason": "Trade quality validated",
            "confidence": confidence,
        }

    def _check_kraken_confidence(self, broker_name: str, validation: Dict) -> Optional[Dict]:
        """
        Check Kraken-specific confidence threshold.
        
        Args:
            broker_name: Name of the broker
            validation: Validation result from _validate_trade_quality
            
        Returns:
            None if check passes, or dict with 'action' and 'reason' if check fails
        """
        if broker_name == 'kraken':
            confidence = validation.get('confidence', 0.0)
            if confidence < self.kraken_min_confidence:
                logger.info(
                    f"   ⚠️  Kraken advisory: Confidence {confidence:.2f} < "
                    f"{self.kraken_min_confidence:.2f} — proceeding (no hard block)"
                )
        return None

    def _log_first_trade_sanity_check(self, symbol: str, direction: str, current_price: float,
                                      position_size: float, account_balance: float, broker_name: str,
                                      score: float, validation: Dict, adx: float,
                                      eligibility: Dict, trend: str, reason: str) -> None:
        """
        Log comprehensive first trade sanity check details.
        
        Args:
            symbol: Trading symbol
            direction: Trade direction ('LONG' or 'SHORT')
            current_price: Current entry price
            position_size: Calculated position size
            account_balance: Account balance
            broker_name: Broker name
            score: Entry score
            validation: Validation result
            adx: ADX value
            eligibility: Eligibility check result
            trend: Market trend
            reason: Entry reason
        """
        if not self.first_trade_attempted:
            logger.info("=" * 80)
            logger.info("🔔 FIRST TRADE SANITY CHECK - Review before execution")
            logger.info("=" * 80)
            logger.info(f"Symbol: {symbol}")
            logger.info(f"Direction: {direction}")
            logger.info(f"Entry Price: ${current_price:.4f}")
            logger.info(f"Position Size: ${position_size:.2f}")
            logger.info(f"Account Balance: ${account_balance:.2f}")
            logger.info(f"Broker: {broker_name.upper()}")
            logger.info("-" * 80)
            logger.info(f"Signal Quality:")
            logger.info(f"  - Entry Score: {score:.1f}/5 (legacy)")
            logger.info(f"  - Confidence: {validation.get('confidence', 0.0):.2f}")
            logger.info(f"  - ADX: {adx:.1f}")
            logger.info("-" * 80)
            logger.info(f"Eligibility Checks:")
            for check_name, check_data in eligibility['checks'].items():
                status = "✅" if check_data.get('valid', True) else "❌"
                logger.info(f"  {status} {check_name}: {check_data}")
            logger.info("-" * 80)
            logger.info(f"Risk Management:")
            logger.info(f"  - Trend: {trend}")
            logger.info(f"  - Reason: {reason}")
            logger.info("=" * 80)
            self.first_trade_attempted = True

    def verify_trade_eligibility(self, symbol: str, df: pd.DataFrame, indicators: Dict, 
                                 side: str, position_size: float, bid_price: float = None, 
                                 ask_price: float = None) -> Dict:
        """
        Comprehensive trade eligibility verification combining RSI, volatility, and spread checks.
        
        This is a unified pre-trade validation that ensures all critical conditions are met:
        - RSI is in acceptable range for the trade direction
        - Volatility (ATR) is sufficient for profitable trading
        - Spread is acceptable (if bid/ask prices provided)
        
        Args:
            symbol: Trading pair symbol
            df: Price DataFrame
            indicators: Dictionary of calculated indicators
            side: Trade direction ('long' or 'short')
            position_size: Position size in USD
            bid_price: Current bid price (optional)
            ask_price: Current ask price (optional)
            
        Returns:
            Dictionary with:
                - 'eligible': bool - whether trade meets all requirements
                - 'reason': str - detailed reason
                - 'checks': dict - detailed check results
        """
        checks = {}
        failures = []
        
        # Get current values
        current_price = df['close'].iloc[-1]
        rsi = scalar(indicators.get('rsi', pd.Series([50])).iloc[-1])
        atr = scalar(indicators.get('atr', pd.Series([0])).iloc[-1])
        
        # Configurable thresholds (can be overridden via config in future)
        # AGGRESSIVE MODE: widened from 30/70 → 25/75 to allow entries in a broader RSI band
        general_rsi_min = 25
        general_rsi_max = 75
        general_min_atr_pct = 0.20  # 0.20% minimum volatility (was 0.5%)
        general_max_spread_pct = 0.50  # 0.50% maximum spread (was 0.20%)
        
        # 1. RSI Range Check
        # NOTE: We use the same RSI range for both long and short to avoid extreme conditions
        # This prevents trading when RSI is in extreme overbought (>75) or oversold (<25) zones
        # Rationale: Extreme RSI often leads to reversals, making entries risky regardless of direction
        if side == 'long':
            # For longs, avoid extreme RSI conditions (both overbought and oversold)
            rsi_min, rsi_max = general_rsi_min, general_rsi_max
            rsi_valid = rsi_min <= rsi <= rsi_max
            checks['rsi'] = {'value': rsi, 'range': f'{rsi_min}-{rsi_max}', 'valid': rsi_valid}
            if not rsi_valid:
                failures.append(f'RSI {rsi:.1f} outside safe range {rsi_min}-{rsi_max} (avoiding extremes)')
        else:  # short
            # For shorts, also avoid extreme RSI conditions (both overbought and oversold)
            rsi_min, rsi_max = general_rsi_min, general_rsi_max
            rsi_valid = rsi_min <= rsi <= rsi_max
            checks['rsi'] = {'value': rsi, 'range': f'{rsi_min}-{rsi_max}', 'valid': rsi_valid}
            if not rsi_valid:
                failures.append(f'RSI {rsi:.1f} outside safe range {rsi_min}-{rsi_max} (avoiding extremes)')
        
        # 2. Volatility (ATR) Check
        # Ensure sufficient volatility for profitable trading.
        # Borderline volatility (0.25%–0.5%) is allowed with a reduced position size
        # instead of hard-blocking: trade smaller rather than reject.
        atr_pct = (atr / current_price) * 100 if current_price > 0 else 0
        min_atr_pct = general_min_atr_pct
        borderline_min_atr_pct = min_atr_pct * BORDERLINE_ATR_FLOOR  # floor for borderline zone
        atr_valid = atr_pct >= min_atr_pct
        borderline_volatility = (not atr_valid) and (atr_pct >= borderline_min_atr_pct)
        allow_with_reduced_size = borderline_volatility

        # ── Volatility Kill Switch: skip trade when ATR is extreme ────────────
        # atr_pct is in % (e.g. 4.5 means 4.5%), EXTREME_VOLATILITY_ATR_PCT is a
        # fraction (0.04 = 4%), so convert for comparison.
        extreme_volatility_pct = EXTREME_VOLATILITY_ATR_PCT * 100  # → 4.0 (%)
        if atr_pct > extreme_volatility_pct:
            logger.info(
                "⚡ VOLATILITY KILL SWITCH: ATR %.2f%% > %.2f%% — skipping %s %s",
                atr_pct, extreme_volatility_pct, side.upper(), symbol,
            )
            failures.append(
                f'Extreme volatility: ATR {atr_pct:.2f}% > {extreme_volatility_pct:.2f}% kill-switch threshold'
            )

        checks['volatility'] = {
            'atr_pct': atr_pct,
            'min_required': min_atr_pct,
            'valid': atr_valid,
            'borderline': borderline_volatility,
            'allow_with_reduced_size': allow_with_reduced_size,
        }
        if not atr_valid and not borderline_volatility:
            failures.append(f'Volatility too low: ATR {atr_pct:.2f}% < {borderline_min_atr_pct:.2f}% (even borderline minimum)')
        
        # 3. Spread Check (if bid/ask prices provided)
        if bid_price is not None and ask_price is not None and bid_price > 0 and ask_price > 0:
            mid_price = (bid_price + ask_price) / 2
            spread_absolute = ask_price - bid_price
            spread_pct = (spread_absolute / mid_price) * 100 if mid_price > 0 else 0
            max_spread_pct = general_max_spread_pct
            spread_valid = spread_pct <= max_spread_pct
            checks['spread'] = {
                'spread_pct': spread_pct, 
                'max_allowed': max_spread_pct, 
                'valid': spread_valid,
                'bid': bid_price,
                'ask': ask_price
            }
            if not spread_valid:
                failures.append(f'Spread too wide: {spread_pct:.3f}% > {max_spread_pct}% maximum')
        else:
            checks['spread'] = {'valid': True, 'note': 'Bid/ask prices not provided, skipping spread check'}
        
        # 4. Broker-specific checks (Kraken safety)
        broker_name = self._get_broker_name()
        if broker_name == 'kraken':
            # Apply stricter Kraken-specific thresholds from configuration
            kraken_min_rsi = self.kraken_min_rsi
            kraken_max_rsi = self.kraken_max_rsi
            kraken_rsi_valid = kraken_min_rsi <= rsi <= kraken_max_rsi
            checks['kraken_rsi_safety'] = {
                'value': rsi, 
                'safe_range': f'{kraken_min_rsi}-{kraken_max_rsi}', 
                'valid': kraken_rsi_valid
            }
            if not kraken_rsi_valid:
                failures.append(f'Kraken safety: RSI {rsi:.1f} outside safe range {kraken_min_rsi}-{kraken_max_rsi}')
            
            # Apply stricter ATR requirement for Kraken
            kraken_min_atr = self.kraken_min_atr_pct
            kraken_atr_valid = atr_pct >= kraken_min_atr
            checks['kraken_atr_safety'] = {
                'atr_pct': atr_pct,
                'min_required': kraken_min_atr,
                'valid': kraken_atr_valid
            }
            if not kraken_atr_valid:
                failures.append(f'Kraken safety: ATR {atr_pct:.2f}% below {kraken_min_atr}% minimum')
        
        # Determine eligibility
        eligible = len(failures) == 0
        # Collect borderline_volatility flag from the volatility check
        _borderline_vol = checks.get('volatility', {}).get('borderline', False)
        allow_with_reduced_size = _borderline_vol and eligible

        if eligible:
            reason = f"✅ Trade eligible: RSI={rsi:.1f}, ATR={atr_pct:.2f}%"
            if 'spread' in checks and 'spread_pct' in checks['spread']:
                reason += f", Spread={checks['spread']['spread_pct']:.3f}%"
            if _borderline_vol:
                reason += " (borderline volatility — reduced size recommended)"
        else:
            reason = f"❌ Trade not eligible: {'; '.join(failures)}"

        return {
            'eligible': eligible,
            'reason': reason,
            'checks': checks,
            'allow_with_reduced_size': allow_with_reduced_size,
        }

    def check_market_filter(self, df: pd.DataFrame, indicators: Dict) -> Tuple[bool, str, str, float]:
        """
        Market Filter: Determine trade direction and signal strength from trend conditions.

        Required conditions:
        - VWAP alignment (price above for uptrend, below for downtrend)
        - EMA sequence (9 > 21 > 50 for uptrend, 9 < 21 < 50 for downtrend)
        - MACD histogram alignment (positive for uptrend, negative for downtrend)
        - ADX > min_adx (configurable, default 6)
        - Volume (market filter) > volume_threshold of 5-candle average
        - Volume (smart filter) > volume_min_threshold of 20-candle average

        Returns:
            Tuple of (allow_trade, direction, reason, market_strength)
            - allow_trade: True when at least one directional condition is met
            - direction: 'uptrend', 'downtrend', or 'none'
            - reason: Explanation string
            - market_strength: 0.0–1.0 (score/5); flows to gate_score_reduction downstream
        """
        # Get current values
        current_price = df['close'].iloc[-1]
        vwap = indicators['vwap'].iloc[-1]
        ema9 = indicators['ema_9'].iloc[-1]
        ema21 = indicators['ema_21'].iloc[-1]
        ema50 = indicators['ema_50'].iloc[-1]
        macd_hist = indicators['histogram'].iloc[-1]
        adx = scalar(indicators['adx'].iloc[-1])

        # Volume check (5-candle average)
        avg_volume_5 = df['volume'].iloc[-5:].mean()
        current_volume = df['volume'].iloc[-1]
        volume_ratio = current_volume / avg_volume_5 if avg_volume_5 > 0 else 0

        # ADX filter — contributes to trend score rather than hard-blocking.
        # A low-ADX market still gets a full score evaluation; the adx_strong
        # condition in uptrend/downtrend scoring already penalises choppy markets.
        # Hard block retained only when min_adx is explicitly forced above zero AND
        # drought relaxation is not active (drought mode disables even this gate).
        _drought = (
            self._freq_ctrl.get_drought_relaxation()
            if self._freq_ctrl is not None
            else None
        )
        _drought_active = _drought is not None and _drought.active

        # Apply drought relaxation to effective thresholds
        _eff_adx = max(0.0, self.min_adx - (_drought.adx_reduction if _drought and _drought.active else 0.0))
        _eff_vol = self.volume_threshold * (_drought.volume_multiplier if _drought and _drought.active else 1.0)

        if _drought_active:
            logger.info(
                "⏳ Drought relaxation active — ADX threshold %.1f→%.1f, "
                "volume threshold %.1f%%→%.1f%%",
                self.min_adx, _eff_adx,
                self.volume_threshold * 100, _eff_vol * 100,
            )

        # Check for uptrend
        uptrend_conditions = {
            'vwap': current_price > vwap,
            'ema_sequence': ema9 > ema21 > ema50,
            'macd_positive': macd_hist > 0,
            'adx_strong': adx > _eff_adx,
            'volume_ok': volume_ratio >= _eff_vol
        }

        # Check for downtrend
        downtrend_conditions = {
            'vwap': current_price < vwap,
            'ema_sequence': ema9 < ema21 < ema50,
            'macd_negative': macd_hist < 0,
            'adx_strong': adx > _eff_adx,
            'volume_ok': volume_ratio >= _eff_vol
        }

        # Score-based direction selection — no binary minimum threshold.
        # market_strength (0.0–1.0 = score/5) flows downstream to modulate gate
        # thresholds rather than hard-blocking the signal.
        # Only a true "zero signal" (score=0 on BOTH sides) results in hold.
        uptrend_score = sum(uptrend_conditions.values())
        downtrend_score = sum(downtrend_conditions.values())

        # Log details for debugging
        logger.debug(f"Market filter - Uptrend: {uptrend_score}/5, Downtrend: {downtrend_score}/5")
        logger.debug(f"  Price vs VWAP: {current_price:.4f} vs {vwap:.4f}")
        logger.debug(f"  EMA sequence: {ema9:.4f} vs {ema21:.4f} vs {ema50:.4f}")
        logger.debug(f"  MACD histogram: {macd_hist:.6f}, ADX: {adx:.1f}, Vol ratio: {volume_ratio:.2f}")

        if uptrend_score >= downtrend_score and uptrend_score > 0:
            _mkt_strength = uptrend_score / 5.0
            return (True, 'uptrend',
                    f'Uptrend ({uptrend_score}/5 — strength={_mkt_strength:.1f}, '
                    f'ADX={adx:.1f}, Vol={volume_ratio*100:.0f}%)',
                    _mkt_strength)
        elif downtrend_score > 0:
            _mkt_strength = downtrend_score / 5.0
            return (True, 'downtrend',
                    f'Downtrend ({downtrend_score}/5 — strength={_mkt_strength:.1f}, '
                    f'ADX={adx:.1f}, Vol={volume_ratio*100:.0f}%)',
                    _mkt_strength)
        else:
            logger.debug(f"  → Market filter: zero conditions met in either direction")
            return (False, 'none',
                    f'No trend signal (Up:{uptrend_score}/5, Down:{downtrend_score}/5)',
                    0.0)

    def check_long_entry(self, df: pd.DataFrame, indicators: Dict) -> Tuple[bool, int, str]:
        """
        Long Entry Logic (INSTITUTIONAL GRADE + ADAPTIVE RSI)

        Conditions:
        1. Pullback to EMA21 or VWAP (price within 0.5% of either)
        2. RSI bullish pullback (ADAPTIVE ranges based on market regime)
        3. Bullish engulfing or hammer candlestick pattern
        4. MACD histogram ticking up (current > previous)
        5. Volume >= 60% of last 2 candles average

        Args:
            df: Price DataFrame
            indicators: Dictionary of calculated indicators

        Returns:
            Tuple of (signal, score, reason)
        """
        current = df.iloc[-1]
        previous = df.iloc[-2]

        current_price = current['close']
        vwap = indicators['vwap'].iloc[-1]
        ema21 = indicators['ema_21'].iloc[-1]
        rsi = scalar(indicators['rsi'].iloc[-1])
        rsi_prev = scalar(indicators['rsi'].iloc[-2])
        macd_hist = indicators['histogram'].iloc[-1]
        macd_hist_prev = indicators['histogram'].iloc[-2]

        conditions = {}

        # 1. Pullback to EMA21 or VWAP (TUNED: 2.5% tolerance — small-cap alts
        #    routinely move 2-3% away from EMA21; 1.5% missed too many valid setups)
        near_ema21 = abs(current_price - ema21) / ema21 < 0.025
        near_vwap = abs(current_price - vwap) / vwap < 0.025
        conditions['pullback'] = near_ema21 or near_vwap

        # 2. RSI bullish pullback (ADAPTIVE MAX ALPHA UPGRADE)
        # Get adaptive RSI ranges based on current market regime.
        # Priority: RegimeStrategyBridge > legacy regime detector > static fallback.
        adx = scalar(indicators.get('adx', pd.Series([0])).iloc[-1])
        _broker_name = self._get_broker_name()
        if (REGIME_BRIDGE_AVAILABLE and self.regime_bridge is not None
                and self.current_regime is not None):
            _rb_params = self.regime_bridge.get_params(self.current_regime)
            long_rsi_min = _rb_params.rsi_long_min
            long_rsi_max = _rb_params.rsi_long_max
            # In CONSOLIDATION regime switch to scalp-optimized RSI bounds
            if (SCALP_MODE_OPTIMIZER_AVAILABLE and self.scalp_optimizer is not None
                    and self.scalp_optimizer.should_use_scalp_mode(self.current_regime)):
                _scalp_cfg = self.scalp_optimizer.get_scalp_config(
                    _broker_name, getattr(self, '_last_account_balance', 100.0)
                )
                long_rsi_min = _scalp_cfg.rsi_long_min
                long_rsi_max = _scalp_cfg.rsi_long_max
        elif self.use_enhanced_scoring and self.regime_detector and self.current_regime:
            rsi_ranges = self.regime_detector.get_adaptive_rsi_ranges(self.current_regime, adx)
            long_rsi_min = rsi_ranges['long_min']
            long_rsi_max = rsi_ranges['long_max']
        else:
            # Fallback to balanced static ranges (when regime detection unavailable)
            # AGGRESSIVE: Widened from 25-65 to 25-67 to capture more trade setups:
            # RSI 25-35: Deep oversold pullback entries (mean reversion)
            # RSI 35-50: Standard pullback entries (momentum continuation)
            # RSI 50-67: Momentum continuation entries (trend following, slightly overbought)
            long_rsi_min = 25
            long_rsi_max = 67

        # Apply adaptive RSI condition: balanced entry strategy (fallback)
        # When regime detection is unavailable, use balanced ranges for all market conditions
        # - RSI 25-40: Deep pullback entries (mean reversion)
        # - RSI 40-55: Shallow pullback entries (momentum continuation)
        # - RSI 55-67: Early momentum entries (trend following)
        conditions['rsi_pullback'] = long_rsi_min <= rsi <= long_rsi_max and rsi > rsi_prev

        # 3. Bullish candlestick patterns
        body = current['close'] - current['open']
        prev_body = previous['close'] - previous['open']

        # Bullish engulfing
        bullish_engulfing = (
            prev_body < 0 and  # Previous was bearish
            body > 0 and  # Current is bullish
            current['close'] > previous['open'] and
            current['open'] < previous['close']
        )

        # Hammer (small body, long lower wick)
        total_range = current['high'] - current['low']
        lower_wick = current['open'] - current['low'] if body > 0 else current['close'] - current['low']
        hammer = (
            body > 0 and
            lower_wick > body * 2 and
            total_range > 0 and
            lower_wick / total_range > 0.6
        )

        conditions['candlestick'] = bullish_engulfing or hammer

        # 4. MACD histogram ticking up
        conditions['macd_tick_up'] = macd_hist > macd_hist_prev

        # 5. Volume confirmation (>= ENTRY_VOLUME_MIN_MULTIPLIER of last 2 candles avg)
        avg_volume_2 = df['volume'].iloc[-3:-1].mean()
        conditions['volume'] = current['volume'] >= avg_volume_2 * ENTRY_VOLUME_MIN_MULTIPLIER

        # Calculate score
        score = sum(conditions.values())
        signal = score >= LEGACY_SIGNAL_THRESHOLD

        # Apply entry optimizer bonus (RSI divergence, BB zone, volume pattern)
        # The bonus is additive and raises the effective score for high-quality setups,
        # which benefits position sizing and signal ranking without blocking any trade
        # that already met the base conditions.
        opt_delta = 0.0
        opt_reason = ""
        if self.entry_optimizer is not None and signal:
            try:
                opt_result = self.entry_optimizer.analyze_entry(df, indicators, "long")
                opt_delta = opt_result.score_delta
                opt_reason = opt_result.reason
            except Exception as exc:
                logger.debug(f"  EntryOptimizer (long) error: {exc}")
        optimized_score = score + opt_delta

        base_reason = f"Long score: {score}/5 ({', '.join([k for k, v in conditions.items() if v])})" if conditions else "Long score: 0/5"
        reason = f"{base_reason} | opt: {opt_reason} (+{opt_delta:.1f})" if opt_delta > 0 else base_reason

        if score > 0:
            logger.debug(f"  Long entry check: {reason}")

        return signal, optimized_score, reason

    def check_short_entry(self, df: pd.DataFrame, indicators: Dict) -> Tuple[bool, int, str]:
        """
        Short Entry Logic (INSTITUTIONAL GRADE + ADAPTIVE RSI, mirror of long with bearish elements)

        Conditions:
        1. Pullback to EMA21 or VWAP (price within 0.5% of either)
        2. RSI bearish pullback (ADAPTIVE ranges based on market regime)
        3. Bearish engulfing or shooting star candlestick pattern
        4. MACD histogram ticking down (current < previous)
        5. Volume >= 60% of last 2 candles average

        Args:
            df: Price DataFrame
            indicators: Dictionary of calculated indicators

        Returns:
            Tuple of (signal, score, reason)
        """
        current = df.iloc[-1]
        previous = df.iloc[-2]

        current_price = current['close']
        vwap = indicators['vwap'].iloc[-1]
        ema21 = indicators['ema_21'].iloc[-1]
        rsi = scalar(indicators['rsi'].iloc[-1])
        rsi_prev = scalar(indicators['rsi'].iloc[-2])
        macd_hist = indicators['histogram'].iloc[-1]
        macd_hist_prev = indicators['histogram'].iloc[-2]

        conditions = {}

        # 1. Pullback to EMA21 or VWAP (TUNED: 2.5% tolerance — small-cap alts
        #    routinely move 2-3% away from EMA21; 1.5% missed too many valid setups)
        near_ema21 = abs(current_price - ema21) / ema21 < 0.025
        near_vwap = abs(current_price - vwap) / vwap < 0.025
        conditions['pullback'] = near_ema21 or near_vwap

        # 2. RSI bearish pullback (ADAPTIVE MAX ALPHA UPGRADE)
        # Get adaptive RSI ranges based on current market regime.
        # Priority: RegimeStrategyBridge > legacy regime detector > static fallback.
        adx = scalar(indicators.get('adx', pd.Series([0])).iloc[-1])
        _broker_name = self._get_broker_name()
        if (REGIME_BRIDGE_AVAILABLE and self.regime_bridge is not None
                and self.current_regime is not None):
            _rb_params_short = self.regime_bridge.get_params(self.current_regime)
            short_rsi_min = _rb_params_short.rsi_short_min
            short_rsi_max = _rb_params_short.rsi_short_max
            # In CONSOLIDATION regime switch to scalp-optimized RSI bounds
            if (SCALP_MODE_OPTIMIZER_AVAILABLE and self.scalp_optimizer is not None
                    and self.scalp_optimizer.should_use_scalp_mode(self.current_regime)):
                _scalp_cfg_s = self.scalp_optimizer.get_scalp_config(
                    _broker_name, getattr(self, '_last_account_balance', 100.0)
                )
                short_rsi_min = _scalp_cfg_s.rsi_short_min
                short_rsi_max = _scalp_cfg_s.rsi_short_max
        elif self.use_enhanced_scoring and self.regime_detector and self.current_regime:
            rsi_ranges = self.regime_detector.get_adaptive_rsi_ranges(self.current_regime, adx)
            short_rsi_min = rsi_ranges['short_min']
            short_rsi_max = rsi_ranges['short_max']
        else:
            # Fallback to balanced static ranges (when regime detection unavailable)
            # AGGRESSIVE: Widened from 35-75 to 33-75 to capture more short setups:
            # RSI 33-45: Early overbought-reversal shorts (slightly oversold reversal zone)
            # RSI 45-60: Momentum continuation shorts
            # RSI 60-75: Extended overbought shorts (mean reversion)
            short_rsi_min = 33
            short_rsi_max = 75

        # Apply adaptive RSI condition: balanced short entry strategy (fallback)
        # When regime detection is unavailable, use balanced ranges for all market conditions
        # - RSI 33-45: Early reversal short entries (trend following)
        # - RSI 45-60: Bounce short entries (momentum continuation)
        # - RSI 60-75: Extended overbought shorts (mean reversion)
        conditions['rsi_pullback'] = short_rsi_min <= rsi <= short_rsi_max and rsi < rsi_prev

        # 3. Bearish candlestick patterns
        body = current['close'] - current['open']
        prev_body = previous['close'] - previous['open']

        # Bearish engulfing
        bearish_engulfing = (
            prev_body > 0 and  # Previous was bullish
            body < 0 and  # Current is bearish
            current['close'] < previous['open'] and
            current['open'] > previous['close']
        )

        # Shooting star (small body, long upper wick)
        total_range = current['high'] - current['low']
        upper_wick = current['high'] - current['open'] if body < 0 else current['high'] - current['close']
        shooting_star = (
            body < 0 and
            upper_wick > abs(body) * 2 and
            total_range > 0 and
            upper_wick / total_range > 0.6
        )

        conditions['candlestick'] = bearish_engulfing or shooting_star

        # 4. MACD histogram ticking down
        conditions['macd_tick_down'] = macd_hist < macd_hist_prev

        # 5. Volume confirmation (>= ENTRY_VOLUME_MIN_MULTIPLIER of last 2 candles avg)
        avg_volume_2 = df['volume'].iloc[-3:-1].mean()
        conditions['volume'] = current['volume'] >= avg_volume_2 * ENTRY_VOLUME_MIN_MULTIPLIER

        # Calculate score
        score = sum(conditions.values())
        signal = score >= LEGACY_SIGNAL_THRESHOLD

        # Apply entry optimizer bonus (RSI divergence, BB zone, volume pattern)
        opt_delta = 0.0
        opt_reason = ""
        if self.entry_optimizer is not None and signal:
            try:
                opt_result = self.entry_optimizer.analyze_entry(df, indicators, "short")
                opt_delta = opt_result.score_delta
                opt_reason = opt_result.reason
            except Exception as exc:
                logger.debug(f"  EntryOptimizer (short) error: {exc}")
        optimized_score = score + opt_delta

        base_reason = f"Short score: {score}/5 ({', '.join([k for k, v in conditions.items() if v])})" if conditions else "Short score: 0/5"
        reason = f"{base_reason} | opt: {opt_reason} (+{opt_delta:.1f})" if opt_delta > 0 else base_reason

        if score > 0:
            logger.debug(f"  Short entry check: {reason}")

        return signal, optimized_score, reason

    def check_smart_filters(self, df: pd.DataFrame, current_time: datetime, symbol: str = None) -> Tuple[bool, str]:
        """
        Smart Filters to avoid bad trades

        Filters:
        1. No trades 5 min before/after major news (stub - placeholder for News API)
        2. No trades if volume < 0.5% avg (20-candle rolling average - emergency relaxation to find opportunities)
        3. No trading during first 1 second of a new candle (per-symbol tracking)

        Args:
            df: Price DataFrame
            current_time: Current datetime
            symbol: Trading symbol (required for candle timing filter)

        Returns:
            Tuple of (allowed, reason)
        """
        # Filter 1: News filter (stub - placeholder for future News API integration)
        # TODO: Integrate with News API (e.g., Benzinga, Alpha Vantage, etc.)
        # For now, this is a placeholder that always passes
        news_clear = True  # Stub: would check upcoming news events here

        # Filter 2: Volume filter - threshold is configurable via volume_min_threshold (default 0.1%)
        # EMERGENCY RELAXATION (Jan 29, 2026 - FOURTH RELAXATION): Lowered from 0.5% to 0.1% to allow ultra-low volume markets
        avg_volume = df['volume'].rolling(window=20).mean().iloc[-1]
        current_volume = df['volume'].iloc[-1]
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0

        if volume_ratio < self.volume_min_threshold:
            logger.debug(f'   🔇 Smart filter (volume): {volume_ratio*100:.1f}% < {self.volume_min_threshold*100:.0f}% threshold')
            return False, f'Volume too low ({volume_ratio*100:.1f}% of avg) - threshold: {self.volume_min_threshold*100:.0f}%'

        # Filter 3: Candle timing filter (DISABLED)
        # EMERGENCY RELAXATION (Jan 29, 2026 - FOURTH RELAXATION): DISABLED (set to 0) - was blocking too many opportunities
        # Detect new candle by comparing timestamps
        # CRITICAL FIX (Jan 27, 2026): Use per-symbol tracking to avoid cross-market contamination
        # Previously used single instance variable causing all markets to block each other
        if len(df) >= 2 and symbol is not None:
            # Check if we have a proper datetime index
            if hasattr(df.index, 'to_pydatetime'):
                # We have a datetime index - apply the candle timing filter
                current_candle_time = df.index[-1]
                last_candle_time = self.last_candle_times.get(symbol)

                # If we have timestamp data, check if we're in first 3 seconds
                if last_candle_time != current_candle_time:
                    # New candle detected - store time and check elapsed time
                    if last_candle_time is None:
                        # First run for this symbol - allow trade
                        self.last_candle_times[symbol] = current_candle_time
                    else:
                        # Calculate time since candle started
                        # Normalize to timezone-naive datetime to avoid timezone mismatch issues
                        candle_dt = current_candle_time.to_pydatetime()
                        if candle_dt.tzinfo is not None:
                            candle_dt = candle_dt.replace(tzinfo=None)
                        if current_time.tzinfo is not None:
                            current_time_naive = current_time.replace(tzinfo=None)
                        else:
                            current_time_naive = current_time
                        time_since_candle = (current_time_naive - candle_dt).total_seconds()

                        self.last_candle_times[symbol] = current_candle_time

                        # Block trade if we're in first N seconds of new candle
                        if time_since_candle < self.candle_exclusion_seconds:
                            logger.debug(f'   🔇 Smart filter (candle timing): {time_since_candle:.0f}s < {self.candle_exclusion_seconds}s threshold')
                            return False, f'First {self.candle_exclusion_seconds}s of new candle - waiting for stability'
            else:
                # No datetime index available - skip candle timing filter
                # This prevents blocking all trades when timestamp data isn't in the DataFrame index
                logger.debug('   ℹ️  Candle timing filter skipped (no datetime index available)')
        elif symbol is None:
            # No symbol provided - skip candle timing filter to avoid errors
            logger.debug('   ℹ️  Candle timing filter skipped (no symbol provided)')

        return True, 'All smart filters passed'

    def _get_risk_score(self, score: float, metadata: Dict) -> float:
        """
        Get the appropriate score for risk calculations

        Args:
            score: Enhanced score (if available) or legacy score
            metadata: Metadata dictionary from enhanced scoring

        Returns:
            Score to use for risk calculations (legacy 0-5 scale)
        """
        if self.use_enhanced_scoring and metadata:
            return metadata.get('legacy_score', score)
        return score

    def check_entry_with_enhanced_scoring(self, df: pd.DataFrame, indicators: Dict,
                                         side: str, account_balance: float) -> Tuple[bool, float, str, Dict]:
        """
        Check entry conditions using the unified Nija AI Engine.

        Route:
            1. NijaAIEngine.evaluate_symbol()  (rank-first, adaptive threshold)
               → composite score 0-100 + position multiplier
            2. Legacy 5-point check (always run for backward-compat metadata)
            3. Regime detection (kept for position sizing / SL/TP downstream)

        Decision rule (priority order):
            a. If NijaAIEngine available → use composite score + adaptive threshold
            b. If only EnhancedEntryScorer available → legacy enhanced path
            c. Fallback → legacy 5-point check only

        Returns:
            (should_enter, score, reason, metadata)
        """
        # ── Cycle Barrier: atomically capture all 4 signals from the same df tick ──
        # This guarantees that regime is freshly detected from the *current* df before
        # check_long/short_entry runs, eliminating the one-cycle regime lag where RSI
        # range boundaries could differ from the regime present in the market data.
        if self._cycle_barrier is not None:
            try:
                _snap = self._cycle_barrier.capture(
                    df=df,
                    indicators=indicators,
                    side=side,
                    regime_detector=self.regime_detector if self.use_enhanced_scoring else None,
                )
                # Publish fresh regime so legacy entry checks use THIS cycle's value
                if _snap.regime is not None:
                    self.current_regime = _snap.regime
            except Exception as _barrier_err:
                logger.debug("[CycleBarrier] capture failed, continuing with cached regime: %s", _barrier_err)

        # ── Always run legacy check (needed for metadata + fallback) ──────
        if side == "long":
            legacy_signal, legacy_score, legacy_reason = self.check_long_entry(df, indicators)
        else:
            legacy_signal, legacy_score, legacy_reason = self.check_short_entry(df, indicators)

        # ── Regime detection ───────────────────────────────────────────────
        regime = self.current_regime
        regime_metrics: Dict = {}
        regime_params: Dict = {}
        if self.use_enhanced_scoring and self.regime_detector is not None:
            try:
                regime, regime_metrics = self.regime_detector.detect_regime(df, indicators)
                self.current_regime = regime
                regime_params = self.regime_detector.get_regime_parameters(regime)
            except Exception as _rd_err:
                logger.debug("Regime detection error: %s", _rd_err)

        # ── Propagate regime scan-interval hint to AI engine speed controller ──
        # Whenever the current regime is known, update the CycleSpeedController
        # so the between-cycle delay reflects market conditions (e.g. faster in
        # trending, slower in crisis) rather than signal density alone.
        if (REGIME_BRIDGE_AVAILABLE and self.regime_bridge is not None
                and self.current_regime is not None
                and self.nija_ai_engine is not None):
            try:
                _regime_params_hint = self.regime_bridge.get_params(self.current_regime)
                self.nija_ai_engine.speed_ctrl.set_regime_hint(
                    int(_regime_params_hint.scan_interval_secs)
                )
            except Exception as _hint_err:
                logger.debug("Speed ctrl regime hint error: %s", _hint_err)

        # ── Fallback: no enhanced scoring available ────────────────────────
        if not self.use_enhanced_scoring:
            return legacy_signal, float(legacy_score), legacy_reason, {"legacy_score": legacy_score}

        # ── Path A: Nija AI Engine (primary) ──────────────────────────────
        if self.nija_ai_engine is not None:
            broker_name = self._get_broker_name() if hasattr(self, "_get_broker_name") else "coinbase"
            entry_type = self._get_entry_type_for_regime(regime) if hasattr(self, "_get_entry_type_for_regime") else "swing"

            try:
                ai_signal = self.nija_ai_engine.evaluate_symbol(
                    df=df,
                    indicators=indicators,
                    side=side,
                    regime=regime,
                    broker=broker_name,
                    entry_type=entry_type,
                    symbol=getattr(self, "_current_symbol", "UNKNOWN"),
                )

                if ai_signal is not None:
                    composite = ai_signal.composite_score
                    should_enter = composite >= ai_signal.threshold_used
                    regime_str = regime.value if hasattr(regime, "value") else str(regime)
                    reason = (
                        f"{side.upper()} | AI composite={composite:.1f}/100 "
                        f"({ai_signal.metadata.get('score_breakdown', {}).get('quality', '?')}) | "
                        f"mult=×{ai_signal.position_multiplier:.2f} | "
                        f"Regime:{regime_str} | Legacy:{legacy_score}/5 | "
                        f"gate={'✅' if ai_signal.metadata.get('gate_passed', True) else '⚠️'}"
                    )
                    metadata = {
                        "legacy_score": legacy_score,
                        "enhanced_score": composite,
                        "composite_score": composite,
                        "position_multiplier": ai_signal.position_multiplier,
                        "entry_type": ai_signal.entry_type,
                        "score_breakdown": ai_signal.metadata.get("score_breakdown", {}),
                        "regime": regime_str,
                        "regime_confidence": regime_metrics.get("confidence", 0.5),
                        "regime_params": regime_params,
                        "should_enter_legacy": legacy_signal,
                        "should_enter_enhanced": should_enter,
                        "combined_decision": should_enter,
                        "ai_engine_used": True,
                    }
                    if should_enter:
                        logger.info("  ✅ %s", reason)
                    else:
                        logger.debug("  ❌ %s", reason)
                    return should_enter, composite, reason, metadata

            except Exception as _ae_err:
                logger.debug("NijaAIEngine.evaluate_symbol error: %s", _ae_err)

        # ── Path B: EnhancedEntryScorer only (fallback) ───────────────────
        try:
            enhanced_score, score_breakdown = self.entry_scorer.calculate_entry_score(df, indicators, side)
        except Exception as _es_err:
            logger.debug("EnhancedEntryScorer error: %s", _es_err)
            enhanced_score, score_breakdown = 50.0, {"quality": "Fair"}

        should_enter_enhanced = self.entry_scorer.should_enter_trade(enhanced_score)
        should_enter = legacy_signal and should_enter_enhanced

        regime_str = regime.value if hasattr(regime, "value") else str(regime or "")
        reason = (
            f"{side.upper()} | Regime:{regime_str} | Legacy:{legacy_score}/5 | "
            f"Enhanced:{enhanced_score:.1f}/100 | {score_breakdown.get('quality', '?')}"
        )
        metadata = {
            "legacy_score": legacy_score,
            "enhanced_score": enhanced_score,
            "score_breakdown": score_breakdown,
            "regime": regime_str,
            "regime_confidence": regime_metrics.get("confidence", 0.5),
            "regime_params": regime_params,
            "should_enter_legacy": legacy_signal,
            "should_enter_enhanced": should_enter_enhanced,
            "combined_decision": should_enter,
            "ai_engine_used": False,
        }

        if should_enter:
            logger.info("  ✅ %s", reason)
        else:
            logger.debug("  ❌ %s", reason)

        return should_enter, enhanced_score, reason, metadata

    # ── Helper: map regime to entry_type string ───────────────────────────────
    def _get_entry_type_for_regime(self, regime: object) -> str:
        """
        Return the strategy profile string for a regime.

        Used by AI Entry Gate and Execution Exit Config to select
        the correct parameters (SCALP / SWING / BREAKOUT / MEAN_REVERSION).
        """
        regime_str = ""
        if hasattr(regime, "value"):
            regime_str = str(regime.value).lower()
        elif regime is not None:
            regime_str = str(regime).lower()

        _MAP = {
            "strong_trend": "breakout",
            "weak_trend":   "swing",
            "ranging":      "mean_reversion",
            "consolidation": "scalp",
            "expansion":    "breakout",
            "mean_reversion": "mean_reversion",
            "volatility_explosion": "swing",
            "trending":     "swing",
            "volatile":     "swing",
        }
        return _MAP.get(regime_str, "swing")

    def adjust_position_size_for_regime(self, base_position_size: float,
                                       regime: 'MarketRegime', score: float) -> float:
        """
        Adjust position size based on market regime and entry score

        Args:
            base_position_size: Base position size from risk manager
            regime: Current market regime
            score: Enhanced entry score (0-100)

        Returns:
            Adjusted position size
        """
        if not self.use_enhanced_scoring:
            return base_position_size

        # Regime-based adjustment
        regime_adjusted = self.regime_detector.adjust_position_size(regime, base_position_size)

        # Score-based adjustment (higher scores = larger positions)
        if score >= 80:  # Excellent setup
            score_multiplier = 1.2
        elif score >= 70:  # Good setup
            score_multiplier = 1.0
        elif score >= 60:  # Fair setup
            score_multiplier = 0.9
        else:  # Marginal setup
            score_multiplier = 0.7

        # Combine adjustments
        final_size = regime_adjusted * score_multiplier

        logger.debug(f"Position size adjustment: ${base_position_size:.2f} -> ${final_size:.2f} "
                    f"(regime:{regime.value}, score:{score:.1f})")

        return final_size

    def check_exit_conditions(self, symbol: str, df: pd.DataFrame,
                             indicators: Dict, current_price: float) -> Tuple[bool, str]:
        """
        Exit Logic

        Conditions:
        0. **EMERGENCY LIQUIDATION** (FIX 3): PnL <= -1% → IMMEDIATE SELL
        1. Opposite signal detected
        2. Trailing stop hit
        3. Trend break (EMA9/21 cross)

        Args:
            symbol: Trading symbol
            df: Price DataFrame
            indicators: Dictionary of calculated indicators
            current_price: Current market price

        Returns:
            Tuple of (should_exit, reason)
        """
        position = self.execution_engine.get_position(symbol)
        if not position:
            return False, 'No position'

        # FIX 3: EMERGENCY LIQUIDATION CHECK (HIGHEST PRIORITY)
        # If PnL <= -1%, force immediate liquidation with NO QUESTIONS
        # This bypasses ALL other checks and filters
        if EMERGENCY_LIQUIDATION_AVAILABLE:
            try:
                liquidator = EmergencyLiquidator()
                if liquidator.should_force_liquidate(position, current_price):
                    # CRITICAL: Return True to trigger immediate exit
                    # The execution will bypass all normal checks
                    return True, '🚨 EMERGENCY LIQUIDATION: PnL <= -1% (capital preservation override)'
            except Exception as e:
                logger.error(f"Error checking emergency liquidation: {e}")

        side = position['side']
        ema9 = indicators['ema_9'].iloc[-1]
        ema21 = indicators['ema_21'].iloc[-1]

        # 1. Check for opposite signal
        if side == 'long':
            short_signal, _, reason = self.check_short_entry(df, indicators)
            if short_signal:
                return True, f'Opposite signal: {reason}'
        else:  # short
            long_signal, _, reason = self.check_long_entry(df, indicators)
            if long_signal:
                return True, f'Opposite signal: {reason}'

        # 2. Check trailing stop
        if self.execution_engine.check_stop_loss_hit(symbol, current_price):
            return True, f'Trailing stop hit @ {position["stop_loss"]:.2f}'

        # 3. Check trend break (EMA9/21 cross)
        ema9_prev = indicators['ema_9'].iloc[-2]
        ema21_prev = indicators['ema_21'].iloc[-2]

        if side == 'long':
            # Bearish cross: EMA9 crosses below EMA21
            if ema9 < ema21 and ema9_prev >= ema21_prev:
                return True, 'Trend break: EMA9 crossed below EMA21'
        else:  # short
            # Bullish cross: EMA9 crosses above EMA21
            if ema9 > ema21 and ema9_prev <= ema21_prev:
                return True, 'Trend break: EMA9 crossed above EMA21'

        return False, 'No exit conditions met'

    def calculate_indicators(self, df: pd.DataFrame) -> Dict:
        """
        Calculate all required indicators

        Args:
            df: Price DataFrame with columns: open, high, low, close, volume

        Returns:
            Dictionary of indicators
        """
        # HARD GUARD: Force numeric types before any math to avoid str/int errors
        try:
            required_cols = ['open', 'high', 'low', 'close', 'volume']
            if not all(col in df.columns for col in required_cols):
                logger.warning("Missing OHLCV columns; cannot calculate indicators")
                return {}
            df[required_cols] = df[required_cols].astype(float)
            # Debug: confirm types are floats
            logger.debug(
                f"DEBUG candle types → close={type(df['close'].iloc[-1])}, "
                f"open={type(df['open'].iloc[-1])}, volume={type(df['volume'].iloc[-1])}"
            )
        except Exception as e:
            logger.warning(f"Failed to normalize candle types before indicators: {e}")
            return {}
        indicators = {
            'vwap': calculate_vwap(df),
            'ema_9': calculate_ema(df, 9),
            'ema_21': calculate_ema(df, 21),
            'ema_50': calculate_ema(df, 50),
            'rsi': calculate_rsi(df, 14),
            'rsi_9': calculate_rsi(df, 9),   # short-term momentum pulse for dual-RSI scoring
        }

        macd_line, signal_line, histogram = calculate_macd(df)
        indicators['macd_line'] = macd_line
        indicators['signal_line'] = signal_line
        indicators['histogram'] = histogram

        indicators['atr'] = calculate_atr(df, 14)
        adx, plus_di, minus_di = calculate_adx(df, 14)
        indicators['adx'] = adx
        indicators['plus_di'] = plus_di
        indicators['minus_di'] = minus_di

        # Calculate Bollinger Bands for volatility-based adaptive profit targets.
        # AGGRESSIVE: std_dev reduced from 2.0 (conventional 95%-capture) → 1.4 so the
        # bands are narrower.  This causes price to touch (or breach) the bands more
        # frequently, allowing the entry optimizer to award BB-proximity bonuses on a
        # larger share of candles and thereby generate more entry signals.  The deviation
        # from the standard 2σ definition is intentional and has been tuned for this
        # high-frequency crypto strategy.
        bb_upper, bb_middle, bb_lower, bb_bandwidth = calculate_bollinger_bands(df, period=20, std_dev=1.4)
        indicators['bb_upper'] = bb_upper
        indicators['bb_middle'] = bb_middle
        indicators['bb_lower'] = bb_lower
        indicators['bb_bandwidth'] = bb_bandwidth  # Normalized volatility measure for adaptive targets

        return indicators

    def analyze_market(self, df: pd.DataFrame, symbol: str,
                       account_balance: float) -> Dict:
        """
        Main analysis function - combines all components

        Args:
            df: Price DataFrame
            symbol: Trading symbol
            account_balance: Current account balance

        Returns:
            Dictionary with analysis results and recommended action
        """
        try:
            print("📊 Evaluating market conditions...")
            # Require minimum data
            if len(df) < 100:
                logger.debug(f"   {symbol}: Insufficient data ({len(df)} candles)")
                return {
                    'action': 'hold',
                    'reason': f'Insufficient data ({len(df)} candles, need 100+)'
                }

            # _last_daily_target_usd stays 0: edge-driven mode, no dollar target blocking.

            # Set starting balance once (first non-zero account balance seen).
            if self._true_profit_tracker is not None and account_balance > 0:
                try:
                    self._true_profit_tracker.set_starting_balance(account_balance)
                except Exception as _tpt_sb_err:
                    logger.debug("TrueProfitTracker.set_starting_balance error: %s", _tpt_sb_err)

            # Calculate indicators
            indicators = self.calculate_indicators(df)

            # Check smart filters
            current_time = datetime.now()
            filters_ok, filter_reason = self.check_smart_filters(df, current_time, symbol)
            if not filters_ok:
                if _BYPASS_SMART_FILTER:
                    logger.info(
                        "   🔓 %s: NIJA_BYPASS_SMART_FILTER active — smart filter bypassed (%s)",
                        symbol, filter_reason,
                    )
                else:
                    logger.info(f"   🔇 TRACE [smart_filter] {symbol}: {filter_reason}")
                    return {
                        'action': 'hold',
                        'reason': filter_reason,
                        'filter_stage': 'smart_filter',
                    }

            # Check market filter — returns 4-tuple including market_strength
            allow_trade, trend, market_reason, _market_strength = self.check_market_filter(df, indicators)

            # ── NIJA_DISABLE_MARKET_FILTER diagnostic bypass ──────────────────
            # When enabled, skip the market filter gate entirely and assign trend
            # direction from RSI so the entry logic always gets a chance to run.
            # Set NIJA_DISABLE_MARKET_FILTER=true to activate (testing only).
            if _DISABLE_MARKET_FILTER:
                _bypass_rsi = scalar(indicators['rsi'].iloc[-1])
                if _bypass_rsi >= _SCALP_RSI_LONG:
                    allow_trade, trend = True, 'uptrend'
                    market_reason = f'[BYPASS] market filter disabled — RSI={_bypass_rsi:.1f} → uptrend'
                elif _bypass_rsi <= _SCALP_RSI_SHORT:
                    allow_trade, trend = True, 'downtrend'
                    market_reason = f'[BYPASS] market filter disabled — RSI={_bypass_rsi:.1f} → downtrend'
                else:
                    allow_trade, trend = False, 'none'
                    market_reason = f'[BYPASS] market filter disabled — RSI={_bypass_rsi:.1f} too neutral'
                _market_strength = 1.0   # bypass assumes full signal strength
                logger.info("   🔓 %s: %s", symbol, market_reason)

            if not allow_trade:
                logger.info(f"   📊 TRACE [market_filter] {symbol}: {market_reason}")
                return {
                    'action': 'hold',
                    'reason': market_reason,
                    'filter_stage': 'market_filter',
                }

            # ── CONSOLIDATION SCALP: RSI + volume/structure reinforcement ─────
            # When check_market_filter returns trend='none' (score=0 on both sides),
            # attempt a consolidation scalp using RSI for direction.  RSI alone is a
            # weak signal — at least one of (volume active, market structure aligned)
            # must also confirm before the trade is allowed.
            if trend == 'none' and _CONSOLIDATION_SCALP:
                _cons_rsi = scalar(indicators['rsi'].iloc[-1])
                if _cons_rsi >= _SCALP_RSI_LONG:
                    _scalp_dir = 'uptrend'
                elif _cons_rsi <= _SCALP_RSI_SHORT:
                    _scalp_dir = 'downtrend'
                else:
                    # RSI is in the neutral band — nothing actionable
                    logger.debug(
                        "   %s: Consolidation scalp skipped — RSI=%.1f in neutral band",
                        symbol, _cons_rsi,
                    )
                    return {'action': 'hold', 'reason': f'No trend + RSI={_cons_rsi:.1f} neutral ({_SCALP_RSI_SHORT:.0f}-{_SCALP_RSI_LONG:.0f})', 'filter_stage': 'market_filter'}

                # ── Multi-factor reinforcement: RSI alone is a weak signal ────
                # Volume: current bar vs 20-bar average (>= 0.4x = market is active;
                # lowered from 0.6x → 0.4x Apr 2026 to match ENTRY_VOLUME_MIN_MULTIPLIER
                # and allow quiet-but-directional consolidation scalps through)
                # Structure: HH+HL (long) or LH+LL (short) on the last two bars.
                _avg_vol_20 = (df['volume'].iloc[-21:-1].mean()
                               if len(df) >= 21 else df['volume'].mean())
                _vol_ok = (float(df['volume'].iloc[-1]) / _avg_vol_20 >= 0.40
                           if _avg_vol_20 > 0 else False)
                _h_now, _h_prev = float(df['high'].iloc[-1]), float(df['high'].iloc[-2])
                _l_now, _l_prev = float(df['low'].iloc[-1]),  float(df['low'].iloc[-2])
                if _scalp_dir == 'uptrend':
                    _struct_ok = _h_now > _h_prev and _l_now > _l_prev   # HH + HL
                else:
                    _struct_ok = _h_now < _h_prev and _l_now < _l_prev   # LH + LL

                _confirmations = int(_vol_ok) + int(_struct_ok)
                if _confirmations == 0:
                    logger.debug(
                        "   %s: Consolidation scalp skipped — RSI=%.1f unconfirmed "
                        "(vol_ok=%s, struct_ok=%s)",
                        symbol, _cons_rsi, _vol_ok, _struct_ok,
                    )
                    return {
                        'action': 'hold',
                        'reason': (
                            f'RSI scalp signal unconfirmed — no volume/structure '
                            f'reinforcement (RSI={_cons_rsi:.1f})'
                        ),
                        'filter_stage': 'market_filter',
                    }

                # market_strength: base 0.3 + 0.2 per confirmation (max 0.7)
                _market_strength = 0.3 + 0.2 * _confirmations
                allow_trade, trend = True, _scalp_dir
                market_reason = (
                    f'Consolidation scalp-{_scalp_dir.replace("trend", "")} '
                    f'(RSI={_cons_rsi:.1f}, '
                    f'vol={"✓" if _vol_ok else "✗"}, '
                    f'struct={"✓" if _struct_ok else "✗"}, '
                    f'strength={_market_strength:.1f})'
                )
                logger.info("   ⚡ %s: %s", symbol, market_reason)

            # If trend is still 'none' (NIJA_CONSOLIDATION_SCALP=false or disabled path)
            if trend == 'none':
                logger.info(f"   📊 TRACE [market_filter] {symbol}: {market_reason}")
                return {'action': 'hold', 'reason': market_reason, 'filter_stage': 'market_filter'}

            # ── 4-Layer Drawdown Risk Controller (pre-entry authority) ────────
            # Runs BEFORE any position or signal checks to avoid wasted computation.
            # Layers: Global CB halt / Daily loss limit / ATR dynamic sizing / Market conditions
            self._last_account_balance = account_balance
            if self.drawdown_risk_ctrl is not None:
                try:
                    # Resolve regime-specific daily loss limit from the bridge so
                    # crisis/defensive regimes protect capital more aggressively.
                    _drc_daily_loss_pct: Optional[float] = None
                    if (REGIME_BRIDGE_AVAILABLE and self.regime_bridge is not None
                            and self.current_regime is not None):
                        try:
                            _drc_daily_loss_pct = self.regime_bridge.get_params(
                                self.current_regime
                            ).daily_loss_limit_pct
                        except Exception:
                            pass
                    _risk_result = self.drawdown_risk_ctrl.pre_entry_check(
                        account_balance=account_balance,
                        df=df,
                        indicators=indicators,
                        daily_pnl_usd=getattr(self, '_daily_pnl_usd', 0.0),
                        regime=self.current_regime,
                        daily_loss_limit_pct=_drc_daily_loss_pct,
                    )
                    self._risk_envelope_multiplier = _risk_result.position_multiplier
                    print(f"⏱ Trade allowed: {_risk_result.can_trade}")
                    if not _risk_result.can_trade:
                        logger.debug(
                            "   🛡️  %s: Risk envelope blocked — %s",
                            symbol, _risk_result.reason,
                        )
                        return {'action': 'hold', 'reason': _risk_result.reason}
                except Exception as _drc_check_err:
                    logger.debug("DrawdownRiskController check error: %s", _drc_check_err)
                    self._risk_envelope_multiplier = 1.0
            else:
                self._risk_envelope_multiplier = 1.0

            # ── Per-symbol re-entry cooldown (from ExecutionExitConfig) ───────
            if self.exit_config is not None:
                import time as _time_mod
                _now = _time_mod.time()
                _last_trade_ts = self._symbol_last_trade_time.get(symbol, 0.0)
                if _last_trade_ts > 0:
                    _elapsed = _now - _last_trade_ts
                    _cooldown_s = self.exit_config.get_cooldown_seconds(
                        trades_per_hour=getattr(self, '_recent_trades_per_hour', 2.0)
                    )
                    if _elapsed < _cooldown_s:
                        logger.debug(
                            "   ⏳ %s: Cooldown active (%.0fs remaining, window=%ds)",
                            symbol, _cooldown_s - _elapsed, _cooldown_s,
                        )
                        return {
                            'action': 'hold',
                            'reason': (
                                f"Re-entry cooldown: {_cooldown_s - _elapsed:.0f}s remaining"
                            ),
                        }

            # Check if we have an existing position
            position = self.execution_engine.get_position(symbol)
            current_price = df['close'].iloc[-1]

            if position:
                # Manage existing position
                logger.debug(f"📊 Managing position: {symbol} @ ${current_price:.4f}")

                # PRIORITY 0: Profit Harvest Layer – ratchet-tier floor checks
                # Updates the tier lock and fires a floor-hit exit when price retraces
                # to the locked-profit stop level.  Also deposits any newly-harvested
                # amount into the capital recycling pool for re-deployment.
                if self.profit_harvest_layer is not None:
                    try:
                        harvest_decision = self.profit_harvest_layer.process_price_update(
                            symbol, current_price
                        )
                        # Floor hit: the ratchet stop was breached – close immediately
                        if harvest_decision.floor_hit:
                            return {
                                'action': 'exit',
                                'reason': (
                                    f'🔒 Profit lock floor hit (tier {harvest_decision.current_tier}): '
                                    f'locking {harvest_decision.locked_profit_pct:.2f}% of peak gain'
                                ),
                                'position': position,
                                'current_price': current_price,
                            }
                        # New tier upgrade → harvest the incremental amount into recycling pool
                        if (
                            harvest_decision.harvest_triggered
                            and harvest_decision.harvest_amount_usd > 0
                            and self.capital_recycling_engine is not None
                        ):
                            try:
                                regime = str(self.current_regime) if self.current_regime else 'UNKNOWN'
                                self.capital_recycling_engine.deposit_profit(
                                    amount_usd=harvest_decision.harvest_amount_usd,
                                    source_symbol=symbol,
                                    regime=regime,
                                )
                                logger.debug(
                                    f"   💰 Harvested ${harvest_decision.harvest_amount_usd:.2f} "
                                    f"from {symbol} → recycling pool"
                                )
                            except Exception as _recycl_err:
                                logger.warning(f"Capital recycling deposit error: {_recycl_err}")
                    except Exception as _harvest_err:
                        logger.debug(f"Profit harvest layer update error: {_harvest_err}")

                should_exit, exit_reason = self.check_exit_conditions(
                    symbol, df, indicators, current_price
                )

                if should_exit:
                    return {
                        'action': 'exit',
                        'reason': exit_reason,
                        'position': position,
                        'current_price': current_price
                    }

                # PRIORITY 1: Check stepped profit exits (more aggressive, fee-aware)
                # This takes profits gradually as position becomes profitable
                stepped_exit = self.execution_engine.check_stepped_profit_exits(symbol, current_price)
                if stepped_exit:
                    return {
                        'action': 'partial_exit',
                        'reason': f"Stepped profit exit at {stepped_exit['profit_level']} (NET: {stepped_exit['net_profit_pct']*100:.1f}%)",
                        'position': position,
                        'exit_size': stepped_exit['exit_size'],
                        'exit_pct': stepped_exit['exit_pct'],
                        'current_price': current_price
                    }

                # PRIORITY 2: Check traditional take profit levels (backup)
                tp_level = self.execution_engine.check_take_profit_hit(symbol, current_price)
                if tp_level:
                    return {
                        'action': f'take_profit_{tp_level}',
                        'reason': f'{tp_level.upper()} reached',
                        'position': position
                    }

                # Update trailing stop
                atr = scalar(indicators['atr'].iloc[-1])
                if position.get('tp1_hit', False):
                    new_stop = self.risk_manager.calculate_trailing_stop(
                        current_price, position['entry_price'],
                        position['side'], atr, breakeven_mode=True
                    )
                    self.execution_engine.update_stop_loss(symbol, new_stop)

                return {
                    'action': 'hold',
                    'reason': 'Position being managed',
                    'position': position
                }

            # No position - check for entry
            adx = scalar(indicators['adx'].iloc[-1])

            # SAFE PROFIT MODE GATE: Block new entries when daily profit is locked in.
            # This prevents giving back the day's gains by continuing to trade after
            # the daily target has been reached or sufficient profit is ratchet-locked.
            if self.safe_profit_mode is not None and self.safe_profit_mode.should_block_entry():
                self.safe_profit_mode.record_blocked_attempt()
                block_reason = self.safe_profit_mode.get_block_reason()
                logger.info(f"   🔒 {symbol}: {block_reason}")
                return {
                    'action': 'hold',
                    'reason': block_reason,
                }

            # EARLY FILTER: Check if we can afford minimum position size for this broker
            # This avoids wasting computation on trades that will be rejected anyway
            broker_name = self._get_broker_name()

            # Kraken requires $10 minimum, others typically allow smaller sizes
            min_required_balance = BROKER_MIN_ORDER_USD.get(broker_name.lower(), _DEFAULT_MIN_ORDER_USD)

            # Calculate maximum possible position size
            # For small accounts (<$100), use 20% to meet broker minimums
            # For larger accounts, use configured max (typically 10%)
            if account_balance < SMALL_ACCOUNT_THRESHOLD:
                max_position_pct = SMALL_ACCOUNT_MAX_POSITION_PCT
            else:
                max_position_pct = self.risk_manager.max_position_pct

            max_position_size = account_balance * max_position_pct

            # If even our maximum possible position is below minimum, skip analysis entirely
            if max_position_size < min_required_balance:
                logger.info(f"   ❌ {symbol}: Account too small for {broker_name}")
                logger.info(f"      Balance: ${account_balance:.2f} | Max position: ${max_position_size:.2f} ({max_position_pct*100:.0f}%)")
                logger.info(f"      Required minimum: ${min_required_balance:.2f}")
                # Guard against division by zero
                if max_position_pct > 0:
                    min_balance_needed = min_required_balance / max_position_pct
                    logger.info(f"      💡 Need ${min_balance_needed:.2f}+ balance to trade on {broker_name}")
                else:
                    logger.info(f"      💡 Need larger balance to trade on {broker_name}")
                return {
                    'action': 'hold',
                    'reason': f'Account too small for {broker_name} minimum (${min_required_balance:.2f})'
                }

            if trend == 'uptrend':
                # Use enhanced scoring if available, otherwise legacy
                if self.use_enhanced_scoring:
                    long_signal, score, reason, metadata = self.check_entry_with_enhanced_scoring(
                        df, indicators, 'long', account_balance
                    )
                else:
                    long_signal, score, reason = self.check_long_entry(df, indicators)
                    metadata = {}

                # ── Momentum / Breakout fallback (score-based OR logic) ────────
                # When the institutional check misses, try the simpler momentum
                # and breakout patterns.  These require only 2-3 confirmations so
                # they produce repeatable daily trades even in quiet markets.
                _momentum_entry_type = None
                if not long_signal and MOMENTUM_ENTRY_AVAILABLE:
                    try:
                        _mom_sig, _mom_score, _mom_reason = check_momentum_long(df, indicators)
                        if _mom_sig:
                            long_signal, score, reason = _mom_sig, _mom_score, _mom_reason
                            metadata = {'entry_source': 'momentum'}
                            _momentum_entry_type = 'momentum'
                            logger.info("   ⚡ %s: MOMENTUM long entry — %s", symbol, _mom_reason)
                    except Exception as _me:
                        logger.debug("momentum_long error: %s", _me)

                if not long_signal and MOMENTUM_ENTRY_AVAILABLE:
                    try:
                        _bo_sig, _bo_score, _bo_reason = check_breakout_long(df, indicators)
                        if _bo_sig:
                            long_signal, score, reason = _bo_sig, _bo_score, _bo_reason
                            metadata = {'entry_source': 'breakout'}
                            _momentum_entry_type = 'breakout'
                            logger.info("   🚀 %s: BREAKOUT long entry — %s", symbol, _bo_reason)
                    except Exception as _be:
                        logger.debug("breakout_long error: %s", _be)

                if long_signal:
                    # ── Score-based AI Entry Gate (LONG) ──────────────────────
                    # Gates contribute weighted points; trade passes when total ≥ threshold.
                    # Drought safeguard lowers gate thresholds by gate_score_reduction %.
                    _entry_type_l = _momentum_entry_type or self._get_entry_type_for_regime(self.current_regime)
                    _drought_l = (
                        self._freq_ctrl.get_drought_relaxation()
                        if self._freq_ctrl is not None else None
                    )
                    _gate_reduction_l = _drought_l.gate_pct_reduction if (_drought_l and _drought_l.active) else 0.0
                    # NIJA_MICROCAP_RELAX_SIDEWAYS: in consolidation/ranging/sideways
                    # regimes the gate is relaxed slightly so the bot stays active
                    # without abandoning edge discipline.
                    if _MICROCAP_RELAX_SIDEWAYS and self.current_regime is not None:
                        _regime_str_l = str(getattr(self.current_regime, 'value',
                                                     self.current_regime)).lower()
                        if any(r in _regime_str_l for r in
                               ("consolidation", "ranging", "sideways", "chop")):
                            _gate_reduction_l = min(0.20, _gate_reduction_l + _MICROCAP_SIDEWAYS_GATE_REDUCTION)
                    # Market-strength gate bonus: weak market conditions relax the threshold.
                    # Equivalent to "+score when trend is confirmed" — strength 1.0 → 0%,
                    # strength 0.6 → 4%, strength 0.2 → 12%, strength 0.0 → 16% bonus.
                    _market_gate_bonus = max(0.0, (0.8 - _market_strength) * 0.20)
                    _gate_reduction_l = min(0.35, _gate_reduction_l + _market_gate_bonus)
                    if self.ai_entry_gate is not None:
                        try:
                            _gate_vol_mult_l: Optional[float] = None
                            if (REGIME_BRIDGE_AVAILABLE and self.regime_bridge is not None
                                    and self.current_regime is not None):
                                try:
                                    _gate_vol_mult_l = self.regime_bridge.get_params(
                                        self.current_regime
                                    ).volume_gate_multiplier
                                except Exception:
                                    pass
                            _gate_result_l = self.ai_entry_gate.check(
                                df=df,
                                indicators=indicators,
                                side='long',
                                enhanced_score=float(score),
                                regime=self.current_regime,
                                broker=broker_name,
                                entry_type=_entry_type_l,
                                gate_score_reduction=_gate_reduction_l,
                                volume_gate_multiplier=_gate_vol_mult_l,
                            )
                            if not _gate_result_l.passed:
                                _gate_score = _gate_result_l.gates.get("gate1_score")
                                _gate_volume = _gate_result_l.gates.get("gate2_volume")
                                _gate_spread = _gate_result_l.gates.get("gate4_spread")
                                _score_detail = (
                                    "%.1f < %.1f" % (_gate_score.value, _gate_score.threshold)
                                    if _gate_score else "n/a"
                                )
                                # VOLATILITY_EXPLOSION is the only hard block (capital protection)
                                if _gate_result_l.regime_name == "volatility_explosion":
                                    logger.warning(
                                        "🛑 VOLATILITY_EXPLOSION: LONG entry hard-blocked (%s)",
                                        symbol,
                                    )
                                    return {'action': 'hold', 'reason': _gate_result_l.reason}
                                # All other gate failures: log advisory, proceed (score-based arch)
                                logger.warning(
                                    "⚠️ AIEntryGate LONG soft-fail %s (proceeding): "
                                    "gate_score=%.1f/%d gate1=%s | %s",
                                    symbol,
                                    _gate_result_l.gate_score,
                                    _gate_result_l.gate_max,
                                    _score_detail,
                                    _gate_result_l.reason,
                                )
                                logger.info(
                                    f"TRADE REJECTED → reason={_gate_result_l.reason}"
                                    f" score={_gate_result_l.gate_score} conf={score}"
                                )
                        except Exception as _gate_l_err:
                            logger.debug("AI Entry Gate error (long): %s", _gate_l_err)

                    # Resolve exit params for this entry (used for SL/TP/trailing)
                    if self.exit_config is not None:
                        try:
                            self._active_exit_params = self.exit_config.get_exit_params(
                                regime=self.current_regime,
                                entry_type=_entry_type_l,
                                broker=broker_name,
                                trades_per_hour=getattr(self, '_recent_trades_per_hour', 2.0),
                            )
                        except Exception as _exc_l_err:
                            logger.debug("Exit config error (long): %s", _exc_l_err)
                            self._active_exit_params = None
                    else:
                        self._active_exit_params = None

                    # Calculate position size
                    # CRITICAL (Rule #3): account_balance is now TOTAL EQUITY (cash + positions)
                    # from broker.get_account_balance() which returns total equity, not just cash
                    risk_score = self._get_risk_score(score, metadata)

                    # Get broker context for intelligent minimum position adjustments
                    broker_min = BROKER_MIN_ORDER_USD.get(broker_name.lower(), _DEFAULT_MIN_ORDER_USD)

                    # Extract regime confidence for GOD MODE+ adaptive risk (if available)
                    regime_confidence = metadata.get('regime_confidence', None) if metadata else None

                    position_size, size_breakdown = self.risk_manager.calculate_position_size(
                        account_balance, adx, risk_score,
                        broker_name=broker_name,
                        broker_min_position=broker_min,
                        regime_confidence=regime_confidence
                    )
                    # Normalize position_size (defensive programming - ensures scalar even if tuple unpacking changes)
                    position_size = scalar(position_size)

                    # ── Industry Principle #3: Risk-Per-Trade override (LONG) ──
                    # When ATR is available, re-size to risk exactly 1-2% of account
                    # based on stop-loss distance rather than a raw balance percentage.
                    if (RISK_PER_TRADE_SIZER_AVAILABLE and self.risk_per_trade_sizer is not None):
                        try:
                            _atr_val_l = float(indicators.get('atr', pd.Series([0])).iloc[-1])
                            _entry_price_l = float(df['close'].iloc[-1])
                            _risk_pct_l = None
                            if (REGIME_BRIDGE_AVAILABLE and self.regime_bridge is not None
                                    and self.current_regime is not None):
                                _rb_p_l = self.regime_bridge.get_params(self.current_regime)
                                _risk_pct_l = _rb_p_l.risk_per_trade_pct / 100.0
                            _rpt_l = self.risk_per_trade_sizer.calculate(
                                account_balance=account_balance,
                                entry_price=_entry_price_l,
                                atr_value=_atr_val_l if _atr_val_l > 0 else None,
                                risk_pct_override=_risk_pct_l,
                                side='long',
                            )
                            if _rpt_l.position_size_usd > 0:
                                position_size = scalar(_rpt_l.position_size_usd)
                        except Exception as _rpt_l_err:
                            logger.debug("Risk-per-trade sizer error (long): %s", _rpt_l_err)

                    # ── Drawdown Risk Controller: ATR dynamic sizing (LONG) ───
                    # Apply the risk envelope multiplier (0.0–1.0) from the pre-filter.
                    # This ensures high-volatility periods automatically trade smaller.
                    _env_mult = getattr(self, '_risk_envelope_multiplier', 1.0)
                    if _env_mult < 1.0 and _env_mult > 0.0:
                        _pre_env = position_size
                        position_size = scalar(position_size * _env_mult)
                        logger.debug(
                            "   🛡️  Risk envelope LONG: $%.2f × %.2f = $%.2f",
                            _pre_env, _env_mult, position_size,
                        )

                    # ── ATR-Based Dynamic Position Sizing (LONG) ──────────────
                    # Scale position size inversely with ATR: high volatility → smaller
                    # positions to preserve R/R and limit drawdown exposure.
                    # Reference: 2% ATR = 1.0× (no adjustment); 4% ATR = 0.5× etc.
                    _atr_val_for_size = float(indicators.get('atr', pd.Series([0])).iloc[-1])
                    _price_for_size   = float(df['close'].iloc[-1])
                    if _atr_val_for_size > 0 and _price_for_size > 0:
                        _atr_pct_for_size = _atr_val_for_size / _price_for_size
                        _atr_size_mult = min(
                            max(_ATR_POSITION_SIZE_REFERENCE / _atr_pct_for_size, 0.25),
                            1.5,
                        )
                        if abs(_atr_size_mult - 1.0) > 0.05:  # only log when adjustment is meaningful
                            _pre_atr_size = position_size
                            position_size = scalar(position_size * _atr_size_mult)
                            logger.debug(
                                "   📐 ATR size LONG: atr=%.2f%% mult=%.2f → $%.2f→$%.2f",
                                _atr_pct_for_size * 100, _atr_size_mult,
                                _pre_atr_size, position_size,
                            )

                    # Adjust position size based on regime and score
                    if self.use_enhanced_scoring and self.current_regime:
                        position_size = self.adjust_position_size_for_regime(
                            position_size, self.current_regime, score
                        )
                    # multiplier (1.0–3.0) that gradually increases position
                    # sizes, compounding capital growth automatically.
                    if self.portfolio_profit_flywheel is not None:
                        try:
                            flywheel_mult = self.portfolio_profit_flywheel.get_capital_multiplier()
                            if flywheel_mult > 1.0:
                                max_allowed = account_balance * self.risk_manager.max_position_pct
                                position_size = min(position_size * flywheel_mult, max_allowed)
                                position_size = scalar(position_size)
                                logger.debug(
                                    f"   🌀 Flywheel ×{flywheel_mult:.2f} → long ${position_size:.2f}"
                                )
                        except Exception as _fw_err:
                            logger.debug(f"Flywheel multiplier error (long): {_fw_err}")

                    # ── AI Intelligence Hub ────────────────────────────────
                    # Evaluate trade through the three AI layers:
                    #   1. AI Market Regime Detection (7-class classifier)
                    #   2. Portfolio Risk Engine (correlation-adjusted sizing)
                    #   3. Capital Allocation AI (Sharpe-weighted capital routing)
                    if self.use_ai_hub and self.ai_hub is not None:
                        base_pct = (
                            position_size / account_balance
                            if account_balance > 0 else 0.05
                        )
                        ai_eval = self.ai_hub.evaluate_trade(
                            symbol=symbol,
                            side='long',
                            df=df,
                            indicators=indicators,
                            base_size_pct=base_pct,
                            portfolio_value=account_balance,
                        )
                        if not ai_eval.ai_approved:
                            logger.info(
                                "   ⚠️ AI Hub LONG advisory %s (proceeding): %s",
                                symbol, ai_eval.ai_reason
                            )
                            logger.info(
                                f"TRADE REJECTED → reason=AI Hub: {ai_eval.ai_reason}"
                                f" score={score} conf={score}"
                            )
                        # Use AI-adjusted position size (correlation + regime)
                        ai_adjusted_size = ai_eval.correlation_adjusted_size_pct * account_balance
                        if ai_adjusted_size > 0 and ai_adjusted_size != position_size:
                            logger.info(
                                "   \U0001f916 AI Hub adjusted LONG size: $%.2f → $%.2f "
                                "(regime=%s, score=%.2f)",
                                position_size, ai_adjusted_size,
                                ai_eval.regime, ai_eval.ai_score,
                            )
                            position_size = ai_adjusted_size
                        metadata['ai_eval'] = ai_eval.to_dict()
                    # ──────────────────────────────────────────────────────

                    if float(position_size) == 0:
                        return {
                            'action': 'hold',
                            'reason': f'Position size = 0 (ADX={adx:.1f} < {self.min_adx})'
                        }

                    # Validate trade quality (position size minimum — physical limit)
                    validation = self._validate_trade_quality(position_size, risk_score,
                                                             account_balance=account_balance)
                    if not validation['valid']:
                        logger.info(
                            f"   ⚠️  Trade validation advisory LONG {symbol}"
                            f" (proceeding): {validation['reason']}"
                        )
                        logger.info(
                            f"TRADE REJECTED → reason={validation['reason']}"
                            f" score={score} conf={score}"
                        )
                    if not eligibility['eligible']:
                        logger.info(
                            f"   ⚠️  Trade eligibility advisory LONG {symbol}"
                            f" (proceeding): {eligibility['reason']}"
                        )
                        logger.info(
                            f"TRADE REJECTED → reason={eligibility['reason']}"
                            f" score={score} conf={score}"
                        )
                    
                    # Apply Kraken-specific confidence threshold if on Kraken
                    kraken_check = self._check_kraken_confidence(broker_name, validation)
                    if kraken_check:
                        return kraken_check
                    
                    # 🔔 FIRST TRADE SANITY CHECK (Jan 30, 2026)
                    # Log comprehensive details before attempting first trade
                    self._log_first_trade_sanity_check(
                        symbol, 'LONG', current_price, position_size, account_balance,
                        broker_name, score, validation, adx, eligibility, trend, reason
                    )

                    # ── HF Scalping: tight fixed stop/TP override ─────────────────
                    # When active, bypass ATR-based targets and the R:R ratio gate
                    # in favour of fixed-percentage scalp levels.
                    if getattr(self, '_hf_scalp_active', False):
                        _sl_pct = getattr(self, '_hf_stop_pct', 0.3) / 100.0
                        _tp_pct = getattr(self, '_hf_tp_pct', 0.5) / 100.0
                        stop_loss  = current_price * (1.0 - _sl_pct)
                        tp_levels  = [current_price * (1.0 + _tp_pct)]
                        logger.info(
                            "   ⚡ [HF-SCALP LONG] %s — SL=%.4f (%.1f%%)  TP=%.4f (%.1f%%)",
                            symbol, stop_loss, _sl_pct * 100, tp_levels[0], _tp_pct * 100,
                        )
                    else:
                        # Calculate stop loss and take profit
                        swing_low = self.risk_manager.find_swing_low(df, lookback=10)
                        atr = scalar(indicators['atr'].iloc[-1])
                        _atr_pct_long = atr / current_price if current_price > 0 else 0.0
                        stop_loss = self.risk_manager.calculate_stop_loss(
                            current_price, 'long', swing_low, atr,
                            regime=self.current_regime,
                        )

                        # ── Execution Exit Config: hard SL cap (LONG) ────────────
                        # Apply the regime-aware hard stop-loss % as a FLOOR on stop
                        # (i.e. stop can't be FURTHER than hard_sl_pct below entry)
                        if self._active_exit_params is not None:
                            try:
                                _hard_sl = self._active_exit_params.stop.hard_sl_pct
                                _sl_floor = current_price * (1.0 - _hard_sl)
                                if stop_loss < _sl_floor:
                                    logger.debug(
                                        "   ⚙️  SL tightened by exit config: %.4f → %.4f "
                                        "(%.2f%% hard cap)",
                                        stop_loss, _sl_floor, _hard_sl * 100,
                                    )
                                    stop_loss = _sl_floor
                            except Exception as _sl_cap_err:
                                logger.debug("Exit config SL cap error (long): %s", _sl_cap_err)

                        # ✅ ADAPTIVE PROFIT TARGETS (INSTITUTIONAL UPGRADE - Jan 29, 2026)
                        # Get broker-specific round-trip fee and use it for dynamic profit targets
                        # Enhanced with ATR and volatility-based adaptive targeting for institutional performance
                        # - Expands targets in high volatility to capture bigger trends
                        # - Contracts targets in low volatility to lock profits faster and avoid whipsaws
                        # - Always maintains minimum fee coverage (1.8x broker fee)
                        broker_capabilities = self._get_broker_capabilities(symbol)
                        broker_fee = broker_capabilities.get_round_trip_fee(use_limit_order=True) if broker_capabilities else None

                        # Extract volatility bandwidth for adaptive profit targeting
                        volatility_bandwidth = scalar(indicators['bb_bandwidth'].iloc[-1])

                        tp_levels = self.risk_manager.calculate_take_profit_levels(
                            current_price, stop_loss, 'long',
                            broker_fee_pct=broker_fee,
                            use_limit_order=True,
                            atr=atr,
                            volatility_bandwidth=volatility_bandwidth,
                            atr_pct=_atr_pct_long,
                        )

                        # ── Execution Exit Config: TP level override (LONG) ───────
                        # When the exit config provides a profile-based TP ladder,
                        # convert pct targets to prices and override the legacy levels.
                        if self._active_exit_params is not None:
                            try:
                                _tp_cfg = self._active_exit_params.tp
                                if _tp_cfg.levels:
                                    tp_levels = [
                                        current_price * (1.0 + lv.target_pct)
                                        for lv in _tp_cfg.levels
                                    ]
                            except Exception as _tp_ov_err:
                                logger.debug("Exit config TP override error (long): %s", _tp_ov_err)

                        # Adjust TP levels based on regime if enhanced scoring is enabled
                        if self.use_enhanced_scoring and self.current_regime:
                            tp_levels = self.regime_detector.adjust_take_profit_levels(
                                self.current_regime, tp_levels
                            )

                        # ═══════════════════════════════════════════════════════════════
                        # LAYER 2: TRADE MATH VERIFICATION
                        # ═══════════════════════════════════════════════════════════════
                        # Verify trade has acceptable math before accepting signal
                        # This is our last line of defense against poor-quality setups

                        # Extract first target for ratio calculation
                        first_target = tp_levels[0] if isinstance(tp_levels, list) else tp_levels

                        # Compute reward and risk amounts
                        risk_dollars = abs(current_price - stop_loss)
                        reward_dollars = abs(first_target - current_price)

                        # Calculate ratio (reward / risk)
                        trade_ratio = reward_dollars / risk_dollars if risk_dollars > 0 else 0

                        # Advisory: minimum acceptable ratio is 1.0 (aligned with MIN_REWARD_RISK)
                        MIN_ACCEPTABLE_RATIO = 1.0
                        if trade_ratio < MIN_ACCEPTABLE_RATIO:
                            logger.info(
                                f"   ⚠️  Trade math advisory LONG {symbol}: ratio {trade_ratio:.2f}"
                                f" below {MIN_ACCEPTABLE_RATIO} (proceeding)"
                            )
                            logger.info(
                                f"TRADE REJECTED → reason=Poor trade math: {trade_ratio:.2f}:1"
                                f" score={score} conf={score}"
                            )

                        # Stop placement advisory (no hard block)
                        if 'atr' in indicators:
                            atr_value = scalar(indicators['atr'].iloc[-1])
                            stop_distance = abs(current_price - stop_loss)
                            min_stop_distance = atr_value * 1.0
                            if stop_distance < min_stop_distance:
                                logger.info(
                                    f"   ⚠️  Stop tight advisory LONG {symbol}:"
                                    f" {stop_distance:.4f} < {min_stop_distance:.4f} ATR"
                                    f" (proceeding)"
                                )

                        # Log trade math
                        logger.info(f"   ✅ Trade math LONG: {trade_ratio:.2f}:1 ratio")

                    # ── Smart Reinvest Cycles (LONG) ───────────────────────
                    # Re-deploy recycled locked profits only when all 7 conditions
                    # are simultaneously perfect.  Augments position size with
                    # claimed capital from the recycling pool.
                    regime_str = str(self.current_regime) if self.current_regime else 'UNKNOWN'
                    position_size = self._apply_smart_reinvestment(
                        position_size=position_size,
                        strategy='ApexTrend',
                        regime=regime_str,
                        account_balance=account_balance,
                    )
                    # ──────────────────────────────────────────────────────

                    result = {
                        'action': 'enter_long',
                        'reason': reason,
                        'entry_price': current_price,
                        'position_size': position_size,
                        'stop_loss': stop_loss,
                        'take_profit': tp_levels,
                        'score': score,
                        'confidence': validation.get('confidence', 0.0),
                        'adx': adx
                    }

                    # Add metadata if available
                    if metadata:
                        result['metadata'] = metadata

                    # Record trade for frequency controller (drought safeguard)
                    if self._freq_ctrl is not None:
                        try:
                            self._freq_ctrl.record_trade()
                        except Exception:
                            pass

                    return result

            elif trend == 'downtrend':
                # ✅ BROKER-AWARE SHORT EXECUTION (HIGH-IMPACT OPTIMIZATION)
                # Check if this broker/symbol supports shorting BEFORE analyzing
                # This prevents wasted computational cycles on blocked trades
                # Effect: Increases win rate, capital utilization, compounding speed
                if EXCHANGE_CAPABILITIES_AVAILABLE:
                    if not can_short(broker_name, symbol):
                        logger.debug(f"   {symbol}: Skipping SHORT analysis - {broker_name} does not support shorting for {symbol}")
                        logger.debug(f"      Market mode: SPOT (long-only) | For shorting use FUTURES/PERPS")
                        return {
                            'action': 'hold',
                            'reason': f'{broker_name} does not support shorting for {symbol} (SPOT market - long-only)'
                        }
                else:
                    # If exchange capabilities not available, log warning but allow (risky)
                    logger.warning(f"⚠️  Exchange capability check unavailable - analyzing SHORT for {symbol} (risky!)")

                # Use enhanced scoring if available, otherwise legacy
                if self.use_enhanced_scoring:
                    short_signal, score, reason, metadata = self.check_entry_with_enhanced_scoring(
                        df, indicators, 'short', account_balance
                    )
                else:
                    short_signal, score, reason = self.check_short_entry(df, indicators)
                    metadata = {}

                # ── Momentum / Breakout fallback (score-based OR logic) ────────
                _momentum_entry_type_s = None
                if not short_signal and MOMENTUM_ENTRY_AVAILABLE:
                    try:
                        _mom_sig_s, _mom_score_s, _mom_reason_s = check_momentum_short(df, indicators)
                        if _mom_sig_s:
                            short_signal, score, reason = _mom_sig_s, _mom_score_s, _mom_reason_s
                            metadata = {'entry_source': 'momentum'}
                            _momentum_entry_type_s = 'momentum'
                            logger.info("   ⚡ %s: MOMENTUM short entry — %s", symbol, _mom_reason_s)
                    except Exception as _me_s:
                        logger.debug("momentum_short error: %s", _me_s)

                if not short_signal and MOMENTUM_ENTRY_AVAILABLE:
                    try:
                        _bo_sig_s, _bo_score_s, _bo_reason_s = check_breakout_short(df, indicators)
                        if _bo_sig_s:
                            short_signal, score, reason = _bo_sig_s, _bo_score_s, _bo_reason_s
                            metadata = {'entry_source': 'breakout'}
                            _momentum_entry_type_s = 'breakout'
                            logger.info("   🚀 %s: BREAKOUT short entry — %s", symbol, _bo_reason_s)
                    except Exception as _be_s:
                        logger.debug("breakout_short error: %s", _be_s)

                if short_signal:
                    # ── Score-based AI Entry Gate (SHORT) ─────────────────────
                    _entry_type_s = _momentum_entry_type_s or self._get_entry_type_for_regime(self.current_regime)
                    _drought_s = (
                        self._freq_ctrl.get_drought_relaxation()
                        if self._freq_ctrl is not None else None
                    )
                    _gate_reduction_s = _drought_s.gate_pct_reduction if (_drought_s and _drought_s.active) else 0.0
                    # NIJA_MICROCAP_RELAX_SIDEWAYS: mirror the long-side gate relaxation
                    if _MICROCAP_RELAX_SIDEWAYS and self.current_regime is not None:
                        _regime_str_s = str(getattr(self.current_regime, 'value',
                                                     self.current_regime)).lower()
                        if any(r in _regime_str_s for r in
                               ("consolidation", "ranging", "sideways", "chop")):
                            _gate_reduction_s = min(0.20, _gate_reduction_s + _MICROCAP_SIDEWAYS_GATE_REDUCTION)
                    # Market-strength gate bonus (mirrors long-side logic).
                    _market_gate_bonus_s = max(0.0, (0.8 - _market_strength) * 0.20)
                    _gate_reduction_s = min(0.35, _gate_reduction_s + _market_gate_bonus_s)
                    if self.ai_entry_gate is not None:
                        try:
                            _gate_vol_mult_s: Optional[float] = None
                            if (REGIME_BRIDGE_AVAILABLE and self.regime_bridge is not None
                                    and self.current_regime is not None):
                                try:
                                    _gate_vol_mult_s = self.regime_bridge.get_params(
                                        self.current_regime
                                    ).volume_gate_multiplier
                                except Exception:
                                    pass
                            _gate_result_s = self.ai_entry_gate.check(
                                df=df,
                                indicators=indicators,
                                side='short',
                                enhanced_score=float(score),
                                regime=self.current_regime,
                                broker=broker_name,
                                entry_type=_entry_type_s,
                                gate_score_reduction=_gate_reduction_s,
                                volume_gate_multiplier=_gate_vol_mult_s,
                            )
                            if not _gate_result_s.passed:
                                _gate_score_short = _gate_result_s.gates.get("gate1_score")
                                _gate_volume_short = _gate_result_s.gates.get("gate2_volume")
                                _gate_spread_short = _gate_result_s.gates.get("gate4_spread")
                                _score_detail_short = (
                                    "%.1f < %.1f" % (_gate_score_short.value, _gate_score_short.threshold)
                                    if _gate_score_short else "n/a"
                                )
                                # VOLATILITY_EXPLOSION is the only hard block (capital protection)
                                if _gate_result_s.regime_name == "volatility_explosion":
                                    logger.warning(
                                        "🛑 VOLATILITY_EXPLOSION: SHORT entry hard-blocked (%s)",
                                        symbol,
                                    )
                                    return {'action': 'hold', 'reason': _gate_result_s.reason}
                                # All other gate failures: log advisory, proceed (score-based arch)
                                logger.warning(
                                    "⚠️ AIEntryGate SHORT soft-fail %s (proceeding): "
                                    "gate_score=%.1f/%d gate1=%s | %s",
                                    symbol,
                                    _gate_result_s.gate_score,
                                    _gate_result_s.gate_max,
                                    _score_detail_short,
                                    _gate_result_s.reason,
                                )
                                logger.info(
                                    f"TRADE REJECTED → reason={_gate_result_s.reason}"
                                    f" score={_gate_result_s.gate_score} conf={score}"
                                )
                        except Exception as _gate_s_err:
                            logger.debug("AI Entry Gate error (short): %s", _gate_s_err)

                    # Resolve exit params for this short entry
                    if self.exit_config is not None:
                        try:
                            self._active_exit_params = self.exit_config.get_exit_params(
                                regime=self.current_regime,
                                entry_type=_entry_type_s,
                                broker=broker_name,
                                trades_per_hour=getattr(self, '_recent_trades_per_hour', 2.0),
                            )
                        except Exception as _exc_s_err:
                            logger.debug("Exit config error (short): %s", _exc_s_err)
                            self._active_exit_params = None
                    else:
                        self._active_exit_params = None

                    # Calculate position size
                    # CRITICAL (Rule #3): account_balance is now TOTAL EQUITY (cash + positions)
                    # from broker.get_account_balance() which returns total equity, not just cash
                    risk_score = self._get_risk_score(score, metadata)

                    # Get broker context for intelligent minimum position adjustments
                    broker_min = BROKER_MIN_ORDER_USD.get(broker_name.lower(), _DEFAULT_MIN_ORDER_USD)

                    # Extract regime confidence for GOD MODE+ adaptive risk (if available)
                    regime_confidence = metadata.get('regime_confidence', None) if metadata else None

                    position_size, size_breakdown = self.risk_manager.calculate_position_size(
                        account_balance, adx, risk_score,
                        broker_name=broker_name,
                        broker_min_position=broker_min,
                        regime_confidence=regime_confidence
                    )
                    # Normalize position_size (defensive programming - ensures scalar even if tuple unpacking changes)
                    position_size = scalar(position_size)

                    # ── Industry Principle #3: Risk-Per-Trade override (SHORT) ─
                    # When ATR is available, re-size to risk exactly 1-2% of account
                    # based on stop-loss distance rather than a raw balance percentage.
                    if (RISK_PER_TRADE_SIZER_AVAILABLE and self.risk_per_trade_sizer is not None):
                        try:
                            _atr_val_s = float(indicators.get('atr', pd.Series([0])).iloc[-1])
                            _entry_price_s = float(df['close'].iloc[-1])
                            _risk_pct_s = None
                            if (REGIME_BRIDGE_AVAILABLE and self.regime_bridge is not None
                                    and self.current_regime is not None):
                                _rb_p_s = self.regime_bridge.get_params(self.current_regime)
                                _risk_pct_s = _rb_p_s.risk_per_trade_pct / 100.0
                            _rpt_s = self.risk_per_trade_sizer.calculate(
                                account_balance=account_balance,
                                entry_price=_entry_price_s,
                                atr_value=_atr_val_s if _atr_val_s > 0 else None,
                                risk_pct_override=_risk_pct_s,
                                side='short',
                            )
                            if _rpt_s.position_size_usd > 0:
                                position_size = scalar(_rpt_s.position_size_usd)
                        except Exception as _rpt_s_err:
                            logger.debug("Risk-per-trade sizer error (short): %s", _rpt_s_err)

                    # ── Drawdown Risk Controller: ATR dynamic sizing (SHORT) ──
                    _env_mult_s = getattr(self, '_risk_envelope_multiplier', 1.0)
                    if _env_mult_s < 1.0 and _env_mult_s > 0.0:
                        _pre_env_s = position_size
                        position_size = scalar(position_size * _env_mult_s)
                        logger.debug(
                            "   🛡️  Risk envelope SHORT: $%.2f × %.2f = $%.2f",
                            _pre_env_s, _env_mult_s, position_size,
                        )

                    # ── ATR-Based Dynamic Position Sizing (SHORT) ─────────────
                    # Mirror of LONG block: scale position inversely with ATR.
                    _atr_val_for_size_s = float(indicators.get('atr', pd.Series([0])).iloc[-1])
                    _price_for_size_s   = float(df['close'].iloc[-1])
                    if _atr_val_for_size_s > 0 and _price_for_size_s > 0:
                        _atr_pct_for_size_s = _atr_val_for_size_s / _price_for_size_s
                        _atr_size_mult_s = min(
                            max(_ATR_POSITION_SIZE_REFERENCE / _atr_pct_for_size_s, 0.25),
                            1.5,
                        )
                        if abs(_atr_size_mult_s - 1.0) > 0.05:
                            _pre_atr_size_s = position_size
                            position_size = scalar(position_size * _atr_size_mult_s)
                            logger.debug(
                                "   📐 ATR size SHORT: atr=%.2f%% mult=%.2f → $%.2f→$%.2f",
                                _atr_pct_for_size_s * 100, _atr_size_mult_s,
                                _pre_atr_size_s, position_size,
                            )

                    # Adjust position size based on regime and score
                    if self.use_enhanced_scoring and self.current_regime:
                        position_size = self.adjust_position_size_for_regime(
                            position_size, self.current_regime, score
                        )

                    # ── Portfolio Profit Flywheel ──────────────────────────
                    if self.portfolio_profit_flywheel is not None:
                        try:
                            flywheel_mult = self.portfolio_profit_flywheel.get_capital_multiplier()
                            if flywheel_mult > 1.0:
                                max_allowed = account_balance * self.risk_manager.max_position_pct
                                position_size = min(position_size * flywheel_mult, max_allowed)
                                position_size = scalar(position_size)
                                logger.debug(
                                    f"   🌀 Flywheel ×{flywheel_mult:.2f} → short ${position_size:.2f}"
                                )
                        except Exception as _fw_err:
                            logger.debug(f"Flywheel multiplier error (short): {_fw_err}")

                    # ── AI Intelligence Hub ────────────────────────────────
                    # Evaluate trade through the three AI layers:
                    #   1. AI Market Regime Detection (7-class classifier)
                    #   2. Portfolio Risk Engine (correlation-adjusted sizing)
                    #   3. Capital Allocation AI (Sharpe-weighted capital routing)
                    if self.use_ai_hub and self.ai_hub is not None:
                        base_pct = (
                            position_size / account_balance
                            if account_balance > 0 else 0.05
                        )
                        ai_eval = self.ai_hub.evaluate_trade(
                            symbol=symbol,
                            side='short',
                            df=df,
                            indicators=indicators,
                            base_size_pct=base_pct,
                            portfolio_value=account_balance,
                        )
                        if not ai_eval.ai_approved:
                            logger.info(
                                "   ⚠️ AI Hub SHORT advisory %s (proceeding): %s",
                                symbol, ai_eval.ai_reason
                            )
                            logger.info(
                                f"TRADE REJECTED → reason=AI Hub: {ai_eval.ai_reason}"
                                f" score={score} conf={score}"
                            )
                        # Use AI-adjusted position size (correlation + regime)
                        ai_adjusted_size = ai_eval.correlation_adjusted_size_pct * account_balance
                        if ai_adjusted_size > 0 and ai_adjusted_size != position_size:
                            logger.info(
                                "   \U0001f916 AI Hub adjusted SHORT size: $%.2f → $%.2f "
                                "(regime=%s, score=%.2f)",
                                position_size, ai_adjusted_size,
                                ai_eval.regime, ai_eval.ai_score,
                            )
                            position_size = ai_adjusted_size
                        metadata['ai_eval'] = ai_eval.to_dict()
                    # ──────────────────────────────────────────────────────

                    if float(position_size) == 0:
                        return {
                            'action': 'hold',
                            'reason': f'Position size = 0 (ADX={adx:.1f} < {self.min_adx})'
                        }

                    # Validate trade quality (position size minimum — physical limit)
                    validation = self._validate_trade_quality(position_size, risk_score,
                                                             account_balance=account_balance)
                    if not validation['valid']:
                        logger.info(
                            f"   ⚠️  Trade validation advisory SHORT {symbol}"
                            f" (proceeding): {validation['reason']}"
                        )
                        logger.info(
                            f"TRADE REJECTED → reason={validation['reason']}"
                            f" score={score} conf={score}"
                        )

                    # ✅ COMPREHENSIVE TRADE ELIGIBILITY CHECK (Jan 30, 2026)
                    # Verify RSI, volatility (ATR), and spread conditions before entering trade
                    # This unified check prevents marginal trades and enforces quality standards
                    eligibility = self.verify_trade_eligibility(
                        symbol, df, indicators, 'short', position_size
                    )
                    if not eligibility['eligible']:
                        logger.info(
                            f"   ⚠️  Trade eligibility advisory SHORT {symbol}"
                            f" (proceeding): {eligibility['reason']}"
                        )
                        logger.info(
                            f"TRADE REJECTED → reason={eligibility['reason']}"
                            f" score={score} conf={score}"
                        )
                    
                    # Apply Kraken-specific confidence threshold if on Kraken
                    kraken_check = self._check_kraken_confidence(broker_name, validation)
                    if kraken_check:
                        return kraken_check
                    
                    # 🔔 FIRST TRADE SANITY CHECK (Jan 30, 2026)
                    # Log comprehensive details before attempting first trade
                    self._log_first_trade_sanity_check(
                        symbol, 'SHORT', current_price, position_size, account_balance,
                        broker_name, score, validation, adx, eligibility, trend, reason
                    )

                    # ── HF Scalping: tight fixed stop/TP override ─────────────────
                    # When active, bypass ATR-based targets and the R:R ratio gate
                    # in favour of fixed-percentage scalp levels.
                    if getattr(self, '_hf_scalp_active', False):
                        _sl_pct = getattr(self, '_hf_stop_pct', 0.3) / 100.0
                        _tp_pct = getattr(self, '_hf_tp_pct', 0.5) / 100.0
                        stop_loss  = current_price * (1.0 + _sl_pct)
                        tp_levels  = [current_price * (1.0 - _tp_pct)]
                        logger.info(
                            "   ⚡ [HF-SCALP SHORT] %s — SL=%.4f (%.1f%%)  TP=%.4f (%.1f%%)",
                            symbol, stop_loss, _sl_pct * 100, tp_levels[0], _tp_pct * 100,
                        )
                    else:
                        # Calculate stop loss and take profit
                        swing_high = self.risk_manager.find_swing_high(df, lookback=10)
                        atr = scalar(indicators['atr'].iloc[-1])
                        _atr_pct_short = atr / current_price if current_price > 0 else 0.0
                        stop_loss = self.risk_manager.calculate_stop_loss(
                            current_price, 'short', swing_high, atr,
                            regime=self.current_regime,
                        )

                        # ── Execution Exit Config: hard SL cap (SHORT) ───────────
                        if self._active_exit_params is not None:
                            try:
                                _hard_sl_s = self._active_exit_params.stop.hard_sl_pct
                                _sl_ceil_s = current_price * (1.0 + _hard_sl_s)
                                if stop_loss > _sl_ceil_s:
                                    logger.debug(
                                        "   ⚙️  SL tightened by exit config (short): %.4f → %.4f "
                                        "(%.2f%% hard cap)",
                                        stop_loss, _sl_ceil_s, _hard_sl_s * 100,
                                    )
                                    stop_loss = _sl_ceil_s
                            except Exception as _sl_cap_s_err:
                                logger.debug("Exit config SL cap error (short): %s", _sl_cap_s_err)

                        # ✅ ADAPTIVE PROFIT TARGETS (INSTITUTIONAL UPGRADE - Jan 29, 2026)
                        # Get broker-specific round-trip fee and use it for dynamic profit targets
                        # Enhanced with ATR and volatility-based adaptive targeting for institutional performance
                        # - Expands targets in high volatility to capture bigger trends
                        # - Contracts targets in low volatility to lock profits faster and avoid whipsaws
                        # - Always maintains minimum fee coverage (1.8x broker fee)
                        broker_capabilities = self._get_broker_capabilities(symbol)
                        broker_fee = broker_capabilities.get_round_trip_fee(use_limit_order=True) if broker_capabilities else None

                        # Extract volatility bandwidth for adaptive profit targeting
                        volatility_bandwidth = scalar(indicators['bb_bandwidth'].iloc[-1])

                        tp_levels = self.risk_manager.calculate_take_profit_levels(
                            current_price, stop_loss, 'short',
                            broker_fee_pct=broker_fee,
                            use_limit_order=True,
                            atr=atr,
                            volatility_bandwidth=volatility_bandwidth,
                            atr_pct=_atr_pct_short,
                        )

                        # ── Execution Exit Config: TP level override (SHORT) ──────
                        if self._active_exit_params is not None:
                            try:
                                _tp_cfg_s = self._active_exit_params.tp
                                if _tp_cfg_s.levels:
                                    tp_levels = [
                                        current_price * (1.0 - lv.target_pct)
                                        for lv in _tp_cfg_s.levels
                                    ]
                            except Exception as _tp_ov_s_err:
                                logger.debug("Exit config TP override error (short): %s", _tp_ov_s_err)

                        # Adjust TP levels based on regime if enhanced scoring is enabled
                        if self.use_enhanced_scoring and self.current_regime:
                            tp_levels = self.regime_detector.adjust_take_profit_levels(
                                self.current_regime, tp_levels
                            )

                        # ═══════════════════════════════════════════════════════════════
                        # LAYER 2: TRADE MATH VERIFICATION (SHORT)
                        # ═══════════════════════════════════════════════════════════════
                        # Verify trade has acceptable math before accepting signal

                        # Extract first target for ratio calculation
                        first_target = tp_levels[0] if isinstance(tp_levels, list) else tp_levels

                        # Compute reward and risk amounts
                        risk_dollars = abs(stop_loss - current_price)
                        reward_dollars = abs(current_price - first_target)

                        # Calculate ratio (reward / risk)
                        trade_ratio = reward_dollars / risk_dollars if risk_dollars > 0 else 0

                        # Advisory: minimum acceptable ratio is 1.0 (aligned with MIN_REWARD_RISK)
                        MIN_ACCEPTABLE_RATIO = 1.0
                        if trade_ratio < MIN_ACCEPTABLE_RATIO:
                            logger.info(
                                f"   ⚠️  Trade math advisory SHORT {symbol}: ratio {trade_ratio:.2f}"
                                f" below {MIN_ACCEPTABLE_RATIO} (proceeding)"
                            )
                            logger.info(
                                f"TRADE REJECTED → reason=Poor trade math: {trade_ratio:.2f}:1"
                                f" score={score} conf={score}"
                            )

                        # Stop placement advisory (no hard block)
                        if 'atr' in indicators:
                            atr_value = scalar(indicators['atr'].iloc[-1])
                            stop_distance = abs(stop_loss - current_price)
                            min_stop_distance = atr_value * 1.0
                            if stop_distance < min_stop_distance:
                                logger.info(
                                    f"   ⚠️  Stop tight advisory SHORT {symbol}:"
                                    f" {stop_distance:.4f} < {min_stop_distance:.4f} ATR"
                                    f" (proceeding)"
                                )

                        # Log trade math
                        logger.info(f"   ✅ Trade math SHORT: {trade_ratio:.2f}:1 ratio")

                    # ── Smart Reinvest Cycles (SHORT) ──────────────────────
                    # Re-deploy recycled locked profits only when all 7 conditions
                    # are simultaneously perfect.  Augments position size with
                    # claimed capital from the recycling pool.
                    regime_str = str(self.current_regime) if self.current_regime else 'UNKNOWN'
                    position_size = self._apply_smart_reinvestment(
                        position_size=position_size,
                        strategy='ApexTrend',
                        regime=regime_str,
                        account_balance=account_balance,
                    )
                    # ──────────────────────────────────────────────────────

                    result = {
                        'action': 'enter_short',
                        'reason': reason,
                        'entry_price': current_price,
                        'position_size': position_size,
                        'stop_loss': stop_loss,
                        'take_profit': tp_levels,
                        'score': score,
                        'confidence': validation.get('confidence', 0.0),
                        'adx': adx
                    }

                    # Add metadata if available
                    if metadata:
                        result['metadata'] = metadata

                    # Record trade for frequency controller (drought safeguard)
                    if self._freq_ctrl is not None:
                        try:
                            self._freq_ctrl.record_trade()
                        except Exception:
                            pass

                    return result

            return {
                'action': 'hold',
                'reason': f'No entry signal ({trend})',
                'filter_stage': 'no_entry',
            }

        except Exception as e:
            logger.error(f"Analysis error: {e}")
            return {
                'action': 'hold',
                'reason': f'Error: {str(e)}'
            }

    def _apply_smart_reinvestment(
        self,
        position_size: float,
        strategy: str,
        regime: str,
        account_balance: float,
    ) -> float:
        """
        Attempt to augment *position_size* with recycled capital from the
        Smart Reinvest Cycles engine.

        Capital is only deployed when ALL seven conditions are simultaneously
        "perfect" (regime, volatility, risk governor, strategy health, win rate,
        pool level, and cooldown).  On any failure the original size is returned
        unchanged.

        Args:
            position_size:   Base position size already validated by the strategy.
            strategy:        Strategy name used for health / cooldown look-ups.
            regime:          Current market regime string.
            account_balance: Portfolio value in USD (for risk-governor check).

        Returns:
            Potentially augmented position size (>= original *position_size*).
        """
        if self.smart_reinvest_engine is None:
            return position_size
        try:
            extra_usd = self.smart_reinvest_engine.request_reinvestment(
                strategy=strategy,
                regime=regime,
                base_position_usd=position_size,
                portfolio_value=account_balance,
            )
            if extra_usd > 0:
                new_size = position_size + extra_usd
                logger.info(
                    "   🔄 SmartReinvest: $%.2f recycled capital added → "
                    "position $%.2f → $%.2f",
                    extra_usd, position_size, new_size,
                )
                return new_size
        except Exception as _sri_err:
            logger.debug("SmartReinvest augmentation error: %s", _sri_err)
        return position_size

    def _update_safe_profit_mode(self, trade_pnl_usd: float) -> None:
        """
        Update the safe profit mode gate after a trade closes.

        Accumulates today's net P&L and fetches the total ratchet-locked amount
        from the profit harvest layer, then feeds both figures to the
        ``SafeProfitModeManager`` so it can decide whether to activate.

        Args:
            trade_pnl_usd: Net profit (or loss) from the just-closed trade.
        """
        if self.safe_profit_mode is None:
            return

        try:
            # Accumulate daily P&L (reset happens inside SafeProfitModeManager on new day)
            self._daily_pnl_usd += trade_pnl_usd

            # Compute total locked profit from all still-open positions in the harvest layer
            locked_usd = 0.0
            if self.profit_harvest_layer is not None:
                try:
                    for pos_state in self.profit_harvest_layer.get_all_statuses().values():
                        locked_pct = pos_state.get('locked_profit_pct', 0.0)
                        size_usd   = pos_state.get('position_size_usd', 0.0)
                        locked_usd += (locked_pct / 100.0) * size_usd
                except Exception as _lock_err:
                    logger.debug("Safe profit mode: error fetching locked amounts: %s", _lock_err)

            # Derive daily target (stored from last analyze_market call, or fallback)
            daily_target = getattr(self, '_last_daily_target_usd', 0.0)

            self.safe_profit_mode.update(
                daily_profit_usd=max(self._daily_pnl_usd, 0.0),  # only count profit days
                daily_target_usd=daily_target,
                locked_profit_usd=locked_usd,
            )
        except Exception as exc:
            logger.debug("Safe profit mode update error: %s", exc)

    def execute_action(self, action_data: Dict, symbol: str) -> bool:
        """
        Execute the recommended action

        Args:
            action_data: Dictionary from analyze_market()
            symbol: Trading symbol

        Returns:
            True if action executed successfully
        """
        action = action_data.get('action')

        try:
            # EMERGENCY: Check if entries are blocked via STOP_ALL_ENTRIES.conf
            stop_entries_file = os.path.join(os.path.dirname(__file__), '..', 'STOP_ALL_ENTRIES.conf')
            entries_blocked = os.path.exists(stop_entries_file)

            if entries_blocked and ('enter_long' in action or 'enter_short' in action):
                logger.error("🛑 BUY BLOCKED: STOP_ALL_ENTRIES.conf active")
                logger.error(f"   Position cap may be exceeded. Fix required before new entries allowed.")
                return False

            if action == 'enter_long':
                position = self.execution_engine.execute_entry(
                    symbol=symbol,
                    side='long',
                    position_size=action_data['position_size'],
                    entry_price=action_data['entry_price'],
                    stop_loss=action_data['stop_loss'],
                    take_profit_levels=action_data['take_profit']
                )
                if position:
                    logger.info(f"Long entry executed: {symbol} @ {action_data['entry_price']:.2f}")
                    # Register with profit harvest layer so ratchet-tier tracking begins
                    if self.profit_harvest_layer is not None:
                        try:
                            self.profit_harvest_layer.register_position(
                                symbol=symbol,
                                side='long',
                                entry_price=action_data['entry_price'],
                                position_size_usd=action_data['position_size'],
                            )
                        except Exception as _reg_err:
                            logger.debug(f"Harvest layer register error (long): {_reg_err}")
                    return True
                else:
                    logger.warning(
                        f"⚠️  EXECUTION BLOCKED: {symbol} long entry returned no position "
                        f"(broker rejected or nonce pause) — skipping, next cycle will retry"
                    )
                    return False

            elif action == 'enter_short':
                # EXCHANGE CAPABILITY CHECK: Verify broker supports shorting for this symbol
                # This prevents SHORT entries on exchanges that don't support them (e.g., Kraken spot)
                broker_name = self._get_broker_name()

                # Check if this broker/symbol combination supports shorting
                if EXCHANGE_CAPABILITIES_AVAILABLE:
                    if not can_short(broker_name, symbol):
                        logger.warning(f"⚠️  SHORT entry BLOCKED: {broker_name} does not support shorting for {symbol}")
                        logger.warning(f"   Strategy signal: enter_short @ {action_data['entry_price']:.2f}")
                        logger.warning(f"   Exchange: {broker_name} (spot markets don't support shorting)")
                        logger.warning(f"   Symbol: {symbol}")
                        logger.warning(f"   ℹ️  Note: SHORT works on futures/perpetuals (e.g., BTC-PERP)")
                        return False
                else:
                    logger.warning(f"⚠️  Exchange capability check unavailable - allowing SHORT (risky!)")

                # Execute SHORT entry
                position = self.execution_engine.execute_entry(
                    symbol=symbol,
                    side='short',
                    position_size=action_data['position_size'],
                    entry_price=action_data['entry_price'],
                    stop_loss=action_data['stop_loss'],
                    take_profit_levels=action_data['take_profit']
                )
                if position:
                    logger.info(f"✅ Short entry executed: {symbol} @ {action_data['entry_price']:.2f} (broker: {broker_name})")
                    # Register with profit harvest layer so ratchet-tier tracking begins
                    if self.profit_harvest_layer is not None:
                        try:
                            self.profit_harvest_layer.register_position(
                                symbol=symbol,
                                side='short',
                                entry_price=action_data['entry_price'],
                                position_size_usd=action_data['position_size'],
                            )
                        except Exception as _reg_err:
                            logger.debug(f"Harvest layer register error (short): {_reg_err}")
                    return True
                else:
                    logger.warning(
                        f"⚠️  EXECUTION BLOCKED: {symbol} short entry returned no position "
                        f"(broker rejected or nonce pause) — skipping, next cycle will retry"
                    )
                    return False

            elif action == 'exit':
                pos_data = action_data.get('position', {})
                exit_price = action_data.get('current_price', pos_data.get('entry_price', 0.0))
                # Guard: ensure exit_price is a valid positive number before proceeding.
                # If neither current_price nor entry_price is available, skip the exit
                # to avoid corrupt P&L calculations and invalid order submissions.
                if not exit_price or exit_price <= 0:
                    exit_price = pos_data.get('entry_price', 0.0)
                if not exit_price or exit_price <= 0:
                    logger.error(
                        f"❌ Exit skipped for {symbol}: no valid exit price available "
                        f"(current_price={action_data.get('current_price')}, "
                        f"entry_price={pos_data.get('entry_price')})"
                    )
                    return False
                success = self.execution_engine.execute_exit(
                    symbol=symbol,
                    exit_price=exit_price,
                    size_pct=1.0,
                    reason=action_data['reason']
                )
                if success:
                    # Compute approximate NET P&L (after broker fees) for profit-stack recording.
                    # Using net profit ensures the flywheel multiplier reflects real compounded gains.
                    entry_price = pos_data.get('entry_price', exit_price)
                    pos_size = pos_data.get('position_size', 0.0)
                    side = pos_data.get('side', 'long')
                    if entry_price and entry_price > 0 and pos_size is not None and pos_size > 0:
                        gross_change = (exit_price - entry_price) / entry_price
                        gross_pnl = gross_change * pos_size if side == 'long' else -gross_change * pos_size
                        # Deduct round-trip broker fee so flywheel tracks net profit
                        broker_fee = self.execution_engine._get_broker_round_trip_fee()
                        fee_cost = pos_size * broker_fee
                        pnl_usd = gross_pnl - fee_cost
                    else:
                        pnl_usd = 0.0
                    is_win = pnl_usd > 0

                    # Accumulate this trade's P&L into the current cycle tracker
                    self._cycle_pnl += pnl_usd

                    # Record trade in flywheel → updates compound multiplier
                    if self.portfolio_profit_flywheel is not None:
                        try:
                            self.portfolio_profit_flywheel.record_trade(
                                symbol=symbol,
                                pnl_usd=pnl_usd,
                                is_win=is_win,
                            )
                        except Exception as _fw_err:
                            logger.debug(f"Flywheel record error: {_fw_err}")

                    # Remove from harvest layer; flush any remaining harvestable balance
                    if self.profit_harvest_layer is not None:
                        try:
                            final_state = self.profit_harvest_layer.remove_position(symbol)
                            remaining = (final_state or {}).get('harvestable_balance_usd', 0.0)
                            if remaining > 0 and self.capital_recycling_engine is not None:
                                regime = str(self.current_regime) if self.current_regime else 'UNKNOWN'
                                self.capital_recycling_engine.deposit_profit(
                                    amount_usd=remaining,
                                    source_symbol=symbol,
                                    regime=regime,
                                    note='final_flush_on_close',
                                )
                        except Exception as _rem_err:
                            logger.debug(f"Harvest layer remove error: {_rem_err}")

                    # Update safe profit mode with latest daily P&L and locked amounts.
                    # This may activate the mode and block future entries for today.
                    self._update_safe_profit_mode(pnl_usd)

                    # True Profit Tracker — emit mandatory close-log lines:
                    #   NET PROFIT (after fees): $X.XX
                    #   NEW CASH BALANCE: $X.XX
                    if self._true_profit_tracker is not None:
                        try:
                            entry_val = pos_size if (pos_size and pos_size > 0) else 0.0
                            # exit_value = entry_value + gross_pnl when P&L is computed
                            exit_val = (entry_val + gross_pnl) if (entry_val > 0 and entry_price and entry_price > 0) else 0.0
                            current_bal = float(getattr(self, '_last_account_balance', 0.0) or 0)
                            self._true_profit_tracker.record_trade(
                                symbol=symbol,
                                entry_value=entry_val,
                                exit_value=exit_val,
                                fees=fee_cost,
                                current_balance=current_bal,
                            )
                        except Exception as _tpt_rec_err:
                            logger.debug("TrueProfitTracker.record_trade error: %s", _tpt_rec_err)
                return success

            elif action == 'partial_exit':
                # Stepped profit exit (fee-aware gradual profit-taking)
                success = self.execution_engine.execute_exit(
                    symbol=symbol,
                    exit_price=action_data.get('current_price'),
                    size_pct=action_data['exit_pct'],
                    reason=action_data['reason']
                )
                if success:
                    logger.info(f"✅ Partial exit executed: {symbol} - {action_data['exit_pct']*100:.0f}% @ ${action_data['current_price']:.4f}")
                    logger.info(f"   Reason: {action_data['reason']}")
                return success

            elif action.startswith('take_profit_'):
                # Partial exits based on TP level
                if action == 'take_profit_tp1':
                    # Exit 50%, move stop to breakeven
                    success = self.execution_engine.execute_exit(
                        symbol=symbol,
                        exit_price=action_data['position']['tp1'],
                        size_pct=0.5,
                        reason='TP1 hit'
                    )
                    if success:
                        # Move stop to breakeven
                        self.execution_engine.update_stop_loss(
                            symbol, action_data['position']['entry_price']
                        )
                    return success

                elif action == 'take_profit_tp2':
                    # Exit another 25% (75% total out)
                    return self.execution_engine.execute_exit(
                        symbol=symbol,
                        exit_price=action_data['position']['tp2'],
                        size_pct=0.5,  # 50% of remaining
                        reason='TP2 hit'
                    )

                elif action == 'take_profit_tp3':
                    # Exit remaining position
                    return self.execution_engine.execute_exit(
                        symbol=symbol,
                        exit_price=action_data['position']['tp3'],
                        size_pct=1.0,
                        reason='TP3 hit'
                    )

            return False

        except Exception as e:
            logger.error(f"Execution error: {e}")
            return False

    # ============================================================
    # INSTITUTIONAL-GRADE RSI ENTRY FILTERS
    # ============================================================

    def _rsi_long_filter(self, rsi: float) -> bool:
        """
        Institutional long entry RSI filter: buy weakness, not strength.

        Args:
            rsi: Current RSI value (expected range: 0-100)

        Returns:
            True if RSI is in optimal long entry zone (25-45), False otherwise

        Note:
            Invalid RSI values (NaN, infinity, or outside 0-100) return False
        """
        # Validate RSI is a valid number within expected range
        if not isinstance(rsi, (int, float)) or np.isnan(rsi) or np.isinf(rsi):
            return False
        if rsi < 0 or rsi > 100:
            return False

        return 25 <= rsi <= 45

    def _rsi_short_filter(self, rsi: float) -> bool:
        """
        Institutional short entry RSI filter: sell strength, not weakness.

        Args:
            rsi: Current RSI value (expected range: 0-100)

        Returns:
            True if RSI is in optimal short entry zone (55-75), False otherwise

        Note:
            Invalid RSI values (NaN, infinity, or outside 0-100) return False
        """
        # Validate RSI is a valid number within expected range
        if not isinstance(rsi, (int, float)) or np.isnan(rsi) or np.isinf(rsi):
            return False
        if rsi < 0 or rsi > 100:
            return False

        return 55 <= rsi <= 75

    # ============================================================
    # AI MOMENTUM SCORING (SKELETON - PLACEHOLDER FOR FUTURE)
    # ============================================================

    def calculate_ai_momentum_score(self, df: pd.DataFrame,
                                    indicators: Dict) -> float:
        """
        AI-powered momentum scoring system (skeleton)

        Future implementation ideas:
        - Machine learning model trained on historical price patterns
        - Sentiment analysis from news/social media
        - Market regime detection (trending vs ranging)
        - Volume profile analysis
        - Order flow analysis

        Args:
            df: Price DataFrame
            indicators: Dictionary of calculated indicators

        Returns:
            Momentum score (0.0 to 1.0)
        """
        # TODO: Implement AI/ML model here
        # Placeholder: simple weighted combination of indicators

        if self.ai_momentum_enabled:
            # Example: weighted scoring
            rsi = scalar(indicators['rsi'].iloc[-1])
            adx = scalar(indicators['adx'].iloc[-1])
            macd_hist = indicators['histogram'].iloc[-1]

            # Normalize to 0-1 range
            rsi_score = abs(rsi - 50) / 50  # Distance from neutral
            adx_score = min(adx / 50, 1.0)  # Trend strength
            macd_score = 0.5  # Placeholder

            # Weighted average
            momentum_score = (rsi_score * 0.3 + adx_score * 0.5 + macd_score * 0.2)

            return momentum_score

        return 0.5  # Neutral score when disabled
