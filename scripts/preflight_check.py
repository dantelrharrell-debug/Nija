#!/usr/bin/env python3
"""
NIJA Pre-Flight Check
======================

Comprehensive startup validation that must pass before the bot begins trading.

Usage
-----
    python scripts/preflight_check.py           # full report
    python scripts/preflight_check.py --fix     # attempt auto-fixes (state machine reset)
    python scripts/preflight_check.py --json    # machine-readable JSON output

Checks performed
----------------
1. Python dependencies    — all packages in requirements.txt are importable
2. Environment variables  — .env exists; REQUIRED vars are set
3. Exchange credentials   — at least one exchange credential set is present
4. Trading state machine  — not stuck in EMERGENCY_STOP
5. Nonce state            — Kraken nonce lead is not poisoned
6. System audit           — runs bot/system_audit.py checks
7. Data directories       — data/, logs/, config/ exist and are writable

Exit codes
----------
0  All checks passed — bot is ready to trade
1  One or more CRITICAL issues found — bot will not start
2  Warnings only — bot may start but with degraded functionality
"""

from __future__ import annotations

import argparse
import importlib
import json as _json
import os
import sys
import time
from pathlib import Path
from typing import Any

# ── Path bootstrap ─────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "bot"))

try:
    from dotenv import load_dotenv
    load_dotenv(_REPO_ROOT / ".env")
except ImportError:
    pass

# ── Colours ────────────────────────────────────────────────────────────────────
_BOLD   = "\033[1m"
_GREEN  = "\033[32m"
_YELLOW = "\033[33m"
_RED    = "\033[31m"
_CYAN   = "\033[36m"
_DIM    = "\033[2m"
_RESET  = "\033[0m"

def _c(color: str, text: str) -> str:
    return f"{color}{text}{_RESET}"


# ── Result helpers ─────────────────────────────────────────────────────────────

class CheckResult:
    def __init__(self, name: str, passed: bool, critical: bool, message: str, fix: str = ""):
        self.name     = name
        self.passed   = passed
        self.critical = critical
        self.message  = message
        self.fix      = fix

    def to_dict(self) -> dict:
        return {
            "name": self.name, "passed": self.passed,
            "critical": self.critical, "message": self.message, "fix": self.fix,
        }

    def icon(self) -> str:
        if self.passed:
            return _c(_GREEN, "✅")
        if self.critical:
            return _c(_RED, "❌")
        return _c(_YELLOW, "⚠️ ")


# ── Individual checks ──────────────────────────────────────────────────────────

def check_dependencies() -> list[CheckResult]:
    """Verify that key packages from requirements.txt are importable."""
    results: list[CheckResult] = []

    packages = [
        ("dotenv",           "python-dotenv",         True),
        ("pandas",           "pandas",                True),
        ("numpy",            "numpy",                 True),
        ("flask",            "Flask",                 True),
        ("krakenex",         "krakenex",              False),
        ("pykrakenapi",      "pykrakenapi",           False),
        ("coinbase",         "coinbase-advanced-py",  False),
        ("requests",         "requests",              True),
        ("ntplib",           "ntplib",                False),
        ("fastapi",          "fastapi",               False),
        ("uvicorn",          "uvicorn",               False),
        ("sqlalchemy",       "SQLAlchemy",            False),
        ("jwt",              "PyJWT",                 False),
    ]

    missing_critical: list[str] = []
    missing_optional: list[str] = []

    for module_name, pkg_name, is_critical in packages:
        try:
            importlib.import_module(module_name)
        except ImportError:
            if is_critical:
                missing_critical.append(pkg_name)
            else:
                missing_optional.append(pkg_name)

    if missing_critical:
        results.append(CheckResult(
            name="Python dependencies (critical)",
            passed=False,
            critical=True,
            message=f"Missing: {', '.join(missing_critical)}",
            fix=f"Run: pip install -r requirements.txt",
        ))
    else:
        results.append(CheckResult(
            name="Python dependencies (critical)",
            passed=True,
            critical=True,
            message="All critical packages importable",
        ))

    if missing_optional:
        results.append(CheckResult(
            name="Python dependencies (optional)",
            passed=False,
            critical=False,
            message=f"Missing optional packages: {', '.join(missing_optional)}",
            fix="Run: pip install -r requirements.txt",
        ))
    else:
        results.append(CheckResult(
            name="Python dependencies (optional)",
            passed=True,
            critical=False,
            message="All optional packages importable",
        ))

    return results


