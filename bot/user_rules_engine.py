"""
NIJA User Rules Engine
======================

Allows users to define custom take-profit and stop-loss rules per position.

Rules:
- Take-Profit: "Sell X% of my SYMBOL position if it gains Y%"
  Example: "Sell 50% of 1INCH if it gains 20%"
- Stop-Loss: "Sell X% of SYMBOL if it drops Z% below entry"
  Example: "Sell 100% of AI3 if it drops 30% below entry"

Rules are stored per user and checked during each position management cycle.
When a rule fires, the specified percentage of the position is sold.

Storage Format:
  data/user_rules_{user_id}.json
  {
    "rules": [
      {
        "rule_id": "uuid",
        "user_id": "user123",
        "rule_type": "take_profit",   // or "stop_loss"
        "symbol": "1INCH-USD",        // None means applies to all symbols
        "trigger_pct": 20.0,          // +20% gain triggers take-profit
        "sell_pct": 50.0,             // Sell 50% of position
        "active": true,
        "created_at": "2026-01-01T00:00:00"
      }
    ]
  }
"""

import json
import logging
import os
import threading
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nija.user_rules")

_data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

RULE_TYPE_TAKE_PROFIT = "take_profit"
RULE_TYPE_STOP_LOSS = "stop_loss"


@dataclass
class UserRule:
    """A single user-defined take-profit or stop-loss rule."""
    rule_id: str
    user_id: str
    rule_type: str          # RULE_TYPE_TAKE_PROFIT or RULE_TYPE_STOP_LOSS
    trigger_pct: float      # % gain (positive) or % loss (positive number, e.g. 30 = sell at -30%)
    sell_pct: float         # % of position to sell (1–100)
    symbol: Optional[str]   # None = applies to all symbols for this user
    active: bool = True
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'UserRule':
        known = set(cls.__dataclass_fields__.keys())
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)

    def is_triggered(self, pnl_pct_fractional: float) -> bool:
        """
        Check if this rule is triggered given the current P&L.

        Args:
            pnl_pct_fractional: Current P&L in fractional format (0.20 = +20%, -0.30 = -30%)

        Returns:
            True if the rule should fire.
        """
        if not self.active:
            return False

        if self.rule_type == RULE_TYPE_TAKE_PROFIT:
            # Trigger when gain >= trigger_pct
            threshold = self.trigger_pct / 100.0
            return pnl_pct_fractional >= threshold

        if self.rule_type == RULE_TYPE_STOP_LOSS:
            # trigger_pct is expressed as a positive number (e.g. 30 means -30%)
            threshold = -(self.trigger_pct / 100.0)
            return pnl_pct_fractional <= threshold

        return False

    def sell_quantity(self, full_quantity: float) -> float:
        """
        Calculate how much of the position to sell.

        Args:
            full_quantity: Total position quantity in base asset units.

        Returns:
            Quantity to sell (fraction of full_quantity based on sell_pct).
        """
        return full_quantity * (self.sell_pct / 100.0)


