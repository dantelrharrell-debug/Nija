"""
NIJA Phase 5 — Live Performance Tuner
======================================

Stress-test and live performance monitoring for the bot.

Provides five integrated pillars:

1. **Trade Outcome Validation** — verifies every closed trade is recorded
   correctly, that profits match expectations, and that AutoReinvestEngine
   applied the right reinvest/withdraw split.

2. **Win-Rate vs Frequency Tuning** — exposes a live-editable configuration
   for AI confidence threshold, take-profit levels, and scan speed so the
   operator can dial performance without restarting the bot.

3. **Compounding Verification** — watches AutoReinvestEngine.process_profit()
   output; confirms split fractions are correct and position-size capital
   grows monotonically over time.

4. **Risk Sanity Checker** — monitors PortfolioKillSwitch, RecoveryController,
   and ExchangeKillSwitch to confirm they are not triggering spuriously;
   also detects phantom PnL discrepancies.

5. **Phase 5 Dashboard** — Flask Blueprint at ``/phase5/dashboard`` showing
   a growing equity curve, full trade history, and reinvest vs withdraw
   breakdown.  Auto-refreshes every 15 s.

Usage
-----
    from phase5_live_performance_tuner import (
        get_phase5_tuner,
        register_phase5_dashboard,
    )

    tuner = get_phase5_tuner()

    # After every closed trade:
    tuner.record_trade_outcome(
        symbol="BTC-USD",
        gross_profit=45.0,
        fees=0.68,
        is_win=True,
        equity_after=1045.0,
        reinvest_usd=33.24,
        withdraw_usd=11.08,
    )

    # In your Flask app:
    register_phase5_dashboard(app)

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from flask import Blueprint, jsonify, render_template_string, request

logger = logging.getLogger("nija.phase5")

# ---------------------------------------------------------------------------
# Optional integrations (all fail-safe)
# ---------------------------------------------------------------------------

try:
    from auto_reinvest_engine import get_auto_reinvest_engine  # type: ignore
    _ARE_AVAILABLE = True
except ImportError:
    _ARE_AVAILABLE = False
    get_auto_reinvest_engine = None  # type: ignore[assignment]

try:
    from portfolio_kill_switch import get_portfolio_kill_switch  # type: ignore
    _PKS_AVAILABLE = True
except ImportError:
    _PKS_AVAILABLE = False
    get_portfolio_kill_switch = None  # type: ignore[assignment]

try:
    from recovery_controller import RecoveryController  # type: ignore
    _RC_AVAILABLE = True
except ImportError:
    _RC_AVAILABLE = False
    RecoveryController = None  # type: ignore[assignment]

try:
    from exchange_kill_switch import get_exchange_kill_switch_protector  # type: ignore
    _EKS_AVAILABLE = True
except ImportError:
    _EKS_AVAILABLE = False
    get_exchange_kill_switch_protector = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

_DATA_DIR = Path(os.environ.get("NIJA_DATA_DIR", "/tmp/nija_monitoring"))
_STATE_FILE = _DATA_DIR / "phase5_tuner_state.json"

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TuningConfig:
    """
    Live-editable performance tuning configuration.

    All fields can be updated at runtime via the Phase 5 API without
    restarting the bot.
    """
    ai_confidence_threshold: float = 55.0  # minimum AI score to enter a trade
    take_profit_pct: float = 2.5           # primary TP level in percent
    scan_interval_seconds: int = 150       # market scan cadence (default 2.5 min)
    min_reinvest_profit: float = 5.0       # minimum net profit for reinvest split
    reinvest_fraction: float = 0.75        # fraction of profit to reinvest
    withdraw_fraction: float = 0.25        # fraction to lock as withdrawn profit


@dataclass
class TradeOutcomeRecord:
    """One validated, closed trade outcome."""
    symbol: str
    gross_profit: float
    fees: float
    net_profit: float
    is_win: bool
    equity_after: float
    reinvest_usd: float
    withdraw_usd: float
    split_valid: bool          # True when reinvest+withdraw ≈ net_profit
    phantom_flag: bool         # True when the PnL looks unrealistic
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class Phase5State:
    """All persistent Phase 5 state."""
    trade_history: List[Dict] = field(default_factory=list)
    equity_curve: List[Dict] = field(default_factory=list)
    total_reinvested: float = 0.0
    total_withdrawn: float = 0.0
    total_profit: float = 0.0
    total_fees: float = 0.0
    trade_count: int = 0
    win_count: int = 0
    phantom_loss_count: int = 0
    kill_switch_triggers: int = 0
    recovery_blocks: int = 0
    tuning: Dict = field(default_factory=lambda: asdict(TuningConfig()))
    last_updated: Optional[str] = None


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class Phase5LivePerformanceTuner:
    """
    Phase 5 Live Performance Tuner singleton.

    Thread-safe; persists state to JSON.
    """

    MAX_HISTORY: int = 1000
    PHANTOM_MULTIPLIER: float = 10.0  # PnL > 10× account value ⇒ phantom flag

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = self._load_state()
        self._cfg = TuningConfig(**self._state.tuning)
        logger.info(
            "🚀 Phase5LivePerformanceTuner initialised | "
            "ai_threshold=%.1f tp=%.1f%% scan=%ds",
            self._cfg.ai_confidence_threshold,
            self._cfg.take_profit_pct,
            self._cfg.scan_interval_seconds,
        )

    # ------------------------------------------------------------------
    # Pillar 1: Trade Outcome Validation
    # ------------------------------------------------------------------

    def record_trade_outcome(
        self,
        symbol: str,
        gross_profit: float,
        fees: float,
        is_win: bool,
        equity_after: float,
        reinvest_usd: float = 0.0,
        withdraw_usd: float = 0.0,
    ) -> TradeOutcomeRecord:
        """
        Validate and record a closed trade.

        Parameters
        ----------
        symbol:
            Trading pair, e.g. ``"BTC-USD"``.
        gross_profit:
            Pre-fee P&L in USD (may be negative).
        fees:
            Transaction costs in USD (always positive).
        is_win:
            ``True`` when the trade closed in profit.
        equity_after:
            Total account equity immediately after the close.
        reinvest_usd:
            Amount returned to trading capital by AutoReinvestEngine.
        withdraw_usd:
            Amount locked as withdrawn profit.

        Returns
        -------
        TradeOutcomeRecord
        """
        net_profit = gross_profit - fees

        # Validate reinvest split (allow ≤$0.02 rounding / float-precision tolerance)
        split_sum = reinvest_usd + withdraw_usd
        split_valid = abs(split_sum - net_profit) <= 0.02 or (
            net_profit < self._cfg.min_reinvest_profit and split_sum == 0.0
        )

        # Phantom loss detection: PnL that dwarfs the whole account is suspicious
        phantom_flag = (
            equity_after > 0
            and abs(gross_profit) > equity_after * self.PHANTOM_MULTIPLIER
        )
        if phantom_flag:
            logger.warning(
                "⚠️ Phantom PnL detected on %s: gross=$%.2f vs equity=$%.2f",
                symbol, gross_profit, equity_after,
            )

        record = TradeOutcomeRecord(
            symbol=symbol,
            gross_profit=gross_profit,
            fees=fees,
            net_profit=net_profit,
            is_win=is_win,
            equity_after=equity_after,
            reinvest_usd=reinvest_usd,
            withdraw_usd=withdraw_usd,
            split_valid=split_valid,
            phantom_flag=phantom_flag,
        )

        with self._lock:
            self._state.trade_count += 1
            if is_win:
                self._state.win_count += 1
            self._state.total_profit += net_profit
            self._state.total_fees += fees
            self._state.total_reinvested += reinvest_usd
            self._state.total_withdrawn += withdraw_usd
            if phantom_flag:
                self._state.phantom_loss_count += 1

            # Append to rolling history
            self._state.trade_history.append(asdict(record))
            if len(self._state.trade_history) > self.MAX_HISTORY:
                self._state.trade_history = self._state.trade_history[-self.MAX_HISTORY:]

            # Update equity curve
            self._state.equity_curve.append(
                {"timestamp": record.timestamp, "equity": equity_after}
            )
            if len(self._state.equity_curve) > self.MAX_HISTORY:
                self._state.equity_curve = self._state.equity_curve[-self.MAX_HISTORY:]

            self._state.last_updated = record.timestamp
            self._save_state()

        if not split_valid:
            logger.warning(
                "❌ Reinvest split mismatch on %s: reinvest=$%.4f + "
                "withdraw=$%.4f ≠ net=$%.4f",
                symbol, reinvest_usd, withdraw_usd, net_profit,
            )
        else:
            logger.info(
                "✅ Trade outcome validated [%s] net=$%.4f reinvest=$%.4f "
                "withdraw=$%.4f win=%s",
                symbol, net_profit, reinvest_usd, withdraw_usd, is_win,
            )

        return record

    # ------------------------------------------------------------------
    # Pillar 2: Win-Rate vs Frequency Tuning
    # ------------------------------------------------------------------

    def get_tuning_config(self) -> TuningConfig:
        """Return a copy of the current tuning configuration."""
        with self._lock:
            return TuningConfig(**asdict(self._cfg))

    def update_tuning(
        self,
        ai_confidence_threshold: Optional[float] = None,
        take_profit_pct: Optional[float] = None,
        scan_interval_seconds: Optional[int] = None,
        min_reinvest_profit: Optional[float] = None,
        reinvest_fraction: Optional[float] = None,
        withdraw_fraction: Optional[float] = None,
    ) -> TuningConfig:
        """
        Update any subset of tuning parameters at runtime.

        Parameters that are ``None`` are left unchanged.

        Returns
        -------
        TuningConfig
            The updated configuration.
        """
        with self._lock:
            if ai_confidence_threshold is not None:
                if not 0.0 <= ai_confidence_threshold <= 100.0:
                    raise ValueError("ai_confidence_threshold must be 0–100")
                self._cfg.ai_confidence_threshold = ai_confidence_threshold
            if take_profit_pct is not None:
                if take_profit_pct <= 0:
                    raise ValueError("take_profit_pct must be positive")
                self._cfg.take_profit_pct = take_profit_pct
            if scan_interval_seconds is not None:
                if scan_interval_seconds < 30:
                    raise ValueError("scan_interval_seconds must be ≥ 30")
                self._cfg.scan_interval_seconds = scan_interval_seconds
            if min_reinvest_profit is not None:
                self._cfg.min_reinvest_profit = min_reinvest_profit
            if reinvest_fraction is not None:
                if not 0.0 <= reinvest_fraction <= 1.0:
                    raise ValueError("reinvest_fraction must be 0–1")
                self._cfg.reinvest_fraction = reinvest_fraction
                self._cfg.withdraw_fraction = 1.0 - reinvest_fraction
            if withdraw_fraction is not None:
                if not 0.0 <= withdraw_fraction <= 1.0:
                    raise ValueError("withdraw_fraction must be 0–1")
                self._cfg.withdraw_fraction = withdraw_fraction
                self._cfg.reinvest_fraction = 1.0 - withdraw_fraction

            self._state.tuning = asdict(self._cfg)
            self._save_state()
            logger.info("⚙️ Tuning updated: %s", asdict(self._cfg))
            return TuningConfig(**asdict(self._cfg))

    # ------------------------------------------------------------------
    # Pillar 3: Compounding Verification
    # ------------------------------------------------------------------

    def verify_compounding(self) -> Dict[str, Any]:
        """
        Pull live data from AutoReinvestEngine and verify the compounding
        split matches the configured fractions.

        Returns a dict with verification details suitable for the dashboard.
        """
        result: Dict[str, Any] = {
            "available": _ARE_AVAILABLE,
            "split_ok": None,
            "expected_reinvest_pct": self._cfg.reinvest_fraction * 100.0,
            "expected_withdraw_pct": self._cfg.withdraw_fraction * 100.0,
            "actual_reinvest_pct": None,
            "actual_withdraw_pct": None,
            "total_processed": None,
            "win_rate": None,
            "position_size_growing": None,
            "notes": [],
        }

        if not (_ARE_AVAILABLE and get_auto_reinvest_engine):
            result["notes"].append("AutoReinvestEngine not available.")
            return result

        try:
            state = get_auto_reinvest_engine().get_state()
        except Exception as exc:
            result["notes"].append(f"Error reading AutoReinvestEngine: {exc}")
            return result

        processed = state.get("total_processed", 0.0)
        reinvested = state.get("total_reinvested", 0.0)
        withdrawn = state.get("total_withdrawn", 0.0)

        result["total_processed"] = processed
        result["win_rate"] = state.get("win_rate", 0.0)

        if processed > 0:
            actual_ri = reinvested / processed * 100.0
            actual_wd = withdrawn / processed * 100.0
            result["actual_reinvest_pct"] = round(actual_ri, 2)
            result["actual_withdraw_pct"] = round(actual_wd, 2)

            # Allow ±5 pp tolerance for rounding / capped withdrawals
            ri_ok = abs(actual_ri - self._cfg.reinvest_fraction * 100.0) <= 5.0
            wd_ok = abs(actual_wd - self._cfg.withdraw_fraction * 100.0) <= 5.0
            result["split_ok"] = ri_ok and wd_ok

            if not result["split_ok"]:
                result["notes"].append(
                    f"⚠️ Split drift: actual reinvest={actual_ri:.1f}% "
                    f"(expected {self._cfg.reinvest_fraction * 100:.0f}%)"
                )
        else:
            result["split_ok"] = True  # No trades yet — OK
            result["notes"].append("No profit processed yet — split check skipped.")

        # Position-size growth proxy: reinvested capital should grow over time
        with self._lock:
            history = list(self._state.equity_curve)
        if len(history) >= 2:
            first_equity = history[0]["equity"]
            last_equity = history[-1]["equity"]
            result["position_size_growing"] = last_equity > first_equity
            if not result["position_size_growing"]:
                result["notes"].append("⚠️ Equity has not grown since first trade.")
        else:
            result["position_size_growing"] = None
            result["notes"].append("Not enough data to assess equity growth yet.")

        return result

    # ------------------------------------------------------------------
    # Pillar 4: Risk Sanity Checker
    # ------------------------------------------------------------------

    def risk_sanity_check(self) -> Dict[str, Any]:
        """
        Run all risk-layer health checks in one call.

        Returns
        -------
        dict
            ``overall_healthy`` — ``True`` when every layer passes.
            Individual layer results under ``portfolio_kill_switch``,
            ``recovery_controller``, and ``exchange_kill_switch``.
        """
        result: Dict[str, Any] = {
            "overall_healthy": True,
            "portfolio_kill_switch": _check_portfolio_kill_switch(),
            "recovery_controller": _check_recovery_controller(),
            "exchange_kill_switch": _check_exchange_kill_switch(),
            "phantom_loss_count": 0,
            "warnings": [],
        }

        with self._lock:
            result["phantom_loss_count"] = self._state.phantom_loss_count
            result["kill_switch_triggers"] = self._state.kill_switch_triggers
            result["recovery_blocks"] = self._state.recovery_blocks

        for layer_name in ("portfolio_kill_switch", "recovery_controller", "exchange_kill_switch"):
            layer = result[layer_name]
            if not layer.get("healthy", True):
                result["overall_healthy"] = False
                result["warnings"].extend(layer.get("warnings", []))

        if result["phantom_loss_count"] > 0:
            result["warnings"].append(
                f"⚠️ {result['phantom_loss_count']} phantom PnL events detected."
            )

        return result

    def record_kill_switch_trigger(self) -> None:
        """Increment the kill-switch trigger counter (call when the KS fires)."""
        with self._lock:
            self._state.kill_switch_triggers += 1
            self._save_state()

    def record_recovery_block(self) -> None:
        """Increment the recovery-block counter (call when RecoveryController blocks a trade)."""
        with self._lock:
            self._state.recovery_blocks += 1
            self._save_state()

    # ------------------------------------------------------------------
    # Pillar 5: State / Summary helpers (used by dashboard)
    # ------------------------------------------------------------------

    def get_summary(self) -> Dict[str, Any]:
        """Return a complete JSON-serialisable summary for the dashboard."""
        with self._lock:
            s = self._state
            trade_count = s.trade_count
            win_count = s.win_count
            win_rate = (win_count / trade_count * 100.0) if trade_count > 0 else 0.0
            total_profit = s.total_profit
            reinvested = s.total_reinvested
            withdrawn = s.total_withdrawn
            reinvest_pct = (reinvested / total_profit * 100.0) if total_profit > 0 else 0.0
            withdraw_pct = (withdrawn / total_profit * 100.0) if total_profit > 0 else 0.0

            return {
                "trade_count": trade_count,
                "win_count": win_count,
                "win_rate": round(win_rate, 2),
                "total_profit": round(total_profit, 4),
                "total_fees": round(s.total_fees, 4),
                "total_reinvested": round(reinvested, 4),
                "total_withdrawn": round(withdrawn, 4),
                "reinvest_pct": round(min(reinvest_pct, 100.0), 2),
                "withdraw_pct": round(min(withdraw_pct, 100.0), 2),
                "phantom_loss_count": s.phantom_loss_count,
                "kill_switch_triggers": s.kill_switch_triggers,
                "recovery_blocks": s.recovery_blocks,
                "last_updated": s.last_updated or datetime.now(timezone.utc).isoformat(),
                "tuning": asdict(self._cfg),
                "equity_curve": list(s.equity_curve[-200:]),
                "trade_history": list(s.trade_history[-50:]),
            }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_state(self) -> Phase5State:
        try:
            _DATA_DIR.mkdir(parents=True, exist_ok=True)
            if _STATE_FILE.exists():
                raw = json.loads(_STATE_FILE.read_text())
                return Phase5State(
                    trade_history=raw.get("trade_history", []),
                    equity_curve=raw.get("equity_curve", []),
                    total_reinvested=raw.get("total_reinvested", 0.0),
                    total_withdrawn=raw.get("total_withdrawn", 0.0),
                    total_profit=raw.get("total_profit", 0.0),
                    total_fees=raw.get("total_fees", 0.0),
                    trade_count=raw.get("trade_count", 0),
                    win_count=raw.get("win_count", 0),
                    phantom_loss_count=raw.get("phantom_loss_count", 0),
                    kill_switch_triggers=raw.get("kill_switch_triggers", 0),
                    recovery_blocks=raw.get("recovery_blocks", 0),
                    tuning=raw.get("tuning", asdict(TuningConfig())),
                    last_updated=raw.get("last_updated"),
                )
        except Exception as exc:
            logger.warning("Could not load Phase5 state: %s", exc)
        return Phase5State()

    def _save_state(self) -> None:
        """Persist state to disk (call while holding self._lock)."""
        try:
            _DATA_DIR.mkdir(parents=True, exist_ok=True)
            _STATE_FILE.write_text(json.dumps(asdict(self._state), indent=2))
        except Exception as exc:
            logger.warning("Could not save Phase5 state: %s", exc)


# ---------------------------------------------------------------------------
# Risk layer helpers (module-level to keep the class lean)
# ---------------------------------------------------------------------------


def _check_portfolio_kill_switch() -> Dict[str, Any]:
    if not (_PKS_AVAILABLE and get_portfolio_kill_switch):
        return {"available": False, "healthy": True, "warnings": []}
    try:
        pks = get_portfolio_kill_switch()
        status = pks.get_status()
        triggered = status.get("triggered", False)
        warnings = []
        if triggered:
            warnings.append(
                f"🔴 Portfolio kill switch ACTIVE: {status.get('trigger_reason', 'unknown')}"
            )
        return {
            "available": True,
            "healthy": not triggered,
            "triggered": triggered,
            "trigger_reason": status.get("trigger_reason"),
            "trigger_timestamp": status.get("trigger_timestamp"),
            "consecutive_losses": status.get("consecutive_losses", 0),
            "warnings": warnings,
        }
    except Exception as exc:
        return {"available": True, "healthy": True, "warnings": [f"Check error: {exc}"]}


def _check_recovery_controller() -> Dict[str, Any]:
    if not (_RC_AVAILABLE and RecoveryController):
        return {"available": False, "healthy": True, "warnings": []}
    try:
        rc = RecoveryController()
        can, reason = rc.can_trade("entry")
        # Use getattr to avoid relying on a private attribute
        state_obj = getattr(rc, "_current_state", None)
        state_name = state_obj.value if state_obj is not None else "unknown"
        warnings = []
        if not can:
            warnings.append(f"🔴 Recovery controller blocking entries: {reason}")
        return {
            "available": True,
            "healthy": can,
            "can_trade": can,
            "reason": reason,
            "state": state_name,
            "warnings": warnings,
        }
    except Exception as exc:
        return {"available": True, "healthy": True, "warnings": [f"Check error: {exc}"]}


def _check_exchange_kill_switch() -> Dict[str, Any]:
    if not (_EKS_AVAILABLE and get_exchange_kill_switch_protector):
        return {"available": False, "healthy": True, "warnings": []}
    try:
        eks = get_exchange_kill_switch_protector()
        gates = eks.evaluate_all_gates()
        red_gates = [g for g in gates if hasattr(g, "status") and g.status == "RED"]
        warnings = [f"🔴 Exchange gate RED: {g.gate_name}" for g in red_gates]
        return {
            "available": True,
            "healthy": len(red_gates) == 0,
            "total_gates": len(gates),
            "red_gates": len(red_gates),
            "warnings": warnings,
        }
    except Exception as exc:
        return {"available": True, "healthy": True, "warnings": [f"Check error: {exc}"]}


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[Phase5LivePerformanceTuner] = None
_instance_lock = threading.Lock()


def get_phase5_tuner() -> Phase5LivePerformanceTuner:
    """Return (or create) the global Phase5LivePerformanceTuner singleton."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = Phase5LivePerformanceTuner()
    return _instance


