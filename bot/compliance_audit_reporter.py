"""
NIJA Compliance, Audit & Regulatory Reporting Module
======================================================

Provides institutional-grade compliance infrastructure:

1. **AuditEventLogger**  — tamper-evident append-only log for every AI
   decision, trade, and risk event. Extends / wraps the existing
   ``trading_audit_logger.TradingAuditLogger`` with additional event types.

2. **TradeReplayEngine** — reconstruct the exact decision sequence that
   led to any historical trade, producing an explainability report.

3. **RegulatoryReporter** — generates regulatory-format reports:
   - SEC-style position / trade blotter (Form 13-F style)
   - FINRA-style order audit trail (OATS-inspired)
   - Investor Transparency Report (plain-English portfolio summary)

4. **ComplianceMonitor** — real-time enforcement of compliance rules;
   fires alerts and can block trades when rules are violated.

Usage
-----
    from bot.compliance_audit_reporter import (
        AuditEventLogger,
        TradeReplayEngine,
        RegulatoryReporter,
        ComplianceMonitor,
        get_compliance_suite,
    )

    suite = get_compliance_suite(log_dir="logs/compliance")
    suite.audit.log_trade_entry("BTC-USD", "BUY", 0.1, 65000, {"strategy": "TREND_FOLLOWING"})
    report = suite.reporter.generate_investor_report()

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.compliance")


# ---------------------------------------------------------------------------
# Audit event types (superset of trading_audit_logger.AuditEventType)
# ---------------------------------------------------------------------------

class AuditEventType(str, Enum):
    # Trade lifecycle
    TRADE_SIGNAL         = "TRADE_SIGNAL"
    TRADE_ENTRY          = "TRADE_ENTRY"
    TRADE_EXIT           = "TRADE_EXIT"
    TRADE_STOP_LOSS      = "TRADE_STOP_LOSS"
    TRADE_TAKE_PROFIT    = "TRADE_TAKE_PROFIT"
    TRADE_PARTIAL_EXIT   = "TRADE_PARTIAL_EXIT"
    TRADE_CANCELLED      = "TRADE_CANCELLED"

    # AI / strategy decisions
    AI_SIGNAL_GENERATED  = "AI_SIGNAL_GENERATED"
    AI_PARAMS_UPDATED    = "AI_PARAMS_UPDATED"
    REGIME_CHANGE        = "REGIME_CHANGE"
    STRATEGY_SWITCH      = "STRATEGY_SWITCH"

    # Risk events
    RISK_GATE_BLOCKED    = "RISK_GATE_BLOCKED"
    VAR_BREACH           = "VAR_BREACH"
    DRAWDOWN_LIMIT       = "DRAWDOWN_LIMIT"
    KILL_SWITCH          = "KILL_SWITCH"
    DAILY_LIMIT_HIT      = "DAILY_LIMIT_HIT"

    # Portfolio events
    POSITION_OPENED      = "POSITION_OPENED"
    POSITION_CLOSED      = "POSITION_CLOSED"
    REBALANCE            = "REBALANCE"
    CAPITAL_UPDATED      = "CAPITAL_UPDATED"

    # System events
    SESSION_START        = "SESSION_START"
    SESSION_END          = "SESSION_END"
    SYSTEM_ERROR         = "SYSTEM_ERROR"
    COMPLIANCE_ALERT     = "COMPLIANCE_ALERT"
    INVESTOR_REPORT      = "INVESTOR_REPORT"


# ---------------------------------------------------------------------------
# Audit record
# ---------------------------------------------------------------------------

@dataclass
class AuditRecord:
    event_id:   str
    event_type: AuditEventType
    timestamp:  str
    symbol:     Optional[str]
    user_id:    Optional[str]
    data:       Dict
    checksum:   str = ""

    def compute_checksum(self) -> str:
        payload = json.dumps(
            {"event_id": self.event_id, "event_type": self.event_type,
             "timestamp": self.timestamp, "symbol": self.symbol,
             "user_id": self.user_id, "data": self.data},
            sort_keys=True
        ).encode()
        return hashlib.sha256(payload).hexdigest()

    def to_dict(self) -> Dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "user_id": self.user_id,
            "data": self.data,
            "checksum": self.checksum,
        }


# ---------------------------------------------------------------------------
# 1. Audit Event Logger
# ---------------------------------------------------------------------------

class AuditEventLogger:
    """
    Thread-safe, tamper-evident append-only audit log.

    Records are written as JSON-Lines to ``{log_dir}/audit_events.jsonl``.
    Each record includes a SHA-256 checksum of its content.  A separate
    ``{log_dir}/audit_index.json`` maintains a lightweight index for fast
    queries by symbol, user, event type, or date range.

    Args:
        log_dir: Directory where log files are written.
    """

    def __init__(self, log_dir: str = "logs/compliance"):
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = self._log_dir / "audit_events.jsonl"
        self._lock = threading.RLock()
        self._counter = 0
        self._index: List[Dict] = []   # lightweight in-memory index

        # Try to integrate with existing TradingAuditLogger
        self._legacy: Optional[Any] = None
        try:
            from bot.trading_audit_logger import TradingAuditLogger
            self._legacy = TradingAuditLogger(log_dir=log_dir)
            logger.debug("[AuditEventLogger] Integrated with TradingAuditLogger")
        except ImportError:
            pass

    # ------------------------------------------------------------------
    def _next_event_id(self) -> str:
        with self._lock:
            self._counter += 1
            return f"EVT_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{self._counter:06d}"

    def log(
        self,
        event_type: AuditEventType,
        data: Dict,
        symbol: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> AuditRecord:
        """
        Write a single audit record to the log.

        Args:
            event_type: AuditEventType enum value.
            data: Arbitrary metadata dict.
            symbol: Trading symbol (optional).
            user_id: User identifier (optional).

        Returns:
            The written AuditRecord.
        """
        record = AuditRecord(
            event_id=self._next_event_id(),
            event_type=event_type,
            timestamp=datetime.now(timezone.utc).isoformat(),
            symbol=symbol,
            user_id=user_id,
            data=data,
        )
        record.checksum = record.compute_checksum()

        line = json.dumps(record.to_dict(), separators=(",", ":"))
        with self._lock:
            with self._log_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
            self._index.append({
                "event_id": record.event_id,
                "event_type": record.event_type.value,
                "timestamp": record.timestamp,
                "symbol": symbol,
                "user_id": user_id,
            })

        logger.debug("[Audit] %s %s %s", record.event_type.value, symbol or "", record.event_id)
        return record

    # Convenience wrappers ------------------------------------------------

    def log_trade_entry(self, symbol: str, side: str, size: float, price: float,
                        metadata: Optional[Dict] = None, user_id: Optional[str] = None) -> AuditRecord:
        return self.log(AuditEventType.TRADE_ENTRY, {
            "side": side, "size": size, "price": price, **(metadata or {})
        }, symbol=symbol, user_id=user_id)

    def log_trade_exit(self, symbol: str, side: str, size: float, price: float,
                       pnl: float, reason: str = "", user_id: Optional[str] = None) -> AuditRecord:
        return self.log(AuditEventType.TRADE_EXIT, {
            "side": side, "size": size, "price": price, "pnl": pnl, "reason": reason
        }, symbol=symbol, user_id=user_id)

    def log_ai_signal(self, symbol: str, action: str, confidence: float,
                      strategy: str, metadata: Optional[Dict] = None) -> AuditRecord:
        return self.log(AuditEventType.AI_SIGNAL_GENERATED, {
            "action": action, "confidence": confidence, "strategy": strategy, **(metadata or {})
        }, symbol=symbol)

    def log_risk_block(self, symbol: str, reason: str, signal: Optional[Dict] = None) -> AuditRecord:
        return self.log(AuditEventType.RISK_GATE_BLOCKED, {
            "reason": reason, "signal": signal or {}
        }, symbol=symbol)

    def log_params_update(self, strategy: str, old_params: Dict, new_params: Dict) -> AuditRecord:
        return self.log(AuditEventType.AI_PARAMS_UPDATED, {
            "strategy": strategy, "old_params": old_params, "new_params": new_params
        })

    def log_regime_change(self, old_regime: str, new_regime: str) -> AuditRecord:
        return self.log(AuditEventType.REGIME_CHANGE, {
            "old": old_regime, "new": new_regime
        })

    def log_compliance_alert(self, rule: str, severity: str, detail: str) -> AuditRecord:
        return self.log(AuditEventType.COMPLIANCE_ALERT, {
            "rule": rule, "severity": severity, "detail": detail
        })

    # Query interface -----------------------------------------------------

    def query(
        self,
        event_types: Optional[List[AuditEventType]] = None,
        symbol: Optional[str] = None,
        user_id: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 200,
    ) -> List[Dict]:
        """
        Return matching audit records from log file.

        Args:
            event_types: Filter by one or more AuditEventType.
            symbol: Filter by symbol.
            user_id: Filter by user.
            since: Only return records at or after this UTC datetime.
            limit: Maximum records to return (most recent).

        Returns:
            List of record dicts.
        """
        type_set = {et.value for et in (event_types or [])} if event_types else None
        since_str = since.isoformat() if since else None
        results: List[Dict] = []

        if not self._log_path.exists():
            return results

        with self._lock:
            with self._log_path.open("r", encoding="utf-8") as f:
                lines = f.readlines()

        for line in reversed(lines):
            if len(results) >= limit:
                break
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if type_set and rec.get("event_type") not in type_set:
                continue
            if symbol and rec.get("symbol") != symbol:
                continue
            if user_id and rec.get("user_id") != user_id:
                continue
            if since_str and rec.get("timestamp", "") < since_str:
                continue
            results.append(rec)

        return list(reversed(results))

    def verify_integrity(self) -> Dict:
        """Verify SHA-256 checksums of all records."""
        total = 0
        failures: List[str] = []
        if not self._log_path.exists():
            return {"status": "no_log", "total": 0, "failures": 0}

        with self._log_path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    rec_dict = json.loads(line)
                    stored_cs = rec_dict.pop("checksum", "")
                    rec = AuditRecord(
                        event_id=rec_dict["event_id"],
                        event_type=AuditEventType(rec_dict["event_type"]),
                        timestamp=rec_dict["timestamp"],
                        symbol=rec_dict.get("symbol"),
                        user_id=rec_dict.get("user_id"),
                        data=rec_dict.get("data", {}),
                    )
                    expected = rec.compute_checksum()
                    if expected != stored_cs:
                        failures.append(rec_dict["event_id"])
                    total += 1
                except Exception:
                    pass

        return {
            "status": "PASS" if not failures else "FAIL",
            "total": total,
            "failures": len(failures),
            "failed_ids": failures[:20],
        }


# ---------------------------------------------------------------------------
# 2. Trade Replay Engine
# ---------------------------------------------------------------------------

class TradeReplayEngine:
    """
    Reconstructs the complete decision chain for any historical trade.

    For a given trade or time window, fetches all audit records and
    produces a chronological ``explanation`` showing:
    - Market conditions at signal time
    - Which strategy fired and why
    - How risk parameters were checked
    - Final order details and fills
    - P&L outcome
    """

    def __init__(self, audit_logger: AuditEventLogger):
        self._audit = audit_logger

    def replay_trade(
        self,
        symbol: str,
        trade_id: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> Dict:
        """
        Reconstruct decision history for a symbol.

        Args:
            symbol: Trading pair.
            trade_id: Optional specific trade_id filter (checked in data).
            since: Start of replay window.
            until: End of replay window (default: now).

        Returns:
            Dict with timeline, summary, and explanation.
        """
        if until is None:
            until = datetime.now(timezone.utc)
        if since is None:
            since = until - timedelta(days=1)

        all_records = self._audit.query(symbol=symbol, since=since, limit=500)

        if trade_id:
            all_records = [
                r for r in all_records
                if str(r.get("data", {}).get("trade_id", "")) == str(trade_id)
                or r.get("event_id") == trade_id
            ]

        timeline = []
        summary: Dict[str, Any] = {
            "symbol": symbol,
            "trade_id": trade_id,
            "window": {"since": since.isoformat(), "until": until.isoformat()},
            "event_count": len(all_records),
        }

        entry_price: Optional[float] = None
        exit_price:  Optional[float] = None
        strategy_used: Optional[str]  = None

        for rec in all_records:
            et = rec.get("event_type", "")
            data = rec.get("data", {})
            entry = {
                "timestamp": rec.get("timestamp"),
                "event_type": et,
                "description": self._describe(et, data),
            }
            timeline.append(entry)

            if et == AuditEventType.TRADE_ENTRY.value:
                entry_price = data.get("price")
                strategy_used = data.get("strategy")
            elif et in (AuditEventType.TRADE_EXIT.value, AuditEventType.TRADE_STOP_LOSS.value,
                        AuditEventType.TRADE_TAKE_PROFIT.value):
                exit_price = data.get("price")
                summary["realised_pnl"] = data.get("pnl")
                summary["exit_reason"]  = data.get("reason", et)

        summary["entry_price"]    = entry_price
        summary["exit_price"]     = exit_price
        summary["strategy_used"]  = strategy_used

        explanation = self._build_explanation(timeline, summary)

        return {
            "symbol": symbol,
            "trade_id": trade_id,
            "summary": summary,
            "timeline": timeline,
            "explanation": explanation,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _describe(event_type: str, data: Dict) -> str:
        templates = {
            "TRADE_ENTRY": "Trade entered: {side} {size} @ {price}",
            "TRADE_EXIT":  "Trade exited: {side} {size} @ {price} (PnL={pnl})",
            "AI_SIGNAL_GENERATED": "AI signal: {action} (confidence={confidence:.2f}) via {strategy}",
            "RISK_GATE_BLOCKED": "Risk gate BLOCKED: {reason}",
            "REGIME_CHANGE": "Market regime changed: {old} → {new}",
            "AI_PARAMS_UPDATED": "Parameters updated for {strategy}",
        }
        tpl = templates.get(event_type, "{event_type}")
        try:
            merged = {"event_type": event_type, **data}
            return tpl.format(**{k: v for k, v in merged.items() if isinstance(v, (str, int, float, bool))})
        except (KeyError, ValueError):
            return f"{event_type}: {json.dumps(data)[:120]}"

    @staticmethod
    def _build_explanation(timeline: List[Dict], summary: Dict) -> str:
        lines = ["=== TRADE REPLAY EXPLANATION ==="]
        if summary.get("strategy_used"):
            lines.append(f"Strategy: {summary['strategy_used']}")
        if summary.get("entry_price"):
            lines.append(f"Entry: {summary['entry_price']}")
        if summary.get("exit_price"):
            lines.append(f"Exit: {summary['exit_price']} — {summary.get('exit_reason', 'n/a')}")
        if summary.get("realised_pnl") is not None:
            lines.append(f"Realised P&L: {summary['realised_pnl']:.4f}")
        lines.append(f"\nEvent sequence ({len(timeline)} events):")
        for i, evt in enumerate(timeline[:30]):
            lines.append(f"  {i+1:2d}. [{evt['timestamp']}] {evt['description']}")
        if len(timeline) > 30:
            lines.append(f"  ... ({len(timeline) - 30} more events)")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# 3. Regulatory Reporter
# ---------------------------------------------------------------------------

class RegulatoryReporter:
    """
    Generates regulatory-format reports from audit log data.

    Reports:
    - ``generate_trade_blotter()``  — SEC/FINRA-style trade blotter CSV
    - ``generate_oats_report()``    — FINRA OATS-inspired order audit trail
    - ``generate_investor_report()`` — Plain-English portfolio transparency report
    """

    DISCLAIMER = (
        "DISCLAIMER: This report is generated by an automated trading system "
        "for informational and transparency purposes only. It does not constitute "
        "financial advice, regulatory filing, or investment recommendation. "
        "Consult a licensed financial professional for regulatory guidance."
    )

    def __init__(self, audit_logger: AuditEventLogger, report_dir: str = "logs/reports"):
        self._audit = audit_logger
        self._report_dir = Path(report_dir)
        self._report_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    def generate_trade_blotter(
        self,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        user_id: Optional[str] = None,
    ) -> str:
        """
        Produce a CSV trade blotter in SEC Form 13-F style.

        Returns:
            File path of generated CSV.
        """
        if until is None:
            until = datetime.now(timezone.utc)
        if since is None:
            since = until - timedelta(days=30)

        entries = self._audit.query(
            event_types=[AuditEventType.TRADE_ENTRY],
            user_id=user_id, since=since, limit=10_000
        )
        exits = self._audit.query(
            event_types=[AuditEventType.TRADE_EXIT, AuditEventType.TRADE_STOP_LOSS,
                         AuditEventType.TRADE_TAKE_PROFIT],
            user_id=user_id, since=since, limit=10_000
        )

        rows = []
        for rec in entries:
            d = rec.get("data", {})
            rows.append({
                "Date": rec.get("timestamp", "")[:10],
                "Symbol": rec.get("symbol", ""),
                "Action": "BUY" if d.get("side") == "BUY" else "SELL",
                "Quantity": d.get("size", ""),
                "Price": d.get("price", ""),
                "Notional": round(float(d.get("size", 0)) * float(d.get("price", 0)), 2),
                "Strategy": d.get("strategy", ""),
                "OrderType": d.get("order_type", "MARKET"),
                "PnL": "",
                "Reason": "",
                "EventID": rec.get("event_id", ""),
                "UserID": rec.get("user_id", ""),
            })
        for rec in exits:
            d = rec.get("data", {})
            rows.append({
                "Date": rec.get("timestamp", "")[:10],
                "Symbol": rec.get("symbol", ""),
                "Action": "CLOSE",
                "Quantity": d.get("size", ""),
                "Price": d.get("price", ""),
                "Notional": round(float(d.get("size", 0)) * float(d.get("price", 0)), 2),
                "Strategy": d.get("strategy", ""),
                "OrderType": "MARKET",
                "PnL": d.get("pnl", ""),
                "Reason": d.get("reason", ""),
                "EventID": rec.get("event_id", ""),
                "UserID": rec.get("user_id", ""),
            })

        # Unified fieldnames so all rows have the same schema
        BLOTTER_FIELDS = ["Date", "Symbol", "Action", "Quantity", "Price",
                          "Notional", "Strategy", "OrderType", "PnL", "Reason",
                          "EventID", "UserID"]

        rows.sort(key=lambda r: r.get("Date", ""))
        fname = self._report_dir / f"trade_blotter_{until.strftime('%Y%m%d')}.csv"
        with open(fname, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=BLOTTER_FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        logger.info("[RegReporter] Trade blotter written: %s (%d rows)", fname, len(rows))
        return str(fname)

    # ------------------------------------------------------------------
    def generate_oats_report(
        self,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> str:
        """
        FINRA OATS-inspired Order Audit Trail System report (JSON).

        Returns:
            File path of generated JSON.
        """
        if until is None:
            until = datetime.now(timezone.utc)
        if since is None:
            since = until - timedelta(days=7)

        all_recs = self._audit.query(since=since, limit=50_000)
        oats_entries = []
        for rec in all_recs:
            oats_entries.append({
                "MessageType": rec.get("event_type", ""),
                "OrderKeyDate": rec.get("timestamp", "")[:10],
                "OrderKey": rec.get("event_id", ""),
                "Symbol": rec.get("symbol", ""),
                "BuySellIndicator": rec.get("data", {}).get("side", ""),
                "Quantity": rec.get("data", {}).get("size", ""),
                "Price": rec.get("data", {}).get("price", ""),
                "OrderType": rec.get("data", {}).get("order_type", "MARKET"),
                "EventTimestamp": rec.get("timestamp", ""),
                "UserID": rec.get("user_id", ""),
                "SystemID": "NIJA_AUTONOMOUS_BOT",
                "Checksum": rec.get("checksum", ""),
            })

        report = {
            "ReportType": "OATS_ORDER_AUDIT_TRAIL",
            "GeneratedAt": datetime.now(timezone.utc).isoformat(),
            "Period": {"since": since.isoformat(), "until": until.isoformat()},
            "TotalEvents": len(oats_entries),
            "Disclaimer": self.DISCLAIMER,
            "Events": oats_entries,
        }
        fname = self._report_dir / f"oats_report_{until.strftime('%Y%m%d')}.json"
        with open(fname, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        logger.info("[RegReporter] OATS report written: %s", fname)
        return str(fname)

    # ------------------------------------------------------------------
    def generate_investor_report(
        self,
        portfolio_snapshot: Optional[Dict] = None,
        since: Optional[datetime] = None,
    ) -> str:
        """
        Plain-English investor transparency report (JSON + summary text).

        Args:
            portfolio_snapshot: Output of MultiAssetExecutor.portfolio_snapshot().
            since: Performance period start (default: 30 days ago).

        Returns:
            File path of generated JSON report.
        """
        if since is None:
            since = datetime.now(timezone.utc) - timedelta(days=30)

        trade_entries = self._audit.query(
            event_types=[AuditEventType.TRADE_ENTRY], since=since, limit=10_000
        )
        trade_exits = self._audit.query(
            event_types=[AuditEventType.TRADE_EXIT, AuditEventType.TRADE_STOP_LOSS,
                         AuditEventType.TRADE_TAKE_PROFIT],
            since=since, limit=10_000,
        )

        total_trades = len(trade_entries)
        total_pnl = sum(
            float(r.get("data", {}).get("pnl", 0)) for r in trade_exits
            if r.get("data", {}).get("pnl") is not None
        )
        winning = sum(1 for r in trade_exits if float(r.get("data", {}).get("pnl", 0)) > 0)
        win_rate = (winning / len(trade_exits) * 100) if trade_exits else 0.0

        # Strategy breakdown
        strategy_pnl: Dict[str, float] = {}
        for r in trade_exits:
            strat = r.get("data", {}).get("strategy", "UNKNOWN")
            pnl   = float(r.get("data", {}).get("pnl", 0))
            strategy_pnl[strat] = strategy_pnl.get(strat, 0.0) + pnl

        report = {
            "ReportType": "INVESTOR_TRANSPARENCY_REPORT",
            "GeneratedAt": datetime.now(timezone.utc).isoformat(),
            "Period": {
                "since": since.isoformat(),
                "until": datetime.now(timezone.utc).isoformat(),
            },
            "Performance": {
                "total_closed_trades": len(trade_exits),
                "total_entries": total_trades,
                "total_realised_pnl": round(total_pnl, 4),
                "win_rate_pct": round(win_rate, 2),
                "winning_trades": winning,
                "losing_trades": len(trade_exits) - winning,
            },
            "StrategyBreakdown": {k: round(v, 4) for k, v in strategy_pnl.items()},
            "Portfolio": portfolio_snapshot or {},
            "RiskEvents": len(self._audit.query(
                event_types=[AuditEventType.RISK_GATE_BLOCKED, AuditEventType.VAR_BREACH,
                             AuditEventType.DRAWDOWN_LIMIT, AuditEventType.KILL_SWITCH],
                since=since, limit=10_000,
            )),
            "Disclaimer": self.DISCLAIMER,
            "SystemInfo": {
                "platform": "NIJA Autonomous Trading",
                "version": "1.0",
                "report_integrity": "SHA-256 checksums on all audit records",
            },
        }

        fname = self._report_dir / f"investor_report_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.json"
        with open(fname, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        # Log the report generation itself
        self._audit.log(AuditEventType.INVESTOR_REPORT, {"file": str(fname),
                                                          "period_since": since.isoformat()})
        logger.info("[RegReporter] Investor report written: %s", fname)
        return str(fname)


# ---------------------------------------------------------------------------
# 4. Compliance Monitor
# ---------------------------------------------------------------------------

@dataclass
class ComplianceRule:
    rule_id:   str
    name:      str
    severity:  str           # "CRITICAL" | "HIGH" | "MEDIUM" | "LOW"
    check_fn:  Callable[[Dict], bool]
    message:   str = ""


class ComplianceMonitor:
    """
    Real-time compliance rule enforcement.

    Rules are defined as simple callables that receive a context dict and
    return True (pass) or False (violation). When a rule is violated:
    - An audit record is written.
    - Alert callbacks are invoked.
    - CRITICAL rules block the triggering action.

    Usage::

        monitor = ComplianceMonitor(audit_logger)
        monitor.add_rule(ComplianceRule(
            rule_id="MAX_POSITION_SIZE",
            name="Maximum position size 10 % of portfolio",
            severity="HIGH",
            check_fn=lambda ctx: ctx.get("size_pct", 0) <= 0.10,
            message="Position size exceeds 10 % portfolio limit",
        ))
        passed = monitor.check_trade(signal_dict)
    """

    DEFAULT_RULES: List[Dict] = [
        {"rule_id": "NO_LEVERAGE_BREACH",  "name": "No leverage > 3×",     "severity": "CRITICAL", "size_pct_max": 1.0},
        {"rule_id": "RISK_DISCLOSURE",     "name": "Risk disclosure shown", "severity": "HIGH"},
        {"rule_id": "MAX_DAILY_TRADES",    "name": "Max 200 trades/day",    "severity": "MEDIUM"},
        {"rule_id": "PII_NOT_LOGGED",      "name": "No PII in logs",        "severity": "CRITICAL"},
    ]

    def __init__(
        self,
        audit_logger: AuditEventLogger,
        on_violation: Optional[Callable[[ComplianceRule, Dict], None]] = None,
    ):
        self._audit = audit_logger
        self._on_violation = on_violation
        self._rules: List[ComplianceRule] = []
        self._violations: List[Dict] = []
        self._lock = threading.Lock()
        self._trade_count_today: int = 0
        self._last_reset: str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._load_default_rules()

    def _load_default_rules(self) -> None:
        self.add_rule(ComplianceRule(
            rule_id="MAX_SIZE_PCT",
            name="Position size ≤ 30 % of portfolio",
            severity="HIGH",
            check_fn=lambda ctx: ctx.get("suggested_size_pct", 0.0) <= 0.30,
            message="Signal suggested_size_pct exceeds 30 % hard cap",
        ))
        self.add_rule(ComplianceRule(
            rule_id="CONFIDENCE_FLOOR",
            name="Signal confidence ≥ 0.30",
            severity="MEDIUM",
            check_fn=lambda ctx: ctx.get("confidence", 1.0) >= 0.30,
            message="Signal confidence below minimum threshold",
        ))
        self.add_rule(ComplianceRule(
            rule_id="VALID_SYMBOL",
            name="Symbol must be non-empty",
            severity="CRITICAL",
            check_fn=lambda ctx: bool(ctx.get("symbol", "").strip()),
            message="Empty or missing symbol in signal",
        ))
        self.add_rule(ComplianceRule(
            rule_id="VALID_ACTION",
            name="Action must be BUY/SELL/HOLD",
            severity="CRITICAL",
            check_fn=lambda ctx: ctx.get("action", "") in {"BUY", "SELL", "HOLD"},
            message="Invalid action in signal",
        ))

    def add_rule(self, rule: ComplianceRule) -> None:
        with self._lock:
            self._rules.append(rule)

    def check_trade(self, signal: Dict) -> Tuple[bool, List[str]]:
        """
        Run all compliance rules against a proposed trade signal.

        Returns:
            (allowed, list_of_violation_messages)
            allowed=False means at least one CRITICAL rule failed.
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with self._lock:
            if today != self._last_reset:
                self._trade_count_today = 0
                self._last_reset = today
            self._trade_count_today += 1

        violations: List[str] = []
        critical_fail = False

        with self._lock:
            rules = list(self._rules)

        for rule in rules:
            try:
                passed = rule.check_fn(signal)
            except Exception as exc:
                logger.warning("[Compliance] Rule %s error: %s", rule.rule_id, exc)
                passed = True   # don't block on check errors

            if not passed:
                msg = rule.message or f"Rule {rule.rule_id} violated"
                violations.append(f"[{rule.severity}] {rule.name}: {msg}")
                self._audit.log_compliance_alert(rule.rule_id, rule.severity, msg)
                with self._lock:
                    self._violations.append({
                        "rule_id": rule.rule_id,
                        "severity": rule.severity,
                        "signal": signal,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                if rule.severity == "CRITICAL":
                    critical_fail = True
                if self._on_violation:
                    try:
                        self._on_violation(rule, signal)
                    except Exception:
                        pass

        allowed = not critical_fail
        if violations:
            logger.warning("[Compliance] %d violation(s): %s", len(violations), violations)
        return allowed, violations

    def compliance_report(self) -> Dict:
        with self._lock:
            return {
                "total_rules": len(self._rules),
                "total_violations": len(self._violations),
                "violations_by_severity": {
                    "CRITICAL": sum(1 for v in self._violations if v["severity"] == "CRITICAL"),
                    "HIGH":     sum(1 for v in self._violations if v["severity"] == "HIGH"),
                    "MEDIUM":   sum(1 for v in self._violations if v["severity"] == "MEDIUM"),
                    "LOW":      sum(1 for v in self._violations if v["severity"] == "LOW"),
                },
                "trades_checked_today": self._trade_count_today,
                "recent_violations": self._violations[-20:],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }


# ---------------------------------------------------------------------------
# Suite factory
# ---------------------------------------------------------------------------

@dataclass
class ComplianceSuite:
    """Bundle of all compliance components for easy injection."""
    audit:    AuditEventLogger
    replay:   TradeReplayEngine
    reporter: RegulatoryReporter
    monitor:  ComplianceMonitor


_suite_instance: Optional[ComplianceSuite] = None
_suite_lock = threading.Lock()


def get_compliance_suite(
    log_dir: str = "logs/compliance",
    report_dir: str = "logs/reports",
    reset: bool = False,
) -> ComplianceSuite:
    """
    Return (or create) the module-level ComplianceSuite singleton.

    Args:
        log_dir: Directory for audit event logs.
        report_dir: Directory for generated regulatory reports.
        reset: Force creation of a new instance.

    Returns:
        ComplianceSuite with all four components configured.
    """
    global _suite_instance
    with _suite_lock:
        if _suite_instance is None or reset:
            audit    = AuditEventLogger(log_dir=log_dir)
            replay   = TradeReplayEngine(audit)
            reporter = RegulatoryReporter(audit, report_dir=report_dir)
            monitor  = ComplianceMonitor(audit)
            _suite_instance = ComplianceSuite(audit, replay, reporter, monitor)
    return _suite_instance
