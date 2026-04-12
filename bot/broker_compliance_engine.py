"""
NIJA Full Broker Compliance Engine
=====================================

Every order passes through a sequential compliance gate before reaching
any broker's ``place_market_order``.  The engine is fully broker-agnostic:
add a new exchange by registering it in :mod:`broker_isolation_registry`.

Gate sequence (per order)
--------------------------
1. **IsolationCheck**   — is this broker allowed to execute?
2. **MicroCapModeCheck** — derive effective minimums from account balance
3. **CapitalCheck**     — does the account have enough capital?
4. **OrderSizeCheck**   — does the order meet exchange minimums?
5. **SymbolCheck**      — is the symbol valid for this exchange?
6. **RiskCheck**        — does the order pass the per-exchange risk plugin?
7. **AuditLog**         — every check is recorded regardless of outcome

Key design decisions
--------------------
* SELL orders bypass checks 3–6 (protective-exit override).
* Coinbase micro-cap bypass is applied at check 2 (MICRO_CAP mode).
* Kraken risk is logged but never blocks (IsolatedRiskPlugin).
* ``ComplianceResult.skip_result`` is the sentinel returned to callers
  when execution is blocked, matching the ``broker_isolated_skip`` format.

Usage
-----
    from bot.broker_compliance_engine import get_compliance_engine
    from bot.broker_compliance_engine import ComplianceContext

    engine = get_compliance_engine()
    ctx = ComplianceContext(
        broker_name="coinbase",
        symbol="ADA-USD",
        side="buy",
        usd_size=5.0,
        balance=12.0,
    )
    result = engine.check(ctx)
    if not result.passed:
        return result.skip_result
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger("nija.compliance_engine")

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ComplianceContext:
    """All information needed to evaluate an order."""
    broker_name: str
    symbol: str
    side: str               # "buy" | "sell"
    usd_size: float
    balance: float = 0.0
    score: float = 0.0
    force_liquidate: bool = False
    user_id: str = ""
    extra: Dict = field(default_factory=dict)


@dataclass
class CheckRecord:
    """Single check outcome, appended to the audit trail."""
    check_name: str
    passed: bool
    reason: str
    elapsed_ms: float = 0.0


@dataclass
class ComplianceResult:
    """Full compliance gate outcome."""
    passed: bool
    reason: str = ""
    checks: List[CheckRecord] = field(default_factory=list)
    mode: str = ""  # execution mode (micro_cap / standard / scaled)

    @property
    def skip_result(self) -> Dict:
        """Broker-compatible skip sentinel for blocked orders."""
        return {
            "status": "broker_isolated_skip",
            "compliance_reason": self.reason,
            "partial_fill": False,
            "filled_pct": 0.0,
        }

    def to_dict(self) -> Dict:
        return {
            "passed": self.passed,
            "reason": self.reason,
            "mode": self.mode,
            "checks": [
                {"check": c.check_name, "passed": c.passed,
                 "reason": c.reason, "elapsed_ms": round(c.elapsed_ms, 2)}
                for c in self.checks
            ],
        }


# ---------------------------------------------------------------------------
# Compliance engine
# ---------------------------------------------------------------------------

class BrokerComplianceEngine:
    """Full per-exchange compliance gate.

    All checks are independent and additive: a later check sees the
    adjusted state from earlier checks (e.g., micro-cap mode lowers
    the effective minimum before the order-size check runs).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._audit_log: List[Dict] = []
        self._max_audit: int = 1000

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def check(self, ctx: ComplianceContext) -> ComplianceResult:
        """Run all compliance checks for *ctx*.

        Parameters
        ----------
        ctx:
            :class:`ComplianceContext` describing the proposed order.

        Returns
        -------
        ComplianceResult
            ``passed=True`` → order may proceed.
            ``passed=False`` → caller should ``return result.skip_result``.
        """
        checks: List[CheckRecord] = []
        mode_label = "unknown"

        # ── 0. Force-liquidate bypass ────────────────────────────────
        if ctx.force_liquidate:
            rec = CheckRecord(
                check_name="ForceLiquidateBypass",
                passed=True,
                reason="force_liquidate=True — all checks bypassed",
            )
            checks.append(rec)
            result = ComplianceResult(passed=True, reason="FORCE_LIQUIDATE", checks=checks)
            self._audit(ctx, result)
            return result

        # ── 1. SELL always passes (protective exit override) ─────────
        if ctx.side.lower() == "sell":
            rec = CheckRecord(
                check_name="ForceSellBypass",
                passed=True,
                reason="SELL — protective exit bypass",
            )
            checks.append(rec)
            result = ComplianceResult(
                passed=True, reason="SELL_BYPASS", checks=checks, mode="sell_bypass"
            )
            self._audit(ctx, result)
            return result

        # ── 2. Derive execution mode from balance ────────────────────
        try:
            from bot.micro_cap_execution_mode import get_execution_mode
        except ImportError:
            from micro_cap_execution_mode import get_execution_mode  # type: ignore
        mode = get_execution_mode(ctx.balance)
        mode_label = mode.mode_type.value
        eff_min = mode.get_effective_order_min(ctx.broker_name)

        if mode.is_suspended():
            rec = self._record("MicroCapModeCheck", False, "SUSPENDED: balance below floor")
            checks.append(rec)
            return self._fail("SUSPENDED", checks, mode_label)

        checks.append(self._record(
            "MicroCapModeCheck", True,
            f"mode={mode_label} eff_min=${eff_min:.2f}",
        ))

        # ── 3. Isolation check ───────────────────────────────────────
        try:
            from bot.broker_isolation_registry import get_broker_isolation_registry
        except ImportError:
            from broker_isolation_registry import get_broker_isolation_registry  # type: ignore
        registry = get_broker_isolation_registry()
        skip = registry.check_execution(ctx.broker_name, ctx.side)
        if skip is not None:
            rec = self._record(
                "IsolationCheck", False,
                f"{ctx.broker_name} isolated — BUY blocked",
            )
            checks.append(rec)
            return self._fail(f"BROKER_ISOLATED:{ctx.broker_name}", checks, mode_label)
        checks.append(self._record("IsolationCheck", True, "execution allowed"))

        # ── 4. Capital floor check (BUY only) ────────────────────────
        entry = registry.get_or_default(ctx.broker_name)
        if not entry.capital.ignore_global_capital_floor and ctx.balance > 0:
            if ctx.balance < entry.capital.min_capital_usd:
                rec = self._record(
                    "CapitalCheck", False,
                    f"balance ${ctx.balance:.2f} < floor ${entry.capital.min_capital_usd:.2f}",
                )
                checks.append(rec)
                return self._fail("CAPITAL_FLOOR", checks, mode_label)
        checks.append(self._record("CapitalCheck", True, "ok"))

        # ── 5. Order size check ──────────────────────────────────────
        # Micro-cap mode: sub-minimum allowed on Coinbase
        if ctx.usd_size > 0 and not mode.is_micro_cap():
            if ctx.usd_size < eff_min:
                rec = self._record(
                    "OrderSizeCheck", False,
                    f"size ${ctx.usd_size:.2f} < min ${eff_min:.2f}",
                )
                checks.append(rec)
                return self._fail("ORDER_TOO_SMALL", checks, mode_label)
        checks.append(self._record(
            "OrderSizeCheck", True,
            f"${ctx.usd_size:.2f} ≥ ${eff_min:.2f} (micro_cap={mode.is_micro_cap()})",
        ))

        # ── 6. Symbol check ──────────────────────────────────────────
        allowed_symbols = entry.filter_symbols([ctx.symbol])
        if entry.symbol_filter is not None and not allowed_symbols:
            rec = self._record(
                "SymbolCheck", False,
                f"{ctx.symbol} not in {ctx.broker_name} allowlist",
            )
            checks.append(rec)
            return self._fail(f"SYMBOL_NOT_ALLOWED:{ctx.symbol}", checks, mode_label)
        checks.append(self._record("SymbolCheck", True, "ok"))

        # ── 7. Risk check ────────────────────────────────────────────
        try:
            from bot.risk_sizing_adapter import RiskSizingAdapterFactory
            from bot.risk_plugin_base import RiskContext
        except ImportError:
            from risk_sizing_adapter import RiskSizingAdapterFactory  # type: ignore
            from risk_plugin_base import RiskContext  # type: ignore

        risk_ctx = RiskContext(
            score=ctx.score,
            symbol=ctx.symbol,
            side=ctx.side,
            size_usd=ctx.usd_size,
            broker_name=ctx.broker_name,
            balance=ctx.balance,
        )
        adapter = RiskSizingAdapterFactory.for_broker(ctx.broker_name)
        risk_result = adapter.evaluate_risk(risk_ctx)
        if not risk_result.passed:
            rec = self._record("RiskCheck", False, risk_result.reason)
            checks.append(rec)
            return self._fail(f"RISK_BLOCKED:{risk_result.reason}", checks, mode_label)
        checks.append(self._record("RiskCheck", True, risk_result.reason))

        # ── All checks passed ────────────────────────────────────────
        result = ComplianceResult(
            passed=True,
            reason="ALL_CHECKS_PASSED",
            checks=checks,
            mode=mode_label,
        )
        self._audit(ctx, result)
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _record(name: str, passed: bool, reason: str) -> CheckRecord:
        return CheckRecord(check_name=name, passed=passed, reason=reason)

    def _fail(
        self, reason: str, checks: List[CheckRecord], mode: str
    ) -> ComplianceResult:
        result = ComplianceResult(
            passed=False, reason=reason, checks=checks, mode=mode
        )
        self._audit(None, result)
        return result

    def _audit(self, ctx: Optional[ComplianceContext], result: ComplianceResult) -> None:
        record: Dict = {
            "ts": time.time(),
            "broker": ctx.broker_name if ctx else "unknown",
            "symbol": ctx.symbol if ctx else "",
            "side": ctx.side if ctx else "",
            "usd_size": ctx.usd_size if ctx else 0,
            "passed": result.passed,
            "reason": result.reason,
            "mode": result.mode,
        }
        with self._lock:
            self._audit_log.append(record)
            if len(self._audit_log) > self._max_audit:
                self._audit_log = self._audit_log[-self._max_audit:]
        if not result.passed:
            logger.info(
                "🔒 Compliance BLOCKED [%s %s %s $%.2f]: %s",
                record["broker"], record["side"].upper(),
                record["symbol"], record["usd_size"], result.reason,
            )

    def get_audit_log(self, limit: int = 50) -> List[Dict]:
        """Return the last *limit* audit records."""
        with self._lock:
            return list(self._audit_log[-limit:])


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_instance: Optional[BrokerComplianceEngine] = None
_instance_lock = threading.Lock()


def get_compliance_engine() -> BrokerComplianceEngine:
    """Return (or create) the process-wide :class:`BrokerComplianceEngine`."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = BrokerComplianceEngine()
    return _instance
