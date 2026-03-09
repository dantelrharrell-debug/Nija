"""
NIJA Monitoring + Control Center
==================================

Unified command-and-control panel that aggregates signals from every NIJA
subsystem, presents a live dashboard, and exposes control primitives for
pausing, resuming, and reconfiguring the bot at runtime.

Subsystems integrated
---------------------
* Market Data Engine          — feed health / bar counts
* Market Inefficiency Scanner — signal throughput / type breakdown
* AI Strategy Evolution Engine — generation, champion fitness
* Risk-of-Ruin Engine          — current ruin probability
* Global Risk Governor         — gate verdicts / daily P&L
* Strategy Health Monitor      — per-strategy composite scores
* Exchange Kill-Switch         — gate status per exchange
* Kill Switch                  — global halt state
* Alert Manager                — active alert counts

Control actions available
-------------------------
* ``pause()``   / ``resume()``   — halt / restart new entries globally.
* ``halt_strategy(name)``        — suspend a single strategy.
* ``resume_strategy(name)``      — re-enable a suspended strategy.
* ``set_risk_param(key, value)`` — update a risk governor parameter at runtime.
* ``trigger_evolution_cycle()``  — force an immediate strategy evolution pass.
* ``run_mis_scan(symbols)``      — run an on-demand MIS scan.

Public API
----------
::

    from bot.monitoring_control_center import get_monitoring_control_center

    mcc = get_monitoring_control_center()

    # Full dashboard snapshot
    dashboard = mcc.get_dashboard()

    # Pause all new entries
    mcc.pause("manual risk review")

    # Resume
    mcc.resume()

    # On-demand MIS scan
    signals = mcc.run_mis_scan(["BTC-USD", "ETH-USD"])

    # Trigger evolution
    evo_report = mcc.trigger_evolution_cycle()

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nija.monitoring_control_center")

# ---------------------------------------------------------------------------
# Optional subsystem imports — all degrade gracefully.
# ---------------------------------------------------------------------------

def _try_import(primary: str, fallback: str):
    try:
        mod = __import__(primary)
        return mod
    except ImportError:
        try:
            mod = __import__(fallback)
            return mod
        except ImportError:
            return None


# ---------------------------------------------------------------------------
# Control state
# ---------------------------------------------------------------------------

@dataclass
class ControlState:
    """Mutable global control state."""
    paused: bool = False
    pause_reason: str = ""
    paused_at: Optional[str] = None
    paused_strategies: List[str] = field(default_factory=list)
    risk_overrides: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "paused": self.paused,
            "pause_reason": self.pause_reason,
            "paused_at": self.paused_at,
            "paused_strategies": list(self.paused_strategies),
            "risk_overrides": dict(self.risk_overrides),
        }


# ---------------------------------------------------------------------------
# Monitoring + Control Center
# ---------------------------------------------------------------------------

class MonitoringControlCenter:
    """
    Unified monitoring dashboard and runtime control panel for all NIJA
    subsystems.
    """

    def __init__(self) -> None:
        self._state = ControlState()
        self._lock = threading.Lock()
        self._event_log: List[Dict[str, Any]] = []
        self._dashboard_cache: Optional[Dict[str, Any]] = None
        self._cache_ts: float = 0.0
        self._cache_ttl: float = 5.0   # seconds

        logger.info("🖥️  MonitoringControlCenter initialised.")

    # ------------------------------------------------------------------
    # Control actions
    # ------------------------------------------------------------------

    def pause(self, reason: str = "manual") -> None:
        """Halt all new trade entries globally."""
        with self._lock:
            self._state.paused = True
            self._state.pause_reason = reason
            self._state.paused_at = datetime.now(timezone.utc).isoformat()
        self._log_event("PAUSED", {"reason": reason})
        logger.warning("⏸️  MCC: trading paused — %s", reason)

    def resume(self) -> None:
        """Resume all new trade entries."""
        with self._lock:
            self._state.paused = False
            self._state.pause_reason = ""
            self._state.paused_at = None
        self._log_event("RESUMED", {})
        logger.info("▶️  MCC: trading resumed.")

    def halt_strategy(self, strategy_name: str) -> None:
        """Suspend a single strategy from taking new entries."""
        with self._lock:
            if strategy_name not in self._state.paused_strategies:
                self._state.paused_strategies.append(strategy_name)
        self._log_event("STRATEGY_HALTED", {"strategy": strategy_name})
        logger.warning("🚫 MCC: strategy '%s' halted.", strategy_name)

    def resume_strategy(self, strategy_name: str) -> None:
        """Re-enable a previously halted strategy."""
        with self._lock:
            try:
                self._state.paused_strategies.remove(strategy_name)
            except ValueError:
                pass
        self._log_event("STRATEGY_RESUMED", {"strategy": strategy_name})
        logger.info("✅ MCC: strategy '%s' resumed.", strategy_name)

    def is_paused(self) -> bool:
        """Return True if global trading is paused."""
        return self._state.paused

    def is_strategy_paused(self, strategy_name: str) -> bool:
        """Return True if the named strategy is halted."""
        return strategy_name in self._state.paused_strategies

    def set_risk_param(self, key: str, value: Any) -> None:
        """Store a runtime risk parameter override."""
        with self._lock:
            self._state.risk_overrides[key] = value
        self._log_event("RISK_PARAM_SET", {"key": key, "value": value})
        logger.info("⚙️  MCC: risk override %s = %s", key, value)

    # ------------------------------------------------------------------
    # On-demand actions
    # ------------------------------------------------------------------

    def run_mis_scan(self, symbols: List[str]) -> List[Any]:
        """Run an on-demand Market Inefficiency Scanner scan."""
        try:
            from market_inefficiency_scanner import get_market_inefficiency_scanner
        except ImportError:
            try:
                from bot.market_inefficiency_scanner import get_market_inefficiency_scanner
            except ImportError:
                logger.warning("⚠️ MIS not available.")
                return []
        mis = get_market_inefficiency_scanner()
        signals = mis.scan(symbols)
        self._log_event("MIS_SCAN", {"symbols": symbols, "signal_count": len(signals)})
        return signals

    def trigger_evolution_cycle(self) -> Dict[str, Any]:
        """Force an immediate AI strategy evolution cycle."""
        try:
            from ai_strategy_evolution_engine import get_ai_strategy_evolution_engine
        except ImportError:
            try:
                from bot.ai_strategy_evolution_engine import get_ai_strategy_evolution_engine
            except ImportError:
                logger.warning("⚠️ Evolution engine not available.")
                return {"error": "evolution_engine_unavailable"}
        evo = get_ai_strategy_evolution_engine()
        report = evo.evolve_cycle()
        self._log_event("EVOLUTION_CYCLE", {"generation": report.get("generation")})
        return report

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    def get_dashboard(self, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Return a full system dashboard snapshot.

        Results are cached for ``_cache_ttl`` seconds.  Pass
        ``force_refresh=True`` to bypass the cache.
        """
        now = time.monotonic()
        with self._lock:
            if (
                not force_refresh
                and self._dashboard_cache is not None
                and (now - self._cache_ts) < self._cache_ttl
            ):
                return self._dashboard_cache

        dashboard: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "control": self._state.to_dict(),
        }

        dashboard["market_data_engine"] = self._collect_mde()
        dashboard["market_inefficiency_scanner"] = self._collect_mis()
        dashboard["ai_strategy_evolution"] = self._collect_evo()
        dashboard["risk_of_ruin"] = self._collect_ror()
        dashboard["global_risk_governor"] = self._collect_grg()
        dashboard["strategy_health"] = self._collect_health()
        dashboard["exchange_kill_switch"] = self._collect_eks()
        dashboard["recent_events"] = list(self._event_log[-20:])

        with self._lock:
            self._dashboard_cache = dashboard
            self._cache_ts = now

        return dashboard

    # ------------------------------------------------------------------
    # Subsystem collectors
    # ------------------------------------------------------------------

    def _collect_mde(self) -> Dict[str, Any]:
        try:
            from market_data_engine import get_market_data_engine
        except ImportError:
            try:
                from bot.market_data_engine import get_market_data_engine
            except ImportError:
                return {"status": "unavailable"}
        try:
            engine = get_market_data_engine()
            return {"status": "ok", **engine.get_summary()}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": str(exc)}

    def _collect_mis(self) -> Dict[str, Any]:
        try:
            from market_inefficiency_scanner import get_market_inefficiency_scanner
        except ImportError:
            try:
                from bot.market_inefficiency_scanner import get_market_inefficiency_scanner
            except ImportError:
                return {"status": "unavailable"}
        try:
            mis = get_market_inefficiency_scanner()
            r = mis.get_report()
            return {"status": "ok", **r}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": str(exc)}

    def _collect_evo(self) -> Dict[str, Any]:
        try:
            from ai_strategy_evolution_engine import get_ai_strategy_evolution_engine
        except ImportError:
            try:
                from bot.ai_strategy_evolution_engine import get_ai_strategy_evolution_engine
            except ImportError:
                return {"status": "unavailable"}
        try:
            evo = get_ai_strategy_evolution_engine()
            r = evo.get_report()
            return {
                "status": "ok",
                "generation": r.get("generation"),
                "champion_genome_id": r.get("champion_genome_id"),
                "champion_fitness": r.get("champion_fitness"),
                "avg_fitness": r.get("avg_fitness"),
                "population_size": r.get("population_size"),
            }
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": str(exc)}

    def _collect_ror(self) -> Dict[str, Any]:
        try:
            from risk_of_ruin_engine import RiskOfRuinEngine
        except ImportError:
            try:
                from bot.risk_of_ruin_engine import RiskOfRuinEngine
            except ImportError:
                return {"status": "unavailable"}
        return {"status": "ok", "note": "call RiskOfRuinEngine.calculate() for full analysis"}

    def _collect_grg(self) -> Dict[str, Any]:
        try:
            from global_risk_governor import get_global_risk_governor
        except ImportError:
            try:
                from bot.global_risk_governor import get_global_risk_governor
            except ImportError:
                return {"status": "unavailable"}
        try:
            gov = get_global_risk_governor()
            report = gov.get_report() if hasattr(gov, "get_report") else {}
            return {"status": "ok", **report}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": str(exc)}

    def _collect_health(self) -> Dict[str, Any]:
        try:
            from strategy_health_monitor import get_strategy_health_monitor
        except ImportError:
            try:
                from bot.strategy_health_monitor import get_strategy_health_monitor
            except ImportError:
                return {"status": "unavailable"}
        try:
            shm = get_strategy_health_monitor()
            report = shm.get_summary() if hasattr(shm, "get_summary") else {}
            return {"status": "ok", **report}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": str(exc)}

    def _collect_eks(self) -> Dict[str, Any]:
        try:
            from exchange_kill_switch import get_exchange_kill_switch_protector
        except ImportError:
            try:
                from bot.exchange_kill_switch import get_exchange_kill_switch_protector
            except ImportError:
                return {"status": "unavailable"}
        try:
            eks = get_exchange_kill_switch_protector()
            report = eks.get_status() if hasattr(eks, "get_status") else {}
            return {"status": "ok", **report}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": str(exc)}

    # ------------------------------------------------------------------
    # Event log
    # ------------------------------------------------------------------

    def _log_event(self, event_type: str, data: Dict[str, Any]) -> None:
        event = {
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **data,
        }
        with self._lock:
            self._event_log.append(event)
            if len(self._event_log) > 1000:
                self._event_log = self._event_log[-1000:]

    def get_event_log(self, n: int = 50) -> List[Dict[str, Any]]:
        """Return the *n* most recent control events."""
        with self._lock:
            return list(self._event_log[-n:])


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_mcc_instance: Optional[MonitoringControlCenter] = None
_mcc_lock = threading.Lock()


