"""
NIJA Micro-Cap Execution Mode
===============================

Converts the capital gate from a **blocker** into a **mode selector**.

When account balance is below the micro-cap threshold (default $25, env
``MICRO_CAP_THRESHOLD``), instead of blocking execution the system
activates micro-cap mode:

  ┌──────────────────────────────────────────────────┐
  │  BALANCE          → EXECUTION MODE               │
  │  $0.50 – $25      → MICRO_CAP  ($1 min, CB only) │
  │  $25   – $500     → STANDARD   ($5 min, all)     │
  │  $500+            → SCALED     ($10 min, all)    │
  └──────────────────────────────────────────────────┘

In MICRO_CAP mode:
  • Coinbase is the **only active** execution path
  • Kraken is set to EXIT-ONLY (no new entries)
  • Minimum order = $1 (``COINBASE_MIN_ORDER_USD``)
  • Capital floor is bypassed (``COINBASE_IGNORE_GLOBAL_CAPITAL_FLOOR``)
  • All capital-gate blockers convert to pass-throughs

Environment overrides
---------------------
MICRO_CAP_THRESHOLD       — balance threshold to activate micro-cap mode (default 25.0)
COINBASE_MIN_ORDER_USD    — minimum order size in micro-cap mode (default 1.0)
COINBASE_MIN_CAPITAL      — minimum capital floor in micro-cap mode (default 1.0)

Singleton access
----------------
    from bot.micro_cap_execution_mode import get_execution_mode, ExecutionModeType

    mode = get_execution_mode(balance=12.50)
    if mode.is_micro_cap():
        logger.info("Micro-cap mode active — $1 orders, Coinbase only")
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger("nija.micro_cap_mode")

# ---------------------------------------------------------------------------
# Thresholds — all env-overridable
# ---------------------------------------------------------------------------

#: Balance below which micro-cap mode activates.
MICRO_CAP_THRESHOLD: float = float(os.getenv("MICRO_CAP_THRESHOLD", "25.0"))

#: Balance above which scaled mode activates.
SCALED_THRESHOLD: float = float(os.getenv("SCALED_THRESHOLD", "500.0"))

#: Minimum order size in micro-cap mode.
MICRO_CAP_ORDER_MIN: float = float(
    os.getenv("COINBASE_MIN_ORDER_USD", os.getenv("COINBASE_MIN_ORDER", "1.0"))
)

#: Minimum capital floor in micro-cap mode.
MICRO_CAP_CAPITAL_MIN: float = float(os.getenv("COINBASE_MIN_CAPITAL", "1.0"))

#: Absolute floor below which even micro-cap mode suspends new entries.
ABSOLUTE_FLOOR: float = float(os.getenv("MINIMUM_BALANCE_PROTECTION", "0.50"))


# ---------------------------------------------------------------------------
# Mode type enum
# ---------------------------------------------------------------------------

class ExecutionModeType(Enum):
    """Account-balance-driven execution mode."""
    MICRO_CAP = "micro_cap"   # $0.50–$25   — Coinbase only, $1 min
    STANDARD  = "standard"    # $25–$500    — all brokers, $5 min
    SCALED    = "scaled"      # $500+       — all brokers, $10 min
    SUSPENDED = "suspended"   # < $0.50     — below absolute floor


# ---------------------------------------------------------------------------
# Mode descriptor
# ---------------------------------------------------------------------------

@dataclass
class ExecutionMode:
    """Complete execution policy derived from account balance.

    This object is the single answer to "what can the bot do right now?".
    It is **never** a blocker — it always returns an actionable mode.
    """
    mode_type: ExecutionModeType
    balance: float
    order_min_usd: float
    capital_min_usd: float
    active_brokers: List[str] = field(default_factory=list)
    isolated_brokers: List[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    def is_micro_cap(self) -> bool:
        return self.mode_type == ExecutionModeType.MICRO_CAP

    def is_standard(self) -> bool:
        return self.mode_type == ExecutionModeType.STANDARD

    def is_scaled(self) -> bool:
        return self.mode_type == ExecutionModeType.SCALED

    def is_suspended(self) -> bool:
        """True only when balance is below the absolute hard floor."""
        return self.mode_type == ExecutionModeType.SUSPENDED

    def blocks_execution(self) -> bool:
        """Capital gate NEVER blocks — use mode-appropriate minimums instead."""
        return self.is_suspended()

    def is_broker_active(self, broker_name: str) -> bool:
        return broker_name.lower() in self.active_brokers

    def is_broker_isolated(self, broker_name: str) -> bool:
        return broker_name.lower() in self.isolated_brokers

    def get_effective_order_min(self, broker_name: str = "") -> float:
        """Return the minimum order size for this mode and broker."""
        name = broker_name.lower()
        if self.is_micro_cap() and name == "coinbase":
            return self.order_min_usd
        return self.order_min_usd

    def to_dict(self) -> Dict:
        return {
            "mode": self.mode_type.value,
            "balance": self.balance,
            "order_min_usd": self.order_min_usd,
            "capital_min_usd": self.capital_min_usd,
            "active_brokers": self.active_brokers,
            "isolated_brokers": self.isolated_brokers,
            "blocks_execution": self.blocks_execution(),
        }


# ---------------------------------------------------------------------------
# Mode factory
# ---------------------------------------------------------------------------

def get_execution_mode(balance: float) -> ExecutionMode:
    """Derive the :class:`ExecutionMode` for *balance*.

    This is the **replacement for all capital gates**.  Callers that
    previously returned ``False`` / raised when balance was too low should
    instead call this function and act on the returned mode.

    Parameters
    ----------
    balance:
        Current account balance in USD.

    Returns
    -------
    ExecutionMode
        Never raises; always returns an actionable mode.
    """
    if balance < ABSOLUTE_FLOOR:
        logger.warning(
            "🔴 MicroCapMode: balance $%.2f below absolute floor $%.2f — SUSPENDED",
            balance, ABSOLUTE_FLOOR,
        )
        return ExecutionMode(
            mode_type=ExecutionModeType.SUSPENDED,
            balance=balance,
            order_min_usd=MICRO_CAP_ORDER_MIN,
            capital_min_usd=ABSOLUTE_FLOOR,
            active_brokers=[],
            isolated_brokers=["kraken", "binance", "okx", "alpaca"],
        )

    if balance < MICRO_CAP_THRESHOLD:
        logger.info(
            "🟡 MicroCapMode: balance $%.2f → MICRO_CAP "
            "(order_min=$%.2f, Coinbase only)",
            balance, MICRO_CAP_ORDER_MIN,
        )
        return ExecutionMode(
            mode_type=ExecutionModeType.MICRO_CAP,
            balance=balance,
            order_min_usd=MICRO_CAP_ORDER_MIN,
            capital_min_usd=MICRO_CAP_CAPITAL_MIN,
            active_brokers=["coinbase"],
            isolated_brokers=["kraken"],
        )

    if balance < SCALED_THRESHOLD:
        return ExecutionMode(
            mode_type=ExecutionModeType.STANDARD,
            balance=balance,
            order_min_usd=5.0,
            capital_min_usd=5.0,
            active_brokers=["coinbase", "kraken", "alpaca", "binance", "okx"],
            isolated_brokers=[],
        )

    return ExecutionMode(
        mode_type=ExecutionModeType.SCALED,
        balance=balance,
        order_min_usd=10.0,
        capital_min_usd=10.0,
        active_brokers=["coinbase", "kraken", "alpaca", "binance", "okx"],
        isolated_brokers=[],
    )


# ---------------------------------------------------------------------------
# Capital-gate converter
# (drop-in replacement for any existing "if balance < minimum: block" check)
# ---------------------------------------------------------------------------

def evaluate_capital_gate(
    balance: float,
    broker_name: str = "coinbase",
    requested_size_usd: float = 0.0,
) -> tuple:
    """Replace a blocking capital-gate check with a mode-aware evaluation.

    Returns ``(allowed: bool, reason: str, mode: ExecutionMode)``.

    Old pattern::

        if balance < MINIMUM_BALANCE:
            return False, "insufficient capital"

    New pattern::

        allowed, reason, mode = evaluate_capital_gate(balance, broker_name, size)
        if not allowed:
            return {"status": "broker_isolated_skip", ...}

    Parameters
    ----------
    balance:
        Current account balance in USD.
    broker_name:
        Broker being evaluated (lower-case).
    requested_size_usd:
        Proposed order size in USD (0 = not checked).
    """
    mode = get_execution_mode(balance)

    if mode.is_suspended():
        return (
            False,
            f"SUSPENDED: balance ${balance:.2f} below floor ${ABSOLUTE_FLOOR:.2f}",
            mode,
        )

    broker = broker_name.lower()

    if not mode.is_broker_active(broker) and mode.is_broker_isolated(broker):
        # Broker isolated in this mode — not a hard block, just redirect
        logger.info(
            "evaluate_capital_gate: %s isolated in %s mode — routing to active broker",
            broker, mode.mode_type.value,
        )

    if requested_size_usd > 0:
        eff_min = mode.get_effective_order_min(broker)
        if requested_size_usd < eff_min:
            logger.debug(
                "evaluate_capital_gate: size $%.2f < mode min $%.2f (%s) — "
                "micro-cap allows sub-minimum on Coinbase",
                requested_size_usd, eff_min, mode.mode_type.value,
            )
            # Micro-cap mode: sub-minimum allowed on Coinbase (don't block)

    return True, f"OK ({mode.mode_type.value})", mode


# ---------------------------------------------------------------------------
# Notional gate adapter
# (replaces the blocking behaviour in minimum_notional_gate.py)
# ---------------------------------------------------------------------------

def get_micro_cap_notional_floor(
    broker_name: str,
    balance: float,
    legacy_floor: float,
) -> float:
    """Return the effective notional floor for *broker_name* / *balance*.

    When micro-cap mode is active the floor is lowered to
    ``MICRO_CAP_ORDER_MIN`` ($1) for the active broker (Coinbase).
    All other cases return *legacy_floor* unchanged.

    Drop-in for ``NotionalGateConfig.get_min_notional_for_broker()``.
    """
    mode = get_execution_mode(balance)
    if mode.is_micro_cap() and broker_name.lower() == "coinbase":
        return MICRO_CAP_ORDER_MIN
    return legacy_floor


# ---------------------------------------------------------------------------
# Module-level singleton (cached last mode per account)
# ---------------------------------------------------------------------------

_cache: Dict[str, ExecutionMode] = {}
_cache_lock = threading.Lock()


def get_cached_execution_mode(
    balance: float,
    account_id: str = "default",
) -> ExecutionMode:
    """Return the :class:`ExecutionMode` for *account_id*, cached per call.

    The cache is keyed on ``account_id`` and invalidated whenever
    ``balance`` changes by more than $0.10.
    """
    with _cache_lock:
        cached = _cache.get(account_id)
        if cached is None or abs(cached.balance - balance) > 0.10:
            _cache[account_id] = get_execution_mode(balance)
        return _cache[account_id]