# ---------------------------------------------------------------------------
# Flask Blueprint
# ---------------------------------------------------------------------------

_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<meta http-equiv="refresh" content="15" />
<title>NIJA — Phase 5 Live Performance Dashboard</title>
<style>
  :root{--green:#00d97e;--red:#f03a4f;--gold:#f5c518;--blue:#58a6ff;--bg:#0d1117;--card:#161b22;--border:#30363d;--text:#c9d1d9;--muted:#8b949e}
  *{box-sizing:border-box}
  body{background:var(--bg);color:var(--text);font-family:'Segoe UI',system-ui,sans-serif;margin:0;padding:1rem}
  h1{color:var(--gold);margin-bottom:.2rem}
  h2{color:var(--text);font-size:.95rem;margin:1.2rem 0 .5rem}
  .subtitle{color:var(--muted);font-size:.8rem;margin-bottom:1.2rem}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:.75rem;margin-bottom:1.2rem}
  .card{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:.9rem}
  .label{color:var(--muted);font-size:.7rem;text-transform:uppercase;letter-spacing:.05em}
  .value{font-size:1.5rem;font-weight:700;margin-top:.2rem}
  .green{color:var(--green)}.red{color:var(--red)}.gold{color:var(--gold)}.blue{color:var(--blue)}
  .badge{display:inline-block;padding:.2rem .5rem;border-radius:4px;font-size:.72rem;font-weight:600}
  .badge-ok{background:#0f4d2e;color:var(--green)}.badge-warn{background:#4d2b0f;color:var(--gold)}.badge-err{background:#4d0f1a;color:var(--red)}
  table{width:100%;border-collapse:collapse;background:var(--card);border-radius:8px;overflow:hidden;font-size:.8rem}
  th{background:#1c2128;color:var(--muted);font-size:.68rem;text-transform:uppercase;padding:.5rem .8rem;text-align:left}
  td{padding:.45rem .8rem;border-top:1px solid var(--border)}
  tr.win td{border-left:3px solid var(--green)}
  tr.loss td{border-left:3px solid var(--red)}
  .bar-wrap{height:6px;background:#21262d;border-radius:3px;margin-top:5px}
  .bar{height:6px;border-radius:3px;background:var(--green)}
  .risk-box{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:.9rem;margin-bottom:.75rem}
  .risk-layer{display:flex;align-items:center;gap:.6rem;padding:.35rem 0;border-bottom:1px solid var(--border)}
  .risk-layer:last-child{border-bottom:none}
  .risk-dot{width:10px;height:10px;border-radius:50%;flex-shrink:0}
  .dot-green{background:var(--green)}.dot-red{background:var(--red)}.dot-muted{background:var(--muted)}
  .tuning-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:.5rem}
  .tune-item{background:var(--card);border:1px solid var(--border);border-radius:6px;padding:.6rem .8rem}
  .tune-label{color:var(--muted);font-size:.68rem;text-transform:uppercase}
  .tune-val{font-size:1.05rem;font-weight:600;margin-top:.15rem}
  canvas{width:100%;height:160px;display:block}
  footer{color:var(--muted);font-size:.7rem;text-align:center;margin-top:1.5rem}
</style>
</head>
<body>
<h1>⚡ NIJA Phase 5 — Live Performance Dashboard</h1>
<p class="subtitle">Auto-refreshes every 15 s &nbsp;·&nbsp; Last updated: {{ last_updated }}</p>

<!-- ── KPIs ── -->
<div class="grid">
  <div class="card">
    <div class="label">Trades</div>
    <div class="value">{{ trade_count }}</div>
  </div>
  <div class="card">
    <div class="label">Win Rate</div>
    <div class="value {{ 'green' if win_rate >= 50 else 'red' }}">{{ "%.1f"|format(win_rate) }}%</div>
    <div class="bar-wrap"><div class="bar" style="width:{{ win_rate }}%"></div></div>
  </div>
  <div class="card">
    <div class="label">Total Profit</div>
    <div class="value {{ 'green' if total_profit >= 0 else 'red' }}">${{ "%.4f"|format(total_profit) }}</div>
  </div>
  <div class="card">
    <div class="label">Reinvested</div>
    <div class="value green">${{ "%.4f"|format(total_reinvested) }}</div>
    <div style="font-size:.7rem;color:var(--muted)">{{ "%.1f"|format(reinvest_pct) }}% of profit</div>
  </div>
  <div class="card">
    <div class="label">Withdrawn</div>
    <div class="value gold">${{ "%.4f"|format(total_withdrawn) }}</div>
    <div style="font-size:.7rem;color:var(--muted)">{{ "%.1f"|format(withdraw_pct) }}% of profit</div>
  </div>
  <div class="card">
    <div class="label">Total Fees</div>
    <div class="value">{{ "$%.4f"|format(total_fees) }}</div>
  </div>
</div>

<!-- ── Equity Curve ── -->
<h2>📈 Equity Curve</h2>
<div style="background:var(--card);border:1px solid var(--border);border-radius:8px;padding:1rem;margin-bottom:1.2rem">
  <canvas id="equityChart"></canvas>
  {% if not equity_curve %}
  <p style="color:var(--muted);text-align:center;margin:.5rem 0">No equity data yet.</p>
  {% endif %}
</div>

<!-- ── Risk Sanity ── -->
<h2>🛡️ Risk Sanity Check</h2>
<div class="risk-box">
  <div class="risk-layer">
    <div class="risk-dot {{ 'dot-green' if not pks_triggered else 'dot-red' }}"></div>
    <div>
      <strong>Portfolio Kill Switch</strong>
      <span class="badge {{ 'badge-ok' if not pks_triggered else 'badge-err' }}">
        {{ "OK" if not pks_triggered else "TRIGGERED" }}
      </span>
      {% if pks_reason %}<div style="font-size:.73rem;color:var(--muted);margin-top:2px">{{ pks_reason }}</div>{% endif %}
    </div>
  </div>
  <div class="risk-layer">
    <div class="risk-dot {{ 'dot-green' if rc_can_trade else 'dot-red' }}"></div>
    <div>
      <strong>Recovery Controller</strong>
      <span class="badge {{ 'badge-ok' if rc_can_trade else 'badge-warn' }}">
        {{ rc_state }}
      </span>
      {% if not rc_can_trade %}<div style="font-size:.73rem;color:var(--gold);margin-top:2px">{{ rc_reason }}</div>{% endif %}
    </div>
  </div>
  <div class="risk-layer">
    <div class="risk-dot {{ 'dot-green' if eks_healthy else 'dot-red' }}"></div>
    <div>
      <strong>Exchange Kill Switch</strong>
      <span class="badge {{ 'badge-ok' if eks_healthy else 'badge-err' }}">
        {{ "CLEAR" if eks_healthy else eks_red_gates|string + " RED GATES" }}
      </span>
    </div>
  </div>
  <div class="risk-layer">
    <div class="risk-dot {{ 'dot-green' if phantom_loss_count == 0 else 'dot-red' }}"></div>
    <div>
      <strong>Phantom PnL Events</strong>
      <span class="badge {{ 'badge-ok' if phantom_loss_count == 0 else 'badge-err' }}">
        {{ phantom_loss_count }}
      </span>
    </div>
  </div>
</div>

<!-- ── Compounding Verification ── -->
<h2>💰 Compounding Verification</h2>
<div class="risk-box">
  <div class="risk-layer">
    <div class="risk-dot {{ 'dot-green' if compound_split_ok else ('dot-red' if compound_split_ok is not none else 'dot-muted') }}"></div>
    <div>
      <strong>Profit Split</strong>
      {% if compound_split_ok is not none %}
      <span class="badge {{ 'badge-ok' if compound_split_ok else 'badge-err' }}">
        {{ "CORRECT" if compound_split_ok else "DRIFT DETECTED" }}
      </span>
      {% else %}<span class="badge badge-warn">NO DATA</span>{% endif %}
      <div style="font-size:.73rem;color:var(--muted);margin-top:2px">
        Expected: reinvest={{ "%.0f"|format(compound_expected_ri) }}%
        withdraw={{ "%.0f"|format(compound_expected_wd) }}%
        {% if compound_actual_ri is not none %}
        &nbsp;·&nbsp; Actual: reinvest={{ "%.1f"|format(compound_actual_ri) }}%
        withdraw={{ "%.1f"|format(compound_actual_wd) }}%
        {% endif %}
      </div>
    </div>
  </div>
  <div class="risk-layer">
    <div class="risk-dot {{ 'dot-green' if equity_growing else ('dot-red' if equity_growing is not none else 'dot-muted') }}"></div>
    <div>
      <strong>Position Size Growing</strong>
      {% if equity_growing is not none %}
      <span class="badge {{ 'badge-ok' if equity_growing else 'badge-warn' }}">
        {{ "YES — equity growing ✅" if equity_growing else "NOT YET ⚠️" }}
      </span>
      {% else %}<span class="badge badge-warn">AWAITING DATA</span>{% endif %}
    </div>
  </div>
</div>

<!-- ── Tuning Config ── -->
<h2>⚙️ Win-Rate / Frequency Tuning Config</h2>
<div class="tuning-grid">
  <div class="tune-item">
    <div class="tune-label">AI Confidence Threshold</div>
    <div class="tune-val blue">{{ tuning.ai_confidence_threshold }}</div>
  </div>
  <div class="tune-item">
    <div class="tune-label">Take-Profit Level</div>
    <div class="tune-val green">{{ tuning.take_profit_pct }}%</div>
  </div>
  <div class="tune-item">
    <div class="tune-label">Scan Interval</div>
    <div class="tune-val">{{ tuning.scan_interval_seconds }}s</div>
  </div>
  <div class="tune-item">
    <div class="tune-label">Reinvest Fraction</div>
    <div class="tune-val green">{{ "%.0f"|format(tuning.reinvest_fraction * 100) }}%</div>
  </div>
  <div class="tune-item">
    <div class="tune-label">Withdraw Fraction</div>
    <div class="tune-val gold">{{ "%.0f"|format(tuning.withdraw_fraction * 100) }}%</div>
  </div>
  <div class="tune-item">
    <div class="tune-label">Min Reinvest Profit</div>
    <div class="tune-val">${{ tuning.min_reinvest_profit }}</div>
  </div>
</div>
<p style="font-size:.73rem;color:var(--muted);margin-top:.5rem">
  Update via: <code>POST /api/phase5/tuning</code> with JSON body.
</p>

<!-- ── Trade History ── -->
<h2>📋 Trade History (last 50)</h2>
{% if trade_history %}
<table>
  <thead>
    <tr>
      <th>Time</th><th>Symbol</th><th>Gross P&L</th><th>Net P&L</th>
      <th>Reinvested</th><th>Withdrawn</th><th>Equity</th><th>Split</th><th>Result</th>
    </tr>
  </thead>
  <tbody>
  {% for t in trade_history|reverse %}
    <tr class="{{ 'win' if t.is_win else 'loss' }}">
      <td>{{ t.timestamp[:19] }}</td>
      <td>{{ t.symbol }}</td>
      <td class="{{ 'green' if t.gross_profit >= 0 else 'red' }}">${{ "%.4f"|format(t.gross_profit) }}</td>
      <td class="{{ 'green' if t.net_profit >= 0 else 'red' }}">${{ "%.4f"|format(t.net_profit) }}</td>
      <td class="green">${{ "%.4f"|format(t.reinvest_usd) }}</td>
      <td class="gold">${{ "%.4f"|format(t.withdraw_usd) }}</td>
      <td>${{ "%.2f"|format(t.equity_after) }}</td>
      <td>
        <span class="badge {{ 'badge-ok' if t.split_valid else 'badge-err' }}">
          {{ "✓" if t.split_valid else "✗" }}
        </span>
        {% if t.phantom_flag %}
        <span class="badge badge-err" title="Phantom PnL">👻</span>
        {% endif %}
      </td>
      <td>{{ "✅ WIN" if t.is_win else "❌ LOSS" }}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>
{% else %}
<p style="color:var(--muted)">No trade history yet.</p>
{% endif %}

<footer>NIJA Trading Systems · Phase 5 Live Performance Dashboard v1.0</footer>

<script>
(function() {
  var curve = {{ equity_curve_json }};
  if (!curve.length) return;
  var canvas = document.getElementById('equityChart');
  if (!canvas) return;
  var ctx = canvas.getContext('2d');
  canvas.width = canvas.offsetWidth || 800;
  canvas.height = 160;
  var W = canvas.width, H = canvas.height;
  var equities = curve.map(function(p){ return p.equity; });
  var minE = Math.min.apply(null, equities);
  var maxE = Math.max.apply(null, equities);
  var range = maxE - minE || 1;
  function xPos(i){ return (i / (curve.length - 1 || 1)) * W; }
  function yPos(e){ return H - ((e - minE) / range) * (H - 20) - 10; }
  ctx.strokeStyle = '#00d97e';
  ctx.lineWidth = 2;
  ctx.beginPath();
  curve.forEach(function(p, i){
    if (i === 0) ctx.moveTo(xPos(i), yPos(p.equity));
    else ctx.lineTo(xPos(i), yPos(p.equity));
  });
  ctx.stroke();
  // Gradient fill
  var grad = ctx.createLinearGradient(0, 0, 0, H);
  grad.addColorStop(0, 'rgba(0,217,126,0.15)');
  grad.addColorStop(1, 'rgba(0,217,126,0)');
  ctx.fillStyle = grad;
  ctx.lineTo(xPos(curve.length-1), H);
  ctx.lineTo(0, H);
  ctx.closePath();
  ctx.fill();
})();
</script>
</body>
</html>"""


def create_phase5_dashboard_blueprint() -> Blueprint:
    """
    Create the Phase 5 Flask Blueprint.

    Register it with::

        app.register_blueprint(create_phase5_dashboard_blueprint())
    """
    bp = Blueprint("phase5", __name__)

    def _build_context() -> Dict[str, Any]:
        tuner = get_phase5_tuner()
        summary = tuner.get_summary()
        risk = tuner.risk_sanity_check()
        compound = tuner.verify_compounding()

        pks = risk.get("portfolio_kill_switch", {})
        rc = risk.get("recovery_controller", {})
        eks = risk.get("exchange_kill_switch", {})

        return {
            "trade_count": summary["trade_count"],
            "win_rate": summary["win_rate"],
            "total_profit": summary["total_profit"],
            "total_fees": summary["total_fees"],
            "total_reinvested": summary["total_reinvested"],
            "total_withdrawn": summary["total_withdrawn"],
            "reinvest_pct": summary["reinvest_pct"],
            "withdraw_pct": summary["withdraw_pct"],
            "phantom_loss_count": summary["phantom_loss_count"],
            "last_updated": summary["last_updated"][:19],
            "equity_curve": summary["equity_curve"],
            "equity_curve_json": json.dumps(summary["equity_curve"]),
            "trade_history": summary["trade_history"],
            "tuning": summary["tuning"],
            # Risk
            "pks_triggered": pks.get("triggered", False),
            "pks_reason": pks.get("trigger_reason"),
            "rc_can_trade": rc.get("can_trade", True),
            "rc_state": rc.get("state", "unknown"),
            "rc_reason": rc.get("reason", ""),
            "eks_healthy": eks.get("healthy", True),
            "eks_red_gates": eks.get("red_gates", 0),
            # Compounding
            "compound_split_ok": compound.get("split_ok"),
            "compound_expected_ri": compound.get("expected_reinvest_pct", 75.0),
            "compound_expected_wd": compound.get("expected_withdraw_pct", 25.0),
            "compound_actual_ri": compound.get("actual_reinvest_pct"),
            "compound_actual_wd": compound.get("actual_withdraw_pct"),
            "equity_growing": compound.get("position_size_growing"),
        }

    # ---- HTML dashboard ----

    @bp.route("/phase5/dashboard")
    def phase5_dashboard():  # type: ignore[return]
        """Full Phase 5 HTML visual dashboard."""
        ctx = _build_context()
        return render_template_string(_DASHBOARD_HTML, **ctx)

    # ---- JSON APIs ----

    @bp.route("/api/phase5/summary")
    def phase5_summary():  # type: ignore[return]
        """JSON summary (no history, no equity curve)."""
        tuner = get_phase5_tuner()
        data = tuner.get_summary()
        data.pop("equity_curve", None)
        data.pop("trade_history", None)
        return jsonify(data)

    @bp.route("/api/phase5/equity-curve")
    def phase5_equity_curve():  # type: ignore[return]
        """JSON equity curve."""
        tuner = get_phase5_tuner()
        return jsonify({"equity_curve": tuner.get_summary()["equity_curve"]})

    @bp.route("/api/phase5/trade-history")
    def phase5_trade_history():  # type: ignore[return]
        """JSON trade history (last 50)."""
        tuner = get_phase5_tuner()
        return jsonify({"trade_history": tuner.get_summary()["trade_history"]})

    @bp.route("/api/phase5/risk-sanity")
    def phase5_risk_sanity():  # type: ignore[return]
        """JSON risk sanity check result."""
        tuner = get_phase5_tuner()
        return jsonify(tuner.risk_sanity_check())

    @bp.route("/api/phase5/compounding")
    def phase5_compounding():  # type: ignore[return]
        """JSON compounding verification result."""
        tuner = get_phase5_tuner()
        return jsonify(tuner.verify_compounding())

    @bp.route("/api/phase5/tuning", methods=["GET"])
    def phase5_tuning_get():  # type: ignore[return]
        """Return current tuning configuration."""
        tuner = get_phase5_tuner()
        return jsonify(asdict(tuner.get_tuning_config()))

    @bp.route("/api/phase5/tuning", methods=["POST"])
    def phase5_tuning_post():  # type: ignore[return]
        """Update tuning configuration from JSON body."""
        tuner = get_phase5_tuner()
        body = request.get_json(silent=True) or {}
        try:
            updated = tuner.update_tuning(
                ai_confidence_threshold=body.get("ai_confidence_threshold"),
                take_profit_pct=body.get("take_profit_pct"),
                scan_interval_seconds=body.get("scan_interval_seconds"),
                min_reinvest_profit=body.get("min_reinvest_profit"),
                reinvest_fraction=body.get("reinvest_fraction"),
                withdraw_fraction=body.get("withdraw_fraction"),
            )
            return jsonify({"success": True, "tuning": asdict(updated)})
        except ValueError as exc:
            return jsonify({"success": False, "error": str(exc)}), 400

    @bp.route("/api/phase5/record-trade", methods=["POST"])
    def phase5_record_trade():  # type: ignore[return]
        """
        Record a trade outcome directly via the API.

        Expected JSON body:
            symbol, gross_profit, fees, is_win, equity_after,
            reinvest_usd (optional), withdraw_usd (optional)
        """
        tuner = get_phase5_tuner()
        body = request.get_json(silent=True) or {}
        required = ("symbol", "gross_profit", "fees", "is_win", "equity_after")
        missing = [k for k in required if k not in body]
        if missing:
            return jsonify({"success": False, "error": f"Missing fields: {missing}"}), 400
        try:
            record = tuner.record_trade_outcome(
                symbol=str(body["symbol"]),
                gross_profit=float(body["gross_profit"]),
                fees=float(body["fees"]),
                is_win=bool(body["is_win"]),
                equity_after=float(body["equity_after"]),
                reinvest_usd=float(body.get("reinvest_usd", 0.0)),
                withdraw_usd=float(body.get("withdraw_usd", 0.0)),
            )
            return jsonify({"success": True, "record": asdict(record)})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    return bp


def register_phase5_dashboard(app: Any) -> None:  # type: ignore[type-arg]
    """
    Convenience function — register the Phase 5 Blueprint with a Flask app.

        register_phase5_dashboard(app)
    """
    try:
        bp = create_phase5_dashboard_blueprint()
        app.register_blueprint(bp)
        logger.info(
            "✅ Phase 5 Performance Tuner dashboard registered "
            "(/phase5/dashboard, /api/phase5/*)"
        )
    except Exception as exc:
        logger.warning("⚠️ Could not register Phase 5 dashboard: %s", exc)
