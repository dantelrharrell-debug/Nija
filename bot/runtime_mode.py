"""
NIJA Runtime Mode Resolution
============================

Centralized resolution of DRY_RUN_MODE, PAPER_MODE, LIVE_CAPITAL_VERIFIED, and
LIVE_TRADING (alias). This helper provides a single authoritative view of the
active runtime mode to prevent divergent interpretations across subsystems.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Tuple

_TRUTHY = {"1", "true", "yes", "enabled", "on"}


def _env_truthy(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in _TRUTHY


def _env_raw(name: str, default: str = "") -> str:
    return os.getenv(name, default)


@dataclass(frozen=True)
class RuntimeModeResolution:
    dry_run: bool
    paper: bool
    live_capital_verified: bool
    live_trading: bool
    live_authorized: bool
    is_live: bool
    mode: str
    source: str
    conflicts: Tuple[str, ...]
    raw: Dict[str, str]

    def as_dict(self) -> Dict[str, object]:
        return {
            "dry_run": self.dry_run,
            "paper": self.paper,
            "live_capital_verified": self.live_capital_verified,
            "live_trading": self.live_trading,
            "live_authorized": self.live_authorized,
            "is_live": self.is_live,
            "mode": self.mode,
            "source": self.source,
            "conflicts": list(self.conflicts),
            "raw": dict(self.raw),
        }


def resolve_runtime_mode() -> RuntimeModeResolution:
    """Resolve the effective runtime mode using a single shared priority."""
    dry_run = _env_truthy("DRY_RUN_MODE")
    paper = _env_truthy("PAPER_MODE")
    live_capital_verified = _env_truthy("LIVE_CAPITAL_VERIFIED")
    live_trading = _env_truthy("LIVE_TRADING")
    live_authorized = live_capital_verified or live_trading

    conflicts = []
    if dry_run and live_authorized:
        conflicts.append("dry_run_vs_live")
    if paper and live_authorized:
        conflicts.append("paper_vs_live")
    if dry_run and paper:
        conflicts.append("dry_run_vs_paper")

    if dry_run:
        mode = "dry_run"
        source = "DRY_RUN_MODE"
    elif live_authorized:
        mode = "live"
        source = "LIVE_CAPITAL_VERIFIED" if live_capital_verified else "LIVE_TRADING"
    elif paper:
        mode = "paper"
        source = "PAPER_MODE"
    else:
        mode = "monitor"
        source = "none"

    raw = {
        "DRY_RUN_MODE": _env_raw("DRY_RUN_MODE", "false"),
        "PAPER_MODE": _env_raw("PAPER_MODE", "false"),
        "LIVE_CAPITAL_VERIFIED": _env_raw("LIVE_CAPITAL_VERIFIED", "false"),
        "LIVE_TRADING": _env_raw("LIVE_TRADING", "false"),
    }

    return RuntimeModeResolution(
        dry_run=dry_run,
        paper=paper,
        live_capital_verified=live_capital_verified,
        live_trading=live_trading,
        live_authorized=live_authorized,
        is_live=mode == "live",
        mode=mode,
        source=source,
        conflicts=tuple(conflicts),
        raw=raw,
    )
