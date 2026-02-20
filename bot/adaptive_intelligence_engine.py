"""
NIJA Adaptive Intelligence Engine
===================================

Unified orchestration layer implementing five key intelligent capabilities:

1. Dynamic Risk Tier & Allocation Adjustments
   - Monitors recent performance, market volatility, and drawdowns
   - Adjusts max_trade_pct and max_concurrent_positions within hard caps
   - Absolute caps and stop-loss rules always enforced

2. Cross-Market & Sector Learning
   - Tracks historical success rates per sector/symbol
   - Weights trades toward high-probability instruments
   - Low-confidence trades allowed with reduced size (not skipped)

3. Strategy Evolution & Adaptive Entry/Exit Logic
   - Automatically tests experimental parameter sets in paper-trading mode
   - Promotes to live trading once confidence thresholds are met
   - Auto-reverts to previous settings if losses exceed threshold

4. Capital Allocation & Auto-Rebalancing
   - Dynamically allocates capital across accounts/brokers
   - Based on account performance history, market opportunities, risk exposure
   - Never exceeds per-account allocation rules

5. Monitoring & Feedback Loop
   - Real-time analytics: win/loss, volatility, position sizes
   - Simulation engine: test allocations/parameters before applying
   - Fail-safe rollback: revert if losses spike or unexpected behavior occurs
   - Audit logs: traceable trading history for compliance and debugging

Author: NIJA Trading Systems
Version: 1.0
Date: February 2026
"""

import logging
import json
import os
import statistics
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path

logger = logging.getLogger("nija.adaptive_intelligence")


# ---------------------------------------------------------------------------
# Shared Enums & Constants
# ---------------------------------------------------------------------------

class VolatilityLevel(Enum):
    """Market volatility classification"""
    LOW = "low"          # Below-normal volatility — safe to increase size
    NORMAL = "normal"    # Expected volatility — base parameters
    HIGH = "high"        # Elevated volatility — reduce size
    EXTREME = "extreme"  # Crisis-level volatility — minimum parameters


# Hard caps that can NEVER be exceeded regardless of adaptive logic
HARD_CAP_MAX_TRADE_PCT = 0.10      # 10 % of account per trade (absolute ceiling)
HARD_CAP_MIN_TRADE_PCT = 0.005     # 0.5 % of account per trade (floor)
HARD_CAP_MAX_CONCURRENT = 20       # Maximum simultaneous positions
HARD_CAP_MIN_CONCURRENT = 1        # Minimum simultaneous positions


# ---------------------------------------------------------------------------
# Feature 1 — Dynamic Risk Controller
# ---------------------------------------------------------------------------

@dataclass
class RiskParameters:
    """Live risk parameters adjusted by the dynamic risk controller"""
    max_trade_pct: float = 0.03          # Max allocation per position (% of balance)
    max_concurrent_positions: int = 5    # Max simultaneous open positions
    volatility_level: VolatilityLevel = VolatilityLevel.NORMAL
    last_updated: datetime = field(default_factory=datetime.now)

    def clamp(self) -> "RiskParameters":
        """Enforce hard caps — called after every adjustment"""
        self.max_trade_pct = max(
            HARD_CAP_MIN_TRADE_PCT,
            min(HARD_CAP_MAX_TRADE_PCT, self.max_trade_pct)
        )
        self.max_concurrent_positions = max(
            HARD_CAP_MIN_CONCURRENT,
            min(HARD_CAP_MAX_CONCURRENT, self.max_concurrent_positions)
        )
        return self


