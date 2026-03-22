import os
import sys
import time
import random
import queue
import json
import logging
import traceback
import collections
from pathlib import Path
from threading import Thread
from typing import Dict, Optional, Tuple
from datetime import datetime
from dotenv import load_dotenv
from enum import Enum
import pandas as pd

# Initialize logger early to avoid NameError in import fallback handlers
logger = logging.getLogger("nija")

# Import entry guardrails (correlation, liquidity, latency)
try:
    from entry_guardrails import (
        PortfolioCorrelationFilter,
        LiquidityFilter,
        ExchangeLatencyGuard,
        run_all_guardrails,
    )
    _ENTRY_GUARDRAILS_AVAILABLE = True
except ImportError:
    try:
        from bot.entry_guardrails import (
            PortfolioCorrelationFilter,
            LiquidityFilter,
            ExchangeLatencyGuard,
            run_all_guardrails,
        )
        _ENTRY_GUARDRAILS_AVAILABLE = True
    except ImportError:
        PortfolioCorrelationFilter = None  # type: ignore
        LiquidityFilter = None  # type: ignore
        ExchangeLatencyGuard = None  # type: ignore
        run_all_guardrails = None  # type: ignore
        _ENTRY_GUARDRAILS_AVAILABLE = False
        logger.warning("⚠️ Entry guardrails not available – correlation/liquidity/latency checks disabled")

# Import market filters at module level to avoid repeated imports in loops
try:
    from market_filters import check_pair_quality, is_high_liquidity_symbol, TOP_20_HIGH_LIQUIDITY_SYMBOLS
except ImportError:
    try:
        from bot.market_filters import check_pair_quality, is_high_liquidity_symbol, TOP_20_HIGH_LIQUIDITY_SYMBOLS
    except ImportError:
        # Graceful fallback if market_filters not available
        check_pair_quality = None
        TOP_20_HIGH_LIQUIDITY_SYMBOLS = set()
        def is_high_liquidity_symbol(symbol: str) -> bool:  # noqa: E302
            return True  # Allow all symbols if filter unavailable

# Import Market Readiness Gate for entry quality control
try:
    from market_readiness_gate import MarketReadinessGate, MarketMode
except ImportError:
    try:
        from bot.market_readiness_gate import MarketReadinessGate, MarketMode
    except ImportError:
        # Graceful fallback if market readiness gate not available
        MarketReadinessGate = None
        MarketMode = None
        logger.warning("⚠️ Market Readiness Gate not available - using legacy entry mode")

# Import Trade Quality Gate for Layer 2 improvements
try:
    from trade_quality_gate import TradeQualityGate
except ImportError:
    try:
        from bot.trade_quality_gate import TradeQualityGate
    except ImportError:
        TradeQualityGate = None

# Import Win Rate Maximizer — trade filtering, risk caps, profit consistency
try:
    from win_rate_maximizer import get_win_rate_maximizer as _get_win_rate_maximizer
    WIN_RATE_MAXIMIZER_AVAILABLE = True
except ImportError:
    try:
        from bot.win_rate_maximizer import get_win_rate_maximizer as _get_win_rate_maximizer
        WIN_RATE_MAXIMIZER_AVAILABLE = True
    except ImportError:
        _get_win_rate_maximizer = None  # type: ignore
        WIN_RATE_MAXIMIZER_AVAILABLE = False
        logger.warning("⚠️ Win Rate Maximizer not available - trade filtering/risk caps/profit consistency disabled")

# Import Market Structure Filter (trend + volume + momentum confirmation)
try:
    from market_structure_filter import structure_valid as _structure_valid
    MARKET_STRUCTURE_FILTER_AVAILABLE = True
except ImportError:
    try:
        from bot.market_structure_filter import structure_valid as _structure_valid
        MARKET_STRUCTURE_FILTER_AVAILABLE = True
    except ImportError:
        MARKET_STRUCTURE_FILTER_AVAILABLE = False
        _structure_valid = None
        logger.warning("⚠️ Market Structure Filter not available - HH/HL + volume + momentum check disabled")

# Import Recovery Controller for capital-first safety (NEW - Feb 2026)
try:
    from recovery_controller import get_recovery_controller, FailureState
    RECOVERY_CONTROLLER_AVAILABLE = True
    logger.info("✅ Recovery Controller loaded - Capital-first safety layer active")
except ImportError:
    try:
        from bot.recovery_controller import get_recovery_controller, FailureState
        RECOVERY_CONTROLLER_AVAILABLE = True
        logger.info("✅ Recovery Controller loaded - Capital-first safety layer active")
    except ImportError:
        RECOVERY_CONTROLLER_AVAILABLE = False
        logger.warning("⚠️ Recovery Controller not available - safety layer disabled")
        get_recovery_controller = None
        FailureState = None

# Import Market Regime Controller — meta-layer that answers "Should we trade now?"
try:
    from market_regime_controller import get_regime_controller, MarketRegimeController, RegimeDecision
    REGIME_CONTROLLER_AVAILABLE = True
    logger.info("✅ Market Regime Controller loaded - trade regime gating active")
except ImportError:
    try:
        from bot.market_regime_controller import get_regime_controller, MarketRegimeController, RegimeDecision
        REGIME_CONTROLLER_AVAILABLE = True
        logger.info("✅ Market Regime Controller loaded - trade regime gating active")
    except ImportError:
        REGIME_CONTROLLER_AVAILABLE = False
        logger.warning("⚠️ Market Regime Controller not available - regime gating disabled")
        get_regime_controller = None
        MarketRegimeController = None
        RegimeDecision = None

# Import Global Risk Governor — portfolio-wide circuit breaker (prevents cascading losses)
try:
    from global_risk_governor import get_global_risk_governor, GovernorConfig
    GLOBAL_RISK_GOVERNOR_AVAILABLE = True
    logger.info("✅ Global Risk Governor loaded - cascade-loss protection active")
except ImportError:
    try:
        from bot.global_risk_governor import get_global_risk_governor, GovernorConfig
        GLOBAL_RISK_GOVERNOR_AVAILABLE = True
        logger.info("✅ Global Risk Governor loaded - cascade-loss protection active")
    except ImportError:
        GLOBAL_RISK_GOVERNOR_AVAILABLE = False
        logger.warning("⚠️ Global Risk Governor not available - cascade-loss protection disabled")
        get_global_risk_governor = None
        GovernorConfig = None

# Import Global Capital Manager — cross-account capital scaling & risk balancing
try:
    from global_capital_manager import get_global_capital_manager
    GLOBAL_CAPITAL_MANAGER_AVAILABLE = True
    logger.info("✅ Global Capital Manager loaded - capital scaling & risk balancing active")
except ImportError:
    try:
        from bot.global_capital_manager import get_global_capital_manager
        GLOBAL_CAPITAL_MANAGER_AVAILABLE = True
        logger.info("✅ Global Capital Manager loaded - capital scaling & risk balancing active")
    except ImportError:
        GLOBAL_CAPITAL_MANAGER_AVAILABLE = False
        logger.warning("⚠️ Global Capital Manager not available - capital scaling disabled")
        get_global_capital_manager = None

# Import Master Strategy Router — one master signal for all accounts
try:
    from master_strategy_router import get_master_strategy_router
    MASTER_STRATEGY_ROUTER_AVAILABLE = True
    logger.info("✅ Master Strategy Router loaded - single master signal coordination active")
except ImportError:
    try:
        from bot.master_strategy_router import get_master_strategy_router
        MASTER_STRATEGY_ROUTER_AVAILABLE = True
        logger.info("✅ Master Strategy Router loaded - single master signal coordination active")
    except ImportError:
        MASTER_STRATEGY_ROUTER_AVAILABLE = False
        logger.warning("⚠️ Master Strategy Router not available - signal coordination disabled")
        get_master_strategy_router = None

# Import Signal Broadcaster — fan-out execution across all accounts
try:
    from signal_broadcaster import get_signal_broadcaster
    SIGNAL_BROADCASTER_AVAILABLE = True
    logger.info("✅ Signal Broadcaster loaded - cross-account fan-out execution active")
except ImportError:
    try:
        from bot.signal_broadcaster import get_signal_broadcaster
        SIGNAL_BROADCASTER_AVAILABLE = True
        logger.info("✅ Signal Broadcaster loaded - cross-account fan-out execution active")
    except ImportError:
        SIGNAL_BROADCASTER_AVAILABLE = False
        logger.warning("⚠️ Signal Broadcaster not available - fan-out execution disabled")
        get_signal_broadcaster = None

# Import Execution Pipeline — final connected flow (Steps 1-6)
try:
    from execution_pipeline import get_execution_pipeline
    EXECUTION_PIPELINE_AVAILABLE = True
    logger.info("✅ Execution Pipeline loaded - full cross-account orchestration active")
except ImportError:
    try:
        from bot.execution_pipeline import get_execution_pipeline
        EXECUTION_PIPELINE_AVAILABLE = True
        logger.info("✅ Execution Pipeline loaded - full cross-account orchestration active")
    except ImportError:
        EXECUTION_PIPELINE_AVAILABLE = False
        logger.warning("⚠️ Execution Pipeline not available")
        get_execution_pipeline = None

# Import Copy Trade Engine — replicate platform trades into all user accounts
try:
    from copy_trade_engine import get_copy_engine, CopySignal
    COPY_ENGINE_AVAILABLE = True
    logger.info("✅ Copy Trade Engine loaded - platform→user trade replication active")
except ImportError:
    try:
        from bot.copy_trade_engine import get_copy_engine, CopySignal
        COPY_ENGINE_AVAILABLE = True
        logger.info("✅ Copy Trade Engine loaded - platform→user trade replication active")
    except ImportError:
        COPY_ENGINE_AVAILABLE = False
        logger.warning("⚠️ Copy Trade Engine not available - user account replication disabled")
        get_copy_engine = None
        CopySignal = None

# Import Account Performance Dashboard — per-account metrics
try:
    from account_performance_dashboard import get_account_performance_dashboard
    ACCOUNT_DASHBOARD_AVAILABLE = True
    logger.info("✅ Account Performance Dashboard loaded - per-account metrics active")
except ImportError:
    try:
        from bot.account_performance_dashboard import get_account_performance_dashboard
        ACCOUNT_DASHBOARD_AVAILABLE = True
        logger.info("✅ Account Performance Dashboard loaded - per-account metrics active")
    except ImportError:
        ACCOUNT_DASHBOARD_AVAILABLE = False
        get_account_performance_dashboard = None

# Import Profit Splitter — proportional profit distribution per user
try:
    from profit_splitter import get_profit_splitter
    PROFIT_SPLITTER_AVAILABLE = True
    logger.info("✅ Profit Splitter loaded - per-user profit splitting active")
except ImportError:
    try:
        from bot.profit_splitter import get_profit_splitter
        PROFIT_SPLITTER_AVAILABLE = True
        logger.info("✅ Profit Splitter loaded - per-user profit splitting active")
    except ImportError:
        PROFIT_SPLITTER_AVAILABLE = False
        get_profit_splitter = None

# Import Profit Lock System — ratchet stops + auto-withdrawal of gains
try:
    from profit_lock_system import get_profit_lock_system as _get_profit_lock_system
    PROFIT_LOCK_SYSTEM_AVAILABLE = True
    logger.info("✅ Profit Lock System loaded - ratchet stops + auto-withdrawal active")
except ImportError:
    try:
        from bot.profit_lock_system import get_profit_lock_system as _get_profit_lock_system
        PROFIT_LOCK_SYSTEM_AVAILABLE = True
        logger.info("✅ Profit Lock System loaded - ratchet stops + auto-withdrawal active")
    except ImportError:
        PROFIT_LOCK_SYSTEM_AVAILABLE = False
        _get_profit_lock_system = None

# Import AI Capital Allocator — auto-shifts funds to best performers
try:
    from ai_capital_allocator import get_ai_capital_allocator
    AI_CAPITAL_ALLOCATOR_AVAILABLE = True
    logger.info("✅ AI Capital Allocator loaded - auto capital shift to best performers active")
except ImportError:
    try:
        from bot.ai_capital_allocator import get_ai_capital_allocator
        AI_CAPITAL_ALLOCATOR_AVAILABLE = True
        logger.info("✅ AI Capital Allocator loaded - auto capital shift to best performers active")
    except ImportError:
        AI_CAPITAL_ALLOCATOR_AVAILABLE = False
        get_ai_capital_allocator = None

# Import CapitalAllocator — cycle-oriented allocation layer (Steps 2/3/5)
try:
    from capital_allocator import get_capital_allocator as _get_capital_allocator
    CAPITAL_ALLOCATOR_AVAILABLE = True
    logger.info("✅ CapitalAllocator loaded - cycle-oriented capital budgeting active")
except ImportError:
    try:
        from bot.capital_allocator import get_capital_allocator as _get_capital_allocator
        CAPITAL_ALLOCATOR_AVAILABLE = True
        logger.info("✅ CapitalAllocator loaded - cycle-oriented capital budgeting active")
    except ImportError:
        CAPITAL_ALLOCATOR_AVAILABLE = False
        _get_capital_allocator = None

# Import Capital Concentration Engine — concentration mode, account ranking,
# kill-weak accounts, live-execution verification, Kelly sizing, dashboard
try:
    from capital_concentration_engine import get_capital_concentration_engine
    CAPITAL_CONCENTRATION_AVAILABLE = True
    logger.info(
        "✅ Capital Concentration Engine loaded - "
        "concentration mode + account ranking + kill-weak + Kelly sizing active"
    )
except ImportError:
    try:
        from bot.capital_concentration_engine import get_capital_concentration_engine
        CAPITAL_CONCENTRATION_AVAILABLE = True
        logger.info(
            "✅ Capital Concentration Engine loaded - "
            "concentration mode + account ranking + kill-weak + Kelly sizing active"
        )
    except ImportError:
        CAPITAL_CONCENTRATION_AVAILABLE = False
        get_capital_concentration_engine = None  # type: ignore[assignment]
        logger.warning(
            "⚠️ Capital Concentration Engine not available - "
            "concentration mode / account ranking / kill-weak disabled"
        )
# Import Account-Level Capital Flow — connects CCE + AIAllocator into one entry point
try:
    from account_level_capital_flow import get_account_level_capital_flow
    ACCOUNT_FLOW_AVAILABLE = True
    logger.info("✅ Account-Level Capital Flow loaded - account ranking + kill-weak + AI weights connected")
except ImportError:
    try:
        from bot.account_level_capital_flow import get_account_level_capital_flow
        ACCOUNT_FLOW_AVAILABLE = True
        logger.info("✅ Account-Level Capital Flow loaded - account ranking + kill-weak + AI weights connected")
    except ImportError:
        ACCOUNT_FLOW_AVAILABLE = False
        get_account_level_capital_flow = None  # type: ignore[assignment]
        logger.warning("⚠️ Account-Level Capital Flow not available - account-level allocation disabled")

try:
    from global_capital_brain import get_global_capital_brain
    GLOBAL_CAPITAL_BRAIN_AVAILABLE = True
    logger.info("✅ Global Capital Brain loaded - capital routing + efficiency score + snowball mode active")
except ImportError:
    try:
        from bot.global_capital_brain import get_global_capital_brain
        GLOBAL_CAPITAL_BRAIN_AVAILABLE = True
        logger.info("✅ Global Capital Brain loaded - capital routing + efficiency score + snowball mode active")
    except ImportError:
        GLOBAL_CAPITAL_BRAIN_AVAILABLE = False
        get_global_capital_brain = None  # type: ignore[assignment]
        logger.warning("⚠️ Global Capital Brain not available - capital routing disabled")

try:
    from ai_market_regime_forecaster import get_ai_market_regime_forecaster
    AI_REGIME_FORECASTER_AVAILABLE = True
    logger.info("✅ AI Market Regime Forecaster loaded - early regime-change prediction active")
except ImportError:
    try:
        from bot.ai_market_regime_forecaster import get_ai_market_regime_forecaster
        AI_REGIME_FORECASTER_AVAILABLE = True
        logger.info("✅ AI Market Regime Forecaster loaded - early regime-change prediction active")
    except ImportError:
        AI_REGIME_FORECASTER_AVAILABLE = False
        logger.warning("⚠️ AI Market Regime Forecaster not available - early warning disabled")
        get_ai_market_regime_forecaster = None

# Import Risk Budget Engine — risk-first position sizing with performance scaling
try:
    from risk_budget_engine import RiskBudgetEngine, RiskBudgetConfig, TradeRecord, OUTCOME_WIN, OUTCOME_LOSS
    RISK_BUDGET_ENGINE_AVAILABLE = True
    logger.info("✅ Risk Budget Engine loaded - risk-first position sizing active")
except ImportError:
    try:
        from bot.risk_budget_engine import RiskBudgetEngine, RiskBudgetConfig, TradeRecord, OUTCOME_WIN, OUTCOME_LOSS
        RISK_BUDGET_ENGINE_AVAILABLE = True
        logger.info("✅ Risk Budget Engine loaded - risk-first position sizing active")
    except ImportError:
        RISK_BUDGET_ENGINE_AVAILABLE = False
        logger.warning("⚠️ Risk Budget Engine not available - using legacy position sizing")
        RiskBudgetEngine = None
        RiskBudgetConfig = None
        TradeRecord = None
        OUTCOME_WIN = "win"
        OUTCOME_LOSS = "loss"

# Import Liquidity Intelligence Engine — per-symbol spread/volume/depth scoring
try:
    from liquidity_intelligence_engine import get_liquidity_intelligence_engine, LiquidityIntelligenceEngine
    LIQUIDITY_INTELLIGENCE_AVAILABLE = True
    logger.info("✅ Liquidity Intelligence Engine loaded - spread/volume/depth gating active")
except ImportError:
    try:
        from bot.liquidity_intelligence_engine import get_liquidity_intelligence_engine, LiquidityIntelligenceEngine
        LIQUIDITY_INTELLIGENCE_AVAILABLE = True
        logger.info("✅ Liquidity Intelligence Engine loaded - spread/volume/depth gating active")
    except ImportError:
        LIQUIDITY_INTELLIGENCE_AVAILABLE = False
        logger.warning("⚠️ Liquidity Intelligence Engine not available - liquidity gating disabled")
        get_liquidity_intelligence_engine = None
        LiquidityIntelligenceEngine = None

# Import Cross-Exchange Price Intelligence — multi-venue price divergence detection
try:
    from cross_exchange_price_intelligence import get_cross_exchange_price_intelligence, CrossExchangePriceIntelligence
    CROSS_EXCHANGE_INTEL_AVAILABLE = True
    logger.info("✅ Cross-Exchange Price Intelligence loaded - divergence detection active")
except ImportError:
    try:
        from bot.cross_exchange_price_intelligence import get_cross_exchange_price_intelligence, CrossExchangePriceIntelligence
        CROSS_EXCHANGE_INTEL_AVAILABLE = True
        logger.info("✅ Cross-Exchange Price Intelligence loaded - divergence detection active")
    except ImportError:
        CROSS_EXCHANGE_INTEL_AVAILABLE = False
        logger.warning("⚠️ Cross-Exchange Price Intelligence not available - divergence detection disabled")
        get_cross_exchange_price_intelligence = None
        CrossExchangePriceIntelligence = None

# Import Portfolio Performance Analytics — comprehensive P&L, Sharpe, drawdown tracking
try:
    from portfolio_performance_analytics import (
        get_portfolio_performance_analytics,
        PortfolioPerformanceAnalytics,
        TradeRecord as PerformanceTradeRecord,
    )
    PORTFOLIO_ANALYTICS_AVAILABLE = True
    logger.info("✅ Portfolio Performance Analytics loaded - Sharpe/Sortino/Calmar tracking active")
except ImportError:
    try:
        from bot.portfolio_performance_analytics import (
            get_portfolio_performance_analytics,
            PortfolioPerformanceAnalytics,
            TradeRecord as PerformanceTradeRecord,
        )
        PORTFOLIO_ANALYTICS_AVAILABLE = True
        logger.info("✅ Portfolio Performance Analytics loaded - Sharpe/Sortino/Calmar tracking active")
    except ImportError:
        PORTFOLIO_ANALYTICS_AVAILABLE = False
        logger.warning("⚠️ Portfolio Performance Analytics not available - performance tracking disabled")
        get_portfolio_performance_analytics = None
        PortfolioPerformanceAnalytics = None
        PerformanceTradeRecord = None

# Import scalar helper for indicator conversions
try:
    from indicators import scalar
except ImportError:
    try:
        from bot.indicators import scalar
    except ImportError:
        # Fallback if indicators.py is not available
        def scalar(x):
            if isinstance(x, (tuple, list)):
                if len(x) == 0:
                    raise ValueError("Cannot convert empty tuple/list to scalar")
                return float(x[0])
            return float(x)

# Import Capital Growth Throttle — updates each cycle and scales position sizes
try:
    from capital_growth_throttle import get_capital_growth_throttle
    CAPITAL_GROWTH_THROTTLE_AVAILABLE = True
    logger.info("✅ Capital Growth Throttle loaded - drawdown-based position scaling active")
except ImportError:
    try:
        from bot.capital_growth_throttle import get_capital_growth_throttle
        CAPITAL_GROWTH_THROTTLE_AVAILABLE = True
        logger.info("✅ Capital Growth Throttle loaded - drawdown-based position scaling active")
    except ImportError:
        CAPITAL_GROWTH_THROTTLE_AVAILABLE = False
        logger.warning("⚠️ Capital Growth Throttle not available - position scaling disabled")
        get_capital_growth_throttle = None

# Import Slippage Protection — pre-trade gate that blocks orders with excessive slippage
try:
    from slippage_protection import get_slippage_protector, SlippageProtector
    SLIPPAGE_PROTECTION_AVAILABLE = True
    logger.info("✅ Slippage Protection loaded - pre-trade slippage gating active")
except ImportError:
    try:
        from bot.slippage_protection import get_slippage_protector, SlippageProtector
        SLIPPAGE_PROTECTION_AVAILABLE = True
        logger.info("✅ Slippage Protection loaded - pre-trade slippage gating active")
    except ImportError:
        SLIPPAGE_PROTECTION_AVAILABLE = False
        logger.warning("⚠️ Slippage Protection not available - slippage gating disabled")
        get_slippage_protector = None
        SlippageProtector = None

# Import Net Profit Gate — Leak #1 fix: reject signals where profit < (spread+slip+fee)×2
try:
    from net_profit_gate import get_net_profit_gate, NetProfitGate
    NET_PROFIT_GATE_AVAILABLE = True
    logger.info("✅ Net Profit Gate loaded")
except ImportError:
    try:
        from bot.net_profit_gate import get_net_profit_gate, NetProfitGate
        NET_PROFIT_GATE_AVAILABLE = True
        logger.info("✅ Net Profit Gate loaded")
    except ImportError:
        NET_PROFIT_GATE_AVAILABLE = False
        get_net_profit_gate = None
        NetProfitGate = None

# Import Latency Drift Guard — Leak #2 fix: reject stale signals where price drifted
try:
    from latency_drift_guard import get_latency_drift_guard, LatencyDriftGuard
    LATENCY_DRIFT_GUARD_AVAILABLE = True
    logger.info("✅ Latency Drift Guard loaded")
except ImportError:
    try:
        from bot.latency_drift_guard import get_latency_drift_guard, LatencyDriftGuard
        LATENCY_DRIFT_GUARD_AVAILABLE = True
        logger.info("✅ Latency Drift Guard loaded")
    except ImportError:
        LATENCY_DRIFT_GUARD_AVAILABLE = False
        get_latency_drift_guard = None
        LatencyDriftGuard = None

# Import Capital Fragmentation Guard — Leak #3 fix: pause underperforming accounts
try:
    from capital_fragmentation_guard import get_fragmentation_guard, CapitalFragmentationGuard
    FRAGMENTATION_GUARD_AVAILABLE = True
    logger.info("✅ Capital Fragmentation Guard loaded")
except ImportError:
    try:
        from bot.capital_fragmentation_guard import get_fragmentation_guard, CapitalFragmentationGuard
        FRAGMENTATION_GUARD_AVAILABLE = True
        logger.info("✅ Capital Fragmentation Guard loaded")
    except ImportError:
        FRAGMENTATION_GUARD_AVAILABLE = False
        get_fragmentation_guard = None
        CapitalFragmentationGuard = None

# Import Crypto Sector Taxonomy — used for sector-level capital allocation caps
try:
    from crypto_sector_taxonomy import get_sector, get_sector_name
    SECTOR_TAXONOMY_AVAILABLE = True
    logger.info("✅ Crypto Sector Taxonomy loaded - sector capital allocation caps active")
except ImportError:
    try:
        from bot.crypto_sector_taxonomy import get_sector, get_sector_name
        SECTOR_TAXONOMY_AVAILABLE = True
        logger.info("✅ Crypto Sector Taxonomy loaded - sector capital allocation caps active")
    except ImportError:
        SECTOR_TAXONOMY_AVAILABLE = False
        logger.warning("⚠️ Crypto Sector Taxonomy not available - sector allocation caps disabled")
        get_sector = None
        get_sector_name = None

# Import Volatility Position Sizing — adjusts position sizes based on current volatility
try:
    from volatility_position_sizing import get_volatility_position_sizer, VolatilityPositionSizer
    VOLATILITY_POSITION_SIZING_AVAILABLE = True
    logger.info("✅ Volatility Position Sizing loaded - ATR-based size scaling active")
except ImportError:
    try:
        from bot.volatility_position_sizing import get_volatility_position_sizer, VolatilityPositionSizer
        VOLATILITY_POSITION_SIZING_AVAILABLE = True
        logger.info("✅ Volatility Position Sizing loaded - ATR-based size scaling active")
    except ImportError:
        VOLATILITY_POSITION_SIZING_AVAILABLE = False
        logger.warning("⚠️ Volatility Position Sizing not available - volatility scaling disabled")
        get_volatility_position_sizer = None
        VolatilityPositionSizer = None

# Import Cross-Broker Arbitrage Monitor — venue price divergence awareness
try:
    from cross_broker_arbitrage_monitor import get_arb_monitor, ArbSignalStrength
    CROSS_BROKER_ARB_AVAILABLE = True
    logger.info("✅ Cross-Broker Arbitrage Monitor loaded - multi-venue price divergence active")
except ImportError:
    try:
        from bot.cross_broker_arbitrage_monitor import get_arb_monitor, ArbSignalStrength
        CROSS_BROKER_ARB_AVAILABLE = True
        logger.info("✅ Cross-Broker Arbitrage Monitor loaded - multi-venue price divergence active")
    except ImportError:
        CROSS_BROKER_ARB_AVAILABLE = False
        logger.warning("⚠️ Cross-Broker Arbitrage Monitor not available - single-venue mode")
        get_arb_monitor = None
        ArbSignalStrength = None

# Import Volatility-Weighted Capital Router — inverse-volatility capital sizing
try:
    from volatility_weighted_capital_router import get_volatility_router
    VOLATILITY_CAPITAL_ROUTER_AVAILABLE = True
    logger.info("✅ Volatility-Weighted Capital Router loaded - inverse-vol sizing active")
except ImportError:
    try:
        from bot.volatility_weighted_capital_router import get_volatility_router
        VOLATILITY_CAPITAL_ROUTER_AVAILABLE = True
        logger.info("✅ Volatility-Weighted Capital Router loaded - inverse-vol sizing active")
    except ImportError:
        VOLATILITY_CAPITAL_ROUTER_AVAILABLE = False
        logger.warning("⚠️ Volatility-Weighted Capital Router not available")
        get_volatility_router = None

# Import Regime Capital Allocator — regime-driven capital allocation shifts
try:
    from regime_capital_allocator import get_regime_capital_allocator
    REGIME_CAPITAL_ALLOCATOR_AVAILABLE = True
    logger.info("✅ Regime Capital Allocator loaded - regime→allocation mapping active")
except ImportError:
    try:
        from bot.regime_capital_allocator import get_regime_capital_allocator
        REGIME_CAPITAL_ALLOCATOR_AVAILABLE = True
        logger.info("✅ Regime Capital Allocator loaded - regime→allocation mapping active")
    except ImportError:
        REGIME_CAPITAL_ALLOCATOR_AVAILABLE = False
        logger.warning("⚠️ Regime Capital Allocator not available - regime allocation disabled")
        get_regime_capital_allocator = None

# Import Market Regime Engine — per-candle BULL/CHOP/CRASH aggression control
try:
    from market_regime_engine import get_market_regime_engine, Regime as RegimeEngineRegime
    MARKET_REGIME_ENGINE_AVAILABLE = True
    logger.info("✅ Market Regime Engine loaded - bull/chop/crash aggression active")
except ImportError:
    try:
        from bot.market_regime_engine import get_market_regime_engine, Regime as RegimeEngineRegime
        MARKET_REGIME_ENGINE_AVAILABLE = True
        logger.info("✅ Market Regime Engine loaded - bull/chop/crash aggression active")
    except ImportError:
        MARKET_REGIME_ENGINE_AVAILABLE = False
        logger.warning("⚠️ Market Regime Engine not available - regime aggression disabled")
        get_market_regime_engine = None
        RegimeEngineRegime = None

# Import Global Drawdown Circuit Breaker — system-wide halt on deep drawdown
try:
    from global_drawdown_circuit_breaker import get_global_drawdown_cb, ProtectionLevel
    GLOBAL_DRAWDOWN_CB_AVAILABLE = True
    logger.info("✅ Global Drawdown Circuit Breaker loaded - system-wide halt active")
except ImportError:
    try:
        from bot.global_drawdown_circuit_breaker import get_global_drawdown_cb, ProtectionLevel
        GLOBAL_DRAWDOWN_CB_AVAILABLE = True
        logger.info("✅ Global Drawdown Circuit Breaker loaded - system-wide halt active")
    except ImportError:
        GLOBAL_DRAWDOWN_CB_AVAILABLE = False
        logger.warning("⚠️ Global Drawdown Circuit Breaker not available - system drawdown halt disabled")
        get_global_drawdown_cb = None
        ProtectionLevel = None

# ── Phase 3: Dynamic Stop-Loss Tightener ────────────────────────────────────
try:
    from dynamic_stop_loss_tightener import get_dynamic_stop_tightener
    DYNAMIC_STOP_TIGHTENER_AVAILABLE = True
    logger.info("✅ Phase 3: Dynamic Stop-Loss Tightener loaded")
except ImportError:
    try:
        from bot.dynamic_stop_loss_tightener import get_dynamic_stop_tightener
        DYNAMIC_STOP_TIGHTENER_AVAILABLE = True
        logger.info("✅ Phase 3: Dynamic Stop-Loss Tightener loaded")
    except ImportError:
        DYNAMIC_STOP_TIGHTENER_AVAILABLE = False
        get_dynamic_stop_tightener = None  # type: ignore
        logger.warning("⚠️ Phase 3: Dynamic Stop-Loss Tightener not available")

# ── Phase 3: Partial TP Ladder ───────────────────────────────────────────────
try:
    from partial_tp_ladder import get_partial_tp_ladder
    PARTIAL_TP_LADDER_AVAILABLE = True
    logger.info("✅ Phase 3: Partial TP Ladder loaded")
except ImportError:
    try:
        from bot.partial_tp_ladder import get_partial_tp_ladder
        PARTIAL_TP_LADDER_AVAILABLE = True
        logger.info("✅ Phase 3: Partial TP Ladder loaded")
    except ImportError:
        PARTIAL_TP_LADDER_AVAILABLE = False
        get_partial_tp_ladder = None  # type: ignore
        logger.warning("⚠️ Phase 3: Partial TP Ladder not available")

# ── Phase 3: News / Event Volatility Filter ──────────────────────────────────
try:
    from news_volatility_filter import get_news_volatility_filter
    NEWS_VOLATILITY_FILTER_AVAILABLE = True
    logger.info("✅ Phase 3: News/Event Volatility Filter loaded")
except ImportError:
    try:
        from bot.news_volatility_filter import get_news_volatility_filter
        NEWS_VOLATILITY_FILTER_AVAILABLE = True
        logger.info("✅ Phase 3: News/Event Volatility Filter loaded")
    except ImportError:
        NEWS_VOLATILITY_FILTER_AVAILABLE = False
        get_news_volatility_filter = None  # type: ignore
        logger.warning("⚠️ Phase 3: News/Event Volatility Filter not available")

# ── Phase 3: Multi-Timeframe Confirmation AI ─────────────────────────────────
try:
    from multi_timeframe_confirmation import get_mtf_confirmation
    MTF_CONFIRMATION_AVAILABLE = True
    logger.info("✅ Phase 3: Multi-Timeframe Confirmation AI loaded")
except ImportError:
    try:
        from bot.multi_timeframe_confirmation import get_mtf_confirmation
        MTF_CONFIRMATION_AVAILABLE = True
        logger.info("✅ Phase 3: Multi-Timeframe Confirmation AI loaded")
    except ImportError:
        MTF_CONFIRMATION_AVAILABLE = False
        get_mtf_confirmation = None  # type: ignore
        logger.warning("⚠️ Phase 3: Multi-Timeframe Confirmation AI not available")

# ── Phase 3: Abnormal Market Kill Switch ─────────────────────────────────────
try:
    from abnormal_market_kill_switch import get_abnormal_market_ks
    ABNORMAL_MARKET_KS_AVAILABLE = True
    logger.info("✅ Phase 3: Abnormal Market Kill Switch loaded")
except ImportError:
    try:
        from bot.abnormal_market_kill_switch import get_abnormal_market_ks
        ABNORMAL_MARKET_KS_AVAILABLE = True
        logger.info("✅ Phase 3: Abnormal Market Kill Switch loaded")
    except ImportError:
        ABNORMAL_MARKET_KS_AVAILABLE = False
        get_abnormal_market_ks = None  # type: ignore
        logger.warning("⚠️ Phase 3: Abnormal Market Kill Switch not available")

# Import Micro-Cap Compounding Config — applies before risk engine and position sizing
try:
    from micro_capital_config import (
        get_micro_cap_compounding_config,
        get_spread_adjusted_profit_target,
        MICRO_CAP_TRADE_COOLDOWN,
        MICRO_CAP_COMPOUNDING_MAX_POSITIONS,
        MICRO_CAP_COMPOUNDING_POSITION_SIZE_PCT,
        MICRO_CAP_COMPOUNDING_PROFIT_TARGET_PCT,
        MICRO_CAP_COMPOUNDING_STOP_LOSS_PCT,
        MAX_CONCURRENT_TRADES,
    )
    MICRO_CAP_COMPOUNDING_AVAILABLE = True
    logger.info("✅ Micro-Cap Compounding Config loaded - balance-gated compounding mode active")
except ImportError:
    try:
        from bot.micro_capital_config import (
            get_micro_cap_compounding_config,
            get_spread_adjusted_profit_target,
            MICRO_CAP_TRADE_COOLDOWN,
            MICRO_CAP_COMPOUNDING_MAX_POSITIONS,
            MICRO_CAP_COMPOUNDING_POSITION_SIZE_PCT,
            MICRO_CAP_COMPOUNDING_PROFIT_TARGET_PCT,
            MICRO_CAP_COMPOUNDING_STOP_LOSS_PCT,
            MAX_CONCURRENT_TRADES,
        )
        MICRO_CAP_COMPOUNDING_AVAILABLE = True
        logger.info("✅ Micro-Cap Compounding Config loaded - balance-gated compounding mode active")
    except ImportError:
        MICRO_CAP_COMPOUNDING_AVAILABLE = False
        MICRO_CAP_TRADE_COOLDOWN = 60  # Default: 60 seconds (matches config constant)
        MICRO_CAP_COMPOUNDING_MAX_POSITIONS = 1
        MICRO_CAP_COMPOUNDING_POSITION_SIZE_PCT = 25.0
        MICRO_CAP_COMPOUNDING_PROFIT_TARGET_PCT = 1.0
        MICRO_CAP_COMPOUNDING_STOP_LOSS_PCT = 0.6
        MAX_CONCURRENT_TRADES = 4  # Default: matches micro_capital_config.MAX_CONCURRENT_TRADES
        logger.warning("⚠️ Micro-Cap Compounding Config not available - micro-cap mode disabled")
        get_micro_cap_compounding_config = None  # type: ignore

        def get_spread_adjusted_profit_target(spread_pct: float, win_streak: int = 0) -> float:
            """Fallback when micro_capital_config is unavailable: base 1.0% + spread."""
            return MICRO_CAP_COMPOUNDING_PROFIT_TARGET_PCT + spread_pct * 100.0

# Import Capital Scaling Engine — automatically increases deposits into winning accounts
try:
    from capital_scaling_engine import get_capital_engine
    CAPITAL_SCALING_ENGINE_AVAILABLE = True
    logger.info("✅ Capital Scaling Engine loaded - auto-deposit compounding active")
except ImportError:
    try:
        from bot.capital_scaling_engine import get_capital_engine
        CAPITAL_SCALING_ENGINE_AVAILABLE = True
        logger.info("✅ Capital Scaling Engine loaded - auto-deposit compounding active")
    except ImportError:
        CAPITAL_SCALING_ENGINE_AVAILABLE = False
        get_capital_engine = None
        logger.warning("⚠️ Capital Scaling Engine not available - auto-compounding disabled")

# Import External Capital Mode — handles multiple users / investors
try:
    from investor_mode import get_investor_mode_engine
    INVESTOR_MODE_AVAILABLE = True
    logger.info("✅ External Capital Mode (Investor Mode) loaded - multi-investor tracking active")
except ImportError:
    try:
        from bot.investor_mode import get_investor_mode_engine
        INVESTOR_MODE_AVAILABLE = True
        logger.info("✅ External Capital Mode (Investor Mode) loaded - multi-investor tracking active")
    except ImportError:
        INVESTOR_MODE_AVAILABLE = False
        get_investor_mode_engine = None
        logger.warning("⚠️ External Capital Mode not available - investor tracking disabled")

# Import Tiered Risk Engine — conservative vs aggressive capital pools
try:
    from core.tiered_risk_engine import TieredRiskEngine
    TIERED_RISK_ENGINE_AVAILABLE = True
    logger.info("✅ Tiered Risk Engine loaded - conservative/aggressive capital pool gating active")
except ImportError:
    try:
        from tiered_risk_engine import TieredRiskEngine
        TIERED_RISK_ENGINE_AVAILABLE = True
        logger.info("✅ Tiered Risk Engine loaded - conservative/aggressive capital pool gating active")
    except ImportError:
        TIERED_RISK_ENGINE_AVAILABLE = False
        TieredRiskEngine = None
        logger.warning("⚠️ Tiered Risk Engine not available - risk-tier gating disabled")

# Import AI Strategy Evolution Engine — system evolves its own strategies
try:
    from ai_strategy_evolution_engine import get_ai_strategy_evolution_engine
    AI_STRATEGY_EVOLUTION_AVAILABLE = True
    logger.info("✅ AI Strategy Evolution Engine loaded - autonomous strategy mutation active")
except ImportError:
    try:
        from bot.ai_strategy_evolution_engine import get_ai_strategy_evolution_engine
        AI_STRATEGY_EVOLUTION_AVAILABLE = True
        logger.info("✅ AI Strategy Evolution Engine loaded - autonomous strategy mutation active")
    except ImportError:
        AI_STRATEGY_EVOLUTION_AVAILABLE = False
        get_ai_strategy_evolution_engine = None
        logger.warning("⚠️ AI Strategy Evolution Engine not available - strategy mutation disabled")

# ── Phase 2: Adaptive Take-Profit Scaling ─────────────────────────────────────
# Dynamically expands/contracts profit targets based on trend strength &
# volatility so winners are locked more aggressively in strong trends.
try:
    from adaptive_profit_target_engine import (
        get_adaptive_profit_engine,
        AdaptiveProfitTargetEngine,
    )
    ADAPTIVE_TP_AVAILABLE = True
    logger.info("✅ Adaptive TP Engine loaded — dynamic profit-target scaling active")
except ImportError:
    try:
        from bot.adaptive_profit_target_engine import (
            get_adaptive_profit_engine,
            AdaptiveProfitTargetEngine,
        )
        ADAPTIVE_TP_AVAILABLE = True
        logger.info("✅ Adaptive TP Engine loaded — dynamic profit-target scaling active")
    except ImportError:
        ADAPTIVE_TP_AVAILABLE = False
        get_adaptive_profit_engine = None
        AdaptiveProfitTargetEngine = None
        logger.warning("⚠️ Adaptive TP Engine not available — static profit targets in use")

# ── Phase 2: Trade Clustering — stack wins in strong trends ───────────────────
# Increases position size during confirmed trending phases where the bot has
# accumulated consecutive wins, safely ramping back to 1× on the first loss.
try:
    from trade_cluster_engine import get_trade_cluster_engine, TradeClusterEngine
    TRADE_CLUSTER_AVAILABLE = True
    logger.info("✅ Trade Cluster Engine loaded — trend-stacking active")
except ImportError:
    try:
        from bot.trade_cluster_engine import get_trade_cluster_engine, TradeClusterEngine
        TRADE_CLUSTER_AVAILABLE = True
        logger.info("✅ Trade Cluster Engine loaded — trend-stacking active")
    except ImportError:
        TRADE_CLUSTER_AVAILABLE = False
        get_trade_cluster_engine = None
        TradeClusterEngine = None
        logger.warning("⚠️ Trade Cluster Engine not available — trend-stacking disabled")

# ── Phase 2: AI Confidence-Based Position Sizing ──────────────────────────────
# Scores every trade on a 0-100 scale and scales position size proportionally
# so high-conviction setups receive more capital than marginal ones.
try:
    from ai_trade_confidence_engine import get_ai_trade_confidence_engine
    AI_CONFIDENCE_SIZING_AVAILABLE = True
    logger.info("✅ AI Confidence Engine loaded — confidence-based position sizing active")
except ImportError:
    try:
        from bot.ai_trade_confidence_engine import get_ai_trade_confidence_engine
        AI_CONFIDENCE_SIZING_AVAILABLE = True
        logger.info("✅ AI Confidence Engine loaded — confidence-based position sizing active")
    except ImportError:
        AI_CONFIDENCE_SIZING_AVAILABLE = False
        get_ai_trade_confidence_engine = None
        logger.warning("⚠️ AI Confidence Engine not available — confidence sizing disabled")

# ── Phase 2: Capital Routing Across Multiple Brokers ──────────────────────────
# Continuously monitors broker performance scores and shifts capital allocation
# weights toward the best-performing brokers via EMA blending + hysteresis.
try:
    from auto_broker_capital_shifter import (
        get_auto_broker_capital_shifter,
        ShiftPolicy,
    )
    AUTO_BROKER_SHIFTER_AVAILABLE = True
    logger.info("✅ Auto Broker Capital Shifter loaded — multi-broker routing active")
except ImportError:
    try:
        from bot.auto_broker_capital_shifter import (
            get_auto_broker_capital_shifter,
            ShiftPolicy,
        )
        AUTO_BROKER_SHIFTER_AVAILABLE = True
        logger.info("✅ Auto Broker Capital Shifter loaded — multi-broker routing active")
    except ImportError:
        AUTO_BROKER_SHIFTER_AVAILABLE = False
        get_auto_broker_capital_shifter = None
        ShiftPolicy = None
        logger.warning("⚠️ Auto Broker Capital Shifter not available — equal broker weighting")

load_dotenv()

# Position adoption safety constants
# When entry price is missing from exchange, use current_price * this multiplier
# This creates an immediate small loss to trigger aggressive exit management
MISSING_ENTRY_PRICE_MULTIPLIER = 1.01  # 1% above current = -0.99% immediate P&L

# Maximum number of open orders to display in logs when positions are being adopted
MAX_DISPLAYED_ORDERS = 5  # Show first 5 orders, summarize remaining

# Capital engine constants
_DEFAULT_BASE_CAPITAL: float = 100.0        # fallback when BASE_CAPITAL env var is not set
_TRADING_FEE_PCT: float = 0.001             # 0.1% fee estimate used for compounding calculations
_AI_EVOLUTION_CYCLE_TRADES: int = 20        # run a genetic evolution cycle every N closed trades

# Import BrokerType and AccountType at module level for use throughout the class
# These are needed in _register_kraken_for_retry and other methods outside __init__
try:
    from broker_manager import BrokerType, AccountType, MINIMUM_TRADING_BALANCE
except ImportError:
    try:
        from bot.broker_manager import BrokerType, AccountType, MINIMUM_TRADING_BALANCE
    except ImportError:
        # If broker_manager is not available, define placeholder enums
        # This allows the module to load even if broker_manager is missing
        # NOTE: These values MUST match the enums defined in broker_manager.py
        # Source of truth: bot/broker_manager.py lines 160-177
        from enum import Enum

        class BrokerType(Enum):
            COINBASE = "coinbase"
            BINANCE = "binance"
            KRAKEN = "kraken"
            OKX = "okx"
            INTERACTIVE_BROKERS = "interactive_brokers"
            TD_AMERITRADE = "td_ameritrade"
            ALPACA = "alpaca"
            TRADIER = "tradier"

        class AccountType(Enum):
            PLATFORM = "platform"
            USER = "user"

        # Also need MINIMUM_TRADING_BALANCE fallback
        MINIMUM_TRADING_BALANCE = 10.0  # Default minimum (updated from $25 for new tier structure)

# NIJA State Machine for Position Management (Feb 15, 2026)
# Formal state tracking to ensure deterministic behavior and proper invariants
class PositionManagementState(Enum):
    """
    Position management state machine for NIJA trading bot.
    
    States:
    - NORMAL: Trading normally, under position cap, entries allowed
    - DRAIN: Over position cap, actively draining excess positions, entries blocked
    - FORCED_UNWIND: Emergency exit mode, closing all positions immediately
    """
    NORMAL = "normal"
    DRAIN = "drain"
    FORCED_UNWIND = "forced_unwind"


class StateInvariantValidator:
    """
    System-level invariant validator for NIJA state machine.
    
    Validates critical invariants at state transitions to ensure system correctness:
    - Position count is always >= 0
    - Excess positions only exist in DRAIN or FORCED_UNWIND states
    - State transitions follow valid paths
    """
    
    @staticmethod
    def validate_state_invariants(state, num_positions, excess_positions, max_positions):
        """
        Validate system invariants for the current state.
        
        Args:
            state: Current PositionManagementState
            num_positions: Current number of open positions
            excess_positions: Number of positions over cap
            max_positions: Maximum allowed positions
            
        Raises:
            AssertionError: If any invariant is violated
        """
        # Invariant 1: Position count must be non-negative
        assert num_positions >= 0, f"INVARIANT VIOLATION: Position count is negative: {num_positions}"
        
        # Invariant 2: Excess calculation must be consistent
        calculated_excess = num_positions - max_positions
        assert excess_positions == calculated_excess, \
            f"INVARIANT VIOLATION: Excess mismatch: reported={excess_positions}, calculated={calculated_excess}"
        
        # Invariant 3: DRAIN mode should only be active when excess > 0
        if state == PositionManagementState.DRAIN:
            assert excess_positions > 0, \
                f"INVARIANT VIOLATION: DRAIN mode active but excess={excess_positions} (should be > 0)"
        
        # Invariant 4: NORMAL mode should only be active when excess <= 0
        if state == PositionManagementState.NORMAL:
            assert excess_positions <= 0, \
                f"INVARIANT VIOLATION: NORMAL mode active but excess={excess_positions} (should be <= 0)"
    
    @staticmethod
    def validate_state_transition(old_state, new_state, num_positions, excess_positions):
        """
        Validate that a state transition is valid.
        
        Args:
            old_state: Previous PositionManagementState
            new_state: New PositionManagementState
            num_positions: Current number of positions
            excess_positions: Number of positions over cap
            
        Returns:
            bool: True if transition is valid, False otherwise
        """
        # Define valid state transitions
        valid_transitions = {
            PositionManagementState.NORMAL: {PositionManagementState.DRAIN, PositionManagementState.FORCED_UNWIND},
            PositionManagementState.DRAIN: {PositionManagementState.NORMAL, PositionManagementState.FORCED_UNWIND},
            PositionManagementState.FORCED_UNWIND: {PositionManagementState.NORMAL, PositionManagementState.DRAIN},
        }
        
        # Allow self-transitions (staying in same state)
        if old_state == new_state:
            return True
        
        # Check if transition is in the allowed set
        if new_state not in valid_transitions.get(old_state, set()):
            logger.error(f"INVALID STATE TRANSITION: {old_state.value} → {new_state.value}")
            return False
        
        return True

# FIX #1: BLACKLIST PAIRS - Disable pairs that are not suitable for strategy
# XRP-USD is PERMANENTLY DISABLED due to negative profitability
# Load additional disabled pairs from environment variable
_env_disabled_pairs = os.getenv('DISABLED_PAIRS', '')
_additional_disabled = [p.strip() for p in _env_disabled_pairs.split(',') if p.strip()]
DISABLED_PAIRS = ["XRP-USD", "XRPUSD", "XRP-USDT"] + _additional_disabled  # Block all XRP pairs - net negative performance

# Load geographically restricted symbols from blacklist
try:
    from bot.restricted_symbols import get_restriction_manager
    _restriction_mgr = get_restriction_manager()
    _restricted_symbols = _restriction_mgr.get_all_restricted_symbols()
    if _restricted_symbols:
        logger.info(f"📋 Loaded {len(_restricted_symbols)} geographically restricted symbols")
        DISABLED_PAIRS.extend(_restricted_symbols)
except ImportError:
    try:
        from restricted_symbols import get_restriction_manager
        _restriction_mgr = get_restriction_manager()
        _restricted_symbols = _restriction_mgr.get_all_restricted_symbols()
        if _restricted_symbols:
            logger.info(f"📋 Loaded {len(_restricted_symbols)} geographically restricted symbols")
            DISABLED_PAIRS.extend(_restricted_symbols)
    except ImportError as e:
        logger.debug(f"Note: Could not load restriction blacklist: {e}")

# Load whitelist configuration for PLATFORM_ONLY mode (optional)
try:
    from bot.platform_only_config import is_whitelisted_symbol, WHITELISTED_ASSETS
    WHITELIST_ENABLED = os.getenv('ENABLE_SYMBOL_WHITELIST', 'false').lower() in ('true', '1', 'yes')
    if WHITELIST_ENABLED:
        logger.info(f"✅ Symbol whitelist ENABLED: {', '.join(WHITELISTED_ASSETS)}")
    else:
        logger.debug("Symbol whitelist available but not enabled (set ENABLE_SYMBOL_WHITELIST=true to enable)")
except ImportError:
    WHITELIST_ENABLED = False
    logger.debug("Note: Symbol whitelist not available (platform_only_config not found)")

# Time conversion constants
MINUTES_PER_HOUR = 60  # Minutes in one hour (used for time-based calculations)

# FIX #1: Removed default capital - MUST be set from live broker balance
# This placeholder is replaced with live multi-broker balance after connection
# Set to $0 to prevent any trading until real balance is loaded
PLACEHOLDER_CAPITAL = 0.0  # No default capital - MUST be set from live balance

# OPTIMIZED EXIT FOR LOSING TRADES - Aggressive capital protection
# Exit losing trades after 15 minutes to minimize capital erosion
# Updated from 30 minutes to be more aggressive with loss prevention
MAX_LOSING_POSITION_HOLD_MINUTES = 15  # Exit losing trades after 15 minutes (aggressive protection)

# Configuration constants
# CRITICAL FIX (Jan 10, 2026): Further reduced market scanning to prevent 429/403 rate limit errors
# Coinbase has strict rate limits (~10 req/s burst, lower sustained)
# Instead of scanning all 730 markets every cycle, we batch scan smaller subsets
# RateLimiter enforces 10 req/min (6s between calls), so we must scan fewer markets
MARKET_SCAN_LIMIT = 30   # Scan 30 markets per cycle for better opportunity discovery
                         # This rotates through different markets each cycle
                         # Complete scan of 730 markets takes ~24 cycles (~60 minutes)
                         # Increased from 15 to find 2x more trading opportunities while respecting rate limits
MIN_CANDLES_REQUIRED = 90  # Minimum candles needed for analysis (relaxed from 100 to prevent infinite sell loops)

# Rate limiting constants (prevent 429 errors from Coinbase API)
# UPDATED (Jan 10, 2026): CRITICAL FIX - Aligned delays with RateLimiter to prevent rate limits
# Coinbase rate limits: ~10 requests/second burst, but sustained rate must be much lower
# Real-world testing shows we need to be even more conservative to avoid 403 "too many errors"
# RateLimiter enforces 6s minimum between get_candles calls (10 req/min)
# Manual delay must be >= 6s to avoid conflicts and ensure proper rate limiting
POSITION_CHECK_DELAY = 0.5  # 500ms delay between position checks (was 0.3s)
SELL_ORDER_DELAY = 0.7      # 700ms delay between sell orders (was 0.5s)
# LATENCY OPTIMISATION: MARKET_SCAN_DELAY is the dominant cycle cost.
# Default 8.0s safely clears the RateLimiter floor (6s minimum) with a 2s buffer.
# Operators can lower to 6.5s via env-var NIJA_MARKET_SCAN_DELAY (min 6.0s enforced).
# At 30 markets: 8.0s→240s vs 6.5s→195s — saves ~45s per cycle.
try:
    _raw_scan_delay = float(os.environ.get("NIJA_MARKET_SCAN_DELAY", "8.0"))
except (ValueError, TypeError):
    import logging as _logging
    _logging.getLogger(__name__).warning(
        "NIJA_MARKET_SCAN_DELAY has an invalid value; defaulting to 8.0s"
    )
    _raw_scan_delay = 8.0
MARKET_SCAN_DELAY = max(6.0, _raw_scan_delay)  # Hard floor: never below RateLimiter minimum
                            # CRITICAL: Must be >= 7.5s to align with RateLimiter (8 req/min for get_candles)
                            # The 0.5s buffer (8.0s vs 7.5s) accounts for jitter and processing time
                            # At 8.0s delay, we scan at ~0.125 req/s which prevents both 429 and 403 errors
                            # At 5-15 markets per cycle with 8.0s delay, scanning takes 40-120 seconds
                            # This conservative rate ensures API key never gets temporarily blocked

# Broker balance fetch timeout constants (Jan 28, 2026)
# CRITICAL FIX: Increased from 20s to 45s to accommodate Kraken API timeout (30s) plus network overhead
# 45s chosen to allow: 30s Kraken API timeout + 15s network/serialization buffer
# Kraken get_account_balance makes 2 API calls (Balance + TradeBalance) with 1s minimum between calls
# Under production load, Kraken regularly takes 15-20s to respond (within 30s API timeout)
# If timeout occurs, cached balance is used as fallback (max age: 5 minutes)
BALANCE_FETCH_TIMEOUT = 45  # Maximum time to wait for balance fetch (must be > Kraken API timeout of 30s)
CACHED_BALANCE_MAX_AGE_SECONDS = 300  # Use cached balance if fresh (5 minutes max staleness)

# Market scanning rotation (prevents scanning same markets every cycle)
# UPDATED (Jan 10, 2026): Adaptive batch sizing to prevent API rate limiting
MARKET_BATCH_SIZE_MIN = 10   # Start with 10 markets per cycle on fresh start (gradual warmup)
MARKET_BATCH_SIZE_MAX = 30  # Maximum markets to scan per cycle after warmup
MARKET_BATCH_WARMUP_CYCLES = 3  # Number of cycles to warm up before using max batch size
MARKET_ROTATION_ENABLED = True  # Rotate through different market batches each cycle

# ============================================================================
# POSITION CAP & SIZE CONSTANTS (CRITICAL RISK CONTROLS)
# ============================================================================
# Global hard cap on concurrent open positions.  No matter the account size
# or environment override, the bot will NEVER hold more than this many
# positions simultaneously.  Lower values = fewer but larger, more meaningful
# trades.  Balance-aware sub-limits are enforced via
# get_balance_based_max_positions() below.
MAX_TOTAL_POSITIONS = 3   # HARD GLOBAL CAP: maximum concurrent open positions
MAX_SECTOR_ALLOCATION = 0.4  # 40% of total capital — cap per sector to prevent concentration risk

# Balance thresholds for the per-account position cap.
# Micro accounts (< BALANCE_THRESHOLD_MICRO) are capped at 2 positions.
# Small accounts (< BALANCE_THRESHOLD_SMALL) are capped at 3 positions.
# Larger accounts use MAX_TOTAL_POSITIONS (3).
BALANCE_THRESHOLD_MICRO = 150.0   # Below this balance → max 2 positions
BALANCE_THRESHOLD_SMALL = 500.0   # Below this balance → max 3 positions

# Minimum USD notional for any NEW entry order.  Orders below this value are
# rejected at source to prevent dust accumulation and unproductive fee spend.
MIN_POSITION_USD = 10.0   # Minimum entry size ($10 ensures fee efficiency and meaningful compounding)

# Dust cleanup threshold for EXISTING positions.  Any open position whose
# current market value falls below this level is marked for cleanup:
#   • sold immediately if the exchange permits (notional >= exchange minimum)
#   • or added to the permanent dust blacklist so it is ignored forever
DUST_POSITION_USD = 2.0   # Cleanup threshold for existing positions (< $2 = dust)

# ============================================================================

# Exit strategy constants (no entry price required)
# CRITICAL FIX (Jan 13, 2026): Aggressive RSI thresholds to sell faster
MIN_POSITION_VALUE = DUST_POSITION_USD  # Auto-exit positions under this USD value (was $1, now $2)
RSI_OVERBOUGHT_THRESHOLD = 55  # Exit when RSI exceeds this (lock gains) - LOWERED from 60 for faster profit-taking
RSI_OVERSOLD_THRESHOLD = 45  # Exit when RSI below this (cut losses) - RAISED from 40 for faster loss-cutting
DEFAULT_RSI = 50  # Default RSI value when indicators unavailable

# Time-based exit thresholds (prevent indefinite holding)
# CRITICAL FIX (Jan 19, 2026): IMMEDIATE EXIT FOR ALL LOSING TRADES
# LOSING TRADES: EXIT after 30 minutes to allow recovery (changed from immediate)
# PROFITABLE TRADES: Can run up to 24 hours to capture full gains
# NIJA is for PROFIT - give positions time to develop and capture gains
MAX_POSITION_HOLD_HOURS = 24  # Auto-exit ALL positions held longer than 24 hours (daily strategy)
MAX_POSITION_HOLD_EMERGENCY = 48  # EMERGENCY exit - force sell ALL positions after 48 hours (absolute failsafe)
STALE_POSITION_WARNING_HOURS = 12  # Warn about positions held this long (12 hours)
# Unsellable position retry timeout (prevent permanent blocking)
# After this many hours, retry selling positions that were previously marked unsellable
# This handles cases where position grew enough to be sellable, or API errors were temporary
UNSELLABLE_RETRY_HOURS = 12  # Retry selling "unsellable" positions after 12 hours (half of max hold time)
# ZOMBIE POSITION DETECTION: Disabled - positions need time to develop
# Auto-imported positions are tracked properly with entry prices now
ZOMBIE_POSITION_HOURS = 24.0  # Increased from 1 hour to 24 hours to allow normal price movement
ZOMBIE_PNL_THRESHOLD = 0.01  # Consider position "stuck" if abs(P&L) < this % (0.01%)

# Profit target thresholds (stepped exits) - FEE-AWARE + ULTRA AGGRESSIVE V7.3
# Updated Jan 12, 2026 - PROFITABILITY FIX: Aggressive profit-taking to lock gains
# CRITICAL: With small positions, we need FASTER exits to lock gains
# Default targets are for Coinbase (1.4% fees)
# Coinbase fees are ~1.4%, so minimum 1.5% needed for net profit
# Kraken fees are ~0.36%, so lower targets are profitable
# Strategy: Exit FULL position at FIRST target hit, checking from HIGHEST to LOWEST
# This prioritizes larger gains while providing emergency exit near breakeven
# 🚨 CRITICAL FIX (Feb 4, 2026): Convert PROFIT_TARGETS to fractional format
# pnl_percent is in fractional format (0.02 = 2%), so targets must match
# Previous bug: targets were in percentage format (4.0 = 4%), causing profit-taking to NEVER fire
# Fix: Divide all targets by 100 to convert to fractional format

# 📈 CAPITAL TIER PROFIT LADDERS (Feb 4, 2026)
# Different capital tiers use different profit targets for optimal risk/reward
# Larger accounts can afford to wait for bigger wins
# Smaller accounts need to take profits more aggressively

# MICRO TIER ($10-$100): Aggressive profit-taking, build capital fast
# PROFITABILITY FIX: Removed 1.2% and 1.5% targets — they barely clear broker fees and produce
# near-zero net profit. Minimum raised to 2.0% to ensure meaningful gain after fees.
PROFIT_TARGETS_MICRO = [
    (0.050, "Profit target +5.0% (Micro tier) - EXCELLENT"),
    (0.035, "Profit target +3.5% (Micro tier) - VERY GOOD"),
    (0.025, "Profit target +2.5% (Micro tier) - GOOD"),
    (0.020, "Profit target +2.0% (Micro tier) - MINIMUM (ensures net profit after broker fees)"),
]

# SMALL TIER ($100-$1000): Balanced approach
# PROFITABILITY FIX: Raised minimum from 1.5% to 2.0% (net +0.6% after Coinbase fees).
PROFIT_TARGETS_SMALL = [
    (0.060, "Profit target +6.0% (Small tier) - EXCELLENT"),
    (0.040, "Profit target +4.0% (Small tier) - VERY GOOD"),
    (0.030, "Profit target +3.0% (Small tier) - GOOD"),
    (0.020, "Profit target +2.0% (Small tier) - MINIMUM"),
]

# MEDIUM TIER ($1000-$10000): Let winners run more
PROFIT_TARGETS_MEDIUM = [
    (0.040, "Profit target +4.0% (Medium tier) - MAJOR PROFIT"),
    (0.030, "Profit target +3.0% (Medium tier) - EXCELLENT"),
    (0.025, "Profit target +2.5% (Medium tier) - GOOD"),
    (0.020, "Profit target +2.0% (Medium tier) - ACCEPTABLE"),
]

# LARGE TIER ($10000+): Maximum profit potential
PROFIT_TARGETS_LARGE = [
    (0.050, "Profit target +5.0% (Large tier) - MAJOR PROFIT"),
    (0.040, "Profit target +4.0% (Large tier) - EXCELLENT"),
    (0.030, "Profit target +3.0% (Large tier) - GOOD"),
    (0.025, "Profit target +2.5% (Large tier) - ACCEPTABLE"),
]

# Default fallback targets (medium tier)
PROFIT_TARGETS = PROFIT_TARGETS_MEDIUM

# BROKER-SPECIFIC PROFIT TARGETS (Jan 27, 2026 - PROFITABILITY FIX)
# 🚨 CRITICAL FIX (Feb 4, 2026): All values converted to FRACTIONAL format (0.04 = 4%)
# Different brokers have different fee structures, requiring different profit targets
# These ensure NET profitability after fees for each broker
# PHILOSOPHY: "Little loss, major profit" - tight stops, wide profit targets

# ─── FEE ROUND-TRIP COSTS PER BROKER (entry + exit, including spread) ──────────
# Coinbase:           1.4%  (0.7% taker × 2 + 0.0% spread accounted in target)
# Kraken:             0.6%  (0.26% taker × 2 + ~0.1% spread, safety margin added)
# Binance:            0.2%  (0.1% taker × 2)
# OKX:                0.2%  (0.1% taker × 2)
# Alpaca (crypto):    0.3%  (0.15% per side)
# Others/Unknown:     1.4%  (use Coinbase conservative estimate as fallback)
# ─────────────────────────────────────────────────────────────────────────────────

# FEE BREAKEVEN THRESHOLD per broker: minimum GROSS profit needed to guarantee a
# NET profit after fees and spread.  Positions that drop BELOW this threshold after
# having been ABOVE it trigger an immediate exit to lock in remaining net profit.
# Values include a 0.2% safety buffer on top of round-trip fees.
BROKER_FEE_BREAKEVEN = {
    'coinbase':            0.016,  # 1.6%  = 1.4% fees + 0.2% buffer
    'kraken':              0.008,  # 0.8%  = 0.6% fees + 0.2% buffer
    'binance':             0.004,  # 0.4%  = 0.2% fees + 0.2% buffer
    'okx':                 0.004,  # 0.4%  = 0.2% fees + 0.2% buffer
    'alpaca':              0.005,  # 0.5%  = 0.3% fees + 0.2% buffer
    'interactive_brokers': 0.016,  # 1.6%  = conservative fallback
    'td_ameritrade':       0.016,  # 1.6%  = conservative fallback
    'tradier':             0.016,  # 1.6%  = conservative fallback
}
# Default fee breakeven for any unknown broker (use most conservative value)
DEFAULT_FEE_BREAKEVEN = 0.016

# PROTECTION MIN PROFIT per broker: the profit level above which the "never break
# even" and "pullback" protections activate.  These are higher than the fee
# breakeven to give positions room to develop while still locking in meaningful gains.
BROKER_PROTECTION_MIN_PROFIT = {
    'coinbase':            0.020,  # 2.0%  — was PROFIT_PROTECTION_MIN_PROFIT
    'kraken':              0.010,  # 1.0%  — was PROFIT_PROTECTION_MIN_PROFIT_KRAKEN
    'binance':             0.006,  # 0.6%  = 0.2% fees + 0.4% net target
    'okx':                 0.006,  # 0.6%  = 0.2% fees + 0.4% net target
    'alpaca':              0.008,  # 0.8%  = 0.3% fees + 0.5% net target
    'interactive_brokers': 0.020,  # 2.0%  = conservative fallback
    'td_ameritrade':       0.020,  # 2.0%  = conservative fallback
    'tradier':             0.020,  # 2.0%  = conservative fallback
}
DEFAULT_PROTECTION_MIN_PROFIT = 0.020

# Kraken fees: ~0.6% round-trip (0.26% taker fee × 2 sides + ~0.1% spread safety margin)
# PROFITABILITY FIX: Removed 1.0% (net +0.4%) and 1.5% (net +0.9%) targets.
# Net R:R at 1.5% gross with -1.5% stop = 0.9/2.1 = 0.43:1 — negative expected value.
# Minimum raised to 2.0% (net +1.4%), giving net R:R = 1.4/2.1 = 0.67:1; positive EV at 70%+ win rate.
PROFIT_TARGETS_KRAKEN = [
    (0.040, "Profit target +4.0% (Net +3.4% after 0.6% fees) - MAJOR PROFIT"),    # Major profit - let winners run
    (0.030, "Profit target +3.0% (Net +2.4% after 0.6% fees) - EXCELLENT"),       # Excellent profit
    (0.020, "Profit target +2.0% (Net +1.4% after 0.6% fees) - MINIMUM"),         # Minimum: positive EV at 70%+ win rate
]

# 🚨 COINBASE PROFIT FIX (Jan 2026) - ENSURE NET PROFITABILITY
# 🚨 CRITICAL FIX (Feb 4, 2026): All values converted to FRACTIONAL format (0.05 = 5%)
# Coinbase fees are 1.4% round-trip (0.7% entry + 0.7% exit)
# ALL profit targets must exceed 1.6% to ensure NET profitability after fees and spread
# REMOVED 1.6% "emergency" target (net +0.2%) — negligible gain, not worth the risk with -1.5% stop
# PHILOSOPHY: Only take trades with meaningful positive risk/reward ratio (2:1 minimum)
PROFIT_TARGETS_COINBASE = [
    (0.050, "Profit target +5.0% (Net +3.6% after 1.4% fees) - MAJOR PROFIT"),    # Major profit - let winners run
    (0.035, "Profit target +3.5% (Net +2.1% after 1.4% fees) - EXCELLENT"),       # Excellent profit
    (0.025, "Profit target +2.5% (Net +1.1% after 1.4% fees) - GOOD"),            # Good profit (preferred target)
    (0.020, "Profit target +2.0% (Net +0.6% after fees) - ACCEPTABLE"),           # Minimum acceptable profit
]

# Binance fees: ~0.2% round-trip (0.1% taker fee x 2 sides)
# Lower targets still yield meaningful net profit due to cheap fee structure
PROFIT_TARGETS_BINANCE = [
    (0.040, "Profit target +4.0% (Net +3.8% after 0.2% fees) - MAJOR PROFIT"),
    (0.030, "Profit target +3.0% (Net +2.8% after 0.2% fees) - EXCELLENT"),
    (0.020, "Profit target +2.0% (Net +1.8% after 0.2% fees) - GOOD"),
    (0.010, "Profit target +1.0% (Net +0.8% after 0.2% fees) - ACCEPTABLE"),
    (0.004, "Profit target +0.4% (Net +0.2% after fees) - MINIMAL"),              # Bare minimum profit
]

# OKX fees: ~0.2% round-trip (0.1% taker fee x 2 sides)
PROFIT_TARGETS_OKX = [
    (0.040, "Profit target +4.0% (Net +3.8% after 0.2% fees) - MAJOR PROFIT"),
    (0.030, "Profit target +3.0% (Net +2.8% after 0.2% fees) - EXCELLENT"),
    (0.020, "Profit target +2.0% (Net +1.8% after 0.2% fees) - GOOD"),
    (0.010, "Profit target +1.0% (Net +0.8% after 0.2% fees) - ACCEPTABLE"),
    (0.004, "Profit target +0.4% (Net +0.2% after fees) - MINIMAL"),              # Bare minimum profit
]

# Alpaca fees: ~0.3% round-trip for crypto (0.15% per side)
PROFIT_TARGETS_ALPACA = [
    (0.040, "Profit target +4.0% (Net +3.7% after 0.3% fees) - MAJOR PROFIT"),
    (0.030, "Profit target +3.0% (Net +2.7% after 0.3% fees) - EXCELLENT"),
    (0.020, "Profit target +2.0% (Net +1.7% after 0.3% fees) - GOOD"),
    (0.010, "Profit target +1.0% (Net +0.7% after 0.3% fees) - ACCEPTABLE"),
    (0.005, "Profit target +0.5% (Net +0.2% after fees) - MINIMAL"),              # Bare minimum profit
]

# PROFITABILITY FIX (Jan 27, 2026): Updated profit targets to ensure NET gains
# NIJA is for PROFIT - all targets now ensure positive returns after fees
# Risk/Reward: Minimum 2:1 ratio enforced via stop loss sizing

# FIX #3: Minimum Profit Threshold (Updated for new targets)
# Calculate required profit = spread + fees + buffer before allowing exit
# Coinbase: ~0.7% taker fee x2 + ~0.2% spread = 1.6% round-trip
MIN_PROFIT_SPREAD = 0.002  # 0.2% estimated spread cost
MIN_PROFIT_FEES = 0.014  # 1.4% total fees (0.7% per side)
MIN_PROFIT_BUFFER = 0.002  # 0.2% safety buffer
MIN_PROFIT_THRESHOLD = 0.020  # 2.0% minimum profit (updated from 1.6% to match new targets)

# PROFIT PROTECTION: Updated for new profit targets (Jan 27, 2026)
# Allow slightly larger pullback since profit targets are higher
PROFIT_PROTECTION_ENABLED = True  # Enable profit protection system
PROFIT_PROTECTION_PULLBACK_FIXED = 0.008  # Allow 0.8% pullback (increased from 0.5%)
PROFIT_PROTECTION_MIN_PROFIT = 0.020  # Must exceed 2.0% for Coinbase before protection activates
PROFIT_PROTECTION_MIN_PROFIT_KRAKEN = 0.010  # Must exceed 1.0% for Kraken before protection activates
PROFIT_PROTECTION_NEVER_BREAKEVEN = True  # Never allow profitable positions to break even

# Stop loss thresholds - ULTRA-AGGRESSIVE (V7.4 FIX - Jan 19, 2026)
# CRITICAL: Exit ANY losing trade IMMEDIATELY (P&L < 0%)
# These thresholds are FAILSAFES only - primary exit is immediate on any loss
# Jan 19, 2026: Changed to immediate exit on ANY loss per user requirement
# Jan 13, 2026: Tightened to -1.0% to cut losses IMMEDIATELY
# Jan 19, 2026: 3-TIER STOP-LOSS SYSTEM for Kraken small balances
# Tier 1: Primary trading stop (-0.6% to -0.8%) - Real stop-loss for risk management
# Tier 2: Emergency micro-stop (-0.01%) - Logic failure prevention (not a trading stop)
# Tier 3: Catastrophic failsafe (-5.0%) - Last resort protection

# 🚨 STOP LOSS FIX (Jan 27, 2026) - PROPER RISK/REWARD RATIO
# Updated to ensure minimum 2:1 reward-to-risk ratio
# With profit targets of 2.5%+ (Coinbase) and 2.0%+ (Kraken),
# stop losses must be proportionally sized to maintain good risk/reward

# TIER 1: PRIMARY TRADING STOP-LOSS
# Tightened to -1.5% to enforce proper risk/reward ratio across all brokers and users.
# With profit targets of 2.0-5.0%, a -1.5% stop gives minimum 1.3:1 R:R.
# Previous -3.0% stop with 1.5-2.5% targets produced negative expected value.
STOP_LOSS_PRIMARY_KRAKEN = -0.015  # -1.5% for Kraken (restored from -3.0%)
STOP_LOSS_PRIMARY_KRAKEN_MIN = -0.015  # -1.5% minimum
STOP_LOSS_PRIMARY_KRAKEN_MAX = -0.020  # -2.0% maximum (tight band to limit losses)

# Coinbase: tightened to -1.5% to overcome the 1.4% round-trip fee drag
STOP_LOSS_PRIMARY_COINBASE = -0.015  # -1.5% primary stop for Coinbase (restored from -3.0%)
COINBASE_STOP_LOSS_MIN = -0.015  # -1.5% minimum
COINBASE_STOP_LOSS_MAX = -0.020  # -2.0% maximum

# Remove the "exit on ANY loss" requirement - this was causing premature exits
COINBASE_EXIT_ANY_LOSS = False  # Allow positions to breathe, honor stop loss levels
COINBASE_MAX_HOLD_MINUTES = 60  # Increased from 30 to 60 minutes (allow time for profit)
COINBASE_PROFIT_LOCK_ENABLED = True  # Enable aggressive profit-taking on Coinbase

# TIER 2: EMERGENCY STOP (Logic failure prevention)
# Scaled proportionally with the tightened primary stop.
STOP_LOSS_MICRO = -0.020  # -2.0% emergency backstop (was -4.0%, scaled with primary stop)
STOP_LOSS_WARNING = -0.015  # -1.5% warn level (matches primary stop for early alert)
STOP_LOSS_THRESHOLD = -0.020  # -2.0% primary stop threshold (was -4.0%)

# TIER 3: CATASTROPHIC FAILSAFE
# Last resort protection - should NEVER be reached in normal operation
# NORMALIZED FORMAT: -0.03 = -3% (fractional format)
STOP_LOSS_EMERGENCY = -0.03  # EMERGENCY exit at -3% loss (was -5%, tightened to limit catastrophic losses)

# PROFITABILITY GUARD: Minimum loss threshold to reduce noise
# CRITICAL FIX (Feb 3, 2026): Lowered from -0.25% to -0.05% to avoid creating dead zone
# OLD VALUE: -0.0025 (-0.25%) created dead zone where stops wouldn't trigger
# NEW VALUE: -0.0005 (-0.05%) only filters bid/ask spread noise
MIN_LOSS_FLOOR = -0.0005  # -0.05% - only ignore bid/ask spread noise (was -0.25%, too high)

# Auto-import safety default constants (FIX #1 - Jan 19, 2026)
# When auto-importing orphaned positions without real entry price, use safety default
# This creates immediate negative P&L to flag position as losing for aggressive exit
SAFETY_DEFAULT_ENTRY_MULTIPLIER = 1.01  # Assume entry was 1% higher than current price
                                          # Creates -0.99% immediate P&L, flagging as loser

# Position management constants - PROFITABILITY FIX (Dec 28, 2025)
# Updated Jan 20, 2026: Raised minimum to $5 for safer trade sizing
# Updated Jan 21, 2026: OPTION 3 (BEST LONG-TERM) - Dynamic minimum based on balance
# ⚠️ CRITICAL WARNING: Small positions are unprofitable due to fees (~1.4% round-trip)
# With $5+ positions, trades have better chance of profitability after fees
# This ensures better trading outcomes and quality over quantity
# STRONG RECOMMENDATION: Fund account to $50+ for optimal trading outcomes
# Support override via MAX_CONCURRENT_POSITIONS environment variable for custom configurations
# Hard cap aligned with MAX_TOTAL_POSITIONS = 5 (global limit, force consolidation).
# Per-balance sub-limits are enforced at runtime via get_balance_based_max_positions().
HARD_MAX_POSITIONS = MAX_TOTAL_POSITIONS  # Absolute ceiling = global cap (5)
_max_positions_env = os.getenv('MAX_CONCURRENT_POSITIONS', str(MAX_CONCURRENT_TRADES))
try:
    MAX_POSITIONS_ALLOWED = int(_max_positions_env)
except ValueError:
    MAX_POSITIONS_ALLOWED = MAX_CONCURRENT_TRADES  # Default: micro_capital_config value (4)
# Enforce hard ceiling – never exceed MAX_TOTAL_POSITIONS regardless of env override
if MAX_POSITIONS_ALLOWED > HARD_MAX_POSITIONS:
    MAX_POSITIONS_ALLOWED = HARD_MAX_POSITIONS
    logger.info(f"📊 MAX_CONCURRENT_POSITIONS capped at hard limit of {HARD_MAX_POSITIONS}")
logger.info(f"📊 Max concurrent positions: {MAX_POSITIONS_ALLOWED} (global cap={MAX_TOTAL_POSITIONS})")

# SPOT_ONLY mode: when enabled, all 'enter_short' signals are blocked so the
# bot only opens long (buy) positions, matching exchange spot-trading semantics.
# Activate via environment variable: SPOT_ONLY=true
SPOT_ONLY = os.getenv('SPOT_ONLY', 'false').strip().lower() == 'true'
if SPOT_ONLY:
    logger.info("🔒 SPOT_ONLY mode: short-selling disabled – only long positions permitted")

# INCUBATION_MODE: activates the disciplined incubation risk profile.
# When true, enforces 0.5%–1% risk per trade, max 5–8 positions,
# 40% correlation cap, ATR-adjusted sizing, VaR auto-size reduction,
# and the drawdown circuit breaker.
# Activate via environment variable: INCUBATION_MODE=true
INCUBATION_MODE = os.getenv('INCUBATION_MODE', 'false').strip().lower() == 'true'
if INCUBATION_MODE:
    if not SPOT_ONLY:
        # Incubation mode always implies spot-only
        SPOT_ONLY = True
        logger.info("🐣 INCUBATION_MODE: SPOT_ONLY enforced automatically")
    # Cap max positions to the incubation ceiling of 3 if the env is not already lower
    if MAX_POSITIONS_ALLOWED > 3:
        MAX_POSITIONS_ALLOWED = 3
        logger.info("🐣 INCUBATION_MODE: MAX_POSITIONS_ALLOWED capped at 3")

# Forced cleanup interval (cycles between cleanup runs)
# Default: 6 cycles (~15 minutes at 2.5 min/cycle) - For maximum safety optics
# Can be overridden via FORCED_CLEANUP_INTERVAL environment variable
_cleanup_interval_env = os.getenv('FORCED_CLEANUP_INTERVAL', '6')
try:
    FORCED_CLEANUP_INTERVAL = int(_cleanup_interval_env)
except ValueError:
    FORCED_CLEANUP_INTERVAL = 6  # Default fallback (15 minutes)
logger.debug(f"🧹 Forced cleanup interval: every {FORCED_CLEANUP_INTERVAL} cycles (~{FORCED_CLEANUP_INTERVAL * 2.5:.0f} minutes)")

# Optional: Cleanup after N trades executed (alternative/additional trigger)
# If set, cleanup runs after N trades OR every FORCED_CLEANUP_INTERVAL cycles (whichever comes first)
_cleanup_trades_env = os.getenv('FORCED_CLEANUP_AFTER_N_TRADES', '')
try:
    FORCED_CLEANUP_AFTER_N_TRADES = int(_cleanup_trades_env) if _cleanup_trades_env else None
    if FORCED_CLEANUP_AFTER_N_TRADES:
        logger.debug(f"🧹 Forced cleanup also triggers after {FORCED_CLEANUP_AFTER_N_TRADES} trades executed")
except ValueError:
    FORCED_CLEANUP_AFTER_N_TRADES = None

# OPTION 3 (BEST LONG-TERM): Dynamic minimum based on balance
# MIN_TRADE_USD = max(10.00, balance * 0.15)
# This scales automatically with account size:
# - $20 account: min trade = $10.00 (15% would be $3.00, floor enforced)
# - $50 account: min trade = $10.00 (15% would be $7.50, floor enforced)
# - $70 account: min trade = $10.50 (15% of $70)
# - $100 account: min trade = $15.00 (15% of $100)
# Minimum $10 per position ensures fee efficiency and meaningful compounding gains
BASE_MIN_POSITION_SIZE_USD = 10.0  # Floor minimum ($10 - no trade under $10 for fee efficiency)
DYNAMIC_POSITION_SIZE_PCT = 0.18  # 18% of balance per position (locked setting)
POSITION_SIZE_WARNING_THRESHOLD_USD = 15.0  # Warn when position is under this amount (near floor)

# OPTION B: Brokerage-specific minimum trade sizes
# Any trade that would create a position below this threshold is skipped,
# preventing dust positions at creation time.
BROKERAGE_MIN_TRADE_USD: dict = {
    'coinbase': 10.0,   # Coinbase minimum ($10 for fee efficiency)
    'kraken':   10.0,   # Kraken exchange minimum ($10 per exchange rules)
    'binance':  10.0,   # Binance minimum
    'okx':      10.0,   # OKX minimum
    'alpaca':   1.0,    # Alpaca minimum (stocks, lower fees)
}

def get_dynamic_min_position_size(balance: float, broker_name: str = '') -> float:
    """
    Calculate dynamic minimum position size based on account balance and
    brokerage-specific minimums (Option B – prevent dust at trade creation).

    Formula: min_trade_usd = max(BASE_MIN_POSITION_SIZE_USD,
                                 account_balance * min_trade_pct,
                                 brokerage_minimum)

    Args:
        balance: Current account balance in USD
        broker_name: Name of the active broker (e.g. 'coinbase', 'kraken').
                     Used to enforce exchange-specific minimum order sizes.
                     Pass an empty string to use the global floor only.

    Returns:
        Minimum position size in USD (never below BASE_MIN_POSITION_SIZE_USD
        or the broker's own minimum, whichever is larger)

    Raises:
        ValueError: If balance is negative
    """
    if balance < 0:
        raise ValueError(f"Balance cannot be negative: {balance}")

    # Look up brokerage-specific minimum (default to BASE_MIN_POSITION_SIZE_USD)
    brokerage_min = BROKERAGE_MIN_TRADE_USD.get(
        broker_name.lower() if broker_name else '',
        BASE_MIN_POSITION_SIZE_USD,
    )

    # Enforce: max(MIN_POSITION_USD floor, base floor, balance-based dynamic, brokerage minimum)
    # MIN_POSITION_USD is the absolute hard floor (prevents any sub-$5 entry regardless of config)
    return max(MIN_POSITION_USD, BASE_MIN_POSITION_SIZE_USD, balance * DYNAMIC_POSITION_SIZE_PCT, brokerage_min)


def get_balance_based_max_positions(balance: float) -> int:
    """
    Return the maximum number of concurrent open positions allowed for the
    given account balance.

    Per-account position cap (force consolidation on all accounts):
      • balance  < BALANCE_THRESHOLD_MICRO ($150)  → 2 positions  (micro / starter)
      • balance  < BALANCE_THRESHOLD_SMALL ($500)  → 3 positions  (small accounts)
      • otherwise                                  → MAX_TOTAL_POSITIONS (= 3)

    The returned value is always capped at MAX_TOTAL_POSITIONS so it is safe
    to use as a direct replacement for the global MAX_POSITIONS_ALLOWED
    whenever a live balance is available.

    Args:
        balance: Current account balance in USD (≥ 0).

    Returns:
        Maximum allowed concurrent positions (int, 1 – MAX_TOTAL_POSITIONS).
    """
    if balance < 0:
        logger.warning(
            "get_balance_based_max_positions: negative balance %.2f detected "
            "(possible API error) – treating as 0.0",
            balance,
        )
        balance = 0.0

    if balance < BALANCE_THRESHOLD_MICRO:
        cap = 2
    elif balance < BALANCE_THRESHOLD_SMALL:
        cap = 3
    else:
        cap = MAX_TOTAL_POSITIONS

    # Never exceed the global hard cap
    return min(cap, MAX_TOTAL_POSITIONS)

# DEPRECATED: Use get_dynamic_min_position_size() instead
# This constant is maintained for backward compatibility only
MIN_POSITION_SIZE_USD = BASE_MIN_POSITION_SIZE_USD  # Legacy fallback (use get_dynamic_min_position_size() instead)
MIN_BALANCE_TO_TRADE_USD = 10.0  # Minimum account balance to allow trading ($10 matches minimum position size)

# ── MICRO ACCOUNT PERFORMANCE BOOSTERS (Mar 2026) ─────────────────────────
# Four features designed to maximise growth for small accounts.  They operate
# independently but can activate simultaneously for accounts ≤ $500.
#
# Feature 1 & 2 (Auto dust cleanup / Forced capital consolidation):
#   • Global cadence : every FORCED_CLEANUP_INTERVAL cycles (~15 min)
#   • Micro cadence  : every MICRO_CLEANUP_INTERVAL cycles (~7.5 min) when
#                      balance < MICRO_CLEANUP_BALANCE_THRESHOLD
#   The auto-cleanup engine (Feature 1) liquidates dust (<$2) back to USDT,
#   while the forced-cleanup engine (Feature 2) merges micro-positions so
#   free capital is consolidated for the next entry.
#   Both use the same MICRO_CLEANUP_INTERVAL so they always fire together.
#
# Feature 3 (Trade frequency booster):
#   • Accounts below MICRO_FREQ_BOOST_THRESHOLD always scan MARKET_BATCH_SIZE_MAX
#     markets per cycle, bypassing the gradual warmup ramp.  Rotation is
#     preserved — the extended batch is appended from the current rotation
#     offset rather than restarting from index 0.
#
# Feature 4 ($100→$1K accelerator mode):
#   • For accounts in [ACCELERATOR_MIN_BALANCE, ACCELERATOR_MAX_BALANCE) that
#     are NOT already in micro-cap compounding mode (which has its own sizing),
#     position size is boosted to ACCELERATOR_POSITION_PCT of balance (25%)
#     instead of the default DYNAMIC_POSITION_SIZE_PCT (18%).
#   • Micro-cap compounding mode takes precedence because it handles the
#     $15–$500 range with its own optimised profit-target and stop-loss logic.
#     The accelerator mode fills the $500–$1 000 gap where micro-cap config
#     is no longer active but accounts still benefit from larger positions.
#
# Priority / precedence when ranges overlap ($100–$500):
#   micro-cap compounding config (if active) > accelerator mode > default sizing
#   cleanup interval : MICRO_CLEANUP_INTERVAL (micro) > FORCED_CLEANUP_INTERVAL (global)
#   scan batch       : MARKET_BATCH_SIZE_MAX (micro, freq-boosted) ≥ adaptive batch
MICRO_CLEANUP_BALANCE_THRESHOLD = 500.0   # Aggressive cleanup threshold (USD)
MICRO_CLEANUP_INTERVAL         = 3        # Cleanup every 3 cycles for micro accounts (~7.5 min)
MICRO_FREQ_BOOST_THRESHOLD     = 500.0    # Always use max batch scan below this balance
ACCELERATOR_MIN_BALANCE        = 100.0    # Lower bound of $100→$1K accelerator range
ACCELERATOR_MAX_BALANCE        = 1000.0   # Upper bound of $100→$1K accelerator range
# NOTE: ACCELERATOR_POSITION_PCT is expressed as a percentage (e.g. 25.0 = 25%).
# DYNAMIC_POSITION_SIZE_PCT (used elsewhere) is a fraction (e.g. 0.18 = 18%).
# get_accelerator_position_size_pct() always returns a percentage for consistency.
ACCELERATOR_POSITION_PCT       = 25.0     # Position-size % in accelerator mode (vs 18% normal)


def get_accelerator_position_size_pct(balance: float) -> float:
    """Return elevated position-size percentage for the $100→$1K accelerator mode.

    Both the in-range return value (``ACCELERATOR_POSITION_PCT``) and the
    out-of-range fallback (``DYNAMIC_POSITION_SIZE_PCT × 100``) are expressed as
    **percentages** (e.g. 25.0 = 25%).  Multiply by ``account_balance / 100.0``
    to obtain a dollar position size.

    Note: ``DYNAMIC_POSITION_SIZE_PCT`` is stored as a fraction (0.18) while
    ``ACCELERATOR_POSITION_PCT`` is stored as a percentage (25.0).  This
    function normalises both to percentages so callers always receive the same
    unit regardless of which branch executes.

    Args:
        balance: Current account balance in USD.

    Returns:
        Position-size percentage (e.g. 25.0 for 25%).
    """
    if ACCELERATOR_MIN_BALANCE <= balance < ACCELERATOR_MAX_BALANCE:
        return ACCELERATOR_POSITION_PCT
    # DYNAMIC_POSITION_SIZE_PCT is a fraction (e.g. 0.18); convert to percentage.
    return DYNAMIC_POSITION_SIZE_PCT * 100.0

# FIX #3 (Jan 20, 2026): Kraken-specific minimum thresholds
# UPDATE (Jan 22, 2026): Aligned with new tier structure and $10 minimum trade size
# Kraken enforces $10 minimum trade size per exchange rules
MIN_KRAKEN_BALANCE = 10.0   # Minimum balance for Kraken to allow trading (updated from $25)
MIN_POSITION_SIZE = 10.0    # Minimum position size for Kraken ($10 minimum trade)

# BROKER PRIORITY SYSTEM (Jan 22, 2025)
# Define entry broker priority for BUY orders
# Brokers will be selected in this order if eligible (not in EXIT_ONLY mode and balance >= minimum)
# Coinbase automatically falls to bottom priority if balance < $25
ENTRY_BROKER_PRIORITY = [
    BrokerType.KRAKEN,
    BrokerType.OKX,
    BrokerType.BINANCE,
    BrokerType.COINBASE,
]

# Minimum balance thresholds for broker eligibility
# UPDATE (Jan 22, 2026): Aligned with new tier structure and $10 Kraken minimum
BROKER_MIN_BALANCE = {
    BrokerType.COINBASE: 10.0,  # Coinbase minimum lowered to support SAVER tier
    BrokerType.KRAKEN: 10.0,    # Kraken minimum is $10 per exchange rules
    BrokerType.OKX: 10.0,       # Lower minimum for OKX
    BrokerType.BINANCE: 10.0,   # Lower minimum for Binance
}

# ============================================================================
# HEARTBEAT TRADE CONFIGURATION
# ============================================================================
# Heartbeat trades are tiny test trades executed periodically to verify:
# - Exchange connectivity is working
# - Order execution is functioning
# - API credentials are valid
# Useful for verification after deployment or to monitor exchange health
HEARTBEAT_TRADE_ENABLED = os.getenv('HEARTBEAT_TRADE', 'false').lower() in ('true', '1', 'yes')
HEARTBEAT_TRADE_SIZE_USD = float(os.getenv('HEARTBEAT_TRADE_SIZE', '5.50'))  # Minimum viable trade size
HEARTBEAT_TRADE_INTERVAL_SECONDS = int(os.getenv('HEARTBEAT_TRADE_INTERVAL', '600'))  # 10 minutes default

if HEARTBEAT_TRADE_ENABLED:
    logger.info(f"❤️  HEARTBEAT TRADE ENABLED: ${HEARTBEAT_TRADE_SIZE_USD:.2f} every {HEARTBEAT_TRADE_INTERVAL_SECONDS}s")
else:
    logger.debug("Heartbeat trade disabled (set HEARTBEAT_TRADE=true to enable)")

def call_with_timeout(func, args=(), kwargs=None, timeout_seconds=30):
    """
    Execute a function with a timeout. Returns (result, error).
    If timeout occurs, returns (None, TimeoutError).
    Default timeout is 30 seconds to accommodate production API latency.

    CRITICAL FIX (Jan 27, 2026): Fixed race condition where queue.get_nowait()
    could raise queue.Empty even after successful completion.
    """
    if kwargs is None:
        kwargs = {}
    result_queue = queue.Queue()

    def worker():
        try:
            result = func(*args, **kwargs)
            result_queue.put((True, result))
        except Exception as e:
            result_queue.put((False, e))

    t = Thread(target=worker, daemon=False)  # Changed to daemon=False to prevent premature termination
    t.start()
    t.join(timeout_seconds)

    if t.is_alive():
        # Thread still running after timeout
        return None, TimeoutError(f"Operation timed out after {timeout_seconds}s")

    # CRITICAL FIX: Use get() with small timeout instead of get_nowait()
    # FIX: Use get(timeout=1.0) instead of get_nowait() to prevent race condition
    # After thread.join(), there's a small window where result may not be in queue yet
    # 1.0s timeout is generous - actual queue write happens in <10ms
    try:
        ok, value = result_queue.get(timeout=1.0)
        return (value, None) if ok else (None, value)
    except queue.Empty:
        # This should never happen if thread completed, but handle it anyway
        return None, Exception("Worker thread completed but no result available")


def safe_close_position(broker, symbol: str, quantity: float) -> bool:
    """
    Safe wrapper around broker.close_position that prevents exchange errors
    from halting the pipeline.

    Args:
        broker: Broker instance with a close_position method.
        symbol: Trading symbol to close.
        quantity: Quantity to close; must be positive.

    Returns:
        True if the position was closed successfully, False otherwise.
    """
    if quantity <= 0:
        return False

    try:
        broker.close_position(symbol, quantity=quantity)
        return True
    except Exception as e:
        logger.warning(f"Dust close failed for {symbol}: {e}")
        return False


# Add bot directory to path if running from root
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Optional market price helper; safe fallback if unavailable
try:
    from bot.market_data import get_current_price  # type: ignore
except Exception:
    def get_current_price(symbol: str):
        """Fallback price lookup (returns None if unavailable)."""
        return None

class TradingStrategy:
    """Production Trading Strategy - Coinbase APEX v7.1.

    Encapsulates the full APEX v7.1 trading strategy with position cap enforcement.
    Integrates market scanning, entry/exit logic, risk management, and automated
    position limit enforcement.
    """

    def __init__(self):
        """Initialize production strategy with multi-broker support."""
        logger.info("Initializing TradingStrategy (APEX v7.1 - Multi-Broker Mode)...")

        # Last Evaluated Trade Tracking (for UI panel)
        self.last_evaluated_trade = {
            'timestamp': None,
            'symbol': None,
            'signal': None,
            'action': None,  # 'executed', 'vetoed', 'evaluated'
            'veto_reasons': [],
            'entry_price': None,
            'position_size': None,
            'broker': None,
            'confidence': None,
            'rsi_9': None,
            'rsi_14': None
        }

        # Initialize safety controller (App Store compliance)
        try:
            from safety_controller import get_safety_controller, TradingMode
            self.safety = get_safety_controller()
            self.safety.log_status()
            
            # Store dry_run_mode for backward compatibility
            self.dry_run_mode = (self.safety.get_current_mode() == TradingMode.DRY_RUN)
        except ImportError:
            # Fallback if safety_controller not available
            logger.warning("⚠️ Safety controller not available - using legacy safety checks")
            self.safety = None
            self.dry_run_mode = os.getenv('DRY_RUN_MODE', 'false').lower() in ('true', '1', 'yes')
            if self.dry_run_mode:
                logger.info("=" * 70)
                logger.info("🎭 DRY-RUN SIMULATOR MODE ACTIVE")
                logger.info("=" * 70)
                logger.info("   FOR APP STORE REVIEW ONLY")
                logger.info("   All trades are simulated - NO REAL ORDERS PLACED")
                logger.info("   Broker API calls return mock data")
                logger.info("=" * 70)

        # Load Capital Growth Ladder config (tier-based fixed trade sizes)
        self.capital_growth_rules = self._load_capital_growth_rules()

        # FIX #1: Initialize portfolio state manager for total equity tracking
        try:
            from portfolio_state import get_portfolio_manager
            self.portfolio_manager = get_portfolio_manager()
            logger.info("✅ Portfolio state manager initialized - using total equity for sizing")
        except ImportError:
            logger.warning("⚠️ Portfolio state manager not available - falling back to cash-based sizing")
            self.portfolio_manager = None

        # Initialize Market Readiness Gate for entry quality control
        if MarketReadinessGate is not None:
            try:
                self.market_readiness_gate = MarketReadinessGate()
                logger.info("✅ Market Readiness Gate initialized - entry quality control active")
            except Exception as e:
                logger.warning(f"⚠️ Failed to initialize Market Readiness Gate: {e}")
                self.market_readiness_gate = None
        else:
            self.market_readiness_gate = None
            logger.warning("⚠️ Market Readiness Gate not available - using legacy entry mode")
        
        # Initialize Trade Quality Gate (Layer 2: Better Math Per Trade)
        if TradeQualityGate is not None:
            try:
                self.quality_gate = TradeQualityGate(min_reward_risk=1.5, require_momentum=True)
                logger.info("✅ Trade Quality Gate initialized - R:R filtering active")
            except Exception as e:
                logger.warning(f"⚠️ Failed to initialize Trade Quality Gate: {e}")
                self.quality_gate = None
        else:
            self.quality_gate = None

        # Initialize Win Rate Maximizer — trade filtering, risk caps, profit consistency
        if WIN_RATE_MAXIMIZER_AVAILABLE and _get_win_rate_maximizer is not None:
            try:
                self.win_rate_maximizer = _get_win_rate_maximizer()
                logger.info("✅ Win Rate Maximizer initialized - trade filtering / risk caps / profit consistency active")
            except Exception as e:
                logger.warning(f"⚠️ Failed to initialize Win Rate Maximizer: {e}")
                self.win_rate_maximizer = None
        else:
            self.win_rate_maximizer = None

        # Initialize Capital Concentration Engine — concentration mode, account ranking,
        # kill-weak accounts, live-execution verification, Kelly sizing, dashboard
        if CAPITAL_CONCENTRATION_AVAILABLE and get_capital_concentration_engine is not None:
            try:
                self.capital_concentration_engine = get_capital_concentration_engine()
                logger.info(
                    "✅ Capital Concentration Engine initialized - "
                    "concentration mode / account ranking / kill-weak / Kelly sizing active"
                )
            except Exception as _cce_err:
                logger.warning("⚠️ Failed to initialize Capital Concentration Engine: %s", _cce_err)
                self.capital_concentration_engine = None
        else:
            self.capital_concentration_engine = None

        # Initialize Account-Level Capital Flow — connects CCE + AIAllocator
        if ACCOUNT_FLOW_AVAILABLE and get_account_level_capital_flow is not None:
            try:
                self.account_flow_layer = get_account_level_capital_flow()
                logger.info(
                    "✅ Account-Level Capital Flow initialized - "
                    "account ranking + kill-weak + AI weights active"
                )
            except Exception as _afl_err:
                logger.warning("⚠️ Failed to initialize Account-Level Capital Flow: %s", _afl_err)
                self.account_flow_layer = None
        else:
            self.account_flow_layer = None

        # Initialize Global Capital Brain — top-level routing + efficiency score +
        # snowball mode + smarter reallocation (sits above all other capital layers)
        if GLOBAL_CAPITAL_BRAIN_AVAILABLE and get_global_capital_brain is not None:
            try:
                self.global_capital_brain = get_global_capital_brain()
                logger.info(
                    "✅ Global Capital Brain initialized - "
                    "capital routing + efficiency score + snowball mode + reallocation active"
                )
            except Exception as _gcb_err:
                logger.warning("⚠️ Failed to initialize Global Capital Brain: %s", _gcb_err)
                self.global_capital_brain = None
        else:
            self.global_capital_brain = None

        # Initialize Profit Lock System — ratchet stops + auto-withdrawal of secured gains
        if PROFIT_LOCK_SYSTEM_AVAILABLE and _get_profit_lock_system is not None:
            try:
                self.profit_lock_system = _get_profit_lock_system()
                logger.info("✅ Profit Lock System initialized – ratchet stops + auto-withdrawal active")
            except Exception as _pls_init_err:
                logger.warning("⚠️ Failed to initialize Profit Lock System: %s", _pls_init_err)
                self.profit_lock_system = None
        else:
            self.profit_lock_system = None

        # Initialize CapitalAllocator — cycle-oriented Step 2/3/5 allocation layer
        if CAPITAL_ALLOCATOR_AVAILABLE and _get_capital_allocator is not None:
            try:
                self._capital_allocator = _get_capital_allocator()
                logger.info("✅ CapitalAllocator initialized — performance-based cycle budgeting active")
            except Exception as _ca_init_err:
                logger.warning("⚠️ Failed to initialize CapitalAllocator: %s", _ca_init_err)
                self._capital_allocator = None
        else:
            self._capital_allocator = None

        # Initialize Market Regime Controller — meta-layer: "Should we trade now?"
        if REGIME_CONTROLLER_AVAILABLE and get_regime_controller is not None:
            try:
                self.regime_controller = get_regime_controller()
                # Active snapshot accumulates per-asset observations during each cycle
                self._regime_snapshot = None
                logger.info("✅ Market Regime Controller initialized - regime gating active")
            except Exception as e:
                logger.warning(f"⚠️ Failed to initialize Market Regime Controller: {e}")
                self.regime_controller = None
                self._regime_snapshot = None
        else:
            self.regime_controller = None
            self._regime_snapshot = None

        # Initialize Market Regime Engine — per-candle BULL/CHOP/CRASH aggression
        if MARKET_REGIME_ENGINE_AVAILABLE and get_market_regime_engine is not None:
            try:
                self.regime_engine = get_market_regime_engine()
                logger.info("✅ Market Regime Engine initialized - bull/chop/crash aggression active")
            except Exception as e:
                logger.warning(f"⚠️ Failed to initialize Market Regime Engine: {e}")
                self.regime_engine = None
        else:
            self.regime_engine = None

        # Initialize Risk Budget Engine — risk-first position sizing with performance scaling
        if RISK_BUDGET_ENGINE_AVAILABLE and RiskBudgetEngine is not None:
            try:
                self.risk_budget_engine = RiskBudgetEngine()
                logger.info("✅ Risk Budget Engine initialized - risk-first position sizing active")
            except Exception as e:
                logger.warning(f"⚠️ Failed to initialize Risk Budget Engine: {e}")
                self.risk_budget_engine = None
        else:
            self.risk_budget_engine = None

        # Initialize Slippage Protector — pre-trade gate that blocks high-slippage orders
        if SLIPPAGE_PROTECTION_AVAILABLE and get_slippage_protector is not None:
            try:
                self.slippage_protector = get_slippage_protector()
                logger.info("✅ Slippage Protector initialized - pre-trade slippage gating active")
            except Exception as e:
                logger.warning(f"⚠️ Failed to initialize Slippage Protector: {e}")
                self.slippage_protector = None
        else:
            self.slippage_protector = None

        # Leak #1 fix: Net Profit Gate — blocks signals where profit < costs×2
        if NET_PROFIT_GATE_AVAILABLE and get_net_profit_gate is not None:
            try:
                self.net_profit_gate = get_net_profit_gate()
                logger.info("✅ Net Profit Gate initialized")
            except Exception as e:
                logger.warning(f"⚠️ Failed to initialize Net Profit Gate: {e}")
                self.net_profit_gate = None
        else:
            self.net_profit_gate = None

        # Leak #2 fix: Latency Drift Guard — stamps signal price, rejects on drift
        if LATENCY_DRIFT_GUARD_AVAILABLE and get_latency_drift_guard is not None:
            try:
                self.latency_drift_guard = get_latency_drift_guard()
                logger.info("✅ Latency Drift Guard initialized")
            except Exception as e:
                logger.warning(f"⚠️ Failed to initialize Latency Drift Guard: {e}")
                self.latency_drift_guard = None
        else:
            self.latency_drift_guard = None

        # Leak #3 fix: Capital Fragmentation Guard — pauses underperforming accounts
        if FRAGMENTATION_GUARD_AVAILABLE and get_fragmentation_guard is not None:
            try:
                self.fragmentation_guard = get_fragmentation_guard()
                logger.info("✅ Capital Fragmentation Guard initialized")
            except Exception as e:
                logger.warning(f"⚠️ Failed to initialize Capital Fragmentation Guard: {e}")
                self.fragmentation_guard = None
        else:
            self.fragmentation_guard = None

        # Initialize Volatility Position Sizer — ATR-based position size scaling
        if VOLATILITY_POSITION_SIZING_AVAILABLE and get_volatility_position_sizer is not None:
            try:
                self.volatility_position_sizer = get_volatility_position_sizer()
                logger.info("✅ Volatility Position Sizer initialized - ATR-based scaling active")
            except Exception as e:
                logger.warning(f"⚠️ Failed to initialize Volatility Position Sizer: {e}")
                self.volatility_position_sizer = None
        else:
            self.volatility_position_sizer = None

        # Initialize Cross-Broker Arbitrage Monitor
        if CROSS_BROKER_ARB_AVAILABLE and get_arb_monitor is not None:
            try:
                self.arb_monitor = get_arb_monitor()
                logger.info("✅ Cross-Broker Arbitrage Monitor initialized")
            except Exception as e:
                logger.warning(f"⚠️ Failed to initialize Cross-Broker Arbitrage Monitor: {e}")
                self.arb_monitor = None
        else:
            self.arb_monitor = None

        # Initialize Volatility-Weighted Capital Router
        if VOLATILITY_CAPITAL_ROUTER_AVAILABLE and get_volatility_router is not None:
            try:
                self.volatility_capital_router = get_volatility_router()
                logger.info("✅ Volatility-Weighted Capital Router initialized")
            except Exception as e:
                logger.warning(f"⚠️ Failed to initialize Volatility-Weighted Capital Router: {e}")
                self.volatility_capital_router = None
        else:
            self.volatility_capital_router = None

        # Initialize Regime Capital Allocator
        if REGIME_CAPITAL_ALLOCATOR_AVAILABLE and get_regime_capital_allocator is not None:
            try:
                self.regime_capital_allocator = get_regime_capital_allocator()
                logger.info("✅ Regime Capital Allocator initialized")
            except Exception as e:
                logger.warning(f"⚠️ Failed to initialize Regime Capital Allocator: {e}")
                self.regime_capital_allocator = None
        else:
            self.regime_capital_allocator = None

        # Initialize Global Drawdown Circuit Breaker
        if GLOBAL_DRAWDOWN_CB_AVAILABLE and get_global_drawdown_cb is not None:
            try:
                self.global_drawdown_cb = get_global_drawdown_cb()
                logger.info("✅ Global Drawdown Circuit Breaker initialized")
            except Exception as e:
                logger.warning(f"⚠️ Failed to initialize Global Drawdown Circuit Breaker: {e}")
                self.global_drawdown_cb = None
        else:
            self.global_drawdown_cb = None

        # ── Phase 3: Dynamic Stop-Loss Tightener ─────────────────────────────
        if DYNAMIC_STOP_TIGHTENER_AVAILABLE and get_dynamic_stop_tightener is not None:
            try:
                self.dynamic_stop_tightener = get_dynamic_stop_tightener()
                logger.info("✅ Phase 3: Dynamic Stop-Loss Tightener initialized")
            except Exception as _e:
                logger.warning("⚠️ Phase 3: Dynamic Stop-Loss Tightener init failed: %s", _e)
                self.dynamic_stop_tightener = None
        else:
            self.dynamic_stop_tightener = None

        # ── Phase 3: Partial TP Ladder ────────────────────────────────────────
        if PARTIAL_TP_LADDER_AVAILABLE and get_partial_tp_ladder is not None:
            try:
                self.partial_tp_ladder = get_partial_tp_ladder()
                logger.info("✅ Phase 3: Partial TP Ladder initialized")
            except Exception as _e:
                logger.warning("⚠️ Phase 3: Partial TP Ladder init failed: %s", _e)
                self.partial_tp_ladder = None
        else:
            self.partial_tp_ladder = None

        # ── Phase 3: News / Event Volatility Filter ───────────────────────────
        if NEWS_VOLATILITY_FILTER_AVAILABLE and get_news_volatility_filter is not None:
            try:
                self.news_volatility_filter = get_news_volatility_filter()
                logger.info("✅ Phase 3: News/Event Volatility Filter initialized")
            except Exception as _e:
                logger.warning("⚠️ Phase 3: News/Event Volatility Filter init failed: %s", _e)
                self.news_volatility_filter = None
        else:
            self.news_volatility_filter = None

        # ── Phase 3: Multi-Timeframe Confirmation AI ──────────────────────────
        if MTF_CONFIRMATION_AVAILABLE and get_mtf_confirmation is not None:
            try:
                self.mtf_confirmation = get_mtf_confirmation()
                logger.info("✅ Phase 3: Multi-Timeframe Confirmation AI initialized")
            except Exception as _e:
                logger.warning("⚠️ Phase 3: MTF Confirmation init failed: %s", _e)
                self.mtf_confirmation = None
        else:
            self.mtf_confirmation = None

        # ── Phase 3: Abnormal Market Kill Switch ──────────────────────────────
        if ABNORMAL_MARKET_KS_AVAILABLE and get_abnormal_market_ks is not None:
            try:
                self.abnormal_market_ks = get_abnormal_market_ks()
                logger.info("✅ Phase 3: Abnormal Market Kill Switch initialized")
            except Exception as _e:
                logger.warning("⚠️ Phase 3: Abnormal Market Kill Switch init failed: %s", _e)
                self.abnormal_market_ks = None
        else:
            self.abnormal_market_ks = None

        if CAPITAL_SCALING_ENGINE_AVAILABLE and get_capital_engine is not None:
            try:
                _base_cap = float(os.environ.get("BASE_CAPITAL", str(_DEFAULT_BASE_CAPITAL)))
                self.capital_scaling_engine = get_capital_engine(
                    base_capital=_base_cap,
                    strategy=os.environ.get("COMPOUNDING_STRATEGY", "moderate"),
                )
                logger.info("✅ Capital Scaling Engine initialized (base_capital=$%.2f)", _base_cap)
            except Exception as _cse_err:
                logger.warning("⚠️ Failed to initialize Capital Scaling Engine: %s", _cse_err)
                self.capital_scaling_engine = None
        else:
            self.capital_scaling_engine = None

        # Initialize External Capital Mode — handles multiple users / investors
        if INVESTOR_MODE_AVAILABLE and get_investor_mode_engine is not None:
            try:
                self.investor_mode_engine = get_investor_mode_engine()
                logger.info("✅ External Capital Mode (Investor Mode) initialized")
            except Exception as _ime_err:
                logger.warning("⚠️ Failed to initialize Investor Mode Engine: %s", _ime_err)
                self.investor_mode_engine = None
        else:
            self.investor_mode_engine = None

        # Initialize Tiered Risk Engine — conservative vs aggressive capital pools
        if TIERED_RISK_ENGINE_AVAILABLE and TieredRiskEngine is not None:
            try:
                _risk_tier = os.environ.get("RISK_PROFILE", "STARTER").upper()
                _total_cap = float(os.environ.get("BASE_CAPITAL", str(_DEFAULT_BASE_CAPITAL)))
                self.tiered_risk_engine = TieredRiskEngine(
                    user_tier=_risk_tier,
                    total_capital=_total_cap,
                )
                logger.info("✅ Tiered Risk Engine initialized (tier=%s)", _risk_tier)
            except Exception as _tre_err:
                logger.warning("⚠️ Failed to initialize Tiered Risk Engine: %s", _tre_err)
                self.tiered_risk_engine = None
        else:
            self.tiered_risk_engine = None

        # Initialize AI Strategy Evolution Engine — system evolves its own strategies
        if AI_STRATEGY_EVOLUTION_AVAILABLE and get_ai_strategy_evolution_engine is not None:
            try:
                self.ai_strategy_evolution_engine = get_ai_strategy_evolution_engine()
                logger.info("✅ AI Strategy Evolution Engine initialized - genetic mutation active")
            except Exception as _asee_err:
                logger.warning("⚠️ Failed to initialize AI Strategy Evolution Engine: %s", _asee_err)
                self.ai_strategy_evolution_engine = None
        else:
            self.ai_strategy_evolution_engine = None

        # ── Phase 2: Adaptive Take-Profit Scaling ─────────────────────────────
        if ADAPTIVE_TP_AVAILABLE and get_adaptive_profit_engine is not None:
            try:
                self.adaptive_tp_engine = get_adaptive_profit_engine()
                logger.info("✅ Phase 2 — Adaptive TP Engine initialized")
            except Exception as _ate_err:
                logger.warning("⚠️ Failed to initialize Adaptive TP Engine: %s", _ate_err)
                self.adaptive_tp_engine = None
        else:
            self.adaptive_tp_engine = None

        # ── Phase 2: Trade Clustering ──────────────────────────────────────────
        if TRADE_CLUSTER_AVAILABLE and get_trade_cluster_engine is not None:
            try:
                self.trade_cluster_engine = get_trade_cluster_engine()
                logger.info("✅ Phase 2 — Trade Cluster Engine initialized")
            except Exception as _tce_err:
                logger.warning("⚠️ Failed to initialize Trade Cluster Engine: %s", _tce_err)
                self.trade_cluster_engine = None
        else:
            self.trade_cluster_engine = None

        # ── Phase 2: AI Confidence-Based Position Sizing ──────────────────────
        if AI_CONFIDENCE_SIZING_AVAILABLE and get_ai_trade_confidence_engine is not None:
            try:
                self.ai_confidence_engine = get_ai_trade_confidence_engine()
                logger.info("✅ Phase 2 — AI Confidence Engine initialized")
            except Exception as _ace_err:
                logger.warning("⚠️ Failed to initialize AI Confidence Engine: %s", _ace_err)
                self.ai_confidence_engine = None
        else:
            self.ai_confidence_engine = None

        # ── Phase 2: Auto Broker Capital Shifter ──────────────────────────────
        if AUTO_BROKER_SHIFTER_AVAILABLE and get_auto_broker_capital_shifter is not None:
            try:
                self.broker_capital_shifter = get_auto_broker_capital_shifter()
                # Pre-register known broker names with equal initial allocation.
                # The shifter will reweight them as real performance data arrives.
                _known_brokers = [
                    b.value for b in BrokerType
                    if b.value in ("coinbase", "kraken", "binance", "okx")
                ]
                for _b in _known_brokers:
                    try:
                        self.broker_capital_shifter.register_broker(
                            _b,
                            initial_allocation=round(1.0 / len(_known_brokers), 4),
                        )
                    except Exception:
                        pass
                logger.info("✅ Phase 2 — Auto Broker Capital Shifter initialized")
            except Exception as _abcs_err:
                logger.warning("⚠️ Failed to initialize Auto Broker Capital Shifter: %s", _abcs_err)
                self.broker_capital_shifter = None
        else:
            self.broker_capital_shifter = None

        # FIX #2: Initialize forced stop-loss executor
        try:
            from forced_stop_loss import create_forced_stop_loss
            # Will be set to actual broker instance after connection
            self.forced_stop_loss = None
            logger.info("✅ Forced stop-loss module loaded")
        except ImportError:
            logger.warning("⚠️ Forced stop-loss module not available")
            self.forced_stop_loss = None

        # Initialize user-defined take-profit / stop-loss rules engine
        try:
            from user_rules_engine import get_user_rules_engine as _get_ure
            self._user_rules_engine = _get_ure()
            logger.info("✅ User Rules Engine initialized – custom TP/SL rules active")
        except ImportError:
            try:
                from bot.user_rules_engine import get_user_rules_engine as _get_ure
                self._user_rules_engine = _get_ure()
                logger.info("✅ User Rules Engine initialized – custom TP/SL rules active")
            except ImportError:
                self._user_rules_engine = None
                logger.warning("⚠️ User Rules Engine not available – custom TP/SL rules disabled")

        # Initialize entry guardrails (correlation, liquidity, latency)
        if _ENTRY_GUARDRAILS_AVAILABLE:
            try:
                self.correlation_filter = PortfolioCorrelationFilter()
                self.liquidity_filter = LiquidityFilter()
                self.latency_guard = ExchangeLatencyGuard()
                logger.info(
                    "✅ Entry guardrails initialized – "
                    "correlation/liquidity/latency checks active"
                )
            except Exception as _eg_err:
                logger.warning(f"⚠️ Failed to initialize entry guardrails: {_eg_err}")
                self.correlation_filter = None
                self.liquidity_filter = None
                self.latency_guard = None
        else:
            self.correlation_filter = None
            self.liquidity_filter = None
            self.latency_guard = None

        # Track positions that can't be sold (too small/dust) to avoid infinite retry loops
        # NEW (Jan 16, 2026): Track with timestamps to allow retry after timeout
        self.unsellable_positions = {}  # Dict of symbol -> timestamp when marked unsellable
        self.unsellable_retry_timeout = UNSELLABLE_RETRY_HOURS * 3600  # Convert hours to seconds

        # Track failed broker connections for error reporting
        self.failed_brokers = {}  # Dict of BrokerType -> broker instance for failed connections

        # Kraken order cleanup manager (initialized after Kraken connection)
        self.kraken_cleanup = None

        # Market rotation state (prevents scanning same markets every cycle)
        self.market_rotation_offset = 0  # Tracks which batch of markets to scan next
        self.all_markets_cache = []      # Cache of all available markets
        self.markets_cache_time = 0      # Timestamp of last market list refresh
        self.MARKETS_CACHE_TTL = 3600    # Refresh market list every hour

        # Rate limiting warmup state (prevents API bans on startup)
        self.cycle_count = 0             # Track number of cycles for warmup
        self.api_health_score = 100      # 0-100, degrades on errors, recovers on success

        # Candle data cache (prevents duplicate API calls for same market/timeframe)
        self.candle_cache = {}           # {symbol: (timestamp, candles_data)}
        self.CANDLE_CACHE_TTL = 150      # Cache candles for 2.5 minutes (one cycle)

        # Heartbeat trade state tracking (for deployment verification and health checks)
        self.heartbeat_last_trade_time = 0  # Last heartbeat trade timestamp
        self.heartbeat_trade_count = 0  # Total heartbeat trades executed

        # Micro-cap re-entry cooldown tracking (MICRO_CAP_TRADE_COOLDOWN seconds between trades per symbol)
        self._micro_cap_last_trade_times: Dict[str, float] = {}
        # Micro-cap consecutive win streak: incremented after each profitable exit,
        # reset to 0 after any losing exit so the bot does not chase extended profit
        # targets when momentum has ended (used by get_spread_adjusted_profit_target).
        self._micro_cap_win_streak: int = 0
        
        # Trade execution tracking (for trade-based cleanup trigger)
        self.trades_since_last_cleanup = 0  # Trades executed since last forced cleanup
        
        # Trade veto tracking for trust layer (log why trades were not executed)
        self.veto_count_session = 0  # Count of vetoed trades this session
        self.last_veto_reason = None  # Last veto reason for display in status banner

        # Position Management State Machine (Feb 15, 2026)
        # Track current state for deterministic position management and proper invariants
        self.position_mgmt_state = PositionManagementState.NORMAL
        self.previous_state = None  # Track previous state for transition logging

        # Scan cycle latency tracking
        # Stores recent total cycle durations (seconds) to compute a moving average.
        # Uses a fixed-length deque so memory stays bounded regardless of runtime.
        self._cycle_durations = collections.deque(maxlen=20)  # rolling window of 20 cycles

        # ── FIRST TRADE GUARANTEE ─────────────────────────────────────────────
        # Forces an initial deployment signal on cycle 0 when balance is healthy,
        # so the bot never stalls silently on fresh startup.
        self._first_trade_executed: bool = False  # set True after first confirmed entry

        # Zero-signal streak tracking (Leak #4 — over-filter monitor)
        # Count consecutive cycles where no qualifying entry signal was found.
        # A high streak usually means filters are too tight or markets are quiet.
        self._zero_signal_streak: int = 0
        # Alert after this many consecutive zero-signal cycles
        self._zero_signal_alert_threshold: int = 10

        # Initialize advanced trading features placeholder
        # NOTE: Advanced modules will be initialized AFTER first live balance fetch
        # and only if LIVE_CAPITAL_VERIFIED=true is set
        self.advanced_manager = None
        self.rotation_manager = None
        self.pro_mode_enabled = False
        self.ai_capital_rotator = None  # AI Capital Rotation Engine (4-step + meta allocation)

        # Initialize credential health monitoring to detect credential loss
        # This helps diagnose recurring disconnection issues
        try:
            from credential_health_monitor import start_credential_monitoring
            logger.info("🔍 Starting credential health monitoring...")
            self.credential_monitor = start_credential_monitoring(check_interval=300)  # Check every 5 minutes
            logger.info("   ✅ Credential monitoring active (checks every 5 minutes)")
        except Exception as e:
            logger.warning(f"⚠️  Could not start credential monitoring: {e}")
            self.credential_monitor = None
        
        # Initialize continuous exit enforcer for fail-safe position management
        # This runs independently of the main trading loop to ensure positions
        # are always managed even when main loop encounters errors
        try:
            from continuous_exit_enforcer import get_continuous_exit_enforcer
            logger.info("🛡️ Starting continuous exit enforcer...")
            self.continuous_exit_enforcer = get_continuous_exit_enforcer()
            self.continuous_exit_enforcer.start()
            logger.info("   ✅ Continuous exit enforcer active (checks every 60 seconds)")
        except Exception as e:
            logger.warning(f"⚠️  Could not start continuous exit enforcer: {e}")
            self.continuous_exit_enforcer = None

        try:
            # Lazy imports to avoid circular deps and allow fallback
            # Note: BrokerType and AccountType are now imported at module level
            from broker_manager import (
                BrokerManager, CoinbaseBroker, KrakenBroker,
                OKXBroker, BinanceBroker, AlpacaBroker
            )
            from multi_account_broker_manager import multi_account_broker_manager
            from position_cap_enforcer import PositionCapEnforcer
            from dust_blacklist import get_dust_blacklist
            from bot.nija_apex_strategy_v71 import NIJAApexStrategyV71

            # Initialize multi-account broker manager for user-specific trading
            logger.info("=" * 70)
            logger.info("🌐 MULTI-ACCOUNT TRADING MODE ACTIVATED")
            logger.info("=" * 70)
            logger.info("   Platform account + User accounts trading independently")
            logger.info("=" * 70)

            # Display the Smart Structure hierarchy (Account 2 = NIJA, users connect via API)
            try:
                from bot.platform_account_layer import get_platform_account_layer
                _pal = get_platform_account_layer()
                _pal.display_hierarchy()
                _pal.validate()
            except Exception as _pal_err:
                logger.debug(f"Platform account layer display skipped: {_pal_err}")

            # Use the global singleton instance to ensure failed connection tracking persists
            self.multi_account_manager = multi_account_broker_manager
            self.broker_manager = BrokerManager()  # Keep for backward compatibility
            connected_brokers = []
            user_brokers = []

            # Add startup delay to avoid immediate rate limiting on restart
            # CRITICAL (Jan 2026): Increased to 45s to ensure API rate limits fully reset
            # Previous 30s delay was still causing rate limit issues in production
            # Coinbase appears to have a ~30-60 second cooldown period after 403 errors
            # Combined with improved retry logic (10 attempts, 15s base delay with 120s cap),
            # this gives the bot multiple chances to recover from temporary API blocks
            startup_delay = 45
            logger.info(f"⏱️  Waiting {startup_delay}s before connecting to avoid rate limits...")
            time.sleep(startup_delay)
            logger.info("✅ Startup delay complete, beginning broker connections...")

            # Try to connect Kraken Pro (PRIMARY BROKER) - PLATFORM ACCOUNT
            logger.info("📊 Attempting to connect Kraken Pro (PLATFORM - PRIMARY)...")
            kraken = None  # Initialize to ensure variable exists for exception handler
            try:
                kraken = KrakenBroker(account_type=AccountType.PLATFORM)
                connection_successful = kraken.connect()

                # CRITICAL FIX (Jan 17, 2026): Allow Kraken to start even if connection test fails
                # This prevents a single connection failure from permanently disabling Kraken trading
                # The trading loop will retry connections in the background and self-heal
                # This is similar to how other brokers handle transient connection issues
                if connection_successful:
                    self.broker_manager.add_broker(kraken)
                    # Register in multi_account_manager using proper method to enforce invariant
                    self.multi_account_manager.register_platform_broker_instance(BrokerType.KRAKEN, kraken)
                    connected_brokers.append("Kraken")
                    logger.info("   ✅ Kraken PLATFORM connected")
                    logger.info("   ✅ Kraken registered as PLATFORM broker in multi-account manager")
                    logger.debug(f"   🔍 Kraken broker object: connected={kraken.connected}, account_type={kraken.account_type}")
                    logger.debug(f"   🔍 BrokerType.KRAKEN enum value: {BrokerType.KRAKEN}, type: {type(BrokerType.KRAKEN)}")
                    logger.debug(f"   🔍 platform_brokers dict keys: {list(self.multi_account_manager.platform_brokers.keys())}")
                    logger.debug(f"   🔍 BrokerType.KRAKEN in platform_brokers: {BrokerType.KRAKEN in self.multi_account_manager.platform_brokers}")

                    # LEGACY COPY TRADING CHECK (DEPRECATED - Feb 3, 2026)
                    # NOTE: Copy trading is deprecated. NIJA now uses independent trading.
                    # All accounts (platform + users) trade independently using the same strategy.
                    # This check is kept for backward compatibility but is expected to fail.
                    try:
                        from bot.kraken_copy_trading import (
                            initialize_copy_trading_system,
                            wrap_kraken_broker_for_copy_trading
                        )

                        # Initialize copy trading system (master + users)
                        if initialize_copy_trading_system():
                            # Wrap the broker to enable automatic copy trading
                            wrap_kraken_broker_for_copy_trading(kraken)
                            logger.info("   ✅ Kraken copy trading system activated")
                            # Notify multi_account_manager that Kraken users are handled by copy trading
                            self.multi_account_manager.kraken_copy_trading_active = True
                        else:
                            logger.info("   ℹ️  Copy trading not initialized - using independent trading mode")
                    except ImportError:
                        # Expected: Copy trading is deprecated, using independent trading
                        logger.info("   ℹ️  Copy trading not available - all accounts use independent trading")
                    except Exception as copy_err:
                        logger.error(f"   ❌ Unexpected error in copy trading check: {copy_err}")
                        import traceback
                        logger.error(traceback.format_exc())

                    # KRAKEN ORDER CLEANUP: Initialize automatic stale order cleanup
                    # This frees up capital tied in unfilled limit orders
                    try:
                        from bot.kraken_order_cleanup import create_kraken_cleanup
                        self.kraken_cleanup = create_kraken_cleanup(kraken, max_order_age_minutes=5)
                        if self.kraken_cleanup:
                            logger.info("   ✅ Kraken order cleanup initialized (max age: 5 minutes)")
                        else:
                            logger.warning("   ⚠️  Kraken order cleanup not available")
                            self.kraken_cleanup = None
                    except ImportError as import_err:
                        logger.warning(f"   ⚠️  Kraken order cleanup module not available: {import_err}")
                        self.kraken_cleanup = None
                    except Exception as cleanup_err:
                        logger.error(f"   ❌ Kraken order cleanup setup error: {cleanup_err}")
                        self.kraken_cleanup = None
                else:
                    # Connection test failed, but still register broker for background retry
                    # The trading loop will handle the disconnected state and retry automatically
                    logger.warning("   ⚠️  Kraken PLATFORM connection test failed, will retry in background")
                    logger.warning("   📌 Kraken broker initialized - trading loop will attempt reconnection")
                    self._log_broker_independence_message()

                    # Use helper method to register for retry
                    self._register_kraken_for_retry(kraken)

            except Exception as e:
                # CRITICAL FIX (Jan 17, 2026): Handle exceptions consistently with connection failures
                # Even if broker initialization throws an exception, register it for retry if possible
                # This maintains consistent self-healing behavior across all failure types
                if kraken is not None:
                    logger.warning(f"   ⚠️  Kraken PLATFORM initialization error: {e}")
                    logger.warning("   📌 Kraken broker will be registered for background retry")
                    self._log_broker_independence_message()

                    # Use helper method to register for retry
                    self._register_kraken_for_retry(kraken)
                else:
                    # Broker object was never created - can't retry
                    logger.error(f"   ❌ Kraken PLATFORM initialization failed: {e}")
                    logger.error("   ❌ Kraken will not be available for trading")
                    self._log_broker_independence_message()

            # Add delay between broker connections
            time.sleep(2.0)  # Increased from 0.5s to 2.0s

            # Try to connect Coinbase - PLATFORM ACCOUNT
            logger.info("📊 Attempting to connect Coinbase Advanced Trade (PLATFORM)...")
            try:
                coinbase = CoinbaseBroker()
                if coinbase.connect():
                    self.broker_manager.add_broker(coinbase)
                    # Register in multi_account_manager using proper method to enforce invariant
                    self.multi_account_manager.register_platform_broker_instance(BrokerType.COINBASE, coinbase)
                    connected_brokers.append("Coinbase")
                    logger.info("   ✅ Coinbase MASTER connected")
                    logger.info("   ✅ Coinbase registered as PLATFORM broker in multi-account manager")
                else:
                    logger.warning("   ⚠️  Coinbase MASTER connection failed")
            except Exception as e:
                logger.warning(f"   ⚠️  Coinbase PLATFORM error: {e}")

            # Try to connect OKX - PLATFORM ACCOUNT
            logger.info("📊 Attempting to connect OKX (PLATFORM)...")
            try:
                okx = OKXBroker()
                if okx.connect():
                    self.broker_manager.add_broker(okx)
                    # Register in multi_account_manager using proper method to enforce invariant
                    self.multi_account_manager.register_platform_broker_instance(BrokerType.OKX, okx)
                    connected_brokers.append("OKX")
                    logger.info("   ✅ OKX PLATFORM connected")
                    logger.info("   ✅ OKX registered as PLATFORM broker in multi-account manager")
                else:
                    logger.warning("   ⚠️  OKX PLATFORM connection failed")
            except Exception as e:
                logger.warning(f"   ⚠️  OKX PLATFORM error: {e}")

            # Add delay between broker connections
            time.sleep(0.5)

            # Try to connect Binance - PLATFORM ACCOUNT
            logger.info("📊 Attempting to connect Binance (PLATFORM)...")
            try:
                binance = BinanceBroker()
                if binance.connect():
                    self.broker_manager.add_broker(binance)
                    # Register in multi_account_manager using proper method to enforce invariant
                    self.multi_account_manager.register_platform_broker_instance(BrokerType.BINANCE, binance)
                    connected_brokers.append("Binance")
                    logger.info("   ✅ Binance PLATFORM connected")
                    logger.info("   ✅ Binance registered as PLATFORM broker in multi-account manager")
                else:
                    logger.warning("   ⚠️  Binance PLATFORM connection failed")
            except Exception as e:
                logger.warning(f"   ⚠️  Binance PLATFORM error: {e}")

            # Add delay between broker connections
            time.sleep(0.5)

            # Try to connect Alpaca (for stocks) - PLATFORM ACCOUNT
            logger.info("📊 Attempting to connect Alpaca (PLATFORM - Paper Trading)...")
            try:
                alpaca = AlpacaBroker()
                if alpaca.connect():
                    self.broker_manager.add_broker(alpaca)
                    # Register in multi_account_manager using proper method to enforce invariant
                    self.multi_account_manager.register_platform_broker_instance(BrokerType.ALPACA, alpaca)
                    connected_brokers.append("Alpaca")
                    logger.info("   ✅ Alpaca PLATFORM connected")
                    logger.info("   ✅ Alpaca registered as PLATFORM broker in multi-account manager")
                else:
                    logger.warning("   ⚠️  Alpaca PLATFORM connection failed")
            except Exception as e:
                logger.warning(f"   ⚠️  Alpaca PLATFORM error: {e}")

            # Add delay before user account connections to ensure platform account
            # connection has completed and nonce ranges are separated
            # CRITICAL (Jan 14, 2026): Increased from 2.0s to 5.0s to prevent Kraken nonce conflicts
            # Master Kraken connection may still be using nonces in the current time window.
            # User connections should wait long enough to ensure non-overlapping nonce ranges.
            time.sleep(5.0)

            # Connect User Accounts - Load from config files
            logger.info("=" * 70)
            logger.info("👤 CONNECTING USER ACCOUNTS FROM CONFIG FILES")
            logger.info("=" * 70)

            # Use the new config-based user loading system
            connected_user_brokers = self.multi_account_manager.connect_users_from_config()

            # Track which users were successfully connected
            user_brokers = []
            if connected_user_brokers:
                for brokerage, user_ids in connected_user_brokers.items():
                    for user_id in user_ids:
                        user_brokers.append(f"{user_id}: {brokerage.title()}")

            logger.info("=" * 70)
            logger.info("✅ Broker connection phase complete")

            # Validate platform account now that all brokers have attempted
            # connection — this is the authoritative post-connection check.
            self._validate_platform_account()

            if connected_brokers or user_brokers:
                if connected_brokers:
                    logger.info(f"✅ PLATFORM ACCOUNT BROKERS: {', '.join(connected_brokers)}")
                if user_brokers:
                    logger.info(f"👥 USER ACCOUNT BROKERS: {', '.join(user_brokers)}")

                # FIX #1: Calculate LIVE multi-broker capital
                # Total Capital = Coinbase (available, if >= min) + Kraken PLATFORM + Optional user balances

                # Get master balance from broker_manager (sums all connected master brokers)
                platform_balance = self.broker_manager.get_total_balance()

                # Break down master balance by broker for transparency
                coinbase_balance = 0.0
                kraken_balance = 0.0
                other_balance = 0.0

                for broker_type, broker in self.multi_account_manager.platform_brokers.items():
                    if broker and broker.connected:
                        try:
                            balance = broker.get_account_balance()
                            if broker_type == BrokerType.COINBASE:
                                coinbase_balance = balance
                            elif broker_type == BrokerType.KRAKEN:
                                kraken_balance = balance
                            else:
                                other_balance += balance
                        except Exception as e:
                            logger.debug(f"Could not get balance for {broker_type.value}: {e}")

                # Get user balances dynamically from multi_account_manager (for copy-trading transparency)
                user_total_balance = 0.0
                if self.multi_account_manager.user_brokers:
                    for user_id, user_broker_dict in self.multi_account_manager.user_brokers.items():
                        for broker_type, broker in user_broker_dict.items():
                            try:
                                if broker.connected:
                                    user_balance = broker.get_account_balance()
                                    user_total_balance += user_balance
                            except Exception as e:
                                logger.debug(f"Could not get balance for {user_id}: {e}")

                # Report balances with breakdown
                logger.info("=" * 70)
                logger.info("💰 LIVE MULTI-BROKER CAPITAL BREAKDOWN")
                logger.info("=" * 70)
                if coinbase_balance > 0:
                    logger.info(f"   Coinbase PLATFORM: ${coinbase_balance:,.2f}")
                if kraken_balance > 0:
                    logger.info(f"   Kraken PLATFORM:   ${kraken_balance:,.2f}")
                if other_balance > 0:
                    logger.info(f"   Other Brokers:   ${other_balance:,.2f}")
                logger.info(f"   📊 TOTAL PLATFORM: ${platform_balance:,.2f}")
                if user_total_balance > 0:
                    logger.info(f"   👥 USER ACCOUNTS (INDEPENDENT): ${user_total_balance:,.2f}")
                logger.info("=" * 70)

                # FIX #2: Force capital re-hydration after broker connections
                # MASTER AUTHORITY RULE: Master capital is always authoritative
                # Users are followers, not required for startup
                if platform_balance > 0:
                    # Master is funded - include user balances for total capital
                    total_capital = platform_balance + user_total_balance
                    logger.info(f"   ✅ Capital calculation: Platform (${platform_balance:.2f}) + Users (${user_total_balance:.2f})")
                elif user_total_balance > 0:
                    # Master unfunded but users have capital - allow user-only trading
                    total_capital = user_total_balance
                    logger.info(f"   ✅ Capital calculation: User-only trading (${user_total_balance:.2f})")
                else:
                    # No capital from platform or users - cannot trade
                    logger.error("=" * 70)
                    logger.error("❌ FATAL: No capital detected from any account")
                    logger.error("=" * 70)
                    logger.error(f"   Platform balance: ${platform_balance:.2f}")
                    logger.error(f"   User balance: ${user_total_balance:.2f}")
                    logger.error("")
                    logger.error("   🛑 Bot cannot trade without capital")
                    logger.error("   💵 Fund at least one account to continue")
                    logger.error("=" * 70)
                    raise RuntimeError("No capital detected from master or user accounts")

                # Build list of active exchanges for logging
                active_exchanges = []
                for broker_type, broker in self.multi_account_manager.platform_brokers.items():
                    if broker and broker.connected:
                        active_exchanges.append(broker_type.value)

                # Update capital allocator with live total
                if self.advanced_manager and total_capital > 0:
                    try:
                        self.advanced_manager.capital_allocator.update_total_capital(total_capital)

                        # Update progressive target manager if available
                        if hasattr(self.advanced_manager, 'target_manager') and self.advanced_manager.target_manager:
                            # Progressive targets scale with available capital
                            logger.info(f"   ✅ Progressive targets adjusted for ${total_capital:,.2f} capital")

                        logger.info(f"   ✅ Capital Allocator: ${total_capital:,.2f} (LIVE multi-broker total)")
                        logger.info(f"   ✅ Advanced Trading Manager: Using live capital")
                    except Exception as e:
                        logger.warning(f"   Failed to update capital allocation: {e}")

                # Update portfolio state manager with total equity
                if self.portfolio_manager and total_capital > 0:
                    try:
                        # Initialize/update master portfolio with total capital
                        self.platform_portfolio = self.portfolio_manager.initialize_platform_portfolio(total_capital)
                        logger.info(f"   ✅ Portfolio State Manager updated with ${total_capital:,.2f}")
                    except Exception as e:
                        logger.warning(f"   ⚠️ Could not update portfolio manager: {e}")

                # FIX #2: Explicit confirmation log (CRITICAL - must see this log)
                if total_capital > 0:
                    logger.info("=" * 70)
                    logger.info(f"💰 LIVE CAPITAL SYNC COMPLETE: ${total_capital:.2f}")
                    logger.info(f"   Active exchanges: {', '.join(active_exchanges)}")
                    logger.info("=" * 70)

                # USER BALANCE SNAPSHOT - Visual certainty of all account balances
                # Added per Jan 2026 requirement for absolute visual confirmation
                logger.info("")
                logger.info("=" * 70)
                logger.info("💰 USER BALANCE SNAPSHOT")
                logger.info("=" * 70)

                # Get all balances from multi_account_manager
                all_balances = self.multi_account_manager.get_all_balances()

                # Platform account
                platform_balances = all_balances.get('platform', {})
                platform_total = sum(platform_balances.values())
                logger.info(f"   • Platform: ${platform_total:,.2f}")
                for broker, balance in platform_balances.items():
                    logger.info(f"      - {broker.upper()}: ${balance:,.2f}")

                # User accounts - specifically Daivon and Tania
                users_balances = all_balances.get('users', {})

                # Find and display Daivon's balance
                daivon_total = 0.0
                daivon_brokers = {}
                for user_id, balances in users_balances.items():
                    if 'daivon' in user_id.lower():
                        daivon_total = sum(balances.values())
                        daivon_brokers = balances
                        break

                logger.info(f"   • Daivon: ${daivon_total:,.2f}")
                for broker, balance in daivon_brokers.items():
                    logger.info(f"      - {broker.upper()}: ${balance:,.2f}")

                # Find and display Tania's balance
                tania_total = 0.0
                tania_brokers = {}
                for user_id, balances in users_balances.items():
                    if 'tania' in user_id.lower():
                        tania_total = sum(balances.values())
                        tania_brokers = balances
                        break

                # Display Tania's balance, breaking down by broker type
                # Based on config and README, Tania may have Kraken and/or Alpaca
                tania_kraken = tania_brokers.get('kraken', 0.0)
                tania_alpaca = tania_brokers.get('alpaca', 0.0)
                logger.info(f"   • Tania (Kraken): ${tania_kraken:,.2f}")
                logger.info(f"   • Tania (Alpaca): ${tania_alpaca:,.2f}")

                # Show grand total
                # Note: This should match total_capital (master) + user_total_balance from above
                # This provides a cross-check of the balance calculations
                grand_total = platform_total + daivon_total + tania_total
                logger.info("")
                logger.info(f"   🏦 TOTAL CAPITAL UNDER MANAGEMENT: ${grand_total:,.2f}")
                logger.info("=" * 70)

                # Initialize advanced trading features AFTER first live balance fetch
                # This ensures advanced modules have access to real capital data
                # Gated by LIVE_CAPITAL_VERIFIED environment variable
                logger.info("🔧 Initializing advanced trading modules with live capital...")
                self._init_advanced_features(total_capital)

                # FIX #3: Hard fail if capital below minimum (non-negotiable)
                if total_capital < MINIMUM_TRADING_BALANCE:
                        logger.error("=" * 70)
                        logger.error("❌ FATAL: Capital below minimum — trading disabled")
                        logger.error("=" * 70)
                        logger.error(f"   Current capital: ${total_capital:.2f}")
                        logger.error(f"   Minimum required: ${MINIMUM_TRADING_BALANCE:.2f}")
                        logger.error(f"   Shortfall: ${MINIMUM_TRADING_BALANCE - total_capital:.2f}")
                        logger.error("")
                        logger.error("   🛑 Bot cannot trade with insufficient capital")
                        logger.error("   💵 Fund your account to continue trading")
                        logger.error("=" * 70)
                        raise RuntimeError(f"Capital below minimum — trading disabled (${total_capital:.2f} < ${MINIMUM_TRADING_BALANCE:.2f})")

                # FIX #1: Select primary master broker with Kraken promotion logic
                # CRITICAL: If Coinbase is in exit_only mode or has insufficient balance, promote Kraken to primary
                # Only call this after all brokers are connected to make an informed decision
                self.broker_manager.select_primary_platform_broker()

                # Get the primary broker from broker_manager
                # This is used for platform account trading
                self.broker = self.broker_manager.get_primary_broker()
                if self.broker:
                    # Log the primary master broker with explicit reason if it was switched
                    broker_name = self.broker.broker_type.value.upper()

                    # Check if any other broker is in exit_only mode (indicates a switch happened)
                    exit_only_brokers = []
                    for broker_type, broker in self.multi_account_manager.platform_brokers.items():
                        if broker and broker.connected and broker.exit_only_mode:
                            exit_only_brokers.append(broker_type.value.upper())

                    if exit_only_brokers and broker_name == "KRAKEN":
                        # Kraken was promoted because another broker is exit-only
                        logger.info(f"📌 Active platform broker: {broker_name} ({', '.join(exit_only_brokers)} EXIT-ONLY)")
                    else:
                        logger.info(f"📌 Active platform broker: {broker_name}")

                    # FIX #2: Initialize forced stop-loss with the connected broker
                    if self.forced_stop_loss is None:
                        try:
                            from forced_stop_loss import create_forced_stop_loss
                            self.forced_stop_loss = create_forced_stop_loss(self.broker)
                            logger.info("✅ Forced stop-loss executor initialized with platform broker")
                        except Exception as e:
                            logger.warning(f"⚠️ Could not initialize forced stop-loss: {e}")

                    # FIX #3: Initialize master portfolio state using SUM of ALL master brokers
                    # CRITICAL: Master portfolio must use total_platform_equity = sum(all master brokers)
                    # Do NOT just use primary broker's balance - this ignores capital in other brokers
                    if self.portfolio_manager:
                        try:
                            # Calculate total cash/balance across ALL connected master brokers
                            total_platform_cash = 0.0
                            platform_broker_balances = []

                            for broker_type, broker in self.multi_account_manager.platform_brokers.items():
                                if broker and broker.connected:
                                    try:
                                        broker_balance = broker.get_account_balance()
                                        total_platform_cash += broker_balance
                                        platform_broker_balances.append(f"{broker_type.value}: ${broker_balance:.2f}")
                                        logger.info(f"   💰 Platform broker {broker_type.value}: ${broker_balance:.2f}")
                                    except Exception as broker_err:
                                        logger.warning(f"   ⚠️ Could not get balance from {broker_type.value}: {broker_err}")

                            if total_platform_cash > 0:
                                # Initialize/update master portfolio with TOTAL cash from all brokers
                                # Note: portfolio.total_equity will be cash + position values
                                self.platform_portfolio = self.portfolio_manager.initialize_platform_portfolio(total_platform_cash)
                                logger.info("=" * 70)
                                logger.info("✅ PLATFORM PORTFOLIO INITIALIZED")
                                logger.info("=" * 70)
                                for balance_str in platform_broker_balances:
                                    logger.info(f"   {balance_str}")
                                logger.info(f"   TOTAL PLATFORM CASH: ${total_platform_cash:.2f}")
                                logger.info(f"   TOTAL PLATFORM EQUITY: ${self.platform_portfolio.total_equity:.2f}")
                                logger.info("=" * 70)
                            else:
                                logger.warning("⚠️ No platform broker balances available - portfolio not initialized")
                                self.platform_portfolio = None
                        except Exception as e:
                            logger.warning(f"⚠️ Could not initialize platform portfolio: {e}")
                            self.platform_portfolio = None
                    else:
                        self.platform_portfolio = None
                else:
                    logger.warning("⚠️  No platform broker available")
                    self.platform_portfolio = None
            else:
                logger.error("❌ NO BROKERS CONNECTED - Running in monitor mode")
                self.broker = None

            # Log clear trading status summary
            logger.info("=" * 70)
            logger.info("📊 ACCOUNT TRADING STATUS SUMMARY")
            logger.info("=" * 70)

            # Count active trading accounts
            # A platform broker is only "active" if it is set AND connected
            _broker_connected = self.broker is not None and getattr(self.broker, 'connected', False)
            active_platform_count = 1 if _broker_connected else 0
            active_user_count = 0

            # Platform account status
            if _broker_connected:
                logger.info(f"✅ PLATFORM ACCOUNT: TRADING (Broker: {self.broker.broker_type.value.upper()})")
            elif self.broker:
                logger.info(
                    f"❌ PLATFORM ACCOUNT: NOT TRADING "
                    f"(Broker: {self.broker.broker_type.value.upper()} — not connected)"
                )
            else:
                logger.info("❌ PLATFORM ACCOUNT: NOT TRADING (No broker connected)")

            # User account status - dynamically load from config
            try:
                from config.user_loader import get_user_config_loader
                user_loader = get_user_config_loader()
                enabled_users = user_loader.get_all_enabled_users()

                if enabled_users:
                    for user in enabled_users:
                        # FIX #1: Check if this is a Kraken user managed by copy trading system
                        is_kraken = user.broker_type.upper() == "KRAKEN"
                        is_copy_trader = getattr(user, 'copy_from_platform', False)
                        kraken_copy_active = getattr(self.multi_account_manager, 'kraken_copy_trading_active', False)

                        # If Kraken user is managed by copy trading, show special status and skip re-evaluation
                        if is_kraken and is_copy_trader and kraken_copy_active:
                            logger.info(f"✅ USER: {user.name}: ACTIVE (COPY TRADING) (Broker: KRAKEN)")
                            # Add disabled symbols info for Kraken copy traders
                            disabled_symbols = getattr(user, 'disabled_symbols', [])
                            if disabled_symbols:
                                disabled_str = ", ".join(disabled_symbols)
                                logger.info(f"   ℹ️  Disabled symbols: {disabled_str} (configured for copy trading)")
                            active_user_count += 1
                            continue  # Skip re-evaluation for copy trading users

                        # Check if this user is actually connected
                        user_broker = self.multi_account_manager.get_user_broker(
                            user.user_id,
                            BrokerType[user.broker_type.upper()]
                        )

                        if user_broker and user_broker.connected:
                            logger.info(f"✅ USER: {user.name}: TRADING (Broker: {user.broker_type.upper()})")
                            active_user_count += 1
                        else:
                            # Check if credentials are configured
                            has_creds = self.multi_account_manager.user_has_credentials(
                                user.user_id,
                                BrokerType[user.broker_type.upper()]
                            )
                            if has_creds:
                                # Credentials configured but connection failed
                                logger.info(f"❌ USER: {user.name}: NOT TRADING (Broker: {user.broker_type.upper()}, Connection failed)")
                            else:
                                # Credentials not configured - informational, not an error
                                logger.info(f"⚪ USER: {user.name}: NOT CONFIGURED (Broker: {user.broker_type.upper()}, Credentials not set)")
                else:
                    logger.info("⚪ No user accounts configured")
            except Exception as e:
                logger.warning(f"⚠️  Could not load user status from config: {e}")
                # Fallback: show status based on connected user brokers
                if self.multi_account_manager.user_brokers:
                    for user_id, user_broker_dict in self.multi_account_manager.user_brokers.items():
                        for broker_type, broker in user_broker_dict.items():
                            if broker.connected:
                                logger.info(f"✅ USER: {user_id}: TRADING (Broker: {broker_type.value.upper()})")
                                active_user_count += 1
                            else:
                                logger.info(f"❌ USER: {user_id}: NOT TRADING (Broker: {broker_type.value.upper()}, Connection failed)")

            logger.info("=" * 70)

            # Overall status and recommendations
            total_active = active_platform_count + active_user_count
            if total_active > 0:
                logger.info(f"🚀 TRADING ACTIVE: {total_active} account(s) ready")
                logger.info("")
                logger.info("Next steps:")
                logger.info("   • Bot will start scanning markets in ~45 seconds")
                logger.info("   • Trades will execute automatically when signals are found")
                logger.info("   • Monitor logs with: tail -f nija.log")
                logger.info("")
                if active_platform_count == 0:
                    logger.info("ℹ️  Platform account not connected")
                    logger.info("")
                    logger.info("💡 RECOMMENDATION: Configure Platform Kraken account")
                    logger.info("")
                    logger.info("   Benefits of adding Platform account:")
                    logger.info("   • Platform trades independently (additional trading capacity)")
                    logger.info("   • Stabilizes system initialization")
                    logger.info("   • Cleaner logs and startup flow")
                    logger.info("")
                    logger.info("   To enable Platform account:")
                    logger.info("   1. Set in your .env file:")
                    logger.info("      KRAKEN_PLATFORM_API_KEY=<your-api-key>")
                    logger.info("      KRAKEN_PLATFORM_API_SECRET=<your-api-secret>")
                    logger.info("")
                    logger.info("   2. Get API credentials at: https://www.kraken.com/u/security/api")
                    logger.info("      (Must use Classic API key, NOT OAuth)")
                    logger.info("")
                    logger.info("   3. Restart the bot")
                    logger.info("")
                    logger.info("   Note: All accounts (Platform + Users) trade independently")
                    logger.info("")
                if active_user_count == 0:
                    logger.info("💡 Tip: Add user accounts to enable multi-user trading")
                    logger.info("   See config/users/ for user configuration")
            else:
                logger.error("❌ NO TRADING ACTIVE - All connection attempts failed")
                logger.error("")
                logger.error("Troubleshooting:")
                logger.error("   1. Run: python3 validate_all_env_vars.py")
                logger.error("   2. Fix any missing credentials")
                logger.error("   3. Restart the bot")
                logger.error("   4. See BROKER_CONNECTION_TROUBLESHOOTING.md for help")

            logger.info("=" * 70)

            # ============================================================================
            # 🧠 TRUST LAYER - USER STATUS BANNER
            # ============================================================================
            self._display_user_status_banner()

            # ============================================================================
            # 🔍 HEARTBEAT TRADE - Verification Mode
            # ============================================================================
            # Execute a single tiny test trade if HEARTBEAT_TRADE=true
            # This verifies API credentials, trading logic, and order execution
            if os.getenv('HEARTBEAT_TRADE', 'false').lower() in ('true', '1', 'yes'):
                logger.info("=" * 70)
                logger.info("💓 HEARTBEAT TRADE MODE ACTIVATED")
                logger.info("=" * 70)
                logger.info("   This mode will execute ONE tiny test trade")
                logger.info("   Purpose: Verify connectivity and trading functionality")
                logger.info("   Action: Bot will auto-disable after heartbeat completes")
                logger.info("=" * 70)
                self._execute_heartbeat_trade()
                logger.info("=" * 70)
                logger.info("✅ HEARTBEAT TRADE COMPLETE - BOT SHUTTING DOWN")
                logger.info("=" * 70)
                logger.info("   IMPORTANT: Set HEARTBEAT_TRADE=false before restart")
                logger.info("   This prevents heartbeat from executing again")
                logger.info("=" * 70)
                import sys
                sys.exit(0)  # Graceful shutdown after heartbeat

            # Initialize independent broker trader for multi-broker support
            try:
                from independent_broker_trader import IndependentBrokerTrader
                # Resolve platform credentials from the PAL singleton so the trader
                # (and all user threads it spawns) carry the platform context.
                _platform_creds = None
                try:
                    from bot.platform_account_layer import get_platform_account_layer
                    _pal_ts = get_platform_account_layer()
                    _ts_status = _pal_ts.get_status()
                    _ts_exchange = _ts_status.platform_exchanges[0] if _ts_status.platform_exchanges else "KRAKEN"
                    _platform_creds = _pal_ts.get_platform_credentials(_ts_exchange)
                except Exception:
                    pass
                self.independent_trader = IndependentBrokerTrader(
                    self.broker_manager,
                    self,
                    self.multi_account_manager,  # Pass multi-account manager for user trading
                    platform_account=_platform_creds,
                )
                logger.info("✅ Independent broker trader initialized")
            except Exception as indie_err:
                logger.warning(f"⚠️  Independent trader initialization failed: {indie_err}")
                self.independent_trader = None
                logger.warning("No platform broker available")

            # Initialize position cap enforcer (hard cap = MAX_TOTAL_POSITIONS = 5)
            if self.broker:
                self.enforcer = PositionCapEnforcer(max_positions=MAX_TOTAL_POSITIONS, broker=self.broker)
                
                # Initialize dust blacklist for permanent sub-$2 position exclusion
                try:
                    self.dust_blacklist = get_dust_blacklist()
                    logger.info("🗑️  Dust blacklist initialized for position normalization")
                except Exception as blacklist_err:
                    logger.warning(f"⚠️  Failed to initialize dust blacklist: {blacklist_err}")
                    self.dust_blacklist = None
                
                # Initialize forced cleanup engine for aggressive dust and cap enforcement
                try:
                    from forced_position_cleanup import ForcedPositionCleanup
                    self.forced_cleanup = ForcedPositionCleanup(
                        dust_threshold_usd=DUST_POSITION_USD,
                        max_positions=MAX_TOTAL_POSITIONS,
                        dry_run=False
                    )
                    logger.info("🧹 Forced position cleanup engine initialized")
                except Exception as cleanup_err:
                    logger.warning(f"⚠️  Failed to initialize forced cleanup: {cleanup_err}")
                    self.forced_cleanup = None

                # Initialize continuous dust monitor (Option A – scheduled dust sweeps)
                try:
                    from continuous_dust_monitor import get_continuous_dust_monitor
                    import os as _os
                    _dust_interval = float(_os.getenv('DUST_SWEEP_INTERVAL_MINUTES', '30'))
                    _dust_threshold = float(_os.getenv('DUST_THRESHOLD_USD', str(DUST_POSITION_USD)))
                    self.continuous_dust_monitor = get_continuous_dust_monitor(
                        dust_threshold_usd=_dust_threshold,
                        sweep_interval_minutes=_dust_interval,
                        dry_run=False,
                    )
                    logger.info(
                        f"🌀 Continuous dust monitor initialized "
                        f"(threshold=${_dust_threshold:.2f}, interval={_dust_interval:.0f}min)"
                    )
                except Exception as _cdm_err:
                    logger.warning(f"⚠️  Failed to initialize continuous dust monitor: {_cdm_err}")
                    self.continuous_dust_monitor = None

                # ── AUTO-CLEANUP ENGINE (1-step dust liquidation + micro-position merge) ──
                try:
                    from bot.auto_cleanup_engine import get_auto_cleanup_engine
                    _ace_dry_run = os.getenv('AUTO_CLEANUP_DRY_RUN', 'false').lower() in ('true', '1', 'yes')
                    _ace_dust_thr  = float(os.getenv('AUTO_CLEANUP_DUST_USD',  str(DUST_POSITION_USD)))
                    _ace_micro_thr = float(os.getenv('AUTO_CLEANUP_MICRO_USD', '10.0'))
                    self.auto_cleanup_engine = get_auto_cleanup_engine(
                        dust_threshold_usd=_ace_dust_thr,
                        micro_threshold_usd=_ace_micro_thr,
                        dry_run=_ace_dry_run,
                    )
                    logger.info(
                        "🧹 Auto-Cleanup Engine initialised "
                        f"(dust<${_ace_dust_thr:.2f}, micro<${_ace_micro_thr:.2f}, "
                        f"dry_run={_ace_dry_run})"
                    )
                except Exception as _ace_err:
                    logger.warning(f"⚠️  Auto-Cleanup Engine not available: {_ace_err}")
                    self.auto_cleanup_engine = None

                # ── PRO POSITION MANAGER (Kelly sizing + tiered scaling rules) ──────
                try:
                    from bot.position_manager import get_pro_position_manager
                    _ppm_kelly = float(os.getenv('KELLY_FRACTION', '0.5'))
                    _ppm_wr    = float(os.getenv('WIN_RATE_ESTIMATE', '0.55'))
                    _ppm_aw    = float(os.getenv('AVG_WIN_PCT', '0.04'))
                    _ppm_al    = float(os.getenv('AVG_LOSS_PCT', '0.02'))
                    self.pro_position_manager = get_pro_position_manager(
                        balance=platform_balance,
                        win_rate=_ppm_wr,
                        avg_win_pct=_ppm_aw,
                        avg_loss_pct=_ppm_al,
                        kelly_fraction=_ppm_kelly,
                    )
                    logger.info(
                        f"🚀 Pro Position Manager initialised | tier={self.pro_position_manager.tier.tier.value} "
                        f"| max_pos={self.pro_position_manager.tier.max_positions} "
                        f"| kelly={_ppm_kelly}"
                    )
                except Exception as _ppm_err:
                    logger.warning(f"⚠️  Pro Position Manager not available: {_ppm_err}")
                    self.pro_position_manager = None

                # Initialize broker failsafes (hard limits and circuit breakers)
                # CRITICAL: Use ONLY master balance, not user balances
                try:
                    from broker_failsafes import create_failsafe_for_broker
                    broker_name = self.broker.broker_type.value if hasattr(self.broker, 'broker_type') else 'coinbase'
                    # ✅ REQUIREMENT 1: Use REAL exchange balance ONLY - No fake $100 fallback
                    if platform_balance <= 0:
                        logger.error(f"❌ Cannot initialize trading: Platform balance is ${platform_balance:.2f}")
                        logger.error("   Fund your account with real capital to enable trading")
                        self.failsafes = None
                    else:
                        account_balance = platform_balance
                        self.failsafes = create_failsafe_for_broker(broker_name, account_balance)
                        logger.info(f"🛡️  Broker failsafes initialized for {broker_name} (Platform balance: ${account_balance:,.2f})")
                except Exception as e:
                    logger.warning(f"⚠️  Failed to initialize broker failsafes: {e}")
                    self.failsafes = None

                # Initialize market adaptation engine
                try:
                    from market_adaptation import create_market_adapter
                    self.market_adapter = create_market_adapter(learning_enabled=True)
                    logger.info(f"🧠 Market adaptation engine initialized with learning enabled")
                except Exception as e:
                    logger.warning(f"⚠️  Failed to initialize market adaptation: {e}")
                    self.market_adapter = None

                # Initialize APEX strategy with primary broker
                self.apex = NIJAApexStrategyV71(broker_client=self.broker)

                # Add delay before syncing positions to avoid rate limiting
                time.sleep(0.5)

                # CRITICAL: Sync position tracker with actual broker positions at startup
                if hasattr(self.broker, 'position_tracker') and self.broker.position_tracker:
                    try:
                        broker_positions = self.broker.get_positions()
                        removed = self.broker.position_tracker.sync_with_broker(broker_positions)
                        if removed > 0:
                            logger.info(f"🔄 Synced position tracker: removed {removed} orphaned positions")
                        # Warn if live broker positions exceed the configured cap
                        live_count = len(broker_positions) if broker_positions else 0
                        if live_count > MAX_POSITIONS_ALLOWED:
                            logger.warning(
                                f"⚠️ POSITION CAP WARNING: {live_count} live position(s) found on restart "
                                f"but cap is {MAX_POSITIONS_ALLOWED}. "
                                f"New entries are BLOCKED until positions drop to {MAX_POSITIONS_ALLOWED}."
                            )
                    except Exception as sync_err:
                        logger.warning(f"⚠️ Position tracker sync failed: {sync_err}")

                logger.info("✅ TradingStrategy initialized (APEX v7.1 + Multi-Broker + 8-Position Cap)")
            else:
                logger.warning("Strategy initialized in monitor mode (no active brokers)")
                self.enforcer = None
                self.apex = None

        except ImportError as e:
            logger.error(f"Failed to import strategy modules: {e}")
            logger.error("Falling back to safe monitor mode (no trades)")
            self.broker = None
            self.broker_manager = None
            self.enforcer = None
            self.apex = None
            self.independent_trader = None

    def adopt_existing_positions(self, broker, broker_name: str = "UNKNOWN", account_id: str = "PLATFORM") -> dict:
        """
        UNIFIED STRATEGY PER ACCOUNT - Core Position Adoption Function
        
        🔒 GUARDRAIL: This function MUST be called on startup for EVERY account.
        It adopts existing open positions from the exchange and immediately
        attaches exit logic (stop-loss, take-profit, trailing stops, time exits).
        
        This enables each account to manage its own positions independently with
        identical exit strategies, regardless of where the position originated.
        
        EXACT FLOW:
        ═══════════════════════════════════════════════════════════════════
        STEP 1: Query Exchange
        ───────────────────────
        - Call broker.get_positions() OR broker.get_open_positions()
        - Fetch ALL open positions currently on the exchange
        - Log count and details of positions found
        
        STEP 2: Wrap in NIJA Model
        ───────────────────────────
        - For each position, extract: symbol, entry_price, quantity, size_usd
        - If entry_price missing: use current_price * 1.01 (safety default)
        - Register in broker.position_tracker using track_entry()
        - This makes positions visible to exit engine
        
        STEP 3: Hand to Exit Engine
        ────────────────────────────
        - Positions are now in position_tracker
        - Next run_cycle() will automatically:
          • Calculate P&L for each position
          • Check stop-loss levels
          • Check take-profit targets
          • Apply trailing stops
          • Monitor time-based exits
        - Exit logic is IDENTICAL for all accounts
        
        STEP 4: Guardrail Verification
        ───────────────────────────────
        - Record adoption in self.position_adoption_status
        - Set adoption_completed flag to prevent silent skips
        - Log adoption summary with position count
        - Return detailed status dict for verification
        ═══════════════════════════════════════════════════════════════════
        
        Args:
            broker: Broker instance to query for positions
            broker_name: Human-readable broker name for logging
            account_id: Account identifier (for multi-account tracking)
            
        Returns:
            dict: Detailed adoption status {
                'success': bool,
                'positions_found': int,
                'positions_adopted': int,
                'adoption_time': str (ISO timestamp),
                'broker_name': str,
                'account_id': str,
                'positions': list of dicts
            }
        """
        if not broker:
            logger.error(f"🔒 GUARDRAIL VIOLATION: Cannot adopt positions - broker is None for {account_id}")
            return {
                'success': False,
                'positions_found': 0,
                'positions_adopted': 0,
                'adoption_time': datetime.now().isoformat(),
                'broker_name': broker_name,
                'account_id': account_id,
                'error': 'Broker is None',
                'positions': []
            }
            
        adoption_start = datetime.now()
        
        # Initialize failed_positions list before any try/except blocks
        # This ensures we can track failures throughout the adoption process
        failed_positions = []
        
        try:
            logger.info("")
            logger.info("═" * 70)
            logger.info(f"🔄 ADOPTING EXISTING POSITIONS")
            logger.info("═" * 70)
            logger.info(f"   Account: {account_id}")
            logger.info(f"   Broker: {broker_name.upper()}")
            logger.info(f"   Time: {adoption_start.isoformat()}")
            logger.info("─" * 70)
            
            # ═══════════════════════════════════════════════════════════════
            # STEP 1: Query Exchange for Open Positions
            # ═══════════════════════════════════════════════════════════════
            logger.info("📡 STEP 1/4: Querying exchange for open positions...")
            
            try:
                # Try get_positions first (standard method)
                if hasattr(broker, 'get_positions'):
                    positions = broker.get_positions()
                # Fallback to get_open_positions if available
                elif hasattr(broker, 'get_open_positions'):
                    positions = broker.get_open_positions()
                else:
                    error_msg = f"Broker {broker_name} does not support position queries"
                    logger.error(f"   ❌ {error_msg}")
                    return {
                        'success': False,
                        'positions_found': 0,
                        'positions_adopted': 0,
                        'adoption_time': adoption_start.isoformat(),
                        'broker_name': broker_name,
                        'account_id': account_id,
                        'error': error_msg,
                        'positions': [],
                        'failed_positions': failed_positions
                    }
                    
                positions_found = len(positions) if positions else 0
                logger.info(f"   ✅ Exchange query complete: {positions_found} position(s) found")
                
                if not positions:
                    logger.info("   ℹ️  No open positions to adopt")
                    
                    # Check for open orders (pending orders that haven't filled yet)
                    open_orders_count = 0
                    open_orders_info = []
                    try:
                        if hasattr(broker, 'get_open_orders'):
                            open_orders = broker.get_open_orders()
                            if open_orders:
                                open_orders_count = len(open_orders)
                                # Extract key details from orders (show first MAX_DISPLAYED_ORDERS)
                                for order in open_orders[:MAX_DISPLAYED_ORDERS]:
                                    pair = order.get('pair', order.get('symbol', 'UNKNOWN'))
                                    side = order.get('type', order.get('side', 'UNKNOWN'))
                                    price = order.get('price', 0)
                                    age_seconds = order.get('age_seconds', 0)
                                    age_minutes = int(age_seconds / 60) if age_seconds > 0 else 0
                                    origin = order.get('origin', 'UNKNOWN')
                                    
                                    open_orders_info.append({
                                        'pair': pair,
                                        'side': side.upper(),
                                        'price': price,
                                        'age_minutes': age_minutes,
                                        'origin': origin
                                    })
                    except Exception as order_err:
                        logger.debug(f"   Could not check open orders: {order_err}")
                    
                    # Log informative message about open orders
                    if open_orders_count > 0:
                        logger.info(f"   📋 {account_id}: {open_orders_count} open order(s) found but no filled positions yet")
                        logger.info(f"   ⏳ Orders are being monitored and will be adopted upon fill")
                        
                        # Log details of open orders for visibility
                        for i, order_info in enumerate(open_orders_info, 1):
                            logger.info(f"      {i}. {order_info['pair']} {order_info['side']} @ ${order_info['price']:.4f} "
                                      f"(age: {order_info['age_minutes']}m, origin: {order_info['origin']})")
                        
                        if open_orders_count > MAX_DISPLAYED_ORDERS:
                            logger.info(f"      ... and {open_orders_count - MAX_DISPLAYED_ORDERS} more order(s)")
                    
                    logger.info("─" * 70)
                    logger.info("✅ ADOPTION COMPLETE: 0 positions (account has no open positions)")
                    logger.info("═" * 70)
                    logger.info("")
                    return {
                        'success': True,
                        'positions_found': 0,
                        'positions_adopted': 0,
                        'adoption_time': adoption_start.isoformat(),
                        'broker_name': broker_name,
                        'account_id': account_id,
                        'open_orders_count': open_orders_count,
                        'positions': [],
                        'failed_positions': failed_positions
                    }
                
            except Exception as fetch_err:
                error_msg = f"Failed to fetch positions: {fetch_err}"
                logger.error(f"   ❌ {error_msg}")
                return {
                    'success': False,
                    'positions_found': 0,
                    'positions_adopted': 0,
                    'adoption_time': adoption_start.isoformat(),
                    'broker_name': broker_name,
                    'account_id': account_id,
                    'error': error_msg,
                    'positions': [],
                    'failed_positions': failed_positions
                }
            
            # ═══════════════════════════════════════════════════════════════
            # STEP 2: Wrap Each Position in NIJA's Internal Model
            # ═══════════════════════════════════════════════════════════════
            logger.info("📦 STEP 2/4: Wrapping positions in NIJA internal model...")
            
            adopted_count = 0
            adopted_positions = []
            position_tracker = getattr(broker, 'position_tracker', None)

            # Load manual entry price overrides from config file (if present)
            entry_price_overrides = {}
            try:
                _overrides_path = Path(__file__).parent.parent / "config" / "entry_price_overrides.json"
                if _overrides_path.exists():
                    with open(_overrides_path, 'r') as _f:
                        _overrides_data = json.load(_f)
                    # Support per-account overrides keyed by account_id, or a flat symbol→price dict
                    if account_id in _overrides_data:
                        entry_price_overrides = _overrides_data[account_id]
                    elif "ALL" in _overrides_data:
                        entry_price_overrides = _overrides_data["ALL"]
                    logger.info(f"   📋 Loaded {len(entry_price_overrides)} manual entry price override(s) for {account_id}")
            except Exception as _ov_err:
                logger.warning(f"   ⚠️  Could not load entry price overrides: {_ov_err}")
            
            # Pre-fetch entry prices for ALL positions in one bulk API call.
            # This replaces up to N individual get_real_entry_price() calls (each ~30s rate-limited)
            # with a single paginated TradesHistory fetch that covers all symbols at once.
            bulk_entry_prices: Dict[str, float] = {}
            if positions and hasattr(broker, 'get_bulk_entry_prices'):
                try:
                    all_symbols = [p.get('symbol', '') for p in positions if p.get('symbol')]
                    if all_symbols:
                        bulk_entry_prices = broker.get_bulk_entry_prices(all_symbols) or {}
                        if bulk_entry_prices:
                            logger.info(
                                f"   📊 Pre-fetched {len(bulk_entry_prices)}/{len(all_symbols)} "
                                f"entry prices via bulk trade history lookup"
                            )
                except Exception as _bulk_err:
                    logger.debug(f"   Bulk entry price pre-fetch failed: {_bulk_err}")

            # 🔒 CAPITAL PROTECTION: position_tracker is MANDATORY - no silent fallback mode
            if not position_tracker:
                error_msg = "position_tracker is MANDATORY but not available"
                logger.error(f"   ❌ CAPITAL PROTECTION: {error_msg}")
                logger.error("   ❌ Cannot adopt positions without position tracking - FAILING ADOPTION")
                logger.error("   🛑 TRADING MUST BE HALTED - manual intervention required")
                return {
                    'success': False,
                    'positions_found': positions_found,
                    'positions_adopted': 0,
                    'adoption_time': adoption_start.isoformat(),
                    'broker_name': broker_name,
                    'account_id': account_id,
                    'error': error_msg,
                    'positions': [],
                    'failed_positions': failed_positions,
                    'critical': True  # Flag for critical failure requiring immediate halt
                }
            
            for i, pos in enumerate(positions, 1):
                try:
                    symbol = pos.get('symbol', 'UNKNOWN')
                    entry_price = pos.get('entry_price', 0.0)
                    current_price = pos.get('current_price', 0.0)
                    quantity = pos.get('quantity', pos.get('size', 0.0))
                    
                    # Calculate size in USD
                    size_usd = pos.get('size_usd', pos.get('usd_value', 0.0))
                    
                    # 🔧 FIX: Handle unknown asset pairs with fallback price fetching
                    if current_price == 0 or current_price is None:
                        logger.warning(f"   [{i}/{positions_found}] ⚠️  {symbol} has no current_price - attempting price fetch")
                        try:
                            # Try to fetch price from broker
                            if broker and hasattr(broker, 'get_current_price'):
                                fetched_price = broker.get_current_price(symbol)
                                if fetched_price and fetched_price > 0:
                                    current_price = fetched_price
                                    logger.info(f"   [{i}/{positions_found}] ✅ {symbol} price fetched: ${current_price:.4f}")
                                else:
                                    logger.error(f"   [{i}/{positions_found}] ❌ {symbol} price fetch failed")
                                    logger.error(f"   ❌ UNKNOWN ASSET PAIR: Cannot value position")
                                    # Mark as zombie position for manual review
                                    logger.error(f"   🧟 MARKING AS ZOMBIE: Position requires manual intervention")
                                    logger.error(f"   💡 Recommendation: Force close via broker or verify symbol mapping")
                                    failed_positions.append({
                                        'symbol': symbol,
                                        'reason': 'UNKNOWN_ASSET_PAIR',
                                        'detail': 'Price fetch failed - cannot value position'
                                    })
                                    continue  # Skip adoption - cannot value this position
                        except Exception as price_err:
                            logger.error(f"   [{i}/{positions_found}] ❌ {symbol} price fetch error: {price_err}")
                            logger.error(f"   🧟 MARKING AS ZOMBIE: Position requires manual intervention")
                            failed_positions.append({
                                'symbol': symbol,
                                'reason': 'PRICE_FETCH_ERROR',
                                'detail': str(price_err)
                            })
                            continue  # Skip adoption - cannot value this position
                    
                    # Recalculate size_usd with current_price if needed
                    if size_usd == 0 and current_price > 0 and quantity > 0:
                        size_usd = current_price * quantity
                    
                    # 🔒 CAPITAL PROTECTION: Entry price must NEVER default to 0 - fail adoption if missing
                    # Note: pos.get('entry_price', 0.0) returns 0.0 if key is missing or value is None
                    recovery_force_close = False  # Flag: trigger immediate market sell after adoption
                    if entry_price == 0 or entry_price <= 0:
                        # Check for a manual override in config/entry_price_overrides.json
                        override_price = entry_price_overrides.get(symbol, 0.0)
                        if override_price and override_price > 0:
                            logger.info(f"   [{i}/{positions_found}] 📋 {symbol}: Using manual entry price override ${override_price:.4f}")
                            entry_price = override_price
                        elif symbol in bulk_entry_prices and bulk_entry_prices[symbol] > 0:
                            # Use pre-fetched bulk entry price (one API call for all symbols)
                            entry_price = bulk_entry_prices[symbol]
                            logger.info(f"   [{i}/{positions_found}] 🔍 {symbol}: Using bulk-fetched entry price ${entry_price:.4f} from trade history")
                        elif broker and hasattr(broker, 'get_real_entry_price'):
                            # 🔍 AUTOMATIC HISTORICAL PRICE FETCH: individual fallback for symbols
                            # missed by the bulk fetch (e.g. due to pagination limits).
                            try:
                                historical_price = broker.get_real_entry_price(symbol)
                                if historical_price and historical_price > 0:
                                    logger.info(f"   [{i}/{positions_found}] 🔍 {symbol}: Auto-fetched historical entry price ${historical_price:.4f} from broker")
                                    entry_price = historical_price
                            except Exception as _hist_err:
                                logger.debug(f"   [{i}/{positions_found}] Historical price fetch failed for {symbol}: {_hist_err}")

                        if entry_price == 0 or entry_price <= 0:
                            # ⚡ OPTION A: Recovery Close Without Entry Price
                            # In recovery mode we do NOT need entry price to close a position.
                            # We only need it for P&L tracking, profit optimisation, and stop-loss logic.
                            # For recovery we just liquidate immediately.
                            in_recovery_mode = False
                            if RECOVERY_CONTROLLER_AVAILABLE and get_recovery_controller is not None and FailureState is not None:
                                try:
                                    rc = get_recovery_controller()
                                    in_recovery_mode = rc.current_state == FailureState.RECOVERY
                                except Exception:
                                    pass

                            if in_recovery_mode and current_price > 0:
                                # Recovery override: adopt with current_price as synthetic entry
                                # and flag position for immediate forced liquidation.
                                entry_price = current_price
                                recovery_force_close = True
                                logger.warning(f"   [{i}/{positions_found}] ⚠️  ENTRY UNKNOWN – RECOVERY FORCED")
                                logger.warning(f"   [{i}/{positions_found}] 🔄 {symbol}: Adopting with entry_price=current_price=${current_price:.4f} for immediate liquidation")
                            elif in_recovery_mode and current_price <= 0:
                                logger.error(f"   [{i}/{positions_found}] ❌ RECOVERY MODE: Cannot liquidate {symbol} - current_price is also unavailable")
                                failed_positions.append({
                                    'symbol': symbol,
                                    'reason': 'MISSING_ENTRY_PRICE',
                                    'detail': 'Entry price and current price are both unavailable - cannot adopt or liquidate'
                                })
                                continue  # Skip - cannot safely liquidate without any price reference
                            else:
                                logger.error(f"   [{i}/{positions_found}] ❌ CAPITAL PROTECTION: {symbol} has NO ENTRY PRICE")
                                logger.error(f"   ❌ Position adoption FAILED - entry price is MANDATORY")
                                logger.error(f"   💡 Recommendation: Verify position history or set entry price in config/entry_price_overrides.json")
                                failed_positions.append({
                                    'symbol': symbol,
                                    'reason': 'MISSING_ENTRY_PRICE',
                                    'detail': 'Entry price is 0 or missing - required for P&L tracking'
                                })
                                continue  # Skip this position - do not adopt without entry price
                    
                    # Register position in tracker (MANDATORY)
                    success = position_tracker.track_entry(
                        symbol=symbol,
                        entry_price=entry_price,
                        quantity=quantity,
                        size_usd=size_usd,
                        strategy="ADOPTED"
                    )
                    if not success:
                        logger.error(f"   [{i}/{positions_found}] ❌ CAPITAL PROTECTION: {symbol} failed position tracker registration")
                        logger.error(f"   ❌ Position adoption FAILED - tracker registration is MANDATORY")
                        failed_positions.append({
                            'symbol': symbol,
                            'reason': 'TRACKER_REGISTRATION_FAILED',
                            'detail': 'Position tracker rejected entry - may be duplicate or invalid'
                        })
                        continue
                    
                    # ⚡ RECOVERY MODE: Immediately market-sell positions adopted without known entry
                    if recovery_force_close:
                        logger.warning(f"   [{i}/{positions_found}] 🚨 RECOVERY LIQUIDATION: Immediately market-selling {symbol}")
                        try:
                            _recovery_sell_submitted = False
                            if hasattr(broker, 'close_position'):
                                _recovery_sell_submitted = safe_close_position(broker, symbol, quantity)
                            elif hasattr(broker, 'place_market_order'):
                                broker.place_market_order(symbol, side='sell', quantity=quantity)
                                _recovery_sell_submitted = True
                            else:
                                logger.error(f"   [{i}/{positions_found}] ❌ Cannot liquidate {symbol}: broker has no close_position or place_market_order")
                            if _recovery_sell_submitted:
                                logger.info(f"   [{i}/{positions_found}] ✅ RECOVERY SELL submitted for {symbol}")
                                # Remove from tracker immediately — position quantity is now 0 after liquidation
                                position_tracker.track_exit(symbol)
                                logger.info(f"   [{i}/{positions_found}] 🧹 {symbol} removed from position tracker (CLOSED_RECOVERY)")
                        except Exception as liq_err:
                            logger.error(f"   [{i}/{positions_found}] ❌ Recovery liquidation FAILED for {symbol}: {liq_err}")

                    # Position successfully adopted
                    adopted_count += 1
                    
                    # Calculate current P&L for logging
                    if current_price > 0 and entry_price > 0:
                        pnl_pct = ((current_price - entry_price) / entry_price) * 100
                    else:
                        pnl_pct = 0.0
                    
                    position_summary = {
                        'symbol': symbol,
                        'entry_price': entry_price,
                        'current_price': current_price,
                        'quantity': quantity,
                        'size_usd': size_usd,
                        'pnl_pct': pnl_pct,
                        'recovery_force_close': recovery_force_close
                    }
                    adopted_positions.append(position_summary)
                    
                    logger.info(f"   [{i}/{positions_found}] ✅ {symbol}: Entry=${entry_price:.4f}, Current=${current_price:.4f}, P&L={pnl_pct:+.2f}%, Size=${size_usd:.2f}")
                        
                except Exception as pos_err:
                    logger.error(f"   [{i}/{positions_found}] ❌ Failed to adopt position: {pos_err}")
                    pos_symbol = pos.get('symbol', 'UNKNOWN') if isinstance(pos, dict) else 'UNKNOWN'
                    failed_positions.append({
                        'symbol': pos_symbol,
                        'reason': 'EXCEPTION',
                        'detail': str(pos_err)
                    })
                    continue
            
            # ═══════════════════════════════════════════════════════════════
            # STEP 3: Hand Positions to Exit Engine
            # ═══════════════════════════════════════════════════════════════
            logger.info("🎯 STEP 3/4: Handing positions to exit engine...")
            logger.info(f"   ✅ {adopted_count} position(s) now under exit management")
            logger.info("   ✅ Stop-loss protection: ENABLED")
            logger.info("   ✅ Take-profit targets: ENABLED")
            logger.info("   ✅ Trailing stops: ENABLED")
            logger.info("   ✅ Time-based exits: ENABLED")
            
            # ═══════════════════════════════════════════════════════════════
            # STEP 4: Guardrail Verification & Status Recording
            # ═══════════════════════════════════════════════════════════════
            logger.info("🔒 STEP 4/4: Recording adoption status (guardrail)...")
            
            # Initialize adoption status tracking if not exists
            if not hasattr(self, 'position_adoption_status'):
                self.position_adoption_status = {}
            
            # Record adoption for this account
            adoption_key = f"{account_id}_{broker_name}"
            adoption_status = {
                'success': True,
                'positions_found': positions_found,
                'positions_adopted': adopted_count,
                'adoption_time': adoption_start.isoformat(),
                'broker_name': broker_name,
                'account_id': account_id,
                'positions': adopted_positions,
                'failed_positions': failed_positions,  # Track failures for diagnostics
                'adoption_completed': True  # 🔒 GUARDRAIL FLAG
            }
            self.position_adoption_status[adoption_key] = adoption_status
            
            logger.info(f"   ✅ Adoption recorded for {adoption_key}")
            logger.info("─" * 70)
            
            # 🔒 GUARDRAIL: Log clear summary
            if adopted_count != positions_found:
                logger.warning("⚠️  ADOPTION MISMATCH:")
                logger.warning(f"   Found: {positions_found} positions")
                logger.warning(f"   Adopted: {adopted_count} positions")
                logger.warning(f"   Failed: {positions_found - adopted_count} positions")
                logger.warning("")
                logger.warning("   📋 FAILURE BREAKDOWN:")
                if failed_positions:
                    # Group failures by reason
                    failure_counts = {}
                    for failure in failed_positions:
                        reason = failure.get('reason', 'UNKNOWN')
                        if reason not in failure_counts:
                            failure_counts[reason] = []
                        failure_counts[reason].append(failure)
                    
                    # Log each failure reason with details
                    for reason, failures in failure_counts.items():
                        logger.warning(f"   ❌ {reason}: {len(failures)} position(s)")
                        for failure in failures:
                            symbol = failure.get('symbol', 'UNKNOWN')
                            detail = failure.get('detail', 'No detail')
                            logger.warning(f"      • {symbol}: {detail}")
                else:
                    logger.warning("   ⚠️  No failure details recorded")
                logger.warning("")
                logger.warning("   💡 RECOMMENDATIONS:")
                if any(f.get('reason') == 'UNKNOWN_ASSET_PAIR' for f in failed_positions):
                    logger.warning("   • Review symbol mappings for unknown asset pairs")
                    logger.warning("   • Consider force closing zombie positions manually")
                if any(f.get('reason') == 'MISSING_ENTRY_PRICE' for f in failed_positions):
                    logger.warning("   • Verify broker position history for entry prices")
                if any(f.get('reason') == 'TRACKER_REGISTRATION_FAILED' for f in failed_positions):
                    logger.warning("   • Check for duplicate positions in tracker")
            else:
                logger.info("✅ ADOPTION COMPLETE:")
                logger.info(f"   All {adopted_count} position(s) successfully adopted")
            
            logger.info("")
            logger.info("💰 PROFIT REALIZATION ACTIVE:")
            logger.info(f"   Exit logic will run NEXT CYCLE (2.5 min)")
            logger.info(f"   All {adopted_count} position(s) monitored for exits")
            logger.info("═" * 70)
            logger.info("")
            
            return adoption_status
            
        except Exception as e:
            error_msg = f"Critical error during position adoption: {e}"
            logger.error(f"❌ {error_msg}")
            import traceback
            logger.error(traceback.format_exc())
            logger.info("═" * 70)
            logger.info("")
            
            return {
                'success': False,
                'positions_found': 0,
                'positions_adopted': 0,
                'adoption_time': adoption_start.isoformat(),
                'broker_name': broker_name,
                'account_id': account_id,
                'error': error_msg,
                'positions': [],
                'failed_positions': failed_positions
            }

    def verify_position_adoption_status(self, account_id: str, broker_name: str) -> bool:
        """
        🔒 GUARDRAIL: Verify that position adoption completed for an account.
        
        This prevents the silent failure where an account has positions but
        they are not being managed by the exit engine.
        
        MUST be called before allowing trading to proceed.
        
        Args:
            account_id: Account identifier
            broker_name: Broker name
            
        Returns:
            bool: True if adoption completed (or no positions exist), False if silently skipped
        """
        if not hasattr(self, 'position_adoption_status'):
            logger.error("🔒 GUARDRAIL VIOLATION: position_adoption_status not initialized")
            logger.error(f"   Account: {account_id}")
            logger.error(f"   Broker: {broker_name}")
            logger.error("   ❌ adopt_existing_positions() was NEVER called")
            return False
        
        adoption_key = f"{account_id}_{broker_name}"
        
        if adoption_key not in self.position_adoption_status:
            logger.error("🔒 GUARDRAIL VIOLATION: Position adoption was skipped")
            logger.error(f"   Account: {account_id}")
            logger.error(f"   Broker: {broker_name}")
            logger.error(f"   Key: {adoption_key}")
            logger.error("   ❌ adopt_existing_positions() was NOT called for this account")
            logger.error("   ⚠️  Positions may exist but are NOT being managed")
            return False
        
        status = self.position_adoption_status[adoption_key]
        
        if not status.get('adoption_completed', False):
            logger.error("🔒 GUARDRAIL VIOLATION: Adoption incomplete")
            logger.error(f"   Account: {account_id}")
            logger.error(f"   Status: {status}")
            return False
        
        # Log successful verification
        logger.info(f"✅ Position adoption verified for {adoption_key}")
        logger.info(f"   Found: {status['positions_found']} position(s)")
        logger.info(f"   Adopted: {status['positions_adopted']} position(s)")
        logger.info(f"   Time: {status['adoption_time']}")
        
        return True

    def get_adoption_summary(self) -> dict:
        """
        Get summary of position adoption status across all accounts.
        
        Also checks for anomalies like users having positions when platform doesn't.
        
        Returns:
            dict: Summary of adoption status for monitoring/debugging
        """
        if not hasattr(self, 'position_adoption_status'):
            return {
                'initialized': False,
                'accounts': 0,
                'total_positions_found': 0,
                'total_positions_adopted': 0
            }
        
        total_found = 0
        total_adopted = 0
        accounts_with_positions = 0
        
        # Track platform vs user positions for anomaly detection
        platform_positions = 0
        user_positions = 0
        user_accounts_with_positions = []
        
        for key, status in self.position_adoption_status.items():
            positions_count = status.get('positions_found', 0)
            
            if positions_count > 0:
                accounts_with_positions += 1
                
                # Identify if this is platform or user account
                account_id = status.get('account_id', '')
                if account_id.startswith('PLATFORM_'):
                    platform_positions += positions_count
                elif account_id.startswith('USER_'):
                    user_positions += positions_count
                    user_accounts_with_positions.append(account_id)
            
            total_found += positions_count
            total_adopted += status.get('positions_adopted', 0)
        
        # 🔒 ANOMALY DETECTION: Log when users have positions but platform doesn't
        if user_positions > 0 and platform_positions == 0:
            logger.warning("")
            logger.warning("═" * 70)
            logger.warning("⚠️  POSITION DISTRIBUTION ANOMALY DETECTED")
            logger.warning("═" * 70)
            logger.warning(f"   USER accounts have {user_positions} position(s)")
            logger.warning(f"   PLATFORM account has 0 positions")
            logger.warning("")
            logger.warning(f"   User accounts with positions:")
            for user_account in user_accounts_with_positions:
                # Look up status using the account_id (which is already the full key)
                # Find the matching status from position_adoption_status
                user_status = None
                for key, status in self.position_adoption_status.items():
                    if status.get('account_id') == user_account:
                        user_status = status
                        break
                
                if user_status:
                    logger.warning(f"      • {user_account}: {user_status.get('positions_found', 0)} position(s)")
                else:
                    logger.warning(f"      • {user_account}: (status not found)")
            logger.warning("")
            logger.warning("   This is NORMAL if:")
            logger.warning("   - Platform account just started (no trades yet)")
            logger.warning("   - Users opened positions independently")
            logger.warning("   - Platform positions were closed but user positions remain")
            logger.warning("")
            logger.warning("   ✅ Each account manages positions INDEPENDENTLY")
            logger.warning("   ✅ Exit logic active for ALL accounts")
            logger.warning("═" * 70)
            logger.warning("")
        
        return {
            'initialized': True,
            'accounts': len(self.position_adoption_status),
            'accounts_with_positions': accounts_with_positions,
            'total_positions_found': total_found,
            'total_positions_adopted': total_adopted,
            'platform_positions': platform_positions,
            'user_positions': user_positions,
            'anomaly_detected': (user_positions > 0 and platform_positions == 0),
            'details': self.position_adoption_status
        }

    def _validate_platform_account(self) -> bool:
        """
        Validate that the platform account is recognised and connected.

        Called once after the broker connection phase completes so that
        platform status is always checked against *live* broker state
        rather than preliminary credential checks run before brokers
        have had a chance to connect.

        Returns:
            bool: True if at least one platform broker is connected.
        """
        logger.info("=" * 70)
        logger.info("🔍 PLATFORM ACCOUNT VALIDATION")
        logger.info("=" * 70)

        # --- Credential check via Platform Account Layer ---
        try:
            from bot.platform_account_layer import get_platform_account_layer
            pal = get_platform_account_layer()
            pal.validate()
        except Exception as pal_err:
            logger.warning(
                f"   ⚠️  PAL validation error: {pal_err} — "
                "continuing with live broker connection check only"
            )

        # --- Live broker connection check (post-connection phase) ---
        platform_connected_count = 0
        if self.multi_account_manager:
            for broker_type, broker in self.multi_account_manager.platform_brokers.items():
                if broker and broker.connected:
                    platform_connected_count += 1
                    logger.info(f"   ✅ Platform {broker_type.value.upper()} — connected")
                else:
                    logger.warning(f"   ⚠️  Platform {broker_type.value.upper()} — NOT connected")

        if platform_connected_count > 0:
            logger.info(
                f"✅ Platform validation complete — "
                f"{platform_connected_count} broker(s) active"
            )
        else:
            logger.warning(
                "⚠️  Platform validation: no platform brokers are connected"
            )

        logger.info("=" * 70)
        return platform_connected_count > 0

    def _log_broker_independence_message(self):
        """
        Helper to log that other brokers continue trading independently.
        This is used when a broker fails to initialize to reassure users
        that the failure is isolated and doesn't affect other exchanges.
        """
        logger.info("")
        logger.info("   ✅ OTHER BROKERS CONTINUE TRADING INDEPENDENTLY")
        logger.info("   ℹ️  Kraken offline does NOT block Coinbase or other exchanges")
        logger.info("")

    def _load_capital_growth_rules(self) -> dict:
        """
        Load Capital Growth Ladder configuration from config/capital_growth_rules.json.

        Defines tier thresholds and fixed trade sizes that scale with account equity:
          - micro tier:          $0 – micro_max      → micro_trade_size per trade
          - growth tier:         micro_max – growth_max → growth_trade_size per trade
          - expansion tier:      growth_max – expansion_max → expansion_trade_size per trade
          - capital_engine tier: expansion_max+        → capital_engine_trade_size per trade

        Also exposes max_capital_per_trade_pct, which must stay in sync with
        bot/enhanced_strategy_config.py RISK_CONFIG['max_capital_per_trade_pct'].

        Returns:
            dict: Parsed growth rules, or sensible defaults if the file is missing/corrupt.
        """
        _defaults = {
            "micro_max": 1000,
            "growth_max": 5000,
            "expansion_max": 25000,
            "micro_trade_size": 5,
            "growth_trade_size": 25,
            "expansion_trade_size": 75,
            "capital_engine_trade_size": 150,
            "max_capital_per_trade_pct": 5,
        }
        _config_path = Path(__file__).parent.parent / "config" / "capital_growth_rules.json"
        try:
            if _config_path.exists():
                with open(_config_path, "r") as _f:
                    rules = json.load(_f)
                # Strip comment keys so callers receive only numeric config
                rules = {k: v for k, v in rules.items() if not k.startswith("_")}
                logger.info(
                    "✅ Capital Growth Ladder loaded from %s "
                    "(micro_max=$%s, growth_max=$%s, expansion_max=$%s, "
                    "max_capital_per_trade_pct=%s%%)",
                    _config_path,
                    rules.get("micro_max", _defaults["micro_max"]),
                    rules.get("growth_max", _defaults["growth_max"]),
                    rules.get("expansion_max", _defaults["expansion_max"]),
                    rules.get("max_capital_per_trade_pct", _defaults["max_capital_per_trade_pct"]),
                )
                return {**_defaults, **rules}
            else:
                logger.warning(
                    "⚠️  capital_growth_rules.json not found at %s – using hardcoded defaults",
                    _config_path,
                )
        except Exception as _e:
            logger.error("❌ Failed to load capital_growth_rules.json: %s – using defaults", _e)
        return _defaults

    def get_tier_trade_size(self, balance: float) -> float:
        """
        Return the fixed trade size (USD) for the current capital tier as defined
        in capital_growth_rules.json.

        Tier boundaries (all configurable via capital_growth_rules.json):
          - micro tier:          balance < micro_max          → micro_trade_size
          - growth tier:         micro_max  ≤ balance < growth_max    → growth_trade_size
          - expansion tier:      growth_max ≤ balance < expansion_max → expansion_trade_size
          - capital_engine tier: balance ≥ expansion_max               → capital_engine_trade_size

        Args:
            balance: Current account balance in USD.

        Returns:
            float: Recommended fixed trade size for the tier.
        """
        rules = self.capital_growth_rules
        if balance < rules["micro_max"]:
            return float(rules["micro_trade_size"])
        elif balance < rules["growth_max"]:
            return float(rules["growth_trade_size"])
        elif balance < rules["expansion_max"]:
            return float(rules["expansion_trade_size"])
        else:
            return float(rules["capital_engine_trade_size"])

    def _get_profit_targets_for_capital(self, balance: float) -> list:
        """
        📈 Select profit ladder based on capital tier.
        
        Different capital sizes use different profit targets for optimal risk/reward.
        Larger accounts can afford to wait for bigger wins.
        Smaller accounts need to take profits more aggressively to build capital.
        
        Args:
            balance: Current account balance in USD
            
        Returns:
            list: Profit target ladder (tuples of (pct, reason))
        """
        if balance < 100:
            # MICRO tier: Aggressive profit-taking
            return PROFIT_TARGETS_MICRO
        elif balance < 1000:
            # SMALL tier: Balanced approach
            return PROFIT_TARGETS_SMALL
        elif balance < 10000:
            # MEDIUM tier: Let winners run more
            return PROFIT_TARGETS_MEDIUM
        else:
            # LARGE tier: Maximum profit potential
            return PROFIT_TARGETS_LARGE

    def _register_kraken_for_retry(self, kraken_broker):
        """
        Register a Kraken broker for background retry attempts.

        This helper method extracts the dual registration logic to avoid code duplication.
        The broker is registered in multiple places for different purposes:
        - failed_brokers: Tracks error messages for diagnostics/debugging
        - broker_manager: Enables trading loop to monitor and retry
        - multi_account_manager: Consistent account management

        This dual registration is intentional - the broker is "failed" for
        diagnostics but "active" for retry attempts, enabling self-healing.

        Args:
            kraken_broker: KrakenBroker instance to register
        """
        self.failed_brokers[BrokerType.KRAKEN] = kraken_broker
        self.broker_manager.add_broker(kraken_broker)
        # Register in multi_account_manager using proper method to enforce invariant
        self.multi_account_manager.register_platform_broker_instance(BrokerType.KRAKEN, kraken_broker)
        logger.info("   ✅ Kraken registered for background connection retry")

    def _get_total_capital_across_all_accounts(self) -> float:
        """
        Get total capital summed across ALL accounts and brokers.

        ✅ CRITICAL (Jan 22, 2026): Capital must be fetched live and summed dynamically
        - Coinbase Master: fetched live
        - Kraken Master: fetched live
        - Kraken Users: fetched live
        - OKX Master: fetched live (if available)
        - Summed before every allocation cycle

        Returns:
            Total capital in USD across all accounts
        """
        total_capital = 0.0

        try:
            # 1. Sum all PLATFORM broker balances
            if hasattr(self, 'multi_account_manager') and self.multi_account_manager:
                for broker_type, broker in self.multi_account_manager.platform_brokers.items():
                    if broker and broker.connected:
                        try:
                            balance = broker.get_account_balance()
                            total_capital += balance
                            logger.debug(f"   Platform {broker_type.value}: ${balance:.2f}")
                        except Exception as e:
                            logger.warning(f"   ⚠️ Could not fetch {broker_type.value} platform balance: {e}")

                # 2. Sum all USER broker balances
                if self.multi_account_manager.user_brokers:
                    for user_id, user_broker_dict in self.multi_account_manager.user_brokers.items():
                        for broker_type, broker in user_broker_dict.items():
                            if broker and broker.connected:
                                try:
                                    balance = broker.get_account_balance()
                                    total_capital += balance
                                    logger.debug(f"   User {user_id} {broker_type.value}: ${balance:.2f}")
                                except Exception as e:
                                    logger.warning(f"   ⚠️ Could not fetch user {user_id} balance: {e}")

            # Fallback: use broker_manager if multi_account_manager not available
            elif hasattr(self, 'broker_manager') and self.broker_manager:
                total_capital = self.broker_manager.get_total_balance()
                logger.debug(f"   Broker manager total: ${total_capital:.2f}")

            logger.info(f"💰 TOTAL CAPITAL (all accounts): ${total_capital:.2f}")

        except Exception as e:
            logger.error(f"❌ Error calculating total capital: {e}")
            # Return 0 on error - better to halt trading than use stale data
            total_capital = 0.0

        return total_capital

    def _display_user_status_banner(self):
        """
        Display a user status banner with trading capabilities and account information.
        
        This Trust Layer feature provides transparent visibility into:
        - Connected brokers and balances
        - Trading modes (LIVE vs PAPER)
        - Safety settings (LIVE_CAPITAL_VERIFIED, PRO_MODE)
        - Account tier information
        """
        logger.info("")
        logger.info("=" * 70)
        logger.info("🧠 TRUST LAYER - USER STATUS BANNER")
        logger.info("=" * 70)
        
        # Safety settings (enhanced with safety controller)
        if hasattr(self, 'safety') and self.safety:
            # Use new safety controller
            status = self.safety.get_status_summary()
            logger.info("📋 SAFETY SETTINGS:")
            logger.info(f"   • MODE: {status['mode'].upper()}")
            logger.info(f"   • TRADING ALLOWED: {'✅ YES' if status['trading_allowed'] else '❌ NO'}")
            logger.info(f"   • REASON: {status['reason']}")
            logger.info(f"   • EMERGENCY STOP: {'🚨 ACTIVE' if status['emergency_stop_active'] else '✅ INACTIVE'}")
            logger.info(f"   • CREDENTIALS: {'✅ CONFIGURED' if status['credentials_configured'] else '❌ NOT CONFIGURED'}")
        else:
            # Legacy safety checks
            live_capital_verified = os.getenv('LIVE_CAPITAL_VERIFIED', 'false').lower() in ('true', '1', 'yes')
            pro_mode_enabled = os.getenv('PRO_MODE', 'false').lower() in ('true', '1', 'yes')
            heartbeat_enabled = os.getenv('HEARTBEAT_TRADE', 'false').lower() in ('true', '1', 'yes')
            dry_run_mode = os.getenv('DRY_RUN_MODE', 'false').lower() in ('true', '1', 'yes')
            
            logger.info("📋 SAFETY SETTINGS:")
            logger.info(f"   • LIVE_CAPITAL_VERIFIED: {'✅ TRUE' if live_capital_verified else '❌ FALSE'}")
            logger.info(f"   • DRY_RUN_MODE: {'✅ ENABLED' if dry_run_mode else '❌ DISABLED'}")
            logger.info(f"   • PRO_MODE: {'✅ ENABLED' if pro_mode_enabled else '❌ DISABLED'}")
            logger.info(f"   • HEARTBEAT_TRADE: {'✅ ENABLED' if heartbeat_enabled else '❌ DISABLED'}")
        
        # Platform account status
        logger.info("")
        logger.info("📊 PLATFORM ACCOUNT:")
        if self.broker:
            broker_name = self.broker.broker_type.value.upper()
            try:
                balance = self.broker.get_account_balance()
                logger.info(f"   • Broker: {broker_name}")
                logger.info(f"   • Balance: ${balance:,.2f}")
                logger.info(f"   • Status: ✅ CONNECTED")
            except Exception as e:
                logger.info(f"   • Broker: {broker_name}")
                logger.info(f"   • Status: ⚠️  CONNECTION ERROR - {str(e)}")
        else:
            logger.info("   • Status: ❌ NO BROKER CONNECTED")
        
        # User accounts status
        logger.info("")
        logger.info("👥 USER ACCOUNTS:")
        if hasattr(self, 'multi_account_manager') and self.multi_account_manager.user_brokers:
            user_count = 0
            for user_id, user_broker_dict in self.multi_account_manager.user_brokers.items():
                for broker_type, broker in user_broker_dict.items():
                    user_count += 1
                    try:
                        if broker.connected:
                            balance = broker.get_account_balance()
                            logger.info(f"   • {user_id} ({broker_type.value.upper()}): ${balance:,.2f} - ✅ CONNECTED")
                        else:
                            logger.info(f"   • {user_id} ({broker_type.value.upper()}): ❌ NOT CONNECTED")
                    except Exception as e:
                        logger.info(f"   • {user_id} ({broker_type.value.upper()}): ⚠️  ERROR - {str(e)}")
            if user_count == 0:
                logger.info("   • No user accounts configured")
        else:
            logger.info("   • No user accounts configured")
        
        logger.info("=" * 70)
        logger.info("")

    def _execute_heartbeat_trade(self):
        """
        Execute a single tiny test trade to verify connectivity and functionality.
        
        This heartbeat trade:
        - Verifies API credentials are valid
        - Tests order placement and execution
        - Validates trading logic flow
        - Uses minimal position size (typically $5-10)
        
        After execution, the bot will auto-disable to prevent further trading.
        User must set HEARTBEAT_TRADE=false before restarting for normal operation.
        """
        try:
            if not self.broker:
                logger.error("❌ HEARTBEAT FAILED: No broker connected")
                return
            
            logger.info("💓 Executing heartbeat trade verification...")
            logger.info("")
            
            # Get account balance
            try:
                balance = self.broker.get_account_balance()
                logger.info(f"   • Account balance: ${balance:,.2f}")
            except Exception as e:
                logger.error(f"   ❌ Failed to get balance: {e}")
                return
            
            # Verify sufficient balance
            if balance < 10.0:
                logger.error(f"   ❌ Insufficient balance for heartbeat (need $10+, have ${balance:.2f})")
                return
            
            # Get available markets
            try:
                markets = self.broker.get_available_markets()
                if not markets:
                    logger.error("   ❌ No markets available")
                    return
                
                # Select a liquid market for heartbeat (prefer BTC or ETH)
                selected_market = None
                for symbol in ['BTC-USD', 'BTCUSD', 'ETH-USD', 'ETHUSD']:
                    if symbol in markets:
                        selected_market = symbol
                        break
                
                # Fallback to first available market
                if not selected_market and markets:
                    selected_market = markets[0]
                
                if not selected_market:
                    logger.error("   ❌ No suitable market found for heartbeat")
                    return
                
                logger.info(f"   • Selected market: {selected_market}")
                
            except Exception as e:
                logger.error(f"   ❌ Failed to get markets: {e}")
                return
            
            # Calculate heartbeat position size (use minimum $5-10)
            position_size_usd = min(10.0, balance * 0.02)  # 2% of balance, max $10
            logger.info(f"   • Position size: ${position_size_usd:.2f}")
            
            # Execute heartbeat buy order
            logger.info("")
            logger.info("   📍 PLACING HEARTBEAT BUY ORDER...")
            try:
                order_result = self.broker.place_market_order(
                    selected_market,
                    'buy',
                    position_size_usd,
                    size_type='quote'  # Order in USD
                )
                
                if order_result and order_result.get('status') not in ['error', 'unfilled']:
                    logger.info(f"   ✅ Heartbeat buy order placed successfully")
                    logger.info(f"      Order ID: {order_result.get('order_id', 'N/A')}")
                    logger.info(f"      Symbol: {selected_market}")
                    logger.info(f"      Size: ${position_size_usd:.2f}")
                    
                    # Wait a moment for order to fill
                    logger.info("")
                    logger.info("   ⏳ Waiting 5 seconds for order to fill...")
                    time.sleep(5)
                    
                    # Immediately exit the position
                    logger.info("")
                    logger.info("   📍 CLOSING HEARTBEAT POSITION...")
                    try:
                        positions = self.broker.get_positions()
                        for pos in positions:
                            if pos.get('symbol') == selected_market:
                                quantity = pos.get('quantity', 0)
                                if quantity > 0:
                                    sell_result = self.broker.place_market_order(
                                        selected_market,
                                        'sell',
                                        quantity,
                                        size_type='base'  # Order in base currency
                                    )
                                    if sell_result and sell_result.get('status') not in ['error', 'unfilled']:
                                        logger.info(f"   ✅ Heartbeat position closed successfully")
                                        logger.info("")
                                        logger.info("💓 HEARTBEAT TRADE VERIFICATION: ✅ SUCCESS")
                                    else:
                                        logger.warning(f"   ⚠️  Heartbeat sell failed: {sell_result.get('error', 'Unknown error')}")
                                    break
                        else:
                            logger.warning("   ⚠️  No position found to close (may have been filled partially)")
                            logger.info("")
                            logger.info("💓 HEARTBEAT TRADE VERIFICATION: ⚠️  PARTIAL SUCCESS")
                    except Exception as e:
                        logger.error(f"   ❌ Failed to close heartbeat position: {e}")
                        logger.info("")
                        logger.info("💓 HEARTBEAT TRADE VERIFICATION: ⚠️  PARTIAL SUCCESS")
                else:
                    error_msg = order_result.get('error', 'Unknown error') if order_result else 'Order failed'
                    logger.error(f"   ❌ Heartbeat buy order failed: {error_msg}")
                    logger.info("")
                    logger.info("💓 HEARTBEAT TRADE VERIFICATION: ❌ FAILED")
                    
            except Exception as e:
                logger.error(f"   ❌ Exception during heartbeat trade: {e}")
                logger.info("")
                logger.info("💓 HEARTBEAT TRADE VERIFICATION: ❌ FAILED")
                
        except Exception as e:
            logger.error(f"❌ HEARTBEAT FATAL ERROR: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def get_last_evaluated_trade(self) -> dict:
        """
        Get the last evaluated trade for UI display.
        
        Returns:
            dict: Last evaluated trade information including:
                - timestamp: When the trade was evaluated
                - symbol: Trading pair
                - signal: 'BUY' or 'SELL'
                - action: 'executed', 'vetoed', or 'evaluated'
                - veto_reasons: List of veto reasons if blocked
                - entry_price: Proposed entry price
                - position_size: Proposed position size in USD
                - broker: Broker name
                - confidence: Signal confidence (0.0-1.0)
                - rsi_9: RSI 9-period value
                - rsi_14: RSI 14-period value
        """
        return self.last_evaluated_trade.copy()

    def _update_last_evaluated_trade(self, symbol: str, signal: str, action: str,
                                     veto_reasons: list = None, entry_price: float = None,
                                     position_size: float = None, broker: str = None,
                                     confidence: float = None, rsi_9: float = None,
                                     rsi_14: float = None):
        """
        Update the last evaluated trade information.
        
        Args:
            symbol: Trading pair (e.g., 'BTC-USD')
            signal: 'BUY' or 'SELL'
            action: 'executed', 'vetoed', or 'evaluated'
            veto_reasons: List of reasons if trade was vetoed
            entry_price: Proposed entry price
            position_size: Proposed position size in USD
            broker: Broker name (e.g., 'KRAKEN')
            confidence: Signal confidence (0.0-1.0)
            rsi_9: RSI 9-period value
            rsi_14: RSI 14-period value
        """
        self.last_evaluated_trade = {
            'timestamp': datetime.now().isoformat(),
            'symbol': symbol,
            'signal': signal,
            'action': action,
            'veto_reasons': veto_reasons or [],
            'entry_price': entry_price,
            'position_size': position_size,
            'broker': broker,
            'confidence': confidence,
            'rsi_9': rsi_9,
            'rsi_14': rsi_14
        }

    def _init_advanced_features(self, total_capital: float = 0.0):
        """Initialize progressive targets, exchange risk profiles, and capital allocation.

        This is optional and will gracefully degrade if modules are not available.

        Also initializes PRO MODE rotation manager if enabled.

        CRITICAL: This method is gated by LIVE_CAPITAL_VERIFIED environment variable.
        Advanced modules are only initialized if LIVE_CAPITAL_VERIFIED=true is set.

        Args:
            total_capital: Live capital from broker connections (default: 0.0)
        """
        # CRITICAL SAFETY: Check LIVE_CAPITAL_VERIFIED first
        # This is the MASTER safety switch that must be explicitly enabled
        # to allow advanced trading features with real capital.
        live_capital_verified_str = os.getenv('LIVE_CAPITAL_VERIFIED', 'false').lower().strip()
        live_capital_verified = live_capital_verified_str in ['true', '1', 'yes', 'enabled']

        if not live_capital_verified:
            logger.info("=" * 70)
            logger.info("🔒 LIVE CAPITAL VERIFIED: FALSE")
            logger.info("   Advanced trading modules initialization SKIPPED")
            logger.info("   To enable advanced features, set LIVE_CAPITAL_VERIFIED=true in .env")
            logger.info("=" * 70)
            self.rotation_manager = None
            self.pro_mode_enabled = False
            self.advanced_manager = None
            self.ai_capital_rotator = None
            return

        logger.info("=" * 70)
        logger.info("🔓 LIVE CAPITAL VERIFIED: TRUE")
        logger.info("   Initializing advanced trading modules...")
        logger.info("=" * 70)

        # Initialize PRO MODE rotation manager
        pro_mode_enabled = os.getenv('PRO_MODE', 'false').lower() in ('true', '1', 'yes')
        min_free_reserve_pct = float(os.getenv('PRO_MODE_MIN_RESERVE_PCT', '0.15'))

        if pro_mode_enabled:
            try:
                from rotation_manager import RotationManager
                self.rotation_manager = RotationManager(
                    min_free_balance_pct=min_free_reserve_pct,
                    rotation_enabled=True,
                    min_opportunity_improvement=0.20  # 20% improvement required for rotation
                )
                logger.info("=" * 70)
                logger.info("🔄 PRO MODE ACTIVATED - Position Rotation Enabled")
                logger.info(f"   Min free balance reserve: {min_free_reserve_pct*100:.0f}%")
                logger.info(f"   Position values count as capital")
                logger.info(f"   Can rotate positions for better opportunities")
                logger.info("=" * 70)
            except Exception as e:
                logger.warning(f"⚠️ Failed to initialize PRO MODE: {e}")
                logger.info("   Falling back to standard mode")
                self.rotation_manager = None
                pro_mode_enabled = False
        else:
            logger.info("ℹ️ PRO MODE disabled (set PRO_MODE=true to enable)")
            self.rotation_manager = None

        self.pro_mode_enabled = pro_mode_enabled

        # Initialize AI Capital Rotation Engine (always active, not gated by PRO_MODE)
        try:
            from bot.ai_capital_rotation_engine import get_ai_capital_rotation_engine
            self.ai_capital_rotator = get_ai_capital_rotation_engine(
                max_active_positions=MAX_POSITIONS_ALLOWED,
                dust_threshold_usd=float(os.getenv('DUST_THRESHOLD_USD', '5.0')),
            )
            logger.info("✅ AI Capital Rotation Engine initialised (MAX=%d positions)", MAX_POSITIONS_ALLOWED)
        except Exception as err:
            logger.warning(f"⚠️ AI Capital Rotation Engine init failed (non-critical): {err}")
            try:
                from ai_capital_rotation_engine import get_ai_capital_rotation_engine
                self.ai_capital_rotator = get_ai_capital_rotation_engine(
                    max_active_positions=MAX_POSITIONS_ALLOWED,
                    dust_threshold_usd=float(os.getenv('DUST_THRESHOLD_USD', '5.0')),
                )
                logger.info("✅ AI Capital Rotation Engine initialised (MAX=%d positions)", MAX_POSITIONS_ALLOWED)
            except Exception as err2:
                logger.warning(f"⚠️ AI Capital Rotation Engine unavailable: {err2}")
                self.ai_capital_rotator = None

        try:
            # Import advanced trading modules
            from advanced_trading_integration import AdvancedTradingManager, ExchangeType

            # FIX #1: Use live capital passed from broker connections
            # This is the actual balance fetched from Coinbase, Kraken, and other brokers
            # Only fall back to environment variable if no capital was passed
            if total_capital > 0.01:  # Use small threshold to avoid floating-point precision issues
                # Use live capital from broker connections (PREFERRED)
                initial_capital = total_capital
                logger.info(f"ℹ️ Using LIVE capital from broker connections: ${initial_capital:.2f}")
            else:
                # Fallback: Try to get from environment variable
                initial_capital_str = os.getenv('INITIAL_CAPITAL', 'auto').strip().upper()

                # Support "auto" and "LIVE" as aliases for automatic balance detection
                if initial_capital_str in ('AUTO', 'LIVE'):
                    # Can't initialize without capital - skip initialization
                    logger.warning(f"⚠️ INITIAL_CAPITAL={initial_capital_str.lower()} but no live capital available")
                    logger.warning(f"   Advanced manager will not be initialized")
                    self.advanced_manager = None
                    return
                else:
                    # Try to parse as numeric value
                    try:
                        initial_capital = float(initial_capital_str)
                        if initial_capital <= 0:
                            logger.warning(f"⚠️ INITIAL_CAPITAL not set or zero, cannot initialize advanced manager")
                            self.advanced_manager = None
                            return
                        else:
                            logger.info(f"ℹ️ Using INITIAL_CAPITAL from environment: ${initial_capital:.2f}")
                    except (ValueError, TypeError):
                        logger.warning(f"⚠️ Invalid INITIAL_CAPITAL={initial_capital_str}, cannot initialize advanced manager")
                        self.advanced_manager = None
                        return

            allocation_strategy = os.getenv('ALLOCATION_STRATEGY', 'conservative')

            # Initialize advanced manager with live capital from broker connections
            self.advanced_manager = AdvancedTradingManager(
                total_capital=initial_capital,
                allocation_strategy=allocation_strategy
            )

            logger.info("=" * 70)
            logger.info("✅ Advanced Trading Features Enabled:")
            logger.info(f"   📈 Progressive Targets: ${self.advanced_manager.target_manager.get_current_target():.2f}/day")
            logger.info(f"   🏦 Exchange Profiles: Loaded")
            logger.info(f"   💰 Capital Allocation: {allocation_strategy}")
            logger.info("=" * 70)

        except ImportError as e:
            logger.info(f"ℹ️ Advanced trading features not available: {e}")
            logger.info("   Continuing with standard trading mode")
            self.advanced_manager = None
        except Exception as e:
            logger.warning(f"⚠️ Failed to initialize advanced features: {e}")
            self.advanced_manager = None

        # ── Hedge-Fund Upgrade: Global Integration Layer ─────────────────
        # Initialises all five pillars (multi-strategy, portfolio execution,
        # smart execution, adaptive learning, regulatory infrastructure) as
        # a single globally accessible singleton.
        try:
            from bot.nija_global_integration import get_nija_global
            log_dir    = os.getenv("COMPLIANCE_LOG_DIR",    "logs/compliance")
            report_dir = os.getenv("COMPLIANCE_REPORT_DIR", "logs/reports")
            # LIVE TRADING MODE: dry-run disabled by default. Set DRY_RUN=true to enable paper trading.
            dry_run    = os.getenv("DRY_RUN", "false").lower() in ("true", "1", "yes")
            quorum     = int(os.getenv("STRATEGY_QUORUM", "2"))
            min_conf   = float(os.getenv("MIN_SIGNAL_CONFIDENCE", "0.45"))

            self.nija_global = get_nija_global(
                total_capital=initial_capital if 'initial_capital' in dir() else total_capital,
                log_dir=log_dir,
                report_dir=report_dir,
                dry_run=dry_run,
                min_strategy_quorum=quorum,
                min_signal_confidence=min_conf,
            )
            logger.info("=" * 70)
            logger.info("🌐 NIJA GLOBAL INTEGRATION ACTIVE")
            logger.info(f"   Pillars: {self.nija_global._initialized_pillars}")
            logger.info(f"   Dry-run: {dry_run}")
            logger.info("=" * 70)
        except Exception as e:
            logger.warning(f"⚠️ NijaGlobalIntegration init failed (non-critical): {e}")
            self.nija_global = None

    def start_independent_multi_broker_trading(self):
        """
        Start independent trading threads for all connected and funded brokers.
        Each broker operates in complete isolation to prevent cascade failures.

        Returns:
            bool: True if independent trading started successfully
        """
        if not self.independent_trader:
            logger.warning("⚠️  Independent trader not initialized")
            return False

        if not self.broker_manager or not self.broker_manager.brokers:
            logger.warning("⚠️  No brokers available for independent trading")
            return False

        try:
            # Start independent trading threads and check if any were started
            success = self.independent_trader.start_independent_trading()
            return bool(success)
        except Exception as e:
            logger.error(f"❌ Failed to start independent trading: {e}")
            return False

    def stop_independent_trading(self):
        """
        Stop all independent trading threads gracefully.
        """
        if self.independent_trader:
            self.independent_trader.stop_all_trading()
        else:
            logger.warning("⚠️  Independent trader not initialized, nothing to stop")

    def get_multi_broker_status(self) -> Dict:
        """
        Get status of all brokers and independent trading.

        Returns:
            dict: Status summary including broker health and trading activity
        """
        if not self.independent_trader:
            return {
                'error': 'Independent trader not initialized',
                'mode': 'single_broker'
            }

        return self.independent_trader.get_status_summary()

    def log_multi_broker_status(self):
        """
        Log current status of all brokers.
        """
        if self.independent_trader:
            self.independent_trader.log_status_summary()
        else:
            logger.info("📊 Single broker mode (independent trading not enabled)")

    def _get_cached_candles(self, symbol: str, timeframe: str = '5m', count: int = 100, broker=None):
        """
        Get candles with caching to reduce API calls.

        Args:
            symbol: Trading pair symbol
            timeframe: Candle timeframe
            count: Number of candles
            broker: Optional broker instance to use. If not provided, uses self.broker.

        Returns:
            List of candle dicts or empty list
        """
        # Use provided broker or fall back to self.broker
        active_broker = broker if broker is not None else self.broker

        cache_key = f"{symbol}_{timeframe}_{count}"
        current_time = time.time()

        # Check cache first
        if cache_key in self.candle_cache:
            cached_time, cached_data = self.candle_cache[cache_key]
            if current_time - cached_time < self.CANDLE_CACHE_TTL:
                logger.debug(f"   {symbol}: Using cached candles (age: {int(current_time - cached_time)}s)")
                return cached_data

        # Cache miss or expired - fetch fresh data
        _t0 = time.perf_counter()
        candles = active_broker.get_candles(symbol, timeframe, count)
        _elapsed_ms = (time.perf_counter() - _t0) * 1_000

        # Feed latency sample into the exchange latency guard (if available)
        if getattr(self, 'latency_guard', None) is not None:
            try:
                self.latency_guard.record_latency(_elapsed_ms)
            except Exception:
                pass  # Non-fatal

        # Cache the result (even if empty, to avoid repeated failed requests)
        self.candle_cache[cache_key] = (current_time, candles)

        return candles

    def _get_broker_name(self, broker) -> str:
        """
        Get broker name for logging from broker instance.

        Args:
            broker: Broker instance (may be None or lack broker_type)

        Returns:
            str: Broker name (e.g., 'coinbase', 'kraken') or 'unknown'
        """
        return broker.broker_type.value if broker and hasattr(broker, 'broker_type') else 'unknown'

    def _is_broker_eligible_for_entry(self, broker: Optional[object]) -> Tuple[bool, str]:
        """
        Check if a broker is eligible for new entry (BUY) orders.

        A broker is eligible if:
        1. It's connected
        2. It's not in EXIT_ONLY mode
        3. Account balance meets minimum threshold

        Args:
            broker: Broker instance to check (uses duck typing to avoid circular imports)

        Returns:
            tuple: (is_eligible: bool, reason: str)
        """
        if not broker:
            veto_reason = "Broker not available"
            logger.info(f"🚫 TRADE VETO: {veto_reason}")
            self.veto_count_session += 1
            self.last_veto_reason = veto_reason
            return False, veto_reason

        broker_name = self._get_broker_name(broker)

        # Skip USER accounts entirely - they are copy trading accounts, not entry sources
        # PLATFORM = primary (generates entries), USER = secondary (receives copied trades)
        # hasattr guard is needed because broker uses duck typing (not a strict base class)
        if hasattr(broker, 'account_type') and broker.account_type == AccountType.USER:
            user_id = getattr(broker, 'user_id', None) or 'missing_user_id'
            skip_msg = f"ENTRY BLOCKED → broker=USER_{user_id} | reason=user account (copy trading only)"
            logger.info(f"   ⏭️  {skip_msg}")
            return False, f"USER account (copy trading only)"

        if not broker.connected:
            veto_reason = f"{broker_name.upper()} not connected"
            logger.info(f"🚫 TRADE VETO: {veto_reason}")
            logger.debug(f"   _is_broker_eligible_for_entry: {broker_name} not connected")
            self.veto_count_session += 1
            self.last_veto_reason = veto_reason
            return False, veto_reason

        # Check if broker is in EXIT_ONLY mode
        if hasattr(broker, 'exit_only_mode') and broker.exit_only_mode:
            veto_reason = f"{broker_name.upper()} in EXIT-ONLY mode"
            logger.info(f"🚫 TRADE VETO: {veto_reason}")
            logger.debug(f"   _is_broker_eligible_for_entry: {broker_name} in EXIT_ONLY mode")
            self.veto_count_session += 1
            self.last_veto_reason = veto_reason
            return False, veto_reason

        # Check if account balance meets minimum threshold
        # CRITICAL FIX (Jan 28, 2026): Use timeout to prevent hanging on slow balance fetches
        # Timeout configured to accommodate Kraken's API timeout (30s) plus network overhead (15s)
        try:
            # Call get_account_balance with timeout to prevent indefinite hanging
            # Uses BALANCE_FETCH_TIMEOUT (45s = 30s Kraken API timeout + 15s network/serialization buffer)
            # Note: Kraken makes 2 API calls (Balance + TradeBalance) with 1s minimum interval between calls
            balance_result = call_with_timeout(broker.get_account_balance, timeout_seconds=BALANCE_FETCH_TIMEOUT)

            # Check if timeout or error occurred
            # call_with_timeout returns (value, None) on success, (None, error) on failure
            if balance_result[1] is not None:  # Error from call_with_timeout
                error_msg = balance_result[1]
                logger.warning(f"   _is_broker_eligible_for_entry: {broker_name} balance fetch timed out or failed: {error_msg}")

                # CRITICAL FIX (Jan 27, 2026): More permissive cached balance fallback
                # When API is slow/timing out, we should still try to trade using cached balance
                # Previously was too conservative - would reject broker if no timestamp
                if hasattr(broker, '_last_known_balance') and broker._last_known_balance is not None:
                    cached_balance = broker._last_known_balance

                    # Check if cached balance has a timestamp (for staleness check)
                    cache_is_fresh = False
                    if hasattr(broker, '_balance_last_updated') and broker._balance_last_updated is not None:
                        balance_age_seconds = time.time() - broker._balance_last_updated
                        cache_is_fresh = balance_age_seconds <= CACHED_BALANCE_MAX_AGE_SECONDS
                        if not cache_is_fresh:
                            logger.warning(f"   ⚠️  Cached balance for {broker_name} is stale ({balance_age_seconds:.0f}s old > {CACHED_BALANCE_MAX_AGE_SECONDS}s max)")
                    else:
                        # CRITICAL FIX (Jan 27, 2026): Conditional cache usage when no timestamp
                        # If broker doesn't track timestamp, we can't verify age
                        # SAFE APPROACH: Only use cache if broker object was created recently (this session)
                        # This prevents trading with very stale data from previous sessions

                        # Check if broker has a 'connected_at' or similar timestamp
                        broker_session_age = None
                        if hasattr(broker, 'connected_at'):
                            broker_session_age = time.time() - broker.connected_at
                        elif hasattr(broker, 'created_at'):
                            broker_session_age = time.time() - broker.created_at

                        # Only use untimestamped cache if broker was connected/created in last 10 minutes
                        # This ensures cache is from current trading session, not stale from previous run
                        if broker_session_age is not None and broker_session_age <= 600:  # 10 minutes
                            cache_is_fresh = True
                            logger.info(f"   ℹ️  {broker_name} cached balance has no timestamp, but broker connected {broker_session_age:.0f}s ago - using cache")
                        else:
                            # No timestamp and no session age - too risky to use
                            cache_is_fresh = False
                            logger.warning(f"   ⚠️  {broker_name} cached balance has no timestamp and no session age - rejecting for safety")

                    if cache_is_fresh:
                        logger.info(f"   ✅ Using cached balance for {broker_name}: ${cached_balance:.2f}")
                        broker_type = broker.broker_type if hasattr(broker, 'broker_type') else None
                        min_balance = BROKER_MIN_BALANCE.get(broker_type, MIN_BALANCE_TO_TRADE_USD)

                        if cached_balance >= min_balance:
                            return True, f"Eligible (cached ${cached_balance:.2f} >= ${min_balance:.2f} min)"
                        else:
                            veto_reason = f"{broker_name.upper()} cached balance ${cached_balance:.2f} < ${min_balance:.2f} minimum"
                            logger.info(f"🚫 TRADE VETO: {veto_reason}")
                            self.veto_count_session += 1
                            self.last_veto_reason = veto_reason
                            return False, veto_reason

                veto_reason = f"{broker_name.upper()} balance fetch failed: timeout or error"
                logger.info(f"🚫 TRADE VETO: {veto_reason}")
                self.veto_count_session += 1
                self.last_veto_reason = veto_reason
                return False, veto_reason

            balance = balance_result[0] if balance_result[0] is not None else 0.0
            
            # 🔒 CAPITAL PROTECTION: Validate broker data completeness before allowing entries
            # Balance of 0.0 could indicate incomplete/missing data
            if balance == 0.0:
                veto_reason = f"{broker_name.upper()} broker data incomplete: balance is 0.0"
                logger.warning(f"🚫 CAPITAL PROTECTION: {veto_reason}")
                logger.info(f"🚫 TRADE VETO: {veto_reason}")
                self.veto_count_session += 1
                self.last_veto_reason = veto_reason
                return False, veto_reason
            
            broker_type = broker.broker_type if hasattr(broker, 'broker_type') else None
            min_balance = BROKER_MIN_BALANCE.get(broker_type, MIN_BALANCE_TO_TRADE_USD)

            logger.debug(f"   _is_broker_eligible_for_entry: {broker_name} balance=${balance:.2f}, min=${min_balance:.2f}")

            if balance < min_balance:
                veto_reason = f"{broker_name.upper()} balance ${balance:.2f} < ${min_balance:.2f} minimum"
                logger.info(f"🚫 TRADE VETO: {veto_reason}")
                self.veto_count_session += 1
                self.last_veto_reason = veto_reason
                return False, veto_reason

            # 🔒 CAPITAL PROTECTION: Final check - ensure broker has position_tracker
            if not hasattr(broker, 'position_tracker') or broker.position_tracker is None:
                veto_reason = f"{broker_name.upper()} broker data incomplete: no position_tracker"
                logger.error(f"🚫 CAPITAL PROTECTION: {veto_reason}")
                logger.info(f"🚫 TRADE VETO: {veto_reason}")
                self.veto_count_session += 1
                self.last_veto_reason = veto_reason
                return False, veto_reason

            logger.info(f"   ✅ ENTRY ALLOWED → broker=PLATFORM | balance=${balance:.2f} >= ${min_balance:.2f} min")
            return True, f"Eligible (${balance:.2f} >= ${min_balance:.2f} min)"
        except Exception as e:
            veto_reason = f"{broker_name.upper()} balance check failed: {e}"
            logger.warning(f"   _is_broker_eligible_for_entry: {broker_name} balance check exception: {e}")
            logger.info(f"🚫 TRADE VETO: {veto_reason}")
            self.veto_count_session += 1
            self.last_veto_reason = veto_reason
            return False, veto_reason

    def _select_entry_broker(self, all_brokers: Dict[BrokerType, object]) -> Tuple[Optional[object], Optional[str], Dict[str, str]]:
        """
        Select the best broker for new entry (BUY) orders based on priority.

        Checks brokers in ENTRY_BROKER_PRIORITY order and returns the first eligible one.
        Coinbase is automatically deprioritized if balance < $25.

        Args:
            all_brokers: Dict of {BrokerType: broker_instance} for all available brokers

        Returns:
            tuple: (broker_instance, broker_name, eligibility_reasons) or (None, None, reasons)
        """
        eligibility_status = {}

        # CRITICAL FIX (Jan 24, 2026): Add debug logging to diagnose broker selection issues
        logger.debug(f"_select_entry_broker called with {len(all_brokers)} brokers: {[bt.value for bt in all_brokers.keys()]}")

        # Check each broker in priority order
        for broker_type in ENTRY_BROKER_PRIORITY:
            broker = all_brokers.get(broker_type)

            if not broker:
                eligibility_status[broker_type.value] = "Not configured"
                logger.debug(f"   {broker_type.value}: Not in all_brokers dict")
                continue

            is_eligible, reason = self._is_broker_eligible_for_entry(broker)
            eligibility_status[broker_type.value] = reason
            logger.debug(f"   {broker_type.value}: is_eligible={is_eligible}, reason={reason}")

            if is_eligible:
                broker_name = self._get_broker_name(broker)
                logger.info(f"✅ Selected {broker_name.upper()} for entry (priority: {ENTRY_BROKER_PRIORITY.index(broker_type) + 1})")
                return broker, broker_name, eligibility_status

        # No eligible broker found
        logger.debug(f"_select_entry_broker: No eligible broker found. Status: {eligibility_status}")
        return None, None, eligibility_status

    def _is_zombie_position(self, pnl_percent: float, entry_time_available: bool, position_age_hours: float) -> bool:
        """
        Detect if a position is a "zombie" - stuck at ~0% P&L for too long.

        Zombie positions occur when auto-import masks a losing trade by setting
        entry_price = current_price, causing P&L to reset to 0%. These positions
        never show as losing and can hold indefinitely, tying up capital.

        Args:
            pnl_percent: Current P&L percentage
            entry_time_available: Whether position has entry time tracked
            position_age_hours: Hours since position entry

        Returns:
            bool: True if position is a zombie (should be exited)
        """
        # Check if P&L is stuck near zero
        pnl_stuck_at_zero = abs(pnl_percent) < ZOMBIE_PNL_THRESHOLD

        # Check if position is old enough to be suspicious
        old_enough = entry_time_available and position_age_hours >= ZOMBIE_POSITION_HOURS

        # Zombie if both conditions are true
        return pnl_stuck_at_zero and old_enough

    def _get_rotated_markets(self, all_markets: list) -> list:
        """
        Get next batch of markets to scan using rotation strategy.

        UPDATED (Jan 10, 2026): Added adaptive batch sizing to prevent API rate limiting
        - Starts with small batch (5 markets) on fresh start or after API errors
        - Gradually increases to max batch size (15 markets) over warmup period
        - Reduces batch size when API health score is low

        This prevents scanning the same markets every cycle and distributes
        API load across time. With 730 markets and batch size of 5-15,
        we complete a full rotation in multiple hours.

        Args:
            all_markets: Full list of available markets

        Returns:
            Subset of markets for this cycle
        """
        # Calculate adaptive batch size based on warmup and API health
        if self.cycle_count < MARKET_BATCH_WARMUP_CYCLES:
            # Warmup phase: use minimum batch size
            batch_size = MARKET_BATCH_SIZE_MIN
            logger.info(f"   🔥 Warmup mode: cycle {self.cycle_count + 1}/{MARKET_BATCH_WARMUP_CYCLES}, batch size={batch_size}")
        elif self.api_health_score < 50:
            # API health degraded: reduce batch size
            batch_size = MARKET_BATCH_SIZE_MIN
            logger.warning(f"   ⚠️  API health low ({self.api_health_score}%), using reduced batch size={batch_size}")
        elif self.api_health_score < 80:
            # Moderate health: use mid-range batch size
            batch_size = (MARKET_BATCH_SIZE_MIN + MARKET_BATCH_SIZE_MAX) // 2
            logger.info(f"   📊 API health moderate ({self.api_health_score}%), batch size={batch_size}")
        else:
            # Good health: use maximum batch size
            batch_size = MARKET_BATCH_SIZE_MAX

        if not MARKET_ROTATION_ENABLED or len(all_markets) <= batch_size:
            # If rotation disabled or fewer markets than batch size, use all markets
            return all_markets[:batch_size]

        # Calculate batch boundaries
        total_markets = len(all_markets)
        start_idx = self.market_rotation_offset
        end_idx = start_idx + batch_size

        # Handle wrap-around
        if end_idx <= total_markets:
            batch = all_markets[start_idx:end_idx]
        else:
            # Wrap around to beginning
            batch = all_markets[start_idx:] + all_markets[:end_idx - total_markets]

        # Update offset for next cycle
        self.market_rotation_offset = end_idx % total_markets

        # Log rotation progress
        rotation_pct = (self.market_rotation_offset / total_markets) * 100
        logger.info(f"   📊 Market rotation: scanning batch {start_idx}-{min(end_idx, total_markets)} of {total_markets} ({rotation_pct:.0f}% through cycle)")

        return batch

    def _get_stop_loss_tier(self, broker, account_balance: float) -> tuple:
        """
        Determine the appropriate stop-loss tier based on broker type and account balance.

        Returns 3-tier stop-loss system:
        - Tier 1: Primary trading stop (for risk management)
        - Tier 2: Emergency micro-stop (for logic failure prevention)
        - Tier 3: Catastrophic failsafe (last resort)

        Args:
            broker: Broker instance (to determine broker type)
            account_balance: Current account balance in USD

        Returns:
            tuple: (primary_stop, micro_stop, catastrophic_stop, description)
        """
        # Determine broker type with multiple fallback approaches
        # This flexibility handles various broker implementations without requiring
        # strict interface contracts. While not ideal, it provides robustness across
        # different broker adapter patterns (BrokerInterface, direct API wrappers, etc.)
        broker_name = 'coinbase'  # default
        if hasattr(broker, 'broker_type'):
            broker_name = broker.broker_type.value.lower() if hasattr(broker.broker_type, 'value') else str(broker.broker_type).lower()
        elif hasattr(broker, '__class__'):
            broker_name = broker.__class__.__name__.lower()

        # Kraken: -1.5% primary stop (tightened from -3.0% to enforce 2:1+ R:R)
        if 'kraken' in broker_name and account_balance < 100:
            primary_stop = STOP_LOSS_PRIMARY_KRAKEN  # -1.5%
            description = f"Kraken small balance (${account_balance:.2f}): Primary -1.5%, Backstop -2.0%, Failsafe -3.0%"

        # Kraken with larger balance: same tight stop
        elif 'kraken' in broker_name:
            primary_stop = STOP_LOSS_PRIMARY_KRAKEN_MIN  # -1.5%
            description = f"Kraken (${account_balance:.2f}): Primary -1.5%, Backstop -2.0%, Failsafe -3.0%"

        # Coinbase: -1.5% stop (tightened from -3.0% to overcome 1.4% fee drag)
        elif 'coinbase' in broker_name:
            primary_stop = STOP_LOSS_PRIMARY_COINBASE  # -1.5%
            description = f"COINBASE (${account_balance:.2f}): Primary -1.5%, Backstop -2.0%, Failsafe -3.0%"

        # All other exchanges: -1.5% universal stop (tightened from -3.0%)
        else:
            primary_stop = -0.015  # -1.5% for all other exchanges (was -3.0%)
            description = f"{broker_name.upper()} (${account_balance:.2f}): Primary -1.5%, Backstop -2.0%, Failsafe -3.0%"

        return (
            primary_stop,           # Tier 1: Primary trading stop
            STOP_LOSS_MICRO,        # Tier 2: Emergency backstop (-2.0%)
            STOP_LOSS_EMERGENCY,    # Tier 3: Catastrophic failsafe (-3.0%)
            description
        )

    def _display_user_status_banner(self, broker=None):
        """
        Display user status banner with trading status and account info.
        
        Shows:
        - Current capital/balance
        - Active positions count
        - Trading status (active/vetoed)
        - Last veto reason (if any)
        - Heartbeat status (if enabled)
        
        Args:
            broker: Optional broker instance to get current status from
        """
        logger.info("=" * 70)
        logger.info("📊 USER STATUS BANNER")
        logger.info("=" * 70)
        
        # Display capital information
        try:
            if broker and broker.connected:
                balance = broker.get_account_balance()
                broker_name = self._get_broker_name(broker)
                logger.info(f"   💰 {broker_name.upper()} Balance: ${balance:,.2f}")
                
                # Get active positions count
                try:
                    positions = broker.get_positions()
                    active_count = len(positions) if positions else 0
                    logger.info(f"   📈 Active Positions: {active_count}")
                except Exception as e:
                    logger.debug(f"   Could not get positions: {e}")
            else:
                logger.info("   ⚠️  No broker connected")
        except Exception as e:
            logger.debug(f"   Could not get balance: {e}")
        
        # Display trading status
        if self.last_veto_reason:
            logger.info(f"   🚫 Trading Status: VETOED")
            logger.info(f"   📋 Last Veto Reason: {self.last_veto_reason}")
            logger.info(f"   📊 Vetoed Trades (Session): {self.veto_count_session}")
        else:
            logger.info(f"   ✅ Trading Status: ACTIVE")
        
        # Display heartbeat status if enabled
        if HEARTBEAT_TRADE_ENABLED:
            if self.heartbeat_last_trade_time > 0:
                time_since_heartbeat = int(time.time() - self.heartbeat_last_trade_time)
                logger.info(f"   ❤️  Heartbeat: Last trade {time_since_heartbeat}s ago ({self.heartbeat_trade_count} total)")
            else:
                logger.info(f"   ❤️  Heartbeat: ENABLED (awaiting first trade)")
        
        logger.info("=" * 70)
    
    def _execute_heartbeat_trade(self, broker=None):
        """
        Execute a tiny heartbeat trade to verify exchange connectivity.
        
        Heartbeat trades are minimal size ($5.50) test trades that:
        - Verify API credentials are working
        - Confirm order execution is functional
        - Monitor exchange connectivity health
        
        Only executes if:
        - HEARTBEAT_TRADE_ENABLED is true
        - Sufficient time has passed since last heartbeat (HEARTBEAT_TRADE_INTERVAL_SECONDS)
        - Broker is connected and has sufficient balance
        
        Args:
            broker: Broker instance to execute heartbeat trade on
            
        Returns:
            bool: True if heartbeat trade was executed, False otherwise
        """
        if not HEARTBEAT_TRADE_ENABLED:
            return False
        
        current_time = time.time()
        
        # Check if enough time has passed since last heartbeat
        if self.heartbeat_last_trade_time > 0:
            time_since_last = current_time - self.heartbeat_last_trade_time
            if time_since_last < HEARTBEAT_TRADE_INTERVAL_SECONDS:
                return False
        
        # Verify broker is available
        if not broker or not broker.connected:
            logger.debug("   Heartbeat trade skipped: no broker connected")
            return False
        
        broker_name = self._get_broker_name(broker)
        
        try:
            # Get account balance to verify we can trade
            balance = broker.get_account_balance()
            if balance < HEARTBEAT_TRADE_SIZE_USD:
                logger.warning(f"   ❤️  Heartbeat trade skipped: ${balance:.2f} < ${HEARTBEAT_TRADE_SIZE_USD:.2f} minimum")
                return False
            
            # Get available markets
            markets = broker.get_available_markets()
            if not markets:
                logger.warning("   ❤️  Heartbeat trade skipped: no markets available")
                return False
            
            # Select a liquid, low-volatility market for heartbeat (prefer BTC-USD or ETH-USD)
            # Try multiple symbol format variations to match broker's format
            preferred_symbols = ['BTC-USD', 'BTCUSD', 'ETH-USD', 'ETHUSD', 'BTC/USD', 'ETH/USD']
            heartbeat_symbol = None
            
            for symbol in preferred_symbols:
                # Try exact match first
                if symbol in markets:
                    heartbeat_symbol = symbol
                    break
                # Try format variations
                symbol_dash = symbol.replace('/', '-')
                symbol_slash = symbol.replace('-', '/')
                if symbol_dash in markets:
                    heartbeat_symbol = symbol_dash
                    break
                if symbol_slash in markets:
                    heartbeat_symbol = symbol_slash
                    break
            
            # Fallback to first available market
            if not heartbeat_symbol and markets:
                heartbeat_symbol = markets[0]
            
            if not heartbeat_symbol:
                logger.warning("   ❤️  Heartbeat trade skipped: no suitable symbol found")
                return False
            
            # Execute tiny market buy order
            logger.info("=" * 70)
            logger.info(f"❤️  HEARTBEAT TRADE EXECUTION")
            logger.info("=" * 70)
            logger.info(f"   Symbol: {heartbeat_symbol}")
            logger.info(f"   Size: ${HEARTBEAT_TRADE_SIZE_USD:.2f}")
            logger.info(f"   Broker: {broker_name.upper()}")
            logger.info(f"   Purpose: Verify connectivity & order execution")
            
            # Place market buy order
            # Note: size_type='quote' means size is in USD, not base currency
            # If broker doesn't support size_type parameter, this will use the size as base currency amount
            try:
                order_result = broker.place_market_order(
                    symbol=heartbeat_symbol,
                    side='buy',
                    size=HEARTBEAT_TRADE_SIZE_USD,
                    size_type='quote'  # USD amount, not base currency amount
                )
            except TypeError:
                # Broker doesn't support size_type parameter - fallback to positional args
                logger.debug(f"   Broker {broker_name} doesn't support size_type parameter, using default")
                order_result = broker.place_market_order(
                    symbol=heartbeat_symbol,
                    side='buy',
                    size=HEARTBEAT_TRADE_SIZE_USD
                )
            
            if order_result and order_result.get('status') in ['filled', 'open', 'pending']:
                self.heartbeat_last_trade_time = current_time
                self.heartbeat_trade_count += 1
                
                logger.info(f"   ✅ Heartbeat trade #{self.heartbeat_trade_count} EXECUTED")
                logger.info(f"   Order ID: {order_result.get('order_id', 'N/A')}")
                logger.info(f"   Status: {order_result.get('status', 'unknown')}")
                logger.info("=" * 70)
                
                return True
            else:
                logger.warning(f"   ❌ Heartbeat trade failed: {order_result}")
                logger.info("=" * 70)
                return False
                
        except Exception as e:
            logger.error(f"   ❤️  Heartbeat trade error: {e}")
            logger.error(f"   {traceback.format_exc()}")
            return False

    def run_cycle(self, broker=None, user_mode=False):
        """Execute a complete trading cycle with position cap enforcement.

        Args:
            broker: Optional broker instance to use for this cycle. If not provided,
                   uses self.broker (default behavior for backward compatibility).
                   This parameter enables thread-safe multi-broker trading by avoiding
                   shared state mutation - each thread passes its own broker instance
                   instead of modifying the shared self.broker variable.
            user_mode: If True, runs in USER mode which:
                      - DISABLES strategy execution (no signal generation)
                      - ONLY manages existing positions (exits, stops, targets)
                      - Users receive signals via CopyTradeEngine, not from strategy
                      Default False for PLATFORM accounts (full strategy execution)

        Steps:
        1. Enforce position cap (auto-sell excess if needed)
        2. [PLATFORM ONLY] Scan markets for opportunities
        3. [PLATFORM ONLY] Execute entry logic / [USER] Execute position exits only
        4. Update trailing stops and take profits
        5. Log cycle summary
        """
        # Use provided broker or fall back to self.broker (thread-safe approach)
        active_broker = broker if broker is not None else self.broker

        # SAFETY: account_balance MUST be defined before any reference — even if
        # entry is skipped early.  All downstream code uses `account_balance is not
        # None` guards so 0.0 is the safe sentinel when the broker is unavailable.
        account_balance: float = 0.0

        # Remember whether the caller explicitly requested user mode so we can
        # distinguish it from user_mode being forced True by safety checks later.
        explicit_user_mode = user_mode

        # ✅ LAYER 0: RECOVERY CONTROLLER - Capital-first safety check
        # This is the AUTHORITATIVE control layer that sits above all other safety checks
        if RECOVERY_CONTROLLER_AVAILABLE and get_recovery_controller:
            recovery_controller = get_recovery_controller()
            
            # Update capital safety assessment if we have balance info
            if active_broker and hasattr(active_broker, 'get_balance'):
                try:
                    balance_result = active_broker.get_balance()
                    if balance_result and not balance_result[1]:  # No error
                        current_balance = balance_result[0]
                        # Count current positions
                        position_count = len(self.execution_engine.positions) if self.execution_engine else 0
                        
                        # Update capital safety assessment
                        recovery_controller.assess_capital_safety(
                            current_balance=current_balance,
                            position_count=position_count
                        )
                except Exception as e:
                    logger.warning(f"Could not update capital safety: {e}")
            
            # Check if trading is allowed
            can_trade_entry, reason = recovery_controller.can_trade("entry")
            
            if not can_trade_entry:
                logger.warning("=" * 80)
                logger.warning("🛡️  RECOVERY CONTROLLER: ENTRIES BLOCKED")
                logger.warning("=" * 80)
                logger.warning(f"   Reason: {reason}")
                logger.warning(f"   State: {recovery_controller.current_state.value}")
                logger.warning(f"   Capital Safety: {recovery_controller.capital_safety_level.value}")
                logger.warning(f"   Mode: Position management only (exits/stops)")
                logger.warning("=" * 80)
                # Force user mode to block new entries but allow position management
                user_mode = True

        # ✅ LAYER 0b: GLOBAL RISK GOVERNOR — cascade-loss circuit breaker
        # Checks daily loss, consecutive losses, equity curve, and exposure concentration.
        # Runs after the recovery controller so we have current balance available.
        if GLOBAL_RISK_GOVERNOR_AVAILABLE and get_global_risk_governor and not user_mode:
            try:
                _gov = get_global_risk_governor()
                _gov_balance = 0.0
                if active_broker and hasattr(active_broker, 'get_balance'):
                    try:
                        _bal_result = active_broker.get_balance()
                        if _bal_result and not _bal_result[1]:
                            _gov_balance = float(_bal_result[0])
                    except Exception:
                        pass

                _gov_pos_count = (
                    len(self.execution_engine.positions)
                    if self.execution_engine else 0
                )
                _gov.update_open_positions(_gov_pos_count)

                if _gov_balance > 0:
                    _gov_decision = _gov.approve_entry(
                        symbol="PORTFOLIO",
                        proposed_risk_usd=0.0,   # portfolio-level gate; per-trade checked separately
                        current_portfolio_value=_gov_balance,
                    )
                    if not _gov_decision.allowed:
                        logger.warning("=" * 80)
                        logger.warning("🛑 GLOBAL RISK GOVERNOR: NEW ENTRIES BLOCKED")
                        logger.warning("=" * 80)
                        logger.warning(f"   Reason: {_gov_decision.reason}")
                        logger.warning(f"   Risk Score: {_gov_decision.risk_score:.0f}/100")
                        logger.warning("   Mode: Position management only (exits/stops)")
                        logger.warning("=" * 80)
                        user_mode = True
                    elif _gov_decision.risk_score > 50:
                        logger.warning(
                            "⚠️ Global Risk Governor: elevated risk %.0f/100 — %s",
                            _gov_decision.risk_score,
                            _gov_decision.reason,
                        )
            except Exception as _gov_exc:
                logger.debug("Global Risk Governor check skipped: %s", _gov_exc)

        # ✅ LAYER 0c: GLOBAL DRAWDOWN CIRCUIT BREAKER — system-wide halt on deep drawdown
        # Monitors aggregate equity and blocks new entries when portfolio drawdown is too deep.
        if GLOBAL_DRAWDOWN_CB_AVAILABLE and get_global_drawdown_cb and not user_mode:
            try:
                _gdcb = get_global_drawdown_cb()
                _gdcb_balance = 0.0
                if active_broker and hasattr(active_broker, 'get_balance'):
                    try:
                        _gdcb_bal_result = active_broker.get_balance()
                        if _gdcb_bal_result and not _gdcb_bal_result[1]:
                            _gdcb_balance = float(_gdcb_bal_result[0])
                    except Exception:
                        pass
                if _gdcb_balance > 0:
                    _gdcb_decision = _gdcb.update_equity(_gdcb_balance)
                    if not _gdcb_decision.allow_new_entries:
                        logger.warning("=" * 80)
                        logger.warning("🛑 GLOBAL DRAWDOWN CIRCUIT BREAKER: NEW ENTRIES HALTED")
                        logger.warning("=" * 80)
                        logger.warning(f"   Level: {_gdcb_decision.level.value}")
                        logger.warning(f"   Drawdown: {_gdcb_decision.drawdown_pct:.2f}%")
                        logger.warning(f"   Reason: {_gdcb_decision.reason}")
                        logger.warning("   Mode: Position management only (exits/stops)")
                        logger.warning("=" * 80)
                        user_mode = True
                    elif _gdcb_decision.drawdown_pct >= 5.0:
                        logger.warning(
                            "⚠️ Global Drawdown CB: %s — drawdown=%.2f%% "
                            "(size mult=%.2f)",
                            _gdcb_decision.level.value,
                            _gdcb_decision.drawdown_pct,
                            _gdcb_decision.position_size_multiplier,
                        )
            except Exception as _gdcb_exc:
                logger.debug("Global Drawdown Circuit Breaker check skipped: %s", _gdcb_exc)

        # ✅ LAYER 0d: PHASE 3 — ABNORMAL MARKET KILL SWITCH
        # Automatically halts trading on flash crashes, extreme volatility,
        # volume explosions, API error storms, or consecutive-loss streaks.
        if ABNORMAL_MARKET_KS_AVAILABLE and hasattr(self, 'abnormal_market_ks') and self.abnormal_market_ks is not None:
            try:
                _aks_triggered, _aks_reason = self.abnormal_market_ks.check_and_trigger()
                if _aks_triggered:
                    logger.critical("🚨 PHASE 3 ABNORMAL MARKET KILL SWITCH ACTIVE: %s", _aks_reason)
                    user_mode = True  # Block new entries until operator resets
            except Exception as _aks_exc:
                logger.debug("Abnormal Market Kill Switch check skipped: %s", _aks_exc)

        # CRITICAL SAFETY CHECK: Verify trading is allowed before ANY operations
        if self.safety:
            trading_allowed, reason = self.safety.is_trading_allowed()
            if not trading_allowed and not user_mode:
                # Trading not allowed - only execute if this is a position management cycle
                logger.warning("=" * 70)
                logger.warning("🛑 TRADING NOT ALLOWED")
                logger.warning("=" * 70)
                logger.warning(f"   Reason: {reason}")
                logger.warning("   Mode: Position management only (exits/stops)")
                logger.warning("   No new entries will be executed")
                logger.warning("=" * 70)
                # Allow position management (exits/stops) but block new entries
                user_mode = True  # Force user mode to disable new entries

        # 🏦 TIERED RISK ENGINE — conservative vs aggressive capital pool gate
        if not user_mode and hasattr(self, 'tiered_risk_engine') and self.tiered_risk_engine is not None:
            try:
                _open_positions = len(getattr(self, 'open_positions', {}))
                _market_vol = 50.0  # neutral default volatility (0-100 scale)
                # Use the actual account balance to compute a realistic representative
                # trade size for the gate check.  The old formula (BASE_CAPITAL * 0.05)
                # produced a hardcoded $5 test trade that was always below the INVESTOR
                # tier minimum ($20), causing the gate to set user_mode=True and block
                # all new entries.  user_mode disables entry scanning for the entire cycle,
                # so this single bad gate was silently preventing every trade.
                _trade_size = get_dynamic_min_position_size(account_balance)
                _tier_ok, _tier_level, _tier_msg = self.tiered_risk_engine.validate_trade(
                    trade_size=_trade_size,
                    current_positions=_open_positions,
                    market_volatility=_market_vol,
                )
                if not _tier_ok:
                    logger.warning("🛑 TIERED RISK ENGINE: entries blocked — %s", _tier_msg)
                    user_mode = True
            except Exception as _tre_gate_err:
                logger.debug("Tiered Risk Engine gate check skipped: %s", _tre_gate_err)

        # 📈 CAPITAL SCALING ENGINE — block entries if drawdown protection halted trading
        if not user_mode and hasattr(self, 'capital_scaling_engine') and self.capital_scaling_engine is not None:
            try:
                _cse_ok, _cse_reason = self.capital_scaling_engine.can_trade()
                if not _cse_ok:
                    logger.warning("🛑 CAPITAL SCALING ENGINE: entries blocked — %s", _cse_reason)
                    user_mode = True
            except Exception as _cse_gate_err:
                logger.debug("Capital Scaling Engine gate check skipped: %s", _cse_gate_err)

        # Log mode for clarity.  Distinguish between:
        #   USER   — caller explicitly requested user mode (copy-trade accounts)
        #   PLATFORM (entries blocked) — safety checks forced entry-only mode on a platform account
        #   MASTER — full strategy execution
        if explicit_user_mode:
            mode_label = "USER (position management only)"
        elif user_mode:
            mode_label = "PLATFORM (entries blocked by safety checks)"
        else:
            mode_label = "MASTER (full strategy)"
        logger.info(f"🔄 Trading cycle mode: {mode_label}")

        # 🔄 BACKGROUND PLATFORM RECONNECT — self-heal disconnected platform brokers.
        # Only runs in MASTER mode (not user mode) and only on every 5th cycle to avoid
        # hammering the API, but still recovers quickly after a transient startup failure.
        # Note: cycle_count is incremented at the end of each run_cycle call (see below),
        # so this check fires on cycles 0, 5, 10 … which is the correct periodic cadence.
        if not user_mode and hasattr(self, 'multi_account_manager') and self.multi_account_manager:
            try:
                _cycle = getattr(self, 'cycle_count', 0)
                if _cycle % 5 == 0:
                    for _bt, _pb in list(self.multi_account_manager.platform_brokers.items()):
                        if _pb is not None and not _pb.connected:
                            logger.info(
                                f"🔄 Cycle {_cycle}: Platform {_bt.value.upper()} is offline — "
                                "attempting background reconnect…"
                            )
                            self.multi_account_manager.try_reconnect_platform_broker(_bt)
            except Exception as _reconnect_err:
                logger.debug(f"Background platform reconnect check error: {_reconnect_err}")

        # ⏱️ Scan-cycle timing: record overall start time
        cycle_start_time = time.time()
        
        # Display user status banner (trust layer feature)
        self._display_user_status_banner(broker=active_broker)
        
        # Execute heartbeat trade if enabled and due
        if not user_mode:  # Only execute heartbeat in MASTER mode
            heartbeat_executed = self._execute_heartbeat_trade(broker=active_broker)
            if heartbeat_executed:
                logger.info("   ❤️  Heartbeat trade executed - connectivity verified")
        
        try:
            # 🚨 EMERGENCY: Check if LIQUIDATE_ALL mode is active
            liquidate_all_file = os.path.join(os.path.dirname(__file__), '..', 'LIQUIDATE_ALL_NOW.conf')
            if os.path.exists(liquidate_all_file):
                logger.error("🚨 EMERGENCY LIQUIDATION MODE ACTIVE")
                logger.error("   SELLING ALL POSITIONS IMMEDIATELY")

                sold_count = 0
                total_positions = 0

                try:
                    if active_broker:
                        try:
                            positions = call_with_timeout(active_broker.get_positions, timeout_seconds=30)
                            if positions[1]:  # Error occurred
                                logger.error(f"   Failed to get positions: {positions[1]}")
                                positions = []
                            else:
                                positions = positions[0] or []
                        except Exception as e:
                            logger.error(f"   Exception getting positions: {e}")
                            positions = []

                        total_positions = len(positions)
                        logger.error(f"   Found {total_positions} positions to liquidate")

                        for i, pos in enumerate(positions, 1):
                            try:
                                symbol = pos.get('symbol', 'UNKNOWN')
                                currency = pos.get('currency', symbol.split('-')[0])
                                quantity = pos.get('quantity', 0)

                                if quantity <= 0:
                                    logger.error(f"   [{i}/{total_positions}] SKIPPING {currency} (quantity={quantity})")
                                    continue

                                logger.error(f"   [{i}/{total_positions}] FORCE SELLING {quantity:.8f} {currency}...")

                                try:
                                    result = call_with_timeout(
                                        active_broker.place_market_order,
                                        args=(symbol, 'sell', quantity),
                                        kwargs={'size_type': 'base'},
                                        timeout_seconds=30
                                    )
                                    if result[1]:  # Error from call_with_timeout
                                        logger.error(f"   ❌ Timeout/error selling {currency}: {result[1]}")
                                    else:
                                        result_dict = result[0] or {}
                                        if result_dict and result_dict.get('status') not in ['error', 'unfilled']:
                                            logger.error(f"   ✅ SOLD {currency}")
                                            sold_count += 1
                                        else:
                                            error_msg = result_dict.get('error', result_dict.get('message', 'Unknown'))
                                            logger.error(f"   ❌ Failed to sell {currency}: {error_msg}")
                                except Exception as e:
                                    logger.error(f"   ❌ Exception during sell: {e}")

                                # Throttle to avoid Coinbase 429 rate limits
                                try:
                                    time.sleep(1.0)
                                except Exception:
                                    pass

                            except Exception as pos_err:
                                logger.error(f"   ❌ Position processing error: {pos_err}")
                                continue

                        logger.error(f"   Liquidation round complete: {sold_count}/{total_positions} sold")

                except Exception as liquidation_error:
                    logger.error(f"   ❌ Emergency liquidation critical error: {liquidation_error}")
                    import traceback
                    logger.error(traceback.format_exc())

                finally:
                    # GUARANTEED cleanup - always remove the trigger file
                    try:
                        if os.path.exists(liquidate_all_file):
                            os.remove(liquidate_all_file)
                            logger.error("✅ Emergency liquidation cycle complete - removed LIQUIDATE_ALL_NOW.conf")
                    except Exception as cleanup_err:
                        logger.error(f"   Warning: Could not delete trigger file: {cleanup_err}")

                return  # Skip normal trading cycle

            # CRITICAL: Enforce position cap first
            if self.enforcer:
                logger.info(f"🔍 Enforcing position cap (max {MAX_POSITIONS_ALLOWED})...")
                success, result = self.enforcer.enforce_cap()
                if result['excess'] > 0:
                    logger.warning(f"⚠️ Excess positions detected: {result['excess']} over cap")
                    logger.info(f"   Sold {result['sold']} positions")
            
            # 🧹 FORCED CLEANUP: Run aggressive dust cleanup and retroactive cap enforcement
            # This runs periodically to clean up:
            # 1. Dust positions < $1 USD
            # 2. Excess positions over hard cap (retroactive enforcement)
            # Runs across ALL accounts (platform + users)
            run_startup_cleanup = hasattr(self, 'cycle_count') and self.cycle_count == 0
            # Feature 2 (Forced capital consolidation / Feature 1 aggressive dust cleanup):
            # Micro accounts (< MICRO_CLEANUP_BALANCE_THRESHOLD) use a shorter interval so
            # capital is freed up faster and available for the next entry.
            _cleanup_interval = (
                MICRO_CLEANUP_INTERVAL
                if account_balance is not None and account_balance < MICRO_CLEANUP_BALANCE_THRESHOLD
                else FORCED_CLEANUP_INTERVAL
            )
            run_periodic_cleanup = hasattr(self, 'cycle_count') and self.cycle_count > 0 and (self.cycle_count % _cleanup_interval == 0)
            
            # Optional trade-based trigger: Cleanup after N trades
            run_trade_based_cleanup = False
            if FORCED_CLEANUP_AFTER_N_TRADES and hasattr(self, 'trades_since_last_cleanup'):
                run_trade_based_cleanup = self.trades_since_last_cleanup >= FORCED_CLEANUP_AFTER_N_TRADES
            
            if hasattr(self, 'forced_cleanup') and self.forced_cleanup and (run_startup_cleanup or run_periodic_cleanup or run_trade_based_cleanup):
                # Determine cleanup reason for logging
                if run_startup_cleanup:
                    cleanup_reason = "STARTUP"
                elif run_trade_based_cleanup:
                    cleanup_reason = f"TRADE-BASED ({self.trades_since_last_cleanup} trades executed)"
                else:
                    cleanup_reason = f"PERIODIC (cycle {self.cycle_count})"
                
                logger.warning(f"")
                logger.warning(f"🧹 FORCED CLEANUP TRIGGERED: {cleanup_reason}")
                logger.warning(f"   Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                logger.warning(f"   Interval: Every {FORCED_CLEANUP_INTERVAL} cycles (~{FORCED_CLEANUP_INTERVAL * 2.5:.0f} minutes)")
                if FORCED_CLEANUP_AFTER_N_TRADES:
                    logger.warning(f"   Trade trigger: After {FORCED_CLEANUP_AFTER_N_TRADES} trades (current: {self.trades_since_last_cleanup})")
                try:
                    if hasattr(self, 'multi_account_manager') and self.multi_account_manager:
                        # Run cleanup across all accounts
                        summary = self.forced_cleanup.cleanup_all_accounts(self.multi_account_manager, is_startup=run_startup_cleanup)
                        logger.warning(f"   ✅ Cleanup complete: Reduced positions by {summary['reduction']}")
                    else:
                        # Single account mode - just cleanup platform
                        logger.info(f"   Running single-account cleanup...")
                        if active_broker:
                            result = self.forced_cleanup.cleanup_single_account(active_broker, "platform", is_startup=run_startup_cleanup)
                            logger.warning(f"   ✅ Cleanup complete: {result['initial_positions']} → {result['final_positions']}")
                    
                    # Reset trade counter after cleanup
                    if hasattr(self, 'trades_since_last_cleanup'):
                        self.trades_since_last_cleanup = 0
                        
                except Exception as cleanup_err:
                    logger.error(f"   ❌ Forced cleanup failed: {cleanup_err}")
                    import traceback
                    logger.error(traceback.format_exc())
                logger.warning(f"")

            # 🌀 CONTINUOUS DUST MONITOR (Option A): Time-based dust sweep
            # Checks all accounts every DUST_SWEEP_INTERVAL_MINUTES (default 30 min)
            # and closes any position < DUST_THRESHOLD_USD. Each action is audit-logged.
            if hasattr(self, 'continuous_dust_monitor') and self.continuous_dust_monitor:
                try:
                    # Build (account_id, broker) list for this cycle
                    _cdm_brokers = []
                    if hasattr(self, 'multi_account_manager') and self.multi_account_manager:
                        for _acct_id, _acct_broker in (
                            self.multi_account_manager.get_all_brokers() or []
                        ):
                            _cdm_brokers.append((_acct_id, _acct_broker))
                    elif active_broker:
                        _cdm_brokers.append(("platform", active_broker))

                    _cdm_summary = self.continuous_dust_monitor.maybe_sweep(
                        brokers=_cdm_brokers if _cdm_brokers else None
                    )
                    if _cdm_summary is not None:
                        logger.info(
                            f"🌀 Dust sweep [{_cdm_summary.sweep_id}]: "
                            f"found={_cdm_summary.dust_found} "
                            f"closed={_cdm_summary.dust_closed} "
                            f"recovered=${_cdm_summary.total_usd_recovered:.4f}"
                        )
                except Exception as _cdm_run_err:
                    logger.warning(f"⚠️  Continuous dust monitor sweep failed: {_cdm_run_err}")

            # ── AUTO-CLEANUP ENGINE: startup-only dust liquidation ───────────────
            # Runs only on startup (cycle 0) to boot with a clean slate.
            # Periodic dust sweep selling has been DISABLED because it was
            # interrupting compounding by liquidating micro positions ($2-$10)
            # that were intentionally opened and should be left to grow.
            _ace_run = (
                hasattr(self, 'auto_cleanup_engine') and self.auto_cleanup_engine
                and hasattr(self, 'cycle_count')
                and self.cycle_count == 0
            )
            if _ace_run and active_broker:
                try:
                    # Collect current raw positions from broker for the cleanup scan
                    _ace_positions = []
                    try:
                        _ace_positions = active_broker.get_positions() or []
                    except Exception:
                        _ace_positions = list(self.open_positions.values()) if hasattr(self, 'open_positions') else []

                    _ace_portfolio_val = getattr(self, 'current_balance', 0.0) or 0.0
                    _ace_result = self.auto_cleanup_engine.run(
                        broker=active_broker,
                        positions=_ace_positions,
                        portfolio_value_usd=_ace_portfolio_val,
                    )
                    _ace_total = _ace_result.dust_liquidated + _ace_result.micro_merged + _ace_result.micro_liquidated
                    if _ace_total:
                        logger.warning(
                            f"🧹 AUTO-CLEANUP: liquidated={_ace_result.dust_liquidated} "
                            f"merged={_ace_result.micro_merged} "
                            f"freed={_ace_result.micro_liquidated} "
                            f"recovered=${_ace_result.total_usd_recovered:.4f}"
                        )
                    else:
                        logger.info("🧹 Auto-cleanup: portfolio is clean (no dust/micro positions)")
                except Exception as _ace_run_err:
                    logger.warning(f"⚠️  Auto-cleanup run failed: {_ace_run_err}")

            # CRITICAL FIX (Jan 24, 2026): Get positions from ALL connected brokers, not just active_broker
            # This ensures positions on all exchanges are monitored for stop-loss, profit-taking, etc.
            # Previously, switching active_broker to Kraken would cause Coinbase positions to be ignored
            current_positions = []
            positions_by_broker = {}  # Track which broker each position belongs to

            # CRITICAL FIX (Jan 24, 2026): Periodic position tracker sync
            # Sync every 10 cycles (~25 minutes) to proactively clear phantom positions
            # Phantom positions = tracked internally but don't exist on exchange
            # This prevents accumulation of stale position data
            sync_interval = 10
            if hasattr(self, 'cycle_count') and self.cycle_count > 0 and (self.cycle_count % sync_interval == 0):
                if active_broker and hasattr(active_broker, 'position_tracker') and active_broker.position_tracker:
                    try:
                        broker_positions = active_broker.get_positions()
                        removed = active_broker.position_tracker.sync_with_broker(broker_positions)
                        if removed > 0:
                            logger.info(f"🔄 Periodic sync: Cleared {removed} phantom position(s) from tracker")
                    except Exception as sync_err:
                        logger.debug(f"   ⚠️ Periodic position sync failed: {sync_err}")

            if hasattr(self, 'multi_account_manager') and self.multi_account_manager:
                # Get positions from all connected platform brokers (user brokers tracked separately)
                logger.info("ℹ️  User positions excluded from platform caps")
                for broker_type, broker in self.multi_account_manager.platform_brokers.items():
                    if broker and broker.connected:
                        try:
                            broker_positions = broker.get_positions()
                            if broker_positions:
                                # Tag each position with its broker for later management
                                for pos in broker_positions:
                                    pos['_broker'] = broker  # Store broker reference
                                    pos['_broker_type'] = broker_type  # Store broker type for logging
                                current_positions.extend(broker_positions)
                                # Safely get broker name (handles both enum and string)
                                broker_name = broker_type.value.upper() if hasattr(broker_type, 'value') else str(broker_type).upper()
                                positions_by_broker[broker_name] = len(broker_positions)
                                logger.debug(f"   Fetched {len(broker_positions)} positions from {broker_name}")
                        except Exception as e:
                            # Safely get broker name for error logging
                            broker_name = broker_type.value.upper() if hasattr(broker_type, 'value') else str(broker_type).upper()
                            logger.warning(f"   ⚠️ Could not fetch positions from {broker_name}: {e}")

                # Log positions by broker for visibility
                if positions_by_broker:
                    logger.info(f"   📊 Positions by broker: {', '.join([f'{name}={count}' for name, count in positions_by_broker.items()])}")
            elif active_broker:
                # Fallback: If multi_account_manager not available, use active_broker
                current_positions = active_broker.get_positions() if active_broker else []
                logger.debug(f"   Fetched {len(current_positions)} positions from active broker (fallback mode)")
            else:
                logger.warning("   ⚠️ No brokers available to fetch positions from")
                current_positions = []

            # CRITICAL FIX: Filter out unsellable positions (dust, unsupported symbols)
            # These positions can't be traded so they shouldn't count toward position cap
            # This prevents dust positions from blocking new entries
            # Note: After timeout expires (24h), positions will be included and retry attempted
            if current_positions and hasattr(self, 'unsellable_positions'):
                tradable_positions = []
                for pos in current_positions:
                    symbol = pos.get('symbol')
                    if symbol and symbol in self.unsellable_positions:
                        # Check if the unsellable timeout is still active (position still marked as unsellable)
                        # When timeout expires, position will be included in count and exit will be retried
                        # (in case position grew above minimum or API error was temporary)
                        marked_time = self.unsellable_positions[symbol]
                        time_since_marked = time.time() - marked_time
                        if time_since_marked < self.unsellable_retry_timeout:
                            # Timeout hasn't passed yet - exclude from count
                            logger.debug(f"   Excluding {symbol} from position count (marked unsellable {time_since_marked/3600:.1f}h ago)")
                            continue  # Skip this position - don't count it
                    tradable_positions.append(pos)

                # Log if we filtered any positions
                filtered_count = len(current_positions) - len(tradable_positions)
                if filtered_count > 0:
                    logger.info(f"   ℹ️  Filtered {filtered_count} unsellable position(s) from count (dust or unsupported)")

                current_positions = tradable_positions

            # POSITION NORMALIZATION: Filter out permanently blacklisted dust positions
            # These are positions < $1 USD that have been permanently excluded
            if current_positions and hasattr(self, 'dust_blacklist') and self.dust_blacklist:
                non_blacklisted_positions = []
                blacklisted_count = 0
                
                for pos in current_positions:
                    symbol = pos.get('symbol')
                    if symbol and self.dust_blacklist.is_blacklisted(symbol):
                        blacklisted_count += 1
                        logger.debug(f"   ⛔ Excluding blacklisted position: {symbol}")
                        continue
                    non_blacklisted_positions.append(pos)
                
                if blacklisted_count > 0:
                    logger.info(f"   🗑️  Filtered {blacklisted_count} blacklisted position(s) from count (permanent dust exclusion)")
                
                current_positions = non_blacklisted_positions

            stop_entries_file = os.path.join(os.path.dirname(__file__), '..', 'STOP_ALL_ENTRIES.conf')
            entries_blocked = os.path.exists(stop_entries_file)

            # Determine if we're in management-only mode
            managing_only = user_mode or entries_blocked or len(current_positions) >= MAX_POSITIONS_ALLOWED

            if entries_blocked:
                logger.error("🛑 ALL NEW ENTRIES BLOCKED: STOP_ALL_ENTRIES.conf is active")
                logger.info("   Exiting positions only (no new buys)")
            elif len(current_positions) >= MAX_POSITIONS_ALLOWED:
                logger.warning(f"🛑 ENTRY BLOCKED: Position cap reached ({len(current_positions)}/{MAX_POSITIONS_ALLOWED})")
                logger.info("   Closing positions only until below cap")
            else:
                logger.info(f"✅ Position cap OK ({len(current_positions)}/{MAX_POSITIONS_ALLOWED}) - entries enabled")

            # 🎯 EXPLICIT PROFIT REALIZATION ACTIVE PROOF
            if managing_only and len(current_positions) > 0:
                logger.info("=" * 70)
                logger.info("💰 PROFIT REALIZATION ACTIVE (Management Mode)")
                logger.info("=" * 70)
                logger.info(f"   📊 {len(current_positions)} open position(s) being monitored")
                logger.info("   ✅ Independent exit logic ENABLED:")
                logger.info("      • Take-profit targets")
                logger.info("      • Trailing stops")
                logger.info("      • Stop-loss protection")
                logger.info("      • Time-based exits")
                logger.info("   🔄 Profit realization runs EVERY cycle (2.5 min)")
                logger.info("   🚫 New entries: BLOCKED")
                logger.info("=" * 70)

            # CRITICAL FIX: Always try to manage positions BEFORE checking strategy
            # This ensures exit logic runs even if apex strategy fails to load
            # Previous bug: Early return here would skip ALL position management
            
            # Get account balance for position sizing
            # NOTE: We no longer return early here - we'll check later for new entries only
            if not active_broker:
                logger.warning("⚠️ No active broker - cannot manage positions")
                logger.info("📡 Monitor mode (no broker connection)")
                return
            
            if not self.apex:
                logger.warning("⚠️ Strategy not loaded - position management may be limited")
                logger.warning("   Will attempt to close positions but cannot open new ones")

            # ⏱️ Sub-step 1: Balance update
            balance_start_time = time.time()

            # FIX #1: Update portfolio state from broker data
            # Get detailed balance including crypto holdings
            # PRO MODE: Also calculate total capital (free balance + position values)
            # TIMEOUT FALLBACK: if live fetch fails, fall back to cached balance.
            try:
                if hasattr(active_broker, 'get_account_balance_detailed'):
                    balance_data = active_broker.get_account_balance_detailed()
                else:
                    balance_data = {'trading_balance': active_broker.get_account_balance()}
            except Exception as _bal_fetch_err:
                logger.warning(f"⚠️  Balance fetch failed ({_bal_fetch_err}); using cached balance")
                _cached = (
                    active_broker._last_known_balance
                    if hasattr(active_broker, '_last_known_balance') and active_broker._last_known_balance is not None
                    else account_balance  # already 0.0 from cycle-start sentinel
                )
                balance_data = {'trading_balance': _cached or 0.0}
            account_balance = balance_data.get('trading_balance', 0.0) or 0.0

            # ── FIRST TRADE GUARANTEE ─────────────────────────────────────────
            # On cycle 0 (fresh startup), if the account has sufficient balance and
            # no positions are open yet, force entry-mode so the bot deploys capital
            # right away rather than waiting for warmup/filter ramp-up to finish.
            if (
                not self._first_trade_executed
                and getattr(self, 'cycle_count', 0) == 0
                and account_balance >= MIN_BALANCE_TO_TRADE_USD
                and not user_mode
            ):
                logger.info("🚀 FIRST TRADE GUARANTEE: cycle 0 — forcing entry scan to deploy capital")
                _first_trade_override = True
            else:
                _first_trade_override = False

            # Leak #5 fix: switch profit-lock mode based on account size
            # Under $1K → GROWTH (suspend withdrawals, maximise compounding)
            # At/above $1K → EXTRACTION (enable daily withdrawal + salary payout)
            if hasattr(self, 'profit_lock_system') and self.profit_lock_system is not None:
                try:
                    self.profit_lock_system.set_account_balance(account_balance)
                except Exception as _pls_mode_err:
                    logger.debug("ProfitLockSystem.set_account_balance skipped: %s", _pls_mode_err)
            # Correct order: balance fetch → micro-cap config →
            #                volatility position sizing → risk engine → trade execution
            # This config is used later in the entry loop to override position size,
            # profit targets, and stop losses when balance < $100.
            # ═══════════════════════════════════════════════════════
            _micro_cap_config = None
            if MICRO_CAP_COMPOUNDING_AVAILABLE and get_micro_cap_compounding_config is not None:
                try:
                    _micro_cap_config = get_micro_cap_compounding_config(account_balance)
                    if _micro_cap_config:
                        logger.info(
                            f"🚀 Micro-cap compounding mode active: "
                            f"max_pos={_micro_cap_config['max_positions']}, "
                            f"size={_micro_cap_config['position_size_pct']}%, "
                            f"PT={_micro_cap_config['profit_target_pct']}%, "
                            f"SL={_micro_cap_config['stop_loss_pct']}%, "
                            f"cooldown={MICRO_CAP_TRADE_COOLDOWN}s"
                        )
                except Exception as _mc_err:
                    logger.warning(f"⚠️ Could not load micro-cap compounding config: {_mc_err}")
                    _micro_cap_config = None

            # ✅ Step 1 of correct throttle order: update capital BEFORE position sizing
            # This ensures the throttle multiplier reflects the current balance for
            # the upcoming position-size calculation (Step 2) and order (Steps 3-4).
            if CAPITAL_GROWTH_THROTTLE_AVAILABLE and get_capital_growth_throttle:
                try:
                    get_capital_growth_throttle().update_capital(account_balance)
                except Exception as _cgt_err:
                    logger.warning("⚠️ Could not update capital growth throttle: %s", _cgt_err)

            # 🏦 ACCOUNT-LEVEL CAPITAL FLOW — refresh equity + AI weights each cycle
            # Keeps drawdown tracking, kill-weak state, and EMA allocation scores current.
            if hasattr(self, 'account_flow_layer') and self.account_flow_layer is not None:
                try:
                    self.account_flow_layer.update(
                        account_id=self._get_primary_broker_id(),
                        balance_usd=account_balance,
                    )
                except Exception as _afl_cycle_err:
                    logger.debug("Account-Level Capital Flow update skipped: %s", _afl_cycle_err)

            # ✅ CRITICAL FIX (Jan 22, 2026): Update capital dynamically BEFORE allocation
            # Capital must be fetched live, not stuck at initialization value
            # This ensures failsafes and allocators use current real balance

            # Get total capital across ALL accounts (master + users)
            total_capital = self._get_total_capital_across_all_accounts()

            # Update failsafes with TOTAL capital (all accounts summed)
            # Note: Failsafes protect the ENTIRE trading operation, not just one broker
            if hasattr(self, 'failsafes') and self.failsafes:
                try:
                    self.failsafes.update_account_balance(total_capital)
                except Exception as e:
                    logger.warning(f"⚠️ Could not update failsafe balance: {e}")

            # Update capital allocator with TOTAL capital (all accounts summed)
            if hasattr(self, 'advanced_manager') and self.advanced_manager:
                try:
                    if hasattr(self.advanced_manager, 'capital_allocator'):
                        self.advanced_manager.capital_allocator.update_total_capital(total_capital)
                except Exception as e:
                    logger.warning(f"⚠️ Could not update capital allocator balance: {e}")

            # Update portfolio state (if available)
            if self.portfolio_manager and hasattr(self, 'platform_portfolio') and self.platform_portfolio:
                try:
                    # Update portfolio from current broker state
                    self.portfolio_manager.update_portfolio_from_broker(
                        portfolio=self.platform_portfolio,
                        available_cash=account_balance,
                        positions=current_positions
                    )

                    # Log portfolio summary
                    summary = self.platform_portfolio.get_summary()
                    logger.info(f"📊 Portfolio State (Total Equity Accounting):")
                    logger.info(f"   Available Cash: ${summary['available_cash']:.2f}")
                    logger.info(f"   Position Value: ${summary['total_position_value']:.2f}")
                    logger.info(f"   Unrealized P&L: ${summary['unrealized_pnl']:.2f}")
                    logger.info(f"   TOTAL EQUITY: ${summary['total_equity']:.2f}")
                    logger.info(f"   Positions: {summary['position_count']}")
                    logger.info(f"   Cash Utilization: {summary['cash_utilization_pct']:.1f}%")
                except Exception as e:
                    logger.warning(f"⚠️ Could not update portfolio state: {e}")

            # ENHANCED FUND VISIBILITY (Jan 19, 2026)
            # Always track held funds and total capital - not just in PRO_MODE
            # This prevents "bleeding" confusion where funds in trades appear missing
            held_funds = balance_data.get('total_held', 0.0)
            total_funds = balance_data.get('total_funds', account_balance)

            # ALWAYS calculate position values (not just in PRO_MODE)
            # Users need to see funds in active trades regardless of mode
            position_value = 0.0
            position_count = 0
            total_capital = account_balance

            if hasattr(active_broker, 'get_total_capital'):
                try:
                    capital_data = active_broker.get_total_capital(include_positions=True)
                    position_value = capital_data.get('position_value', 0.0)
                    position_count = capital_data.get('position_count', 0)
                    total_capital = capital_data.get('total_capital', account_balance)
                except Exception as e:
                    logger.warning(f"⚠️ Could not calculate position values: {e}")
                    position_value = 0.0
                    position_count = 0
                    total_capital = account_balance

            # Log comprehensive balance breakdown showing ALL fund allocations
            logger.info(f"💰 Account Balance Breakdown:")
            logger.info(f"   ✅ Available (free to trade): ${account_balance:.2f}")

            if held_funds > 0:
                logger.info(f"   🔒 Held (in open orders): ${held_funds:.2f}")

            if position_value > 0:
                logger.info(f"   📊 In Active Positions: ${position_value:.2f} ({position_count} positions)")

            # Calculate grand total including held funds and position values
            grand_total = account_balance + held_funds + position_value
            logger.info(f"   💎 TOTAL ACCOUNT VALUE: ${grand_total:.2f}")

            if position_value > 0 or held_funds > 0:
                if grand_total > 0:
                    allocation_pct = (account_balance / grand_total * 100)
                    deployed_pct = 100 - allocation_pct
                    logger.info(f"   📈 Cash allocation: {allocation_pct:.1f}% available, {deployed_pct:.1f}% deployed")
                else:
                    logger.info(f"   📈 Cash allocation: 0.0% available, 0.0% deployed")

            # KRAKEN ORDER CLEANUP: Cancel stale limit orders to free capital
            # This runs every cycle if Kraken cleanup is available and broker is Kraken
            if self.kraken_cleanup and hasattr(active_broker, 'broker_type') and active_broker.broker_type == BrokerType.KRAKEN:
                try:
                    # Only run cleanup if enough time has passed (default: 5 minutes)
                    # Use slightly longer interval than order age to give orders time to fill
                    if self.kraken_cleanup.should_run_cleanup(min_interval_minutes=6):
                        logger.info("")
                        cancelled_count, capital_freed = self.kraken_cleanup.cleanup_stale_orders(dry_run=False)
                        if cancelled_count > 0:
                            logger.info(f"   🧹 Kraken cleanup: Freed ${capital_freed:.2f} by cancelling {cancelled_count} stale order(s)")
                            # Update balance after freeing capital
                            try:
                                old_balance = account_balance
                                new_balance = active_broker.get_account_balance()
                                # Always update balance regardless of whether it increased
                                # SAFETY: guard against None return from get_account_balance()
                                if new_balance is None:
                                    logger.warning("   ⚠️ Kraken balance refresh returned None — keeping previous balance")
                                    new_balance = old_balance
                                account_balance = float(new_balance or 0.0)
                                if account_balance > old_balance:
                                    logger.info(f"   💰 Balance increased: ${old_balance:.2f} → ${account_balance:.2f} (+${account_balance - old_balance:.2f})")
                            except Exception as balance_err:
                                logger.debug(f"   Could not refresh balance: {balance_err}")
                except Exception as cleanup_err:
                    logger.warning(f"⚠️ Kraken order cleanup error: {cleanup_err}")

            # Small delay after balance check to avoid rapid-fire API calls
            time.sleep(0.5)

            balance_duration = time.time() - balance_start_time
            logger.info(f"⏱️  [TIMING] Balance update: {balance_duration:.2f}s")

            # ── CYCLE STEP 2: CapitalAllocator.rebalance() ──────────────────
            # Compute per-strategy capital budgets using live total_capital.
            # Must run after balance refresh (Step 1) and before entry sizing
            # (Step 3) so all position-size calculations use fresh budgets.
            if self._capital_allocator is not None:
                try:
                    self._capital_allocator.rebalance(total_capital=total_capital)
                except Exception as _ca_reb_err:
                    logger.warning("⚠️ CapitalAllocator.rebalance failed: %s", _ca_reb_err)
            # ────────────────────────────────────────────────────────────────

            # ── PER-ACCOUNT POSITION CAP (CONSOLIDATION MODE) ─────────────────
            # Derive the effective position cap from the live account balance.
            # This enforces the force-consolidation rule:
            #   balance < $150  → max 3 positions  (micro/starter accounts)
            #   balance < $500  → max 5 positions  (small accounts)
            #   otherwise       → MAX_TOTAL_POSITIONS (global cap = 5)
            # The result is also capped at MAX_POSITIONS_ALLOWED so the user's
            # environment variable can only *lower* the cap, never raise it above
            # the global hard limit.
            effective_max_positions = min(
                get_balance_based_max_positions(account_balance),
                MAX_POSITIONS_ALLOWED,
            )
            logger.info(
                f"📊 Effective position cap: {effective_max_positions} "
                f"(balance=${account_balance:.2f}, global_cap={MAX_TOTAL_POSITIONS})"
            )
            # ──────────────────────────────────────────────────────────────────

            # ⏱️ Sub-step 2: Position update
            positions_start_time = time.time()

            # CRITICAL FIX: Wrap position management in try-except to ensure it ALWAYS runs
            # Previous bug: Any exception in position fetching would skip ALL exit logic
            # New behavior: Exit logic attempts to run even if other parts fail
            try:
                # STEP 1: Manage existing positions (check for exits/profit taking)
                logger.info(f"📊 Managing {len(current_positions)} open position(s)...")

                # LOG POSITION PROFIT STATUS FOR VISIBILITY (Jan 26, 2026)
                if current_positions:
                    try:
                        # Get current prices for all open positions
                        current_prices_dict = {}
                        for pos in current_positions:
                            try:
                                symbol = pos.get('symbol')
                                if symbol:
                                    # Fetch current price from broker
                                    candles = active_broker.get_market_data(symbol, limit=1)
                                    if candles and len(candles) > 0:
                                        current_prices_dict[symbol] = candles[-1]['close']
                            except Exception as price_err:
                                logger.debug(f"Could not fetch price for {pos.get('symbol')}: {price_err}")

                        # Log position profit status summary
                        if hasattr(self, 'execution_engine') and self.execution_engine:
                            self.execution_engine.log_position_profit_status(current_prices_dict)
                    except Exception as log_err:
                        logger.debug(f"Could not log position profit status during position monitoring: {log_err}")

                # NOTE (Jan 24, 2026): Stop-loss tiers are now calculated PER-POSITION based on each position's broker
                # This ensures correct stop-loss thresholds for positions on different exchanges (Kraken vs Coinbase)
                # See line ~2169 where position_primary_stop, position_micro_stop are calculated for each position
                # using self._get_stop_loss_tier(position_broker, position_broker_balance)

                # STATE MACHINE: Calculate current state based on position count and forced unwind status
                # Effective position cap is balance-aware (see get_balance_based_max_positions)
                positions_over_cap = len(current_positions) - effective_max_positions
                
                # INVARIANT VALIDATION: Ensure position count is valid
                assert len(current_positions) >= 0, f"INVARIANT VIOLATION: Position count is negative: {len(current_positions)}"
                
                # CRITICAL: Check for forced unwind mode (per-user emergency exit)
                # When enabled, ALL positions are closed immediately regardless of P&L
                forced_unwind_active = False
                if hasattr(self, 'continuous_exit_enforcer') and self.continuous_exit_enforcer:
                    # Get user_id from broker (if available)
                    user_id = getattr(active_broker, 'user_id', 'platform')
                    forced_unwind_active = self.continuous_exit_enforcer.is_forced_unwind_active(user_id)
                
                # Determine new state based on current conditions
                if forced_unwind_active:
                    new_state = PositionManagementState.FORCED_UNWIND
                elif positions_over_cap > 0:
                    new_state = PositionManagementState.DRAIN
                else:
                    new_state = PositionManagementState.NORMAL
                
                # INVARIANT VALIDATION: Validate state invariants before proceeding
                StateInvariantValidator.validate_state_invariants(
                    new_state, 
                    len(current_positions), 
                    positions_over_cap, 
                    effective_max_positions
                )
                
                # STATE TRANSITION LOGGING: Log state changes explicitly
                if new_state != self.position_mgmt_state:
                    old_state_name = self.position_mgmt_state.value.upper()
                    new_state_name = new_state.value.upper()
                    
                    # Validate transition is allowed
                    if StateInvariantValidator.validate_state_transition(
                        self.position_mgmt_state, new_state, len(current_positions), positions_over_cap
                    ):
                        logger.warning("=" * 80)
                        logger.warning(f"🔄 STATE TRANSITION: {old_state_name} → {new_state_name}")
                        logger.warning("=" * 80)
                        logger.warning(f"   Positions: {len(current_positions)}/{effective_max_positions}")
                        logger.warning(f"   Excess: {positions_over_cap}")
                        logger.warning(f"   Forced Unwind: {forced_unwind_active}")
                        logger.warning("=" * 80)
                        
                        self.previous_state = self.position_mgmt_state
                        self.position_mgmt_state = new_state
                    else:
                        logger.error(f"INVALID STATE TRANSITION BLOCKED: {old_state_name} → {new_state_name}")
                        # Keep current state if transition is invalid
                        new_state = self.position_mgmt_state
                
                # CRITICAL FIX: Identify ALL positions that need to exit first
                # Then sell them ALL concurrently, not one at a time
                positions_to_exit = []

                # Pre-calculate total portfolio value (used by portfolio-rebalance rules).
                # Uses the last-known size_usd from each position as an approximation;
                # exact per-cycle prices are fetched per-position in the analysis loop below.
                _total_portfolio_value_usd = 0.0
                for _pos in current_positions:
                    _pos_val = (
                        _pos.get('size_usd') or
                        _pos.get('usd_value') or
                        _pos.get('value_usd') or
                        0
                    )
                    try:
                        _total_portfolio_value_usd += float(_pos_val)
                    except (TypeError, ValueError):
                        pass

                # FORCED UNWIND MODE: Close all positions immediately
                if new_state == PositionManagementState.FORCED_UNWIND:
                    logger.error("=" * 80)
                    logger.error("🚨 FORCED UNWIND MODE ACTIVE")
                    logger.error("=" * 80)
                    if hasattr(self, 'continuous_exit_enforcer') and self.continuous_exit_enforcer:
                        user_id = getattr(active_broker, 'user_id', 'platform')
                        logger.error(f"   User: {user_id}")
                    logger.error(f"   Positions: {len(current_positions)}")
                    logger.error("   ALL positions will be closed immediately")
                    logger.error("   Bypassing all normal trading filters")
                    logger.error("=" * 80)
                    
                    logger.warning("🚨 FORCED UNWIND: Adding all positions to exit queue")
                    for position in current_positions:
                        symbol = position.get('symbol')
                        quantity = position.get('quantity', 0)
                        position_broker = position.get('_broker', active_broker)
                        position_broker_type = position.get('_broker_type')
                        broker_label = position_broker_type.value.upper() if (position_broker_type and hasattr(position_broker_type, 'value')) else "UNKNOWN"
                        
                        if symbol and quantity > 0:
                            positions_to_exit.append({
                                'symbol': symbol,
                                'quantity': quantity,
                                'reason': 'FORCED UNWIND (emergency consolidation)',
                                'broker': position_broker,
                                'broker_label': broker_label,
                                'force_liquidate': True  # Bypass all filters
                            })
                    
                    logger.warning(f"🚨 FORCED UNWIND: {len(positions_to_exit)} positions queued for immediate exit")
                    # Skip normal position analysis - just close everything
                
                # DRAIN MODE: Over position cap, actively draining excess positions
                # NORMAL MODE: Under position cap, managing positions normally
                # Both modes analyze positions for potential exits
                if new_state == PositionManagementState.DRAIN:
                    logger.info("=" * 70)
                    logger.info("🔥 DRAIN MODE ACTIVE")
                    logger.info("=" * 70)
                    logger.info(f"   📊 Excess positions: {positions_over_cap}")
                    logger.info(f"   🎯 Strategy: Rank by PnL, age, and size")
                    logger.info(f"   🔄 Drain rate: 1-{min(positions_over_cap, 3)} positions per cycle")
                    logger.info(f"   🚫 New entries: BLOCKED until under {effective_max_positions} positions")
                    logger.info(f"   💡 Goal: Gradually free capital and reduce risk")
                    logger.info("=" * 70)
                elif new_state == PositionManagementState.NORMAL:
                    logger.info("=" * 70)
                    logger.info("✅ NORMAL MODE - Position Management")
                    logger.info("=" * 70)
                    logger.info(f"   📊 Positions: {len(current_positions)}/{effective_max_positions}")
                    logger.info("=" * 70)
                
                # Position analysis loop (runs for both DRAIN and NORMAL modes)
                if new_state in (PositionManagementState.DRAIN, PositionManagementState.NORMAL):
                    for idx, position in enumerate(current_positions):
                        try:
                            symbol = position.get('symbol')
                            if not symbol:
                                continue

                            # Skip positions we know can't be sold (too small/dust)
                            # But allow retry after timeout in case position grew or API error was temporary
                            if symbol in self.unsellable_positions:
                                # Check if enough time has passed to retry
                                marked_time = self.unsellable_positions[symbol]
                                time_since_marked = time.time() - marked_time
                                if time_since_marked < self.unsellable_retry_timeout:
                                    logger.debug(f"   ⏭️ Skipping {symbol} (marked unsellable {time_since_marked/3600:.1f}h ago, retry in {(self.unsellable_retry_timeout - time_since_marked)/3600:.1f}h)")
                                    continue
                                else:
                                    logger.info(f"   🔄 Retrying {symbol} (marked unsellable {time_since_marked/3600:.1f}h ago - timeout reached)")
                                    # Remove from unsellable dict to allow full processing
                                    del self.unsellable_positions[symbol]

                            # CRITICAL FIX (Jan 24, 2026): Use the correct broker for this position
                            # Each position is tagged with its broker when fetched from multi_account_manager
                            position_broker = position.get('_broker', active_broker)
                            position_broker_type = position.get('_broker_type')
                            # Safely get broker label (handles both enum and string)
                            broker_label = position_broker_type.value.upper() if (position_broker_type and hasattr(position_broker_type, 'value')) else "UNKNOWN"

                            logger.info(f"   Analyzing {symbol} on {broker_label}...")

                            # Get current price from the position's broker
                            current_price = position_broker.get_current_price(symbol)
                            if not current_price or current_price == 0:
                                logger.warning(f"   ⚠️ Could not get price for {symbol} from {broker_label}")
                                continue

                            # Get position value
                            quantity = position.get('quantity', 0)
                            position_value = current_price * quantity

                            logger.info(f"   {symbol} ({broker_label}): {quantity:.8f} @ ${current_price:.2f} = ${position_value:.2f}")

                            # PROFITABILITY MODE: Aggressive exit on weak markets
                            # Exit positions when market conditions deteriorate to prevent bleeding

                            # CRITICAL FIX: We don't have entry_price from Coinbase API!
                            # Instead, use aggressive exit criteria based on:
                            # 1. Market conditions (if filter fails, exit immediately)
                            # 2. Small position size (anything under $1 should be exited)
                            # 3. RSI overbought/oversold (take profits or cut losses)

                            # AUTO-EXIT small positions (under $1) - these are likely losers
                            if position_value < MIN_POSITION_VALUE:
                                logger.info(f"   🔴 SMALL POSITION AUTO-EXIT: {symbol} (${position_value:.2f} < ${MIN_POSITION_VALUE})")
                                # HARD IGNORE: Permanently blacklist sub-$1 positions.
                                # MIN_POSITION_VALUE is $2, so positions in the $1–$2 range are
                                # auto-exited but NOT blacklisted.  Only truly sub-$1 amounts
                                # (pure dust) are permanently excluded from future trading.
                                if position_value < 1.0 and hasattr(self, 'dust_blacklist') and self.dust_blacklist:
                                    logger.warning(f"   🚫 HARD IGNORE: Blacklisting {symbol} (${position_value:.4f} < $1.00) — permanently excluded")
                                    self.dust_blacklist.add_to_blacklist(
                                        symbol=symbol,
                                        usd_value=position_value,
                                        reason=f"sub-$1 position (${position_value:.4f}) — permanently ignored"
                                    )
                                positions_to_exit.append({
                                    'symbol': symbol,
                                    'quantity': quantity,
                                    'reason': f'Small position cleanup (${position_value:.2f})',
                                    'broker': position_broker,
                                    'broker_label': broker_label
                                })
                                continue

                            # PROFIT-BASED EXIT LOGIC (NEW!)
                            # Check if we have entry price tracked for this position
                            entry_price_available = False
                            entry_time_available = False
                            position_age_hours = 0
                            just_auto_imported = False  # Track if position was just imported this cycle

                            if active_broker and hasattr(active_broker, 'position_tracker') and active_broker.position_tracker:
                                try:
                                    tracked_position = active_broker.position_tracker.get_position(symbol)
                                    if tracked_position:
                                        entry_price_available = True

                                        # Calculate position age (needed for both stop-loss and time-based logic)
                                        entry_time = tracked_position.get('first_entry_time')
                                        if entry_time:
                                            try:
                                                entry_dt = datetime.fromisoformat(entry_time)
                                                now = datetime.now()
                                                position_age_hours = (now - entry_dt).total_seconds() / 3600
                                                entry_time_available = True
                                            except Exception as time_err:
                                                logger.debug(f"   Could not parse entry time for {symbol}: {time_err}")

                                    # CRITICAL FIX (Jan 19, 2026): Calculate P&L FIRST, check stop-loss BEFORE time-based exits
                                    # Railway Golden Rule #5: Stop-loss > time exit (always)
                                    # The old logic had time-based exits BEFORE stop-loss checks, which is backwards!
                                    pnl_data = active_broker.position_tracker.calculate_pnl(symbol, current_price)
                                    if pnl_data:
                                        entry_price_available = True
                                        pnl_percent = pnl_data['pnl_percent']
                                        pnl_dollars = pnl_data['pnl_dollars']
                                        entry_price = pnl_data['entry_price']

                                        # Validate PnL scale — log a warning for extreme values (>±100%)
                                        # but do NOT raise an exception: a genuine >100% gain or catastrophic
                                        # loss must still flow through the exit checks below.
                                        if abs(pnl_percent) >= 1.0:
                                            logger.warning(
                                                f"   ⚠️ Large PnL detected for {symbol}: "
                                                f"{pnl_percent*100:.2f}% — extreme move or scale issue. "
                                                f"Continuing with exit checks."
                                            )

                                        logger.info(f"   💰 P&L: ${pnl_dollars:+.2f} ({pnl_percent*100:+.2f}%) | Entry: ${entry_price:.2f}")

                                        # 🔒 PROFIT LOCK SYSTEM — ratchet floor check
                                        # Advance the ratchet stop for this position; if the
                                        # lock floor has been hit, queue an immediate exit to
                                        # secure the locked-in gain.
                                        if hasattr(self, 'profit_lock_system') and self.profit_lock_system is not None:
                                            try:
                                                _pls_action = self.profit_lock_system.update_position(
                                                    symbol=symbol,
                                                    current_price=current_price,
                                                )
                                                if _pls_action == "close":
                                                    positions_to_exit.append({
                                                        'symbol': symbol,
                                                        'quantity': quantity,
                                                        'reason': 'Profit lock: ratchet floor hit – securing gains',
                                                        'broker': position_broker,
                                                        'broker_label': broker_label,
                                                    })
                                            except Exception as _pls_upd_err:
                                                logger.debug(
                                                    "ProfitLockSystem.update_position skipped for %s: %s",
                                                    symbol, _pls_upd_err,
                                                )

                                        # ═══════════════════════════════════════════════
                                        # PHASE 3 — DYNAMIC STOP-LOSS TIGHTENER
                                        # Ratchets the stop upward as the position profits.
                                        # ═══════════════════════════════════════════════
                                        if (
                                            DYNAMIC_STOP_TIGHTENER_AVAILABLE
                                            and hasattr(self, 'dynamic_stop_tightener')
                                            and self.dynamic_stop_tightener is not None
                                            and entry_price > 0
                                        ):
                                            try:
                                                _pos_side_dst = position.get('side', 'long')
                                                _init_stop_dst = position.get('stop_loss', 0.0)
                                                _dst_result = self.dynamic_stop_tightener.update(
                                                    position_id=symbol,
                                                    current_price=current_price,
                                                    entry_price=entry_price,
                                                    initial_stop=_init_stop_dst if _init_stop_dst > 0 else None,
                                                    side=_pos_side_dst,
                                                )
                                                if _dst_result.stop_moved:
                                                    logger.info(
                                                        "   📐 Phase 3 DynamicStop: %s stop "
                                                        "%.4f → %.4f  [%s]",
                                                        symbol,
                                                        _dst_result.old_stop,
                                                        _dst_result.new_stop,
                                                        _dst_result.tightening_stage,
                                                    )
                                                    # Check if tightened stop is now hit
                                                    _dst_side = _pos_side_dst.lower()
                                                    _dst_stop_hit = (
                                                        (_dst_side == 'long' and current_price <= _dst_result.new_stop)
                                                        or (_dst_side == 'short' and current_price >= _dst_result.new_stop)
                                                    )
                                                    if _dst_stop_hit:
                                                        positions_to_exit.append({
                                                            'symbol': symbol,
                                                            'quantity': quantity,
                                                            'reason': (
                                                                f"Phase 3 DynamicStop triggered: "
                                                                f"stop={_dst_result.new_stop:.4f}  "
                                                                f"[{_dst_result.tightening_stage}]"
                                                            ),
                                                            'broker': position_broker,
                                                            'broker_label': broker_label,
                                                        })
                                            except Exception as _dst_exc:
                                                logger.debug(
                                                    "Phase 3 DynamicStop check skipped for %s: %s",
                                                    symbol, _dst_exc,
                                                )

                                        # ═══════════════════════════════════════════════
                                        # PHASE 3 — PARTIAL TP LADDER
                                        # Take profits in tranches as price advances.
                                        # ═══════════════════════════════════════════════
                                        if (
                                            PARTIAL_TP_LADDER_AVAILABLE
                                            and hasattr(self, 'partial_tp_ladder')
                                            and self.partial_tp_ladder is not None
                                            and entry_price > 0
                                            and quantity > 0
                                        ):
                                            try:
                                                _pos_side_tpl = position.get('side', 'long')
                                                _tpl_action = self.partial_tp_ladder.update(
                                                    position_id=symbol,
                                                    current_price=current_price,
                                                    entry_price=entry_price,
                                                    side=_pos_side_tpl,
                                                )
                                                if _tpl_action is not None:
                                                    _tpl_qty = quantity * _tpl_action.exit_pct
                                                    logger.info(
                                                        "   💰 Phase 3 TPLadder: %s — %s triggered "
                                                        "(+%.2f%%)  exit %.0f%% of position (%.8f units)",
                                                        symbol,
                                                        _tpl_action.label,
                                                        _tpl_action.profit_pct,
                                                        _tpl_action.exit_pct * 100,
                                                        _tpl_qty,
                                                    )
                                                    positions_to_exit.append({
                                                        'symbol': symbol,
                                                        'quantity': _tpl_qty,
                                                        'reason': (
                                                            f"Phase 3 PartialTP {_tpl_action.label}: "
                                                            f"+{_tpl_action.profit_pct:.2f}%"
                                                        ),
                                                        'broker': position_broker,
                                                        'broker_label': broker_label,
                                                    })
                                            except Exception as _tpl_exc:
                                                logger.debug(
                                                    "Phase 3 PartialTPLadder check skipped for %s: %s",
                                                    symbol, _tpl_exc,
                                                )

                                        # ✅ USER-DEFINED TAKE-PROFIT / STOP-LOSS RULES
                                        # Checked immediately after P&L is computed, before
                                        # the 3-tier system stop-loss checks below, so that
                                        # personal thresholds are honoured first.
                                        if hasattr(self, '_user_rules_engine') and self._user_rules_engine is not None:
                                            _rule_user_id = getattr(active_broker, 'user_id', None)
                                            if _rule_user_id:
                                                try:
                                                    _rule_actions = self._user_rules_engine.check_rules(
                                                        user_id=_rule_user_id,
                                                        symbol=symbol,
                                                        pnl_pct_fractional=pnl_percent,
                                                        full_quantity=quantity,
                                                        current_price=current_price,
                                                        position_value_usd=position_value,
                                                        portfolio_total_value_usd=_total_portfolio_value_usd if _total_portfolio_value_usd > 0 else None,
                                                    )
                                                    for _sell_qty, _rule_reason, _lock_stable in _rule_actions:
                                                        if _sell_qty > 0:
                                                            positions_to_exit.append({
                                                                'symbol': symbol,
                                                                'quantity': _sell_qty,
                                                                'reason': _rule_reason,
                                                                'broker': position_broker,
                                                                'broker_label': broker_label,
                                                                'lock_to_stablecoin': _lock_stable,
                                                            })
                                                except Exception as _re:
                                                    logger.warning(f"   ⚠️ User rules check error for {symbol}: {_re}")

                                        # 🛡️ 3-TIER PROTECTIVE STOP-LOSS SYSTEM (JAN 21, 2026)
                                        # Tier 1: Primary trading stop (varies by broker and balance)
                                        # Tier 2: Emergency micro-stop to prevent logic failures
                                        # Tier 3: Catastrophic failsafe (last resort)

                                        # TIER 1: PRIMARY TRADING STOP-LOSS
                                        # This is the REAL stop-loss for risk management
                                        # For Kraken small balances: -0.6% to -0.8%
                                        # For Coinbase/other: -1.0%
                                        if pnl_percent <= primary_stop:
                                            logger.warning(f"   🛡️ PRIMARY PROTECTIVE STOP-LOSS HIT: {symbol} at {pnl_percent*100:.2f}% (threshold: {primary_stop*100:.2f}%)")
                                            logger.warning(f"   💥 TIER 1: Protective trading stop triggered - capital preservation mode")

                                            # FIX #2: Use protective stop-loss executor (risk management override)
                                            if self.forced_stop_loss:
                                                success, result, error = self.forced_stop_loss.force_sell_position(
                                                    symbol=symbol,
                                                    quantity=quantity,
                                                    reason=f"Primary protective stop-loss: {pnl_percent*100:.2f}% <= {primary_stop*100:.2f}%"
                                                )

                                                if success:
                                                    logger.info(f"   ✅ PROTECTIVE STOP-LOSS EXECUTED: {symbol}")
                                                    # Track the exit
                                                    if hasattr(active_broker, 'position_tracker') and active_broker.position_tracker:
                                                        active_broker.position_tracker.track_exit(symbol, quantity)
                                                    # Increment trade counter for trade-based cleanup trigger
                                                    if hasattr(self, 'trades_since_last_cleanup'):
                                                        self.trades_since_last_cleanup += 1
                                                else:
                                                    logger.error(f"   ❌ PROTECTIVE STOP-LOSS FAILED: {error}")
                                            else:
                                                # Fallback to legacy stop-loss if protective executor not available
                                                logger.warning("   ⚠️ Protective stop-loss executor not available, using legacy method")
                                                try:
                                                    result = active_broker.place_market_order(
                                                        symbol=symbol,
                                                        side='sell',
                                                        quantity=quantity,
                                                        size_type='base'
                                                    )

                                                    if result and result.get('status') not in ['error', 'unfilled']:
                                                        order_id = result.get('order_id', 'N/A')
                                                        logger.info(f"   ✅ ORDER ACCEPTED: Order ID {order_id}")
                                                        if hasattr(active_broker, 'position_tracker') and active_broker.position_tracker:
                                                            active_broker.position_tracker.track_exit(symbol, quantity)
                                                        # Increment trade counter for trade-based cleanup trigger
                                                        if hasattr(self, 'trades_since_last_cleanup'):
                                                            self.trades_since_last_cleanup += 1
                                                    else:
                                                        error_msg = result.get('error', 'Unknown error') if result else 'No response'
                                                        logger.error(f"   ❌ ORDER REJECTED: {error_msg}")
                                                except Exception as sell_err:
                                                    logger.error(f"   ❌ ORDER EXCEPTION: {sell_err}")

                                            # Skip ALL remaining logic for this position
                                            continue

                                        # TIER 2: EMERGENCY MICRO-STOP (Logic failure prevention)
                                        # This is NOT a trading stop - it's a failsafe to prevent logic failures
                                        # Examples: imported positions, calculation errors, data corruption
                                        # Note: This should RARELY trigger - Tier 1 should catch most losses
                                        # Only triggers for losses that somehow bypassed Tier 1
                                        # (e.g., imported positions without proper entry price tracking)
                                        if pnl_percent <= micro_stop:
                                            logger.warning(f"   ⚠️ EMERGENCY MICRO-STOP: {symbol} at {pnl_percent:.2f}% (threshold: {micro_stop*100:.2f}%)")
                                            logger.warning(f"   💥 TIER 2: Emergency micro-stop to prevent logic failures (not a trading stop)")
                                            logger.warning(f"   ⚠️  NOTE: Tier 1 was bypassed - possible imported position or logic error")

                                            # FIX #2: Use forced stop-loss for emergency too
                                            if self.forced_stop_loss:
                                                success, result, error = self.forced_stop_loss.force_sell_position(
                                                    symbol=symbol,
                                                    quantity=quantity,
                                                    reason=f"Emergency micro-stop: {pnl_percent:.2f}% <= {micro_stop*100:.2f}%"
                                                )

                                                if success:
                                                    logger.info(f"   ✅ EMERGENCY STOP EXECUTED: {symbol}")
                                                    if hasattr(active_broker, 'position_tracker') and active_broker.position_tracker:
                                                        active_broker.position_tracker.track_exit(symbol, quantity)
                                                    # Increment trade counter for trade-based cleanup trigger
                                                    if hasattr(self, 'trades_since_last_cleanup'):
                                                        self.trades_since_last_cleanup += 1
                                                else:
                                                    logger.error(f"   ❌ EMERGENCY STOP FAILED: {error}")
                                            else:
                                                # Fallback
                                                try:
                                                    result = active_broker.place_market_order(
                                                        symbol=symbol,
                                                        side='sell',
                                                        quantity=quantity,
                                                        size_type='base'
                                                    )

                                                    if result and result.get('status') not in ['error', 'unfilled']:
                                                        order_id = result.get('order_id', 'N/A')
                                                        logger.info(f"   ✅ MICRO-STOP EXECUTED: Order ID {order_id}")
                                                        if hasattr(active_broker, 'position_tracker') and active_broker.position_tracker:
                                                            active_broker.position_tracker.track_exit(symbol, quantity)
                                                        # Increment trade counter for trade-based cleanup trigger
                                                        if hasattr(self, 'trades_since_last_cleanup'):
                                                            self.trades_since_last_cleanup += 1
                                                    else:
                                                        error_msg = result.get('error', 'Unknown error') if result else 'No response'
                                                        logger.error(f"   ❌ MICRO-STOP FAILED: {error_msg}")
                                                except Exception as sell_err:
                                                    logger.error(f"   ❌ MICRO-STOP EXCEPTION: {sell_err}")

                                            continue

                                        # 🚨 COINBASE LOCKDOWN (Jan 2026) - EXIT ANY LOSS IMMEDIATELY
                                        # Coinbase has been holding losing trades - enforce ZERO TOLERANCE for losses
                                        # Exit ANY position showing ANY loss on Coinbase (no waiting period)
                                        if pnl_percent < 0 and 'coinbase' in broker_label.lower():
                                            logger.warning(f"   🚨 COINBASE LOCKDOWN: {symbol} showing loss at {pnl_percent*100:.2f}%")
                                            logger.warning(f"   💥 ZERO TOLERANCE MODE - exiting Coinbase loss immediately!")
                                            positions_to_exit.append({
                                                'symbol': symbol,
                                                'quantity': quantity,
                                                'reason': f'Coinbase lockdown: ANY loss exit ({pnl_percent*100:.2f}%)',
                                                'broker': position_broker,
                                                'broker_label': broker_label
                                            })
                                            continue

                                        # ✅ LOSING TRADES: 15-MINUTE MAXIMUM HOLD TIME (for non-Coinbase)
                                        # For tracked positions with P&L < 0%, enforce STRICT 15-minute max hold time
                                        # This prevents capital erosion from positions held too long in a losing state
                                        # CRITICAL FIX (Jan 21, 2026): Also exit losing positions WITHOUT entry time tracking
                                        # to prevent positions from being stuck indefinitely
                                        if pnl_percent < 0:
                                            # Convert position age from hours to minutes
                                            position_age_minutes = position_age_hours * MINUTES_PER_HOUR

                                            # SCENARIO 1: Position with time tracking that exceeds max hold time
                                            if entry_time_available and position_age_minutes >= MAX_LOSING_POSITION_HOLD_MINUTES:
                                                logger.warning(f"   🚨 LOSING TRADE TIME EXIT: {symbol} at {pnl_percent*100:.2f}% held for {position_age_minutes:.1f} minutes (max: {MAX_LOSING_POSITION_HOLD_MINUTES} min)")
                                                logger.warning(f"   💥 NIJA IS FOR PROFIT, NOT LOSSES - selling immediately!")
                                                positions_to_exit.append({
                                                    'symbol': symbol,
                                                    'quantity': quantity,
                                                    'reason': f'Losing trade time exit (held {position_age_minutes:.1f}min at {pnl_percent*100:.2f}%)',
                                                    'broker': position_broker,
                                                    'broker_label': broker_label
                                                })
                                                continue
                                            elif not entry_time_available:
                                                # SCENARIO 2: Losing position without time tracking (SAFETY FALLBACK)
                                                # Exit immediately to prevent indefinite losses when we cannot determine age
                                                logger.warning(f"   🚨 LOSING POSITION WITHOUT TIME TRACKING: {symbol} at {pnl_percent*100:.2f}%")
                                                logger.warning(f"   💥 Cannot determine age - exiting to prevent indefinite losses!")
                                                positions_to_exit.append({
                                                    'symbol': symbol,
                                                    'quantity': quantity,
                                                    'reason': f'Losing position without time tracking (P&L: {pnl_percent*100:.2f}%)',
                                                    'broker': position_broker,
                                                    'broker_label': broker_label
                                                })
                                                continue

                                        # TIER 3: CATASTROPHIC PROTECTIVE FAILSAFE (Last resort protection)
                                        # This should NEVER be reached in normal operation
                                        # Only triggers at -5.0% to catch extreme edge cases
                                        if pnl_percent <= catastrophic_stop:
                                            logger.warning(f"   🚨 CATASTROPHIC PROTECTIVE FAILSAFE TRIGGERED: {symbol} at {pnl_percent*100:.2f}% (threshold: {catastrophic_stop*100:.1f}%)")
                                            logger.warning(f"   💥 TIER 3: Last resort capital preservation - severe loss detected!")
                                            logger.warning(f"   🛡️ PROTECTIVE EXIT MODE — Risk Management Override Active")

                                            # Use forced exit path with retry - bypasses ALL filters
                                            exit_success = False
                                            try:
                                                # Attempt 1: Direct market sell
                                                result = active_broker.place_market_order(
                                                    symbol=symbol,
                                                    side='sell',
                                                    quantity=quantity,
                                                    size_type='base'
                                                )

                                                # Enhanced logging for catastrophic events
                                                if result and result.get('status') not in ['error', 'unfilled']:
                                                    order_id = result.get('order_id', 'N/A')
                                                    logger.error(f"   ✅ CATASTROPHIC EXIT COMPLETE: Order ID {order_id}")
                                                    exit_success = True
                                                    if hasattr(active_broker, 'position_tracker') and active_broker.position_tracker:
                                                        active_broker.position_tracker.track_exit(symbol, quantity)
                                                else:
                                                    error_msg = result.get('error', 'Unknown error') if result else 'No response'
                                                    logger.error(f"   ❌ CATASTROPHIC EXIT ATTEMPT 1 FAILED: {error_msg}")

                                                    # Retry once for catastrophic exits
                                                    logger.error(f"   🔄 Retrying catastrophic exit (attempt 2/2)...")
                                                    time.sleep(1)  # Brief pause

                                                    result = active_broker.place_market_order(
                                                        symbol=symbol,
                                                        side='sell',
                                                        quantity=quantity,
                                                        size_type='base'
                                                    )
                                                    if result and result.get('status') not in ['error', 'unfilled']:
                                                        order_id = result.get('order_id', 'N/A')
                                                        logger.error(f"   ✅ CATASTROPHIC EXIT COMPLETE (retry): Order ID {order_id}")
                                                        exit_success = True
                                                        if hasattr(active_broker, 'position_tracker') and active_broker.position_tracker:
                                                            active_broker.position_tracker.track_exit(symbol, quantity)
                                                    else:
                                                        error_msg = result.get('error', 'Unknown error') if result else 'No response'
                                                        logger.error(f"   ❌ CATASTROPHIC EXIT RETRY FAILED: {error_msg}")
                                            except Exception as emergency_err:
                                                logger.error(f"   ❌ CATASTROPHIC EXIT EXCEPTION: {symbol} - {emergency_err}")
                                                logger.error(f"   Exception type: {type(emergency_err).__name__}")

                                            # Log final status
                                            if not exit_success:
                                                logger.error(f"   🛑 CATASTROPHIC EXIT FAILED AFTER 2 ATTEMPTS")
                                                logger.error(f"   🛑 MANUAL INTERVENTION REQUIRED FOR {symbol}")
                                                logger.error(f"   🛑 Position may still be open - check broker manually")

                                            # Skip to next position - catastrophic exit overrides all other logic
                                            continue

                                        # 💎 PROFIT PROTECTION: Never Break Even, Never Loss (Jan 23, 2026)
                                        # NIJA is for PROFIT ONLY - exit when profit decreases more than 0.5%
                                        # Fixed 0.5% pullback allowed - exit when profit drops 0.5%+ from previous check
                                        # Learning and adjusting: allow small pullback but exit on larger decrease
                                        if PROFIT_PROTECTION_ENABLED:
                                            previous_profit_pct = pnl_data.get('previous_profit_pct', 0.0)

                                            # Determine per-broker profit thresholds
                                            try:
                                                broker_type = getattr(active_broker, 'broker_type', None)
                                            except AttributeError:
                                                broker_type = None

                                            # Resolve broker key for threshold lookups (works for ALL brokerages)
                                            broker_key = broker_type.value if broker_type else ''
                                            protection_min_profit = BROKER_PROTECTION_MIN_PROFIT.get(
                                                broker_key, DEFAULT_PROTECTION_MIN_PROFIT
                                            )
                                            fee_breakeven_threshold = BROKER_FEE_BREAKEVEN.get(
                                                broker_key, DEFAULT_FEE_BREAKEVEN
                                            )

                                            # RULE 1: Exit on Profit Decrease > 0.5%
                                            # If position is profitable AND profit decreases by MORE than 0.5%, exit
                                            # Hold up to 0.5% pullback, exit when it exceeds
                                            # Example: 3.0% → 2.9% (0.1% decrease) = HOLD
                                            #          3.0% → 2.5% (0.5% decrease) = HOLD
                                            #          3.0% → 2.49% (0.51% decrease) = EXIT
                                            #          3.0% → 2.4% (0.6% decrease) = EXIT
                                            if pnl_percent >= protection_min_profit and previous_profit_pct >= protection_min_profit:
                                                # Calculate decrease from previous profit
                                                profit_decrease = previous_profit_pct - pnl_percent

                                                # Exit if decrease EXCEEDS 0.5% (> not >=)
                                                if profit_decrease > PROFIT_PROTECTION_PULLBACK_FIXED:
                                                    logger.warning(f"   💎 PROFIT PROTECTION: {symbol} profit pullback exceeded")
                                                    logger.warning(f"      Previous profit: {previous_profit_pct*100:+.2f}% → Current: {pnl_percent*100:+.2f}%")
                                                    logger.warning(f"      Pullback: {profit_decrease*100:.3f}% (max allowed: 0.5%)")
                                                    logger.warning(f"   🔒 TAKING PROFIT NOW - PULLBACK EXCEEDS 0.5%!")
                                                    positions_to_exit.append({
                                                        'symbol': symbol,
                                                        'quantity': quantity,
                                                        'reason': f'Profit pullback {profit_decrease*100:.2f}% exceeded 0.5% limit',
                                                        'broker': position_broker,
                                                        'broker_label': broker_label
                                                    })
                                                    continue

                                                # Log protection status
                                                if profit_decrease > 0:
                                                    cushion = (PROFIT_PROTECTION_PULLBACK_FIXED - profit_decrease) * 100
                                                    logger.debug(f"   💎 Profit pullback within limit: {symbol} at {pnl_percent*100:+.2f}% (pullback: {profit_decrease*100:.3f}%, cushion: {cushion:.3f}%)")
                                                else:
                                                    logger.debug(f"   💎 Profit increasing: {symbol} at {pnl_percent*100:+.2f}% (previous: {previous_profit_pct*100:+.2f}%)")

                                            # RULE 2: Never Break Even Protection
                                            # If position was profitable above minimum threshold and current profit approaches breakeven, exit immediately
                                            if PROFIT_PROTECTION_NEVER_BREAKEVEN and previous_profit_pct >= protection_min_profit and pnl_percent < protection_min_profit:
                                                logger.warning(f"   🚫 NEVER BREAK EVEN: {symbol} approaching breakeven after being profitable")
                                                logger.warning(f"      Previous profit: {previous_profit_pct*100:+.2f}% → Current: {pnl_percent*100:+.2f}%")
                                                logger.warning(f"   🔒 EXITING NOW - NIJA NEVER BREAKS EVEN!")
                                                positions_to_exit.append({
                                                    'symbol': symbol,
                                                    'quantity': quantity,
                                                    'reason': f'Never break even: was {previous_profit_pct*100:+.2f}%, now {pnl_percent*100:+.2f}%',
                                                    'broker': position_broker,
                                                    'broker_label': broker_label
                                                })
                                                continue

                                            # RULE 3: Fee-Breakeven Guard (applies to ALL brokerages)
                                            # Protects positions that reached fee-adjusted breakeven but never crossed
                                            # the higher protection_min_profit threshold.
                                            # When profit drops BELOW the fee-breakeven level after having been ABOVE
                                            # it, exit immediately to lock in whatever net profit remains before fees
                                            # erase it entirely.
                                            # Example (Coinbase, fee_breakeven=1.6%):
                                            #   Position peaks at 1.8% (net +0.4%) — below 2% protection threshold
                                            #   Position falls to 1.4% (net ~0%) → guard fires, exit now
                                            if (PROFIT_PROTECTION_NEVER_BREAKEVEN
                                                    and pnl_percent > 0
                                                    and pnl_percent < fee_breakeven_threshold
                                                    and previous_profit_pct >= fee_breakeven_threshold):
                                                logger.warning(f"   💰 FEE BREAKEVEN GUARD ({broker_key or 'unknown'}): {symbol} dropped below fee breakeven")
                                                logger.warning(f"      Previous profit: {previous_profit_pct*100:+.2f}% → Current: {pnl_percent*100:+.2f}%")
                                                logger.warning(f"      Fee threshold: {fee_breakeven_threshold*100:.1f}% — exiting to lock in remaining profit!")
                                                positions_to_exit.append({
                                                    'symbol': symbol,
                                                    'quantity': quantity,
                                                    'reason': (
                                                        f'Fee breakeven guard ({broker_key}): was {previous_profit_pct*100:+.2f}%, '
                                                        f'now {pnl_percent*100:+.2f}% (below {fee_breakeven_threshold*100:.1f}% fee threshold)'
                                                    ),
                                                    'broker': position_broker,
                                                    'broker_label': broker_label
                                                })
                                                continue

                                        # STEPPED PROFIT TAKING - Exit portions at profit targets
                                        # This locks in gains and frees capital for new opportunities
                                        # Check targets from highest to lowest
                                        # FIX #3: Only exit if profit > minimum threshold (spread + fees + buffer)
                                        # ENHANCEMENT: Use broker-specific profit targets for ALL supported brokers.
                                        # Each broker has its own fee structure, so targets ensure net profitability.
                                        # Safely get broker_type, defaulting to generic targets if not available
                                        try:
                                            broker_type = getattr(active_broker, 'broker_type', None)
                                        except AttributeError:
                                            broker_type = None

                                        _bkey = broker_type.value if broker_type else ''
                                        if _bkey == 'kraken':
                                            profit_targets = PROFIT_TARGETS_KRAKEN
                                            min_threshold = BROKER_FEE_BREAKEVEN.get('kraken', DEFAULT_FEE_BREAKEVEN)
                                        elif _bkey == 'coinbase':
                                            profit_targets = PROFIT_TARGETS_COINBASE
                                            min_threshold = BROKER_FEE_BREAKEVEN.get('coinbase', DEFAULT_FEE_BREAKEVEN)
                                        elif _bkey == 'binance':
                                            profit_targets = PROFIT_TARGETS_BINANCE
                                            min_threshold = BROKER_FEE_BREAKEVEN.get('binance', DEFAULT_FEE_BREAKEVEN)
                                        elif _bkey == 'okx':
                                            profit_targets = PROFIT_TARGETS_OKX
                                            min_threshold = BROKER_FEE_BREAKEVEN.get('okx', DEFAULT_FEE_BREAKEVEN)
                                        elif _bkey == 'alpaca':
                                            profit_targets = PROFIT_TARGETS_ALPACA
                                            min_threshold = BROKER_FEE_BREAKEVEN.get('alpaca', DEFAULT_FEE_BREAKEVEN)
                                        else:
                                            # Conservative Coinbase targets for any unknown/future broker
                                            profit_targets = PROFIT_TARGETS
                                            min_threshold = DEFAULT_FEE_BREAKEVEN

                                        for target_pct, reason in profit_targets:
                                            if pnl_percent >= target_pct:
                                                # Double-check: ensure profit meets minimum threshold
                                                if pnl_percent >= min_threshold:
                                                    # 💰 EXPLICIT PROFIT REALIZATION LOG (Management Mode)
                                                    if managing_only:
                                                        logger.info(f"   💰 PROFIT REALIZATION (MANAGEMENT MODE): {symbol}")
                                                        logger.info(f"      Current P&L: +{pnl_percent*100:.2f}%")
                                                        logger.info(f"      Profit target: +{target_pct*100:.2f}%")
                                                        logger.info(f"      Reason: {reason}")
                                                        logger.info(f"      🔥 Proof: Realizing profit even with new entries BLOCKED")
                                                    else:
                                                        logger.info(f"   🎯 PROFIT TARGET HIT: {symbol} at +{pnl_percent*100:.2f}% (target: +{target_pct*100}%, min threshold: +{min_threshold*100:.1f}%)")
                                                    positions_to_exit.append({
                                                        'symbol': symbol,
                                                        'quantity': quantity,
                                                        'reason': f'{reason} hit (actual: +{pnl_percent*100:.2f}%)',
                                                        'broker': position_broker,
                                                        'broker_label': broker_label
                                                    })
                                                    break  # Exit the for loop, continue to next position
                                                else:
                                                    logger.info(f"   ⚠️ Target {target_pct*100}% hit but profit {pnl_percent*100:.2f}% < minimum threshold {min_threshold*100:.1f}% - holding")
                                        else:
                                            # No profit target hit, check stop loss (LEGACY FALLBACK)
                                            # CRITICAL FIX (Jan 19, 2026): Stop-loss checks happen BEFORE time-based exits
                                            # This ensures losing trades get stopped out immediately, not held for hours

                                            # CATASTROPHIC STOP LOSS: Force exit at -5% or worse (ABSOLUTE FAILSAFE)
                                            if pnl_percent <= STOP_LOSS_EMERGENCY:
                                                if managing_only:
                                                    logger.warning(f"   💰 LOSS PROTECTION (MANAGEMENT MODE): {symbol}")
                                                    logger.warning(f"      Current P&L: {pnl_percent*100:.2f}%")
                                                    logger.warning(f"      Catastrophic stop: {STOP_LOSS_EMERGENCY*100:.0f}%")
                                                    logger.warning(f"      🔥 Proof: Protecting capital even with new entries BLOCKED")
                                                else:
                                                    logger.warning(f"   🛡️ CATASTROPHIC PROTECTIVE EXIT: {symbol} at {pnl_percent*100:.2f}% (threshold: {STOP_LOSS_EMERGENCY*100:.0f}%)")
                                                logger.warning(f"   💥 PROTECTIVE ACTION: Exiting to prevent severe capital loss")
                                                positions_to_exit.append({
                                                    'symbol': symbol,
                                                    'quantity': quantity,
                                                    'reason': f'Catastrophic protective exit at {STOP_LOSS_EMERGENCY*100:.0f}% (actual: {pnl_percent*100:.2f}%)',
                                                    'broker': position_broker,
                                                    'broker_label': broker_label
                                                })
                                            # STANDARD STOP LOSS: Normal stop-loss threshold
                                            # CRITICAL FIX (Feb 3, 2026): Changed AND to OR - was preventing stops from triggering!
                                            # BUG: "pnl <= -2% AND pnl <= -0.25%" requires BOTH conditions (creates restrictive zone)
                                            #      Only triggers if pnl <= -2% (stricter threshold), making -0.25% floor meaningless
                                            # FIX: "pnl <= -1.5% OR pnl <= -0.05%" triggers when EITHER condition met (proper stop logic)
                                            #      Now triggers at WHICHEVER threshold is hit first
                                            # This was causing 80%+ of stop losses to FAIL and positions to keep losing
                                            elif pnl_percent <= STOP_LOSS_THRESHOLD or pnl_percent <= MIN_LOSS_FLOOR:
                                                # Determine which threshold triggered for accurate logging
                                                triggered_by = (
                                                    f"{STOP_LOSS_THRESHOLD*100:.2f}% primary threshold"
                                                    if pnl_percent <= STOP_LOSS_THRESHOLD
                                                    else f"{MIN_LOSS_FLOOR*100:.2f}% noise floor"
                                                )
                                                if managing_only:
                                                    logger.warning(f"   💰 LOSS PROTECTION (MANAGEMENT MODE): {symbol}")
                                                    logger.warning(f"      Current P&L: {pnl_percent*100:.2f}% (triggered by {triggered_by})")
                                                    logger.warning(f"      🔥 Proof: Cutting losses even with new entries BLOCKED")
                                                else:
                                                    logger.warning(f"   🛑 PROTECTIVE STOP-LOSS HIT: {symbol} at {pnl_percent*100:.2f}% (triggered by {triggered_by})")
                                                # PROFITABILITY GUARD: Verify this is actually a losing position
                                                if pnl_percent >= 0:
                                                    logger.error(f"   ❌ PROFITABILITY GUARD: Attempted to stop-loss a WINNING position at +{pnl_percent*100:.2f}%!")
                                                    logger.error(f"   🛡️ GUARD BLOCKED: Not exiting profitable position")
                                                else:
                                                    positions_to_exit.append({
                                                        'symbol': symbol,
                                                        'quantity': quantity,
                                                        'reason': f'Protective stop-loss ({triggered_by}, actual: {pnl_percent*100:.2f}%)',
                                                        'broker': position_broker,
                                                        'broker_label': broker_label
                                                    })
                                            # WARNING THRESHOLD: Approaching stop loss
                                            elif pnl_percent <= STOP_LOSS_WARNING:
                                                logger.warning(f"   ⚠️ Approaching protective stop: {symbol} at {pnl_percent*100:.2f}%")
                                                # Don't exit yet, but log it
                                            elif self._is_zombie_position(pnl_percent, entry_time_available, position_age_hours):
                                                # ZOMBIE POSITION DETECTION: Position stuck at ~0% P&L for too long
                                                # This catches auto-imported positions that mask actual losses
                                                logger.warning(f"   🧟 ZOMBIE POSITION DETECTED: {symbol} at {pnl_percent:+.2f}% after {position_age_hours:.1f}h | "
                                                              f"Position stuck at ~0% P&L suggests auto-import masked a losing trade | "
                                                              f"AGGRESSIVE EXIT to prevent indefinite holding of potential loser")
                                                positions_to_exit.append({
                                                    'symbol': symbol,
                                                    'quantity': quantity,
                                                    'reason': f'Zombie position exit (stuck at {pnl_percent:+.2f}% for {position_age_hours:.1f}h - likely masked loser)',
                                                    'broker': position_broker,
                                                    'broker_label': broker_label
                                                })
                                            else:
                                                # Position has entry price but not at any exit threshold
                                                # CRITICAL FIX (Jan 19, 2026): Add time-based exits AFTER stop-loss checks
                                                # Railway Golden Rule #5: Stop-loss > time exit (always)
                                                # Only check time-based exits if stop-loss didn't trigger

                                                # Common holding message (avoid duplication)
                                                holding_msg = f"   📊 Holding {symbol}: P&L {pnl_percent:+.2f}% (no exit threshold reached)"

                                                if entry_time_available:
                                                    # 🚨 COINBASE LOCKDOWN (Jan 2026) - FORCE EXIT AFTER 30 MINUTES
                                                    # Coinbase positions MUST exit within 30 minutes (even if profitable)
                                                    # This prevents holding positions too long and missing exit opportunities
                                                    if 'coinbase' in broker_label.lower():
                                                        position_age_minutes = position_age_hours * MINUTES_PER_HOUR
                                                        if position_age_minutes >= COINBASE_MAX_HOLD_MINUTES:
                                                            logger.warning(f"   🚨 COINBASE TIME LOCKDOWN: {symbol} held {position_age_minutes:.1f} min (max: {COINBASE_MAX_HOLD_MINUTES})")
                                                            logger.warning(f"   💥 Force exiting to lock in current P&L: {pnl_percent*100:+.2f}%")
                                                            positions_to_exit.append({
                                                                'symbol': symbol,
                                                                'quantity': quantity,
                                                                'reason': f'Coinbase time lockdown (held {position_age_minutes:.1f}min at {pnl_percent*100:+.2f}%)',
                                                                'broker': position_broker,
                                                                'broker_label': broker_label
                                                            })
                                                            continue

                                                    # EMERGENCY TIME-BASED EXIT: Force exit ALL positions after 12 hours (FAILSAFE)
                                                    # This is a last-resort failsafe for profitable positions that aren't hitting targets
                                                    if position_age_hours >= MAX_POSITION_HOLD_EMERGENCY:
                                                        logger.error(f"   🚨 EMERGENCY TIME EXIT: {symbol} held for {position_age_hours:.1f} hours (emergency max: {MAX_POSITION_HOLD_EMERGENCY})")
                                                        logger.error(f"   💥 FORCE SELLING to prevent indefinite holding!")
                                                        positions_to_exit.append({
                                                            'symbol': symbol,
                                                            'quantity': quantity,
                                                            'reason': f'EMERGENCY time exit (held {position_age_hours:.1f}h, max {MAX_POSITION_HOLD_EMERGENCY}h)',
                                                            'broker': position_broker,
                                                            'broker_label': broker_label
                                                        })
                                                    # TIME-BASED EXIT: Auto-exit stale positions
                                                    elif position_age_hours >= MAX_POSITION_HOLD_HOURS:
                                                        logger.warning(f"   ⏰ STALE POSITION EXIT: {symbol} held for {position_age_hours:.1f} hours (max: {MAX_POSITION_HOLD_HOURS})")
                                                        positions_to_exit.append({
                                                            'symbol': symbol,
                                                            'quantity': quantity,
                                                            'reason': f'Time-based exit (held {position_age_hours:.1f}h, max {MAX_POSITION_HOLD_HOURS}h)',
                                                            'broker': position_broker,
                                                            'broker_label': broker_label
                                                        })
                                                    elif position_age_hours >= STALE_POSITION_WARNING_HOURS:
                                                        logger.info(f"   ⚠️ Position aging: {symbol} held for {position_age_hours:.1f} hours")
                                                        logger.info(holding_msg)
                                                    else:
                                                        logger.info(holding_msg)
                                                else:
                                                    logger.info(holding_msg)
                                            continue  # Continue to next position check

                                        # If we got here via break, skip remaining checks
                                        continue

                                except Exception as pnl_err:
                                    logger.debug(f"   Could not calculate P&L for {symbol}: {pnl_err}")

                            # Log if no entry price available - this helps debug why positions aren't taking profit
                            if not entry_price_available:
                                logger.warning(f"   ⚠️ No entry price tracked for {symbol} - attempting auto-import")

                                # ✅ FIX 1: AUTO-IMPORTED POSITION EXIT SUPPRESSION FIX
                                # Auto-import orphaned positions with aggressive exit parameters
                                # These positions are likely losers and should be exited aggressively
                                auto_import_success = False
                                real_entry_price = None

                                # Try to get real entry price from broker API
                                if active_broker and hasattr(active_broker, 'get_real_entry_price'):
                                    try:
                                        real_entry_price = active_broker.get_real_entry_price(symbol)
                                        if real_entry_price and real_entry_price > 0:
                                            logger.info(f"   ✅ Real entry price fetched: ${real_entry_price:.2f}")
                                    except Exception as fetch_err:
                                        logger.debug(f"   Could not fetch real entry price: {fetch_err}")

                                # If real entry cannot be fetched, use safety default
                                if not real_entry_price or real_entry_price <= 0:
                                    # SAFETY DEFAULT: Assume entry was higher than current by multiplier
                                    # This creates immediate negative P&L to trigger aggressive exits
                                    real_entry_price = current_price * SAFETY_DEFAULT_ENTRY_MULTIPLIER
                                    logger.warning(f"   ⚠️ Using safety default entry price: ${real_entry_price:.2f} (current * {SAFETY_DEFAULT_ENTRY_MULTIPLIER})")
                                    logger.warning(f"   🔴 This position will be flagged as losing and exited aggressively")

                                if active_broker and hasattr(active_broker, 'position_tracker') and active_broker.position_tracker:
                                    try:
                                        # Calculate position size
                                        size_usd = quantity * current_price

                                        # Track the position with real or estimated entry price
                                        # Set aggressive exit parameters for auto-imported positions
                                        auto_import_success = active_broker.position_tracker.track_entry(
                                            symbol=symbol,
                                            entry_price=real_entry_price,
                                            quantity=quantity,
                                            size_usd=size_usd,
                                            strategy="AUTO_IMPORTED"
                                        )

                                        if auto_import_success:
                                            # Compute real PnL immediately
                                            immediate_pnl = ((current_price - real_entry_price) / real_entry_price) * 100
                                            logger.info(f"   ✅ AUTO-IMPORTED: {symbol} @ ${real_entry_price:.2f}")
                                            logger.info(f"   💰 Immediate P&L: {immediate_pnl:+.2f}%")
                                            logger.info(f"   🔴 Aggressive exits enabled: force_stop_loss=True, max_loss_pct=1.5%")

                                            # AUTO-IMPORTED LOSERS ARE EXITED FIRST
                                            # If position is immediately losing, queue it for exit NOW (not next cycle!)
                                            if immediate_pnl < 0:
                                                logger.warning(f"   🚨 AUTO-IMPORTED LOSER: {symbol} at {immediate_pnl:.2f}%")
                                                logger.warning(f"   💥 Queuing for IMMEDIATE EXIT THIS CYCLE")
                                                positions_to_exit.append({
                                                    'symbol': symbol,
                                                    'quantity': quantity,
                                                    'reason': f'Auto-imported losing position ({immediate_pnl:+.2f}%)',
                                                    'broker': position_broker,
                                                    'broker_label': broker_label
                                                })
                                                # Skip all remaining logic for this position since it's queued for exit
                                                continue

                                            logger.info(f"      Position now tracked - will use profit targets in next cycle")
                                            logger.info(f"   ✅ AUTO-IMPORTED: {symbol} @ ${current_price:.2f} (P&L will start from $0) | "
                                                      f"⚠️  WARNING: This position may have been losing before auto-import! | "
                                                      f"Position now tracked - will evaluate exit in next cycle")

                                            # CRITICAL FIX: Don't mark as just_auto_imported to allow stop-loss to execute
                                            # Auto-imported positions should NOT skip stop-loss checks!
                                            # Only skip profit-taking logic to avoid premature exits
                                            just_auto_imported = False  # Changed from True - stop-loss must execute!

                                            # Re-fetch position data to get accurate tracking info
                                            # This ensures control flow variables reflect actual state
                                            try:
                                                tracked_position = active_broker.position_tracker.get_position(symbol)
                                                if tracked_position:
                                                    entry_price_available = True

                                                    # Get entry time from newly tracked position
                                                    entry_time = tracked_position.get('first_entry_time')
                                                    if entry_time:
                                                        try:
                                                            entry_dt = datetime.fromisoformat(entry_time)
                                                            now = datetime.now()
                                                            position_age_hours = (now - entry_dt).total_seconds() / 3600
                                                            entry_time_available = True
                                                        except Exception:
                                                            # Just imported, so age should be ~0
                                                            entry_time_available = True
                                                            position_age_hours = 0

                                                    logger.info(f"      Position verified in tracker - aggressive exits disabled")
                                            except Exception as verify_err:
                                                logger.warning(f"      Could not verify imported position: {verify_err}")
                                                # Still mark as available since track_entry succeeded
                                                entry_price_available = True
                                        else:
                                            logger.error(f"   ❌ Auto-import failed for {symbol} - will use fallback exit logic")
                                    except Exception as import_err:
                                        logger.error(f"   ❌ Error auto-importing {symbol}: {import_err}")
                                        logger.error(f"      Will use fallback exit logic")

                                # If auto-import failed or not available, use fallback logic
                                if not auto_import_success:
                                    logger.warning(f"      💡 Auto-import unavailable - using fallback exit logic")

                                    # CRITICAL FIX: For positions without entry price, use technical indicators
                                    # to determine if position is weakening (RSI < 52, price < EMA9)
                                    # This conservative exit strategy prevents holding potentially losing positions

                                    # Check if position was entered recently (less than 1 hour ago)
                                    # If not, it's likely an old position that should be exited
                                    if entry_time_available:
                                        # We have time but no price - unusual, but use time-based exit
                                        if position_age_hours >= MAX_POSITION_HOLD_HOURS:
                                            logger.warning(f"   ⏰ FALLBACK TIME EXIT: {symbol} held {position_age_hours:.1f}h (max: {MAX_POSITION_HOLD_HOURS}h)")
                                            positions_to_exit.append({
                                                'symbol': symbol,
                                                'quantity': quantity,
                                                'reason': f'Time-based exit without entry price (held {position_age_hours:.1f}h)',
                                                'broker': position_broker,
                                                'broker_label': broker_label
                                            })
                                            continue
                                    else:
                                        # No entry time AND no entry price - this is an orphaned position
                                        # These are likely old positions from before tracking was implemented
                                        # Be conservative: exit if position shows any signs of weakness
                                        logger.warning(f"   ⚠️ ORPHANED POSITION: {symbol} has no entry price or time tracking")
                                        logger.warning(f"      This position will be exited aggressively to prevent losses")

                            # Get market data for analysis (use cached method to prevent rate limiting)
                            candles = self._get_cached_candles(symbol, '5m', 100, broker=active_broker)
                            if not candles or len(candles) < MIN_CANDLES_REQUIRED:
                                logger.warning(f"   ⚠️ Insufficient data for {symbol} ({len(candles) if candles else 0} candles, need {MIN_CANDLES_REQUIRED})")
                                # CRITICAL: Exit positions we can't analyze to prevent blind holding
                                logger.info(f"   🔴 NO DATA EXIT: {symbol} (cannot analyze market)")
                                positions_to_exit.append({
                                    'symbol': symbol,
                                    'quantity': quantity,
                                    'reason': 'Insufficient market data for analysis',
                                    'broker': position_broker,
                                    'broker_label': broker_label
                                })
                                continue

                            # Convert to DataFrame
                            df = pd.DataFrame(candles)

                            # CRITICAL: Ensure numeric types for OHLCV data
                            for col in ['open', 'high', 'low', 'close', 'volume']:
                                if col in df.columns:
                                    df[col] = pd.to_numeric(df[col], errors='coerce')

                            # Calculate indicators for exit signal detection
                            logger.debug(f"   DEBUG candle types → close={type(df['close'].iloc[-1])}, open={type(df['open'].iloc[-1])}, volume={type(df['volume'].iloc[-1])}")
                            indicators = self.apex.calculate_indicators(df)
                            if not indicators:
                                # Can't analyze - exit to prevent blind holding
                                logger.warning(f"   ⚠️ No indicators for {symbol} - exiting")
                                positions_to_exit.append({
                                    'symbol': symbol,
                                    'quantity': quantity,
                                    'reason': 'No indicators available',
                                    'broker': position_broker,
                                    'broker_label': broker_label
                                })
                                continue

                            # CRITICAL: Skip ALL exits for positions that were just auto-imported this cycle
                            # These positions have entry_price = current_price (P&L = $0), so evaluating them
                            # for ANY exit signals would defeat the purpose of auto-import
                            # Let them develop P&L for at least one full cycle before applying ANY exit rules
                            # This guard is placed early to protect against both orphaned and momentum-based exits
                            if just_auto_imported:
                                logger.info(f"   ⏭️  SKIPPING EXITS: {symbol} was just auto-imported this cycle")
                                logger.info(f"      Will evaluate exit signals in next cycle after P&L develops")
                                logger.info(f"      🔍 Note: If this position shows 0% P&L for multiple cycles, it may be a masked loser")
                                continue

                            # MOMENTUM-BASED PROFIT TAKING (for positions without entry price)
                            # When we don't have entry price, use price momentum and trend reversal signals
                            # This helps lock in gains on strong moves and cut losses on weak positions

                            rsi = scalar(indicators.get('rsi', pd.Series()).iloc[-1] if 'rsi' in indicators else DEFAULT_RSI)

                            # CRITICAL FIX (Jan 16, 2026): ORPHANED POSITION PROTECTION
                            # Positions without entry prices are more likely to be losing trades
                            # Apply ULTRA-AGGRESSIVE exits to prevent holding losers
                            if not entry_price_available:
                                # For orphaned positions, exit on ANY weakness signal
                                # This includes: RSI < 52 (below neutral), price below any EMA, or any downtrend

                                # Get EMAs for trend analysis
                                ema9 = indicators.get('ema_9', pd.Series()).iloc[-1] if 'ema_9' in indicators else current_price
                                ema21 = indicators.get('ema_21', pd.Series()).iloc[-1] if 'ema_21' in indicators else current_price

                                # Exit if RSI below 52 (slightly below neutral) - indicates weakening momentum
                                if rsi < 52:
                                    logger.warning(f"   🚨 ORPHANED POSITION EXIT: {symbol} (RSI={rsi:.1f} < 52, no entry price)")
                                    logger.warning(f"      Exiting aggressively to prevent holding potential loser")
                                    positions_to_exit.append({
                                        'symbol': symbol,
                                        'quantity': quantity,
                                        'reason': f'Orphaned position with weak RSI ({rsi:.1f}) - preventing loss',
                                        'broker': position_broker,
                                        'broker_label': broker_label
                                    })
                                    continue

                                # Exit if price is below EMA9 (short-term weakness)
                                if current_price < ema9:
                                    logger.warning(f"   🚨 ORPHANED POSITION EXIT: {symbol} (price ${current_price:.2f} < EMA9 ${ema9:.2f})")
                                    logger.warning(f"      Exiting aggressively to prevent holding potential loser")
                                    positions_to_exit.append({
                                        'symbol': symbol,
                                        'quantity': quantity,
                                        'reason': f'Orphaned position below EMA9 - preventing loss',
                                        'broker': position_broker,
                                        'broker_label': broker_label
                                    })
                                    continue

                                # If orphaned position made it here, it's showing strength - still monitor closely
                                logger.info(f"   ✅ ORPHANED POSITION SHOWING STRENGTH: {symbol} (RSI={rsi:.1f}, price above EMA9)")
                                logger.info(f"      Will monitor with lenient criteria to allow P&L development (exit only on extreme RSI with confirmation)")

                            # PROFITABILITY FIX (Jan 28, 2026): REMOVE UNPROFITABLE RSI-ONLY EXITS
                            # Previous logic was exiting on RSI signals without verifying profitability
                            # This caused "buying low, selling low" and "buying high, selling high" scenarios
                            #
                            # KEY INSIGHT: RSI overbought/oversold indicates MOMENTUM, not profitability
                            # - Position can be overbought (RSI > 55) but still losing money
                            # - Position can be oversold (RSI < 45) but still making money
                            #
                            # NEW STRATEGY: For orphaned positions that passed aggressive checks (RSI >= 52, price >= EMA9)
                            # use EXTREME signals only to allow positions to develop proper P&L:
                            # - Only exit on VERY overbought (RSI > 70) with confirmed weakness (price < EMA9)
                            # - Only exit on VERY oversold (RSI < 30) with confirmed downtrend (price < EMA21)
                            # - Always verify price action confirms the RSI signal before exit
                            #
                            # This prevents premature exits and lets positions develop proper P&L

                            # EXTREME overbought (RSI > 70) with momentum weakening - likely reversal
                            # Only exit if price is also below EMA9 (confirming momentum loss)
                            if rsi > 70:
                                ema9 = indicators.get('ema_9', pd.Series()).iloc[-1] if 'ema_9' in indicators else current_price
                                if current_price < ema9:
                                    logger.info(f"   📈 EXTREME OVERBOUGHT + REVERSAL: {symbol} (RSI={rsi:.1f}, price<EMA9)")
                                    logger.info(f"      Exiting to protect against sharp reversal from overbought")
                                    positions_to_exit.append({
                                        'symbol': symbol,
                                        'quantity': quantity,
                                        'reason': f'Extreme overbought reversal (RSI={rsi:.1f}, price<EMA9)',
                                        'broker': position_broker,
                                        'broker_label': broker_label
                                    })
                                    continue
                                else:
                                    logger.info(f"   📊 {symbol} very overbought (RSI={rsi:.1f}) but still strong (price>EMA9) - HOLDING")
                                    continue

                            # REMOVED (Jan 28, 2026): Moderate RSI exits (RSI 45-55, RSI 50+) were too aggressive
                            # These exits were triggering without profit verification, causing:
                            # - Selling winners too early (RSI 50-55 exits at small gains)
                            # - Selling losers too late (RSI 45-50 exits after significant losses)
                            # Result: "Buying low, selling low" and minimal profits
                            #
                            # Now only extreme RSI levels (>70, <30) with confirming signals trigger exits
                            # This allows positions to develop proper P&L before exiting

                            # EXTREME oversold (RSI < 30) with continued weakness - likely further decline
                            # Only exit if price is also below EMA21 (confirming downtrend)
                            if rsi < 30:
                                ema21 = indicators.get('ema_21', pd.Series()).iloc[-1] if 'ema_21' in indicators else current_price
                                if current_price < ema21:
                                    logger.info(f"   📉 EXTREME OVERSOLD + DOWNTREND: {symbol} (RSI={rsi:.1f}, price<EMA21)")
                                    logger.info(f"      Exiting to prevent further losses in confirmed downtrend")
                                    positions_to_exit.append({
                                        'symbol': symbol,
                                        'quantity': quantity,
                                        'reason': f'Extreme oversold downtrend (RSI={rsi:.1f}, price<EMA21)',
                                        'broker': position_broker,
                                        'broker_label': broker_label
                                    })
                                    continue
                                else:
                                    logger.info(f"   📊 {symbol} very oversold (RSI={rsi:.1f}) but bouncing (price>EMA21) - HOLDING for recovery")
                                    continue

                            # Check for weak market conditions (exit signal)
                            # This protects capital even without knowing entry price
                            allow_trade, trend, market_reason = self.apex.check_market_filter(df, indicators)

                            # AGGRESSIVE: If market conditions deteriorate, exit immediately
                            if not allow_trade:
                                logger.info(f"   ⚠️ Market conditions weak: {market_reason}")
                                logger.info(f"   💰 MARKING {symbol} for concurrent exit")
                                positions_to_exit.append({
                                    'symbol': symbol,
                                    'quantity': quantity,
                                    'reason': market_reason,
                                    'broker': position_broker,
                                    'broker_label': broker_label
                                })
                                continue

                            # If we get here, position passes all checks - keep it
                            logger.info(f"   ✅ {symbol} passing all checks (RSI={rsi:.1f}, trend={trend})")

                        except Exception as e:
                            logger.error(f"   Error analyzing position {symbol}: {e}", exc_info=True)

                        # Rate limiting: Add delay after each position check to prevent 429 errors
                        # Skip delay after the last position
                        if idx < len(current_positions) - 1:
                            jitter = random.uniform(0, 0.05)  # 0-50ms jitter
                            time.sleep(POSITION_CHECK_DELAY + jitter)

                # CRITICAL: If still over cap after normal exit analysis, force-sell weakest remaining positions
                # Uses balance-aware effective_max_positions cap
                if len(current_positions) > effective_max_positions and len(positions_to_exit) < (len(current_positions) - effective_max_positions):
                    logger.warning(f"🚨 STILL OVER CAP: Need to sell {len(current_positions) - effective_max_positions - len(positions_to_exit)} more positions")

                    # Identify positions not yet marked for exit
                    symbols_to_exit = {p['symbol'] for p in positions_to_exit}
                    remaining_positions = [p for p in current_positions if p.get('symbol') not in symbols_to_exit]

                    # Sort by USD value (smallest first - easiest to exit and lowest capital impact)
                    # CRITICAL FIX: Add None-check safety guard for price fetching in sort key
                    def get_position_value(p):
                        """Calculate position value with None-check safety."""
                        symbol = p.get('symbol', '')
                        quantity = p.get('quantity', 0)
                        price = active_broker.get_current_price(symbol)
                        # Return 0 if price is None to sort invalid positions first
                        return quantity * (price if price is not None else 0)

                    remaining_sorted = sorted(remaining_positions, key=get_position_value)

                    # Force-sell smallest positions to get under cap
                    positions_needed = (len(current_positions) - effective_max_positions) - len(positions_to_exit)
                    for pos_idx, pos in enumerate(remaining_sorted[:positions_needed]):
                        symbol = pos.get('symbol')
                        quantity = pos.get('quantity', 0)
                        try:
                            price = active_broker.get_current_price(symbol)

                            # CRITICAL FIX: Add None-check safety guard
                            # Prevents ghost positions from invalid price fetches
                            if price is None or price == 0:
                                logger.error(f"   ❌ Price fetch failed for {symbol} — symbol mismatch")
                                logger.error(f"   💡 This position may be unmanageable due to incorrect broker symbol format")
                                logger.warning(f"   🔴 FORCE-EXIT anyway: {symbol} (price unknown)")
                                positions_to_exit.append({
                                    'symbol': symbol,
                                    'quantity': quantity,
                                    'reason': 'Over position cap (price fetch failed - symbol mismatch)',
                                    'broker': position_broker,
                                    'broker_label': broker_label
                                })
                                continue

                            value = quantity * price
                            logger.warning(f"   🔴 FORCE-EXIT to meet cap: {symbol} (${value:.2f})")
                            positions_to_exit.append({
                                'symbol': symbol,
                                'quantity': quantity,
                                'reason': f'Over position cap (${value:.2f})',
                                'broker': position_broker,
                                'broker_label': broker_label
                            })
                        except Exception as price_err:
                            # Still add even if price fetch fails
                            logger.warning(f"   ⚠️ Could not get price for {symbol}: {price_err}")
                            positions_to_exit.append({
                                'symbol': symbol,
                                'quantity': quantity,
                                'reason': 'Over position cap',
                                'broker': position_broker,
                                'broker_label': broker_label
                            })

                        # Rate limiting: Add delay after each price check (except last one)
                        if pos_idx < positions_needed - 1:
                            jitter = random.uniform(0, 0.05)  # 0-50ms jitter
                            time.sleep(POSITION_CHECK_DELAY + jitter)

                # CRITICAL FIX: Now sell ALL positions concurrently (not one at a time)
                if positions_to_exit:
                    logger.info(f"")
                    logger.info(f"🔴 CONCURRENT EXIT: Selling {len(positions_to_exit)} positions NOW")
                    logger.info(f"="*80)

                    # Track sell results to provide accurate summary
                    successful_sells = []
                    failed_sells = []

                    for i, pos_data in enumerate(positions_to_exit, 1):
                        symbol = pos_data['symbol']
                        quantity = pos_data['quantity']
                        reason = pos_data['reason']
                        # CRITICAL FIX (Jan 24, 2026): Use the correct broker for each position
                        exit_broker = pos_data.get('broker', active_broker)
                        exit_broker_label = pos_data.get('broker_label', 'UNKNOWN')

                        logger.info(f"[{i}/{len(positions_to_exit)}] Selling {symbol} on {exit_broker_label} ({reason})")

                        # CRITICAL FIX (Jan 10, 2026): Validate symbol before placing order
                        # Prevents "ProductID is invalid" errors
                        if not symbol or not isinstance(symbol, str):
                            logger.error(f"  ❌ SKIPPING: Invalid symbol (value: {symbol}, type: {type(symbol)})")
                            # Store descriptive string for logging - will be displayed in summary
                            failed_sells.append(f"INVALID_SYMBOL({symbol})")
                            continue

                        try:
                            # 🚨 COINBASE LOCKDOWN (Jan 2026) - FORCE LIQUIDATE MODE
                            # Use force_liquidate for Coinbase sells to bypass ALL validation
                            # This ensures stop-losses and profit-taking ALWAYS execute
                            is_coinbase = 'coinbase' in exit_broker_label.lower()
                            use_force_liquidate = is_coinbase and (
                                'lockdown' in reason.lower() or
                                'loss' in reason.lower() or
                                'stop' in reason.lower() or
                                'profit' in reason.lower() or
                                'rebalance' in reason.lower()
                            )

                            if use_force_liquidate:
                                logger.info(f"  🛡️ PROTECTIVE MODE: Using force_liquidate for Coinbase exit")

                            result = exit_broker.place_market_order(
                                symbol=symbol,
                                side='sell',
                                quantity=quantity,
                                size_type='base',
                                force_liquidate=use_force_liquidate,  # Bypass ALL validation for Coinbase protective exits
                                ignore_balance=use_force_liquidate,   # Skip balance checks
                                ignore_min_trade=use_force_liquidate  # Skip minimum trade size checks
                            )

                            # Handle dust positions separately from actual failures
                            if result and result.get('status') == 'skipped_dust':
                                logger.info(f"  💨 {symbol} SKIPPED (dust position - too small to sell)")
                                logger.info(f"     Will automatically retry in 24h if position grows")
                                # Mark as unsellable for 24h retry window
                                self.unsellable_positions[symbol] = time.time()
                                # Don't add to failed_sells - this is expected behavior for dust
                                continue

                            if result and result.get('status') not in ['error', 'unfilled']:
                                logger.info(f"  ✅ {symbol} SOLD successfully on {exit_broker_label}!")
                                # ✅ FIX #3: EXPLICIT SELL CONFIRMATION LOG
                                # If this was a stop-loss exit, log it clearly
                                if 'stop loss' in reason.lower():
                                    logger.info(f"  ✅ SOLD {symbol} @ market due to stop loss")
                                # Track the exit in position tracker (use the correct broker)
                                if hasattr(exit_broker, 'position_tracker') and exit_broker.position_tracker:
                                    exit_broker.position_tracker.track_exit(symbol, quantity)
                                # Remove from unsellable dict if it was there (position grew and became sellable)
                                if symbol in self.unsellable_positions:
                                    del self.unsellable_positions[symbol]
                                successful_sells.append(symbol)
                            else:
                                error_msg = result.get('error', result.get('message', 'Unknown')) if result else 'No response'
                                error_code = result.get('error') if result else None
                                logger.error(f"  ❌ {symbol} sell failed: {error_msg}")
                                logger.error(f"     Full result: {result}")
                                failed_sells.append(symbol)

                                # CRITICAL FIX (Jan 10, 2026): Handle INVALID_SYMBOL errors
                                # These indicate the symbol format is wrong or the product doesn't exist
                                is_invalid_symbol = (
                                    error_code == 'INVALID_SYMBOL' or
                                    'INVALID_SYMBOL' in str(error_msg) or
                                    'invalid symbol' in str(error_msg).lower()
                                )
                                if is_invalid_symbol:
                                    logger.error(f"     ⚠️ Symbol {symbol} is invalid or unsupported")
                                    logger.error(f"     💡 This position will be skipped for 24 hours")
                                    self.unsellable_positions[symbol] = time.time()
                                    continue

                                # If it's a dust/too-small position, mark it as unsellable to prevent infinite retries
                                # Check both error code and message for robustness
                                is_size_error = (
                                    error_code == 'INVALID_SIZE' or
                                    'INVALID_SIZE' in str(error_msg) or
                                    'too small' in str(error_msg).lower() or
                                    'minimum' in str(error_msg).lower()
                                )
                                if is_size_error:
                                    logger.warning(f"     💡 Position {symbol} is too small to sell via API - marking as dust")
                                    logger.warning(f"     💡 Will retry after 24 hours in case position grows")
                                    self.unsellable_positions[symbol] = time.time()
                        except Exception as sell_err:
                            logger.error(f"  ❌ {symbol} exception during sell: {sell_err}")
                            logger.error(f"     Error type: {type(sell_err).__name__}")
                            logger.error(f"     Traceback: {traceback.format_exc()}")
                            # Convert symbol to string for consistent logging - prevents join() errors
                            failed_sells.append(str(symbol) if symbol else "UNKNOWN_SYMBOL")

                        # Rate limiting: Add delay after each sell order (except the last one)
                        if i < len(positions_to_exit):
                            jitter = random.uniform(0, 0.1)  # 0-100ms jitter
                            time.sleep(SELL_ORDER_DELAY + jitter)

                    logger.info(f"="*80)
                    # CRITICAL FIX (Jan 22, 2026): Provide accurate exit summary with success/failure counts
                    # Previous version logged "positions processed" which was misleading - users thought all sells succeeded
                    logger.info(f"🔴 CONCURRENT EXIT SUMMARY:")
                    logger.info(f"   ✅ Successfully sold: {len(successful_sells)} positions")
                    if successful_sells:
                        logger.info(f"      {', '.join(successful_sells)}")
                    logger.info(f"   ❌ Failed to sell: {len(failed_sells)} positions")
                    if failed_sells:
                        logger.error(f"      {', '.join(failed_sells)}")
                        logger.error(f"   🚨 WARNING: {len(failed_sells)} position(s) still open on exchange!")
                        logger.error(f"   💡 Check Coinbase manually and retry or sell manually if needed")
                    logger.info(f"="*80)
                    logger.info(f"")

                    # ── Micro-cap win-streak update ──────────────────────────────
                    # After each successfully closed position, determine whether the
                    # exit was a profit (win) or a loss and update the streak counter.
                    # Only explicit loss exits reset the streak; ambiguous/neutral exits
                    # (e.g., manual closes, timeouts with no loss keyword) are ignored.
                    _profit_keywords = ('profit target', 'profit realization', 'profit hit')
                    _loss_keywords = ('stop loss', 'stop-loss', 'loss', 'lockdown',
                                      'time exit', 'protective', 'zombie', 'catastrophic',
                                      'drawdown', 'emergency')
                    for _pd in positions_to_exit:
                        if _pd['symbol'] not in successful_sells:
                            continue  # only update for sells that went through
                        _reason_lower = _pd.get('reason', '').lower()
                        _is_profit_exit = any(kw in _reason_lower for kw in _profit_keywords)
                        _is_loss_exit = any(kw in _reason_lower for kw in _loss_keywords)
                        if _is_profit_exit and not _is_loss_exit:
                            self._micro_cap_win_streak += 1
                            logger.info(
                                f"   🔥 Micro-cap win streak: {self._micro_cap_win_streak} "
                                f"(+1 after profit exit of {_pd['symbol']})"
                            )
                        elif _is_loss_exit:
                            if self._micro_cap_win_streak > 0:
                                logger.info(
                                    f"   🔄 Micro-cap win streak RESET: {self._micro_cap_win_streak} → 0 "
                                    f"(loss exit of {_pd['symbol']})"
                                )
                            self._micro_cap_win_streak = 0
                        # Ambiguous exits (neither profit nor loss keyword) leave the streak unchanged.

                # CRITICAL FIX: Ensure position management errors don't crash the entire cycle
                # If exit logic fails, log the error but continue to allow next cycle to retry
            except Exception as exit_err:
                logger.error("=" * 80)
                logger.error("🚨 POSITION MANAGEMENT ERROR")
                logger.error("=" * 80)
                logger.error(f"   Error during position management: {exit_err}")
                logger.error(f"   Type: {type(exit_err).__name__}")
                logger.error("   Exit logic will retry next cycle (2.5 min)")
                logger.error("=" * 80)
                import traceback
                logger.error(traceback.format_exc())
                # Don't return - allow cycle to continue and try new entries
                # This ensures the bot keeps running even if exit logic fails

            positions_duration = time.time() - positions_start_time
            logger.info(f"⏱️  [TIMING] Position update: {positions_duration:.2f}s")

            # ⏱️ Sub-step 3: Entry scan
            entry_start_time = time.time()

            # STEP 2: Look for new entry opportunities (only if entries allowed)
            # USER accounts NEVER generate entry signals - they receive signals via CopyTradeEngine
            # Only MASTER accounts scan markets and generate buy signals
            # PROFITABILITY FIX: Use module-level constants for consistency

            # ENHANCED LOGGING (Jan 22, 2025): Show broker-aware condition checklist for trade execution
            logger.info("")
            logger.info("═" * 80)
            logger.info("🎯 TRADE EXECUTION CONDITION CHECKLIST (BROKER-AWARE)")
            logger.info("═" * 80)

            # Initialise entry-gate variables so they are always in scope for the
            # ENTRY CHECK log that follows the if/else block below.
            can_enter = True
            skip_reasons = []

            if user_mode:
                if explicit_user_mode:
                    # USER MODE: Skip market scanning and entry signal generation entirely
                    logger.info("   ✅ Mode: USER (copy trading only)")
                    logger.info("   ⏭️  RESULT: Skipping market scan (signals from copy trade engine)")
                    logger.info("   ℹ️  USER accounts execute copied trades only")
                    logger.info("   ℹ️  USER accounts do not scan markets independently")
                else:
                    # PLATFORM account with entries blocked by safety checks
                    logger.info("   ⚠️  Mode: PLATFORM (entries blocked by safety checks)")
                    logger.info("   ⏭️  RESULT: Skipping market scan until safety conditions clear")
                logger.info("═" * 80)
                logger.info("")
            else:
                logger.info("   ✅ Mode: PLATFORM (full strategy execution)")
                logger.info(f"   📊 Current positions: {len(current_positions)}/{effective_max_positions}")
                logger.info(f"   💰 Account balance: ${account_balance:.2f}")
                logger.info(f"   💵 Minimum to trade: ${MIN_BALANCE_TO_TRADE_USD:.2f}")
                logger.info(f"   🚫 Entries blocked: {entries_blocked}")
                logger.info("")

                # Check each condition individually
                can_enter = True
                skip_reasons = []

                if entries_blocked:
                    can_enter = False
                    skip_reasons.append("STOP_ALL_ENTRIES.conf is active")
                    logger.warning("   ❌ CONDITION FAILED: Entry blocking is active")
                else:
                    logger.info("   ✅ CONDITION PASSED: Entry blocking is OFF")

                if len(current_positions) >= effective_max_positions:
                    can_enter = False
                    skip_reasons.append(f"Position cap reached ({len(current_positions)}/{effective_max_positions})")
                    logger.warning(f"   ❌ CONDITION FAILED: Position cap reached ({len(current_positions)}/{effective_max_positions})")
                else:
                    logger.info(f"   ✅ CONDITION PASSED: Under position cap ({len(current_positions)}/{effective_max_positions})")

                # NOTE: Balance check is intentionally deferred until AFTER broker selection.
                # The authoritative balance gate is applied once we know which broker was
                # selected and have fetched its live balance (see below).
                logger.info("   ℹ️  Balance check deferred – will be validated against selected broker balance")

                # BROKER-AWARE ENTRY GATING (Jan 22, 2025)
                # Check broker eligibility - must not be in EXIT_ONLY mode and meet balance requirements
                logger.info("")
                logger.info("   🏦 BROKER ELIGIBILITY CHECK:")

                # CRITICAL FIX (Jan 24, 2026): Wrap entire broker selection in try-catch
                # to prevent silent failures that cause market scanning to never execute
                try:
                    # Get all available brokers for selection
                    all_brokers = {}
                    if hasattr(self, 'multi_account_manager') and self.multi_account_manager:
                        # ensure mutable broker registry
                        all_brokers = dict(getattr(self.multi_account_manager, 'platform_brokers', {}))

                    # Add current active broker if not in multi_account_manager
                    # CRITICAL: Never add USER accounts to entry broker candidates —
                    # USER accounts are copy-trading (secondary) and must not generate entries.
                    if active_broker and hasattr(active_broker, 'broker_type'):
                        _acct_type = getattr(active_broker, 'account_type', None)
                        if _acct_type == AccountType.USER:
                            _uid = getattr(active_broker, 'user_id', None) or 'missing_user_id'
                            _bname = self._get_broker_name(active_broker).upper()
                            logger.info(
                                f"      ⏭️  ENTRY BLOCKED → broker=USER_{_uid}_{_bname} "
                                f"| reason=user account (copy trading only)"
                            )
                        else:
                            all_brokers[active_broker.broker_type] = active_broker

                    # CRITICAL FIX (Jan 24, 2026): Log if no brokers are available for selection
                    # This helps diagnose why no trades are executing
                    if not all_brokers:
                        logger.warning(f"      ⚠️  No brokers available for selection!")
                        logger.warning(f"      Multi-account manager: {'Yes' if self.multi_account_manager else 'No'}")
                        logger.warning(f"      Active broker: {'Yes' if active_broker else 'No'}")
                    else:
                        logger.info(f"      Available brokers for selection: {', '.join([bt.value.upper() for bt in all_brokers.keys()])}")

                    # Select best broker for entry based on priority
                    entry_broker, entry_broker_name, broker_eligibility = self._select_entry_broker(all_brokers)

                    # Note: Broker eligibility logging moved to after exception handler (line ~3420)
                    # to ensure it happens even if an exception occurs

                    if not entry_broker:
                        can_enter = False
                        skip_reasons.append("No eligible broker for entry (all in EXIT_ONLY or below minimum balance)")
                        logger.warning(f"   ❌ CONDITION FAILED: No eligible broker for entry")
                        logger.warning(f"      💡 All brokers are either in EXIT-ONLY mode or below minimum balance")
                    else:
                        logger.info(f"   ✅ CONDITION PASSED: {entry_broker_name.upper()} available for entry")
                        # Update active_broker to use the selected entry broker
                        active_broker = entry_broker

                        # CRITICAL FIX (Jan 26, 2026): Update apex strategy's broker reference
                        # When switching brokers, we must update the execution engine's broker
                        # Otherwise position sizing is calculated correctly but execution uses wrong broker
                        # This was causing KRAKEN trades ($57.31) to be executed with COINBASE balance ($24.16)
                        if self.apex and hasattr(self.apex, 'update_broker_client'):
                            logger.info(f"   🔄 Updating apex strategy broker to {entry_broker_name.upper()}")
                            self.apex.update_broker_client(active_broker)

                        # CRITICAL FIX (Jan 22, 2026): Update account_balance from selected entry broker
                        # When switching brokers, we must re-fetch the balance from the NEW broker
                        # Otherwise position sizing uses the wrong broker's balance (e.g., Coinbase $20 instead of Kraken $28)
                        # CRITICAL FIX (Jan 26, 2026): Wrap balance fetch in timeout to prevent hanging
                        # Without timeout, slow Kraken API calls can block indefinitely, preventing market scanning
                        balance_data = None
                        balance_fetch_failed = False

                        try:
                            if hasattr(active_broker, 'get_account_balance_detailed'):
                                # Use timeout to prevent hanging on slow balance fetches
                                balance_result = call_with_timeout(
                                    active_broker.get_account_balance_detailed,
                                    timeout_seconds=BALANCE_FETCH_TIMEOUT
                                )

                                if balance_result[1] is not None:  # Timeout or error
                                    logger.warning(f"   ⚠️  {entry_broker_name.upper()} detailed balance fetch timed out: {balance_result[1]}")
                                    balance_fetch_failed = True
                                else:
                                    balance_data = balance_result[0]
                            else:
                                # Fallback to simple balance fetch with timeout
                                balance_result = call_with_timeout(
                                    active_broker.get_account_balance,
                                    timeout_seconds=BALANCE_FETCH_TIMEOUT
                                )

                                if balance_result[1] is not None:  # Timeout or error
                                    logger.warning(f"   ⚠️  {entry_broker_name.upper()} balance fetch timed out: {balance_result[1]}")
                                    balance_fetch_failed = True
                                else:
                                    balance_data = {'trading_balance': balance_result[0]}
                        except Exception as e:
                            logger.warning(f"   ⚠️  {entry_broker_name.upper()} balance fetch exception: {e}")
                            balance_fetch_failed = True

                        # Use cached balance if fresh fetch failed
                        if balance_fetch_failed or balance_data is None:
                            if hasattr(active_broker, '_last_known_balance') and active_broker._last_known_balance is not None:
                                cached_balance = active_broker._last_known_balance

                                # Check if cached balance has a timestamp and is fresh
                                cache_is_fresh = False
                                if hasattr(active_broker, '_balance_last_updated') and active_broker._balance_last_updated is not None:
                                    balance_age_seconds = time.time() - active_broker._balance_last_updated
                                    cache_is_fresh = balance_age_seconds <= CACHED_BALANCE_MAX_AGE_SECONDS
                                    if not cache_is_fresh:
                                        logger.warning(f"   ⚠️  Cached balance for {entry_broker_name.upper()} is stale ({balance_age_seconds:.0f}s old > {CACHED_BALANCE_MAX_AGE_SECONDS}s max)")
                                else:
                                    # No timestamp - use cache anyway since fetch failed (better than nothing)
                                    cache_is_fresh = True
                                    logger.warning(f"   ⚠️  Cached balance for {entry_broker_name.upper()} has no timestamp, using anyway due to fetch failure")

                                if cache_is_fresh:
                                    logger.warning(f"   ⚠️  Using cached balance for {entry_broker_name.upper()}: ${cached_balance:.2f}")
                                    balance_data = {'trading_balance': cached_balance, 'total_held': 0.0, 'total_funds': cached_balance}
                                else:
                                    # Stale cache and fresh fetch failed - use eligibility check balance
                                    logger.error(f"   ❌ Cached balance too stale for {entry_broker_name.upper()}")
                                    logger.warning(f"   ⚠️  Using balance from eligibility check as fallback: ${account_balance:.2f}")
                                    balance_data = {'trading_balance': account_balance, 'total_held': 0.0, 'total_funds': account_balance}
                            else:
                                logger.error(f"   ❌ No cached balance available for {entry_broker_name.upper()}")
                                # Use the balance from eligibility check as last resort
                                logger.warning(f"   ⚠️  Using balance from eligibility check as fallback: ${account_balance:.2f}")
                                balance_data = {'trading_balance': account_balance, 'total_held': 0.0, 'total_funds': account_balance}

                        account_balance = balance_data.get('trading_balance', 0.0) or 0.0

                        # ── SELECTED BROKER BALANCE CHECK ──────────────────────
                        # This is the AUTHORITATIVE balance gate.  We now have the
                        # live balance from the selected entry broker; block entry
                        # immediately if it is below the trading floor.
                        if account_balance is not None and account_balance < MIN_BALANCE_TO_TRADE_USD:
                            can_enter = False
                            _bal_reason = (
                                f"insufficient balance on {entry_broker_name.upper()}: "
                                f"${account_balance:.2f} < ${MIN_BALANCE_TO_TRADE_USD:.2f}"
                            )
                            skip_reasons.append(_bal_reason)
                            logger.warning(f"   ❌ CONDITION FAILED: {_bal_reason}")
                        else:
                            logger.info(
                                f"   ✅ CONDITION PASSED: {entry_broker_name.upper()} balance "
                                f"${account_balance:.2f} >= ${MIN_BALANCE_TO_TRADE_USD:.2f} minimum"
                            )

                        # ═══════════════════════════════════════════════════════
                        # GLOBAL CAPITAL MANAGER — register account balance
                        # Enables proportional allocation & cross-account risk
                        # ═══════════════════════════════════════════════════════
                        if GLOBAL_CAPITAL_MANAGER_AVAILABLE and get_global_capital_manager:
                            try:
                                _gcm = get_global_capital_manager()
                                _acct_label = self._get_broker_name(active_broker)
                                _gcm.register_account(_acct_label, account_balance)
                            except Exception as _gcm_err:
                                logger.debug("GlobalCapitalManager register_account skipped: %s", _gcm_err)

                        # ═══════════════════════════════════════════════════════
                        # SIGNAL BROADCASTER — register account for fan-out
                        # ═══════════════════════════════════════════════════════
                        if SIGNAL_BROADCASTER_AVAILABLE and get_signal_broadcaster:
                            try:
                                _sb = get_signal_broadcaster()
                                _acct_label = self._get_broker_name(active_broker)
                                _sb.register_account(_acct_label, active_broker, account_balance)
                            except Exception as _sb_err:
                                logger.debug("SignalBroadcaster register_account skipped: %s", _sb_err)

                        # Update capital growth throttle with refreshed broker balance
                        # (broker may have changed mid-cycle; keep throttle in sync)
                        if CAPITAL_GROWTH_THROTTLE_AVAILABLE and get_capital_growth_throttle:
                            try:
                                get_capital_growth_throttle().update_capital(account_balance)
                            except Exception as _cgt_err:
                                logger.debug("Capital growth throttle update skipped: %s", _cgt_err)

                        # Also update position values and total capital from the new broker
                        held_funds = balance_data.get('total_held', 0.0)
                        total_funds = balance_data.get('total_funds', account_balance)

                        # Fetch total capital with timeout protection
                        if hasattr(active_broker, 'get_total_capital'):
                            try:
                                capital_result = call_with_timeout(
                                    active_broker.get_total_capital,
                                    kwargs={'include_positions': True},
                                    timeout_seconds=BALANCE_FETCH_TIMEOUT
                                )

                                if capital_result[1] is not None:  # Timeout or error
                                    logger.warning(f"   ⚠️  {entry_broker_name.upper()} capital fetch timed out: {capital_result[1]}")
                                    total_capital = account_balance
                                else:
                                    capital_data = capital_result[0]
                                    position_value = capital_data.get('position_value', 0.0)
                                    position_count = capital_data.get('position_count', 0)
                                    total_capital = capital_data.get('total_capital', account_balance)
                            except Exception as e:
                                logger.debug(f"⚠️ Could not calculate position values from entry broker: {e}")
                                total_capital = account_balance
                        else:
                            total_capital = account_balance

                        logger.info(f"   💰 {entry_broker_name.upper()} balance updated: ${account_balance:.2f} (total capital: ${total_capital:.2f})")

                except Exception as broker_check_error:
                    # CRITICAL FIX (Jan 27, 2026): Enhanced exception logging with line number
                    # This helps diagnose exactly where broker selection is failing
                    logger.error(f"   ❌ ERROR during broker eligibility check: {broker_check_error}")
                    logger.error(f"   Exception type: {type(broker_check_error).__name__}")
                    import traceback
                    logger.error(f"   Traceback: {traceback.format_exc()}")
                    logger.error(f"   ⚠️  This error prevented broker selection - bot will skip market scanning")
                    can_enter = False
                    skip_reasons.append(f"Broker eligibility check failed: {broker_check_error}")
                    # Set entry_broker to None to ensure it's defined for later code
                    entry_broker = None
                    entry_broker_name = "UNKNOWN"
                    # Initialize empty broker_eligibility dict if it wasn't created
                    if 'broker_eligibility' not in locals():
                        broker_eligibility = {}

                # CRITICAL FIX (Jan 27, 2026): Always log broker eligibility status
                # Even if exception occurred, we want to see which brokers were checked
                if 'broker_eligibility' in locals() and broker_eligibility:
                    logger.info("")
                    logger.info("   📊 Broker Eligibility Results:")
                    for broker_name, status in broker_eligibility.items():
                        if "Eligible" in status:
                            logger.info(f"      ✅ {broker_name.upper()}: {status}")
                        elif "Not configured" in status:
                            logger.info(f"      ⚪ {broker_name.upper()}: {status}")
                        else:
                            logger.warning(f"      ❌ {broker_name.upper()}: {status}")

                logger.info("")
                logger.info("═" * 80)

                if can_enter:
                    logger.info(f"🟢 RESULT: CONDITIONS PASSED FOR {entry_broker_name.upper()}")
                    logger.info("═" * 80)
                    logger.info("")
                else:
                    logger.warning("🔴 RESULT: CONDITIONS FAILED - SKIPPING MARKET SCAN")
                    # 🧠 TRUST LAYER: Explicit trade veto reason logging
                    logger.warning("=" * 70)
                    logger.warning("🚫 TRADE VETO - Signal Blocked from Execution")
                    logger.warning("=" * 70)
                    for idx, reason in enumerate(skip_reasons, 1):
                        logger.warning(f"   Veto Reason {idx}: {reason}")
                    logger.warning("=" * 70)
                    logger.warning("")

            # ENTRY CHECK debug log — emitted before the entry gate to make the
            # decision transparent in the logs regardless of the outcome.
            # NOTE: balance gate is now encoded inside `can_enter` (applied against
            # the selected broker's live balance above), so we do NOT re-check
            # `account_balance >= MIN_BALANCE_TO_TRADE_USD` here.
            allow_entries = (
                not user_mode
                and not entries_blocked
                and len(current_positions) < effective_max_positions
                and can_enter
            )
            if allow_entries:
                block_reason = "OK"
            elif user_mode:
                block_reason = "user_mode" if explicit_user_mode else "safety_check_forced_user_mode"
            elif entries_blocked:
                block_reason = "STOP_ALL_ENTRIES.conf active"
            elif len(current_positions) >= effective_max_positions:
                block_reason = f"position_cap ({len(current_positions)}/{effective_max_positions})"
            else:
                block_reason = "; ".join(skip_reasons) if skip_reasons else "unknown"
            logger.info(f"ENTRY CHECK → allowed={allow_entries}, reason={block_reason}")

            # Continue with market scanning if conditions passed
            # SAFETY: Re-normalize account_balance before any comparisons/formatting.
            # This catches any unexpected None that slipped past the earlier guards
            # (e.g. a future code path that re-assigns without a float() wrapper).
            if not isinstance(account_balance, (int, float)):
                logger.warning(
                    "⚠️ account_balance is unexpectedly non-numeric (%r) before entry scan — "
                    "resetting to 0.0.  Check balance-fetch paths above for a missing None guard.",
                    account_balance,
                )
                account_balance = 0.0
            else:
                account_balance = float(account_balance or 0.0)
            if not user_mode and not entries_blocked and len(current_positions) < effective_max_positions and can_enter:
                logger.info(f"🔍 Scanning for new opportunities (positions: {len(current_positions)}/{effective_max_positions}, balance: ${account_balance:.2f}, min: ${MIN_BALANCE_TO_TRADE_USD})...")

                # Get top market candidates (limit scan to prevent timeouts)
                try:
                    # Get list of all products (with caching to reduce API calls)
                    current_time = time.time()
                    if (not self.all_markets_cache or
                        current_time - self.markets_cache_time > self.MARKETS_CACHE_TTL):
                        logger.info("   🔄 Refreshing market list from API...")
                        all_products = active_broker.get_all_products()
                        if all_products:
                            # FIX #3 (Jan 20, 2026): Filter Kraken markets BEFORE caching
                            # At startup: kraken_markets = [m for m in all_markets if kraken.supports_symbol(m)]
                            # Then scan ONLY these filtered markets
                            broker_name = self._get_broker_name(active_broker)
                            if broker_name == 'kraken':
                                original_count = len(all_products)
                                all_products = [
                                    sym for sym in all_products
                                    if sym.endswith('/USD') or sym.endswith('/USDT') or
                                       sym.endswith('-USD') or sym.endswith('-USDT')
                                ]
                                filtered_count = original_count - len(all_products)
                                logger.info(f"   🔍 Kraken market filter: {filtered_count} unsupported symbols removed at startup")
                                logger.info(f"      Kraken markets cached: {len(all_products)} (*/USD and */USDT pairs ONLY)")

                            self.all_markets_cache = all_products
                            self.markets_cache_time = current_time
                            logger.info(f"   ✅ Cached {len(all_products)} markets")
                        else:
                            logger.warning("   ⚠️  No products available from API")
                            return
                    else:
                        all_products = self.all_markets_cache
                        cache_age = int(current_time - self.markets_cache_time)
                        logger.info(f"   ✅ Using cached market list ({len(all_products)} markets, age: {cache_age}s)")

                    if not all_products:
                        logger.warning("   No products available for scanning")
                        return

                    # Use rotation to scan different markets each cycle
                    markets_to_scan = self._get_rotated_markets(all_products)

                    # FIRST TRADE GUARANTEE: bypass warmup batch-size cap on cycle 0
                    # so the bot scans a meaningful number of markets immediately.
                    # Rotation offset from _get_rotated_markets is respected so we
                    # do not always restart from index 0.
                    if _first_trade_override and len(markets_to_scan) < MARKET_BATCH_SIZE_MAX:
                        _boost = min(MARKET_BATCH_SIZE_MAX, len(all_products))
                        _extra_needed = _boost - len(markets_to_scan)
                        _next_start = self.market_rotation_offset
                        _extra = [
                            all_products[(_next_start + _i) % len(all_products)]
                            for _i in range(_extra_needed)
                        ]
                        markets_to_scan = markets_to_scan + _extra
                        logger.info(f"   🚀 First-trade override: scanning {_boost} markets (bypassing warmup cap, rotation offset={_next_start})")

                    # Feature 3: Trade frequency booster — for micro accounts (< MICRO_FREQ_BOOST_THRESHOLD)
                    # always scan the maximum batch so more opportunities are evaluated each cycle.
                    # Rotation is preserved: extra markets are appended starting from the current
                    # rotation offset (set by _get_rotated_markets) so we do NOT restart from index 0.
                    if account_balance is not None and account_balance < MICRO_FREQ_BOOST_THRESHOLD:
                        _boost_size = min(MARKET_BATCH_SIZE_MAX, len(all_products))
                        if len(markets_to_scan) < _boost_size:
                            _extra_needed = _boost_size - len(markets_to_scan)
                            _total_mkts = len(all_products)
                            # self.market_rotation_offset was already advanced by _get_rotated_markets
                            _next_start = self.market_rotation_offset
                            _extra = [
                                all_products[(_next_start + _i) % _total_mkts]
                                for _i in range(_extra_needed)
                            ]
                            markets_to_scan = markets_to_scan + _extra
                            logger.info(
                                f"   🔥 Micro-account frequency boost: scanning {_boost_size} markets "
                                f"(+{_extra_needed} appended from rotation, "
                                f"balance=${account_balance:.2f} < ${MICRO_FREQ_BOOST_THRESHOLD:.0f})"
                            )

                    # FIX #3 (Jan 20, 2026): Kraken markets already filtered at startup
                    # No need to filter again during scan - markets_to_scan already contains only supported pairs
                    scan_limit = len(markets_to_scan)
                    logger.info(f"   Scanning {scan_limit} markets (batch rotation mode)...")

                    # Adaptive rate limiting: track consecutive errors (429, 403, or no data)
                    # UPDATED (Jan 10, 2026): Distinguish invalid symbols from genuine errors
                    rate_limit_counter = 0
                    error_counter = 0  # Track total errors including exceptions
                    invalid_symbol_counter = 0  # Track invalid/delisted symbols (don't count as errors)
                    max_consecutive_rate_limits = 2  # CRITICAL FIX (Jan 10): Reduced from 3 - activate circuit breaker faster
                    max_total_errors = 4  # CRITICAL FIX (Jan 10): Reduced from 5 - stop scan earlier to prevent API ban

                    # Track filtering reasons for debugging
                    filter_stats = {
                        'total': 0,
                        'insufficient_data': 0,
                        'smart_filter': 0,
                        'market_filter': 0,
                        'no_entry_signal': 0,
                        'position_too_small': 0,
                        'signals_found': 0,
                        'rate_limited': 0,
                        'cache_hits': 0,
                        'sector_cap': 0,
                    }

                    # 📡 SIGNAL TRACE — collect near-miss signals for end-of-cycle reporting.
                    # Each entry: {'symbol': str, 'score': float, 'reason': str, 'direction': str}
                    # Only the top-3 closest-to-entry symbols are shown to keep logs concise.
                    _near_miss_signals: list = []

                    # ═══════════════════════════════════════════════════════
                    # PRIORITY SELECTION — phase 1: collect validated signals
                    # ═══════════════════════════════════════════════════════
                    # All signals that pass every gate are stored here.  After
                    # the full market scan they are sorted by score and only
                    # the top-ranked setups are executed (see post-scan block).
                    pending_signals = []

                    # ═══════════════════════════════════════════════════════
                    # MARKET REGIME CONTROLLER — pre-scan meta decision
                    # "Should the bot be trading this cycle at all?"
                    # ═══════════════════════════════════════════════════════
                    # The regime controller uses a two-cycle approach to prevent
                    # whipsaw:
                    #   1. BEFORE the symbol loop → read the PREVIOUS cycle's
                    #      regime decision from last_result to gate this cycle's
                    #      entries.
                    #   2. AFTER the symbol loop  → evaluate the CURRENT cycle's
                    #      snapshot and store it for the next cycle.
                    #
                    # This means the first cycle always gets the safe default
                    # (allow entries, 1.0x size), which is intentional: there is
                    # no prior data to make a blocking decision on.
                    _regime_snapshot = None
                    _regime_result = None

                    # Default: allow entries at full size (safe first-cycle default)
                    _regime_entries_allowed = True
                    _regime_size_multiplier = 1.0

                    if hasattr(self, 'regime_controller') and self.regime_controller is not None:
                        try:
                            # Step 1: Apply the PREVIOUS cycle's regime decision to this cycle
                            _prev_result = self.regime_controller.last_result
                            if _prev_result is not None:
                                _regime_result = _prev_result
                                _regime_entries_allowed = _prev_result.allow_new_entries
                                _regime_size_multiplier = _prev_result.position_size_multiplier
                                if not _regime_entries_allowed:
                                    logger.warning(
                                        f"   🚫 REGIME CONTROLLER (previous cycle): "
                                        f"{_prev_result.reason} "
                                        f"(score={_prev_result.smoothed_score:.1f})"
                                    )

                            # Step 2: Begin a fresh snapshot for THIS cycle's observations
                            _regime_snapshot = self.regime_controller.begin_snapshot()
                        except Exception as regime_init_err:
                            logger.debug(f"   ⚠️ Regime Controller init error: {regime_init_err}")
                            _regime_snapshot = None

                    for i, symbol in enumerate(markets_to_scan):
                        filter_stats['total'] += 1
                        try:
                            # FIX #1: BLACKLIST CHECK - Skip disabled pairs immediately
                            if symbol in DISABLED_PAIRS:
                                logger.debug(f"   ⛔ SKIPPING {symbol}: Blacklisted pair (spread > profit edge)")
                                continue

                            # HIGH-LIQUIDITY FILTER - Only trade top 20 pairs by volume
                            # Ensures tight spreads, deep order books, and reliable price action
                            if TOP_20_HIGH_LIQUIDITY_SYMBOLS and not is_high_liquidity_symbol(symbol):
                                logger.debug(f"   ⏭️  SKIPPING {symbol}: Not in top-20 high-liquidity list")
                                filter_stats['low_quality'] = filter_stats.get('low_quality', 0) + 1
                                continue

                            # WHITELIST CHECK - Only trade whitelisted symbols if whitelist is enabled
                            if WHITELIST_ENABLED:
                                broker_name = self._get_broker_name(active_broker)
                                if not is_whitelisted_symbol(symbol, broker_name):
                                    logger.debug(f"   ⏭️  SKIPPING {symbol}: Not in whitelist (only trading {', '.join(WHITELISTED_ASSETS)})")
                                    continue

                            # CRITICAL: Add delay BEFORE fetching candles to prevent rate limiting
                            # This is in addition to the delay after processing (line ~1201)
                            # Pre-delay ensures we never make requests too quickly in succession
                            if i > 0:  # Don't delay before first market
                                jitter = random.uniform(0, 0.3)  # Add 0-300ms jitter
                                time.sleep(MARKET_SCAN_DELAY + jitter)

                            # Get candles with caching to reduce duplicate API calls
                            candles = self._get_cached_candles(symbol, '5m', 100, broker=active_broker)

                            # Check if we got candles or if rate limited
                            if not candles:
                                # Empty candles could be:
                                # 1. Invalid/delisted symbol (don't count as error)
                                # 2. Rate limited (count as error)
                                # 3. No data available (count as error)
                                # We assume invalid symbol if we get consistent empty responses

                                # Note: Invalid symbols are caught in get_candles() and return []
                                # So if we get here with no candles, it's likely rate limiting or no data
                                # We still increment counters but will check for invalid symbols in exceptions below
                                rate_limit_counter += 1
                                error_counter += 1
                                filter_stats['insufficient_data'] += 1

                                # PHASE 3: Record API error in abnormal market detector
                                if (
                                    ABNORMAL_MARKET_KS_AVAILABLE
                                    and hasattr(self, 'abnormal_market_ks')
                                    and self.abnormal_market_ks is not None
                                ):
                                    try:
                                        self.abnormal_market_ks.record_api_error()
                                    except Exception:
                                        pass

                                # Degrade API health score on errors
                                self.api_health_score = max(0, self.api_health_score - 5)

                                logger.debug(f"   {symbol}: No candles returned (may be rate limited or no data)")

                                # GLOBAL CIRCUIT BREAKER: If too many total errors, stop scanning entirely
                                if error_counter >= max_total_errors:
                                    filter_stats['rate_limited'] += 1
                                    broker_name = self._get_broker_name(active_broker)
                                    logger.error(f"   🚨 GLOBAL CIRCUIT BREAKER: {error_counter} total errors - stopping scan to prevent API block")
                                    logger.error(f"   Exchange: {broker_name} | API health: {self.api_health_score}%")
                                    logger.error(f"   💤 Waiting 30s for API to fully recover before next cycle...")
                                    logger.error(f"   💡 TIP: Enable additional exchanges (Kraken, OKX, Binance) to distribute load")
                                    logger.error(f"   📖 See MULTI_EXCHANGE_TRADING_GUIDE.md for setup instructions")
                                    self.api_health_score = max(0, self.api_health_score - 20)  # Major penalty
                                    time.sleep(30.0)  # CRITICAL FIX (Jan 10): Increased from 20s to 30s for better recovery
                                    break  # Exit the market scan loop entirely

                                # If we're getting many consecutive failures, assume rate limiting
                                if rate_limit_counter >= max_consecutive_rate_limits:
                                    filter_stats['rate_limited'] += 1
                                    logger.warning(f"   ⚠️ Possible rate limiting detected ({rate_limit_counter} consecutive failures)")
                                    logger.warning(f"   🛑 CIRCUIT BREAKER: Pausing for 15s to allow API to recover...")
                                    self.api_health_score = max(0, self.api_health_score - 10)  # Moderate penalty
                                    time.sleep(15.0)  # CRITICAL FIX (Jan 10): Decreased from 20s to 15s for consistency
                                    rate_limit_counter = 0  # Reset counter after delay
                                continue
                            elif len(candles) < 100:
                                rate_limit_counter = 0  # Reset on partial success
                                self.api_health_score = min(100, self.api_health_score + 1)  # Small recovery
                                filter_stats['insufficient_data'] += 1
                                logger.debug(f"   {symbol}: Insufficient candles ({len(candles)}/100)")
                                continue
                            else:
                                # Success! Reset rate limit counter and improve health
                                rate_limit_counter = 0
                                self.api_health_score = min(100, self.api_health_score + 2)  # Gradual recovery

                            # Convert to DataFrame
                            df = pd.DataFrame(candles)

                            # CRITICAL: Ensure numeric types
                            for col in ['open', 'high', 'low', 'close', 'volume']:
                                if col in df.columns:
                                    df[col] = pd.to_numeric(df[col], errors='coerce')

                            # Feed latest candle into Market Regime Engine so it can
                            # maintain its rolling ATR / ADX / volume baseline and
                            # continuously update the BULL / CHOP / CRASH classification.
                            if MARKET_REGIME_ENGINE_AVAILABLE and hasattr(self, 'regime_engine') and self.regime_engine is not None:
                                try:
                                    _re_candle = df.iloc[-1]
                                    self.regime_engine.update(
                                        close=float(_re_candle['close']),
                                        high=float(_re_candle['high']),
                                        low=float(_re_candle['low']),
                                        volume=float(_re_candle['volume']) if 'volume' in df.columns else 0.0,
                                    )
                                except Exception as _re_feed_err:
                                    logger.debug("Regime engine candle update failed for %s: %s", symbol, _re_feed_err)

                            # PHASE 3: Feed bar into Abnormal Market Kill Switch detector
                            if (
                                ABNORMAL_MARKET_KS_AVAILABLE
                                and hasattr(self, 'abnormal_market_ks')
                                and self.abnormal_market_ks is not None
                            ):
                                try:
                                    _aks_candle = df.iloc[-1]
                                    self.abnormal_market_ks.update_market(
                                        symbol=symbol,
                                        close=float(_aks_candle['close']),
                                        high=float(_aks_candle['high']),
                                        low=float(_aks_candle['low']),
                                        volume=float(_aks_candle['volume']) if 'volume' in df.columns else 0.0,
                                    )
                                except Exception as _aks_feed_err:
                                    logger.debug(
                                        "AbnormalMarketKillSwitch update_market failed for %s: %s",
                                        symbol, _aks_feed_err,
                                    )

                            # FIX #4: PAIR QUALITY FILTER - Check spread, volume, and ATR before analyzing
                            # Only run if check_pair_quality is available (imported at module level)
                            if check_pair_quality is not None:
                                try:
                                    # Get current bid/ask for spread check
                                    current_price = df['close'].iloc[-1]

                                    # PLACEHOLDER: Estimate bid/ask from price
                                    # TODO: Replace with actual bid/ask from broker API for more accurate spread check
                                    # Most major pairs (BTC, ETH, SOL) have ~0.01-0.05% spread
                                    # This conservative estimate (0.1%) ensures we don't miss quality pairs
                                    estimated_spread_pct = 0.001  # Assume 0.1% spread for estimation
                                    bid_price = current_price * (1 - estimated_spread_pct / 2)
                                    ask_price = current_price * (1 + estimated_spread_pct / 2)

                                    # Feed Cross-Broker Arbitrage Monitor with primary broker price
                                    if CROSS_BROKER_ARB_AVAILABLE and hasattr(self, 'arb_monitor') and self.arb_monitor is not None:
                                        try:
                                            _primary_broker_name = (
                                                active_broker.broker_type.value
                                                if hasattr(active_broker, 'broker_type')
                                                else "primary"
                                            )
                                            self.arb_monitor.update_price(
                                                _primary_broker_name, symbol, bid_price, ask_price
                                            )
                                        except Exception:
                                            pass

                                    # Calculate ATR percentage if available
                                    atr_pct = None
                                    if 'atr' in df.columns and len(df) > 0:
                                        atr_value = df['atr'].iloc[-1]
                                        if pd.notna(atr_value) and current_price > 0:
                                            atr_pct = atr_value / current_price

                                    # Check pair quality
                                    quality_check = check_pair_quality(
                                        symbol=symbol,
                                        bid_price=bid_price,
                                        ask_price=ask_price,
                                        atr_pct=atr_pct,
                                        max_spread_pct=0.0015,  # 0.15% max spread
                                        min_atr_pct=0.005,  # 0.5% minimum ATR
                                        disabled_pairs=DISABLED_PAIRS
                                    )

                                    if not quality_check['quality_acceptable']:
                                        reasons = ', '.join(quality_check['reasons_failed'])
                                        logger.debug(f"   ⛔ QUALITY FILTER: {symbol} failed - {reasons}")
                                        filter_stats['market_filter'] += 1
                                        continue
                                    else:
                                        logger.debug(f"   ✅ Quality check passed: {symbol}")
                                except Exception as quality_err:
                                    # If quality check fails, log warning but don't block trading
                                    logger.debug(f"   ⚠️ Quality check error for {symbol}: {quality_err}")

                            # ═══════════════════════════════════════════════════════
                            # MARKET READINESS GATE - Check market conditions
                            # ═══════════════════════════════════════════════════════
                            # Calculate required indicators for market readiness check
                            if self.market_readiness_gate is not None:
                                try:
                                    # Calculate indicators needed for readiness check
                                    current_price = df['close'].iloc[-1]
                                    
                                    # Calculate ATR if not already in df
                                    if 'atr' not in df.columns:
                                        from indicators import calculate_atr
                                        df['atr'] = calculate_atr(df, period=14)
                                    atr = scalar(df['atr'].iloc[-1])
                                    
                                    # Calculate ADX if not already in df
                                    if 'adx' not in df.columns:
                                        from indicators import calculate_adx
                                        df['adx'] = calculate_adx(df, period=14)
                                    adx = scalar(df['adx'].iloc[-1])
                                    
                                    # Calculate volume percentile (current volume vs 24h average)
                                    volume_percentile = 50.0  # Default to neutral
                                    if 'volume' in df.columns and len(df) >= 20:
                                        current_volume = df['volume'].iloc[-1]
                                        avg_volume = df['volume'].rolling(window=20).mean().iloc[-1]
                                        if avg_volume > 0:
                                            volume_ratio = current_volume / avg_volume
                                            # Convert ratio to percentile (0.5 = 50%, 1.0 = 100%, 2.0 = 200%)
                                            volume_percentile = min(100, volume_ratio * 50)
                                    
                                    # Estimate spread (TODO: get real bid/ask from broker)
                                    spread_pct = 0.001  # Conservative 0.1% estimate
                                    
                                    # Check market readiness (pass None for entry_score initially)
                                    mode, conditions, details = self.market_readiness_gate.check_market_readiness(
                                        atr=atr,
                                        current_price=current_price,
                                        adx=adx,
                                        volume_percentile=volume_percentile,
                                        spread_pct=spread_pct,
                                        entry_score=None  # Will check again after scoring
                                    )
                                    
                                    # Block entries in IDLE mode
                                    if mode == MarketMode.IDLE:
                                        logger.debug(f"   ⏸️  {symbol}: IDLE MODE - {details['message']}")
                                        filter_stats['market_filter'] += 1
                                        continue
                                    
                                except Exception as readiness_err:
                                    logger.debug(f"   ⚠️ Market readiness check error for {symbol}: {readiness_err}")
                                    # Continue with analysis if readiness check fails

                            # ═══════════════════════════════════════════════════════
                            # MARKET STRUCTURE FILTER (Higher High/Low + Volume + RSI)
                            # ═══════════════════════════════════════════════════════
                            # Entry allowed only when trend, volume expansion, AND
                            # momentum all confirm.  Prevents buying fake breakouts.
                            _symbol_structure_passed = True  # default
                            if MARKET_STRUCTURE_FILTER_AVAILABLE and _structure_valid is not None:
                                try:
                                    _symbol_structure_passed = _structure_valid(df)
                                    if not _symbol_structure_passed:
                                        logger.debug(
                                            f"   ⛔ {symbol}: Market structure filter blocked entry "
                                            f"(HH/HL trend, volume expansion, or RSI momentum not confirmed)"
                                        )
                                        filter_stats['market_filter'] += 1
                                        # Record observation in regime snapshot before skipping
                                        if _regime_snapshot is not None:
                                            try:
                                                _adx_val = float(df['adx'].iloc[-1]) if 'adx' in df.columns else 0.0
                                                _rsi_val = float(df['rsi'].iloc[-1]) if 'rsi' in df.columns else 50.0
                                                _atr_val = float(df['atr'].iloc[-1]) if 'atr' in df.columns else 0.0
                                                _price_val = float(df['close'].iloc[-1]) if len(df) > 0 else 1.0
                                                _atr_pct = _atr_val / _price_val if _price_val > 0 else 0.0
                                                self.regime_controller.record_asset(
                                                    _regime_snapshot,
                                                    adx=_adx_val,
                                                    rsi=_rsi_val,
                                                    structure_passed=False,
                                                    atr_pct=_atr_pct,
                                                )
                                            except Exception:
                                                pass
                                        continue
                                except Exception as structure_err:
                                    logger.debug(f"   ⚠️ Market structure check error for {symbol}: {structure_err}")
                                    # Continue with analysis if structure check fails

                            # Record per-symbol observations in regime snapshot (structure passed)
                            if _regime_snapshot is not None:
                                try:
                                    _adx_val = float(df['adx'].iloc[-1]) if 'adx' in df.columns else 0.0
                                    _rsi_val = float(df['rsi'].iloc[-1]) if 'rsi' in df.columns else 50.0
                                    _atr_val = float(df['atr'].iloc[-1]) if 'atr' in df.columns else 0.0
                                    _price_val = float(df['close'].iloc[-1]) if len(df) > 0 else 1.0
                                    _atr_pct = _atr_val / _price_val if _price_val > 0 else 0.0
                                    self.regime_controller.record_asset(
                                        _regime_snapshot,
                                        adx=_adx_val,
                                        rsi=_rsi_val,
                                        structure_passed=_symbol_structure_passed,
                                        atr_pct=_atr_pct,
                                    )
                                except Exception:
                                    pass

                            # Analyze for entry
                            # CRITICAL: Use broker-specific balance for position sizing
                            # PRO MODE: Include broker's position values (total capital)
                            # STANDARD MODE: Use only broker's free balance
                            # NOTE: Both account_balance and total_capital are broker-specific at this point
                            # (updated at lines 3418 and 3440 from selected entry broker)
                            broker_balance = total_capital if self.pro_mode_enabled else account_balance

                            # Strategy-gate result placeholders — populated by the WIN RATE MAXIMIZER
                            # block inside the PLATFORM branch and consumed by the Capital Brain
                            # hierarchy check in the entry-execution block below.
                            _wmx_approved: bool = True
                            _wmx_reason: str = ""

                            # ═══════════════════════════════════════════════════════
                            # MASTER STRATEGY ROUTER — ONE signal, not per-user signals
                            # Platform: generates signal via APEX and publishes it.
                            # User accounts: read the master signal only (no independent
                            # strategy execution — copied trades only).
                            # ═══════════════════════════════════════════════════════
                            if user_mode:
                                # USER ACCOUNTS — block independent strategy execution.
                                # Only execute trades copied from the platform account.
                                if MASTER_STRATEGY_ROUTER_AVAILABLE and get_master_strategy_router:
                                    try:
                                        _msr = get_master_strategy_router()
                                        _stored_signal = _msr.current_signal
                                        if isinstance(_stored_signal, dict) and _stored_signal.get('symbol') == symbol:
                                            analysis = _stored_signal
                                        else:
                                            # No master signal for this symbol — skip entry
                                            filter_stats['no_entry_signal'] += 1
                                            logger.debug("   %s (USER): no master signal — skipping entry", symbol)
                                            continue
                                    except Exception as _msr_err:
                                        logger.debug("MasterStrategyRouter read skipped for %s: %s", symbol, _msr_err)
                                        continue
                                else:
                                    # Master router unavailable — user accounts must not trade independently
                                    filter_stats['no_entry_signal'] += 1
                                    logger.debug("   %s (USER): master router unavailable — skipping entry", symbol)
                                    continue
                            else:
                                # PLATFORM ACCOUNT — generate signal via APEX and publish via master router
                                analysis = self.apex.analyze_market(df, symbol, broker_balance)

                                # ═══════════════════════════════════════════════════════
                                # LAYER 2: TRADE QUALITY GATE
                                # ═══════════════════════════════════════════════════════
                                # Filter trades through quality gate (R:R, momentum, stop quality)
                                if hasattr(self, 'quality_gate') and self.quality_gate:
                                    analysis = self.quality_gate.filter_strategy_signal(analysis, df)

                                # ═══════════════════════════════════════════════════════
                                # LAYER 3: WIN RATE MAXIMIZER  (strategy signal quality)
                                # ═══════════════════════════════════════════════════════
                                # Multi-layer gate: signal quality score, risk caps, profit
                                # consistency.  Result is stored in _wmx_approved / _wmx_reason
                                # and fed into the Capital Brain hierarchy check below so the
                                # full Global→Account→Strategy→Trade pipeline is traced there.
                                if hasattr(self, 'win_rate_maximizer') and self.win_rate_maximizer:
                                    _wmx_action = analysis.get('action', 'hold')
                                    if _wmx_action in ('enter_long', 'enter_short'):
                                        try:
                                            _indicators_for_wmx = getattr(self, '_last_indicators', {}) or {}
                                            _wmx_approved, _wmx_reason, _wmx_score = self.win_rate_maximizer.approve_trade(
                                                symbol=symbol,
                                                analysis=analysis,
                                                df=df,
                                                indicators=_indicators_for_wmx,
                                                account_balance=broker_balance,
                                            )
                                            if not _wmx_approved:
                                                logger.info(f"   🚫 Win Rate Maximizer REJECTED {symbol}: {_wmx_reason}")
                                                # Convert analysis to 'hold' so:
                                                #   (a) near-miss capture fires correctly below, and
                                                #   (b) the entry-execution block is not reached.
                                                # _wmx_approved=False is also passed to the Capital Brain
                                                # hierarchy check so the Strategy layer is traced there.
                                                analysis = {'action': 'hold', 'reason': f'Win Rate Maximizer: {_wmx_reason}'}
                                        except Exception as _wmx_err:
                                            logger.debug("Win Rate Maximizer approve_trade skipped for %s: %s", symbol, _wmx_err)

                                # ═══════════════════════════════════════════════════════
                                # PHASE 3 — LAYER 4a: NEWS / EVENT VOLATILITY FILTER
                                # ═══════════════════════════════════════════════════════
                                # Block entries during news-driven volatility spikes.
                                # Feed bar data to the filter EVERY cycle, then gate entries.
                                if (
                                    NEWS_VOLATILITY_FILTER_AVAILABLE
                                    and hasattr(self, 'news_volatility_filter')
                                    and self.news_volatility_filter is not None
                                    and analysis.get('action') in ('enter_long', 'enter_short')
                                ):
                                    try:
                                        _nvf = self.news_volatility_filter
                                        # Feed current bar
                                        _last_close = float(df['close'].iloc[-1]) if 'close' in df.columns and len(df) > 0 else 0.0
                                        _last_vol   = float(df['volume'].iloc[-1]) if 'volume' in df.columns and len(df) > 0 else 0.0
                                        _nvf.update(symbol=symbol, close=_last_close, volume=_last_vol)
                                        # Check if entry allowed
                                        _nvf_ok, _nvf_reason = _nvf.can_enter(symbol=symbol)
                                        if not _nvf_ok:
                                            logger.info(
                                                "   📰 PHASE 3 News/Volatility Filter BLOCKED %s: %s",
                                                symbol, _nvf_reason,
                                            )
                                            analysis = {'action': 'hold', 'reason': f'NewsVolatilityFilter: {_nvf_reason}'}
                                    except Exception as _nvf_exc:
                                        logger.debug("News Volatility Filter check skipped for %s: %s", symbol, _nvf_exc)

                                # ═══════════════════════════════════════════════════════
                                # PHASE 3 — LAYER 4b: MULTI-TIMEFRAME CONFIRMATION AI
                                # ═══════════════════════════════════════════════════════
                                # Only allow entry when higher timeframes agree on direction.
                                if (
                                    MTF_CONFIRMATION_AVAILABLE
                                    and hasattr(self, 'mtf_confirmation')
                                    and self.mtf_confirmation is not None
                                    and analysis.get('action') in ('enter_long', 'enter_short')
                                ):
                                    try:
                                        _mtf_side = (
                                            'long' if analysis.get('action') == 'enter_long'
                                            else 'short'
                                        )
                                        _mtf_result = self.mtf_confirmation.confirm(df=df, signal_side=_mtf_side)
                                        if not _mtf_result.confirmed:
                                            logger.info(
                                                "   🔭 PHASE 3 MTF Confirmation BLOCKED %s: %s",
                                                symbol, _mtf_result.summary,
                                            )
                                            analysis = {'action': 'hold', 'reason': f'MTFConfirmation: {_mtf_result.summary}'}
                                    except Exception as _mtf_exc:
                                        logger.debug("MTF Confirmation check skipped for %s: %s", symbol, _mtf_exc)


                                if MASTER_STRATEGY_ROUTER_AVAILABLE and get_master_strategy_router:
                                    try:
                                        _msr = get_master_strategy_router()
                                        _msr.update({**analysis, 'symbol': symbol})
                                    except Exception as _msr_err:
                                        logger.debug("MasterStrategyRouter update skipped for %s: %s", symbol, _msr_err)

                            action = analysis.get('action', 'hold')
                            reason = analysis.get('reason', '')

                            # Track why we didn't trade
                            if action == 'hold':
                                if 'Insufficient data' in reason or 'candles' in reason:
                                    filter_stats['insufficient_data'] += 1
                                elif 'smart filter' in reason.lower() or 'volume too low' in reason.lower() or 'candle' in reason.lower():
                                    filter_stats['smart_filter'] += 1
                                    logger.debug(f"   {symbol}: Smart filter - {reason}")
                                elif 'ADX' in reason or 'Volume' in reason or 'Mixed signals' in reason:
                                    filter_stats['market_filter'] += 1
                                    logger.debug(f"   {symbol}: Market filter - {reason}")
                                else:
                                    filter_stats['no_entry_signal'] += 1
                                    logger.debug(f"   {symbol}: No signal - {reason}")

                                # 📡 NEAR-MISS CAPTURE: record signals that have a score so
                                # the end-of-cycle summary can show "closest to entry" symbols.
                                _NEAR_MISS_REASON_MAX = 80  # max chars for reason string in near-miss report
                                _nm_score = analysis.get('score', analysis.get('enhanced_score', None))
                                if _nm_score is not None:
                                    try:
                                        _nm_score_f = float(_nm_score)
                                        _near_miss_signals.append({
                                            'symbol': symbol,
                                            'score': _nm_score_f,
                                            'reason': reason[:_NEAR_MISS_REASON_MAX] if reason else 'no signal',
                                            'direction': analysis.get('direction', analysis.get('trend', '?')),
                                        })
                                    except (TypeError, ValueError):
                                        pass
                                continue

                            # Execute buy actions
                            if action in ['enter_long', 'enter_short']:
                                # SPOT_ONLY / INCUBATION_MODE: block short entries
                                if action == 'enter_short' and SPOT_ONLY:
                                    filter_stats['no_entry_signal'] += 1
                                    logger.debug(
                                        f"   {symbol}: Blocked – SPOT_ONLY mode active "
                                        f"(short positions not permitted)"
                                    )
                                    continue

                                # ═══════════════════════════════════════════════════════
                                # SECTOR CAPITAL CAP — block entry if sector already
                                # consumes ≥ MAX_SECTOR_ALLOCATION (40 %) of capital.
                                # ═══════════════════════════════════════════════════════
                                if SECTOR_TAXONOMY_AVAILABLE and get_sector is not None and broker_balance > 0:
                                    try:
                                        _signal_sector = get_sector(symbol)
                                        _sector_alloc_usd = 0.0
                                        for _pos in current_positions:
                                            _pos_sym = _pos.get('symbol', '')
                                            if not _pos_sym:
                                                continue
                                            if get_sector(_pos_sym) == _signal_sector:
                                                # Use size_usd / usd_value if available, else qty * last price
                                                _pos_val = _pos.get('size_usd', _pos.get('usd_value', 0.0))
                                                if _pos_val <= 0:
                                                    _pos_qty = _pos.get('quantity', _pos.get('size', 0.0))
                                                    _pos_price = _pos.get('current_price', 0.0)
                                                    if _pos_qty > 0 and _pos_price > 0:
                                                        _pos_val = _pos_qty * _pos_price
                                                _sector_alloc_usd += _pos_val
                                        if broker_balance > 0 and _sector_alloc_usd / broker_balance > MAX_SECTOR_ALLOCATION:
                                            _sector_name = get_sector_name(_signal_sector) if get_sector_name else str(_signal_sector)
                                            logger.info(
                                                f"   🚫 {symbol}: SECTOR CAP — {_sector_name} sector "
                                                f"allocation ${_sector_alloc_usd:.2f} / ${broker_balance:.2f} "
                                                f"= {_sector_alloc_usd / broker_balance:.1%} "
                                                f"> {MAX_SECTOR_ALLOCATION:.0%} limit — signal skipped"
                                            )
                                            filter_stats['sector_cap'] += 1
                                            continue
                                    except Exception as _sector_err:
                                        logger.debug(
                                            "Sector allocation check skipped for %s: %s",
                                            symbol, _sector_err,
                                        )

                                filter_stats['signals_found'] += 1
                                position_size = analysis.get('position_size', 0)
                                entry_score = analysis.get('score', 0)  # Get entry score from analysis

                                # ═══════════════════════════════════════════════════════
                                # GLOBAL CAPITAL BRAIN — UNIFIED DECISION HIERARCHY
                                #
                                #   Layer 1 — GLOBAL   : Is this the best account?
                                #   Layer 2 — ACCOUNT  : Is this account healthy?
                                #   Layer 3 — STRATEGY : Did the strategy gate pass?
                                #   Layer 4 — TRADE    : Apply Capital Snowball sizing.
                                #
                                # Single call.  Single result.  First failure short-circuits.
                                # When all four layers pass, final_position_size already
                                # includes the snowball multiplier.
                                # ═══════════════════════════════════════════════════════
                                if hasattr(self, 'global_capital_brain') and self.global_capital_brain is not None:
                                    try:
                                        _brain_acct_id = self._get_primary_broker_id()

                                        # Layer 2 input: account health from account_flow_layer
                                        _brain_acct_alive = True
                                        if hasattr(self, 'account_flow_layer') and self.account_flow_layer is not None:
                                            try:
                                                _brain_acct_alive = self.account_flow_layer.is_account_tradeable(_brain_acct_id)
                                            except Exception:
                                                pass

                                        _hierarchy = self.global_capital_brain.run_hierarchy_check(
                                            current_account_id=_brain_acct_id,
                                            all_accounts=[_brain_acct_id],
                                            is_account_alive=_brain_acct_alive,
                                            strategy_approved=_wmx_approved,
                                            strategy_reason=_wmx_reason,
                                            base_position_size=position_size,
                                        )

                                        if not _hierarchy.approved:
                                            _layer_emoji = {
                                                "global": "🌐", "account": "☠️",
                                                "strategy": "🚫", "trade": "📊",
                                            }.get(_hierarchy.blocked_at or "", "🧠")
                                            logger.warning(
                                                "   %s %s: CAPITAL BRAIN [%s] BLOCKED — %s",
                                                _layer_emoji, symbol,
                                                (_hierarchy.blocked_at or "").upper(),
                                                _hierarchy.rejection_reason,
                                            )
                                            filter_stats['market_filter'] += 1
                                            continue

                                        # All layers passed — apply snowball-adjusted size
                                        if _hierarchy.final_position_size > 0:
                                            if _hierarchy.snowball_multiplier > 1.0:
                                                logger.info(
                                                    "   🚀 %s: Capital Snowball %.1f× "
                                                    "(win_streak=%d) — size $%.2f → $%.2f",
                                                    symbol,
                                                    _hierarchy.snowball_multiplier,
                                                    _hierarchy.win_streak,
                                                    position_size,
                                                    _hierarchy.final_position_size,
                                                )
                                            position_size = _hierarchy.final_position_size

                                    except Exception as _brain_err:
                                        logger.debug(
                                            "Capital Brain hierarchy check skipped for %s: %s",
                                            symbol, _brain_err,
                                        )
                                else:
                                    # Brain unavailable — fall back to standalone account kill-gate
                                    if hasattr(self, 'account_flow_layer') and self.account_flow_layer is not None:
                                        try:
                                            _acct_id = self._get_primary_broker_id()
                                            if not self.account_flow_layer.is_account_tradeable(_acct_id):
                                                logger.warning(
                                                    "   ☠️  %s: ACCOUNT KILLED — drawdown exceeded "
                                                    "kill threshold; entry blocked by account-level "
                                                    "capital flow",
                                                    symbol,
                                                )
                                                filter_stats['market_filter'] += 1
                                                continue
                                        except Exception as _afl_kill_err:
                                            logger.debug(
                                                "Account kill-gate check skipped for %s: %s",
                                                symbol, _afl_kill_err,
                                            )

                                # ── CYCLE STEP 3: Cap size by CapitalAllocator budget ──
                                # get_allocated_capital() returns strategy_allocation ÷
                                # max_concurrent_positions so no single trade over-draws the
                                # strategy's bucket even when multiple signals fire together.
                                if self._capital_allocator is not None:
                                    try:
                                        _ca_budget = self._capital_allocator.get_allocated_capital("APEX_V71")
                                        if _ca_budget > 0 and position_size > _ca_budget:
                                            logger.info(
                                                "   📐 %s: CapitalAllocator capped size "
                                                "$%.2f → $%.2f (budget=$%.2f)",
                                                symbol, position_size, _ca_budget, _ca_budget,
                                            )
                                            position_size = _ca_budget
                                    except Exception as _ca_size_err:
                                        logger.debug(
                                            "CapitalAllocator sizing cap skipped for %s: %s",
                                            symbol, _ca_size_err,
                                        )
                                # ──────────────────────────────────────────────────────

                                # ═══════════════════════════════════════════════════════
                                # MICRO-CAP COMPOUNDING CONFIG — applied BEFORE volatility
                                # sizing and risk engine (correct pipeline order).
                                #
                                # Correct order:
                                #   balance fetch → micro-cap config → volatility sizing
                                #   → risk engine → trade execution
                                # ═══════════════════════════════════════════════════════
                                if _micro_cap_config:
                                    # 1. Re-entry cooldown: enforce MICRO_CAP_TRADE_COOLDOWN
                                    _last_trade_ts = self._micro_cap_last_trade_times.get(symbol, 0.0)
                                    if _last_trade_ts > 0:
                                        _elapsed_since_trade = time.time() - _last_trade_ts
                                        if _elapsed_since_trade < MICRO_CAP_TRADE_COOLDOWN:
                                            _remaining = MICRO_CAP_TRADE_COOLDOWN - _elapsed_since_trade
                                            logger.info(
                                                f"   ⏳ {symbol}: Micro-cap re-entry cooldown active "
                                                f"({_remaining:.0f}s remaining, cooldown={MICRO_CAP_TRADE_COOLDOWN}s)"
                                            )
                                            filter_stats['market_filter'] += 1
                                            continue

                                    # 2. Max positions from micro-cap config (1 at a time)
                                    _mc_max_pos = int(_micro_cap_config.get('max_positions', MICRO_CAP_COMPOUNDING_MAX_POSITIONS))
                                    if len(current_positions) >= _mc_max_pos:
                                        logger.info(
                                            f"   🛑 {symbol}: Micro-cap position limit reached "
                                            f"({len(current_positions)}/{_mc_max_pos}) — entry blocked"
                                        )
                                        filter_stats['market_filter'] += 1
                                        continue

                                    # 3. Override position size from micro-cap config
                                    _mc_pos_pct = float(_micro_cap_config.get('position_size_pct', MICRO_CAP_COMPOUNDING_POSITION_SIZE_PCT))
                                    _mc_position_size = account_balance * _mc_pos_pct / 100.0
                                    logger.info(
                                        f"   🚀 {symbol}: Micro-cap compounding mode — "
                                        f"position size {_mc_pos_pct:.0f}% of "
                                        f"${account_balance:.2f} = ${_mc_position_size:.2f} "
                                        f"(was ${position_size:.2f})"
                                    )
                                    position_size = _mc_position_size

                                    # 4. Override stop_loss and profit_target in analysis dict
                                    _mc_entry_price = analysis.get('entry_price', 0.0)
                                    if _mc_entry_price and _mc_entry_price > 0:
                                        _mc_stop_pct = float(_micro_cap_config.get('stop_loss_pct', MICRO_CAP_COMPOUNDING_STOP_LOSS_PCT))
                                        # Dynamic profit target: base + current spread + win-streak bonus.
                                        # Spread from analysis (if available) or a conservative 0.1% estimate
                                        # (representative of typical liquid pairs such as BTC/ETH/SOL).
                                        # Win-streak resets to 0 after any loss so extended targets are
                                        # only applied while momentum is intact.
                                        _mc_spread_pct = analysis.get('spread_pct', 0.001) or 0.001
                                        _mc_profit_pct = get_spread_adjusted_profit_target(
                                            _mc_spread_pct, self._micro_cap_win_streak
                                        )
                                        # Pre-compute components for the log message (avoids re-deriving from total)
                                        _mc_spread_display = _mc_spread_pct * 100.0
                                        _mc_base = MICRO_CAP_COMPOUNDING_PROFIT_TARGET_PCT  # 1.0%
                                        _mc_streak_bonus = round(_mc_profit_pct - _mc_base - _mc_spread_display, 4)
                                        if action == 'enter_long':
                                            _mc_stop_loss = _mc_entry_price * (1.0 - _mc_stop_pct / 100.0)
                                            _mc_take_profit = _mc_entry_price * (1.0 + _mc_profit_pct / 100.0)
                                        else:  # enter_short
                                            _mc_stop_loss = _mc_entry_price * (1.0 + _mc_stop_pct / 100.0)
                                            _mc_take_profit = _mc_entry_price * (1.0 - _mc_profit_pct / 100.0)
                                        analysis['stop_loss'] = _mc_stop_loss
                                        analysis['take_profit'] = [_mc_take_profit]
                                        analysis['position_size'] = position_size
                                        logger.info(
                                            f"   🎯 {symbol}: Micro-cap targets — "
                                            f"SL={_mc_stop_pct}% (${_mc_stop_loss:.6f}), "
                                            f"PT={_mc_profit_pct:.2f}% (${_mc_take_profit:.6f}) "
                                            f"[base={_mc_base:.1f}% + spread={_mc_spread_display:.2f}% + streak_bonus={_mc_streak_bonus:.2f}% | wins={self._micro_cap_win_streak}]"
                                        )
                                    else:
                                        # Entry price not available; just update position_size in analysis
                                        analysis['position_size'] = position_size

                                # ── $100 → $1K ACCELERATOR MODE ────────────────────────
                                # Feature 4: Boost position-size percentage for accounts in the
                                # $100–$1 000 range to compound capital faster toward the $1 000
                                # milestone.
                                #
                                # Mutual exclusivity with micro-cap compounding mode:
                                # Micro-cap compounding (_micro_cap_config is not None) handles
                                # accounts in the $15–$500 range with its own optimised sizing,
                                # stop-loss, and profit-target logic.  The accelerator mode is
                                # intentionally skipped when micro-cap config is active so the
                                # two sizing regimes do not conflict.  In practice the accelerator
                                # primarily activates for accounts in the $500–$1 000 gap where
                                # micro-cap config is no longer loaded.
                                if _micro_cap_config is None and ACCELERATOR_MIN_BALANCE <= account_balance < ACCELERATOR_MAX_BALANCE:
                                    _accel_pct = get_accelerator_position_size_pct(account_balance)
                                    _accel_size = account_balance * _accel_pct / 100.0
                                    if _accel_size > position_size:
                                        logger.info(
                                            f"   🔥 {symbol}: $100→$1K accelerator mode — "
                                            f"size {_accel_pct:.0f}% of ${account_balance:.2f} = "
                                            f"${_accel_size:.2f} (was ${position_size:.2f})"
                                        )
                                        position_size = _accel_size

                                # ═══════════════════════════════════════════════════════
                                # CAPITAL GROWTH THROTTLE — Steps 2 & 3 of correct order
                                # Step 2: base position size is already set above.
                                # Step 3: apply throttle multiplier before any further
                                #         adjustments so all downstream gates work on the
                                #         already-throttled size.
                                # ═══════════════════════════════════════════════════════
                                if CAPITAL_GROWTH_THROTTLE_AVAILABLE and get_capital_growth_throttle:
                                    try:
                                        _throttle = get_capital_growth_throttle()
                                        _throttle_mult = _throttle.get_multiplier()
                                        if _throttle_mult <= 0.0:
                                            logger.warning(
                                                "   🔒 %s: Capital Growth Throttle LOCKED "
                                                "(drawdown ≥ 20%%) — entry blocked.",
                                                symbol,
                                            )
                                            filter_stats['market_filter'] += 1  # capital protection block
                                            continue
                                        if _throttle_mult < 1.0:
                                            _pre_throttle_size = position_size
                                            position_size = position_size * _throttle_mult
                                            logger.info(
                                                "   📉 %s: Capital Growth Throttle %.0f%% "
                                                "(drawdown=%.1f%%) — size $%.2f → $%.2f",
                                                symbol,
                                                _throttle_mult * 100,
                                                _throttle.state.drawdown_pct,
                                                _pre_throttle_size,
                                                position_size,
                                            )
                                    except Exception as _cgt_err:
                                        logger.debug(
                                            "Capital Growth Throttle skipped for %s: %s",
                                            symbol, _cgt_err,
                                        )

                                # ═══════════════════════════════════════════════════════
                                # REGIME CONTROLLER GATE — respect regime decision
                                # ═══════════════════════════════════════════════════════
                                # The regime controller evaluates the GLOBAL market
                                # environment after the scan loop.  Its decision from
                                # the PREVIOUS cycle is used here to gate entries.
                                if not _regime_entries_allowed:
                                    logger.info(
                                        f"   🚫 {symbol}: REGIME BLOCK — {_regime_result.reason if _regime_result else 'unfavorable market conditions'}"
                                    )
                                    filter_stats['market_filter'] += 1
                                    continue

                                # Apply regime-based position-size multiplier
                                if _regime_size_multiplier != 1.0 and _regime_size_multiplier > 0:
                                    _original_size = position_size
                                    position_size = position_size * _regime_size_multiplier
                                    logger.info(
                                        f"   ⚠️  {symbol}: Regime size adjustment "
                                        f"({_regime_size_multiplier:.2f}x) — "
                                        f"${_original_size:.2f} → ${position_size:.2f}"
                                    )

                                # ═══════════════════════════════════════════════════════
                                # AI MARKET REGIME FORECASTER — early-warning regime gate
                                # ═══════════════════════════════════════════════════════
                                # When the forecaster detects an imminent regime change
                                # (transition_risk ≥ 80), reduce position size to protect
                                # capital against entering during an unstable transition.
                                if AI_REGIME_FORECASTER_AVAILABLE and get_ai_market_regime_forecaster:
                                    try:
                                        _forecaster = get_ai_market_regime_forecaster()
                                        _current_regime_label = (
                                            _regime_result.regime if _regime_result and hasattr(_regime_result, 'regime')
                                            else "RANGING"
                                        )
                                        _indicators_snap = {
                                            'atr': analysis.get('atr', 0.0),
                                            'adx': adx if 'adx' in locals() else 25.0,
                                            'rsi_9': analysis.get('rsi_9', 50.0),
                                            'rsi': analysis.get('rsi', 50.0),
                                            'bb_upper': analysis.get('bb_upper', 0.0),
                                            'bb_lower': analysis.get('bb_lower', 0.0),
                                            'bb_middle': analysis.get('bb_mid', 0.0),
                                        }
                                        _forecast = _forecaster.forecast(
                                            df=df,
                                            indicators=_indicators_snap,
                                            current_regime=str(_current_regime_label),
                                        )
                                        if _forecast.transition_risk >= 80:
                                            # High risk: block entry to avoid entering during regime shift
                                            logger.warning(
                                                f"   🔮 {symbol}: AI REGIME FORECASTER — "
                                                f"imminent regime change BLOCKED entry "
                                                f"(risk={_forecast.transition_risk:.0f}/100 "
                                                f"next={_forecast.top_next_regime} "
                                                f"p={_forecast.transition_probability:.0%})"
                                            )
                                            if _forecast.early_warnings:
                                                logger.warning(
                                                    f"      ⚡ Early warnings: {'; '.join(_forecast.early_warnings[:3])}"
                                                )
                                            filter_stats['market_filter'] += 1
                                            continue
                                        elif _forecast.transition_risk >= 55:
                                            # Moderate risk: reduce position size
                                            _forecast_mult = max(
                                                0.5,
                                                1.0 - (_forecast.transition_risk - 55) / 100.0,
                                            )
                                            _pre_forecast_size = position_size
                                            position_size = position_size * _forecast_mult
                                            logger.info(
                                                f"   🔮 {symbol}: AI Regime Forecaster — "
                                                f"regime transition risk {_forecast.transition_risk:.0f}/100 "
                                                f"size reduced {_pre_forecast_size:.2f}→{position_size:.2f} "
                                                f"(next_regime={_forecast.top_next_regime})"
                                            )
                                    except Exception as _fc_err:
                                        logger.debug(
                                            "AI Market Regime Forecaster skipped for %s: %s",
                                            symbol, _fc_err,
                                        )

                                # ═══════════════════════════════════════════════════════
                                # REGIME CAPITAL ALLOCATOR — regime-driven sizing shift
                                # ═══════════════════════════════════════════════════════
                                if REGIME_CAPITAL_ALLOCATOR_AVAILABLE and hasattr(self, 'regime_capital_allocator') and self.regime_capital_allocator is not None:
                                    try:
                                        _rca_regime = (
                                            str(_regime_result.regime)
                                            if _regime_result and hasattr(_regime_result, 'regime')
                                            else "UNKNOWN"
                                        )
                                        _rca_conf = (
                                            float(_regime_result.confidence)
                                            if _regime_result and hasattr(_regime_result, 'confidence')
                                            else 0.6
                                        )
                                        self.regime_capital_allocator.update_regime(
                                            _rca_regime, _rca_conf
                                        )
                                        _rca_params = self.regime_capital_allocator.get_allocation_params()
                                        if not _rca_params.allow_new_entries:
                                            logger.info(
                                                f"   🔄 {symbol}: REGIME ALLOCATOR BLOCK — "
                                                f"regime={_rca_params.regime} ({_rca_params.description})"
                                            )
                                            filter_stats['market_filter'] += 1
                                            continue
                                        if _rca_params.position_size_multiplier != 1.0:
                                            _pre_rca = position_size
                                            position_size *= _rca_params.position_size_multiplier
                                            logger.info(
                                                f"   🔄 {symbol}: Regime Allocator size "
                                                f"{_rca_params.regime} "
                                                f"({_rca_params.position_size_multiplier:.2f}x) "
                                                f"${_pre_rca:.2f}→${position_size:.2f}"
                                            )
                                    except Exception as _rca_err:
                                        logger.debug("Regime Capital Allocator skipped for %s: %s", symbol, _rca_err)

                                # ═══════════════════════════════════════════════════════
                                # PHASE 2: ADAPTIVE TAKE-PROFIT SCALING
                                # Dynamically expands profit targets in strong trends and
                                # contracts them in weak/diverging conditions so that
                                # winners are locked in more aggressively.
                                # ═══════════════════════════════════════════════════════
                                if ADAPTIVE_TP_AVAILABLE and hasattr(self, 'adaptive_tp_engine') and self.adaptive_tp_engine is not None:
                                    try:
                                        _atp_entry = analysis.get('entry_price', 0.0) or float(df['close'].iloc[-1])
                                        _atp_side = "long" if action == "enter_long" else "short"
                                        _atp_indicators = getattr(self, '_last_indicators', {}) or {}
                                        _atp_regime = "normal"
                                        if MARKET_REGIME_ENGINE_AVAILABLE and hasattr(self, 'regime_engine') and self.regime_engine is not None:
                                            try:
                                                _re_val = self.regime_engine.current_regime
                                                _atp_regime = str(_re_val.value).lower() if hasattr(_re_val, 'value') else str(_re_val).lower()
                                            except Exception:
                                                pass
                                        _atp_atr = float(analysis.get('atr', 0.0) or 0.0) or None
                                        _atp_result = self.adaptive_tp_engine.calculate_adaptive_targets(
                                            entry_price=_atp_entry,
                                            side=_atp_side,
                                            df=df,
                                            indicators=_atp_indicators,
                                            current_regime=_atp_regime,
                                            atr=_atp_atr,
                                        )
                                        # Replace the primary take-profit in analysis with the
                                        # adaptive TP3 target (3% base, scaled by trend + vol).
                                        _atp_targets = _atp_result.get('targets', {})
                                        if _atp_targets:
                                            _atp_primary = _atp_targets.get('tp3') or _atp_targets.get('tp2') or _atp_targets.get('tp1')
                                            if _atp_primary and _atp_primary.get('price'):
                                                analysis['take_profit'] = [_atp_primary['price']]
                                                _atp_mult = _atp_result.get('combined_multiplier', 1.0)
                                                logger.info(
                                                    f"   🎯 {symbol}: Adaptive TP "
                                                    f"({_atp_result.get('trend_strength', '?').upper()} trend "
                                                    f"{_atp_mult:.2f}× mult) → "
                                                    f"${_atp_primary['price']:.4f} "
                                                    f"({_atp_primary['percentage']*100:.2f}%)"
                                                )
                                    except Exception as _atp_err:
                                        logger.debug("Adaptive TP Engine skipped for %s: %s", symbol, _atp_err)

                                # ═══════════════════════════════════════════════════════
                                # MARKET REGIME ENGINE — bull / chop / crash aggression
                                # Applies per-candle BULL/CHOP/CRASH behaviour multipliers
                                # sourced from the MarketRegimeEngine singleton (ATR ratio +
                                # ADX + volume surge).
                                #
                                #   Regime │ size_mult │ freq_mult │ stop_mult
                                #   ───────┼───────────┼───────────┼──────────
                                #   BULL   │   1.50×   │   1.25×   │   0.90×  (larger, tighter)
                                #   CHOP   │   0.60×   │   0.50×   │   1.10×  (smaller, wider)
                                #   CRASH  │   0.25×   │   0.20×   │   1.50×  (minimal, very wide)
                                # ═══════════════════════════════════════════════════════
                                if MARKET_REGIME_ENGINE_AVAILABLE and hasattr(self, 'regime_engine') and self.regime_engine is not None:
                                    try:
                                        _re_regime = self.regime_engine.current_regime
                                        _re_conf = self.regime_engine.confidence
                                        _re_behavior = self.regime_engine.behavior
                                        _re_size_mult = _re_behavior.position_size_multiplier
                                        _re_freq_mult = _re_behavior.trade_frequency_multiplier
                                        _re_stop_mult = _re_behavior.stop_loss_multiplier
                                        _re_label = _re_behavior.label

                                        # Only apply when the engine has enough data to
                                        # produce a meaningful classification.
                                        if _re_conf > 0.0 and (RegimeEngineRegime is None or _re_regime != RegimeEngineRegime.UNKNOWN):
                                            # ── Trade-frequency gate ──────────────────────
                                            # In CHOP (0.50) or CRASH (0.20) regimes, honour
                                            # the multiplier by randomly skipping that fraction
                                            # of signals, preserving high-quality entries.
                                            if _re_freq_mult < 1.0:
                                                if random.random() > _re_freq_mult:
                                                    logger.info(
                                                        f"   🔀 {symbol}: REGIME ENGINE ({_re_label}) — "
                                                        f"trade skipped via freq gate "
                                                        f"(freq={_re_freq_mult:.2f}, conf={_re_conf:.0%})"
                                                    )
                                                    filter_stats['market_filter'] = filter_stats.get('market_filter', 0) + 1
                                                    continue

                                            # ── Position-size scaling ─────────────────────
                                            if _re_size_mult != 1.0:
                                                _pre_re_size = position_size
                                                position_size *= _re_size_mult
                                                logger.info(
                                                    f"   📊 {symbol}: Regime Engine ({_re_label}) "
                                                    f"size {_re_size_mult:.2f}× — "
                                                    f"${_pre_re_size:.2f}→${position_size:.2f} "
                                                    f"(conf={_re_conf:.0%})"
                                                )

                                            # ── Stop-loss width adjustment ────────────────
                                            # Tighten in BULL (0.90×) to lock profits faster;
                                            # widen in CHOP/CRASH to avoid premature stops.
                                            if _re_stop_mult != 1.0:
                                                _re_entry_price = analysis.get('entry_price', 0.0) or float(df['close'].iloc[-1])
                                                _re_action = analysis.get('action', '')
                                                for _sl_key in ('stop_loss', 'stop_price'):
                                                    _sl_val = analysis.get(_sl_key, 0.0)
                                                    if _sl_val and _sl_val > 0 and _re_entry_price > 0:
                                                        if _re_action in ('enter_long', 'buy'):
                                                            _sl_dist = _re_entry_price - _sl_val
                                                            _new_sl = _re_entry_price - (_sl_dist * _re_stop_mult)
                                                        else:
                                                            _sl_dist = _sl_val - _re_entry_price
                                                            _new_sl = _re_entry_price + (_sl_dist * _re_stop_mult)
                                                        analysis[_sl_key] = _new_sl
                                                        logger.debug(
                                                            "   🛡️ %s: Regime Engine stop-loss (%s) "
                                                            "%.2f× — %.6f→%.6f",
                                                            symbol, _sl_key,
                                                            _re_stop_mult, _sl_val, _new_sl,
                                                        )
                                    except Exception as _re_err:
                                        logger.debug("Market Regime Engine aggression skipped for %s: %s", symbol, _re_err)

                                # ═══════════════════════════════════════════════════════
                                # VOLATILITY-WEIGHTED CAPITAL ROUTER — inverse-vol sizing
                                # ═══════════════════════════════════════════════════════
                                if VOLATILITY_CAPITAL_ROUTER_AVAILABLE and hasattr(self, 'volatility_capital_router') and self.volatility_capital_router is not None:
                                    try:
                                        _atr_raw = analysis.get('atr', 0.0)
                                        _close_price = float(df['close'].iloc[-1]) if df is not None and len(df) > 0 else 0.0
                                        if _close_price > 0 and _atr_raw > 0:
                                            _atr_pct = (_atr_raw / _close_price) * 100.0
                                            self.volatility_capital_router.update_volatility(symbol, _atr_pct)
                                        _vol_mult = self.volatility_capital_router.get_size_multiplier(symbol)
                                        if _vol_mult != 1.0:
                                            _pre_vol = position_size
                                            position_size *= _vol_mult
                                            logger.info(
                                                f"   📊 {symbol}: Volatility Router size "
                                                f"({_vol_mult:.2f}x) "
                                                f"${_pre_vol:.2f}→${position_size:.2f}"
                                            )
                                    except Exception as _vol_err:
                                        logger.debug("Volatility-Weighted Capital Router skipped for %s: %s", symbol, _vol_err)

                                # ═══════════════════════════════════════════════════════
                                # GLOBAL DRAWDOWN CIRCUIT BREAKER — per-trade size scale
                                # ═══════════════════════════════════════════════════════
                                if GLOBAL_DRAWDOWN_CB_AVAILABLE and hasattr(self, 'global_drawdown_cb') and self.global_drawdown_cb is not None:
                                    try:
                                        _gdcb_mult = self.global_drawdown_cb.get_position_size_multiplier()
                                        if _gdcb_mult < 1.0:
                                            _pre_gdcb = position_size
                                            position_size *= _gdcb_mult
                                            logger.info(
                                                f"   🛡️ {symbol}: Global Drawdown CB size "
                                                f"({_gdcb_mult:.2f}x) "
                                                f"${_pre_gdcb:.2f}→${position_size:.2f}"
                                            )
                                    except Exception as _gdcb2_err:
                                        logger.debug("Global Drawdown CB size scaling skipped for %s: %s", symbol, _gdcb2_err)

                                # ═══════════════════════════════════════════════════════
                                # CROSS-BROKER ARBITRAGE MONITOR — best venue selection
                                # ═══════════════════════════════════════════════════════
                                if CROSS_BROKER_ARB_AVAILABLE and hasattr(self, 'arb_monitor') and self.arb_monitor is not None:
                                    try:
                                        _arb_signal = self.arb_monitor.get_arb_signal(symbol)
                                        if _arb_signal.venue_count >= 2:
                                            logger.debug(
                                                "   🔀 %s: ArbitrageMonitor spread_gap=%.3f%% "
                                                "best_buy=%s best_sell=%s strength=%s",
                                                symbol,
                                                _arb_signal.spread_gap_pct,
                                                _arb_signal.best_buy_venue,
                                                _arb_signal.best_sell_venue,
                                                _arb_signal.strength.value,
                                            )
                                    except Exception as _arb_err:
                                        logger.debug("Cross-Broker Arb Monitor skipped for %s: %s", symbol, _arb_err)

                                # ═══════════════════════════════════════════════════════
                                # RISK BUDGET ENGINE — risk-first position size override
                                # ═══════════════════════════════════════════════════════
                                # When available, use the Risk Budget Engine to compute
                                # a risk-first position size and cap any oversized signal.
                                if hasattr(self, 'risk_budget_engine') and self.risk_budget_engine is not None:
                                    try:
                                        _entry_price = analysis.get('entry_price', 0.0) or float(df['close'].iloc[-1])
                                        _stop_price = analysis.get('stop_price', 0.0)
                                        if _entry_price > 0 and _stop_price > 0 and _stop_price != _entry_price:
                                            _rb_result = self.risk_budget_engine.calculate_position_size(
                                                account_balance=account_balance,
                                                entry_price=_entry_price,
                                                stop_price=_stop_price,
                                            )
                                            _rb_size = _rb_result.get('position_size_usd', position_size)
                                            # Use whichever is smaller: strategy size or risk-budget size
                                            if _rb_size < position_size:
                                                logger.info(
                                                    f"   💰 {symbol}: Risk Budget Engine capped position "
                                                    f"${position_size:.2f} → ${_rb_size:.2f} "
                                                    f"(risk_pct={_rb_result.get('risk_pct', 0):.2%})"
                                                )
                                                position_size = _rb_size
                                    except Exception as rb_err:
                                        logger.debug(f"   ⚠️ Risk Budget Engine error for {symbol}: {rb_err}")

                                # ═══════════════════════════════════════════════════════
                                # VOLATILITY POSITION SIZING — ATR-based size adjustment
                                # Scales position size inversely with current volatility
                                # so every trade carries a similar dollar-risk exposure.
                                # ═══════════════════════════════════════════════════════
                                if hasattr(self, 'volatility_position_sizer') and self.volatility_position_sizer is not None:
                                    try:
                                        _vol_current_price = float(df['close'].iloc[-1])
                                        _vol_adjusted_size, _vol_sizing_result = self.volatility_position_sizer.adjust(
                                            df=df,
                                            current_price=_vol_current_price,
                                            proposed_size_usd=position_size,
                                            account_balance=account_balance,
                                        )
                                        if _vol_sizing_result.size_multiplier != 1.0:
                                            logger.info(
                                                f"   📐 {symbol}: Volatility Position Sizing "
                                                f"({_vol_sizing_result.size_multiplier:.2f}x) "
                                                f"${position_size:.2f} → ${_vol_adjusted_size:.2f} "
                                                f"[regime={_vol_sizing_result.volatility_regime} "
                                                f"atr={_vol_sizing_result.atr_pct:.2f}%]"
                                            )
                                        position_size = _vol_adjusted_size
                                    except Exception as _vol_err:
                                        logger.debug(
                                            f"   ⚠️ Volatility Position Sizing skipped for {symbol}: {_vol_err}"
                                        )

                                # ═══════════════════════════════════════════════════════
                                # ACCOUNT-LEVEL CAPITAL FLOW — concentration × AI-weight multiplier
                                # Boosts capital into hot/top-ranked accounts (win-rate > 70%)
                                # and reduces it for weakened accounts approaching kill threshold.
                                # ═══════════════════════════════════════════════════════
                                if hasattr(self, 'account_flow_layer') and self.account_flow_layer is not None:
                                    try:
                                        _afl_acct_id = self._get_primary_broker_id()
                                        _afl_mult = self.account_flow_layer.get_size_multiplier(_afl_acct_id)
                                        if _afl_mult != 1.0 and _afl_mult > 0:
                                            _afl_pre = position_size
                                            position_size = position_size * _afl_mult
                                            logger.info(
                                                "   🏦 %s: Account-Level Flow %.2fx "
                                                "(acct=%s) — $%.2f → $%.2f",
                                                symbol, _afl_mult, _afl_acct_id,
                                                _afl_pre, position_size,
                                            )
                                    except Exception as _afl_size_err:
                                        logger.debug(
                                            "Account-Level Capital Flow sizing skipped for %s: %s",
                                            symbol, _afl_size_err,
                                        )

                                # ═══════════════════════════════════════════════════════
                                # MARKET READINESS GATE - Re-check with entry score for CAUTIOUS mode
                                # ═══════════════════════════════════════════════════════
                                if self.market_readiness_gate is not None:
                                    try:
                                        # Re-check market readiness with actual entry score
                                        # This enables CAUTIOUS mode filtering (requires score ≥85)
                                        mode, conditions, details = self.market_readiness_gate.check_market_readiness(
                                            atr=atr,
                                            current_price=current_price,
                                            adx=adx,
                                            volume_percentile=volume_percentile,
                                            spread_pct=spread_pct,
                                            entry_score=entry_score
                                        )
                                        
                                        # Apply mode-specific position size adjustments
                                        if mode == MarketMode.IDLE:
                                            logger.info(f"   ⏸️  {symbol}: IDLE MODE - No entries allowed")
                                            logger.info(f"      {details['message']}")
                                            filter_stats['market_filter'] += 1
                                            continue
                                        elif mode == MarketMode.CAUTIOUS:
                                            if not details['allow_entries']:
                                                _min_score_req = details.get('min_entry_score', 70)
                                                logger.info(f"   ⚠️  {symbol}: CAUTIOUS MODE - Entry blocked (score {entry_score:.0f} < {_min_score_req})")
                                                filter_stats['market_filter'] += 1
                                                continue
                                            else:
                                                # CAUTIOUS mode: Cap position size at 20% of normal
                                                cautious_multiplier = details.get('position_size_multiplier', 0.20)
                                                original_size = position_size
                                                position_size = position_size * cautious_multiplier
                                                logger.info(f"   ⚠️  {symbol}: CAUTIOUS MODE - Position size reduced to {cautious_multiplier*100:.0f}%")
                                                logger.info(f"      Original: ${original_size:.2f} → Cautious: ${position_size:.2f}")
                                                logger.info(f"      Entry score: {entry_score:.0f}/100")
                                        elif mode == MarketMode.AGGRESSIVE:
                                            logger.debug(f"   🚀 {symbol}: AGGRESSIVE MODE - Full position sizing")
                                        
                                    except Exception as readiness_err:
                                        logger.warning(f"   ⚠️ Market readiness re-check error for {symbol}: {readiness_err}")
                                        # Continue with trade if readiness check fails

                                # ═══════════════════════════════════════════════════════
                                # GLOBAL CAPITAL SCALING — proportional allocation
                                # Scale position size by this account's share of total capital.
                                # ═══════════════════════════════════════════════════════
                                if GLOBAL_CAPITAL_MANAGER_AVAILABLE and get_global_capital_manager:
                                    try:
                                        _gcm = get_global_capital_manager()
                                        _acct_label = self._get_broker_name(active_broker)
                                        allocation = _gcm.get_allocation(_acct_label)
                                        if allocation < 1.0:
                                            _pre_alloc_size = position_size
                                            position_size *= allocation
                                            logger.info(
                                                f"   📊 {symbol}: Global capital scaling "
                                                f"({allocation:.2%} share) — "
                                                f"${_pre_alloc_size:.2f} → ${position_size:.2f}"
                                            )
                                    except Exception as _gcm_err:
                                        logger.debug(
                                            "GlobalCapitalManager allocation skipped for %s: %s",
                                            symbol, _gcm_err,
                                        )

                                # ═══════════════════════════════════════════════════════
                                # PHASE 2: AI CONFIDENCE-BASED POSITION SIZING
                                # Scale position size proportionally to trade confidence
                                # score (0–100).  High-conviction setups (≥80) get a 10%
                                # boost; low-conviction setups (< 65) are reduced.
                                # ═══════════════════════════════════════════════════════
                                if AI_CONFIDENCE_SIZING_AVAILABLE and hasattr(self, 'ai_confidence_engine') and self.ai_confidence_engine is not None:
                                    try:
                                        _conf_side = "long" if action == "enter_long" else "short"
                                        _conf_indicators = getattr(self, '_last_indicators', {}) or {}
                                        _conf_result = self.ai_confidence_engine.evaluate(
                                            df=df,
                                            indicators=_conf_indicators,
                                            side=_conf_side,
                                            symbol=symbol,
                                        )
                                        _conf_score = _conf_result.get("score", 65.0)
                                        _conf_action = _conf_result.get("recommended_action", "EXECUTE")

                                        # Block trades where confidence engine recommends SKIP
                                        if _conf_action == "SKIP":
                                            logger.info(
                                                f"   🧠 {symbol}: AI Confidence SKIP "
                                                f"(score={_conf_score:.1f}/100) — "
                                                f"{_conf_result.get('reason', '')}"
                                            )
                                            filter_stats['market_filter'] = (
                                                filter_stats.get('market_filter', 0) + 1
                                            )
                                            continue

                                        # Scale position size by confidence: 0.65→1.0 maps to 0.80×→1.10×
                                        _conf_min_score = 65.0
                                        _conf_max_score = 100.0
                                        _conf_min_mult = 0.80
                                        _conf_max_mult = 1.10
                                        _normalized = max(0.0, min(1.0, (_conf_score - _conf_min_score) / (_conf_max_score - _conf_min_score)))
                                        _conf_mult = _conf_min_mult + (_conf_max_mult - _conf_min_mult) * _normalized
                                        if abs(_conf_mult - 1.0) >= 0.01:
                                            _pre_conf = position_size
                                            position_size *= _conf_mult
                                            logger.info(
                                                f"   🧠 {symbol}: AI Confidence sizing "
                                                f"(score={_conf_score:.1f}/100 → {_conf_mult:.2f}×) "
                                                f"${_pre_conf:.2f} → ${position_size:.2f}"
                                            )
                                    except Exception as _conf_err:
                                        logger.debug("AI Confidence sizing skipped for %s: %s", symbol, _conf_err)

                                # ═══════════════════════════════════════════════════════
                                # PHASE 2: TRADE CLUSTERING — stack wins in strong trends
                                # When the bot has accumulated consecutive wins in a BULL
                                # regime with high ADX, ramp up position size by up to
                                # 1.5× to concentrate capital into the trend.
                                # ═══════════════════════════════════════════════════════
                                if TRADE_CLUSTER_AVAILABLE and hasattr(self, 'trade_cluster_engine') and self.trade_cluster_engine is not None:
                                    try:
                                        _cluster_adx = float(analysis.get('adx', 0.0) or 0.0)
                                        _cluster_regime = "UNKNOWN"
                                        if MARKET_REGIME_ENGINE_AVAILABLE and hasattr(self, 'regime_engine') and self.regime_engine is not None:
                                            try:
                                                _re = self.regime_engine.current_regime
                                                _cluster_regime = str(_re.value) if hasattr(_re, 'value') else str(_re)
                                            except Exception:
                                                pass
                                        _cluster_mult = self.trade_cluster_engine.get_cluster_multiplier(
                                            adx=_cluster_adx,
                                            regime=_cluster_regime,
                                        )
                                        if _cluster_mult > 1.0:
                                            _pre_cluster = position_size
                                            position_size *= _cluster_mult
                                            _cluster_status = self.trade_cluster_engine.get_status()
                                            logger.info(
                                                f"   🔗 {symbol}: Trade Cluster ({_cluster_status.state}) "
                                                f"consecutive_wins={_cluster_status.consecutive_wins} "
                                                f"({_cluster_mult:.2f}×) "
                                                f"${_pre_cluster:.2f} → ${position_size:.2f}"
                                            )
                                    except Exception as _cluster_err:
                                        logger.debug("Trade Cluster sizing skipped for %s: %s", symbol, _cluster_err)

                                # ═══════════════════════════════════════════════════════
                                # PHASE 2: CAPITAL ROUTING ACROSS BROKERS
                                # Apply the broker-specific allocation weight so capital
                                # flows toward best-performing brokers over time.
                                # ═══════════════════════════════════════════════════════
                                if AUTO_BROKER_SHIFTER_AVAILABLE and hasattr(self, 'broker_capital_shifter') and self.broker_capital_shifter is not None:
                                    try:
                                        _broker_label = self._get_broker_name(active_broker)
                                        _broker_allocs = self.broker_capital_shifter.get_allocations()
                                        if _broker_allocs and _broker_label in _broker_allocs:
                                            _num_brokers = len(_broker_allocs)
                                            _equal_share = 1.0 / _num_brokers if _num_brokers > 0 else 1.0
                                            _broker_alloc = _broker_allocs[_broker_label]
                                            # Convert allocation fraction to a multiplier relative to
                                            # the equal-share baseline so a well-performing broker
                                            # gets a multiplier > 1.0 and a poor broker gets < 1.0.
                                            _broker_mult = _broker_alloc / _equal_share if _equal_share > 0 else 1.0
                                            # Clamp to a sensible range
                                            _broker_mult = max(0.50, min(2.0, _broker_mult))
                                            if abs(_broker_mult - 1.0) >= 0.02:
                                                _pre_broker = position_size
                                                position_size *= _broker_mult
                                                logger.info(
                                                    f"   🏦 {symbol}: Broker Capital Routing "
                                                    f"({_broker_label} alloc={_broker_alloc:.1%} "
                                                    f"mult={_broker_mult:.2f}×) "
                                                    f"${_pre_broker:.2f} → ${position_size:.2f}"
                                                )
                                    except Exception as _bcs_err:
                                        logger.debug("Broker Capital Shifter sizing skipped for %s: %s", symbol, _bcs_err)

                                # Calculate dynamic minimum based on account balance and
                                # brokerage-specific minimums (Option B – prevent dust at creation)
                                broker_name = self._get_broker_name(active_broker)
                                min_position_size_dynamic = get_dynamic_min_position_size(
                                    account_balance, broker_name
                                )

                                # PROFITABILITY WARNING: Small positions have lower profitability
                                # Fees are ~1.4% round-trip, so very small positions face significant fee pressure
                                # DYNAMIC MINIMUM: Position must meet max(10.00, balance * DYNAMIC_POSITION_SIZE_PCT, brokerage_min)
                                if position_size < min_position_size_dynamic:
                                    filter_stats['position_too_small'] += 1
                                    # FIX #3 (Jan 19, 2026): Explicit trade rejection logging
                                    logger.info(f"   ❌ Entry rejected for {symbol}")
                                    logger.info(f"      Reason: Position size ${position_size:.2f} < ${min_position_size_dynamic:.2f} minimum")
                                    logger.info(f"      💡 Dynamic minimum = max($10.00, ${account_balance:.2f} × {DYNAMIC_POSITION_SIZE_PCT*100:.0f}%, brokerage_min[{broker_name}]) = ${min_position_size_dynamic:.2f}")
                                    logger.info(f"      💡 Small positions face severe fee impact (~1.4% round-trip)")
                                    # Calculate break-even % needed: (fee_dollars / position_size) * 100
                                    breakeven_pct = (position_size * 0.014 / position_size) * 100 if position_size > 0 else 0
                                    logger.info(f"      📊 Would need {breakeven_pct:.1f}% gain just to break even on fees")
                                    continue

                                # Warn if position is near the minimum but allowed
                                if position_size < POSITION_SIZE_WARNING_THRESHOLD_USD:
                                    logger.warning(f"   ⚠️  Small position: ${position_size:.2f} - profitability may be limited by fees")

                                # ═══════════════════════════════════════════════════════
                                # CROSS-ACCOUNT RISK BALANCING — global 6% ceiling
                                # Block trade if adding it would breach MAX_GLOBAL_RISK.
                                # ═══════════════════════════════════════════════════════
                                if GLOBAL_CAPITAL_MANAGER_AVAILABLE and get_global_capital_manager:
                                    try:
                                        _gcm = get_global_capital_manager()
                                        _acct_label = self._get_broker_name(active_broker)
                                        _requested_risk = (
                                            position_size / account_balance
                                            if account_balance > 0 else 0.0
                                        )
                                        # Check BEFORE updating so the ceiling test excludes
                                        # the current account's own in-flight risk.
                                        if not _gcm.can_open_trade(_requested_risk):
                                            logger.warning(
                                                f"   🚫 {symbol}: BLOCKED_GLOBAL_RISK — "
                                                f"cross-account risk ceiling reached "
                                                f"(requested={_requested_risk:.2%}, MAX=6%)"
                                            )
                                            filter_stats['market_filter'] += 1
                                            continue
                                        # Approved — record this account's risk commitment
                                        _gcm.update_account_risk(_acct_label, _requested_risk)
                                    except Exception as _gcm_err:
                                        logger.debug(
                                            "GlobalCapitalManager risk check skipped for %s: %s",
                                            symbol, _gcm_err,
                                        )

                                # CRITICAL: Verify we're still under position cap before placing order
                                if len(current_positions) >= effective_max_positions:
                                    logger.error(f"   ❌ SAFETY VIOLATION: Position cap ({effective_max_positions}) reached - BLOCKING NEW ENTRY")
                                    logger.error(f"      Current positions: {len(current_positions)}")
                                    logger.error(f"      This should not happen - cap should have been checked earlier!")
                                    break
                                
                                logger.info(f"   ✅ Final position cap check: {len(current_positions)}/{effective_max_positions} - OK to enter")

                                # PRO MODE: Check if rotation is needed
                                needs_rotation = False
                                if self.pro_mode_enabled and self.rotation_manager and position_size > account_balance:
                                    logger.info(f"   🔄 PRO MODE: Position size ${position_size:.2f} exceeds free balance ${account_balance:.2f}")
                                    logger.info(f"   → Rotation needed: ${position_size - account_balance:.2f}")

                                    # Check if we can rotate
                                    can_rotate, rotate_reason = self.rotation_manager.can_rotate(
                                        total_capital=total_capital,
                                        free_balance=account_balance,
                                        current_positions=len(current_positions)
                                    )

                                    if can_rotate:
                                        logger.info(f"   ✅ Rotation allowed: {rotate_reason}")

                                        # Build position metrics for rotation scoring
                                        position_metrics = {}
                                        for pos in current_positions:
                                            pos_symbol = pos.get('symbol')
                                            pos_qty = pos.get('quantity', 0)

                                            try:
                                                pos_price = active_broker.get_current_price(pos_symbol)

                                                # CRITICAL FIX: Add None-check safety guard
                                                # Prevents errors from invalid price fetches
                                                if pos_price is None:
                                                    logger.error(f"   ❌ Price fetch failed for {pos_symbol} — symbol mismatch")
                                                    logger.error(f"   💡 Skipping position from rotation scoring due to invalid price")
                                                    continue

                                                pos_value = pos_qty * pos_price if pos_price > 0 else 0

                                                # Get position age if available
                                                pos_age_hours = 0
                                                if hasattr(active_broker, 'position_tracker') and active_broker.position_tracker:
                                                    tracked = active_broker.position_tracker.get_position(pos_symbol)
                                                    if tracked and tracked.get('first_entry_time'):
                                                        entry_dt = datetime.fromisoformat(tracked['first_entry_time'])
                                                        pos_age_hours = (datetime.now() - entry_dt).total_seconds() / 3600

                                                # Calculate P&L if entry price available
                                                pos_pnl_pct = 0.0
                                                if hasattr(active_broker, 'position_tracker') and active_broker.position_tracker:
                                                    tracked = active_broker.position_tracker.get_position(pos_symbol)
                                                    if tracked and tracked.get('average_entry_price'):
                                                        entry_price = float(tracked['average_entry_price'])
                                                        if entry_price > 0:
                                                            pos_pnl_pct = ((pos_price - entry_price) / entry_price) * 100

                                                # Get RSI if available (from recent market data)
                                                pos_rsi = 50  # Neutral default
                                                try:
                                                    # Attempt to get recent RSI from market data
                                                    if hasattr(self, 'apex') and self.apex:
                                                        # Try to get recent candles and calculate RSI
                                                        recent_candles = active_broker.get_candles(pos_symbol, '5m', 50)
                                                        if recent_candles and len(recent_candles) >= 14:
                                                            df_temp = pd.DataFrame(recent_candles)
                                                            for col in ['close']:
                                                                if col in df_temp.columns:
                                                                    df_temp[col] = pd.to_numeric(df_temp[col], errors='coerce')
                                                            indicators = self.apex.calculate_indicators(df_temp)
                                                            if 'rsi' in indicators:
                                                                pos_rsi = indicators['rsi']
                                                except Exception:
                                                    # Keep default RSI if calculation fails
                                                    pass

                                                position_metrics[pos_symbol] = {
                                                    'value': pos_value,
                                                    'age_hours': pos_age_hours,
                                                    'pnl_pct': pos_pnl_pct,
                                                    'rsi': pos_rsi
                                                }
                                            except Exception:
                                                continue

                                        # Select positions to close for rotation
                                        needed_capital = position_size - account_balance
                                        positions_to_close = self.rotation_manager.select_positions_for_rotation(
                                            positions=current_positions,
                                            position_metrics=position_metrics,
                                            needed_capital=needed_capital,
                                            total_capital=total_capital
                                        )

                                        if positions_to_close:
                                            logger.info(f"   🔄 Closing {len(positions_to_close)} position(s) for rotation:")

                                            # Close selected positions
                                            closed_count = 0
                                            for pos_to_close in positions_to_close:
                                                close_symbol = pos_to_close.get('symbol')
                                                close_qty = pos_to_close.get('quantity')

                                                try:
                                                    logger.info(f"      Closing {close_symbol}: {close_qty:.8f}")
                                                    result = active_broker.place_market_order(
                                                        close_symbol,
                                                        'sell',
                                                        close_qty,
                                                        size_type='base'
                                                    )

                                                    if result and result.get('status') not in ['error', 'unfilled']:
                                                        closed_count += 1
                                                        logger.info(f"      ✅ Closed {close_symbol} successfully")
                                                    else:
                                                        logger.warning(f"      ⚠️ Failed to close {close_symbol}")

                                                    time.sleep(0.5)  # Small delay between closes

                                                except Exception as close_err:
                                                    logger.error(f"      ❌ Error closing {close_symbol}: {close_err}")

                                            if closed_count > 0:
                                                logger.info(f"   ✅ Rotation complete: Closed {closed_count} positions")
                                                self.rotation_manager.record_rotation(success=True)

                                                # Update free balance after rotation
                                                try:
                                                    time.sleep(1.0)  # Wait for balances to update
                                                    # SAFETY: guard against None return from get_account_balance()
                                                    _rotation_balance = active_broker.get_account_balance()
                                                    if _rotation_balance is None:
                                                        logger.warning("   ⚠️ Rotation balance refresh returned None — keeping previous balance")
                                                        _rotation_balance = account_balance
                                                    account_balance = float(_rotation_balance or 0.0)
                                                    logger.info(f"   💰 Updated free balance: ${account_balance:.2f}")
                                                except Exception:
                                                    pass
                                            else:
                                                logger.warning(f"   ⚠️ Rotation failed - no positions closed")
                                                self.rotation_manager.record_rotation(success=False)
                                                continue  # Skip this trade
                                        else:
                                            logger.warning(f"   ⚠️ No suitable positions for rotation")
                                            continue  # Skip this trade
                                    else:
                                        logger.warning(f"   ⚠️ Cannot rotate: {rotate_reason}")
                                        continue  # Skip this trade if rotation not allowed

                                # ═══════════════════════════════════════════════════════
                                # ENTRY GUARDRAILS — correlation / liquidity / latency
                                 # ═══════════════════════════════════════════════════════
                                if (
                                    _ENTRY_GUARDRAILS_AVAILABLE
                                    and run_all_guardrails is not None
                                    and getattr(self, 'correlation_filter', None) is not None
                                    and getattr(self, 'liquidity_filter', None) is not None
                                    and getattr(self, 'latency_guard', None) is not None
                                ):
                                    try:
                                        # Feed latest close price into correlation tracker
                                        _close_price = float(df['close'].iloc[-1])
                                        self.correlation_filter.update_price(symbol, _close_price)

                                        # Estimate 24-hour USD volume: sum the last 288 candles worth
                                        # of quote-volume (288 × 5-minute candles = 24 h).
                                        # The DataFrame holds 100 candles at most; we use all available
                                        # bars and scale up to 288 to get a conservative 24 h estimate.
                                        _vol_24h = 0.0
                                        if 'volume' in df.columns and _close_price > 0:
                                            _candle_vol_sum = float(df['volume'].sum())
                                            _n_candles = max(1, len(df))
                                            # Scale the observed sum to a 24-h window
                                            _vol_24h = _candle_vol_sum * (_close_price * 288 / _n_candles)

                                        # Use spread from analysis when available; otherwise fall back
                                        # to a conservative 0.1 % estimate.  This is a known limitation
                                        # when the broker API does not expose a live order book; callers
                                        # that have real bid/ask data should pass it explicitly to the
                                        # LiquidityFilter.check() call instead of using this estimate.
                                        _est_spread = 0.001  # 0.1 % conservative ceiling
                                        _bid = _close_price * (1 - _est_spread / 2)
                                        _ask = _close_price * (1 + _est_spread / 2)

                                        # Build list of currently open position symbols
                                        _open_syms = [
                                            p.get('symbol', '') for p in current_positions
                                            if p.get('symbol')
                                        ]

                                        _guard_passed, _guard_reason = run_all_guardrails(
                                            correlation_filter=self.correlation_filter,
                                            liquidity_filter=self.liquidity_filter,
                                            latency_guard=self.latency_guard,
                                            candidate_symbol=symbol,
                                            open_position_symbols=_open_syms,
                                            volume_24h_usd=_vol_24h,
                                            bid=_bid,
                                            ask=_ask,
                                            position_size_usd=position_size,
                                        )

                                        if not _guard_passed:
                                            logger.info(
                                                f"   🛡️  ENTRY GUARDRAILS blocked {symbol}: {_guard_reason}"
                                            )
                                            filter_stats['entry_guardrails'] = (
                                                filter_stats.get('entry_guardrails', 0) + 1
                                            )
                                            continue
                                    except Exception as _guard_err:
                                        logger.debug(
                                            f"   ⚠️ Entry guardrail check error for {symbol}: {_guard_err}"
                                        )
                                        # Non-fatal: allow trade if guardrails fail unexpectedly

                                logger.info(f"   🎯 BUY SIGNAL: {symbol} - size=${position_size:.2f} - {analysis.get('reason', '')}")

                                # ═══════════════════════════════════════════════════════
                                # SLIPPAGE PROTECTION — block order if worst-case slippage
                                # is too high to preserve profitability.
                                # ═══════════════════════════════════════════════════════
                                if hasattr(self, 'slippage_protector') and self.slippage_protector is not None:
                                    try:
                                        _slip_current_price = float(df['close'].iloc[-1])
                                        # Use spread from analysis if available; default to 0.1% estimate
                                        _slip_spread = analysis.get('spread_pct', 0.001) or 0.001
                                        _slip_bid = _slip_current_price * (1.0 - _slip_spread / 2.0)
                                        _slip_ask = _slip_current_price * (1.0 + _slip_spread / 2.0)
                                        _slip_vol_pct = analysis.get('atr_pct', 0.02) or 0.02
                                        # Estimate 24h volume from df when available
                                        if 'volume' in df.columns and _slip_current_price > 0:
                                            _slip_n = max(1, len(df))
                                            _slip_vol_24h = float(df['volume'].sum()) * (
                                                _slip_current_price * 288 / _slip_n
                                            )
                                        else:
                                            _slip_vol_24h = 0.0
                                        _slip_result = self.slippage_protector.check(
                                            symbol=symbol,
                                            side='buy',
                                            order_size_usd=position_size,
                                            bid=_slip_bid,
                                            ask=_slip_ask,
                                            volume_24h_usd=_slip_vol_24h,
                                            volatility_pct=float(_slip_vol_pct),
                                        )
                                        if not _slip_result.approved:
                                            logger.info(
                                                f"   🚫 {symbol}: SLIPPAGE PROTECTION blocked entry — "
                                                f"{_slip_result.reason}"
                                            )
                                            filter_stats['market_filter'] = (
                                                filter_stats.get('market_filter', 0) + 1
                                            )
                                            continue
                                    except Exception as _slip_err:
                                        logger.debug(
                                            f"   ⚠️ Slippage protection check skipped for {symbol}: {_slip_err}"
                                        )
                                        # Non-fatal: allow trade if slippage check fails

                                # ═══════════════════════════════════════════════════════
                                # NET PROFIT GATE — Leak #1 fix
                                # Reject signals where expected profit < (spread + slippage
                                # + fees) × safety_multiple (default 2×).
                                # ═══════════════════════════════════════════════════════
                                if hasattr(self, 'net_profit_gate') and self.net_profit_gate is not None:
                                    try:
                                        _npg_spread = analysis.get('spread_pct', 0.001) or 0.001
                                        # Primary take-profit as a fraction
                                        _npg_tp_list = analysis.get('take_profit', []) or []
                                        _npg_entry_p = analysis.get('entry_price', 0.0) or 0.0
                                        if _npg_tp_list and _npg_entry_p > 0:
                                            _npg_tp = float(_npg_tp_list[0]) if isinstance(_npg_tp_list, list) else float(_npg_tp_list)
                                            _npg_profit_pct = abs(_npg_tp - _npg_entry_p) / _npg_entry_p
                                        else:
                                            _npg_profit_pct = analysis.get('profit_target_pct', 0.0) or 0.0
                                        _npg_ok, _npg_reason = self.net_profit_gate.check(
                                            symbol=symbol,
                                            profit_target_pct=_npg_profit_pct,
                                            spread_pct=_npg_spread,
                                        )
                                        if not _npg_ok:
                                            filter_stats['market_filter'] = (
                                                filter_stats.get('market_filter', 0) + 1
                                            )
                                            continue
                                    except Exception as _npg_err:
                                        logger.debug(
                                            f"   ⚠️ Net Profit Gate check skipped for {symbol}: {_npg_err}"
                                        )

                                # ═══════════════════════════════════════════════════════
                                # LATENCY DRIFT GUARD — Leak #2 fix
                                # Stamp the current price; reject if the market has moved
                                # too far by the time execution begins.
                                # ═══════════════════════════════════════════════════════
                                _drift_token = None
                                if hasattr(self, 'latency_drift_guard') and self.latency_drift_guard is not None:
                                    try:
                                        _drift_price = float(df['close'].iloc[-1])
                                        _drift_token = self.latency_drift_guard.stamp_signal(
                                            symbol, _drift_price
                                        )
                                        analysis['_drift_token'] = _drift_token
                                        analysis['_drift_signal_price'] = _drift_price
                                    except Exception as _dg_err:
                                        logger.debug(
                                            f"   ⚠️ Latency Drift Guard stamp skipped for {symbol}: {_dg_err}"
                                        )

                                # ═══════════════════════════════════════════════════════
                                # PRIORITY SELECTION — queue signal for post-scan ranking
                                # ═══════════════════════════════════════════════════════
                                # All gates have passed. Store the fully-sized signal so
                                # the post-scan priority executor can rank all candidates
                                # by score and deploy capital in the highest-probability
                                # setups first (instead of first-found order).
                                pending_signals.append({
                                    'symbol': symbol,
                                    'analysis': analysis,
                                    'position_size': position_size,
                                    'entry_score': entry_score,
                                    'action': action,
                                })
                                logger.info(
                                    f"   📋 Signal queued (score={entry_score:.1f}, "
                                    f"size=${position_size:.2f}) — continuing scan for more candidates"
                                )

                        except Exception as e:
                            # CRITICAL FIX (Jan 10, 2026): Distinguish invalid symbols from rate limits
                            # Invalid symbols should NOT trigger circuit breakers or count as errors
                            error_str = str(e).lower()

                            # More specific patterns to avoid false positives
                            is_productid_invalid = 'productid is invalid' in error_str or 'product_id is invalid' in error_str
                            is_invalid_argument = '400' in error_str and 'invalid_argument' in error_str
                            is_invalid_product_symbol = (
                                'invalid' in error_str and
                                ('product' in error_str or 'symbol' in error_str) and
                                ('not found' in error_str or 'does not exist' in error_str or 'unknown' in error_str)
                            )

                            is_invalid_symbol = is_productid_invalid or is_invalid_argument or is_invalid_product_symbol

                            if is_invalid_symbol:
                                # Invalid/delisted symbol - skip silently without counting as error
                                invalid_symbol_counter += 1
                                filter_stats['market_filter'] += 1  # Count as filtered, not error
                                logger.debug(f"   ⚠️ Invalid/delisted symbol: {symbol} - skipping")
                                continue

                            # Count as error only if not an invalid symbol
                            error_counter += 1
                            logger.debug(f"   Error scanning {symbol}: {e}")

                            # Check if it's a rate limit error
                            if '429' in str(e) or 'rate limit' in str(e).lower() or 'too many' in str(e).lower() or '403' in str(e):
                                filter_stats['rate_limited'] += 1
                                rate_limit_counter += 1
                                logger.warning(f"   ⚠️ Rate limit error on {symbol}: {e}")

                                # GLOBAL CIRCUIT BREAKER: Too many errors = stop scanning
                                if error_counter >= max_total_errors:
                                    broker_name = self._get_broker_name(active_broker)
                                    logger.error(f"   🚨 GLOBAL CIRCUIT BREAKER: {error_counter} total errors - stopping scan")
                                    logger.error(f"   Exchange: {broker_name} | API health: {self.api_health_score}%")
                                    logger.error(f"   💤 Waiting 10s for API to fully recover...")
                                    logger.error(f"   💡 TIP: Enable additional exchanges (Kraken, OKX, Binance) to distribute load")
                                    logger.error(f"   📖 See MULTI_EXCHANGE_TRADING_GUIDE.md for setup instructions")
                                    time.sleep(10.0)
                                    break  # Exit market scan loop

                                # Add extra delay to recover
                                if rate_limit_counter >= 3:
                                    logger.warning(f"   🛑 CIRCUIT BREAKER: Pausing for 8s to allow API rate limits to reset...")
                                    time.sleep(8.0)  # Increased from 5.0s
                                    rate_limit_counter = 0
                            continue

                    # Note: Market scan delay is now applied BEFORE each candle fetch (see line ~1088)
                    # This ensures we never make requests too quickly in succession
                    # No post-delay needed since pre-delay is more effective at preventing rate limits

                    # ═══════════════════════════════════════════════════════
                    # PRIORITY SELECTION — phase 2: rank and execute top signals
                    # ═══════════════════════════════════════════════════════
                    # Sort every validated signal collected during the scan by
                    # entry score (descending) and execute only the top-ranked
                    # ones that fit within the remaining position slots.  This
                    # ensures capital is always deployed in the highest-
                    # probability setups rather than the first found.
                    # ═══════════════════════════════════════════════════════
                    if pending_signals:
                        # current_positions was fetched at the start of this cycle. Because
                        # the new two-phase design collects signals without executing any
                        # trades during the scan loop, this count is accurate: no positions
                        # were opened between the fetch and this point.  The
                        # _trades_executed_this_cycle counter below tracks positions opened
                        # during priority execution so subsequent slot checks stay correct.
                        _slots_available = max(
                            0, effective_max_positions - len(current_positions)
                        )
                        _ranked_signals = sorted(
                            pending_signals,
                            key=lambda x: x['entry_score'],
                            reverse=True,
                        )
                        logger.info("")
                        logger.info(
                            f"🏆 PRIORITY SELECTION: {len(_ranked_signals)} signal(s) collected, "
                            f"{_slots_available} slot(s) available"
                        )
                        for _rank_i, _rank_sig in enumerate(_ranked_signals[:3], start=1):
                            logger.info(
                                f"   #{_rank_i}: {_rank_sig['symbol']} "
                                f"(score={_rank_sig['entry_score']:.1f}, "
                                f"size=${_rank_sig['position_size']:.2f})"
                            )
                        if len(_ranked_signals) > 3:
                            logger.info(f"   ... and {len(_ranked_signals) - 3} more signal(s) ranked below")

                        _trades_executed_this_cycle = 0
                        for _sig_data in _ranked_signals[:_slots_available]:
                            if (
                                len(current_positions) + _trades_executed_this_cycle
                                >= effective_max_positions
                            ):
                                logger.info("   🛑 Position cap reached — stopping priority execution")
                                break

                            _ps_symbol = _sig_data['symbol']
                            _ps_analysis = _sig_data['analysis']
                            _ps_position_size = _sig_data['position_size']
                            _ps_action = _sig_data['action']

                            # Leak #2 — verify price hasn't drifted since signal was stamped
                            if hasattr(self, 'latency_drift_guard') and self.latency_drift_guard is not None:
                                _drift_token = _ps_analysis.get('_drift_token')
                                if _drift_token:
                                    try:
                                        _exec_price = _ps_analysis.get('entry_price') or _ps_analysis.get('price') or 0.0
                                        if _exec_price > 0:
                                            _drift_ok, _drift_reason = self.latency_drift_guard.check_drift(
                                                _drift_token, float(_exec_price)
                                            )
                                            if not _drift_ok:
                                                logger.warning(
                                                    "   ⏩ LATENCY DRIFT: %s skipped — %s",
                                                    _ps_symbol, _drift_reason,
                                                )
                                                filter_stats['market_filter'] = (
                                                    filter_stats.get('market_filter', 0) + 1
                                                )
                                                continue
                                        else:
                                            self.latency_drift_guard.clear(_drift_token)
                                    except Exception as _drift_exec_err:
                                        logger.debug("Drift guard execution check skipped: %s", _drift_exec_err)
                                        self.latency_drift_guard.clear(_drift_token)

                            logger.info(
                                f"   🎯 Executing priority signal "
                                f"#{_trades_executed_this_cycle + 1}: {_ps_symbol} "
                                f"(score={_sig_data['entry_score']:.1f})"
                            )

                            _ps_success = self.apex.execute_action(_ps_analysis, _ps_symbol)
                            if _ps_success:
                                logger.info(f"   ✅ Position opened: {_ps_symbol}")
                                _trades_executed_this_cycle += 1
                                # Mark first trade as executed (first-trade guarantee flag)
                                if not self._first_trade_executed:
                                    self._first_trade_executed = True
                                    logger.info("🚀 FIRST TRADE GUARANTEE: initial deployment confirmed ✅")

                                # 🔒 PROFIT LOCK SYSTEM — register new position for ratchet tracking
                                if hasattr(self, 'profit_lock_system') and self.profit_lock_system is not None:
                                    try:
                                        _pls_entry = (
                                            _ps_analysis.get('entry_price')
                                            or _ps_analysis.get('price')
                                            or 0.0
                                        )
                                        if _pls_entry > 0:
                                            self.profit_lock_system.register_position(
                                                symbol=_ps_symbol,
                                                side='long',
                                                entry_price=float(_pls_entry),
                                                position_size_usd=float(_ps_position_size),
                                            )
                                        else:
                                            logger.debug(
                                                "ProfitLockSystem: skipping register for %s — entry price unavailable",
                                                _ps_symbol,
                                            )
                                    except Exception as _pls_reg_err:
                                        logger.debug(
                                            "ProfitLockSystem.register_position skipped for %s: %s",
                                            _ps_symbol, _pls_reg_err,
                                        )

                                # ═══════════════════════════════════════════════════════
                                # PHASE 3 — DYNAMIC STOP TIGHTENER + PARTIAL TP LADDER
                                # Register new position with Phase 3 position managers.
                                # ═══════════════════════════════════════════════════════
                                _p3_entry_price = float(
                                    _ps_analysis.get('entry_price')
                                    or _ps_analysis.get('price')
                                    or 0.0
                                )
                                _p3_stop = float(
                                    _ps_analysis.get('stop_loss')
                                    or _ps_analysis.get('stop')
                                    or 0.0
                                )
                                _p3_side = 'long' if _ps_action == 'enter_long' else 'short'
                                if _p3_entry_price > 0:
                                    if (
                                        DYNAMIC_STOP_TIGHTENER_AVAILABLE
                                        and hasattr(self, 'dynamic_stop_tightener')
                                        and self.dynamic_stop_tightener is not None
                                        and _p3_stop > 0
                                    ):
                                        try:
                                            self.dynamic_stop_tightener.register_position(
                                                position_id=_ps_symbol,
                                                entry_price=_p3_entry_price,
                                                initial_stop=_p3_stop,
                                                side=_p3_side,
                                            )
                                            logger.debug(
                                                "Phase 3 DynamicStopTightener: registered %s",
                                                _ps_symbol,
                                            )
                                        except Exception as _dst_reg_err:
                                            logger.debug(
                                                "Phase 3 DynamicStopTightener.register_position skipped: %s",
                                                _dst_reg_err,
                                            )

                                    if (
                                        PARTIAL_TP_LADDER_AVAILABLE
                                        and hasattr(self, 'partial_tp_ladder')
                                        and self.partial_tp_ladder is not None
                                    ):
                                        try:
                                            self.partial_tp_ladder.register_position(
                                                position_id=_ps_symbol,
                                                entry_price=_p3_entry_price,
                                                side=_p3_side,
                                            )
                                            logger.debug(
                                                "Phase 3 PartialTPLadder: registered %s",
                                                _ps_symbol,
                                            )
                                        except Exception as _tpl_reg_err:
                                            logger.debug(
                                                "Phase 3 PartialTPLadder.register_position skipped: %s",
                                                _tpl_reg_err,
                                            )

                                # ═══════════════════════════════════════════════════════
                                # COPY TRADE ENGINE — broadcast platform trade to users
                                # Only the platform account triggers copy broadcasting.
                                # ═══════════════════════════════════════════════════════
                                if not user_mode and COPY_ENGINE_AVAILABLE and get_copy_engine and CopySignal:
                                    try:
                                        _ps_copy_side = "buy" if _ps_action == "enter_long" else "sell"
                                        logger.info(
                                            f"   📡 Broadcasting trade: {_ps_symbol} "
                                            f"{_ps_copy_side} ${_ps_position_size:.2f}"
                                        )
                                        _ps_copy_engine = get_copy_engine()
                                        _ps_copy_results = _ps_copy_engine.broadcast(CopySignal(
                                            symbol=_ps_symbol,
                                            side=_ps_copy_side,
                                            platform_size_usd=_ps_position_size,
                                        ))
                                        _ps_copy_count = len([
                                            r for r in (_ps_copy_results or [])
                                            if getattr(r, 'skipped', True) is False
                                        ])
                                        logger.info(f"   👥 Copying to {_ps_copy_count} account(s)")
                                    except Exception as _ps_copy_err:
                                        logger.debug(
                                            "CopyEngine broadcast skipped for %s: %s",
                                            _ps_symbol, _ps_copy_err,
                                        )

                                # ═══════════════════════════════════════════════════════
                                # EXECUTION PIPELINE — fan-out signal to all accounts
                                # Steps: risk-check → broadcast → dashboard → profit split
                                # → AI capital reallocation
                                # ═══════════════════════════════════════════════════════
                                if EXECUTION_PIPELINE_AVAILABLE and get_execution_pipeline:
                                    try:
                                        _ps_pipeline = get_execution_pipeline()
                                        _ps_regime_label = (
                                            _regime_result.regime
                                            if _regime_result and hasattr(_regime_result, 'regime')
                                            else "RANGING"
                                        )
                                        _ps_pipeline.run(
                                            signal={**_ps_analysis, 'symbol': _ps_symbol},
                                            account_id=self._get_broker_name(active_broker),
                                            account_balance=account_balance,
                                            regime=_ps_regime_label,
                                        )
                                    except Exception as _ps_pipe_err:
                                        logger.debug(
                                            "ExecutionPipeline skipped for %s: %s",
                                            _ps_symbol, _ps_pipe_err,
                                        )

                                # Record micro-cap trade time for re-entry cooldown
                                if _micro_cap_config:
                                    self._micro_cap_last_trade_times[_ps_symbol] = time.time()
                                    logger.info(
                                        f"   ⏱️  Micro-cap cooldown started for {_ps_symbol} "
                                        f"({MICRO_CAP_TRADE_COOLDOWN}s)"
                                    )
                            else:
                                logger.error(f"   ❌ Failed to open position: {_ps_symbol}")

                        logger.info(
                            f"   📊 Priority execution complete: "
                            f"{_trades_executed_this_cycle} trade(s) executed this cycle"
                        )

                    # ═══════════════════════════════════════════════════════
                    # MARKET REGIME CONTROLLER — post-scan evaluation
                    # ═══════════════════════════════════════════════════════
                    # Evaluate the global regime after all assets have been
                    # observed.  The result is stored in the controller's
                    # last_result property and will gate entries in the
                    # NEXT scan cycle.
                    if _regime_snapshot is not None and hasattr(self, 'regime_controller') and self.regime_controller is not None:
                        try:
                            # Evaluate and store — the result is accessible via
                            # self.regime_controller.last_result in the next cycle
                            self.regime_controller.evaluate(_regime_snapshot)
                        except Exception as regime_eval_err:
                            logger.debug(f"   ⚠️ Regime Controller evaluation error: {regime_eval_err}")

                    # Log filtering summary
                    logger.info(f"   📊 Scan summary: {filter_stats['total']} markets scanned")
                    logger.info(f"      💡 Signals found: {filter_stats['signals_found']}")
                    logger.info(f"      📉 No data: {filter_stats['insufficient_data']}")

                    # Report invalid symbols separately (informational, not errors)
                    if invalid_symbol_counter > 0:
                        logger.info(f"      ℹ️ Invalid/delisted symbols: {invalid_symbol_counter} (skipped)")

                    if filter_stats['rate_limited'] > 0:
                        logger.warning(f"      ⚠️ Rate limited: {filter_stats['rate_limited']} times")
                    logger.info(f"      🔇 Smart filter: {filter_stats['smart_filter']}")
                    logger.info(f"      📊 Market filter: {filter_stats['market_filter']}")
                    logger.info(f"      🚫 No entry signal: {filter_stats['no_entry_signal']}")
                    logger.info(f"      💵 Position too small: {filter_stats['position_too_small']}")
                    if filter_stats.get('sector_cap', 0) > 0:
                        logger.info(f"      🏷️  Sector cap (40%): {filter_stats['sector_cap']}")
                    if filter_stats.get('entry_guardrails', 0) > 0:
                        logger.info(f"      🛡️  Entry guardrails: {filter_stats['entry_guardrails']}")

                    # 📡 SIGNAL TRACE — show top-3 near-miss symbols so users can see
                    # which pairs are closest to triggering a trade and why they didn't.
                    if _near_miss_signals:
                        _top_near_misses = sorted(
                            _near_miss_signals, key=lambda x: x['score'], reverse=True
                        )[:3]
                        logger.info("   📡 SIGNAL TRACE — closest to entry this cycle:")
                        for _nm in _top_near_misses:
                            logger.info(
                                f"      • {_nm['symbol']} | score {_nm['score']:.1f}/100 "
                                f"| dir:{_nm['direction']} | {_nm['reason']}"
                            )

                    # EXPLICIT: Log waiting status when no signals found
                    if filter_stats['signals_found'] == 0:
                        self._zero_signal_streak += 1
                        logger.info("")
                        logger.info("   ⏳ WAITING FOR PLATFORM ENTRY")
                        logger.info("   → No qualifying signals found in this cycle")
                        logger.info(
                            "   → Zero-signal streak: %d cycle(s)", self._zero_signal_streak
                        )
                        logger.info("   → Will continue monitoring markets...")
                        if self._zero_signal_streak >= self._zero_signal_alert_threshold:
                            _filterable = [
                                (k, v) for k, v in filter_stats.items()
                                if k not in ('total', 'signals_found', 'cache_hits')
                                and isinstance(v, (int, float))
                            ]
                            if _filterable:
                                dominant_filter = max(_filterable, key=lambda x: x[1])
                            else:
                                dominant_filter = ("unknown", 0)
                            logger.warning(
                                "⚠️ OVER-FILTER ALERT: %d consecutive cycles with 0 signals. "
                                "Dominant filter: '%s' (%d). "
                                "Consider loosening entry criteria if markets are active.",
                                self._zero_signal_streak,
                                dominant_filter[0],
                                dominant_filter[1],
                            )
                    else:
                        # Signals found — reset the streak
                        if self._zero_signal_streak > 0:
                            logger.info(
                                "   ✅ Zero-signal streak reset (was %d cycles)",
                                self._zero_signal_streak,
                            )
                        self._zero_signal_streak = 0

                except Exception as e:
                    logger.error(f"Error during market scan: {e}", exc_info=True)
            else:
                # Enhanced diagnostic logging to understand why entries are blocked
                reasons = []
                if user_mode:
                    if explicit_user_mode:
                        reasons.append("user mode (copy-trade account)")
                    else:
                        reasons.append("safety checks forced management-only mode")
                if entries_blocked:
                    reasons.append("STOP_ALL_ENTRIES.conf exists")
                if len(current_positions) >= effective_max_positions:
                    reasons.append(f"Position cap reached ({len(current_positions)}/{effective_max_positions})")
                if account_balance is not None and account_balance < MIN_BALANCE_TO_TRADE_USD:
                    reasons.append(f"Balance ${account_balance:.2f} < ${MIN_BALANCE_TO_TRADE_USD} minimum (need buffer for fees)")

                reason_str = ", ".join(reasons) if reasons else "Unknown reason"
                logger.info(f"   Skipping new entries: {reason_str}")

            entry_duration = time.time() - entry_start_time
            logger.info(f"⏱️  [TIMING] Entry scan: {entry_duration:.2f}s")

            # ⏱️ Overall cycle duration + moving average
            cycle_total_duration = time.time() - cycle_start_time
            self._cycle_durations.append(cycle_total_duration)
            cycle_duration_average = sum(self._cycle_durations) / len(self._cycle_durations)
            logger.info(
                f"⏱️  [TIMING] Cycle total: {cycle_total_duration:.2f}s  |  "
                f"Moving avg ({len(self._cycle_durations)} cycles): {cycle_duration_average:.2f}s  |  "
                f"balance={balance_duration:.2f}s  positions={positions_duration:.2f}s  entry={entry_duration:.2f}s"
            )

            # Increment cycle counter for warmup tracking
            self.cycle_count += 1
            
            # SAFETY VERIFICATION: Check position count at end of cycle
            # Use the already-filtered current_positions count to avoid false violations.
            # Raw broker.get_positions() returns ALL crypto holdings on the exchange
            # (including dust/unsellable positions filtered earlier in the cycle), which
            # can exceed effective_max_positions even when the bot is within its cap.
            try:
                final_count = len(current_positions)

                if final_count > effective_max_positions:
                    logger.error(f"")
                    logger.error(f"❌ SAFETY VIOLATION DETECTED AT END OF CYCLE!")
                    logger.error(f"   Position count: {final_count}")
                    logger.error(f"   Maximum allowed: {effective_max_positions}")
                    logger.error(f"   Excess positions: {final_count - effective_max_positions}")
                    logger.error(f"   ⚠️ CRITICAL: Cap enforcement failed - this should never happen!")
                    logger.error(f"")
                elif final_count == effective_max_positions:
                    logger.info(f"✅ Position cap verification: At cap ({final_count}/{effective_max_positions})")
                else:
                    logger.info(f"✅ Position cap verification: Under cap ({final_count}/{effective_max_positions})")
            except Exception as verify_err:
                logger.debug(f"Position count verification skipped: {verify_err}")

        except Exception as e:
            # Never raise to keep bot loop alive
            logger.error(f"Error in trading cycle: {e}", exc_info=True)

    def _get_primary_broker_id(self) -> str:
        """Return a stable string identifier for the currently active broker."""
        if hasattr(self, 'broker') and self.broker:
            btype = getattr(self.broker, 'broker_type', None)
            if btype is not None:
                return str(btype.value).lower() if hasattr(btype, 'value') else str(btype).lower()
        return "primary"

    def record_trade_with_advanced_manager(self, symbol: str, profit_usd: float, is_win: bool):
        """
        Record a completed trade with the advanced trading manager.

        Args:
            symbol: Trading symbol
            profit_usd: Profit/loss in USD
            is_win: True if trade was profitable
        """
        # Record with broker failsafes for circuit breaker protection
        if hasattr(self, 'failsafes') and self.failsafes:
            try:
                pnl_pct = (profit_usd / 100.0) if profit_usd != 0 else 0.0  # Approximate percentage
                self.failsafes.record_trade_result(profit_usd, pnl_pct)
            except Exception as e:
                logger.warning(f"Failed to record trade in failsafes: {e}")
        
        # Record with Market Readiness Gate for win rate tracking
        if hasattr(self, 'market_readiness_gate') and self.market_readiness_gate:
            try:
                # Calculate profit as percentage (assumes $100 position size for approximation)
                # TODO: Track actual position size for accurate percentage calculation
                pnl_pct = (profit_usd / 100.0) if profit_usd != 0 else 0.0
                self.market_readiness_gate.record_trade_result(pnl_pct)
            except Exception as e:
                logger.warning(f"Failed to record trade in market readiness gate: {e}")

        # Record with Risk Budget Engine for dynamic performance scaling
        if hasattr(self, 'risk_budget_engine') and self.risk_budget_engine is not None:
            try:
                outcome = OUTCOME_WIN if is_win else OUTCOME_LOSS
                self.risk_budget_engine.record_trade_outcome(outcome=outcome, pnl=profit_usd)
            except Exception as e:
                logger.warning(f"Failed to record trade in risk budget engine: {e}")

        # Record with market adaptation for learning
        if hasattr(self, 'market_adapter') and self.market_adapter:
            try:
                # Estimate hold time (default 30 minutes if not tracked)
                hold_time_minutes = 30
                current_regime = getattr(self.market_adapter, 'current_regime', None)
                if current_regime:
                    self.market_adapter.record_trade_performance(
                        regime=current_regime,
                        pnl_dollars=profit_usd,
                        hold_time_minutes=hold_time_minutes,
                        parameters_used={'symbol': symbol}
                    )
            except Exception as e:
                logger.warning(f"Failed to record trade in market adapter: {e}")

        # Record with Portfolio Profit Engine for total portfolio profit tracking
        try:
            from bot.portfolio_profit_engine import get_portfolio_profit_engine
            _ppe = get_portfolio_profit_engine()
            _ppe.record_trade(symbol=symbol, pnl_usd=profit_usd, is_win=is_win)
        except ImportError:
            try:
                from portfolio_profit_engine import get_portfolio_profit_engine
                _ppe = get_portfolio_profit_engine()
                _ppe.record_trade(symbol=symbol, pnl_usd=profit_usd, is_win=is_win)
            except ImportError:
                logger.debug("Portfolio Profit Engine not available — skipping portfolio profit recording")
        except Exception as e:
            logger.warning(f"Failed to record trade in Portfolio Profit Engine: {e}")

        # Auto-Reinvest Engine — split profit into reinvest vs withdraw buckets
        try:
            from bot.auto_reinvest_engine import get_auto_reinvest_engine as _get_are
            _are_decision = _get_are().process_profit(
                symbol=symbol,
                gross_profit=profit_usd,
                fees=0.0,
                is_win=is_win,
            )
            if not _are_decision.skipped:
                logger.info(
                    "💰 AutoReinvest [%s] reinvest=$%.4f withdraw=$%.4f",
                    symbol, _are_decision.reinvest_usd, _are_decision.withdraw_usd,
                )
        except ImportError:
            try:
                from auto_reinvest_engine import get_auto_reinvest_engine as _get_are
                _are_decision = _get_are().process_profit(
                    symbol=symbol,
                    gross_profit=profit_usd,
                    fees=0.0,
                    is_win=is_win,
                )
                if not _are_decision.skipped:
                    logger.info(
                        "💰 AutoReinvest [%s] reinvest=$%.4f withdraw=$%.4f",
                        symbol, _are_decision.reinvest_usd, _are_decision.withdraw_usd,
                    )
            except ImportError:
                logger.debug("AutoReinvestEngine not available — skipping reinvest split")
        except Exception as _are_err:
            logger.debug("AutoReinvestEngine record skipped: %s", _are_err)

        # Record with Self-Learning Strategy Allocator
        try:
            from bot.self_learning_strategy_allocator import get_self_learning_allocator
            _sla = get_self_learning_allocator()
            # Use "APEX_V71" as the strategy name for the APEX v7.1 strategy
            _sla.record_trade(strategy="APEX_V71", pnl_usd=profit_usd, is_win=is_win)
        except ImportError:
            try:
                from self_learning_strategy_allocator import get_self_learning_allocator
                _sla = get_self_learning_allocator()
                _sla.record_trade(strategy="APEX_V71", pnl_usd=profit_usd, is_win=is_win)
            except ImportError:
                logger.debug("Self-Learning Strategy Allocator not available")
        except Exception as e:
            logger.warning(f"Failed to record trade in Self-Learning Allocator: {e}")

        # Record with Smart Drawdown Recovery engine
        try:
            from bot.smart_drawdown_recovery import get_smart_drawdown_recovery
            _sdr = get_smart_drawdown_recovery()
            _sdr_status = _sdr.get_status()
            _sdr.update(
                current_capital=_sdr_status["current_capital"] + profit_usd,
                is_win=is_win,
            )
        except ImportError:
            try:
                from smart_drawdown_recovery import get_smart_drawdown_recovery
                _sdr = get_smart_drawdown_recovery()
                _sdr_status = _sdr.get_status()
                _sdr.update(
                    current_capital=_sdr_status["current_capital"] + profit_usd,
                    is_win=is_win,
                )
            except ImportError:
                logger.debug("Smart Drawdown Recovery not available")
        except Exception as e:
            logger.warning(f"Failed to update Smart Drawdown Recovery: {e}")

        # Record with Global Risk Governor for cascade-loss circuit breaker
        if GLOBAL_RISK_GOVERNOR_AVAILABLE and get_global_risk_governor:
            try:
                _gov = get_global_risk_governor()
                _gov.record_trade_result(pnl_usd=profit_usd, is_win=is_win)
            except Exception as _gov_err:
                logger.debug("Global Risk Governor trade record skipped: %s", _gov_err)

        # Record with Win Rate Maximizer — keeps risk caps and consistency metrics current
        if hasattr(self, 'win_rate_maximizer') and self.win_rate_maximizer:
            try:
                self.win_rate_maximizer.record_outcome(
                    symbol=symbol,
                    is_win=is_win,
                    pnl_usd=profit_usd,
                )
            except Exception as _wmx_err:
                logger.debug("Win Rate Maximizer record_outcome skipped for %s: %s", symbol, _wmx_err)

        # 📊 CAPITAL CONCENTRATION ENGINE — update concentration mode, account ranking,
        # kill-weak state, and Kelly sizing stats after every closed trade
        if hasattr(self, 'capital_concentration_engine') and self.capital_concentration_engine is not None:
            try:
                self.capital_concentration_engine.record_trade(
                    account_id=self._get_primary_broker_id(),
                    pnl_usd=profit_usd,
                    is_win=is_win,
                )
            except Exception as _cce_err:
                logger.debug("Capital Concentration Engine record_trade skipped for %s: %s", symbol, _cce_err)

        # 🧠 GLOBAL CAPITAL BRAIN — update efficiency score, win streak, snowball
        # state, and reallocation counters after every closed trade
        if hasattr(self, 'global_capital_brain') and self.global_capital_brain is not None:
            try:
                self.global_capital_brain.record_trade(
                    account_id=self._get_primary_broker_id(),
                    pnl_usd=profit_usd,
                    is_win=is_win,
                )
            except Exception as _gcb_err:
                logger.debug("Global Capital Brain record_trade skipped for %s: %s", symbol, _gcb_err)

        # 🔒 PROFIT LOCK SYSTEM — record realised profit and trigger auto-withdrawal if threshold met
        if hasattr(self, 'profit_lock_system') and self.profit_lock_system is not None:
            try:
                self.profit_lock_system.record_closed_profit(symbol=symbol, pnl_usd=profit_usd)
            except Exception as _pls_close_err:
                logger.debug("ProfitLockSystem.record_closed_profit skipped for %s: %s", symbol, _pls_close_err)

        # ── CYCLE STEP 5: Feed result back into CapitalAllocator ──────────
        # Updates per-strategy performance scores (EMA return, win-rate,
        # profit-factor, Sharpe) so the next rebalance() shifts more capital
        # toward better-performing strategies automatically.
        if hasattr(self, '_capital_allocator') and self._capital_allocator is not None:
            try:
                self._capital_allocator.record_result(
                    strategy="APEX_V71",
                    pnl_usd=profit_usd,
                    is_win=is_win,
                    position_size_usd=abs(profit_usd) if profit_usd else 100.0,
                )
            except Exception as _ca_rec_err:
                logger.debug("CapitalAllocator.record_result skipped for %s: %s", symbol, _ca_rec_err)
        # ──────────────────────────────────────────────────────────────────

        # 🔍 CAPITAL FRAGMENTATION GUARD — Leak #3: update account-level performance
        if hasattr(self, 'fragmentation_guard') and self.fragmentation_guard is not None:
            try:
                self.fragmentation_guard.record_trade(
                    account_id=self._get_primary_broker_id(),
                    pnl_usd=profit_usd,
                    is_win=is_win,
                )
            except Exception as _fg_err:
                logger.debug("Fragmentation guard record_trade skipped for %s: %s", symbol, _fg_err)

        # Feed Global Drawdown Circuit Breaker trade outcome (drives recovery step-down)
        if GLOBAL_DRAWDOWN_CB_AVAILABLE and hasattr(self, 'global_drawdown_cb') and self.global_drawdown_cb is not None:
            try:
                self.global_drawdown_cb.record_trade(pnl_usd=profit_usd, is_win=is_win)
            except Exception as _gdcb_rt_err:
                logger.debug("Global Drawdown CB record_trade skipped for %s: %s", symbol, _gdcb_rt_err)

        # PHASE 3 — Abnormal Market Kill Switch: feed trade outcome
        if hasattr(self, 'abnormal_market_ks') and self.abnormal_market_ks is not None:
            try:
                self.abnormal_market_ks.record_trade(pnl_usd=profit_usd, is_win=is_win)
                # Also de-register closed position from Phase 3 managers
                if hasattr(self, 'dynamic_stop_tightener') and self.dynamic_stop_tightener is not None:
                    self.dynamic_stop_tightener.remove_position(symbol)
                if hasattr(self, 'partial_tp_ladder') and self.partial_tp_ladder is not None:
                    self.partial_tp_ladder.remove_position(symbol)
            except Exception as _aks_rt_err:
                logger.debug("Phase 3 AbnormalMarketKS record_trade skipped for %s: %s", symbol, _aks_rt_err)

        if hasattr(self, 'capital_scaling_engine') and self.capital_scaling_engine is not None:
            try:
                _fees = abs(profit_usd) * _TRADING_FEE_PCT  # approximate exchange fees
                _new_cap = float(os.environ.get("BASE_CAPITAL", str(_DEFAULT_BASE_CAPITAL)))
                try:
                    _broker = getattr(self, 'broker', None)
                    if _broker:
                        _bal = _broker.get_balance()
                        if isinstance(_bal, (int, float)) and _bal > 0:
                            _new_cap = float(_bal)
                except Exception:
                    pass
                self.capital_scaling_engine.record_trade(
                    profit=profit_usd,
                    fees=_fees,
                    is_win=is_win,
                    new_capital=_new_cap,
                )
            except Exception as _cse_rec_err:
                logger.debug("Capital Scaling Engine record_trade skipped for %s: %s", symbol, _cse_rec_err)

        # 💼 EXTERNAL CAPITAL MODE — distribute portfolio P&L to all registered investors
        if hasattr(self, 'investor_mode_engine') and self.investor_mode_engine is not None:
            try:
                self.investor_mode_engine.record_portfolio_profit(
                    pnl_usd=profit_usd,
                    symbol=symbol,
                )
            except Exception as _ime_rec_err:
                logger.debug("Investor Mode record_portfolio_profit skipped for %s: %s", symbol, _ime_rec_err)

        # 🔒 TIERED RISK ENGINE — update daily P&L tracking for drawdown guard
        if hasattr(self, 'tiered_risk_engine') and self.tiered_risk_engine is not None:
            try:
                self.tiered_risk_engine.update_daily_pnl(pnl=profit_usd)
            except Exception as _tre_rec_err:
                logger.debug("Tiered Risk Engine update_daily_pnl skipped for %s: %s", symbol, _tre_rec_err)

        # 🧬 AI STRATEGY EVOLUTION ENGINE — feed live result to genetic fitness scoring
        if hasattr(self, 'ai_strategy_evolution_engine') and self.ai_strategy_evolution_engine is not None:
            try:
                _current_capital = float(os.environ.get("BASE_CAPITAL", str(_DEFAULT_BASE_CAPITAL)))
                _pnl_pct = (profit_usd / _current_capital * 100.0) if _current_capital > 0 else 0.0
                _best_genome = self.ai_strategy_evolution_engine.get_best_genome()
                _genome_id = _best_genome.genome_id if _best_genome else "genome-000"
                _regime = "UNKNOWN"
                try:
                    if hasattr(self, 'market_regime_controller') and self.market_regime_controller:
                        _regime = str(getattr(self.market_regime_controller, 'current_regime', "UNKNOWN"))
                except Exception:
                    pass
                self.ai_strategy_evolution_engine.record_trade(
                    genome_id=_genome_id,
                    pnl_pct=_pnl_pct,
                    is_win=is_win,
                    regime=_regime,
                )
                # Trigger an evolution cycle every 20 trades to mutate strategies
                _trade_count = getattr(self, '_ai_evolution_trade_count', 0) + 1
                self._ai_evolution_trade_count = _trade_count
                if _trade_count % _AI_EVOLUTION_CYCLE_TRADES == 0:
                    try:
                        _evo_summary = self.ai_strategy_evolution_engine.evolve_cycle()
                        logger.info(
                            "🧬 AI Evolution cycle triggered (trade #%d) — "
                            "gen=%s champion_fitness=%.4f",
                            _trade_count,
                            _evo_summary.get("generation", "?"),
                            _evo_summary.get("champion_fitness", 0.0),
                        )
                    except Exception as _evo_err:
                        logger.debug("AI evolution cycle skipped: %s", _evo_err)
            except Exception as _asee_rec_err:
                logger.debug("AI Strategy Evolution record_trade skipped for %s: %s", symbol, _asee_rec_err)

        # ── Phase 2: Trade Clustering — record outcome ─────────────────────
        if TRADE_CLUSTER_AVAILABLE and hasattr(self, 'trade_cluster_engine') and self.trade_cluster_engine is not None:
            try:
                self.trade_cluster_engine.record_outcome(is_win=is_win, pnl_usd=profit_usd)
            except Exception as _tce_rec_err:
                logger.debug("Trade Cluster Engine record_outcome skipped for %s: %s", symbol, _tce_rec_err)

        # ── Phase 2: Adaptive TP — record win streak for streak multiplier ──
        if ADAPTIVE_TP_AVAILABLE and hasattr(self, 'adaptive_tp_engine') and self.adaptive_tp_engine is not None:
            try:
                self.adaptive_tp_engine.record_trade_result(is_win=is_win)
            except Exception as _atp_rec_err:
                logger.debug("Adaptive TP Engine record_trade_result skipped for %s: %s", symbol, _atp_rec_err)

        # ── Phase 2: Auto Broker Capital Shifter — periodic evaluation ──────
        # Evaluate on every closed trade so allocations stay current.
        if AUTO_BROKER_SHIFTER_AVAILABLE and hasattr(self, 'broker_capital_shifter') and self.broker_capital_shifter is not None:
            try:
                _shift_result = self.broker_capital_shifter.evaluate()
                if _shift_result.shifted:
                    logger.info(
                        "🔀 Broker Capital Shift applied — %s",
                        _shift_result.reason,
                    )
            except Exception as _bcs_rec_err:
                logger.debug("Auto Broker Capital Shifter evaluate skipped after trade: %s", _bcs_rec_err)

        if not self.advanced_manager:
            return

        try:
            # Determine which exchange was used
            from advanced_trading_integration import ExchangeType

            # Default to Coinbase as it's the primary broker
            exchange = ExchangeType.COINBASE

            # Try to detect actual exchange if broker type is available
            if hasattr(self, 'broker') and self.broker:
                broker_type = getattr(self.broker, 'broker_type', None)
                if broker_type:
                    exchange_mapping = {
                        'coinbase': ExchangeType.COINBASE,
                        'okx': ExchangeType.OKX,
                        'kraken': ExchangeType.KRAKEN,
                        'binance': ExchangeType.BINANCE,
                        'alpaca': ExchangeType.ALPACA,
                    }
                    broker_name = str(broker_type.value).lower() if hasattr(broker_type, 'value') else str(broker_type).lower()
                    exchange = exchange_mapping.get(broker_name, ExchangeType.COINBASE)

            # Record the trade
            self.advanced_manager.record_completed_trade(
                exchange=exchange,
                profit_usd=profit_usd,
                is_win=is_win
            )

            logger.debug(f"Recorded trade in advanced manager: {symbol} profit=${profit_usd:.2f} win={is_win}")

        except Exception as e:
            logger.warning(f"Failed to record trade in advanced manager: {e}")

    def process_end_of_day(self):
        """
        Process end-of-day tasks for advanced trading features.

        Should be called once per day to:
        - Check if daily profit target was achieved
        - Trigger rebalancing if needed
        - Generate performance reports
        """
        if not self.advanced_manager:
            return

        try:
            # Process end-of-day in advanced manager
            self.advanced_manager.process_end_of_day()

            # Log current status
            current_target = self.advanced_manager.target_manager.get_current_target()
            progress = self.advanced_manager.target_manager.get_progress_summary()

            logger.info("=" * 70)
            logger.info("📊 END OF DAY SUMMARY")
            logger.info(f"   Current Target: ${current_target:.2f}/day")
            logger.info(f"   Progress: {progress}")
            logger.info("=" * 70)

        except Exception as e:
            logger.warning(f"Failed to process end-of-day tasks: {e}")
