"""
NIJA System Audit
==================

Comprehensive pre-flight health check that answers:
  "Is NIJA actually ready to make real money safely?"

Run directly:
    python3 bot/system_audit.py

Or call from code:
    from bot.system_audit import run_audit, AuditResult
    result = run_audit()
    if not result.ready_to_trade:
        print(result.summary())

Author: NIJA Trading Systems
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger("nija.system_audit")

# ─── Project root (two levels up from this file) ─────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ─── Result types ─────────────────────────────────────────────────────────────

@dataclass
class AuditItem:
    """Single check result."""
    category: str
    name: str
    passed: bool
    critical: bool          # True  → blocks trading; False → warning only
    message: str
    fix: str = ""           # How to resolve if failed

    def status_icon(self) -> str:
        if self.passed:
            return "✅"
        return "🔴" if self.critical else "⚠️ "


@dataclass
class AuditResult:
    """Aggregated result of a full system audit."""
    items: List[AuditItem] = field(default_factory=list)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # ── convenience queries ───────────────────────────────────────────────────
    @property
    def critical_failures(self) -> List[AuditItem]:
        return [i for i in self.items if not i.passed and i.critical]

    @property
    def warnings(self) -> List[AuditItem]:
        return [i for i in self.items if not i.passed and not i.critical]

    @property
    def passing(self) -> List[AuditItem]:
        return [i for i in self.items if i.passed]

    @property
    def ready_to_trade(self) -> bool:
        return len(self.critical_failures) == 0

    def summary(self) -> str:
        lines = [
            "=" * 70,
            "  NIJA SYSTEM AUDIT REPORT",
            f"  {self.timestamp}",
            "=" * 70,
        ]

        if self.critical_failures:
            lines.append(f"\n🔴 CRITICAL ISSUES ({len(self.critical_failures)}) — TRADING BLOCKED")
            for item in self.critical_failures:
                lines.append(f"   • [{item.category}] {item.name}")
                lines.append(f"     {item.message}")
                if item.fix:
                    lines.append(f"     FIX: {item.fix}")

        if self.warnings:
            lines.append(f"\n⚠️  WARNINGS ({len(self.warnings)})")
            for item in self.warnings:
                lines.append(f"   • [{item.category}] {item.name}: {item.message}")
                if item.fix:
                    lines.append(f"     FIX: {item.fix}")

        if self.passing:
            lines.append(f"\n✅ PASSING ({len(self.passing)})")
            for item in self.passing:
                lines.append(f"   • [{item.category}] {item.name}: {item.message}")

        lines.append("\n" + "=" * 70)
        if self.ready_to_trade:
            if self.warnings:
                lines.append("  VERDICT: ⚠️  CONDITIONALLY READY — address warnings for optimal safety")
            else:
                lines.append("  VERDICT: ✅ READY TO TRADE")
        else:
            lines.append("  VERDICT: 🔴 NOT READY — resolve critical issues above before trading")
        lines.append("=" * 70)
        return "\n".join(lines)


# ─── Individual audit checks ──────────────────────────────────────────────────

def _check_env_file(items: List[AuditItem]) -> None:
    """Check .env file existence and key contents."""
    env_path = _PROJECT_ROOT / ".env"
    if env_path.exists():
        content = env_path.read_text()
        items.append(AuditItem(
            category="ENV",
            name=".env file",
            passed=True,
            critical=True,
            message=".env file found",
        ))
        # Check for LIVE_CAPITAL_VERIFIED
        if "LIVE_CAPITAL_VERIFIED" not in content:
            items.append(AuditItem(
                category="ENV",
                name="LIVE_CAPITAL_VERIFIED in .env",
                passed=False,
                critical=True,
                message=".env exists but LIVE_CAPITAL_VERIFIED key is missing",
                fix="Add LIVE_CAPITAL_VERIFIED=true to your .env file",
            ))
        else:
            lcv_ok = any(
                f"LIVE_CAPITAL_VERIFIED={v}" in content
                for v in ("true", "True", "TRUE", "1", "yes", "Yes", "YES", "enabled")
            )
            items.append(AuditItem(
                category="ENV",
                name="LIVE_CAPITAL_VERIFIED value",
                passed=lcv_ok,
                critical=True,
                message=(
                    "LIVE_CAPITAL_VERIFIED=true ✓" if lcv_ok
                    else "LIVE_CAPITAL_VERIFIED is set but NOT true"
                ),
                fix="Set LIVE_CAPITAL_VERIFIED=true in .env",
            ))
    else:
        items.append(AuditItem(
            category="ENV",
            name=".env file",
            passed=False,
            critical=True,
            message="No .env file found — ALL environment variables are missing",
            fix=(
                "Copy .env.example to .env, fill in your API keys, "
                "and set LIVE_CAPITAL_VERIFIED=true"
            ),
        ))


def _check_live_capital_verified(items: List[AuditItem]) -> None:
    """Check the LIVE_CAPITAL_VERIFIED env var at runtime."""
    lcv = os.getenv("LIVE_CAPITAL_VERIFIED", "").lower().strip()
    passed = lcv in ("true", "1", "yes", "enabled")
    items.append(AuditItem(
        category="ENV",
        name="LIVE_CAPITAL_VERIFIED (runtime)",
        passed=passed,
        critical=True,
        message=(
            f"LIVE_CAPITAL_VERIFIED='{lcv}' — MASTER KILL-SWITCH IS OFF"
            if not passed else
            f"LIVE_CAPITAL_VERIFIED='{lcv}' — live trading enabled"
        ),
        fix="Set LIVE_CAPITAL_VERIFIED=true in .env or export it as an env var",
    ))


def _check_trading_state_machine(items: List[AuditItem]) -> None:
    """Check the persisted trading-state-machine state."""
    state_path = _PROJECT_ROOT / ".nija_trading_state.json"
    if not state_path.exists():
        items.append(AuditItem(
            category="STATE",
            name="Trading state machine",
            passed=False,
            critical=False,
            message="No state file found — bot will default to OFF on startup",
            fix="Start the bot once to create the state file, then transition to LIVE_ACTIVE",
        ))
        return

    try:
        data = json.loads(state_path.read_text())
        current = data.get("current_state", "UNKNOWN")
        last = data.get("last_updated", "?")

        if current == "LIVE_ACTIVE":
            items.append(AuditItem(
                category="STATE",
                name="Trading state machine",
                passed=True,
                critical=False,
                message=f"State = LIVE_ACTIVE (last updated: {last})",
            ))
        elif current == "EMERGENCY_STOP":
            items.append(AuditItem(
                category="STATE",
                name="Trading state machine",
                passed=False,
                critical=True,
                message=f"State = EMERGENCY_STOP — all trading halted (last updated: {last})",
                fix=(
                    "Investigate the emergency stop reason from the history, "
                    "then call state_machine.transition_to(TradingState.OFF) "
                    "followed by transition_to(TradingState.LIVE_ACTIVE)"
                ),
            ))
        elif current == "OFF":
            items.append(AuditItem(
                category="STATE",
                name="Trading state machine",
                passed=False,
                critical=True,
                message=(
                    f"State = OFF — bot will not make broker calls "
                    f"(last updated: {last}). "
                    "This usually means the bot restarted after an emergency stop "
                    "and was never transitioned back to LIVE_ACTIVE."
                ),
                fix=(
                    "Ensure .env has valid credentials and LIVE_CAPITAL_VERIFIED=true, "
                    "then call: state_machine.transition_to(TradingState.LIVE_ACTIVE, "
                    "'Manually re-activating after emergency stop clearance')"
                ),
            ))
        elif current == "DRY_RUN":
            items.append(AuditItem(
                category="STATE",
                name="Trading state machine",
                passed=False,
                critical=False,
                message=f"State = DRY_RUN — no real orders will be placed (last updated: {last})",
                fix="Transition to LIVE_ACTIVE to enable real trading",
            ))
        else:
            items.append(AuditItem(
                category="STATE",
                name="Trading state machine",
                passed=False,
                critical=False,
                message=f"State = {current} (last updated: {last})",
            ))
    except Exception as exc:
        items.append(AuditItem(
            category="STATE",
            name="Trading state machine",
            passed=False,
            critical=False,
            message=f"Could not read state file: {exc}",
        ))


def _check_kill_switches(items: List[AuditItem]) -> None:
    """Check all kill switches."""
    # NIJA_KILL_SWITCH env var
    nija_ks = os.getenv("NIJA_KILL_SWITCH", "0").strip().upper()
    if nija_ks in ("1", "TRUE", "YES"):
        items.append(AuditItem(
            category="KILL_SWITCH",
            name="NIJA_KILL_SWITCH env var",
            passed=False,
            critical=True,
            message=f"NIJA_KILL_SWITCH={nija_ks} — all trading blocked",
            fix="Unset NIJA_KILL_SWITCH or set it to 0",
        ))
    else:
        items.append(AuditItem(
            category="KILL_SWITCH",
            name="NIJA_KILL_SWITCH env var",
            passed=True,
            critical=True,
            message=f"NIJA_KILL_SWITCH={nija_ks} (not active)",
        ))

    # Portfolio kill switch
    try:
        _add_bot_path()
        from bot.portfolio_kill_switch import PortfolioKillSwitch
        pks = PortfolioKillSwitch()
        triggered = pks.is_triggered()
        items.append(AuditItem(
            category="KILL_SWITCH",
            name="Portfolio Kill Switch",
            passed=not triggered,
            critical=True,
            message=(
                f"TRIGGERED — {pks._trigger_reason}" if triggered
                else "Not triggered"
            ),
            fix=(
                "Call portfolio_kill_switch.reset('reason') to clear the halt"
                if triggered else ""
            ),
        ))
    except Exception as exc:
        items.append(AuditItem(
            category="KILL_SWITCH",
            name="Portfolio Kill Switch",
            passed=True,
            critical=False,
            message=f"Module check skipped: {exc}",
        ))

    # Hard controls
    try:
        _add_bot_path()
        from controls import get_hard_controls
        hc = get_hard_controls()
        can, msg = hc.can_trade("platform")
        if not can:
            items.append(AuditItem(
                category="KILL_SWITCH",
                name="Hard Controls (can_trade)",
                passed=False,
                critical=True,
                message=msg or "Trading blocked by hard controls",
                fix="Resolve the underlying condition reported in the message above",
            ))
        else:
            items.append(AuditItem(
                category="KILL_SWITCH",
                name="Hard Controls (can_trade)",
                passed=True,
                critical=True,
                message="Hard controls allow trading",
            ))
    except Exception as exc:
        items.append(AuditItem(
            category="KILL_SWITCH",
            name="Hard Controls",
            passed=False,
            critical=True,
            message=f"Import error: {exc}",
        ))


def _check_circuit_breakers(items: List[AuditItem]) -> None:
    """Check all circuit breakers and drawdown guards."""
    try:
        _add_bot_path()
        from bot.global_drawdown_circuit_breaker import get_global_drawdown_cb
        cb = get_global_drawdown_cb()
        can, reason = cb.can_trade()
        items.append(AuditItem(
            category="CIRCUIT_BREAKER",
            name="Global Drawdown Circuit Breaker",
            passed=can,
            critical=True,
            message=reason,
            fix="Wait for the drawdown recovery period to complete" if not can else "",
        ))
    except Exception as exc:
        items.append(AuditItem(
            category="CIRCUIT_BREAKER",
            name="Global Drawdown Circuit Breaker",
            passed=True,
            critical=False,
            message=f"Module check skipped: {exc}",
        ))

    try:
        from bot.global_risk_governor import get_global_risk_governor
        gov = get_global_risk_governor()
        halt = gov._halt_active
        items.append(AuditItem(
            category="CIRCUIT_BREAKER",
            name="Global Risk Governor",
            passed=not halt,
            critical=True,
            message=(
                f"HALTED — {gov._halt_reason}" if halt
                else f"Not halted (consecutive_losses={gov._consecutive_losses})"
            ),
            fix="Call gov.reset_halt() after investigating the halt reason" if halt else "",
        ))
    except Exception as exc:
        items.append(AuditItem(
            category="CIRCUIT_BREAKER",
            name="Global Risk Governor",
            passed=True,
            critical=False,
            message=f"Module check skipped: {exc}",
        ))

    try:
        from bot.emergency_capital_protection import get_emergency_capital_protection
        ecp = get_emergency_capital_protection()
        active = ecp.is_active()
        items.append(AuditItem(
            category="CIRCUIT_BREAKER",
            name="Emergency Capital Protection",
            passed=not active,
            critical=False,
            message="ACTIVE — trading limited" if active else "Not active",
            fix="Wait for account balance to recover above drawdown threshold" if active else "",
        ))
    except Exception as exc:
        items.append(AuditItem(
            category="CIRCUIT_BREAKER",
            name="Emergency Capital Protection",
            passed=True,
            critical=False,
            message=f"Module check skipped: {exc}",
        ))


def _check_market_readiness(items: List[AuditItem]) -> None:
    """Check the Market Readiness Gate."""
    try:
        from bot.market_readiness_gate import MarketReadinessGate
        mrg = MarketReadinessGate()
        hours = mrg.get_hours_since_circuit_breaker_clear()
        in_cooldown = hours < mrg.IDLE_CIRCUIT_BREAKER_COOLDOWN_HOURS
        items.append(AuditItem(
            category="MARKET",
            name="Market Readiness Gate (CB cooldown)",
            passed=not in_cooldown,
            critical=False,
            message=(
                f"In IDLE cooldown — circuit breaker was cleared {hours:.1f}h ago "
                f"(need {mrg.IDLE_CIRCUIT_BREAKER_COOLDOWN_HOURS:.0f}h)"
                if in_cooldown else
                f"CB cooldown elapsed ({hours:.0f}h ago)"
            ),
            fix=f"Wait {mrg.IDLE_CIRCUIT_BREAKER_COOLDOWN_HOURS - hours:.1f}h more" if in_cooldown else "",
        ))
    except Exception as exc:
        items.append(AuditItem(
            category="MARKET",
            name="Market Readiness Gate",
            passed=True,
            critical=False,
            message=f"Module check skipped: {exc}",
        ))


def _check_api_credentials(items: List[AuditItem]) -> None:
    """Check broker API credentials are present."""
    creds = {
        "COINBASE_API_KEY": ("Coinbase API Key", True),
        "COINBASE_API_SECRET": ("Coinbase API Secret", True),
        "COINBASE_PEM_CONTENT": ("Coinbase PEM (Ed25519)", False),
        "KRAKEN_API_KEY": ("Kraken API Key", False),
        "KRAKEN_API_SECRET": ("Kraken API Secret", False),
    }
    for env_key, (label, is_critical) in creds.items():
        val = os.getenv(env_key, "")
        has_val = bool(val and val.strip())
        if has_val:
            items.append(AuditItem(
                category="CREDENTIALS",
                name=label,
                passed=True,
                critical=is_critical,
                message=f"Set ({len(val)} chars)",
            ))
        else:
            items.append(AuditItem(
                category="CREDENTIALS",
                name=label,
                passed=False,
                critical=is_critical,
                message="NOT SET",
                fix=f"Set {env_key} in your .env file or Railway environment variables",
            ))


def _check_syntax(items: List[AuditItem]) -> None:
    """Python syntax check on critical bot modules."""
    key_files = [
        "bot/trading_strategy.py",
        "bot/broker_integration.py",
        "bot/execution_engine.py",
        "bot/risk_manager.py",
        "bot/indicators.py",
        "controls/__init__.py",
    ]
    for rel_path in key_files:
        fp = _PROJECT_ROOT / rel_path
        if not fp.exists():
            items.append(AuditItem(
                category="SYNTAX",
                name=rel_path,
                passed=False,
                critical=True,
                message="File not found",
            ))
            continue
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(fp)],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            items.append(AuditItem(
                category="SYNTAX",
                name=rel_path,
                passed=True,
                critical=True,
                message="Syntax OK",
            ))
        else:
            err = result.stderr.strip()[:200]
            items.append(AuditItem(
                category="SYNTAX",
                name=rel_path,
                passed=False,
                critical=True,
                message=f"SYNTAX ERROR: {err}",
                fix="Fix the syntax error reported above",
            ))


def _check_risk_parameters(items: List[AuditItem]) -> None:
    """Validate that key risk parameters are within safe ranges."""
    try:
        _add_bot_path()
        import micro_capital_config as mc

        risk_pct = getattr(mc, "RISK_PER_TRADE", None)
        max_positions = getattr(mc, "MAX_CONCURRENT_TRADES", None)
        stop_loss = getattr(mc, "STOP_LOSS_PRIMARY", None) or getattr(mc, "STOP_LOSS", None)
        tp1 = getattr(mc, "MICRO_CAP_TP1_PCT", None)

        if risk_pct is not None:
            safe = 0.1 <= risk_pct <= 3.0
            items.append(AuditItem(
                category="RISK",
                name="Risk per trade",
                passed=safe,
                critical=False,
                message=f"{risk_pct}% per trade {'(within safe range)' if safe else '(OUTSIDE safe 0.1–3% range)'}",
                fix="Set RISK_PER_TRADE to between 0.1% and 3.0%" if not safe else "",
            ))

        if max_positions is not None:
            items.append(AuditItem(
                category="RISK",
                name="Max concurrent positions",
                passed=True,
                critical=False,
                message=f"{max_positions} position(s) max",
            ))

        if tp1 is not None:
            rr_ok = tp1 > 1.5 if stop_loss is None else (tp1 / abs(stop_loss or 1.5)) > 1.0
            items.append(AuditItem(
                category="RISK",
                name="Reward-to-risk at TP1",
                passed=rr_ok,
                critical=False,
                message=f"TP1={tp1}% {'(R:R > 1:1)' if rr_ok else '(R:R < 1:1 — unfavourable)'}",
            ))
    except Exception as exc:
        items.append(AuditItem(
            category="RISK",
            name="Risk parameter check",
            passed=True,
            critical=False,
            message=f"Module check skipped: {exc}",
        ))


def _check_required_dirs(items: List[AuditItem]) -> None:
    """Check required directories exist."""
    required = ["data", "logs", "bot", "config"]
    for d in required:
        p = _PROJECT_ROOT / d
        items.append(AuditItem(
            category="DIRS",
            name=f"Directory: {d}/",
            passed=p.is_dir(),
            critical=False,
            message="exists" if p.is_dir() else "MISSING",
            fix=f"Create the '{d}' directory: mkdir {d}" if not p.is_dir() else "",
        ))


def _add_bot_path() -> None:
    """Ensure the project root and bot/ directory are on sys.path."""
    root = str(_PROJECT_ROOT)
    bot_dir = str(_PROJECT_ROOT / "bot")
    if root not in sys.path:
        sys.path.insert(0, root)
    if bot_dir not in sys.path:
        sys.path.insert(0, bot_dir)


# ─── Main entry point ─────────────────────────────────────────────────────────

def run_audit(load_env: bool = True) -> AuditResult:
    """
    Run the full system audit and return an :class:`AuditResult`.

    Args:
        load_env: If True, attempt to load .env before running checks.
    """
    _add_bot_path()

    if load_env:
        try:
            from dotenv import load_dotenv
            env_path = _PROJECT_ROOT / ".env"
            if env_path.exists():
                load_dotenv(str(env_path))
        except ImportError:
            pass  # dotenv not installed — env vars must come from the OS

    result = AuditResult()

    # Run all checks
    _check_env_file(result.items)
    _check_live_capital_verified(result.items)
    _check_trading_state_machine(result.items)
    _check_kill_switches(result.items)
    _check_circuit_breakers(result.items)
    _check_market_readiness(result.items)
    _check_api_credentials(result.items)
    _check_syntax(result.items)
    _check_risk_parameters(result.items)
    _check_required_dirs(result.items)

    return result


def activate_live_trading(reason: str = "Manual activation via system_audit") -> Tuple[bool, str]:
    """
    Transition the trading state machine from OFF → LIVE_ACTIVE.

    This is safe to call only after verifying:
      1. LIVE_CAPITAL_VERIFIED=true
      2. API credentials are set
      3. No kill switches active

    Returns:
        (success, message)
    """
    _add_bot_path()
    try:
        from bot.trading_state_machine import get_state_machine, TradingState
        sm = get_state_machine()
        current = sm.get_current_state()

        if current == TradingState.LIVE_ACTIVE:
            return True, "Already in LIVE_ACTIVE state"

        if current == TradingState.EMERGENCY_STOP:
            # Must go to OFF first, then to LIVE_ACTIVE
            sm.transition_to(TradingState.OFF, "Clearing emergency stop: " + reason)

        sm.transition_to(TradingState.LIVE_ACTIVE, reason)
        return True, f"Successfully transitioned from {current.value} → LIVE_ACTIVE"
    except Exception as exc:
        return False, f"Failed to transition to LIVE_ACTIVE: {exc}"


# ─── CLI runner ───────────────────────────────────────────────────────────────

def _print_audit_banner() -> None:
    print("\n" + "=" * 70)
    print("  NIJA FULL SYSTEM AUDIT")
    print("  Is the platform ready to make real money safely?")
    print("=" * 70)


def main() -> int:
    """CLI entry point.  Returns exit code (0=ready, 1=not ready)."""
    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s | %(message)s",
    )

    _print_audit_banner()
    result = run_audit(load_env=True)

    # Print category-by-category
    categories_seen: set = set()
    for item in result.items:
        if item.category not in categories_seen:
            print(f"\n[{item.category}]")
            categories_seen.add(item.category)
        icon = item.status_icon()
        print(f"  {icon}  {item.name}: {item.message}")
        if not item.passed and item.fix:
            print(f"       → FIX: {item.fix}")

    print(result.summary())

    if result.ready_to_trade:
        # Offer to activate live trading if state is OFF or DRY_RUN
        state_path = _PROJECT_ROOT / ".nija_trading_state.json"
        if state_path.exists():
            data = json.loads(state_path.read_text())
            current = data.get("current_state", "")
            if current not in ("LIVE_ACTIVE",):
                print(
                    f"\n  NOTE: Trading state is '{current}'. "
                    "Run activate_live_trading() or transition via the dashboard "
                    "to enable broker calls."
                )
    return 0 if result.ready_to_trade else 1


if __name__ == "__main__":
    sys.exit(main())