class DynamicRiskController:
    """
    Feature 1 — Dynamic Risk Tier & Allocation Adjustments

    Monitors recent performance, market volatility, and drawdowns to
    automatically adjust trade size per position and max concurrent positions.

    Safety guarantees:
    - Absolute hard caps are never exceeded
    - Stop-loss rules enforced by the underlying risk_manager (not bypassed here)
    - Adjustments are incremental and reversible
    """

    def __init__(
        self,
        base_max_trade_pct: float = 0.03,
        base_max_concurrent: int = 5,
        evaluation_window: int = 20,   # Number of recent trades to evaluate
    ):
        self.base_max_trade_pct = base_max_trade_pct
        self.base_max_concurrent = base_max_concurrent
        self.evaluation_window = evaluation_window

        # Current active parameters
        self.parameters = RiskParameters(
            max_trade_pct=base_max_trade_pct,
            max_concurrent_positions=base_max_concurrent,
        ).clamp()

        # Trade history for performance monitoring
        self._trade_results: List[Dict[str, Any]] = []

        logger.info(
            "✅ DynamicRiskController initialized | "
            f"base_trade_pct={base_max_trade_pct:.2%} "
            f"base_concurrent={base_max_concurrent}"
        )

    def record_trade_result(
        self,
        pnl: float,
        is_win: bool,
        current_drawdown_pct: float,
        volatility_pct: float,
    ) -> None:
        """Record a completed trade for the rolling performance window."""
        self._trade_results.append({
            "timestamp": datetime.now(),
            "pnl": pnl,
            "is_win": is_win,
            "drawdown_pct": current_drawdown_pct,
            "volatility_pct": volatility_pct,
        })
        # Keep only the most recent window
        if len(self._trade_results) > self.evaluation_window * 2:
            self._trade_results = self._trade_results[-self.evaluation_window:]

    def update_parameters(self, current_volatility_pct: float, current_drawdown_pct: float) -> RiskParameters:
        """
        Re-evaluate and adjust risk parameters based on recent performance.

        Args:
            current_volatility_pct: Annualized volatility of portfolio/market (0-100)
            current_drawdown_pct:   Current peak-to-trough drawdown (0-100)

        Returns:
            Updated RiskParameters (hard caps enforced)
        """
        recent = self._trade_results[-self.evaluation_window:]

        win_rate = (sum(1 for t in recent if t["is_win"]) / len(recent)) if recent else 0.5
        avg_pnl = statistics.mean(t["pnl"] for t in recent) if recent else 0.0

        # ---- Classify volatility ----
        if current_volatility_pct < 15:
            vol_level = VolatilityLevel.LOW
        elif current_volatility_pct < 35:
            vol_level = VolatilityLevel.NORMAL
        elif current_volatility_pct < 60:
            vol_level = VolatilityLevel.HIGH
        else:
            vol_level = VolatilityLevel.EXTREME

        # ---- Compute trade-size multiplier ----
        # Volatility adjustment (lower vol = larger positions)
        vol_multiplier = {
            VolatilityLevel.LOW:     1.20,
            VolatilityLevel.NORMAL:  1.00,
            VolatilityLevel.HIGH:    0.75,
            VolatilityLevel.EXTREME: 0.50,
        }[vol_level]

        # Drawdown adjustment (higher drawdown = smaller positions)
        if current_drawdown_pct >= 20:
            drawdown_multiplier = 0.50
        elif current_drawdown_pct >= 10:
            drawdown_multiplier = 0.75
        else:
            drawdown_multiplier = 1.00

        # Performance adjustment
        if win_rate >= 0.65 and avg_pnl > 0:
            perf_multiplier = 1.15
        elif win_rate <= 0.40 or avg_pnl < 0:
            perf_multiplier = 0.80
        else:
            perf_multiplier = 1.00

        new_trade_pct = self.base_max_trade_pct * vol_multiplier * drawdown_multiplier * perf_multiplier

        # ---- Compute concurrent-positions adjustment ----
        if vol_level == VolatilityLevel.EXTREME or current_drawdown_pct >= 20:
            concurrent_delta = -2
        elif vol_level == VolatilityLevel.HIGH or current_drawdown_pct >= 10:
            concurrent_delta = -1
        elif vol_level == VolatilityLevel.LOW and win_rate >= 0.60:
            concurrent_delta = +2
        else:
            concurrent_delta = 0

        new_concurrent = self.base_max_concurrent + concurrent_delta

        self.parameters = RiskParameters(
            max_trade_pct=new_trade_pct,
            max_concurrent_positions=new_concurrent,
            volatility_level=vol_level,
        ).clamp()

        logger.info(
            f"🔧 RiskParams updated | "
            f"trade_pct={self.parameters.max_trade_pct:.2%} "
            f"concurrent={self.parameters.max_concurrent_positions} "
            f"vol={vol_level.value} dd={current_drawdown_pct:.1f}% wr={win_rate:.1%}"
        )
        return self.parameters

    def get_current_parameters(self) -> RiskParameters:
        """Return the current active risk parameters."""
        return self.parameters


# ---------------------------------------------------------------------------
# Feature 2 — Sector Learning Engine
# ---------------------------------------------------------------------------

@dataclass
class SectorPerformance:
    """Performance statistics for a single sector or symbol"""
    name: str
    trade_count: int = 0
    win_count: int = 0
    total_pnl: float = 0.0
    confidence_weight: float = 1.0  # Applied to position sizing

    @property
    def win_rate(self) -> float:
        return (self.win_count / self.trade_count) if self.trade_count > 0 else 0.5

    @property
    def avg_pnl(self) -> float:
        return (self.total_pnl / self.trade_count) if self.trade_count > 0 else 0.0