def get_monitoring_control_center() -> MonitoringControlCenter:
    """Return the process-level singleton MonitoringControlCenter."""
    global _mcc_instance
    if _mcc_instance is None:
        with _mcc_lock:
            if _mcc_instance is None:
                _mcc_instance = MonitoringControlCenter()
    return _mcc_instance


# ---------------------------------------------------------------------------
# CLI self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    mcc = get_monitoring_control_center()

    print("▶  Initial state:", mcc.is_paused())
    mcc.pause("CLI self-test")
    print("⏸  Paused:", mcc.is_paused())
    mcc.resume()
    print("▶  Resumed:", mcc.is_paused())

    mcc.halt_strategy("ApexTrend")
    print("🚫 ApexTrend halted:", mcc.is_strategy_paused("ApexTrend"))
    mcc.resume_strategy("ApexTrend")
    print("✅ ApexTrend resumed:", mcc.is_strategy_paused("ApexTrend"))

    mcc.set_risk_param("max_daily_loss_pct", 0.03)

    print("\n🖥️  Dashboard snapshot:")
    dashboard = mcc.get_dashboard(force_refresh=True)
    # Print control and module statuses (omit full population list)
    for section, content in dashboard.items():
        if section in ("recent_events",):
            continue
        if isinstance(content, dict):
            status = content.get("status", "—")
            print(f"  {section}: status={status}")
        else:
            print(f"  {section}: {content}")

    print("\n📋 Event log (last 5):")
    for evt in mcc.get_event_log(5):
        print(f"  [{evt['timestamp']}] {evt['type']}")