def check_env_file() -> list[CheckResult]:
    """Check .env exists and required variables are set."""
    results: list[CheckResult] = []

    env_path = _REPO_ROOT / ".env"
    if not env_path.exists():
        results.append(CheckResult(
            name=".env file",
            passed=False,
            critical=True,
            message="No .env file found — all environment variables are missing",
            fix="Run: python scripts/setup_env.py",
        ))
        return results

    results.append(CheckResult(
        name=".env file",
        passed=True,
        critical=False,
        message=f".env found ({env_path})",
    ))

    required = [
        ("LIVE_CAPITAL_VERIFIED", True),
    ]
    for var, critical in required:
        val = os.getenv(var, "")
        if not val:
            results.append(CheckResult(
                name=f"ENV: {var}",
                passed=False,
                critical=critical,
                message=f"{var} is not set",
                fix=f"Add {var}=true to .env (only when ready to trade live)",
            ))
        else:
            results.append(CheckResult(
                name=f"ENV: {var}",
                passed=True,
                critical=critical,
                message=f"{var}={val}",
            ))

    return results


def check_exchange_credentials() -> list[CheckResult]:
    """Verify at least one exchange credential set is configured."""
    results: list[CheckResult] = []

    has_kraken_platform = bool(
        os.getenv("KRAKEN_PLATFORM_API_KEY") and os.getenv("KRAKEN_PLATFORM_API_SECRET")
    )
    has_kraken_legacy = bool(
        os.getenv("KRAKEN_API_KEY") and os.getenv("KRAKEN_API_SECRET")
    )
    has_coinbase = bool(
        os.getenv("COINBASE_API_KEY") and os.getenv("COINBASE_API_SECRET")
    )

    if has_kraken_platform:
        results.append(CheckResult(
            name="Kraken PLATFORM credentials",
            passed=True, critical=True,
            message="KRAKEN_PLATFORM_API_KEY and SECRET are set",
        ))
    else:
        results.append(CheckResult(
            name="Kraken PLATFORM credentials",
            passed=False, critical=True,
            message="KRAKEN_PLATFORM_API_KEY or KRAKEN_PLATFORM_API_SECRET not set",
            fix="Add KRAKEN_PLATFORM_API_KEY and KRAKEN_PLATFORM_API_SECRET to .env",
        ))

    if has_kraken_legacy:
        results.append(CheckResult(
            name="Kraken legacy credentials",
            passed=True, critical=False,
            message="KRAKEN_API_KEY and SECRET are set (fallback)",
        ))

    if has_coinbase:
        results.append(CheckResult(
            name="Coinbase credentials",
            passed=True, critical=False,
            message="COINBASE_API_KEY and SECRET are set (secondary broker)",
        ))
    else:
        results.append(CheckResult(
            name="Coinbase credentials",
            passed=False, critical=False,
            message="COINBASE_API_KEY or COINBASE_API_SECRET not set (optional secondary broker)",
            fix="Add COINBASE_API_KEY and COINBASE_API_SECRET to .env",
        ))

    if not has_kraken_platform and not has_kraken_legacy and not has_coinbase:
        results.append(CheckResult(
            name="Exchange credentials",
            passed=False, critical=True,
            message="No exchange credentials configured — cannot connect to any broker",
            fix="Run: python scripts/setup_env.py",
        ))

    return results


