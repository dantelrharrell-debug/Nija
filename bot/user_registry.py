"""
NIJA User Registry
====================

Lightweight per-user registry that allows the NIJA bot to operate as a
multi-tenant service.  Each registered user gets:

* A unique ``user_id``
* Their own daily profit target and kill-switch flag
* A plan/tier label (e.g. "starter", "pro", "elite")
* Persistent JSON storage for across-restart survival

This module is intentionally thin — it **does not** duplicate the full
``MultiUserPortfolioManager`` logic.  Instead it acts as the user-facing
front-door: registration, discovery, and per-user control toggles.

Usage
-----
    from bot.user_registry import get_user_registry

    reg = get_user_registry()

    # Register a new subscriber
    reg.register_user(
        user_id="alice",
        display_name="Alice Smith",
        email="alice@example.com",
        plan="starter",
        daily_target_usd=25.0,
    )

    # List all active users
    for user in reg.list_users():
        print(user["user_id"], user["plan"])

    # Trigger kill-switch for a single user
    reg.set_kill_switch(user_id="alice", active=True, reason="Manual stop")

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("nija.user_registry")


# ---------------------------------------------------------------------------
# Plans / tiers
# ---------------------------------------------------------------------------

VALID_PLANS = ("free", "starter", "pro", "elite")

PLAN_DEFAULTS: Dict[str, dict] = {
    "free":    {"daily_target_usd": 5.0,   "max_positions": 2,  "monthly_usd": 0.0},
    "starter": {"daily_target_usd": 25.0,  "max_positions": 5,  "monthly_usd": 29.0},
    "pro":     {"daily_target_usd": 100.0, "max_positions": 15, "monthly_usd": 79.0},
    "elite":   {"daily_target_usd": 500.0, "max_positions": 50, "monthly_usd": 199.0},
}


# ---------------------------------------------------------------------------
# User record
# ---------------------------------------------------------------------------

@dataclass
class UserRecord:
    user_id: str
    display_name: str = ""
    email: str = ""
    plan: str = "starter"
    daily_target_usd: float = 25.0
    max_positions: int = 5
    monthly_usd: float = 29.0
    active: bool = True
    kill_switch_active: bool = False
    kill_switch_reason: str = ""
    created_at: str = ""
    updated_at: str = ""
    # Lifetime stats (updated externally by the trading layer)
    total_pnl_usd: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    # Tags / notes
    notes: str = ""
    metadata: Dict = field(default_factory=dict)

    @property
    def win_rate_pct(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return (self.winning_trades / self.total_trades) * 100.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["win_rate_pct"] = round(self.win_rate_pct, 1)
        return d


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class UserRegistry:
    """
    Central registry of all NIJA subscribers.

    Thread-safe, persistent JSON backend.
    """

    _DEFAULT_DATA_DIR = Path(__file__).parent.parent / "data"
    _REGISTRY_FILE = "user_registry.json"

    def __init__(self, data_dir: Optional[str] = None) -> None:
        data_path = Path(data_dir) if data_dir else self._DEFAULT_DATA_DIR
        data_path.mkdir(parents=True, exist_ok=True)
        self._registry_file = data_path / self._REGISTRY_FILE
        self._lock = threading.RLock()
        self._users: Dict[str, UserRecord] = {}
        self._load()
        logger.info("👥 UserRegistry ready | users=%d", len(self._users))

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_user(
        self,
        user_id: Optional[str] = None,
        display_name: str = "",
        email: str = "",
        plan: str = "starter",
        daily_target_usd: Optional[float] = None,
        notes: str = "",
        metadata: Optional[dict] = None,
    ) -> UserRecord:
        """
        Register a new user.  If ``user_id`` is omitted a UUID is generated.

        Returns the new UserRecord.
        Raises ValueError if the user already exists.
        """
        if plan not in VALID_PLANS:
            raise ValueError(f"Invalid plan '{plan}'. Must be one of: {VALID_PLANS}")

        with self._lock:
            uid = user_id or str(uuid.uuid4())[:8]
            if uid in self._users:
                raise ValueError(f"User '{uid}' already registered")

            defaults = PLAN_DEFAULTS[plan]
            record = UserRecord(
                user_id=uid,
                display_name=display_name or uid,
                email=email,
                plan=plan,
                daily_target_usd=(
                    daily_target_usd
                    if daily_target_usd is not None
                    else defaults["daily_target_usd"]
                ),
                max_positions=defaults["max_positions"],
                monthly_usd=defaults["monthly_usd"],
                created_at=_ts(),
                updated_at=_ts(),
                notes=notes,
                metadata=metadata or {},
            )
            self._users[uid] = record
            self._save()
            logger.info(
                "✅ Registered user '%s' (plan=%s, target=$%.2f)",
                uid,
                plan,
                record.daily_target_usd,
            )
            return record

    def remove_user(self, user_id: str) -> bool:
        """
        Remove a user from the registry.

        Returns True if removed, False if not found.
        """
        with self._lock:
            if user_id not in self._users:
                return False
            del self._users[user_id]
            self._save()
        logger.info("🗑️  Removed user '%s'", user_id)
        return True

    def update_user(self, user_id: str, **kwargs) -> Optional[UserRecord]:
        """
        Update mutable fields on a user record.

        Supported kwargs: display_name, email, plan, daily_target_usd,
        active, notes, metadata.

        Returns the updated record or None if not found.
        """
        with self._lock:
            record = self._users.get(user_id)
            if record is None:
                return None
            if "plan" in kwargs:
                plan = kwargs.pop("plan")
                if plan not in VALID_PLANS:
                    raise ValueError(f"Invalid plan '{plan}'")
                defaults = PLAN_DEFAULTS[plan]
                record.plan = plan
                record.monthly_usd = defaults["monthly_usd"]
                if "daily_target_usd" not in kwargs:
                    record.daily_target_usd = defaults["daily_target_usd"]
                if "max_positions" not in kwargs:
                    record.max_positions = defaults["max_positions"]
            for k, v in kwargs.items():
                if hasattr(record, k):
                    setattr(record, k, v)
            record.updated_at = _ts()
            self._save()
        return record

    # ------------------------------------------------------------------
    # Kill switch
    # ------------------------------------------------------------------

    def set_kill_switch(
        self,
        user_id: str,
        active: bool,
        reason: str = "",
    ) -> bool:
        """
        Enable or disable the kill switch for a specific user.

        Returns True if the user was found and updated.
        """
        with self._lock:
            record = self._users.get(user_id)
            if record is None:
                logger.warning("kill_switch: user '%s' not found", user_id)
                return False
            record.kill_switch_active = active
            record.kill_switch_reason = reason if active else ""
            record.updated_at = _ts()
            self._save()
        state_str = "ACTIVATED" if active else "CLEARED"
        logger.info(
            "🔴 Kill switch %s for user '%s': %s",
            state_str,
            user_id,
            reason,
        )
        return True

    def is_kill_switch_active(self, user_id: str) -> bool:
        """Return True if the user's kill switch is currently active."""
        with self._lock:
            record = self._users.get(user_id)
            return record.kill_switch_active if record else False

    # ------------------------------------------------------------------
    # Stats update (called by trading layer)
    # ------------------------------------------------------------------

    def record_trade_result(
        self,
        user_id: str,
        pnl_usd: float,
        is_win: bool,
    ) -> bool:
        """
        Update lifetime PnL stats for a user after a trade closes.

        Returns True if the user was found.
        """
        with self._lock:
            record = self._users.get(user_id)
            if record is None:
                return False
            record.total_pnl_usd += pnl_usd
            record.total_trades += 1
            if is_win:
                record.winning_trades += 1
            record.updated_at = _ts()
            self._save()
        return True

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_user(self, user_id: str) -> Optional[UserRecord]:
        """Return a user record by ID (or None)."""
        with self._lock:
            return self._users.get(user_id)

    def list_users(self, active_only: bool = False) -> List[dict]:
        """
        Return a list of user dicts suitable for API serialization.

        If *active_only* is True, only return users where active=True.
        """
        with self._lock:
            users = list(self._users.values())
        if active_only:
            users = [u for u in users if u.active]
        return [u.to_dict() for u in users]

    def user_count(self) -> int:
        """Total number of registered users."""
        with self._lock:
            return len(self._users)

    def active_user_count(self) -> int:
        """Number of active users."""
        with self._lock:
            return sum(1 for u in self._users.values() if u.active)

    def get_summary(self) -> dict:
        """High-level summary for the dashboard."""
        with self._lock:
            users = list(self._users.values())
        total = len(users)
        active = sum(1 for u in users if u.active)
        kill_active = sum(1 for u in users if u.kill_switch_active)
        total_pnl = sum(u.total_pnl_usd for u in users)
        plans: Dict[str, int] = {}
        for u in users:
            plans[u.plan] = plans.get(u.plan, 0) + 1
        mrr = sum(u.monthly_usd for u in users if u.active)
        return {
            "total_users": total,
            "active_users": active,
            "kill_switch_active_count": kill_active,
            "total_pnl_usd": round(total_pnl, 2),
            "monthly_recurring_revenue_usd": round(mrr, 2),
            "plan_breakdown": plans,
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save(self) -> None:
        """Persist registry to disk (must be called with self._lock held)."""
        try:
            data = [u.to_dict() for u in self._users.values()]
            tmp = str(self._registry_file) + ".tmp"
            with open(tmp, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, self._registry_file)
        except Exception as exc:
            logger.error("UserRegistry save failed: %s", exc)

    def _load(self) -> None:
        if not self._registry_file.exists():
            return
        try:
            with open(self._registry_file) as f:
                rows = json.load(f)
            for row in rows:
                uid = row.get("user_id")
                if not uid:
                    continue
                # Strip computed properties before constructing
                row.pop("win_rate_pct", None)
                self._users[uid] = UserRecord(**{
                    k: row[k] for k in UserRecord.__dataclass_fields__ if k in row
                })
            logger.debug("Loaded %d users from registry", len(self._users))
        except Exception as exc:
            logger.error("UserRegistry load failed: %s", exc)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[UserRegistry] = None
_instance_lock = threading.Lock()


def get_user_registry(data_dir: Optional[str] = None) -> UserRegistry:
    """Return the process-wide singleton UserRegistry."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = UserRegistry(data_dir=data_dir)
        return _instance


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()
