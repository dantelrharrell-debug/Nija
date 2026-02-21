"""
NIJA Account Mode Manager
=========================

Per-account mode flag system for dynamic risk routing.

Each account can be assigned a mode that controls its risk behavior,
following the prop-firm pattern for multi-account routing:

    {"account": "daivon", "mode": "recovery"}

Available modes:
- normal      : Standard risk parameters (default)
- recovery    : Exit-only; no new entries, minimal position exposure
- conservative: Reduced position sizes and tighter loss limits
- aggressive  : Larger position sizes with relaxed limits (advanced users)
- paused      : All trading halted (no entries or exits triggered)

Mode rules are applied on top of each user's base risk limits,
allowing a single service to handle all accounts with different risk profiles.

Author: NIJA Trading Systems
Version: 1.0
Date: February 2026
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional

logger = logging.getLogger("nija.account_mode_manager")


class AccountMode(str, Enum):
    """
    Per-account trading mode.

    Controls which risk rules are applied for a given account.
    String-based enum allows direct JSON serialization / deserialization.
    """
    NORMAL = "normal"            # Default: standard risk parameters
    RECOVERY = "recovery"        # Exit-only; no new entries
    CONSERVATIVE = "conservative"  # Reduced exposure, tighter limits
    AGGRESSIVE = "aggressive"    # Higher exposure (advanced users only)
    PAUSED = "paused"            # All trading halted


@dataclass
class ModeRiskOverrides:
    """
    Risk parameter overrides applied when an account is in a specific mode.

    Any field set to None is left unchanged (i.e., the user's base value is kept).
    """
    # Position sizing
    max_position_pct: Optional[float] = None   # Max position as fraction of balance
    min_position_pct: Optional[float] = None   # Min position as fraction of balance
    max_open_positions: Optional[int] = None   # Max concurrent open positions

    # Loss limits
    max_daily_loss_pct: Optional[float] = None   # Max daily loss as fraction of balance
    max_daily_loss_usd: Optional[float] = None   # Max daily loss in USD
    max_weekly_loss_usd: Optional[float] = None  # Max weekly loss in USD
    max_drawdown_pct: Optional[float] = None     # Max drawdown from peak

    # Trade limits
    max_daily_trades: Optional[int] = None       # Max trades per day

    # Circuit breaker
    circuit_breaker_loss_pct: Optional[float] = None  # Loss % that halts trading

    # Entry gate – when False, can_trade() always returns False
    allow_new_entries: bool = True


# ============================================================================
# Mode → risk override mappings
# ============================================================================
# These are intentionally conservative defaults. Operators can tune them by
# subclassing AccountModeManager or overriding MODE_RULES at startup.
# ============================================================================

MODE_RULES: Dict[AccountMode, ModeRiskOverrides] = {
    AccountMode.NORMAL: ModeRiskOverrides(
        # All fields are None → user's base limits apply unchanged
        allow_new_entries=True,
    ),

    AccountMode.RECOVERY: ModeRiskOverrides(
        # Exits only; block new entries and shrink max exposure dramatically
        max_position_pct=0.05,     # 5% max per position (vs 20% default)
        max_open_positions=2,       # Only 2 concurrent positions while unwinding
        max_daily_trades=5,         # Minimal trading during recovery
        circuit_breaker_loss_pct=0.02,  # Halt earlier (2% vs 3%)
        allow_new_entries=False,    # KEY: no new trade entries
    ),

    AccountMode.CONSERVATIVE: ModeRiskOverrides(
        max_position_pct=0.10,     # 10% max (half the normal 20%)
        max_open_positions=3,
        max_daily_loss_pct=0.03,   # 3% daily loss cap (vs 5%)
        max_drawdown_pct=0.10,     # 10% drawdown limit (vs 15%)
        circuit_breaker_loss_pct=0.02,
        allow_new_entries=True,
    ),

    AccountMode.AGGRESSIVE: ModeRiskOverrides(
        max_position_pct=0.30,     # 30% max (vs 20% default)
        max_open_positions=8,
        max_daily_loss_pct=0.08,   # 8% daily loss cap
        max_drawdown_pct=0.20,     # 20% drawdown limit
        circuit_breaker_loss_pct=0.05,
        max_daily_trades=30,
        allow_new_entries=True,
    ),

    AccountMode.PAUSED: ModeRiskOverrides(
        max_daily_trades=0,        # Zero trades allowed
        allow_new_entries=False,
    ),
}


class AccountModeManager:
    """
    Manages per-account mode flags and applies their risk overrides.

    Usage
    -----
    Typical call site in UserRiskManager::

        mode_manager = AccountModeManager()
        mode = mode_manager.get_mode("daivon_frazier")  # -> AccountMode.RECOVERY
        limits = mode_manager.apply_mode_overrides(mode, limits)

    The mode is read from the IndividualUserConfig which is loaded from
    ``config/users/<user_id>.json``.
    """

    def __init__(self, mode_rules: Optional[Dict[AccountMode, ModeRiskOverrides]] = None):
        """
        Args:
            mode_rules: Optional custom mode → override mapping.
                        Defaults to the module-level MODE_RULES dict.
        """
        self._mode_rules = mode_rules if mode_rules is not None else MODE_RULES
        # In-process cache of account → mode
        self._account_modes: Dict[str, AccountMode] = {}

        logger.info("AccountModeManager initialized")

    # ------------------------------------------------------------------
    # Mode registry
    # ------------------------------------------------------------------

    def set_mode(self, account: str, mode: AccountMode) -> None:
        """
        Set the mode for an account at runtime.

        This is the primary mechanism for changing an account's mode
        without restarting the service.

        Args:
            account: Account identifier (e.g. 'daivon_frazier')
            mode: The new AccountMode
        """
        prev = self._account_modes.get(account)
        self._account_modes[account] = mode

        if prev != mode:
            logger.info(
                "🔄 Account mode changed: account=%s  %s → %s",
                account, prev.value if prev else "unset", mode.value
            )
        else:
            logger.debug("Account mode unchanged: account=%s mode=%s", account, mode.value)

    def get_mode(self, account: str, default: AccountMode = AccountMode.NORMAL) -> AccountMode:
        """
        Get the current mode for an account.

        Args:
            account: Account identifier
            default: Fallback mode if account has no explicit mode set

        Returns:
            AccountMode for the account
        """
        return self._account_modes.get(account, default)

    def load_mode_from_config(self, account: str, raw_mode: str) -> AccountMode:
        """
        Parse a raw mode string from a config file and register it for the account.

        Unknown values fall back to NORMAL with a warning.

        Args:
            account: Account identifier
            raw_mode: String read from the config (e.g. 'recovery')

        Returns:
            Resolved AccountMode
        """
        try:
            mode = AccountMode(raw_mode.lower())
        except ValueError:
            logger.warning(
                "⚠️  Unknown mode '%s' for account '%s' – defaulting to normal",
                raw_mode, account
            )
            mode = AccountMode.NORMAL

        self.set_mode(account, mode)
        return mode

    # ------------------------------------------------------------------
    # Risk-override application
    # ------------------------------------------------------------------

    def apply_mode_overrides(self, mode: AccountMode, limits: object) -> object:
        """
        Apply mode-based risk overrides to a UserRiskLimits object in-place.

        Only fields explicitly set in ModeRiskOverrides (i.e. not None) are
        modified; all other fields in ``limits`` remain as-is.

        Args:
            mode: The AccountMode to apply
            limits: A UserRiskLimits instance to modify

        Returns:
            The same ``limits`` object (modified in-place) for convenience
        """
        overrides = self._mode_rules.get(mode)
        if overrides is None:
            logger.warning("No overrides defined for mode '%s', using base limits", mode.value)
            return limits

        applied: Dict[str, object] = {}

        for field_name in overrides.__dataclass_fields__.keys():
            if field_name == "allow_new_entries":
                # Handled separately – stored on limits if the attribute exists
                if hasattr(limits, "allow_new_entries"):
                    old = getattr(limits, "allow_new_entries")
                    setattr(limits, "allow_new_entries", overrides.allow_new_entries)
                    if old != overrides.allow_new_entries:
                        applied[field_name] = overrides.allow_new_entries
                continue

            value = getattr(overrides, field_name)
            if value is not None and hasattr(limits, field_name):
                old = getattr(limits, field_name)
                setattr(limits, field_name, value)
                if old != value:
                    applied[field_name] = value

        if applied:
            logger.debug(
                "Mode '%s' applied overrides: %s", mode.value, applied
            )

        return limits

    def can_enter_trade(self, account: str) -> bool:
        """
        Quick check: is this account allowed to open new positions?

        Args:
            account: Account identifier

        Returns:
            False when mode is RECOVERY or PAUSED, True otherwise
        """
        mode = self.get_mode(account)
        overrides = self._mode_rules.get(mode)
        if overrides is None:
            return True
        return overrides.allow_new_entries

    def get_mode_summary(self, account: str) -> Dict:
        """
        Return a dict summary of the account's current mode and its overrides.

        Useful for dashboards and audit logging.
        """
        mode = self.get_mode(account)
        overrides = self._mode_rules.get(mode, ModeRiskOverrides())

        return {
            "account": account,
            "mode": mode.value,
            "allow_new_entries": overrides.allow_new_entries,
            "overrides": {
                k: v
                for k, v in overrides.__dict__.items()
                if v is not None and k != "allow_new_entries"
            },
        }


# ============================================================================
# Module-level singleton
# ============================================================================

_manager_instance: Optional[AccountModeManager] = None


def get_account_mode_manager() -> AccountModeManager:
    """
    Get the global AccountModeManager singleton.

    Returns:
        AccountModeManager instance
    """
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = AccountModeManager()
    return _manager_instance


__all__ = [
    "AccountMode",
    "ModeRiskOverrides",
    "AccountModeManager",
    "MODE_RULES",
    "get_account_mode_manager",
]