def check_state_machine() -> list[CheckResult]:
    """Check trading state machine is not stuck in EMERGENCY_STOP."""
    results: list[CheckResult] = []

    state_path = _REPO_ROOT / ".nija_trading_state.json"
    if not state_path.exists():
        results.append(CheckResult(
            name="Trading state machine",
            passed=False, critical=False,
            message="No state file found — bot will default to OFF on startup",
            fix="Start the bot once to initialise the state file",
        ))
        return results

    try:
        import json
        data = json.loads(state_path.read_text())
        current = data.get("current_state", "UNKNOWN")
        last = data.get("last_updated", "?")

        if current == "LIVE_ACTIVE":
            results.append(CheckResult(
                name="Trading state machine",
                passed=True, critical=False,
                message=f"State = LIVE_ACTIVE (last updated: {last})",
            ))
        elif current == "EMERGENCY_STOP":
            # Find last emergency reason
            reason = "unknown"
            for entry in reversed(data.get("history", [])):
                if entry.get("to") == "EMERGENCY_STOP":
                    reason = entry.get("reason", "unknown")[:100]
                    break
            results.append(CheckResult(
                name="Trading state machine",
                passed=False, critical=True,
                message=f"State = EMERGENCY_STOP — all trading halted. Reason: {reason}",
                fix="Run: python scripts/reset_state_machine.py",
            ))
        elif current == "OFF":
            results.append(CheckResult(
                name="Trading state machine",
                passed=False, critical=True,
                message=f"State = OFF — bot will not make broker calls (last updated: {last})",
                fix="Ensure LIVE_CAPITAL_VERIFIED=true, then run: python scripts/reset_state_machine.py",
            ))
        elif current == "DRY_RUN":
            results.append(CheckResult(
                name="Trading state machine",
                passed=False, critical=False,
                message=f"State = DRY_RUN — no real orders will be placed (last updated: {last})",
                fix="Run: python scripts/reset_state_machine.py --to LIVE_ACTIVE",
            ))
        else:
            results.append(CheckResult(
                name="Trading state machine",
                passed=True, critical=False,
                message=f"State = {current} (last updated: {last})",
            ))
    except Exception as exc:
        results.append(CheckResult(
            name="Trading state machine",
            passed=False, critical=False,
            message=f"Could not read state file: {exc}",
        ))

    return results


def check_nonce_state() -> list[CheckResult]:
    """Check if the Kraken nonce is in a healthy state."""
    results: list[CheckResult] = []

    try:
        from global_kraken_nonce import get_global_nonce_stats, get_global_nonce_manager

        stats = get_global_nonce_stats()
        mgr   = get_global_nonce_manager()

        last_nonce = stats["last_nonce"]
        now_ms     = int(time.time() * 1000)
        lead_ms    = last_nonce - now_ms

        if stats["trading_paused"]:
            pause_rem = stats["pause_remaining_s"]
            results.append(CheckResult(
                name="Nonce: trading pause",
                passed=False, critical=True,
                message=f"Nonce manager has paused trading for {pause_rem:.0f}s more (post-nuclear reset)",
                fix="Wait for pause to expire, or restart the bot with NIJA_FORCE_NONCE_RESYNC=1",
            ))
        else:
            results.append(CheckResult(
                name="Nonce: trading pause",
                passed=True, critical=False,
                message="No nonce-triggered trading pause active",
            ))

        nuclear = stats["nuclear_reset_count"]
        if nuclear >= 2:
            results.append(CheckResult(
                name="Nonce: nuclear resets",
                passed=False, critical=True,
                message=f"{nuclear} nuclear nonce resets in this session — nonce likely poisoned",
                fix=(
                    "Deep-probe mode has been auto-activated. "
                    "If trading still fails: restart with NIJA_DEEP_NONCE_RESET=1, "
                    "or consider creating a new Kraken API key."
                ),
            ))
        elif nuclear == 1:
            results.append(CheckResult(
                name="Nonce: nuclear resets",
                passed=False, critical=False,
                message="1 nuclear nonce reset in this session — monitoring",
                fix="If errors continue, restart with NIJA_DEEP_NONCE_RESET=1",
            ))
        else:
            results.append(CheckResult(
                name="Nonce: nuclear resets",
                passed=True, critical=False,
                message="No nuclear resets this session",
            ))

        # Lead check
        lead_min = lead_ms / 60_000
        if lead_ms > 60 * 60_000:  # > 60 min
            results.append(CheckResult(
                name="Nonce: lead vs wall-clock",
                passed=False, critical=True,
                message=f"Nonce is {lead_min:.1f} min ahead of wall-clock — ceiling-jump territory",
                fix=(
                    "Restart with NIJA_NONCE_CEILING_JUMP=1 or run: "
                    "python bot/reset_kraken_nonce.py"
                ),
            ))
        elif lead_ms > 10 * 60_000:  # > 10 min
            results.append(CheckResult(
                name="Nonce: lead vs wall-clock",
                passed=False, critical=False,
                message=f"Nonce is {lead_min:.1f} min ahead — deep-probe may be needed",
                fix="Restart with NIJA_DEEP_NONCE_RESET=1 if Kraken rejects connections",
            ))
        elif lead_ms > 0:
            results.append(CheckResult(
                name="Nonce: lead vs wall-clock",
                passed=True, critical=False,
                message=f"Nonce is {lead_ms}ms ahead of wall-clock — healthy",
            ))
        else:
            results.append(CheckResult(
                name="Nonce: lead vs wall-clock",
                passed=False, critical=False,
                message=f"Nonce is behind wall-clock by {abs(lead_ms)}ms — will auto-advance on next call",
            ))

        if stats["deep_reset_active"]:
            results.append(CheckResult(
                name="Nonce: deep-reset mode",
                passed=False, critical=False,
                message="Deep-reset mode is active (120-min probe coverage) — nonce recovery in progress",
                fix="Monitor logs; if errors persist, create a new Kraken API key",
            ))

        if mgr.detect_other_process_running():
            results.append(CheckResult(
                name="Nonce: duplicate process",
                passed=False, critical=True,
                message="Another NIJA process appears to be holding the nonce lock",
                fix="Stop all duplicate NIJA processes: ps aux | grep bot.py  →  kill <pid>",
            ))
        else:
            results.append(CheckResult(
                name="Nonce: duplicate process",
                passed=True, critical=False,
                message="No duplicate NIJA process detected",
            ))

    except ImportError:
        results.append(CheckResult(
            name="Nonce state",
            passed=False, critical=False,
            message="global_kraken_nonce module not importable (missing dependencies?)",
            fix="Run: pip install -r requirements.txt",
        ))

    return results


