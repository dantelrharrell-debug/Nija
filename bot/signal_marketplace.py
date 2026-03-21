"""
NIJA Signal Marketplace
========================

Foundation layer for signal distribution, subscriptions, and monetisation.

Architecture overview
---------------------
::

    ┌──────────────────────────────────────────────────────────────────┐
    │                     SignalMarketplace                            │
    │                                                                  │
    │  Signal providers (strategies) → publish signals                │
    │  Subscribers (users/accounts)  → receive signals                │
    │                                                                  │
    │  Core operations:                                                │
    │    publish_signal(provider, symbol, side, confidence, meta)      │
    │      → signal_id (UUID)                                          │
    │                                                                  │
    │    subscribe(subscriber_id, provider_id, tier)                   │
    │    unsubscribe(subscriber_id, provider_id)                       │
    │                                                                  │
    │    get_signals_for_subscriber(subscriber_id)                     │
    │      → List[Signal]  (only from subscribed providers)           │
    │                                                                  │
    │    record_copy_outcome(signal_id, subscriber_id, pnl_usd, won)  │
    │      → tracks copy-trading P&L per subscriber                   │
    │                                                                  │
    │  Subscription tiers:                                             │
    │    FREE    – delayed signals, limited to 1 provider              │
    │    BASIC   – near-real-time, up to 3 providers                   │
    │    PRO     – real-time, unlimited providers                      │
    │    ELITE   – real-time + priority routing + advanced analytics   │
    │                                                                  │
    │  Persistence: data/signal_marketplace.jsonl (signal audit)      │
    │               data/signal_marketplace_subs.json (subscriptions) │
    └──────────────────────────────────────────────────────────────────┘

Usage
-----
::

    from bot.signal_marketplace import get_signal_marketplace, SubscriptionTier

    mp = get_signal_marketplace()

    # Subscribe a user account to a strategy provider:
    mp.subscribe("account_alice", provider_id="ApexTrend", tier=SubscriptionTier.PRO)

    # Publish a signal from a strategy (called by the strategy engine):
    sig_id = mp.publish_signal(
        provider_id="ApexTrend",
        symbol="BTC-USD",
        side="long",
        confidence=0.82,
        entry_price=42_000.0,
        stop_loss_price=41_000.0,
        take_profit_price=44_000.0,
    )

    # Retrieve pending signals for a subscriber's copy-trading engine:
    signals = mp.get_signals_for_subscriber("account_alice")

    # After the copy trade closes:
    mp.record_copy_outcome(sig_id, "account_alice", pnl_usd=+95.0, won=True)

    print(mp.get_report())

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger("nija.signal_marketplace")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_DATA_DIR: str = "data"
MAX_SIGNAL_QUEUE: int = 500       # per-provider rolling signal buffer
MAX_SIGNAL_AGE_S: float = 300.0   # signals older than 5 min are expired

# Tier provider limits
_TIER_PROVIDER_LIMIT: dict = {}    # populated after SubscriptionTier defined


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class SubscriptionTier(str, Enum):
    FREE = "FREE"
    BASIC = "BASIC"
    PRO = "PRO"
    ELITE = "ELITE"


_TIER_PROVIDER_LIMIT = {
    SubscriptionTier.FREE: 1,
    SubscriptionTier.BASIC: 3,
    SubscriptionTier.PRO: 999,
    SubscriptionTier.ELITE: 999,
}

# Signal delay per tier (seconds; FREE gets delayed signals)
_TIER_DELAY_S: dict[SubscriptionTier, float] = {
    SubscriptionTier.FREE: 60.0,
    SubscriptionTier.BASIC: 5.0,
    SubscriptionTier.PRO: 0.0,
    SubscriptionTier.ELITE: 0.0,
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Signal:
    """A single trading signal published by a strategy provider."""
    signal_id: str
    provider_id: str
    published_at: str         # ISO timestamp
    symbol: str
    side: str                 # "long" | "short"
    confidence: float         # 0.0 – 1.0
    entry_price: float
    stop_loss_price: float
    take_profit_price: float
    meta: Dict[str, Any] = field(default_factory=dict)

    def age_seconds(self) -> float:
        try:
            ts = datetime.fromisoformat(self.published_at)
            now = datetime.now(timezone.utc)
            if ts.tzinfo is None:
                from datetime import timezone as _tz
                ts = ts.replace(tzinfo=_tz.utc)
            return (now - ts).total_seconds()
        except Exception:
            return 0.0

    def is_expired(self) -> bool:
        return self.age_seconds() > MAX_SIGNAL_AGE_S

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Subscription:
    """One subscriber → provider subscription record."""
    subscriber_id: str
    provider_id: str
    tier: SubscriptionTier
    subscribed_at: str


@dataclass
class CopyOutcome:
    """Result of a copy-trade execution."""
    signal_id: str
    provider_id: str          # provider that published the signal
    subscriber_id: str
    closed_at: str
    pnl_usd: float
    won: bool


@dataclass
class ProviderStats:
    """Aggregated stats for a signal provider."""
    provider_id: str
    signals_published: int
    copy_trades: int
    copy_wins: int
    copy_win_rate: float
    total_copy_pnl: float
    subscriber_count: int


# ---------------------------------------------------------------------------
# Marketplace
# ---------------------------------------------------------------------------

class SignalMarketplace:
    """
    Central hub for signal publication, subscription management, and
    copy-trading outcome tracking.
    """

    def __init__(self, data_dir: Optional[str] = None) -> None:
        self._data_dir = Path(data_dir or DEFAULT_DATA_DIR)
        self._data_dir.mkdir(parents=True, exist_ok=True)

        # Signal buffers per provider
        self._signals: Dict[str, Deque[Signal]] = {}
        # Subscriptions: subscriber_id → list of Subscription
        self._subscriptions: Dict[str, List[Subscription]] = {}
        # Copy outcomes: provider_id → list of CopyOutcome
        self._copy_outcomes: Dict[str, List[CopyOutcome]] = {}
        # Provider counters
        self._provider_signal_count: Dict[str, int] = {}
        # Index: signal_id → provider_id (for fast outcome attribution)
        self._signal_provider_index: Dict[str, str] = {}

        self._lock = threading.Lock()
        self._load_state()
        logger.info("SignalMarketplace initialised (data_dir=%s)", self._data_dir)

    # ------------------------------------------------------------------
    # Signal publication
    # ------------------------------------------------------------------

    def publish_signal(
        self,
        provider_id: str,
        symbol: str,
        side: str,
        confidence: float,
        entry_price: float = 0.0,
        stop_loss_price: float = 0.0,
        take_profit_price: float = 0.0,
        meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Publish a new trading signal.

        Returns the signal_id (UUID string).
        """
        sig = Signal(
            signal_id=str(uuid.uuid4()),
            provider_id=provider_id,
            published_at=datetime.now(timezone.utc).isoformat(),
            symbol=symbol,
            side=side,
            confidence=max(0.0, min(1.0, confidence)),
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            meta=meta or {},
        )
        with self._lock:
            if provider_id not in self._signals:
                self._signals[provider_id] = deque(maxlen=MAX_SIGNAL_QUEUE)
                self._provider_signal_count[provider_id] = 0
            self._signals[provider_id].append(sig)
            self._provider_signal_count[provider_id] += 1
            self._signal_provider_index[sig.signal_id] = provider_id

        self._append_signal_audit(sig)
        logger.debug(
            "SignalMarketplace: published signal %s by %s %s %s conf=%.2f",
            sig.signal_id[:8], provider_id, side.upper(), symbol, confidence,
        )
        return sig.signal_id

    # ------------------------------------------------------------------
    # Subscription management
    # ------------------------------------------------------------------

    def subscribe(
        self,
        subscriber_id: str,
        provider_id: str,
        tier: SubscriptionTier = SubscriptionTier.BASIC,
    ) -> bool:
        """
        Subscribe a user/account to a signal provider.

        Enforces provider limits per tier.  Returns True on success.
        """
        with self._lock:
            subs = self._subscriptions.setdefault(subscriber_id, [])
            # Already subscribed?
            if any(s.provider_id == provider_id for s in subs):
                logger.debug("SignalMarketplace: %s already subscribed to %s", subscriber_id, provider_id)
                return True
            # Tier limit check
            limit = _TIER_PROVIDER_LIMIT.get(tier, 1)
            if len(subs) >= limit:
                logger.warning(
                    "SignalMarketplace: %s at provider limit (%d) for tier %s",
                    subscriber_id, limit, tier.value,
                )
                return False
            subs.append(Subscription(
                subscriber_id=subscriber_id,
                provider_id=provider_id,
                tier=tier,
                subscribed_at=datetime.now(timezone.utc).isoformat(),
            ))

        self._save_subscriptions()
        logger.info("SignalMarketplace: %s subscribed to %s (tier=%s)", subscriber_id, provider_id, tier.value)
        return True

    def unsubscribe(self, subscriber_id: str, provider_id: str) -> bool:
        """Remove a subscription. Returns True if it existed."""
        with self._lock:
            subs = self._subscriptions.get(subscriber_id, [])
            before = len(subs)
            self._subscriptions[subscriber_id] = [s for s in subs if s.provider_id != provider_id]
            changed = len(self._subscriptions[subscriber_id]) < before

        if changed:
            self._save_subscriptions()
            logger.info("SignalMarketplace: %s unsubscribed from %s", subscriber_id, provider_id)
        return changed

    # ------------------------------------------------------------------
    # Signal delivery
    # ------------------------------------------------------------------

    def get_signals_for_subscriber(
        self, subscriber_id: str, max_age_s: Optional[float] = None
    ) -> List[Signal]:
        """
        Return all non-expired signals for a subscriber's active providers,
        respecting tier-based delays.
        """
        age_limit = max_age_s if max_age_s is not None else MAX_SIGNAL_AGE_S
        with self._lock:
            subs = self._subscriptions.get(subscriber_id, [])
            result: List[Signal] = []
            for sub in subs:
                delay = _TIER_DELAY_S.get(sub.tier, 0.0)
                queue = self._signals.get(sub.provider_id, deque())
                for sig in queue:
                    age = sig.age_seconds()
                    if age > age_limit:
                        continue
                    if age < delay:
                        continue  # signal too fresh for this tier
                    result.append(sig)
        return result

    # ------------------------------------------------------------------
    # Copy-trade outcome tracking
    # ------------------------------------------------------------------

    def record_copy_outcome(
        self,
        signal_id: str,
        subscriber_id: str,
        pnl_usd: float,
        won: bool,
    ) -> None:
        """Record the result of a subscriber copying a signal."""
        with self._lock:
            provider_id_resolved = self._signal_provider_index.get(signal_id, "unknown")
        outcome = CopyOutcome(
            signal_id=signal_id,
            provider_id=provider_id_resolved,
            subscriber_id=subscriber_id,
            closed_at=datetime.now(timezone.utc).isoformat(),
            pnl_usd=pnl_usd,
            won=won,
        )
        with self._lock:
            self._copy_outcomes.setdefault(provider_id_resolved, []).append(outcome)

        self._append_outcome_audit(outcome)

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------

    def get_provider_stats(self, provider_id: str) -> ProviderStats:
        """Aggregate copy-trade stats for a provider."""
        with self._lock:
            signal_count = self._provider_signal_count.get(provider_id, 0)
            subscriber_count = sum(
                1 for subs in self._subscriptions.values()
                if any(s.provider_id == provider_id for s in subs)
            )
            # Only outcomes attributed to this provider
            outcomes: List[CopyOutcome] = list(self._copy_outcomes.get(provider_id, []))

        copy_trades = len(outcomes)
        wins = sum(1 for o in outcomes if o.won)
        wr = wins / copy_trades if copy_trades > 0 else 0.0
        total_pnl = sum(o.pnl_usd for o in outcomes)

        return ProviderStats(
            provider_id=provider_id,
            signals_published=signal_count,
            copy_trades=copy_trades,
            copy_wins=wins,
            copy_win_rate=wr,
            total_copy_pnl=total_pnl,
            subscriber_count=subscriber_count,
        )

    def get_all_providers(self) -> List[str]:
        """List all providers that have published at least one signal."""
        with self._lock:
            return list(self._signals.keys())

    def get_report(self) -> str:
        """Human-readable marketplace status report."""
        with self._lock:
            total_subs = sum(len(v) for v in self._subscriptions.values())
            total_signals = sum(self._provider_signal_count.values())
            providers = list(self._signals.keys())

        lines = [
            "═══════════════════════════════════════════════════",
            "  NIJA Signal Marketplace",
            "═══════════════════════════════════════════════════",
            f"  Providers       : {len(providers)}",
            f"  Total signals   : {total_signals}",
            f"  Active subs     : {total_subs}",
            "───────────────────────────────────────────────────",
        ]
        for pid in providers:
            stats = self.get_provider_stats(pid)
            lines.append(
                f"  [{pid}]  signals={stats.signals_published}"
                f"  subs={stats.subscriber_count}"
                f"  copy_trades={stats.copy_trades}"
                f"  win_rate={stats.copy_win_rate:.1%}"
                f"  P&L=${stats.total_copy_pnl:,.2f}"
            )
        lines.append("═══════════════════════════════════════════════════")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _append_signal_audit(self, sig: Signal) -> None:
        try:
            path = self._data_dir / "signal_marketplace.jsonl"
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(sig.to_dict()) + "\n")
        except OSError as exc:
            logger.warning("SignalMarketplace: signal audit write failed: %s", exc)

    def _append_outcome_audit(self, outcome: CopyOutcome) -> None:
        try:
            path = self._data_dir / "signal_marketplace_outcomes.jsonl"
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(outcome)) + "\n")
        except OSError as exc:
            logger.warning("SignalMarketplace: outcome audit write failed: %s", exc)

    def _save_subscriptions(self) -> None:
        path = self._data_dir / "signal_marketplace_subs.json"
        try:
            with self._lock:
                data = {
                    sub_id: [asdict(s) for s in subs]
                    for sub_id, subs in self._subscriptions.items()
                }
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("SignalMarketplace: subscription save failed: %s", exc)

    def _load_state(self) -> None:
        subs_path = self._data_dir / "signal_marketplace_subs.json"
        if subs_path.exists():
            try:
                data = json.loads(subs_path.read_text(encoding="utf-8"))
                for sub_id, subs_raw in data.items():
                    self._subscriptions[sub_id] = [
                        Subscription(
                            subscriber_id=s["subscriber_id"],
                            provider_id=s["provider_id"],
                            tier=SubscriptionTier(s["tier"]),
                            subscribed_at=s["subscribed_at"],
                        )
                        for s in subs_raw
                    ]
                logger.info(
                    "SignalMarketplace: loaded %d subscriber records",
                    len(self._subscriptions),
                )
            except Exception as exc:
                logger.warning("SignalMarketplace: load subscriptions failed: %s", exc)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_INSTANCE: Optional[SignalMarketplace] = None
_INSTANCE_LOCK = threading.Lock()


def get_signal_marketplace(data_dir: Optional[str] = None) -> SignalMarketplace:
    """Thread-safe singleton accessor."""
    global _INSTANCE
    with _INSTANCE_LOCK:
        if _INSTANCE is None:
            _INSTANCE = SignalMarketplace(data_dir=data_dir)
    return _INSTANCE