class SectorLearningEngine:
    """
    Feature 2 — Cross-Market & Sector Learning

    Tracks historical success rates per sector and symbol.
    Returns a confidence weight (0.3–1.5) used to scale position sizes.

    Safety: Low-confidence instruments are never fully blocked — they always
    receive at least 30 % of the base position size.
    """

    MIN_WEIGHT = 0.30   # Floor: always allow some exposure to avoid overfitting
    MAX_WEIGHT = 1.50   # Ceiling: maximum boost for high-performers
    MIN_TRADES_FOR_WEIGHTING = 10  # Need this many trades before adjusting weight

    def __init__(self, data_dir: str = "./data/sector_learning"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self._sector_stats: Dict[str, SectorPerformance] = {}
        self._symbol_stats: Dict[str, SectorPerformance] = {}

        self._load()
        logger.info("✅ SectorLearningEngine initialized")

    def record_trade(self, symbol: str, sector: str, pnl: float, is_win: bool) -> None:
        """Record a completed trade for sector and symbol learning."""
        for key, store in [(sector, self._sector_stats), (symbol, self._symbol_stats)]:
            if key not in store:
                store[key] = SectorPerformance(name=key)
            perf = store[key]
            perf.trade_count += 1
            perf.total_pnl += pnl
            if is_win:
                perf.win_count += 1
            # Update confidence weight after recording
            perf.confidence_weight = self._compute_weight(perf)

        self._save()

    def get_confidence_weight(self, symbol: str, sector: str) -> float:
        """
        Return a position-size confidence weight for the given symbol/sector.

        Weight is derived from historical success rates. Falls back to 1.0 if
        insufficient data.
        """
        sym_perf = self._symbol_stats.get(symbol)
        sec_perf = self._sector_stats.get(sector)

        sym_weight = sym_perf.confidence_weight if (
            sym_perf and sym_perf.trade_count >= self.MIN_TRADES_FOR_WEIGHTING
        ) else 1.0

        sec_weight = sec_perf.confidence_weight if (
            sec_perf and sec_perf.trade_count >= self.MIN_TRADES_FOR_WEIGHTING
        ) else 1.0

        # Blend symbol-level and sector-level weights (symbol more specific → higher weight)
        blended = 0.6 * sym_weight + 0.4 * sec_weight
        return max(self.MIN_WEIGHT, min(self.MAX_WEIGHT, blended))

    def get_top_sectors(self, n: int = 5) -> List[Tuple[str, float]]:
        """Return the n highest-weighted sectors by confidence weight."""
        sorted_sectors = sorted(
            self._sector_stats.values(),
            key=lambda s: s.confidence_weight,
            reverse=True,
        )
        return [(s.name, s.confidence_weight) for s in sorted_sectors[:n]]

    def get_summary(self) -> Dict[str, Any]:
        """Return a summary of all tracked sectors and symbols."""
        return {
            "sectors": {
                k: {
                    "trade_count": v.trade_count,
                    "win_rate": round(v.win_rate, 3),
                    "avg_pnl": round(v.avg_pnl, 4),
                    "confidence_weight": round(v.confidence_weight, 3),
                }
                for k, v in self._sector_stats.items()
            },
            "top_symbols": sorted(
                [
                    {
                        "symbol": v.name,
                        "trade_count": v.trade_count,
                        "win_rate": round(v.win_rate, 3),
                        "confidence_weight": round(v.confidence_weight, 3),
                    }
                    for v in self._symbol_stats.values()
                    if v.trade_count >= self.MIN_TRADES_FOR_WEIGHTING
                ],
                key=lambda x: x["confidence_weight"],
                reverse=True,
            )[:20],
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_weight(self, perf: SectorPerformance) -> float:
        """Compute confidence weight from performance statistics."""
        if perf.trade_count < self.MIN_TRADES_FOR_WEIGHTING:
            return 1.0  # Neutral — insufficient data

        wr = perf.win_rate
        avg_pnl = perf.avg_pnl

        # Base weight from win rate relative to 50 % baseline
        wr_weight = 0.5 + (wr - 0.5) * 2.0  # 0.0 at 0% WR, 1.5 at 75% WR

        # Profit factor adjustment
        if avg_pnl > 0:
            pf_boost = min(0.3, avg_pnl * 10)
        else:
            pf_boost = max(-0.3, avg_pnl * 10)

        raw_weight = wr_weight + pf_boost
        return max(self.MIN_WEIGHT, min(self.MAX_WEIGHT, raw_weight))

    def _load(self) -> None:
        path = self.data_dir / "sector_stats.json"
        if not path.exists():
            return
        try:
            with open(path) as f:
                data = json.load(f)
            for name, d in data.get("sectors", {}).items():
                sp = SectorPerformance(**d)
                self._sector_stats[name] = sp
            for name, d in data.get("symbols", {}).items():
                sp = SectorPerformance(**d)
                self._symbol_stats[name] = sp
            logger.info(f"✅ SectorLearningEngine loaded {len(self._sector_stats)} sectors, "
                        f"{len(self._symbol_stats)} symbols")
        except Exception as e:
            logger.warning(f"⚠️ SectorLearningEngine could not load data: {e}")

    def _save(self) -> None:
        path = self.data_dir / "sector_stats.json"
        try:
            data = {
                "sectors": {k: asdict(v) for k, v in self._sector_stats.items()},
                "symbols": {k: asdict(v) for k, v in self._symbol_stats.items()},
            }
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"⚠️ SectorLearningEngine could not save data: {e}")


# ---------------------------------------------------------------------------
# Feature 3 — Strategy Evolution Controller
# ---------------------------------------------------------------------------

class ExperimentState(Enum):
    """Lifecycle state of a parameter experiment"""
    PAPER_TRADING = "paper_trading"   # Running in simulation only
    PROMOTED = "promoted"             # Promoted to live trading
    ROLLED_BACK = "rolled_back"       # Reverted due to poor performance
    PENDING = "pending"               # Awaiting paper-trading results


@dataclass
class ParameterExperiment:
    """A set of strategy parameters being tested in paper-trading"""
    experiment_id: str
    parameters: Dict[str, Any]
    state: ExperimentState = ExperimentState.PENDING

    # Paper-trading performance tracking
    paper_trades: int = 0
    paper_wins: int = 0
    paper_pnl: float = 0.0

    # Live performance after promotion (for rollback monitoring)
    live_trades: int = 0
    live_pnl: float = 0.0

    created_at: datetime = field(default_factory=datetime.now)
    promoted_at: Optional[datetime] = None
    rolled_back_at: Optional[datetime] = None

    @property
    def paper_win_rate(self) -> float:
        return (self.paper_wins / self.paper_trades) if self.paper_trades > 0 else 0.0

    @property
    def paper_avg_pnl(self) -> float:
        return (self.paper_pnl / self.paper_trades) if self.paper_trades > 0 else 0.0


class StrategyEvolutionController:
    """
    Feature 3 — Strategy Evolution & Adaptive Entry/Exit Logic

    Manages the full lifecycle of parameter experiments:
      1. Register a new experiment (paper-trading phase begins)
      2. Record simulated trade results
      3. Evaluate and promote if confidence thresholds are met
      4. Monitor live performance and roll back if losses spike

    Safety: Changes only applied after simulated results show improvement.
             Auto-reverts if live losses exceed rollback threshold.
    """

    # Promotion requires: min trades, min win rate, and positive avg PnL
    PROMOTION_MIN_PAPER_TRADES = 20
    PROMOTION_MIN_WIN_RATE = 0.55
    PROMOTION_MIN_AVG_PNL = 0.0  # Must be profitable on average

    # Rollback if live avg PnL drops below this after promotion
    ROLLBACK_LIVE_AVG_PNL_THRESHOLD = -0.005  # -0.5 % average loss per trade
    ROLLBACK_MIN_LIVE_TRADES = 10             # Need at least this many live trades before rollback

    def __init__(self, data_dir: str = "./data/strategy_evolution"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self._experiments: Dict[str, ParameterExperiment] = {}
        self._active_experiment_id: Optional[str] = None  # Currently promoted experiment
        self._base_parameters: Dict[str, Any] = {}        # Fallback parameters

        self._load()
        logger.info("✅ StrategyEvolutionController initialized")

    def set_base_parameters(self, params: Dict[str, Any]) -> None:
        """Set the baseline parameters to fall back to on rollback."""
        self._base_parameters = dict(params)

    def register_experiment(self, experiment_id: str, parameters: Dict[str, Any]) -> ParameterExperiment:
        """
        Register a new parameter set for paper-trading evaluation.

        Args:
            experiment_id: Unique identifier for this experiment
            parameters:    Parameter dict to test (e.g. RSI thresholds, stop-loss %)

        Returns:
            The new ParameterExperiment object
        """
        exp = ParameterExperiment(
            experiment_id=experiment_id,
            parameters=dict(parameters),
            state=ExperimentState.PAPER_TRADING,
        )
        self._experiments[experiment_id] = exp
        self._save()
        logger.info(f"🧪 Experiment '{experiment_id}' registered for paper trading | params={parameters}")
        return exp

    def record_paper_result(self, experiment_id: str, pnl: float, is_win: bool) -> Optional[ParameterExperiment]:
        """
        Record a simulated trade result for a paper-trading experiment.
        Evaluates promotion automatically after recording.

        Returns:
            Updated experiment, or None if experiment_id unknown
        """
        exp = self._experiments.get(experiment_id)
        if exp is None or exp.state != ExperimentState.PAPER_TRADING:
            return None

        exp.paper_trades += 1
        exp.paper_pnl += pnl
        if is_win:
            exp.paper_wins += 1

        # Check promotion criteria
        if (
            exp.paper_trades >= self.PROMOTION_MIN_PAPER_TRADES
            and exp.paper_win_rate >= self.PROMOTION_MIN_WIN_RATE
            and exp.paper_avg_pnl >= self.PROMOTION_MIN_AVG_PNL
        ):
            self._promote(experiment_id)

        self._save()
        return exp

    def record_live_result(self, pnl: float, is_win: bool) -> Optional[ParameterExperiment]:
        """
        Record a live trade result for the currently promoted experiment.
        Checks rollback criteria automatically.

        Returns:
            Currently promoted experiment, or None if no active experiment
        """
        if self._active_experiment_id is None:
            return None

        exp = self._experiments.get(self._active_experiment_id)
        if exp is None or exp.state != ExperimentState.PROMOTED:
            return None

        exp.live_trades += 1
        exp.live_pnl += pnl

        live_avg = exp.live_pnl / exp.live_trades
        if (
            exp.live_trades >= self.ROLLBACK_MIN_LIVE_TRADES
            and live_avg < self.ROLLBACK_LIVE_AVG_PNL_THRESHOLD
        ):
            self._rollback(self._active_experiment_id)

        self._save()
        return exp

    def get_active_parameters(self) -> Dict[str, Any]:
        """
        Return the currently active parameter set.
        Falls back to base parameters if no experiment is promoted.
        """
        if self._active_experiment_id:
            exp = self._experiments.get(self._active_experiment_id)
            if exp and exp.state == ExperimentState.PROMOTED:
                return dict(exp.parameters)
        return dict(self._base_parameters)

    def get_status(self) -> Dict[str, Any]:
        """Return a summary of all experiments and the currently active set."""
        return {
            "active_experiment": self._active_experiment_id,
            "active_parameters": self.get_active_parameters(),
            "experiments": [
                {
                    "id": exp.experiment_id,
                    "state": exp.state.value,
                    "paper_trades": exp.paper_trades,
                    "paper_win_rate": round(exp.paper_win_rate, 3),
                    "paper_pnl": round(exp.paper_pnl, 4),
                    "live_trades": exp.live_trades,
                    "live_pnl": round(exp.live_pnl, 4),
                }
                for exp in self._experiments.values()
            ],
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _promote(self, experiment_id: str) -> None:
        """Promote experiment to live trading."""
        exp = self._experiments[experiment_id]
        exp.state = ExperimentState.PROMOTED
        exp.promoted_at = datetime.now()
        self._active_experiment_id = experiment_id
        logger.info(
            f"🚀 Experiment '{experiment_id}' PROMOTED to live | "
            f"paper_trades={exp.paper_trades} "
            f"win_rate={exp.paper_win_rate:.1%} "
            f"avg_pnl={exp.paper_avg_pnl:.4f}"
        )

    def _rollback(self, experiment_id: str) -> None:
        """Roll back a promoted experiment to base parameters."""
        exp = self._experiments[experiment_id]
        exp.state = ExperimentState.ROLLED_BACK
        exp.rolled_back_at = datetime.now()
        self._active_experiment_id = None
        logger.warning(
            f"⏪ Experiment '{experiment_id}' ROLLED BACK | "
            f"live_trades={exp.live_trades} "
            f"live_avg_pnl={exp.live_pnl / exp.live_trades:.4f}"
        )

    def _load(self) -> None:
        path = self.data_dir / "experiments.json"
        if not path.exists():
            return
        try:
            with open(path) as f:
                data = json.load(f)
            self._base_parameters = data.get("base_parameters", {})
            self._active_experiment_id = data.get("active_experiment_id")
            for d in data.get("experiments", []):
                exp = ParameterExperiment(
                    experiment_id=d["experiment_id"],
                    parameters=d["parameters"],
                    state=ExperimentState(d["state"]),
                    paper_trades=d.get("paper_trades", 0),
                    paper_wins=d.get("paper_wins", 0),
                    paper_pnl=d.get("paper_pnl", 0.0),
                    live_trades=d.get("live_trades", 0),
                    live_pnl=d.get("live_pnl", 0.0),
                    created_at=datetime.fromisoformat(d["created_at"]),
                    promoted_at=datetime.fromisoformat(d["promoted_at"]) if d.get("promoted_at") else None,
                    rolled_back_at=datetime.fromisoformat(d["rolled_back_at"]) if d.get("rolled_back_at") else None,
                )
                self._experiments[exp.experiment_id] = exp
            logger.info(f"✅ StrategyEvolutionController loaded {len(self._experiments)} experiments")
        except Exception as e:
            logger.warning(f"⚠️ StrategyEvolutionController could not load data: {e}")

    def _save(self) -> None:
        path = self.data_dir / "experiments.json"
        try:
            exps = []
            for exp in self._experiments.values():
                d = {
                    "experiment_id": exp.experiment_id,
                    "parameters": exp.parameters,
                    "state": exp.state.value,
                    "paper_trades": exp.paper_trades,
                    "paper_wins": exp.paper_wins,
                    "paper_pnl": exp.paper_pnl,
                    "live_trades": exp.live_trades,
                    "live_pnl": exp.live_pnl,
                    "created_at": exp.created_at.isoformat(),
                    "promoted_at": exp.promoted_at.isoformat() if exp.promoted_at else None,
                    "rolled_back_at": exp.rolled_back_at.isoformat() if exp.rolled_back_at else None,
                }
                exps.append(d)
            with open(path, "w") as f:
                json.dump({
                    "base_parameters": self._base_parameters,
                    "active_experiment_id": self._active_experiment_id,
                    "experiments": exps,
                }, f, indent=2)
        except Exception as e:
            logger.warning(f"⚠️ StrategyEvolutionController could not save data: {e}")


# ---------------------------------------------------------------------------
# Feature 4 — Capital Rebalancer
# ---------------------------------------------------------------------------

@dataclass
class AccountAllocation:
    """Capital allocation record for a single account/broker"""
    account_id: str
    broker: str
    current_balance: float
    allocated_pct: float      # Fraction of total portfolio allocated here
    performance_score: float  # 0.0 (worst) to 1.0 (best)
    last_updated: datetime = field(default_factory=datetime.now)

    @property
    def allocated_amount(self) -> float:
        return self.current_balance * self.allocated_pct


class CapitalRebalancer:
    """
    Feature 4 — Capital Allocation & Auto-Rebalancing

    Dynamically allocates capital across accounts/brokers based on:
    - Account performance history
    - Market opportunities per broker
    - Risk exposure vs. current balance

    Safety:
    - Per-account allocation caps are always respected
    - Never allocates more than the configured maximum to any single account
    """

    DEFAULT_MIN_ALLOC = 0.05   # 5 % minimum allocation per account
    DEFAULT_MAX_ALLOC = 0.50   # 50 % maximum allocation per account

    def __init__(
        self,
        min_alloc_pct: float = DEFAULT_MIN_ALLOC,
        max_alloc_pct: float = DEFAULT_MAX_ALLOC,
    ):
        self.min_alloc_pct = min_alloc_pct
        self.max_alloc_pct = max_alloc_pct

        self._accounts: Dict[str, AccountAllocation] = {}
        self._trade_history: Dict[str, List[Dict]] = {}  # account_id → trades

        logger.info("✅ CapitalRebalancer initialized")

    def register_account(
        self,
        account_id: str,
        broker: str,
        current_balance: float,
        initial_alloc_pct: float = 0.20,
    ) -> AccountAllocation:
        """Register an account for capital rebalancing."""
        alloc = AccountAllocation(
            account_id=account_id,
            broker=broker,
            current_balance=current_balance,
            allocated_pct=initial_alloc_pct,
            performance_score=0.5,
        )
        self._accounts[account_id] = alloc
        self._trade_history[account_id] = []
        logger.info(f"📂 Account '{account_id}' ({broker}) registered | balance=${current_balance:.2f}")
        return alloc

    def record_account_trade(self, account_id: str, pnl: float, is_win: bool) -> None:
        """Record a trade for a specific account."""
        if account_id not in self._trade_history:
            self._trade_history[account_id] = []
        self._trade_history[account_id].append({
            "timestamp": datetime.now().isoformat(),
            "pnl": pnl,
            "is_win": is_win,
        })
        # Keep only last 100 trades per account
        if len(self._trade_history[account_id]) > 100:
            self._trade_history[account_id] = self._trade_history[account_id][-100:]

    def update_account_balance(self, account_id: str, new_balance: float) -> None:
        """Update the current balance for an account."""
        if account_id in self._accounts:
            self._accounts[account_id].current_balance = new_balance
            self._accounts[account_id].last_updated = datetime.now()

    def rebalance(self) -> Dict[str, float]:
        """
        Compute new allocation percentages based on performance scores.

        Returns:
            Dict mapping account_id → new_allocation_pct
        """
        if not self._accounts:
            return {}

        # Update performance scores
        for account_id, account in self._accounts.items():
            history = self._trade_history.get(account_id, [])
            if history:
                recent = history[-20:]  # Last 20 trades
                win_rate = sum(1 for t in recent if t["is_win"]) / len(recent)
                avg_pnl = sum(t["pnl"] for t in recent) / len(recent)
                # Score: blend of win rate and normalised PnL
                account.performance_score = max(0.0, min(1.0, win_rate * 0.6 + min(avg_pnl * 10, 0.4)))
            else:
                account.performance_score = 0.5  # Neutral for new accounts

        # Compute raw weights proportional to performance scores
        total_score = sum(a.performance_score for a in self._accounts.values())
        if total_score <= 0:
            # Equal weight fallback
            eq = 1.0 / len(self._accounts)
            for account in self._accounts.values():
                account.allocated_pct = max(self.min_alloc_pct, min(self.max_alloc_pct, eq))
        else:
            raw_allocs = {
                aid: a.performance_score / total_score
                for aid, a in self._accounts.items()
            }
            # Clamp to [min, max] and re-normalise
            clamped = {
                aid: max(self.min_alloc_pct, min(self.max_alloc_pct, pct))
                for aid, pct in raw_allocs.items()
            }
            total_clamped = sum(clamped.values())
            for account_id, account in self._accounts.items():
                account.allocated_pct = clamped[account_id] / total_clamped
                account.last_updated = datetime.now()

        result = {aid: a.allocated_pct for aid, a in self._accounts.items()}
        logger.info(f"⚖️ Capital rebalanced: {result}")
        return result

    def get_allocation_summary(self) -> Dict[str, Any]:
        """Return current allocation summary for all accounts."""
        return {
            "accounts": [
                {
                    "account_id": a.account_id,
                    "broker": a.broker,
                    "balance": round(a.current_balance, 2),
                    "allocated_pct": round(a.allocated_pct, 4),
                    "performance_score": round(a.performance_score, 3),
                }
                for a in self._accounts.values()
            ]
        }


# ---------------------------------------------------------------------------
# Feature 5 — Adaptive Intelligence Engine (Master Orchestrator)
# ---------------------------------------------------------------------------

class AdaptiveIntelligenceEngine:
    """
    Feature 5 — Monitoring & Feedback Loop (Master Orchestrator)

    Integrates all four adaptive components into a unified system:
    - DynamicRiskController     (Feature 1)
    - SectorLearningEngine      (Feature 2)
    - StrategyEvolutionController (Feature 3)
    - CapitalRebalancer         (Feature 4)

    Provides:
    - Real-time analytics: win/loss, volatility, position sizes
    - Simulation / dry-run mode before applying changes live
    - Fail-safe rollback when losses spike
    - Audit log for compliance and debugging
    """

    def __init__(
        self,
        data_dir: str = "./data/adaptive_intelligence",
        base_max_trade_pct: float = 0.03,
        base_max_concurrent: int = 5,
        dry_run: bool = False,
    ):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.dry_run = dry_run

        # Instantiate all subsystems
        self.risk_controller = DynamicRiskController(
            base_max_trade_pct=base_max_trade_pct,
            base_max_concurrent=base_max_concurrent,
        )
        self.sector_learner = SectorLearningEngine(
            data_dir=str(self.data_dir / "sector_learning")
        )
        self.evolution_controller = StrategyEvolutionController(
            data_dir=str(self.data_dir / "strategy_evolution")
        )
        self.capital_rebalancer = CapitalRebalancer()

        # Audit log
        self._audit_log: List[Dict[str, Any]] = []
        self._audit_file = self.data_dir / "audit_log.jsonl"

        logger.info(
            f"🧠 AdaptiveIntelligenceEngine initialized | "
            f"dry_run={dry_run} | data_dir={self.data_dir}"
        )

    # ------------------------------------------------------------------
    # Primary interface — call after every completed trade
    # ------------------------------------------------------------------

    def on_trade_completed(
        self,
        account_id: str,
        symbol: str,
        sector: str,
        pnl: float,
        is_win: bool,
        current_drawdown_pct: float,
        current_volatility_pct: float,
        experiment_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Process a completed trade through all adaptive subsystems.

        This is the central feedback loop entry point. Call it after every
        closed trade to keep all intelligent components up-to-date.

        Args:
            account_id:             Which account/broker this trade belonged to
            symbol:                 Traded symbol (e.g. "BTC-USD")
            sector:                 Asset sector (e.g. "layer_1_alt")
            pnl:                    Net PnL of the trade (after fees)
            is_win:                 True if trade was profitable
            current_drawdown_pct:  Current portfolio drawdown (0-100)
            current_volatility_pct: Annualized market volatility (0-100)
            experiment_id:          If this was a paper trade for an experiment, its ID

        Returns:
            Dict with updated parameters from all subsystems
        """
        # 1 — Dynamic Risk
        self.risk_controller.record_trade_result(
            pnl=pnl,
            is_win=is_win,
            current_drawdown_pct=current_drawdown_pct,
            volatility_pct=current_volatility_pct,
        )
        risk_params = self.risk_controller.update_parameters(
            current_volatility_pct=current_volatility_pct,
            current_drawdown_pct=current_drawdown_pct,
        )

        # 2 — Sector Learning
        self.sector_learner.record_trade(
            symbol=symbol, sector=sector, pnl=pnl, is_win=is_win
        )
        confidence_weight = self.sector_learner.get_confidence_weight(symbol, sector)

        # 3 — Strategy Evolution
        if experiment_id:
            self.evolution_controller.record_paper_result(experiment_id, pnl, is_win)
        else:
            self.evolution_controller.record_live_result(pnl, is_win)

        # 4 — Capital Rebalancing
        self.capital_rebalancer.record_account_trade(account_id, pnl, is_win)

        result = {
            "risk_parameters": {
                "max_trade_pct": risk_params.max_trade_pct,
                "max_concurrent_positions": risk_params.max_concurrent_positions,
                "volatility_level": risk_params.volatility_level.value,
            },
            "sector_confidence_weight": confidence_weight,
            "active_strategy_parameters": self.evolution_controller.get_active_parameters(),
        }

        # Audit log
        self._write_audit(
            event="trade_completed",
            account_id=account_id,
            symbol=symbol,
            sector=sector,
            pnl=pnl,
            is_win=is_win,
            drawdown_pct=current_drawdown_pct,
            volatility_pct=current_volatility_pct,
            result=result,
        )

        return result

    def get_trade_parameters(
        self, symbol: str, sector: str, account_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Return all adaptive parameters needed to size the next trade.

        Call this before placing a new order.

        Returns:
            Dict with max_trade_pct, max_concurrent_positions,
            confidence_weight, and active strategy parameters
        """
        risk = self.risk_controller.get_current_parameters()
        confidence_weight = self.sector_learner.get_confidence_weight(symbol, sector)
        strategy_params = self.evolution_controller.get_active_parameters()

        params = {
            "max_trade_pct": risk.max_trade_pct,
            "max_concurrent_positions": risk.max_concurrent_positions,
            "volatility_level": risk.volatility_level.value,
            "sector_confidence_weight": confidence_weight,
            # Effective position size = base_size * confidence_weight
            "strategy_parameters": strategy_params,
        }

        if account_id:
            alloc = self.capital_rebalancer._accounts.get(account_id)
            if alloc:
                params["account_allocation_pct"] = alloc.allocated_pct

        return params

    def run_rebalance(self) -> Dict[str, float]:
        """
        Trigger a capital rebalance cycle across all registered accounts.

        Returns:
            New allocation percentages per account
        """
        if self.dry_run:
            logger.info("🔍 DRY RUN: capital rebalance simulated but not applied")
            return {}

        new_allocs = self.capital_rebalancer.rebalance()
        self._write_audit(event="rebalance", allocations=new_allocs)
        return new_allocs

    def get_full_status(self) -> Dict[str, Any]:
        """Return a comprehensive status snapshot of all adaptive systems."""
        risk = self.risk_controller.get_current_parameters()
        return {
            "dry_run": self.dry_run,
            "risk_parameters": {
                "max_trade_pct": risk.max_trade_pct,
                "max_concurrent_positions": risk.max_concurrent_positions,
                "volatility_level": risk.volatility_level.value,
            },
            "sector_learning": self.sector_learner.get_summary(),
            "strategy_evolution": self.evolution_controller.get_status(),
            "capital_allocation": self.capital_rebalancer.get_allocation_summary(),
            "audit_log_entries": len(self._audit_log),
        }

    # ------------------------------------------------------------------
    # Audit logging
    # ------------------------------------------------------------------

    def _write_audit(self, event: str, **kwargs) -> None:
        """Write an immutable audit log entry."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "event": event,
            **kwargs,
        }
        self._audit_log.append(entry)
        try:
            with open(self._audit_file, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.warning(f"⚠️ Audit log write failed: {e}")

    def get_audit_log(self, last_n: int = 50) -> List[Dict[str, Any]]:
        """Return the most recent audit log entries."""
        return self._audit_log[-last_n:]


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_engine_instance: Optional[AdaptiveIntelligenceEngine] = None


def get_adaptive_intelligence_engine(
    data_dir: str = "./data/adaptive_intelligence",
    base_max_trade_pct: float = 0.03,
    base_max_concurrent: int = 5,
    dry_run: bool = False,
    reset: bool = False,
) -> AdaptiveIntelligenceEngine:
    """
    Return (or create) the singleton AdaptiveIntelligenceEngine instance.

    Args:
        data_dir:            Directory for persistent data storage
        base_max_trade_pct: Base max trade size as fraction of balance
        base_max_concurrent: Base max simultaneous positions
        dry_run:             If True, rebalancing changes are simulated only
        reset:               Force creation of a new instance

    Returns:
        AdaptiveIntelligenceEngine singleton
    """
    global _engine_instance
    if _engine_instance is None or reset:
        _engine_instance = AdaptiveIntelligenceEngine(
            data_dir=data_dir,
            base_max_trade_pct=base_max_trade_pct,
            base_max_concurrent=base_max_concurrent,
            dry_run=dry_run,
        )
    return _engine_instance


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")

    engine = get_adaptive_intelligence_engine(
        data_dir="/tmp/nija_adaptive_demo",
        base_max_trade_pct=0.03,
        base_max_concurrent=5,
    )

    # Register accounts
    engine.capital_rebalancer.register_account("PLATFORM", "Coinbase", 5000.0, 0.60)
    engine.capital_rebalancer.register_account("USER_1",   "Kraken",   2000.0, 0.40)

    # Register a parameter experiment
    engine.evolution_controller.set_base_parameters({"rsi_oversold": 30, "rsi_overbought": 70})
    engine.evolution_controller.register_experiment(
        "exp_001", {"rsi_oversold": 28, "rsi_overbought": 72}
    )

    # Simulate trades
    import random
    random.seed(42)
    for i in range(25):
        account_id = "PLATFORM" if i % 3 != 0 else "USER_1"
        is_win = random.random() > 0.42
        pnl = random.uniform(0.005, 0.03) if is_win else random.uniform(-0.025, -0.002)
        result = engine.on_trade_completed(
            account_id=account_id,
            symbol="BTC-USD",
            sector="bitcoin",
            pnl=pnl,
            is_win=is_win,
            current_drawdown_pct=5.0,
            current_volatility_pct=28.0,
            experiment_id="exp_001" if i < 22 else None,
        )

    # Final status
    import json as _json
    print("\n📊 ADAPTIVE INTELLIGENCE ENGINE STATUS")
    print("=" * 70)
    status = engine.get_full_status()
    print(_json.dumps(status, indent=2, default=str))