def check_system_audit() -> list[CheckResult]:
    """Delegate to bot/system_audit.py for comprehensive checks."""
    results: list[CheckResult] = []
    try:
        from system_audit import run_audit
        audit = run_audit(load_env=True)
        for item in audit.critical_failures:
            results.append(CheckResult(
                name=f"Audit: {item.name}",
                passed=False, critical=True,
                message=item.message,
                fix=getattr(item, "fix", ""),
            ))
        for item in audit.warnings:
            results.append(CheckResult(
                name=f"Audit: {item.name}",
                passed=False, critical=False,
                message=item.message,
                fix=getattr(item, "fix", ""),
            ))
    except Exception as exc:
        results.append(CheckResult(
            name="System audit",
            passed=False, critical=False,
            message=f"Could not run system_audit: {exc}",
            fix="Ensure bot/ is on the Python path and dependencies are installed",
        ))
    return results


def check_directories() -> list[CheckResult]:
    """Verify required directories exist and are writable."""
    results: list[CheckResult] = []
    for rel_dir in ("data", "logs", "config", "bot"):
        dirpath = _REPO_ROOT / rel_dir
        if not dirpath.exists():
            results.append(CheckResult(
                name=f"Directory: {rel_dir}/",
                passed=False, critical=False,
                message=f"{dirpath} does not exist",
                fix=f"Run: mkdir -p {rel_dir}",
            ))
        elif not os.access(dirpath, os.W_OK):
            results.append(CheckResult(
                name=f"Directory: {rel_dir}/",
                passed=False, critical=False,
                message=f"{dirpath} is not writable",
                fix=f"Run: chmod u+w {rel_dir}",
            ))
        else:
            results.append(CheckResult(
                name=f"Directory: {rel_dir}/",
                passed=True, critical=False,
                message=f"{dirpath} exists and is writable",
            ))
    return results


# ── Auto-fix ───────────────────────────────────────────────────────────────────

def apply_auto_fixes(all_results: list[CheckResult]) -> list[str]:
    """Apply safe automatic fixes; return list of actions taken."""
    actions: list[str] = []

    critical_names = {r.name for r in all_results if not r.passed and r.critical}

    # Auto-fix: reset EMERGENCY_STOP → OFF (+ auto-activate if LIVE_CAPITAL_VERIFIED=true)
    if "Trading state machine" in " ".join(critical_names) or any(
        "EMERGENCY_STOP" in r.message for r in all_results if not r.passed
    ):
        try:
            sys.path.insert(0, str(_REPO_ROOT / "scripts"))
            import reset_state_machine
            rc = reset_state_machine.main(["--force"])
            if rc == 0:
                actions.append("State machine: reset EMERGENCY_STOP → OFF (and attempted LIVE_ACTIVE)")
        except Exception as exc:
            actions.append(f"State machine reset failed: {exc}")

    return actions


