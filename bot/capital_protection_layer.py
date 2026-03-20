"""
NIJA Capital Protection Layer
==============================

Enforces hard limits on capital concentration to prevent catastrophic loss:

1. **Max % of capital per symbol** — no single symbol may absorb more than
   ``MAX_SYMBOL_EXPOSURE_PCT`` (default 10 %) of total account equity.

2. **Max concurrent exposure across accounts** — the sum of all open
   positions (across every account) must not exceed
   ``MAX_TOTAL_EXPOSURE_PCT`` (default 80 %) of aggregate account equity.

Usage
-----
::

    from bot.capital_protection_layer import get_capital_protection_layer

    cpl = get_capital_protection_layer()
    allowed, reason = cpl.validate_trade(
        symbol="BTC-USD",
        trade_size_usd=500.0,
        account_equity=10_000.0,
        open_positions={"BTC-USD": 300.0, "ETH-USD": 200.0},
    )
    if not allowed:
        logger.warning(f"Trade blocked by capital protection: {reason}")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nija.capital.protection")

# ---------------------------------------------------------------------------
# Default thresholds (all expressed as fractions, e.g. 0.10 = 10 %)
# ---------------------------------------------------------------------------

# Maximum fraction of *total equity* that any single symbol may represent.
DEFAULT_MAX_SYMBOL_EXPOSURE_PCT: float = 0.10  # 10 %

# Maximum fraction of *total equity* that may be deployed concurrently
# across all symbols and all accounts.
DEFAULT_MAX_TOTAL_EXPOSURE_PCT: float = 0.80   # 80 %

# Warn (but don't block) when total exposure exceeds this fraction.
DEFAULT_WARN_TOTAL_EXPOSURE_PCT: float = 0.65  # 65 %


# ---------------------------------------------------------------------------
# Data-classes
# ---------------------------------------------------------------------------


@dataclass
class TradeValidationResult:
    """Result returned by :meth:`CapitalProtectionLayer.validate_trade`."""

    allowed: bool
    symbol: str
    trade_size_usd: float
    reason: str = ""

    # Exposure diagnostics
    symbol_exposure_before_usd: float = 0.0
    symbol_exposure_after_usd: float = 0.0
    symbol_exposure_pct_after: float = 0.0
    total_exposure_before_usd: float = 0.0
    total_exposure_after_usd: float = 0.0
    total_exposure_pct_after: float = 0.0

    # Limits applied
    max_symbol_exposure_pct: float = DEFAULT_MAX_SYMBOL_EXPOSURE_PCT
    max_total_exposure_pct: float = DEFAULT_MAX_TOTAL_EXPOSURE_PCT

    checked_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict:
        return {
            "allowed": self.allowed,
            "symbol": self.symbol,
            "trade_size_usd": self.trade_size_usd,
            "reason": self.reason,
            "symbol_exposure_before_usd": self.symbol_exposure_before_usd,
            "symbol_exposure_after_usd": self.symbol_exposure_after_usd,
            "symbol_exposure_pct_after": round(self.symbol_exposure_pct_after * 100, 2),
            "total_exposure_before_usd": self.total_exposure_before_usd,
            "total_exposure_after_usd": self.total_exposure_after_usd,
            "total_exposure_pct_after": round(self.total_exposure_pct_after * 100, 2),
            "max_symbol_exposure_pct": round(self.max_symbol_exposure_pct * 100, 2),
            "max_total_exposure_pct": round(self.max_total_exposure_pct * 100, 2),
            "checked_at": self.checked_at.isoformat(),
        }


@dataclass
class MultiAccountExposure:
    """Aggregate exposure snapshot across all registered accounts."""

    total_equity_usd: float = 0.0
    total_deployed_usd: float = 0.0

    # Per-account breakdown: {account_id: equity_usd}
    account_equities: Dict[str, float] = field(default_factory=dict)

    # Per-symbol deployed capital across ALL accounts: {symbol: deployed_usd}
    symbol_exposure: Dict[str, float] = field(default_factory=dict)

    @property
    def total_exposure_pct(self) -> float:
        if self.total_equity_usd <= 0:
            return 0.0
        return self.total_deployed_usd / self.total_equity_usd

    def get_symbol_exposure_pct(self, symbol: str) -> float:
        if self.total_equity_usd <= 0:
            return 0.0
        return self.symbol_exposure.get(symbol, 0.0) / self.total_equity_usd

    def to_dict(self) -> Dict:
        return {
            "total_equity_usd": self.total_equity_usd,
            "total_deployed_usd": self.total_deployed_usd,
            "total_exposure_pct": round(self.total_exposure_pct * 100, 2),
            "account_count": len(self.account_equities),
            "symbol_count": len(self.symbol_exposure),
            "top_symbols": sorted(
                self.symbol_exposure.items(), key=lambda x: x[1], reverse=True
            )[:10],
        }


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class CapitalProtectionLayer:
    """
    Hard-limit guard that prevents dangerous capital concentration.

    Two checks are applied before every trade:

    * **Symbol limit** — existing + proposed exposure for ``symbol`` must
      not exceed ``max_symbol_exposure_pct × total_equity``.
    * **Concurrent exposure** — existing + proposed total deployed capital
      must not exceed ``max_total_exposure_pct × total_equity``.

    Both are configurable at construction time; defaults are conservative
    (10 % per symbol, 80 % total).
    """

    def __init__(
        self,
        max_symbol_exposure_pct: float = DEFAULT_MAX_SYMBOL_EXPOSURE_PCT,
        max_total_exposure_pct: float = DEFAULT_MAX_TOTAL_EXPOSURE_PCT,
        warn_total_exposure_pct: float = DEFAULT_WARN_TOTAL_EXPOSURE_PCT,
    ) -> None:
        if not (0 < max_symbol_exposure_pct <= 1.0):
            raise ValueError("max_symbol_exposure_pct must be in (0, 1]")
        if not (0 < max_total_exposure_pct <= 1.0):
            raise ValueError("max_total_exposure_pct must be in (0, 1]")
        if max_symbol_exposure_pct > max_total_exposure_pct:
            raise ValueError(
                "max_symbol_exposure_pct cannot exceed max_total_exposure_pct"
            )

        self.max_symbol_exposure_pct = max_symbol_exposure_pct
        self.max_total_exposure_pct = max_total_exposure_pct
        self.warn_total_exposure_pct = warn_total_exposure_pct

        # Registry of multi-account equity snapshots: {account_id: equity_usd}
        self._account_equities: Dict[str, float] = {}

        # Trade block counter (for monitoring)
        self._trades_blocked: int = 0
        self._trades_allowed: int = 0

        logger.info(
            f"CapitalProtectionLayer initialised — "
            f"max_symbol={max_symbol_exposure_pct*100:.0f}%  "
            f"max_total={max_total_exposure_pct*100:.0f}%"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_account(self, account_id: str, equity_usd: float) -> None:
        """
        Register (or update) an account's equity for multi-account exposure
        calculations.

        Parameters
        ----------
        account_id:
            Unique identifier for the account (e.g. ``"kraken_platform"``).
        equity_usd:
            Current account equity in USD.
        """
        self._account_equities[account_id] = max(0.0, equity_usd)
        logger.debug(
            f"[CapitalProtection] account '{account_id}' equity updated "
            f"→ ${equity_usd:,.2f}"
        )

    def validate_trade(
        self,
        symbol: str,
        trade_size_usd: float,
        account_equity: float,
        open_positions: Dict[str, float],
        account_id: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """
        Validate whether a new trade is within capital protection limits.

        Parameters
        ----------
        symbol:
            The symbol to trade (e.g. ``"BTC-USD"``).
        trade_size_usd:
            Proposed trade size in USD.
        account_equity:
            Total equity of the *single account* placing the trade.
        open_positions:
            ``{symbol: usd_value}`` dict of the account's current open
            positions (per-symbol USD values, **not including** the
            proposed trade).
        account_id:
            Optional identifier used to include this account in the
            multi-account aggregate.

        Returns
        -------
        (allowed: bool, reason: str)
            ``allowed=True`` means the trade passes both limits.
        """
        result = self.validate_trade_full(
            symbol=symbol,
            trade_size_usd=trade_size_usd,
            account_equity=account_equity,
            open_positions=open_positions,
            account_id=account_id,
        )
        return result.allowed, result.reason

    def validate_trade_full(
        self,
        symbol: str,
        trade_size_usd: float,
        account_equity: float,
        open_positions: Dict[str, float],
        account_id: Optional[str] = None,
    ) -> TradeValidationResult:
        """
        Same as :meth:`validate_trade` but returns the full
        :class:`TradeValidationResult` with exposure diagnostics.
        """
        if account_equity <= 0:
            return TradeValidationResult(
                allowed=False,
                symbol=symbol,
                trade_size_usd=trade_size_usd,
                reason="account_equity must be positive",
            )

        if trade_size_usd <= 0:
            return TradeValidationResult(
                allowed=True,
                symbol=symbol,
                trade_size_usd=trade_size_usd,
                reason="zero-size trade, no exposure change",
            )

        # Update account registry if account_id provided
        if account_id:
            self.register_account(account_id, account_equity)

        # ── Per-symbol check ─────────────────────────────────────────
        current_symbol_usd = open_positions.get(symbol, 0.0)
        proposed_symbol_usd = current_symbol_usd + trade_size_usd
        proposed_symbol_pct = proposed_symbol_usd / account_equity
        max_symbol_usd = self.max_symbol_exposure_pct * account_equity

        # ── Total concurrent exposure check ─────────────────────────
        current_total_usd = sum(open_positions.values())
        proposed_total_usd = current_total_usd + trade_size_usd
        proposed_total_pct = proposed_total_usd / account_equity
        max_total_usd = self.max_total_exposure_pct * account_equity

        # ── Build result skeleton ────────────────────────────────────
        res = TradeValidationResult(
            allowed=True,
            symbol=symbol,
            trade_size_usd=trade_size_usd,
            symbol_exposure_before_usd=current_symbol_usd,
            symbol_exposure_after_usd=proposed_symbol_usd,
            symbol_exposure_pct_after=proposed_symbol_pct,
            total_exposure_before_usd=current_total_usd,
            total_exposure_after_usd=proposed_total_usd,
            total_exposure_pct_after=proposed_total_pct,
            max_symbol_exposure_pct=self.max_symbol_exposure_pct,
            max_total_exposure_pct=self.max_total_exposure_pct,
        )

        # ── Symbol limit ─────────────────────────────────────────────
        if proposed_symbol_pct > self.max_symbol_exposure_pct:
            self._trades_blocked += 1
            res.allowed = False
            res.reason = (
                f"Symbol limit breached: {symbol} would be "
                f"{proposed_symbol_pct*100:.1f}% of equity "
                f"(limit={self.max_symbol_exposure_pct*100:.0f}%, "
                f"current={current_symbol_usd:.2f}, proposed_add=${trade_size_usd:.2f}, "
                f"max_allowed=${max_symbol_usd:.2f})"
            )
            logger.warning(f"🚫 [CapitalProtection] {res.reason}")
            return res

        # ── Concurrent exposure limit ─────────────────────────────────
        if proposed_total_pct > self.max_total_exposure_pct:
            self._trades_blocked += 1
            res.allowed = False
            res.reason = (
                f"Total exposure limit breached: portfolio would be "
                f"{proposed_total_pct*100:.1f}% deployed "
                f"(limit={self.max_total_exposure_pct*100:.0f}%, "
                f"current=${current_total_usd:.2f}, proposed_add=${trade_size_usd:.2f}, "
                f"max_allowed=${max_total_usd:.2f})"
            )
            logger.warning(f"🚫 [CapitalProtection] {res.reason}")
            return res

        # ── Warn on high but acceptable exposure ──────────────────────
        if proposed_total_pct > self.warn_total_exposure_pct:
            logger.warning(
                f"⚠️  [CapitalProtection] High concurrent exposure: "
                f"{proposed_total_pct*100:.1f}% of equity deployed "
                f"(warn threshold={self.warn_total_exposure_pct*100:.0f}%)"
            )

        # ── All checks passed ─────────────────────────────────────────
        self._trades_allowed += 1
        res.reason = (
            f"OK — symbol={proposed_symbol_pct*100:.1f}%/{self.max_symbol_exposure_pct*100:.0f}%  "
            f"total={proposed_total_pct*100:.1f}%/{self.max_total_exposure_pct*100:.0f}%"
        )
        logger.debug(f"✅ [CapitalProtection] {symbol} trade approved: {res.reason}")
        return res

    def get_multi_account_exposure(
        self,
        all_account_positions: Dict[str, Dict[str, float]],
    ) -> MultiAccountExposure:
        """
        Compute aggregate exposure snapshot across all registered accounts.

        Parameters
        ----------
        all_account_positions:
            ``{account_id: {symbol: usd_value}}`` nested dict of every
            account's open positions.

        Returns
        -------
        MultiAccountExposure
        """
        snap = MultiAccountExposure(
            account_equities=dict(self._account_equities),
            total_equity_usd=sum(self._account_equities.values()),
        )

        for account_id, positions in all_account_positions.items():
            for sym, usd_val in positions.items():
                snap.symbol_exposure[sym] = snap.symbol_exposure.get(sym, 0.0) + usd_val
                snap.total_deployed_usd += usd_val

        return snap

    def validate_multi_account_trade(
        self,
        symbol: str,
        trade_size_usd: float,
        all_account_positions: Dict[str, Dict[str, float]],
    ) -> Tuple[bool, str]:
        """
        Validate a trade against *aggregate* multi-account limits.

        Uses :attr:`_account_equities` (populated via :meth:`register_account`)
        as the total equity denominator.

        Returns
        -------
        (allowed: bool, reason: str)
        """
        total_equity = sum(self._account_equities.values())
        if total_equity <= 0:
            logger.warning(
                "[CapitalProtection] No account equity registered; "
                "skipping multi-account check (returning allowed=True)"
            )
            return True, "no equity registered — check skipped"

        snap = self.get_multi_account_exposure(all_account_positions)

        current_symbol_usd = snap.symbol_exposure.get(symbol, 0.0)
        proposed_symbol_usd = current_symbol_usd + trade_size_usd
        proposed_symbol_pct = proposed_symbol_usd / total_equity

        proposed_total_usd = snap.total_deployed_usd + trade_size_usd
        proposed_total_pct = proposed_total_usd / total_equity

        if proposed_symbol_pct > self.max_symbol_exposure_pct:
            reason = (
                f"[Multi-account] {symbol} exposure {proposed_symbol_pct*100:.1f}% "
                f"exceeds limit {self.max_symbol_exposure_pct*100:.0f}% "
                f"across {len(self._account_equities)} accounts"
            )
            logger.warning(f"🚫 [CapitalProtection] {reason}")
            return False, reason

        if proposed_total_pct > self.max_total_exposure_pct:
            reason = (
                f"[Multi-account] Total concurrent exposure {proposed_total_pct*100:.1f}% "
                f"exceeds limit {self.max_total_exposure_pct*100:.0f}% "
                f"across {len(self._account_equities)} accounts"
            )
            logger.warning(f"🚫 [CapitalProtection] {reason}")
            return False, reason

        return True, (
            f"[Multi-account] OK — symbol={proposed_symbol_pct*100:.1f}%  "
            f"total={proposed_total_pct*100:.1f}%"
        )

    def get_status(self) -> Dict:
        """Return current protection configuration and block statistics."""
        total = self._trades_allowed + self._trades_blocked
        return {
            "max_symbol_exposure_pct": round(self.max_symbol_exposure_pct * 100, 1),
            "max_total_exposure_pct": round(self.max_total_exposure_pct * 100, 1),
            "warn_total_exposure_pct": round(self.warn_total_exposure_pct * 100, 1),
            "trades_allowed": self._trades_allowed,
            "trades_blocked": self._trades_blocked,
            "block_rate_pct": round(
                (self._trades_blocked / total * 100) if total > 0 else 0.0, 2
            ),
            "registered_accounts": len(self._account_equities),
            "total_registered_equity_usd": sum(self._account_equities.values()),
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_INSTANCE: Optional[CapitalProtectionLayer] = None


def get_capital_protection_layer(
    max_symbol_exposure_pct: float = DEFAULT_MAX_SYMBOL_EXPOSURE_PCT,
    max_total_exposure_pct: float = DEFAULT_MAX_TOTAL_EXPOSURE_PCT,
    warn_total_exposure_pct: float = DEFAULT_WARN_TOTAL_EXPOSURE_PCT,
) -> CapitalProtectionLayer:
    """Return (or create) the singleton :class:`CapitalProtectionLayer`."""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = CapitalProtectionLayer(
            max_symbol_exposure_pct=max_symbol_exposure_pct,
            max_total_exposure_pct=max_total_exposure_pct,
            warn_total_exposure_pct=warn_total_exposure_pct,
        )
    return _INSTANCE