class UserRulesEngine:
    """
    Manages user-defined take-profit and stop-loss rules.

    Thread-safe; each user has an independent lock.
    Rules are persisted to JSON files so they survive restarts.
    """

    def __init__(self, data_dir: Optional[str] = None):
        self._data_dir = data_dir or _data_dir
        os.makedirs(self._data_dir, exist_ok=True)
        self._manager_lock = threading.Lock()
        self._user_locks: Dict[str, threading.Lock] = {}
        # In-memory cache: user_id -> List[UserRule]
        self._rules_cache: Dict[str, List[UserRule]] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_user_lock(self, user_id: str) -> threading.Lock:
        with self._manager_lock:
            if user_id not in self._user_locks:
                self._user_locks[user_id] = threading.Lock()
            return self._user_locks[user_id]

    def _rules_file(self, user_id: str) -> str:
        safe_id = user_id.replace("/", "_").replace("\\", "_")
        return os.path.join(self._data_dir, f"user_rules_{safe_id}.json")

    def _load_rules(self, user_id: str) -> List[UserRule]:
        path = self._rules_file(user_id)
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r") as fh:
                data = json.load(fh)
            return [UserRule.from_dict(r) for r in data.get("rules", [])]
        except (json.JSONDecodeError, IOError, TypeError) as exc:
            logger.warning("Could not load rules for %s: %s", user_id, exc)
            return []

    def _save_rules(self, user_id: str, rules: List[UserRule]) -> None:
        path = self._rules_file(user_id)
        tmp = path + ".tmp"
        try:
            with open(tmp, "w") as fh:
                json.dump({"rules": [r.to_dict() for r in rules]}, fh, indent=2)
            os.replace(tmp, path)
        except IOError as exc:
            logger.error("Could not save rules for %s: %s", user_id, exc)

    def _get_cached_rules(self, user_id: str) -> List[UserRule]:
        """Return cached rules, loading from disk if necessary."""
        if user_id not in self._rules_cache:
            self._rules_cache[user_id] = self._load_rules(user_id)
        return self._rules_cache[user_id]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_take_profit_rule(
        self,
        user_id: str,
        trigger_pct: float,
        sell_pct: float,
        symbol: Optional[str] = None,
        rule_id: Optional[str] = None,
    ) -> UserRule:
        """
        Add a take-profit rule for a user.

        Args:
            user_id: User identifier.
            trigger_pct: Gain percentage that triggers the rule (e.g. 20.0 = +20%).
            sell_pct: Percentage of position to sell when triggered (1–100).
            symbol: Trading symbol (e.g. '1INCH-USD'). None = all symbols.
            rule_id: Optional explicit rule ID (auto-generated if omitted).

        Returns:
            The created UserRule.

        Raises:
            ValueError: If parameters are out of valid ranges.
        """
        if trigger_pct <= 0:
            raise ValueError(f"take_profit trigger_pct must be positive, got {trigger_pct}")
        if not (0 < sell_pct <= 100):
            raise ValueError(f"sell_pct must be greater than 0 and at most 100, got {sell_pct}")

        rule = UserRule(
            rule_id=rule_id or str(uuid.uuid4()),
            user_id=user_id,
            rule_type=RULE_TYPE_TAKE_PROFIT,
            trigger_pct=trigger_pct,
            sell_pct=sell_pct,
            symbol=symbol,
        )

        lock = self._get_user_lock(user_id)
        with lock:
            rules = self._get_cached_rules(user_id)
            rules.append(rule)
            self._save_rules(user_id, rules)

        logger.info(
            "✅ Take-profit rule added for %s: sell %.0f%% of %s if gain >= %.1f%%",
            user_id, sell_pct, symbol or "all symbols", trigger_pct,
        )
        return rule

    def add_stop_loss_rule(
        self,
        user_id: str,
        trigger_pct: float,
        sell_pct: float,
        symbol: Optional[str] = None,
        rule_id: Optional[str] = None,
    ) -> UserRule:
        """
        Add a stop-loss rule for a user.

        Args:
            user_id: User identifier.
            trigger_pct: Loss percentage that triggers the rule (positive number,
                         e.g. 30.0 means sell when position is down 30%).
            sell_pct: Percentage of position to sell when triggered (1–100).
            symbol: Trading symbol (e.g. 'AI3-USD'). None = all symbols.
            rule_id: Optional explicit rule ID (auto-generated if omitted).

        Returns:
            The created UserRule.

        Raises:
            ValueError: If parameters are out of valid ranges.
        """
        if trigger_pct <= 0:
            raise ValueError(f"stop_loss trigger_pct must be positive (e.g. 30 for -30%), got {trigger_pct}")
        if not (0 < sell_pct <= 100):
            raise ValueError(f"sell_pct must be greater than 0 and at most 100, got {sell_pct}")

        rule = UserRule(
            rule_id=rule_id or str(uuid.uuid4()),
            user_id=user_id,
            rule_type=RULE_TYPE_STOP_LOSS,
            trigger_pct=trigger_pct,
            sell_pct=sell_pct,
            symbol=symbol,
        )

        lock = self._get_user_lock(user_id)
        with lock:
            rules = self._get_cached_rules(user_id)
            rules.append(rule)
            self._save_rules(user_id, rules)

        logger.info(
            "🛡️ Stop-loss rule added for %s: sell %.0f%% of %s if loss >= %.1f%%",
            user_id, sell_pct, symbol or "all symbols", trigger_pct,
        )
        return rule

    def get_rules(
        self,
        user_id: str,
        symbol: Optional[str] = None,
        rule_type: Optional[str] = None,
    ) -> List[UserRule]:
        """
        Get all active rules for a user, optionally filtered by symbol and/or type.

        Args:
            user_id: User identifier.
            symbol: Filter to rules that match this symbol (or apply to all symbols).
            rule_type: Filter by rule type ('take_profit' or 'stop_loss').

        Returns:
            List of matching active UserRule objects.
        """
        lock = self._get_user_lock(user_id)
        with lock:
            rules = self._get_cached_rules(user_id)

        result = [r for r in rules if r.active]

        if symbol is not None:
            result = [r for r in result if r.symbol is None or r.symbol == symbol]

        if rule_type is not None:
            result = [r for r in result if r.rule_type == rule_type]

        return result

    def get_rule_by_id(self, user_id: str, rule_id: str) -> Optional[UserRule]:
        """Return a single rule by ID, or None if not found."""
        lock = self._get_user_lock(user_id)
        with lock:
            rules = self._get_cached_rules(user_id)
        for r in rules:
            if r.rule_id == rule_id:
                return r
        return None

    def delete_rule(self, user_id: str, rule_id: str) -> bool:
        """
        Deactivate (soft-delete) a rule by ID.

        Args:
            user_id: User identifier.
            rule_id: Rule UUID to delete.

        Returns:
            True if the rule was found and deactivated, False if not found.
        """
        lock = self._get_user_lock(user_id)
        with lock:
            rules = self._get_cached_rules(user_id)
            for rule in rules:
                if rule.rule_id == rule_id and rule.user_id == user_id:
                    rule.active = False
                    self._save_rules(user_id, rules)
                    logger.info("🗑️ Rule %s deleted for user %s", rule_id, user_id)
                    return True
        logger.warning("Rule %s not found for user %s", rule_id, user_id)
        return False

    def check_rules(
        self,
        user_id: str,
        symbol: str,
        pnl_pct_fractional: float,
        full_quantity: float,
    ) -> List[Tuple[float, str]]:
        """
        Evaluate all applicable rules for a given position and return triggered actions.

        Rules are evaluated in priority order:
        1. Stop-loss rules first (capital preservation)
        2. Take-profit rules second (profit locking)

        Args:
            user_id: User identifier.
            symbol: Trading symbol (e.g. '1INCH-USD').
            pnl_pct_fractional: Current P&L in fractional format (0.20 = +20%, -0.30 = -30%).
            full_quantity: Full position quantity in base asset units.

        Returns:
            List of (sell_quantity, reason) tuples for each triggered rule.
            May be empty if no rules are triggered.
        """
        rules = self.get_rules(user_id, symbol=symbol)

        # Separate by type so stop-losses are checked first
        stop_loss_rules = [r for r in rules if r.rule_type == RULE_TYPE_STOP_LOSS]
        take_profit_rules = [r for r in rules if r.rule_type == RULE_TYPE_TAKE_PROFIT]

        actions: List[Tuple[float, str]] = []

        for rule in stop_loss_rules + take_profit_rules:
            if rule.is_triggered(pnl_pct_fractional):
                qty = rule.sell_quantity(full_quantity)
                if qty <= 0:
                    continue
                pnl_display = f"{pnl_pct_fractional * 100:+.2f}%"
                if rule.rule_type == RULE_TYPE_STOP_LOSS:
                    reason = (
                        f"User stop-loss rule: sell {rule.sell_pct:.0f}% at {pnl_display} "
                        f"(threshold: -{rule.trigger_pct:.1f}%)"
                    )
                else:
                    reason = (
                        f"User take-profit rule: sell {rule.sell_pct:.0f}% at {pnl_display} "
                        f"(threshold: +{rule.trigger_pct:.1f}%)"
                    )
                logger.info(
                    "🎯 User rule triggered for %s %s: %s",
                    user_id, symbol, reason,
                )
                actions.append((qty, reason))

        return actions


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_engine: Optional[UserRulesEngine] = None
_engine_lock = threading.Lock()


def get_user_rules_engine() -> UserRulesEngine:
    """Return the global UserRulesEngine singleton."""
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = UserRulesEngine()
    return _engine


__all__ = [
    "UserRule",
    "UserRulesEngine",
    "get_user_rules_engine",
    "RULE_TYPE_TAKE_PROFIT",
    "RULE_TYPE_STOP_LOSS",
]
