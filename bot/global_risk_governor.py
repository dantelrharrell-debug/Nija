"""
NIJA Global Risk Governor
==========================

Prevents cascading losses by enforcing portfolio-wide circuit breakers across
every dimension of risk simultaneously.  Unlike per-trade or per-strategy
guards, the Global Risk Governor has final veto over **every** new position
regardless of what individual strategies recommend.

Architecture
------------
::

  ┌─────────────────────────────────────────────────────────┐
  │                  GlobalRiskGovernor                      │
  │                                                          │
  │  1. Daily Loss Gate        – blocks new entries once     │
  │     daily P&L crosses –X% of portfolio equity            │
  │                                                          │
  │  2. Consecutive Loss Gate  – blocks after N consecutive  │
  │     losing trades (cascade breaker)                      │
  │                                                          │
  │  3. Equity Curve Gate      – blocks when equity falls    │
  │     below its own N-trade moving average                 │
  │                                                          │
  │  4. Exposure Concentration – caps simultaneous open      │
  │     positions and total notional risk                    │
  │                                                          │
  │  5. Volatility Spike Gate  – suspends trading during     │
  │     abnormal volatility regimes                          │
  │                                                          │
  │  All gates produce an allow/deny verdict with a human-   │
  │  readable reason and a risk score (0-100).               │
  └─────────────────────────────────────────────────────────┘

Key Design Decisions
--------------------
* **Single source of truth**: one singleton, thread-safe, persistent state.
* **Graceful degradation**: if state file is missing/corrupt, resets cleanly.
* **Zero hard dependencies**: works standalone; optionally integrates with
  AlertManager and DrawdownProtectionSystem when available.
* **Audit trail**: every gate decision is appended to a JSON-lines log.

Usage
-----
    from bot.global_risk_governor import get_global_risk_governor

    gov = get_global_risk_governor()

    # Before opening any position:
    decision = gov.approve_entry(
        symbol="BTC-USD",
        proposed_risk_usd=250.0,
        current_portfolio_value=10_000.0,
    )
    if not decision.allowed:
        logger.warning(f"Trade blocked: {decision.reason}")
        return

    # After a trade closes:
    gov.record_trade_result(pnl_usd=120.0, is_win=True)

    # Inspect overall status:
    print(gov.get_status())

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import threading
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, date, timezone
from enum import Enum
from pathlib import Path
from typing import Deque, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.global_risk_governor")

# ---------------------------------------------------------------------------
# Constants – all overridable via constructor kwargs
# ---------------------------------------------------------------------------

DEFAULT_MAX_DAILY_LOSS_PCT: float = 3.0          # halt if daily loss > 3% of equity
DEFAULT_MAX_CONSECUTIVE_LOSSES: int = 5          # halt after 5 consecutive losses
DEFAULT_EQUITY_MA_WINDOW: int = 20               # equity-curve MA window (trades)
DEFAULT_MAX_OPEN_POSITIONS: int = 12             # max simultaneous open positions
DEFAULT_MAX_TOTAL_RISK_PCT: float = 8.0          # max total open risk as % of equity
DEFAULT_VOLATILITY_MULTIPLIER_LIMIT: float = 2.5 # block if vol > X× 30-day average
DEFAULT_HALT_COOLDOWN_SECONDS: int = 3600        # min seconds between auto-resume

DATA_DIR = Path(__file__).parent.parent / "data"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class GateStatus(Enum):
    """Status of a single risk gate."""
    GREEN  = "green"   # no issue
    YELLOW = "yellow"  # elevated risk – reduce size but allow entry
    RED    = "red"     # blocked – no new entries


class HaltReason(Enum):
    """Why trading was halted."""
    NONE                 = "none"
    DAILY_LOSS_LIMIT     = "daily_loss_limit"
    CONSECUTIVE_LOSSES   = "consecutive_losses"
    EQUITY_CURVE         = "equity_curve"
    EXPOSURE_LIMIT       = "exposure_limit"
    VOLATILITY_SPIKE     = "volatility_spike"
    MANUAL               = "manual"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class GateDecision:
    """Result from a single risk gate evaluation."""
    gate_name: str
    status: GateStatus
    reason: str
    size_multiplier: float = 1.0   # 1.0 = full size; <1.0 = scaled down


@dataclass
class GovernorDecision:
    """Aggregated decision returned to callers."""
    allowed: bool
    reason: str
    risk_score: float              # 0 = pristine, 100 = maximum risk
    size_multiplier: float         # caller should multiply their size by this
    gate_decisions: List[GateDecision] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "risk_score": round(self.risk_score, 2),
            "size_multiplier": round(self.size_multiplier, 4),
            "gates": [
                {
                    "name": g.gate_name,
                    "status": g.status.value,
                    "reason": g.reason,
                    "multiplier": round(g.size_multiplier, 4),
                }
                for g in self.gate_decisions
            ],
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class GovernorConfig:
    """Tunable configuration for the Global Risk Governor."""
    max_daily_loss_pct: float            = DEFAULT_MAX_DAILY_LOSS_PCT
    max_consecutive_losses: int          = DEFAULT_MAX_CONSECUTIVE_LOSSES
    equity_ma_window: int                = DEFAULT_EQUITY_MA_WINDOW
    max_open_positions: int              = DEFAULT_MAX_OPEN_POSITIONS
    max_total_risk_pct: float            = DEFAULT_MAX_TOTAL_RISK_PCT
    volatility_multiplier_limit: float   = DEFAULT_VOLATILITY_MULTIPLIER_LIMIT
    halt_cooldown_seconds: int           = DEFAULT_HALT_COOLDOWN_SECONDS

    # Intermediate thresholds that produce YELLOW (size reduction) instead of RED
    daily_loss_caution_pct: float        = 1.5   # caution at half the daily limit
    consecutive_loss_caution: int        = 3     # caution after 3 losses
    exposure_caution_pct: float          = 5.0   # caution before hitting hard cap

    # Size reduction factors for YELLOW gates
    caution_size_multiplier: float       = 0.65


# ---------------------------------------------------------------------------
# Core Governor
# ---------------------------------------------------------------------------

class GlobalRiskGovernor:
    """
    Portfolio-wide circuit breaker that prevents cascading losses.

    Thread-safe singleton (use ``get_global_risk_governor()`` factory).
    State is persisted to JSON on every trade record so restarts
    do not reset counters mid-session.
    """

    STATE_FILE = DATA_DIR / "global_risk_governor.json"
    AUDIT_FILE = DATA_DIR / "global_risk_governor_audit.jsonl"

    def __init__(self, config: Optional[GovernorConfig] = None) -> None:
        self.config = config or GovernorConfig()
        self._lock = threading.RLock()

        # Persistent counters
        self._daily_pnl: float = 0.0
        self._daily_date: str = str(date.today())
        self._consecutive_losses: int = 0
        self._trade_equity_history: Deque[float] = deque(
            maxlen=self.config.equity_ma_window * 3
        )
        self._open_positions: int = 0
        self._total_risk_usd: float = 0.0
        self._halt_active: bool = False
        self._halt_reason: HaltReason = HaltReason.NONE
        self._halt_timestamp: Optional[str] = None
        self._recent_volatility_ratio: float = 1.0

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._load_state()

        # Optional AlertManager integration
        self._alert_mgr = None
        try:
            from bot.alert_manager import get_alert_manager
            self._alert_mgr = get_alert_manager()
        except Exception:
            try:
                from alert_manager import get_alert_manager  # type: ignore
                self._alert_mgr = get_alert_manager()
            except Exception:
                pass

        logger.info(
            "✅ GlobalRiskGovernor ready | daily_loss_limit=%.1f%% | "
            "max_consec_losses=%d | equity_ma=%d bars",
            self.config.max_daily_loss_pct,
            self.config.max_consecutive_losses,
            self.config.equity_ma_window,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def approve_entry(
        self,
        symbol: str,
        proposed_risk_usd: float,
        current_portfolio_value: float,
        current_volatility_ratio: float = 1.0,
    ) -> GovernorDecision:
        """
        Evaluate whether a new trade entry is permitted.

        Parameters
        ----------
        symbol:
            Instrument identifier (for logging).
        proposed_risk_usd:
            Maximum capital at risk for this trade (e.g. position_size × stop_distance).
        current_portfolio_value:
            Current total portfolio equity in USD.
        current_volatility_ratio:
            Current ATR (or similar) divided by its 30-day average.  >1 means
            elevated volatility.

        Returns
        -------
        GovernorDecision
            ``.allowed`` is False if any RED gate fires.
        """
        with self._lock:
            self._maybe_reset_daily(current_portfolio_value)
            self._recent_volatility_ratio = current_volatility_ratio

            gate_results: List[GateDecision] = [
                self._gate_halt_check(),
                self._gate_daily_loss(current_portfolio_value),
                self._gate_consecutive_losses(),
                self._gate_equity_curve(),
                self._gate_exposure(proposed_risk_usd, current_portfolio_value),
                self._gate_volatility(current_volatility_ratio),
            ]

            # Aggregate
            red_gates = [g for g in gate_results if g.status == GateStatus.RED]
            yellow_gates = [g for g in gate_results if g.status == GateStatus.YELLOW]

            if red_gates:
                reason = "; ".join(g.reason for g in red_gates)
                risk_score = min(100.0, 80.0 + 5.0 * len(red_gates))
                decision = GovernorDecision(
                    allowed=False,
                    reason=f"🚫 Trade BLOCKED — {reason}",
                    risk_score=risk_score,
                    size_multiplier=0.0,
                    gate_decisions=gate_results,
                )
            elif yellow_gates:
                reason = "; ".join(g.reason for g in yellow_gates)
                min_mult = min(g.size_multiplier for g in yellow_gates)
                risk_score = 40.0 + 10.0 * len(yellow_gates)
                decision = GovernorDecision(
                    allowed=True,
                    reason=f"⚠️ Caution — {reason}",
                    risk_score=min(79.0, risk_score),
                    size_multiplier=min_mult,
                    gate_decisions=gate_results,
                )
            else:
                decision = GovernorDecision(
                    allowed=True,
                    reason="✅ All risk gates GREEN",
                    risk_score=max(0.0, 10.0 + self._consecutive_losses * 5.0),
                    size_multiplier=1.0,
                    gate_decisions=gate_results,
                )

            self._audit(symbol, decision)
            return decision

    def record_trade_result(
        self,
        pnl_usd: float,
        is_win: bool,
        portfolio_value: Optional[float] = None,
    ) -> None:
        """
        Update internal counters after a trade closes.

        Must be called for every completed trade so the governor stays
        synchronised with the actual P&L history.
        """
        with self._lock:
            self._daily_pnl += pnl_usd

            if is_win:
                self._consecutive_losses = 0
            else:
                self._consecutive_losses += 1
                # Check cascade breaker threshold
                if self._consecutive_losses >= self.config.max_consecutive_losses:
                    self._activate_halt(
                        HaltReason.CONSECUTIVE_LOSSES,
                        f"{self._consecutive_losses} consecutive losses — cascade breaker",
                    )

            if portfolio_value is not None:
                self._trade_equity_history.append(portfolio_value)

            self._save_state()
            logger.debug(
                "GovernorRecord: pnl=%.2f win=%s consec_losses=%d daily_pnl=%.2f",
                pnl_usd, is_win, self._consecutive_losses, self._daily_pnl,
            )

    def update_open_positions(
        self,
        open_count: int,
        total_risk_usd: float = 0.0,
    ) -> None:
        """Synchronise the open-position counter (call after every open/close)."""
        with self._lock:
            self._open_positions = open_count
            self._total_risk_usd = total_risk_usd

    def resume_trading(self, reason: str = "manual resume") -> None:
        """Manually lift a halt (e.g. end-of-day reset or operator action)."""
        with self._lock:
            if self._halt_active:
                logger.info(
                    "GlobalRiskGovernor: halt lifted — %s (was: %s)",
                    reason, self._halt_reason.value,
                )
            self._halt_active = False
            self._halt_reason = HaltReason.NONE
            self._halt_timestamp = None
            self._save_state()

    def get_status(self) -> Dict:
        """Return a human-readable / JSON-serialisable status snapshot."""
        with self._lock:
            equity_ma = self._equity_curve_ma()
            current_equity = (
                self._trade_equity_history[-1]
                if self._trade_equity_history
                else None
            )
            return {
                "halt_active": self._halt_active,
                "halt_reason": self._halt_reason.value,
                "halt_since": self._halt_timestamp,
                "daily_pnl_usd": round(self._daily_pnl, 2),
                "daily_date": self._daily_date,
                "consecutive_losses": self._consecutive_losses,
                "open_positions": self._open_positions,
                "total_risk_usd": round(self._total_risk_usd, 2),
                "equity_ma": round(equity_ma, 2) if equity_ma else None,
                "current_equity": round(current_equity, 2) if current_equity else None,
                "volatility_ratio": round(self._recent_volatility_ratio, 4),
                "config": {
                    "max_daily_loss_pct": self.config.max_daily_loss_pct,
                    "max_consecutive_losses": self.config.max_consecutive_losses,
                    "equity_ma_window": self.config.equity_ma_window,
                    "max_open_positions": self.config.max_open_positions,
                    "max_total_risk_pct": self.config.max_total_risk_pct,
                },
            }

    # ------------------------------------------------------------------
    # Internal gate implementations
    # ------------------------------------------------------------------

    def _gate_halt_check(self) -> GateDecision:
        """Gate 0: Hard halt (previously activated)."""
        if not self._halt_active:
            return GateDecision("halt_check", GateStatus.GREEN, "No active halt", 1.0)
        return GateDecision(
            "halt_check",
            GateStatus.RED,
            f"Trading halted: {self._halt_reason.value} (since {self._halt_timestamp})",
            0.0,
        )

    def _gate_daily_loss(self, portfolio_value: float) -> GateDecision:
        """Gate 1: Daily loss limit."""
        if portfolio_value <= 0:
            return GateDecision("daily_loss", GateStatus.GREEN, "No portfolio value", 1.0)

        loss_pct = (-self._daily_pnl / portfolio_value) * 100.0  # positive = loss
        caution = self.config.daily_loss_caution_pct
        limit   = self.config.max_daily_loss_pct

        if loss_pct >= limit:
            self._activate_halt(
                HaltReason.DAILY_LOSS_LIMIT,
                f"Daily loss {loss_pct:.2f}% ≥ limit {limit:.1f}%",
            )
            return GateDecision(
                "daily_loss",
                GateStatus.RED,
                f"Daily loss {loss_pct:.2f}% exceeded limit {limit:.1f}%",
                0.0,
            )
        if loss_pct >= caution:
            ratio = (loss_pct - caution) / max(limit - caution, 0.001)
            mult = 1.0 - ratio * (1.0 - self.config.caution_size_multiplier)
            return GateDecision(
                "daily_loss",
                GateStatus.YELLOW,
                f"Daily loss caution {loss_pct:.2f}% (limit {limit:.1f}%)",
                round(mult, 3),
            )
        return GateDecision(
            "daily_loss",
            GateStatus.GREEN,
            f"Daily P&L {self._daily_pnl:+.2f} USD ({loss_pct:.2f}% loss)",
            1.0,
        )

    def _gate_consecutive_losses(self) -> GateDecision:
        """Gate 2: Consecutive-loss cascade breaker."""
        cl = self._consecutive_losses
        caution = self.config.consecutive_loss_caution
        limit   = self.config.max_consecutive_losses

        if cl >= limit:
            return GateDecision(
                "consecutive_losses",
                GateStatus.RED,
                f"{cl} consecutive losses ≥ limit {limit}",
                0.0,
            )
        if cl >= caution:
            ratio = (cl - caution) / max(limit - caution, 1)
            mult = 1.0 - ratio * (1.0 - self.config.caution_size_multiplier)
            return GateDecision(
                "consecutive_losses",
                GateStatus.YELLOW,
                f"{cl} consecutive losses (caution threshold {caution})",
                round(mult, 3),
            )
        return GateDecision(
            "consecutive_losses",
            GateStatus.GREEN,
            f"{cl} consecutive losses (limit {limit})",
            1.0,
        )

    def _gate_equity_curve(self) -> GateDecision:
        """Gate 3: Equity curve below moving average."""
        ma = self._equity_curve_ma()
        if ma is None or not self._trade_equity_history:
            return GateDecision("equity_curve", GateStatus.GREEN, "Insufficient equity history", 1.0)

        current = self._trade_equity_history[-1]
        deviation_pct = ((current - ma) / ma) * 100.0

        if deviation_pct < -5.0:  # equity > 5% below MA → RED
            return GateDecision(
                "equity_curve",
                GateStatus.RED,
                f"Equity {deviation_pct:.1f}% below {self.config.equity_ma_window}-trade MA",
                0.0,
            )
        if deviation_pct < -2.0:  # 2-5% below MA → YELLOW
            ratio = abs(deviation_pct + 2.0) / 3.0
            mult = 1.0 - ratio * (1.0 - self.config.caution_size_multiplier)
            return GateDecision(
                "equity_curve",
                GateStatus.YELLOW,
                f"Equity {deviation_pct:.1f}% below {self.config.equity_ma_window}-trade MA",
                round(mult, 3),
            )
        return GateDecision(
            "equity_curve",
            GateStatus.GREEN,
            f"Equity {deviation_pct:+.1f}% vs {self.config.equity_ma_window}-trade MA",
            1.0,
        )

    def _gate_exposure(
        self,
        proposed_risk_usd: float,
        portfolio_value: float,
    ) -> GateDecision:
        """Gate 4: Open-position count and total notional risk."""
        if self._open_positions >= self.config.max_open_positions:
            return GateDecision(
                "exposure",
                GateStatus.RED,
                f"Max open positions reached ({self._open_positions}/{self.config.max_open_positions})",
                0.0,
            )

        if portfolio_value > 0:
            new_total_risk = self._total_risk_usd + proposed_risk_usd
            new_risk_pct = (new_total_risk / portfolio_value) * 100.0
            caution_pct  = self.config.exposure_caution_pct
            limit_pct    = self.config.max_total_risk_pct

            if new_risk_pct >= limit_pct:
                return GateDecision(
                    "exposure",
                    GateStatus.RED,
                    f"Total risk {new_risk_pct:.1f}% would exceed limit {limit_pct:.1f}%",
                    0.0,
                )
            if new_risk_pct >= caution_pct:
                ratio = (new_risk_pct - caution_pct) / max(limit_pct - caution_pct, 0.001)
                mult = 1.0 - ratio * (1.0 - self.config.caution_size_multiplier)
                return GateDecision(
                    "exposure",
                    GateStatus.YELLOW,
                    f"Total risk elevated: {new_risk_pct:.1f}% (limit {limit_pct:.1f}%)",
                    round(mult, 3),
                )

        return GateDecision(
            "exposure",
            GateStatus.GREEN,
            f"Open positions {self._open_positions}/{self.config.max_open_positions}",
            1.0,
        )

    def _gate_volatility(self, volatility_ratio: float) -> GateDecision:
        """Gate 5: Volatility spike protection."""
        limit = self.config.volatility_multiplier_limit
        caution = limit * 0.75

        if volatility_ratio >= limit:
            return GateDecision(
                "volatility",
                GateStatus.RED,
                f"Volatility spike: {volatility_ratio:.2f}× average (limit {limit:.1f}×)",
                0.0,
            )
        if volatility_ratio >= caution:
            ratio = (volatility_ratio - caution) / max(limit - caution, 0.001)
            mult = 1.0 - ratio * (1.0 - self.config.caution_size_multiplier)
            return GateDecision(
                "volatility",
                GateStatus.YELLOW,
                f"Elevated volatility: {volatility_ratio:.2f}× average",
                round(mult, 3),
            )
        return GateDecision(
            "volatility",
            GateStatus.GREEN,
            f"Volatility normal: {volatility_ratio:.2f}× average",
            1.0,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _equity_curve_ma(self) -> Optional[float]:
        """Simple moving average of the last ``equity_ma_window`` equity snapshots."""
        window = self.config.equity_ma_window
        history = list(self._trade_equity_history)
        if len(history) < window:
            if len(history) == 0:
                return None
            return sum(history) / len(history)
        return sum(history[-window:]) / window

    def _activate_halt(self, reason: HaltReason, message: str) -> None:
        """Activate trading halt and fire an alert if AlertManager is available."""
        if self._halt_active and self._halt_reason == reason:
            return  # already halted for same reason
        self._halt_active = True
        self._halt_reason = reason
        self._halt_timestamp = datetime.now(timezone.utc).isoformat()
        logger.critical("🛑 GlobalRiskGovernor HALT: %s", message)
        self._save_state()

        if self._alert_mgr:
            try:
                self._alert_mgr.fire_alert(
                    category="RISK_LIMIT_BREACH",
                    severity="CRITICAL",
                    title="Global Risk Governor Halt",
                    message=message,
                )
            except Exception:
                pass

    def _maybe_reset_daily(self, portfolio_value: float) -> None:
        """Reset daily P&L counter at the start of a new calendar day."""
        today = str(date.today())
        if today != self._daily_date:
            logger.info(
                "GovernorDailyReset: day %s → %s | daily_pnl=%.2f",
                self._daily_date, today, self._daily_pnl,
            )
            self._daily_pnl = 0.0
            self._daily_date = today
            # Automatically lift a daily-loss halt on new day
            if self._halt_active and self._halt_reason == HaltReason.DAILY_LOSS_LIMIT:
                self.resume_trading("new trading day")
            # Also record portfolio value for equity curve
            if portfolio_value > 0:
                self._trade_equity_history.append(portfolio_value)
            self._save_state()

    def _audit(self, symbol: str, decision: GovernorDecision) -> None:
        """Append decision to JSON-lines audit log."""
        try:
            record = {"symbol": symbol}
            record.update(decision.to_dict())
            with self.AUDIT_FILE.open("a") as fh:
                fh.write(json.dumps(record) + "\n")
        except Exception as exc:
            logger.debug("GovernorAudit write failed: %s", exc)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_state(self) -> None:
        try:
            state = {
                "daily_pnl": self._daily_pnl,
                "daily_date": self._daily_date,
                "consecutive_losses": self._consecutive_losses,
                "open_positions": self._open_positions,
                "total_risk_usd": self._total_risk_usd,
                "halt_active": self._halt_active,
                "halt_reason": self._halt_reason.value,
                "halt_timestamp": self._halt_timestamp,
                "equity_history": list(self._trade_equity_history),
            }
            self.STATE_FILE.write_text(json.dumps(state, indent=2))
        except Exception as exc:
            logger.debug("GovernorState save failed: %s", exc)

    def _load_state(self) -> None:
        try:
            if not self.STATE_FILE.exists():
                return
            state = json.loads(self.STATE_FILE.read_text())
            self._daily_pnl          = float(state.get("daily_pnl", 0.0))
            self._daily_date         = str(state.get("daily_date", str(date.today())))
            self._consecutive_losses = int(state.get("consecutive_losses", 0))
            self._open_positions     = int(state.get("open_positions", 0))
            self._total_risk_usd     = float(state.get("total_risk_usd", 0.0))
            self._halt_active        = bool(state.get("halt_active", False))
            self._halt_reason        = HaltReason(state.get("halt_reason", HaltReason.NONE.value))
            self._halt_timestamp     = state.get("halt_timestamp")
            for v in state.get("equity_history", []):
                self._trade_equity_history.append(float(v))
            logger.info("GovernorState loaded from %s", self.STATE_FILE)
        except Exception as exc:
            logger.warning("GovernorState load failed (%s) — starting fresh", exc)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_governor_instance: Optional[GlobalRiskGovernor] = None
_governor_lock = threading.Lock()


def get_global_risk_governor(config: Optional[GovernorConfig] = None) -> GlobalRiskGovernor:
    """
    Return the process-wide GlobalRiskGovernor singleton.

    Thread-safe.  Pass *config* only on the first call; subsequent calls
    ignore it and return the already-created instance.
    """
    global _governor_instance
    if _governor_instance is None:
        with _governor_lock:
            if _governor_instance is None:
                _governor_instance = GlobalRiskGovernor(config)
    return _governor_instance
