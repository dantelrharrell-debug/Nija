"""
NIJA Self-Optimization Engine
==============================

Closes the AI feedback loop so the system improves itself without human
intervention:

    Strategy performance analyzed
        → AI adjusts parameters automatically
            → system improves itself

Flow
----
1. **Analyze** – read live StrategyMetrics from StrategyPerformanceTracker.
2. **Diagnose** – score each metric against configurable thresholds and derive
   a list of *findings* (what is wrong and by how much).
3. **Prescribe** – map each finding to one or more parameter adjustments using
   conservative, bounded rules so the engine can never push parameters into
   dangerous territory.
4. **Apply** – write the merged parameter patch to the active config and
   persist the full adjustment history to disk so every decision is auditable.
5. **Evaluate** – after N additional trades the engine measures whether the
   last adjustment actually improved things; if not, it rolls back.

Key design principles
---------------------
* **Safety first** – every parameter has hard min/max bounds that are never
  crossed, regardless of what the analysis suggests.
* **Incremental changes** – adjustments are small (typically ≤10 % per cycle)
  to prevent overcorrection.
* **Fully autonomous** – no human approval step; the engine monitors, decides,
  and acts on its own schedule.
* **Auditable** – every decision is logged and persisted with timestamps,
  metrics snapshot, and the exact delta applied.

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

import json
import logging
import math
from copy import deepcopy
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.self_optimization")

# ---------------------------------------------------------------------------
# Parameter space – every tunable knob with its safe bounds
# ---------------------------------------------------------------------------

PARAMETER_SPACE: Dict[str, Dict[str, Any]] = {
    # Entry quality filters
    "min_signal_score": {
        "default": 4,
        "min": 2,
        "max": 6,
        "step": 1,
        "description": "Minimum signal confirmations required for entry (out of 6)",
    },
    "min_confidence": {
        "default": 0.60,
        "min": 0.40,
        "max": 0.85,
        "step": 0.05,
        "description": "Minimum trade-confidence threshold (0–1)",
    },
    # Trend-strength filter
    "adx_threshold": {
        "default": 10,
        "min": 6,
        "max": 25,
        "step": 2,
        "description": "Minimum ADX for a tradeable trend",
    },
    # Volume gate
    "volume_threshold": {
        "default": 0.10,
        "min": 0.05,
        "max": 0.50,
        "step": 0.05,
        "description": "Minimum volume vs recent average",
    },
    # RSI zones
    "rsi_bullish_min": {
        "default": 40,
        "min": 30,
        "max": 55,
        "step": 5,
        "description": "Lower bound of the RSI bullish zone",
    },
    "rsi_bullish_max": {
        "default": 70,
        "min": 60,
        "max": 80,
        "step": 5,
        "description": "Upper bound of the RSI bullish zone",
    },
    # Position sizing & risk
    "base_position_pct": {
        "default": 0.05,
        "min": 0.01,
        "max": 0.15,
        "step": 0.01,
        "description": "Base position size as fraction of account equity",
    },
    "stop_loss_pct": {
        "default": 0.02,
        "min": 0.005,
        "max": 0.05,
        "step": 0.005,
        "description": "Base stop-loss distance as fraction of entry price",
    },
    "profit_target_pct": {
        "default": 0.04,
        "min": 0.01,
        "max": 0.10,
        "step": 0.005,
        "description": "Primary profit-target distance as fraction of entry price",
    },
}

# ---------------------------------------------------------------------------
# Thresholds that drive diagnostic decisions
# ---------------------------------------------------------------------------

PERFORMANCE_THRESHOLDS: Dict[str, Any] = {
    # Win-rate bands
    "win_rate_excellent": 0.60,
    "win_rate_good": 0.50,
    "win_rate_poor": 0.45,
    "win_rate_critical": 0.38,
    # Profit-factor bands
    "profit_factor_excellent": 2.0,
    "profit_factor_good": 1.4,
    "profit_factor_poor": 1.1,
    "profit_factor_critical": 1.0,
    # Sharpe-ratio bands
    "sharpe_excellent": 1.5,
    "sharpe_good": 0.8,
    "sharpe_poor": 0.3,
    "sharpe_critical": 0.0,
    # Max drawdown (as % of peak equity)
    "drawdown_excellent": 5.0,
    "drawdown_acceptable": 10.0,
    "drawdown_warning": 15.0,
    "drawdown_critical": 20.0,
    # Minimum sample size before making any changes
    "min_trades_for_adjustment": 20,
}

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    """A single performance issue identified during analysis."""

    metric: str
    current_value: float
    threshold: float
    severity: str  # "info" | "warning" | "critical"
    message: str


@dataclass
class ParameterAdjustment:
    """A single parameter change recommended by the engine."""

    parameter: str
    old_value: float
    new_value: float
    delta: float
    reason: str


@dataclass
class OptimizationCycle:
    """Complete record of one optimization cycle."""

    cycle_id: str
    timestamp: str
    strategy: str
    trades_analyzed: int
    metrics_snapshot: Dict[str, float]
    findings: List[Finding]
    adjustments: List[ParameterAdjustment]
    parameters_before: Dict[str, float]
    parameters_after: Dict[str, float]
    # Filled in after evaluation
    evaluation_trades: int = 0
    evaluation_score_before: float = 0.0
    evaluation_score_after: float = 0.0
    improvement_pct: float = 0.0
    rolled_back: bool = False
    notes: str = ""


# ---------------------------------------------------------------------------
# Performance analyzer
# ---------------------------------------------------------------------------


class PerformanceAnalyzer:
    """
    Reads StrategyMetrics and converts them into a list of actionable Findings.
    """

    def analyze(self, metrics: Any, strategy: str) -> List[Finding]:
        """
        Analyse a StrategyMetrics object and return a prioritised list of
        Findings.

        Args:
            metrics: StrategyMetrics instance from strategy_performance.py.
            strategy: Strategy name (for logging context).

        Returns:
            List of Finding objects, most severe first.
        """
        findings: List[Finding] = []
        t = PERFORMANCE_THRESHOLDS

        if metrics.total_trades < t["min_trades_for_adjustment"]:
            logger.info(
                "📊 [%s] Only %d trades – need %d before adjustments",
                strategy,
                metrics.total_trades,
                t["min_trades_for_adjustment"],
            )
            return findings

        # --- Win rate ---
        wr = metrics.win_rate
        if wr < t["win_rate_critical"]:
            findings.append(
                Finding(
                    metric="win_rate",
                    current_value=wr,
                    threshold=t["win_rate_critical"],
                    severity="critical",
                    message=f"Win rate {wr:.1%} is critically low (<{t['win_rate_critical']:.0%}). "
                    "Tighten entry criteria.",
                )
            )
        elif wr < t["win_rate_poor"]:
            findings.append(
                Finding(
                    metric="win_rate",
                    current_value=wr,
                    threshold=t["win_rate_poor"],
                    severity="warning",
                    message=f"Win rate {wr:.1%} is below target ({t['win_rate_poor']:.0%}).",
                )
            )

        # --- Profit factor ---
        pf = metrics.profit_factor
        if pf != float("inf") and pf < t["profit_factor_critical"]:
            findings.append(
                Finding(
                    metric="profit_factor",
                    current_value=pf,
                    threshold=t["profit_factor_critical"],
                    severity="critical",
                    message=f"Profit factor {pf:.2f} ≤ 1.0: strategy is losing money.",
                )
            )
        elif pf != float("inf") and pf < t["profit_factor_poor"]:
            findings.append(
                Finding(
                    metric="profit_factor",
                    current_value=pf,
                    threshold=t["profit_factor_poor"],
                    severity="warning",
                    message=f"Profit factor {pf:.2f} is below healthy level ({t['profit_factor_poor']:.1f}).",
                )
            )

        # --- Sharpe ratio ---
        sr = metrics.sharpe_ratio
        if sr < t["sharpe_critical"]:
            findings.append(
                Finding(
                    metric="sharpe_ratio",
                    current_value=sr,
                    threshold=t["sharpe_critical"],
                    severity="critical",
                    message=f"Sharpe ratio {sr:.3f} is negative – risk-adjusted returns are poor.",
                )
            )
        elif sr < t["sharpe_poor"]:
            findings.append(
                Finding(
                    metric="sharpe_ratio",
                    current_value=sr,
                    threshold=t["sharpe_poor"],
                    severity="warning",
                    message=f"Sharpe ratio {sr:.3f} is below healthy level ({t['sharpe_poor']:.1f}).",
                )
            )

        # --- Max drawdown ---
        dd = metrics.max_drawdown_pct
        if dd >= t["drawdown_critical"]:
            findings.append(
                Finding(
                    metric="max_drawdown_pct",
                    current_value=dd,
                    threshold=t["drawdown_critical"],
                    severity="critical",
                    message=f"Max drawdown {dd:.1f}% exceeds critical limit ({t['drawdown_critical']:.0f}%). "
                    "Reduce position size.",
                )
            )
        elif dd >= t["drawdown_warning"]:
            findings.append(
                Finding(
                    metric="max_drawdown_pct",
                    current_value=dd,
                    threshold=t["drawdown_warning"],
                    severity="warning",
                    message=f"Max drawdown {dd:.1f}% exceeds warning level ({t['drawdown_warning']:.0f}%).",
                )
            )

        # Sort: critical first
        findings.sort(key=lambda f: {"critical": 0, "warning": 1, "info": 2}[f.severity])
        return findings


# ---------------------------------------------------------------------------
# Parameter adjuster
# ---------------------------------------------------------------------------


class ParameterAdjuster:
    """
    Converts a list of Findings into concrete ParameterAdjustments,
    always staying within the safe bounds defined in PARAMETER_SPACE.
    """

    def prescribe(
        self,
        findings: List[Finding],
        current_params: Dict[str, float],
        metrics: Any,
    ) -> List[ParameterAdjustment]:
        """
        Derive conservative parameter adjustments from the findings.

        Args:
            findings: Ordered list of Findings (critical first).
            current_params: Current active parameter values.
            metrics: StrategyMetrics for additional context.

        Returns:
            List of ParameterAdjustment objects.
        """
        adjustments: List[ParameterAdjustment] = []
        applied: set = set()  # avoid double-adjusting the same parameter

        def _adjust(param: str, direction: int, multiplier: float = 1.0) -> Optional[ParameterAdjustment]:
            """
            Move *param* by one step in *direction* (+1 = increase, -1 = decrease).
            *multiplier* scales the step size (use 2.0 for critical findings).
            """
            if param in applied:
                return None
            spec = PARAMETER_SPACE.get(param)
            if spec is None:
                return None
            old = current_params.get(param, spec["default"])
            step = spec["step"] * multiplier
            new = old + direction * step
            new = max(spec["min"], min(spec["max"], new))
            new = round(new, 6)
            if new == old:
                return None
            adj = ParameterAdjustment(
                parameter=param,
                old_value=old,
                new_value=new,
                delta=new - old,
                reason="",
            )
            applied.add(param)
            return adj

        for finding in findings:
            severity_mult = 2.0 if finding.severity == "critical" else 1.0

            if finding.metric == "win_rate":
                # Raise entry bar to improve quality
                adj = _adjust("min_signal_score", +1, severity_mult)
                if adj:
                    adj.reason = finding.message
                    adjustments.append(adj)
                adj = _adjust("min_confidence", +1, severity_mult)
                if adj:
                    adj.reason = finding.message
                    adjustments.append(adj)

            elif finding.metric == "profit_factor":
                # Widen profit target and tighten stops
                adj = _adjust("profit_target_pct", +1, severity_mult)
                if adj:
                    adj.reason = finding.message
                    adjustments.append(adj)
                adj = _adjust("stop_loss_pct", -1, severity_mult)
                if adj:
                    adj.reason = finding.message
                    adjustments.append(adj)

            elif finding.metric == "sharpe_ratio":
                # Reduce volatility exposure: tighter entry + smaller size
                adj = _adjust("adx_threshold", +1, severity_mult)
                if adj:
                    adj.reason = finding.message
                    adjustments.append(adj)
                adj = _adjust("base_position_pct", -1, severity_mult)
                if adj:
                    adj.reason = finding.message
                    adjustments.append(adj)

            elif finding.metric == "max_drawdown_pct":
                # Shrink positions and tighten stops
                adj = _adjust("base_position_pct", -1, severity_mult)
                if adj:
                    adj.reason = finding.message
                    adjustments.append(adj)
                adj = _adjust("stop_loss_pct", -1, 0.5)  # gentler stop tightening
                if adj:
                    adj.reason = finding.message
                    adjustments.append(adj)

        # If everything looks good (no findings), try small improvements
        if not findings and metrics.total_trades >= PERFORMANCE_THRESHOLDS["min_trades_for_adjustment"]:
            wr = metrics.win_rate
            if wr >= PERFORMANCE_THRESHOLDS["win_rate_excellent"]:
                adj = _adjust("base_position_pct", +1, 0.5)  # slowly increase size when winning
                if adj:
                    adj.reason = f"Excellent win rate {wr:.1%} – gently increasing position size."
                    adjustments.append(adj)

        return adjustments


# ---------------------------------------------------------------------------
# Self-optimization engine
# ---------------------------------------------------------------------------


class SelfOptimizationEngine:
    """
    Orchestrates the full self-improvement feedback loop:

    Strategy performance analyzed
        → AI adjusts parameters automatically
            → system improves itself

    Usage
    -----
    .. code-block:: python

        engine = SelfOptimizationEngine()

        # Call after every N trades (e.g., from the main trading loop)
        result = engine.run_cycle("apex_v71")
        if result:
            # Apply result.parameters_after to the active strategy
            active_params.update(result.parameters_after)
    """

    STATE_DIR = Path(__file__).parent.parent / "data"
    STATE_FILE = STATE_DIR / "self_optimization_state.json"

    # Minimum trades between successive optimization cycles for the same strategy
    MIN_TRADES_BETWEEN_CYCLES = 30

    # Trades to wait before evaluating whether the last cycle was beneficial
    EVALUATION_TRADES = 20

    def __init__(self, state_dir: Optional[str] = None):
        if state_dir:
            self.STATE_DIR = Path(state_dir)
            self.STATE_FILE = self.STATE_DIR / "self_optimization_state.json"
        self.STATE_DIR.mkdir(parents=True, exist_ok=True)

        self._analyzer = PerformanceAnalyzer()
        self._adjuster = ParameterAdjuster()

        # Keyed by strategy name
        self._active_params: Dict[str, Dict[str, float]] = {}
        self._cycle_history: List[OptimizationCycle] = []
        self._last_cycle_trade_count: Dict[str, int] = {}

        self._load_state()
        logger.info("🤖 SelfOptimizationEngine initialized — %d strategies tracked", len(self._active_params))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_active_parameters(self, strategy: str) -> Dict[str, float]:
        """
        Return the current AI-optimized parameters for *strategy*.

        If no adjustments have been made yet, returns the defaults from
        PARAMETER_SPACE.

        Args:
            strategy: Strategy identifier (e.g. ``"apex_v71"``).

        Returns:
            Dict of parameter_name → value.
        """
        if strategy not in self._active_params:
            self._active_params[strategy] = self._default_params()
        return deepcopy(self._active_params[strategy])

    def run_cycle(self, strategy: str, performance_tracker: Any = None) -> Optional[OptimizationCycle]:
        """
        Execute one full optimize cycle for *strategy*.

        Steps:
        1. Fetch latest StrategyMetrics.
        2. Analyse metrics → Findings.
        3. Convert Findings → ParameterAdjustments.
        4. Apply adjustments to the active parameter set.
        5. Persist state and return the cycle record.

        Args:
            strategy: Strategy identifier.
            performance_tracker: Optional ``StrategyPerformanceTracker``
                instance.  If *None*, the module-level singleton is used.

        Returns:
            ``OptimizationCycle`` if adjustments were made, ``None`` otherwise.
        """
        tracker = self._get_tracker(performance_tracker)
        if tracker is None:
            logger.warning("⚠️  No performance tracker available – skipping cycle")
            return None

        metrics = tracker.get_metrics(strategy)

        # Rate-limit: only optimize after enough new trades have accumulated
        last_count = self._last_cycle_trade_count.get(strategy, 0)
        if metrics.total_trades - last_count < self.MIN_TRADES_BETWEEN_CYCLES:
            logger.debug(
                "⏳ [%s] %d trades since last cycle (need %d) – skipping",
                strategy,
                metrics.total_trades - last_count,
                self.MIN_TRADES_BETWEEN_CYCLES,
            )
            return None

        logger.info("🔬 [%s] Running self-optimization cycle (%d trades)", strategy, metrics.total_trades)

        # 1. Analyze
        findings = self._analyzer.analyze(metrics, strategy)

        # 2. Prescribe
        current_params = self.get_active_parameters(strategy)
        adjustments = self._adjuster.prescribe(findings, current_params, metrics)

        cycle_id = f"{strategy}_{datetime.now().strftime('%Y%m%dT%H%M%S')}"

        if not adjustments:
            logger.info("✅ [%s] No adjustments needed – strategy performing well", strategy)
            # Still record the cycle for auditing, just without changes
            cycle = OptimizationCycle(
                cycle_id=cycle_id,
                timestamp=datetime.now().isoformat(),
                strategy=strategy,
                trades_analyzed=metrics.total_trades,
                metrics_snapshot=self._metrics_to_dict(metrics),
                findings=findings,
                adjustments=[],
                parameters_before=current_params,
                parameters_after=current_params,
                notes="No adjustments required.",
            )
            self._cycle_history.append(cycle)
            self._last_cycle_trade_count[strategy] = metrics.total_trades
            self._save_state()
            return cycle

        # 3. Apply
        new_params = deepcopy(current_params)
        for adj in adjustments:
            new_params[adj.parameter] = adj.new_value

        cycle = OptimizationCycle(
            cycle_id=cycle_id,
            timestamp=datetime.now().isoformat(),
            strategy=strategy,
            trades_analyzed=metrics.total_trades,
            metrics_snapshot=self._metrics_to_dict(metrics),
            findings=findings,
            adjustments=adjustments,
            parameters_before=current_params,
            parameters_after=new_params,
        )

        self._active_params[strategy] = new_params
        self._cycle_history.append(cycle)
        self._last_cycle_trade_count[strategy] = metrics.total_trades

        self._log_cycle_summary(cycle)
        self._save_state()
        return cycle

    def evaluate_last_cycle(self, strategy: str, performance_tracker: Any = None) -> Optional[OptimizationCycle]:
        """
        After EVALUATION_TRADES new trades have been completed, compare
        performance before and after the last cycle.  If things got worse,
        automatically roll back to the prior parameters.

        Args:
            strategy: Strategy identifier.
            performance_tracker: Optional tracker instance.

        Returns:
            Updated OptimizationCycle record, or *None* if there is nothing to
            evaluate.
        """
        # Find last unevaluated cycle with actual adjustments
        cycle = self._last_unevaluated_cycle(strategy)
        if cycle is None:
            return None

        tracker = self._get_tracker(performance_tracker)
        if tracker is None:
            return None

        metrics = tracker.get_metrics(strategy)
        new_trades = metrics.total_trades - cycle.trades_analyzed

        if new_trades < self.EVALUATION_TRADES:
            logger.debug(
                "⏳ [%s] Evaluation needs %d more trades (%d so far)",
                strategy,
                self.EVALUATION_TRADES - new_trades,
                new_trades,
            )
            return None

        score_before = self._score(cycle.metrics_snapshot)
        score_after = self._score(self._metrics_to_dict(metrics))
        improvement = ((score_after - score_before) / max(abs(score_before), 1e-9)) * 100

        cycle.evaluation_trades = new_trades
        cycle.evaluation_score_before = score_before
        cycle.evaluation_score_after = score_after
        cycle.improvement_pct = improvement

        if improvement < -5.0:  # performance dropped by more than 5 %
            logger.warning(
                "⚠️  [%s] Last cycle made things worse (%.1f%%) – rolling back parameters",
                strategy,
                improvement,
            )
            self._active_params[strategy] = deepcopy(cycle.parameters_before)
            cycle.rolled_back = True
            cycle.notes = f"Auto-rolled back: performance dropped {abs(improvement):.1f}%."
        else:
            logger.info(
                "✅ [%s] Cycle evaluation: improvement=%.1f%% – keeping adjusted parameters",
                strategy,
                improvement,
            )
            cycle.notes = f"Confirmed: improvement={improvement:.1f}%."

        self._save_state()
        return cycle

    def get_optimization_history(self, strategy: Optional[str] = None) -> List[OptimizationCycle]:
        """
        Return the history of optimization cycles.

        Args:
            strategy: If provided, filter to cycles for this strategy only.

        Returns:
            List of OptimizationCycle records, newest first.
        """
        history = self._cycle_history
        if strategy:
            history = [c for c in history if c.strategy == strategy]
        return list(reversed(history))

    def generate_summary(self, strategy: Optional[str] = None) -> str:
        """
        Generate a human-readable summary of all optimization activity.

        Args:
            strategy: Optional filter.

        Returns:
            Formatted text report.
        """
        history = self.get_optimization_history(strategy)
        label = strategy or "ALL STRATEGIES"
        lines = [
            "",
            "=" * 80,
            f"🤖  NIJA SELF-OPTIMIZATION ENGINE — SUMMARY ({label})",
            "=" * 80,
        ]

        if not history:
            lines.append("  No optimization cycles recorded yet.")
            lines.append("=" * 80)
            return "\n".join(lines)

        for cycle in history[:20]:  # show last 20
            status = "↩️  ROLLED BACK" if cycle.rolled_back else ("🔧 ADJUSTED" if cycle.adjustments else "✅ NO CHANGE")
            lines.append(
                f"\n  [{cycle.timestamp[:19]}]  {cycle.strategy}  —  {status}"
            )
            lines.append(f"     Trades analyzed : {cycle.trades_analyzed}")
            if cycle.findings:
                lines.append(f"     Findings        : {len(cycle.findings)}")
                for f in cycle.findings:
                    lines.append(f"       • [{f.severity.upper()}] {f.message}")
            if cycle.adjustments:
                lines.append(f"     Adjustments     : {len(cycle.adjustments)}")
                for adj in cycle.adjustments:
                    arrow = "↑" if adj.delta > 0 else "↓"
                    lines.append(
                        f"       • {adj.parameter}: {adj.old_value} → {adj.new_value} ({arrow}{abs(adj.delta):.4g})"
                    )
            if cycle.evaluation_trades:
                lines.append(
                    f"     Evaluation      : {cycle.improvement_pct:+.1f}% improvement "
                    f"over {cycle.evaluation_trades} trades"
                )
            if cycle.notes:
                lines.append(f"     Notes           : {cycle.notes}")

        lines.append("")
        lines.append("=" * 80)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _default_params() -> Dict[str, float]:
        """Return a copy of all parameters at their default values."""
        return {k: v["default"] for k, v in PARAMETER_SPACE.items()}

    @staticmethod
    def _get_tracker(tracker: Any) -> Any:
        """Return *tracker* if provided, otherwise fall back to singleton."""
        if tracker is not None:
            return tracker
        try:
            from bot.strategy_performance import get_strategy_performance_tracker
            return get_strategy_performance_tracker()
        except ImportError:
            try:
                from strategy_performance import get_strategy_performance_tracker
                return get_strategy_performance_tracker()
            except ImportError:
                return None

    @staticmethod
    def _metrics_to_dict(metrics: Any) -> Dict[str, float]:
        """Extract key numeric fields from a StrategyMetrics instance."""
        keys = [
            "win_rate", "profit_factor", "sharpe_ratio", "calmar_ratio",
            "max_drawdown", "max_drawdown_pct", "total_pnl", "expectancy",
            "total_trades",
        ]
        result: Dict[str, float] = {}
        for k in keys:
            val = getattr(metrics, k, None)
            if val is not None and val != float("inf"):
                result[k] = float(val)
        return result

    @staticmethod
    def _score(metrics_dict: Dict[str, float]) -> float:
        """
        Compute a simple composite score from a metrics snapshot.
        Higher is better.
        """
        sr = metrics_dict.get("sharpe_ratio", 0.0)
        pf = min(metrics_dict.get("profit_factor", 1.0), 5.0)  # cap at 5
        wr = metrics_dict.get("win_rate", 0.0)
        dd = metrics_dict.get("max_drawdown_pct", 0.0)
        return (sr * 0.35) + (pf * 0.30) + (wr * 100 * 0.20) - (dd * 0.15)

    def _last_unevaluated_cycle(self, strategy: str) -> Optional[OptimizationCycle]:
        """Find the most recent cycle for *strategy* that hasn't been evaluated yet."""
        for cycle in reversed(self._cycle_history):
            if cycle.strategy == strategy and cycle.adjustments and not cycle.evaluation_trades:
                return cycle
        return None

    def _log_cycle_summary(self, cycle: OptimizationCycle) -> None:
        logger.info("🔧 [%s] Optimization cycle %s applied %d adjustment(s):", cycle.strategy, cycle.cycle_id, len(cycle.adjustments))
        for adj in cycle.adjustments:
            arrow = "↑" if adj.delta > 0 else "↓"
            logger.info(
                "   • %-25s %s %s → %s  (reason: %s)",
                adj.parameter,
                arrow,
                adj.old_value,
                adj.new_value,
                adj.reason[:80],
            )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_state(self) -> None:
        def _serialise_cycle(c: OptimizationCycle) -> Dict:
            d = {
                "cycle_id": c.cycle_id,
                "timestamp": c.timestamp,
                "strategy": c.strategy,
                "trades_analyzed": c.trades_analyzed,
                "metrics_snapshot": c.metrics_snapshot,
                "findings": [asdict(f) for f in c.findings],
                "adjustments": [asdict(a) for a in c.adjustments],
                "parameters_before": c.parameters_before,
                "parameters_after": c.parameters_after,
                "evaluation_trades": c.evaluation_trades,
                "evaluation_score_before": c.evaluation_score_before,
                "evaluation_score_after": c.evaluation_score_after,
                "improvement_pct": c.improvement_pct,
                "rolled_back": c.rolled_back,
                "notes": c.notes,
            }
            return d

        try:
            state = {
                "updated_at": datetime.now().isoformat(),
                "active_params": self._active_params,
                "last_cycle_trade_count": self._last_cycle_trade_count,
                "cycle_history": [_serialise_cycle(c) for c in self._cycle_history],
            }
            with open(self.STATE_FILE, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as exc:
            logger.error("Failed to save self-optimization state: %s", exc)

    def _load_state(self) -> None:
        if not self.STATE_FILE.exists():
            return
        try:
            with open(self.STATE_FILE, "r") as f:
                state = json.load(f)

            self._active_params = state.get("active_params", {})
            self._last_cycle_trade_count = state.get("last_cycle_trade_count", {})

            for item in state.get("cycle_history", []):
                try:
                    findings = [Finding(**fi) for fi in item.get("findings", [])]
                    adjustments = [ParameterAdjustment(**a) for a in item.get("adjustments", [])]
                    cycle = OptimizationCycle(
                        cycle_id=item["cycle_id"],
                        timestamp=item["timestamp"],
                        strategy=item["strategy"],
                        trades_analyzed=item["trades_analyzed"],
                        metrics_snapshot=item.get("metrics_snapshot", {}),
                        findings=findings,
                        adjustments=adjustments,
                        parameters_before=item.get("parameters_before", {}),
                        parameters_after=item.get("parameters_after", {}),
                        evaluation_trades=item.get("evaluation_trades", 0),
                        evaluation_score_before=item.get("evaluation_score_before", 0.0),
                        evaluation_score_after=item.get("evaluation_score_after", 0.0),
                        improvement_pct=item.get("improvement_pct", 0.0),
                        rolled_back=item.get("rolled_back", False),
                        notes=item.get("notes", ""),
                    )
                    self._cycle_history.append(cycle)
                except Exception as exc:
                    logger.warning("Skipping malformed cycle record: %s", exc)

            logger.info(
                "✅ Loaded self-optimization state — %d strategies, %d cycles",
                len(self._active_params),
                len(self._cycle_history),
            )
        except Exception as exc:
            logger.warning("Could not load self-optimization state: %s", exc)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_engine: Optional[SelfOptimizationEngine] = None


def get_self_optimization_engine() -> SelfOptimizationEngine:
    """Return (or create) the module-level SelfOptimizationEngine singleton."""
    global _engine
    if _engine is None:
        _engine = SelfOptimizationEngine()
    return _engine


# ---------------------------------------------------------------------------
# CLI demo / smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import random

    logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")

    try:
        from bot.strategy_performance import StrategyPerformanceTracker, StrategyTrade
    except ImportError:
        from strategy_performance import StrategyPerformanceTracker, StrategyTrade

    tracker = StrategyPerformanceTracker()
    now = datetime.now()

    # Simulate a run of trades that has a low win rate
    for i in range(60):
        pnl = random.gauss(-1, 15)  # slightly negative expectancy → should trigger adjustments
        trade = StrategyTrade(
            trade_id=f"SOE-{i:04d}",
            strategy="apex_v71",
            symbol="BTC-USD",
            pnl=pnl,
            fees=0.4,
            entry_ts=now - timedelta(hours=i * 4),
            exit_ts=now - timedelta(hours=i * 4 - 2),
            side="long",
            market_regime="ranging",
        )
        tracker.record_trade(trade)

    engine = SelfOptimizationEngine(state_dir="/tmp/soe_demo")
    cycle = engine.run_cycle("apex_v71", tracker)

    if cycle:
        print(engine.generate_summary("apex_v71"))
        print("\n📌 Active parameters after optimization:")
        for k, v in engine.get_active_parameters("apex_v71").items():
            print(f"   {k}: {v}")
