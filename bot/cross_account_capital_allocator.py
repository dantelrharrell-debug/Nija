"""
NIJA Cross-Account Capital Allocator
======================================

Distributes a platform-account trade size proportionally across all connected
user accounts so that every user's position is sized relative to their own
balance while respecting global risk limits.

Architecture
------------
::

    CrossAccountCapitalAllocator
        │
        ├── PlatformAccountLayer  (user list + platform presence check)
        ├── GlobalCapitalManager  (balance registry + global risk ceiling)
        └── MultiAccountBrokerManager  (live balance fetch per user)

    Typical call sequence (per trading cycle)
    ------------------------------------------
    allocator = get_cross_account_allocator()

    # 1. Refresh balances from live brokers:
    allocator.refresh_balances(multi_account_manager)

    # 2. Compute each user's trade size given the platform trade USD:
    for user_id in allocator.user_ids():
        size = allocator.compute_user_size(user_id, platform_size_usd=200.0)

    # 3. Gate individual trade against global risk ceiling:
    if allocator.approve_trade(user_id, size_usd):
        broker.execute_order(symbol, side, size_usd, size_type="quote")

Design Goals
------------
* **Proportional sizing** – a user with twice the platform balance gets twice
  the position size.  A user with half the balance gets half.
* **Floor / ceiling** – configurable minimum (``min_size_usd``) and maximum
  (``max_size_pct`` of user balance) guards prevent dust trades and
  oversized positions.
* **Global risk ceiling** – delegates to ``GlobalCapitalManager.can_open_trade``
  to enforce the portfolio-wide 6 % risk cap.
* **Platform-gated** – returns zero allocation for any exchange where NIJA has
  no platform account (delegates to ``PlatformAccountLayer.has_platform_account``).

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger("nija.cross_account_allocator")

# ---------------------------------------------------------------------------
# Default allocation parameters
# ---------------------------------------------------------------------------

#: Minimum trade size (USD) for a user account — below this the trade is skipped.
DEFAULT_MIN_TRADE_USD = 5.0

#: Maximum position as a fraction of the user's account balance (50 %).
DEFAULT_MAX_POSITION_PCT = 0.50

#: Maximum position size in USD (hard ceiling across all users).
DEFAULT_MAX_POSITION_USD = 10_000.0


# ---------------------------------------------------------------------------
# Per-user allocation result
# ---------------------------------------------------------------------------


@dataclass
class UserAllocation:
    """Allocation decision for a single user account on one exchange."""

    user_id: str
    exchange: str
    user_balance_usd: float
    platform_balance_usd: float
    platform_size_usd: float
    allocated_size_usd: float
    approved: bool
    reason: str
    scale_factor: float = 0.0   # user_balance / platform_balance


# ---------------------------------------------------------------------------
# Allocator
# ---------------------------------------------------------------------------


class CrossAccountCapitalAllocator:
    """
    Computes proportional per-user trade sizes from a platform trade size.

    Register balances once per trading cycle via ``refresh_balances()``, then
    call ``compute_user_size()`` for each user before order submission.
    """

    def __init__(
        self,
        min_trade_usd: float = DEFAULT_MIN_TRADE_USD,
        max_position_pct: float = DEFAULT_MAX_POSITION_PCT,
        max_position_usd: float = DEFAULT_MAX_POSITION_USD,
    ) -> None:
        self._min_trade_usd = min_trade_usd
        self._max_position_pct = max_position_pct
        self._max_position_usd = max_position_usd
        self._lock = threading.Lock()

        # {user_id: {exchange: balance_usd}}
        self._user_balances: Dict[str, Dict[str, float]] = {}
        # {exchange: balance_usd}  — platform account balances
        self._platform_balances: Dict[str, float] = {}

        self._gcm = self._load_gcm()
        self._pal = self._load_pal()

    # ------------------------------------------------------------------
    # Balance registration
    # ------------------------------------------------------------------

    def register_platform_balance(self, exchange: str, balance_usd: float) -> None:
        """Register the platform account balance for *exchange*."""
        with self._lock:
            self._platform_balances[exchange.upper()] = max(0.0, balance_usd)
            logger.debug(
                "[Allocator] platform balance registered: %s $%.2f",
                exchange.upper(), balance_usd,
            )
        if self._gcm is not None:
            try:
                self._gcm.register_account(f"platform_{exchange.lower()}", balance_usd)
            except Exception:
                pass

    def register_user_balance(
        self, user_id: str, exchange: str, balance_usd: float
    ) -> None:
        """Register a single user's balance on *exchange*."""
        exchange = exchange.upper()
        with self._lock:
            if user_id not in self._user_balances:
                self._user_balances[user_id] = {}
            self._user_balances[user_id][exchange] = max(0.0, balance_usd)
            logger.debug(
                "[Allocator] user balance registered: %s/%s $%.2f",
                user_id, exchange, balance_usd,
            )
        if self._gcm is not None:
            try:
                self._gcm.register_account(f"{user_id}_{exchange.lower()}", balance_usd)
            except Exception:
                pass

    def refresh_balances(self, multi_account_manager) -> int:
        """
        Fetch live balances from all connected user brokers via
        *multi_account_manager* and register them.

        Args:
            multi_account_manager: A ``MultiAccountBrokerManager`` instance.

        Returns:
            Number of user/exchange combinations updated.
        """
        updated = 0
        if multi_account_manager is None:
            return 0

        # Platform brokers
        try:
            for broker_type, broker in multi_account_manager.platform_brokers.items():
                if broker.connected:
                    try:
                        bal = broker.get_account_balance()
                        self.register_platform_balance(broker_type.value, bal)
                        updated += 1
                    except Exception as exc:
                        logger.debug("[Allocator] platform balance fetch error (%s): %s", broker_type.value, exc)
        except Exception as exc:
            logger.debug("[Allocator] platform_brokers access error: %s", exc)

        # User brokers
        try:
            for user_id, user_brokers in multi_account_manager.user_brokers.items():
                for broker_type, broker in user_brokers.items():
                    if broker.connected:
                        try:
                            bal = broker.get_account_balance()
                            self.register_user_balance(user_id, broker_type.value, bal)
                            updated += 1
                        except Exception as exc:
                            logger.debug(
                                "[Allocator] user balance fetch error (%s/%s): %s",
                                user_id, broker_type.value, exc,
                            )
        except Exception as exc:
            logger.debug("[Allocator] user_brokers access error: %s", exc)

        logger.debug("[Allocator] refreshed %d balance(s)", updated)
        return updated

    # ------------------------------------------------------------------
    # Allocation computation
    # ------------------------------------------------------------------

    def compute_user_size(
        self,
        user_id: str,
        platform_size_usd: float,
        exchange: str = "KRAKEN",
    ) -> UserAllocation:
        """
        Compute the USD position size for *user_id* given the platform trade.

        The user's size is scaled proportionally:
            user_size = platform_size × (user_balance / platform_balance)

        Subject to floor (``min_trade_usd``) and ceiling (``max_position_pct``
        of user balance and ``max_position_usd``).

        Args:
            user_id: User identifier.
            platform_size_usd: The platform account's trade size in USD.
            exchange: Exchange name (case-insensitive).

        Returns:
            UserAllocation describing the decision.
        """
        exchange = exchange.upper()

        # --- Platform-presence gate (Step 3) ---
        if self._pal is not None:
            try:
                if not self._pal.has_platform_account(exchange):
                    return UserAllocation(
                        user_id=user_id,
                        exchange=exchange,
                        user_balance_usd=0.0,
                        platform_balance_usd=0.0,
                        platform_size_usd=platform_size_usd,
                        allocated_size_usd=0.0,
                        approved=False,
                        reason=f"no platform account for {exchange} — allocation blocked",
                    )
            except Exception:
                pass

        with self._lock:
            platform_bal = self._platform_balances.get(exchange, 0.0)
            user_bal = self._user_balances.get(user_id, {}).get(exchange, 0.0)

        if platform_bal <= 0:
            return UserAllocation(
                user_id=user_id,
                exchange=exchange,
                user_balance_usd=user_bal,
                platform_balance_usd=platform_bal,
                platform_size_usd=platform_size_usd,
                allocated_size_usd=0.0,
                approved=False,
                reason="platform balance is zero — cannot compute scale factor",
            )

        if user_bal <= 0:
            return UserAllocation(
                user_id=user_id,
                exchange=exchange,
                user_balance_usd=user_bal,
                platform_balance_usd=platform_bal,
                platform_size_usd=platform_size_usd,
                allocated_size_usd=0.0,
                approved=False,
                reason=f"user {user_id} has zero balance on {exchange}",
            )

        scale = user_bal / platform_bal
        raw_size = platform_size_usd * scale

        # Apply floor
        if raw_size < self._min_trade_usd:
            return UserAllocation(
                user_id=user_id,
                exchange=exchange,
                user_balance_usd=user_bal,
                platform_balance_usd=platform_bal,
                platform_size_usd=platform_size_usd,
                allocated_size_usd=0.0,
                approved=False,
                reason=(
                    f"computed size ${raw_size:.2f} < min ${self._min_trade_usd:.2f}"
                ),
                scale_factor=scale,
            )

        # Apply triple ceiling: the final size is the minimum of:
        #   1. raw proportional size
        #   2. max_position_pct fraction of user balance (default 50 %)
        #   3. absolute max_position_usd cap (default $10,000)
        pct_cap = user_bal * self._max_position_pct
        final_size = min(raw_size, pct_cap, self._max_position_usd)

        # Global risk gate
        if self._gcm is not None and user_bal > 0:
            try:
                requested_risk = final_size / user_bal
                if not self._gcm.can_open_trade(requested_risk):
                    return UserAllocation(
                        user_id=user_id,
                        exchange=exchange,
                        user_balance_usd=user_bal,
                        platform_balance_usd=platform_bal,
                        platform_size_usd=platform_size_usd,
                        allocated_size_usd=0.0,
                        approved=False,
                        reason="blocked by global risk ceiling (6 %)",
                        scale_factor=scale,
                    )
            except Exception:
                pass

        return UserAllocation(
            user_id=user_id,
            exchange=exchange,
            user_balance_usd=user_bal,
            platform_balance_usd=platform_bal,
            platform_size_usd=platform_size_usd,
            allocated_size_usd=final_size,
            approved=True,
            reason=f"proportional allocation (scale={scale:.3f})",
            scale_factor=scale,
        )

    def approve_trade(
        self, user_id: str, size_usd: float, exchange: str = "KRAKEN"
    ) -> bool:
        """
        Shorthand gate: True when ``compute_user_size`` returns approved.

        Useful for callers that already have a size and just need a binary gate.
        """
        alloc = self.compute_user_size(user_id, size_usd, exchange)
        return alloc.approved

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------

    def user_ids(self, exchange: str = "") -> List[str]:
        """Return all registered user IDs, optionally filtered by exchange."""
        with self._lock:
            if not exchange:
                return list(self._user_balances.keys())
            ex = exchange.upper()
            return [uid for uid, exs in self._user_balances.items() if ex in exs]

    def get_summary(self) -> str:
        """Return a human-readable allocation summary."""
        with self._lock:
            lines = ["Cross-Account Capital Allocator — Balance Summary"]
            lines.append("-" * 60)
            for ex, bal in sorted(self._platform_balances.items()):
                lines.append(f"  Platform [{ex}]: ${bal:,.2f}")
            lines.append("")
            for uid, exs in sorted(self._user_balances.items()):
                for ex, bal in sorted(exs.items()):
                    lines.append(f"  User [{uid}/{ex}]: ${bal:,.2f}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_gcm():
        for mod_name in ("bot.global_capital_manager", "global_capital_manager"):
            try:
                mod = __import__(mod_name, fromlist=["get_global_capital_manager"])
                return mod.get_global_capital_manager()
            except ImportError:
                continue
            except Exception as exc:
                logger.debug("[Allocator] GlobalCapitalManager load error: %s", exc)
                return None
        logger.debug("[Allocator] GlobalCapitalManager not found — risk ceiling disabled")
        return None

    @staticmethod
    def _load_pal():
        for mod_name in ("bot.platform_account_layer", "platform_account_layer"):
            try:
                mod = __import__(mod_name, fromlist=["get_platform_account_layer"])
                return mod.get_platform_account_layer()
            except ImportError:
                continue
            except Exception as exc:
                logger.debug("[Allocator] PlatformAccountLayer load error: %s", exc)
                return None
        logger.debug("[Allocator] PlatformAccountLayer not found — platform gate disabled")
        return None


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_ALLOCATOR: Optional[CrossAccountCapitalAllocator] = None
_ALLOCATOR_LOCK = threading.Lock()


def get_cross_account_allocator(
    min_trade_usd: float = DEFAULT_MIN_TRADE_USD,
    max_position_pct: float = DEFAULT_MAX_POSITION_PCT,
    max_position_usd: float = DEFAULT_MAX_POSITION_USD,
) -> CrossAccountCapitalAllocator:
    """Return the process-wide :class:`CrossAccountCapitalAllocator` singleton."""
    global _ALLOCATOR
    if _ALLOCATOR is None:
        with _ALLOCATOR_LOCK:
            if _ALLOCATOR is None:
                _ALLOCATOR = CrossAccountCapitalAllocator(
                    min_trade_usd=min_trade_usd,
                    max_position_pct=max_position_pct,
                    max_position_usd=max_position_usd,
                )
                logger.info(
                    "[CrossAccountAllocator] singleton created "
                    "(min=$%.2f, max_pct=%.0f%%, max_usd=$%.0f)",
                    min_trade_usd,
                    max_position_pct * 100,
                    max_position_usd,
                )
    return _ALLOCATOR