# ── Print helpers ──────────────────────────────────────────────────────────────

def _print_results(results: list[CheckResult]) -> None:
    for r in results:
        print(f"  {r.icon()}  {r.name}")
        if not r.passed:
            print(f"      {_c(_DIM, r.message)}")
            if r.fix:
                print(f"      {_c(_CYAN, 'FIX: ' + r.fix)}")


def _print_summary(results: list[CheckResult]) -> tuple[int, int, int]:
    failures = [r for r in results if not r.passed and r.critical]
    warnings = [r for r in results if not r.passed and not r.critical]
    passes   = [r for r in results if r.passed]
    return len(failures), len(warnings), len(passes)


# ── Main ───────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="NIJA pre-flight validation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--fix",   action="store_true", help="Attempt safe auto-fixes.")
    parser.add_argument("--json",  action="store_true", help="Output machine-readable JSON.")
    parser.add_argument("--quick", action="store_true", help="Skip slow checks (nonce, audit).")
    args = parser.parse_args(argv)

    print(_c(_BOLD, "\n══════════════════════════════════════════"))
    print(_c(_BOLD, "  NIJA Pre-Flight Check"))
    print(_c(_BOLD, "══════════════════════════════════════════\n"))

    all_results: list[CheckResult] = []

    sections: list[tuple[str, Any]] = [
        ("Python Dependencies",    check_dependencies),
        ("Environment Variables",  check_env_file),
        ("Exchange Credentials",   check_exchange_credentials),
        ("Trading State Machine",  check_state_machine),
        ("Required Directories",   check_directories),
    ]
    if not args.quick:
        sections += [
            ("Kraken Nonce State",  check_nonce_state),
            ("System Audit",        check_system_audit),
        ]

    for section_name, check_fn in sections:
        print(_c(_BOLD + _CYAN, f"  ── {section_name}"))
        try:
            section_results = check_fn()
        except Exception as exc:
            section_results = [CheckResult(
                name=section_name, passed=False, critical=False,
                message=f"Check threw an exception: {exc}",
            )]
        _print_results(section_results)
        all_results.extend(section_results)
        print()

    n_failures, n_warnings, n_passes = _print_summary(all_results)

    if args.fix and n_failures > 0:
        print(_c(_BOLD + _YELLOW, "  ── Auto-Fix"))
        actions = apply_auto_fixes(all_results)
        for a in actions:
            print(f"  {_c(_GREEN, '🔧')}  {a}")
        if actions:
            print()
            print(_c(_YELLOW, "  Re-running checks after fixes …\n"))
            return main(["--quick"] if args.quick else [])
        print()

    # ── Summary ────────────────────────────────────────────────────────────
    print("══════════════════════════════════════════")
    if n_failures == 0 and n_warnings == 0:
        print(_c(_GREEN + _BOLD, "  ✅  VERDICT: READY TO TRADE"))
    elif n_failures == 0:
        print(_c(_YELLOW + _BOLD, f"  ⚠️   VERDICT: {n_warnings} warning(s) — bot may start with degraded functionality"))
    else:
        print(_c(_RED + _BOLD, f"  🔴  VERDICT: {n_failures} critical issue(s) — bot CANNOT trade"))
        print()
        print(_c(_BOLD, "  Quick fix commands:"))
        if any("setup_env" in r.fix for r in all_results if not r.passed and r.critical):
            print("    python scripts/setup_env.py")
        if any("reset_state" in r.fix for r in all_results if not r.passed and r.critical):
            print("    python scripts/reset_state_machine.py")
        if any("pip install" in r.fix for r in all_results if not r.passed and r.critical):
            print("    pip install -r requirements.txt")
    print(f"  Passed: {n_passes}   Warnings: {n_warnings}   Critical: {n_failures}")
    print("══════════════════════════════════════════\n")

    if args.json:
        import json
        print(json.dumps([r.to_dict() for r in all_results], indent=2))

    if n_failures > 0:
        return 1
    if n_warnings > 0:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
