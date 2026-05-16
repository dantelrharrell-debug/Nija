"""
NIJA Control Layer — Phase 1: Signal Processing Pipeline
=========================================================

Hybrid Dual-Engine architecture (APEX v7.1 + Institutional):
  - Engine 1 (APEX v7.1):    Scalping, 40% capital
  - Engine 2 (Institutional): Swings,   60% capital

This package provides the Redis-first control layer that sits between
signal generation and execution.  It normalises, validates, and
risk-gates every signal before it reaches the order router.

Public API
----------
::

    from bot.control import (
        ControlCompiler, RawSignal, CompiledSignal,
        RegimeEngine, MarketRegime,
        RiskEngine,
        SignalPipeline,
    )

    pipeline = SignalPipeline()
    result   = pipeline.process_signal(raw_signal, df, current_positions)
    if result:
        execute(result)

Author: NIJA Trading Systems
Phase:  1 — Control Layer (Redis-first, no ML/DB)
"""

from bot.control.control_compiler import (
    ControlCompiler,
    RawSignal,
    CompiledSignal,
    get_control_compiler,
)
from bot.control.regime_engine import (
    RegimeEngine,
    MarketRegime,
    RegimeResult,
    get_regime_engine,
)
from bot.control.risk_engine import (
    RiskEngine,
    RiskRules,
    get_risk_engine,
)
from bot.control.signal_pipeline import (
    SignalPipeline,
    get_signal_pipeline,
)

__all__ = [
    # Control Compiler
    "ControlCompiler",
    "RawSignal",
    "CompiledSignal",
    "get_control_compiler",
    # Regime Engine
    "RegimeEngine",
    "MarketRegime",
    "RegimeResult",
    "get_regime_engine",
    # Risk Engine
    "RiskEngine",
    "RiskRules",
    "get_risk_engine",
    # Signal Pipeline
    "SignalPipeline",
    "get_signal_pipeline",
]
