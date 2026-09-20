"""
NIJA Signal Broadcaster
========================

Broadcasts a validated trade signal to **multiple accounts / brokers** while
applying proportional, risk-adjusted position sizing via the GlobalCapitalManager.

Each account receives a trade sized by:
    base_size = account.balance * risk_fraction
    final_size = base_size * capital_manager.get_allocation(account.id)

This means larger accounts naturally get larger positions while the
portfolio-wide risk budget is still respected.

Usage
-----
::

    from bot.signal_broadcaster import get_signal_broadcaster, BroadcastSignal

    broadcaster = get_signal_broadcaster()

    broadcaster.register_account("coinbase", coinbase_broker, balance=5000.0)
    broadcaster.register_account("kraken",   kraken_broker,   balance=3000.0)

    results = broadcaster.execute_across_accounts({
        "action": "enter_long",
        "symbol": "BTC-USD",
    })

    for r in results:
        print(r.account_id, "->", r.status, r.error or "")

Retry System
------------
Every per-account execution is automatically retried on transient failures
using exponential backoff::

    RetryConfig(max_retries=3, base_delay_s=1.0, backoff_factor=2.0, max_delay_s=30.0)

Retry schedule (defaults): 1 s → 2 s → 4 s (capped at 30 s).
"skipped" results (e.g. size_zero) are never retried.
All retries are fail-safe — exceptions never propagate to the caller.
``BroadcastResult.attempts`` records how many attempts were made and
``BroadcastResult.retry_exhausted`` is ``True`` when all retries failed.

Author: NIJA Trading Systems
Version: 2.1
Date: March 2026
"""

from __future__ import annotations

import hashlib
import logging
import os
import random
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bot.control.decision_context import (
    PROTECTION_CONFIRMED,
    PROTECTION_UNVERIFIED,
    UserDecisionContext,
    UserPortfolioSnapshot,
)

from bot.feature_flags import get_strategy_execution_mode

logger = logging.getLogger("nija.signal_broadcaster")

DEFAULT_RISK_FRACTION = 0.02
SEED_HEX_LENGTH = 16  # 16 hex chars (64-bit seed) for jitter randomization
JITTER_BUCKET_SECONDS = 60


def _get_env_float(name: str, default: float) -> float:
    """Read a float environment variable with safe fallback."""
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = str(raw).strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# Retry configuration
# ---------------------------------------------------------------------------

@dataclass
class RetryConfig:
    """Exponential-backoff retry policy for per-account broadcast attempts.

    Attributes:
        max_retries:    Maximum number of *additional* attempts after the first.
                        Set to 0 to disable retries entirely.
        base_delay_s:   Delay (seconds) before the first retry.
        backoff_factor: Multiplier applied to the delay on each subsequent retry.
        max_delay_s:    Hard cap on inter-retry delay (seconds).
    """
    max_retries: int = 3
    base_delay_s: float = 1.0
    backoff_factor: float = 2.0
    max_delay_s: float = 30.0

# ---------------------------------------------------------------------------
# Optional dependency: GlobalCapitalManager
# ---------------------------------------------------------------------------
try:
    from global_capital_manager import get_global_capital_manager
    _GCM_AVAILABLE = True
except ImportError:
    try:
        from bot.global_capital_manager import get_global_capital_manager
        _GCM_AVAILABLE = True
    except ImportError:
        _GCM_AVAILABLE = False
        get_global_capital_manager = None  # type: ignore[assignment]

try:
    from bot.pipeline_order_submitter import submit_market_order_via_pipeline
except ImportError:
    try:
        from pipeline_order_submitter import submit_market_order_via_pipeline  # type: ignore[import]
    except ImportError:
        submit_market_order_via_pipeline = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Data structures (non-default fields FIRST)
# ---------------------------------------------------------------------------

@dataclass
class BroadcastSignal:
    """Signal to broadcast across multiple accounts."""
    symbol: str
    side: str                     # "buy" / "sell" / "long" / "short"
    size_usd: float               # base position size in USD
    strategy: str = ""
    account_ids: List[str] = field(default_factory=list)
    order_type: Optional[str] = None
    asset_class: Optional[str] = None
    # Optional per-account size overrides (account_id -> fraction of size_usd)
    account_fractions: Dict[str, float] = field(default_factory=dict)


@dataclass
class AccountResult:
    """Execution result for one account."""
    account_id: str
    success: bool
    fill_price: float = 0.0
    filled_size_usd: float = 0.0
    broker: str = ""
    error: str = ""
    latency_ms: float = 0.0


@dataclass
class AccountRecord:
    """Broker account registered for signal broadcasting."""
    account_id: str
    broker: Any                      # BaseBroker instance
    balance: float = 0.0


@dataclass
class BroadcastResult:
    """Result of executing a broadcast signal on a single account."""
    account_id: str
    symbol: str
    side: str
    size_usd: float
    status: str                      # "filled" | "skipped" | "error"
    order_result: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    attempts: int = 1                # total execution attempts made (1 = no retries)
    retry_exhausted: bool = False    # True when all retries failed
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class AccountDecision:
    """Account-specific decision input derived from a shared market signal."""
    account_id: str
    user_id: str
    broker: str
    decision_context: UserDecisionContext
    portfolio_snapshot: UserPortfolioSnapshot
    proposed_size_usd: float
    signal: Dict[str, Any]


# ---------------------------------------------------------------------------
# SignalBroadcaster
# ---------------------------------------------------------------------------

class SignalBroadcaster:
    """
    Executes a master signal across all registered broker accounts
    with proportional, risk-adjusted position sizing.
    """

    def __init__(
        self,
        risk_fraction: float = DEFAULT_RISK_FRACTION,
        retry_config: Optional[RetryConfig] = None,
    ) -> None:
        self._accounts: Dict[str, AccountRecord] = {}
        self._risk_fraction = risk_fraction
        self._retry_config = retry_config or RetryConfig()
        self._lock = threading.Lock()
        # Timing divergence controls (defaults add slight jitter/cooldown per account)
        self._execution_jitter_ms = _get_env_float("NIJA_ACCOUNT_EXECUTION_JITTER_MS", 250.0)
        self._cooldown_base_s = _get_env_float("NIJA_ACCOUNT_COOLDOWN_BASE_S", 0.0)
        self._cooldown_jitter_s = _get_env_float("NIJA_ACCOUNT_COOLDOWN_JITTER_S", 0.25)
        self._account_cooldown_offsets: Dict[str, float] = {}
        self._account_last_exec_ts: Dict[str, float] = {}
        self._account_seed_cache: Dict[str, int] = {}

    def _resolve_live_balance(self, broker: Any, candidate_balance: float) -> float:
        """Return a non-negative balance, preferring a live broker balance when available."""
        live_balance = 0.0
        try:
            if broker is not None and hasattr(broker, "get_account_balance"):
                raw = broker.get_account_balance()
                if isinstance(raw, dict):
                    live_balance = float(
                        raw.get("trading_balance")
                        or raw.get("available_balance")
                        or raw.get("balance")
                        or 0.0
                    )
                else:
                    live_balance = float(raw or 0.0)
        except Exception as exc:
            logger.debug("[Broadcaster] live balance fetch failed: %s", exc)

        if live_balance <= 0.0:
            try:
                live_balance = float(getattr(broker, "_last_known_balance", 0.0) or 0.0)
            except Exception:
                live_balance = 0.0

        if live_balance <= 0.0:
            return max(0.0, float(candidate_balance or 0.0))
        return max(0.0, live_balance)

    def _resolve_buying_power(self, broker: Any, fallback_balance: float) -> float:
        """Return broker buying power when exposed, else fall back to live balance."""
        buying_power = 0.0
        try:
            if broker is not None and hasattr(broker, "get_account_balance"):
                raw = broker.get_account_balance()
                if isinstance(raw, dict):
                    buying_power = float(
                        raw.get("buying_power")
                        or raw.get("available_buying_power")
                        or raw.get("available_balance")
                        or raw.get("trading_balance")
                        or raw.get("free_margin")
                        or 0.0
                    )
        except Exception as exc:
            logger.debug("[Broadcaster] buying power fetch failed: %s", exc)
        if buying_power <= 0.0:
            return max(0.0, float(fallback_balance or 0.0))
        return max(0.0, buying_power)

    # ── Account registry ─────────────────────────────────────────────────────

    def register_account(
        self,
        account_id: str,
        broker: Any,
        balance: float = 0.0,
    ) -> None:
        """Register (or update) a broker account for fan-out execution."""
        resolved_balance = self._resolve_live_balance(broker, balance)
        with self._lock:
            self._accounts[account_id] = AccountRecord(
                account_id=account_id,
                broker=broker,
                balance=resolved_balance,
            )
            if account_id not in self._account_cooldown_offsets:
                self._account_cooldown_offsets[account_id] = self._compute_account_cooldown_offset(account_id)
            # Keep GlobalCapitalManager in sync
            if _GCM_AVAILABLE and get_global_capital_manager:
                try:
                    get_global_capital_manager().register_account(account_id, resolved_balance)
                except Exception:
                    pass
        logger.debug("[Broadcaster] registered account %s balance=%.2f", account_id, resolved_balance)

    def update_balance(self, account_id: str, balance: float) -> None:
        """Update the cached balance for an account (call each trading cycle)."""
        with self._lock:
            if account_id in self._accounts:
                record = self._accounts[account_id]
                resolved_balance = self._resolve_live_balance(record.broker, balance)
                record.balance = resolved_balance
                if _GCM_AVAILABLE and get_global_capital_manager:
                    try:
                        get_global_capital_manager().register_account(account_id, resolved_balance)
                    except Exception:
                        pass

    def account_ids(self) -> List[str]:
        """Return a snapshot of registered account IDs."""
        with self._lock:
            return list(self._accounts.keys())

    # ── Core fan-out ──────────────────────────────────────────────────────────

    def execute_across_accounts(
        self,
        signal: Dict[str, Any],
    ) -> List[BroadcastResult]:
        """
        Execute *signal* on every registered account.

        Sizing per account
        ------------------
        1. ``base_size = account.balance × risk_fraction``
        2. ``size *= capital_manager.get_allocation(account.id)``   ← weighted

        Args:
            signal: Dict with at minimum ``{'action': str, 'symbol': str}``.
                    Use the dict from ``ApexStrategy.analyze_market()`` or
                    ``MasterStrategyRouter.get_signal()``.

        Returns:
            List of BroadcastResult, one per account.
        """
        action = signal.get("action", "hold")
        symbol = signal.get("symbol", "")
        side = "buy" if action == "enter_long" else "sell" if action == "enter_short" else ""

        results: List[BroadcastResult] = []

        if not side or not symbol:
            logger.debug(
                "[Broadcaster] skipping fan-out — action=%s symbol=%s", action, symbol
            )
            return results

        with self._lock:
            accounts_snapshot = list(self._accounts.values())

        capital_manager = (
            get_global_capital_manager()
            if _GCM_AVAILABLE and get_global_capital_manager
            else None
        )

        for account in accounts_snapshot:
            result = self._execute_with_retry(
                account=account,
                signal=signal,
                symbol=symbol,
                side=side,
                capital_manager=capital_manager,
            )
            results.append(result)

        filled = sum(1 for r in results if r.status == "filled")
        logger.info(
            "[Broadcaster] %s %s → %d/%d accounts filled",
            side.upper(), symbol, filled, len(results),
        )
        return results

    def build_account_decisions(
        self,
        signal: Dict[str, Any],
    ) -> List[AccountDecision]:
        """Build isolated account-scoped decision inputs from one shared market signal."""
        symbol = str(signal.get("symbol") or "")
        strategy_signal_id = str(signal.get("strategy_signal_id") or signal.get("signal_id") or "")
        trade_id_prefix = str(signal.get("trade_id") or strategy_signal_id or symbol or "signal")
        strategy = str(signal.get("strategy") or "SignalBroadcaster")

        with self._lock:
            accounts_snapshot = list(self._accounts.values())

        decisions: List[AccountDecision] = []
        capital_manager = (
            get_global_capital_manager()
            if _GCM_AVAILABLE and get_global_capital_manager
            else None
        )
        for account in accounts_snapshot:
            broker_name = self._broker_name(account.broker)
            user_id = self._user_for_account(account)
            portfolio_id = f"{broker_name}:{account.account_id}"
            live_balance = self._resolve_live_balance(account.broker, account.balance)
            buying_power = self._resolve_buying_power(account.broker, live_balance)
            allocation = 1.0
            if capital_manager is not None:
                try:
                    allocation = float(capital_manager.get_allocation(account.account_id))
                except Exception:
                    allocation = 1.0
            proposed_size_usd = round(live_balance * self._risk_fraction * allocation, 2)
            positions, positions_proven = self._positions_for_broker(account.broker)
            pending_orders, orders_proven = self._pending_orders_for_broker(account.broker)
            broker_healthy = self._broker_is_healthy(account.broker)
            configured_mode = get_strategy_execution_mode().strip().lower()
            execution_mode = str(signal.get("execution_mode") or configured_mode).strip().lower()
            environment = str(
                signal.get("environment")
                or ("production" if execution_mode in {"live", "limited_live"} else "test")
            ).strip()
            decision_context = UserDecisionContext(
                user_id=user_id,
                account_id=account.account_id,
                broker=broker_name,
                portfolio_id=portfolio_id,
                strategy_signal_id=strategy_signal_id or f"{strategy}:{symbol}",
                trade_id=f"{trade_id_prefix}:{account.account_id}",
                asset_class=signal.get("asset_class"),
                execution_mode=execution_mode,
                environment=environment,
            )
            portfolio_snapshot = UserPortfolioSnapshot(
                user_id=user_id,
                account_id=account.account_id,
                broker=broker_name,
                balance=live_balance,
                equity=live_balance,
                available_buying_power=buying_power,
                open_positions=tuple(positions),
                pending_orders=tuple(pending_orders),
                portfolio_exposure=sum(float(p.get("usd_value") or p.get("size_usd") or 0.0) for p in positions),
                protection_state=self._protection_state_for_broker(account.broker),
                authoritative_positions_proven=positions_proven and broker_healthy,
                broker_healthy=broker_healthy,
                positions_fresh=positions_proven,
                orders_fresh=orders_proven,
                metadata={
                    "strategy": strategy,
                    # Kraken entry admission must remain fail-closed unless the
                    # broker adapter explicitly proves authoritative margin
                    # position visibility. Never infer proof from an empty list.
                    "kraken_margin_visibility_proven": (
                        self._kraken_margin_visibility_proven(account.broker)
                        if broker_name == "kraken"
                        else True
                    ),
                },
            )
            decisions.append(
                AccountDecision(
                    account_id=account.account_id,
                    user_id=user_id,
                    broker=broker_name,
                    decision_context=decision_context,
                    portfolio_snapshot=portfolio_snapshot,
                    proposed_size_usd=proposed_size_usd,
                    signal=dict(signal),
                )
            )
        return decisions

    def _execute_with_retry(
        self,
        account: AccountRecord,
        signal: Dict[str, Any],
        symbol: str,
        side: str,
        capital_manager: Any,
    ) -> BroadcastResult:
        """Execute signal for one account, retrying on transient errors.

        Uses exponential backoff governed by ``self._retry_config``.
        "skipped" results (e.g. size_zero) are never retried.
        This method is always fail-safe — it never raises an exception.
        """
        cfg = self._retry_config
        self._apply_account_timing_controls(account.account_id, symbol)
        result = self._execute_single(
            account=account,
            signal=signal,
            symbol=symbol,
            side=side,
            capital_manager=capital_manager,
        )

        # Don't retry skipped orders or successful fills
        if result.status != "error" or cfg.max_retries <= 0:
            return result

        delay = cfg.base_delay_s
        for attempt in range(1, cfg.max_retries + 1):
            capped_delay = min(delay, cfg.max_delay_s)
            logger.warning(
                "[Broadcaster] retry %d/%d for account=%s %s %s in %.1fs — prev: %s",
                attempt, cfg.max_retries,
                account.account_id, side.upper(), symbol,
                capped_delay, result.error,
            )
            time.sleep(capped_delay)

            result = self._execute_single(
                account=account,
                signal=signal,
                symbol=symbol,
                side=side,
                capital_manager=capital_manager,
            )
            result.attempts = attempt + 1  # 1 original + N retries so far

            if result.status != "error":
                logger.info(
                    "[Broadcaster] retry %d succeeded for account=%s %s %s",
                    attempt, account.account_id, side.upper(), symbol,
                )
                return result

            delay *= cfg.backoff_factor

        # All retries exhausted
        result.retry_exhausted = True
        logger.error(
            "[Broadcaster] all %d retries exhausted for account=%s %s %s — final error: %s",
            cfg.max_retries, account.account_id, side.upper(), symbol, result.error,
        )
        return result

    def _execute_single(
        self,
        account: AccountRecord,
        signal: Dict[str, Any],
        symbol: str,
        side: str,
        capital_manager: Any,
    ) -> BroadcastResult:
        """Execute signal for one account with proportional sizing."""
        try:
            broker = account.broker

            # 1. Base size: risk_fraction × balance
            size = account.balance * self._risk_fraction

            # 2. Weighted copy trading: scale by account's capital share
            if capital_manager is not None:
                allocation = capital_manager.get_allocation(account.account_id)
                size *= allocation

            size = round(size, 2)

            signal_metadata = signal.get("metadata") if isinstance(signal.get("metadata"), dict) else {}
            duplicate_key = str(signal.get("duplicate_key") or signal_metadata.get("duplicate_key") or "").strip()
            duplicate_token = str(signal.get("duplicate_token") or signal_metadata.get("duplicate_token") or "").strip()
            raw_shared_required = signal.get(
                "duplicate_shared_required",
                signal_metadata.get("duplicate_shared_required", False),
            )
            duplicate_shared_required = (
                raw_shared_required
                if isinstance(raw_shared_required, bool)
                else str(raw_shared_required or "").strip().lower() in {"1", "true", "yes", "on"}
            )

            if size <= 0:
                if duplicate_key and duplicate_token:
                    from bot.control.decision_context import (
                        IdempotencyReservationHandle,
                        get_user_scoped_idempotency_registry,
                    )
                    get_user_scoped_idempotency_registry().release(
                        IdempotencyReservationHandle(duplicate_key, duplicate_token, bool(duplicate_shared_required))
                    )
                return BroadcastResult(
                    account_id=account.account_id,
                    symbol=symbol,
                    side=side,
                    size_usd=size,
                    status="skipped",
                    error="size_zero",
                )

            logger.info(
                "[Broadcaster] → %s | %s %s $%.2f",
                account.account_id, side.upper(), symbol, size,
            )
            self._account_last_exec_ts[account.account_id] = time.monotonic()

            if submit_market_order_via_pipeline is None:
                if duplicate_key and duplicate_token:
                    from bot.control.decision_context import (
                        IdempotencyReservationHandle,
                        get_user_scoped_idempotency_registry,
                    )
                    get_user_scoped_idempotency_registry().release(
                        IdempotencyReservationHandle(duplicate_key, duplicate_token)
                    )
                order = {
                    "status": "error",
                    "error": "ExecutionPipeline submit helper unavailable; direct broker fallback blocked",
                }
            else:
                order = submit_market_order_via_pipeline(
                    broker=broker,
                    symbol=symbol,
                    side=side,
                    quantity=size,
                    size_type="quote",
                    strategy="SignalBroadcaster",
                    metadata_override=(
                        {
                            "duplicate_key": duplicate_key,
                            "duplicate_token": duplicate_token,
                            "duplicate_shared_required": bool(duplicate_shared_required),
                        }
                        if duplicate_key and duplicate_token
                        else None
                    ),
                )

            status = str(order.get("status", "error") if order else "error").lower()
            order_id = (order or {}).get("order_id") or (order or {}).get("id") or (order or {}).get("txid")
            if status == "error" and order_id:
                status = "pending"
            # ACK/open/pending is not fill proof. Preserve the broker/execution
            # pipeline state until authoritative reconciliation proves FILLED.
            if status in {"open", "pending", "accepted", "acknowledged"}:
                status = "pending"
            elif status in {"filled", "closed"}:
                status = "filled"

            return BroadcastResult(
                account_id=account.account_id,
                symbol=symbol,
                side=side,
                size_usd=size,
                status=status,
                order_result=order or {},
            )

        except Exception as exc:
            logger.warning(
                "[Broadcaster] %s error on %s: %s",
                account.account_id, symbol, exc,
            )
            return BroadcastResult(
                account_id=account.account_id,
                symbol=symbol,
                side=side,
                size_usd=0.0,
                status="error",
                error=str(exc),
            )

    def _compute_account_cooldown_offset(self, account_id: str) -> float:
        """Compute a deterministic cooldown offset for an account."""
        if self._cooldown_jitter_s <= 0:
            return 0.0
        seed = self._seed_for_account(account_id)
        rng = random.Random(seed)
        return rng.uniform(0.0, self._cooldown_jitter_s)

    def _seed_for_account(self, account_id: str) -> int:
        """Return a deterministic integer seed for an account.

        64-bit seeds are sufficient for timing jitter (not crypto/security use).
        """
        cached = self._account_seed_cache.get(account_id)
        if cached is not None:
            return cached
        digest = hashlib.sha256(account_id.encode("utf-8")).hexdigest()
        seed = int(digest[:SEED_HEX_LENGTH], 16)
        self._account_seed_cache[account_id] = seed
        return seed

    def _seed_from_components(self, payload: str) -> int:
        """Return a deterministic seed from a composite payload."""
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return int(digest[:SEED_HEX_LENGTH], 16)

    @staticmethod
    def _broker_name(broker: Any) -> str:
        broker_type = getattr(broker, "broker_type", None)
        value = getattr(broker_type, "value", broker_type)
        if value:
            return str(value).strip().lower()
        return str(getattr(broker, "broker_name", "") or getattr(broker, "NAME", "") or "unknown").strip().lower()

    @staticmethod
    def _user_for_account(account: AccountRecord) -> str:
        user_id = getattr(account.broker, "user_id", None) or getattr(account.broker, "nija_user_id", None)
        return str(user_id or account.account_id or "PLATFORM")

    @staticmethod
    def _positions_for_broker(broker: Any) -> tuple[List[Dict[str, Any]], bool]:
        try:
            positions = broker.get_positions()
            if isinstance(positions, list):
                return [dict(p) for p in positions], True
        except Exception:
            return [], False
        return [], False

    @staticmethod
    def _pending_orders_for_broker(broker: Any) -> tuple[List[Dict[str, Any]], bool]:
        getter = getattr(broker, "get_open_orders", None)
        if not callable(getter):
            return [], False
        try:
            orders = getter()
            if isinstance(orders, list):
                return [dict(o) for o in orders], True
        except Exception:
            return [], False
        return [], False

    @staticmethod
    def _kraken_margin_visibility_proven(broker: Any) -> bool:
        """Require explicit proof that Kraken margin OpenPositions are visible.

        Balance/spot-position freshness is insufficient.  V2 stays fail-closed
        until the adapter exposes an explicit margin/OpenPositions authority
        signal.
        """
        for attribute in (
            "kraken_margin_visibility_proven",
            "authoritative_margin_positions_visible",
            "open_positions_visibility_proven",
            "kraken_open_positions_visibility_proven",
        ):
            try:
                value = getattr(broker, attribute, None)
                if callable(value):
                    value = value()
            except Exception:
                return False
            if value is not None:
                return value is True
        try:
            from bot.runtime_kraken_margin_canonical_coverage_v366_patch import fetch_margin_positions
            ok, _positions, _reason = fetch_margin_positions(broker, force=False)
            return ok is True
        except Exception:
            return False

    @staticmethod
    def _broker_is_healthy(broker: Any) -> bool:
        for attribute in ("connected", "is_connected", "healthy", "is_healthy"):
            value = getattr(broker, attribute, None)
            if callable(value):
                try:
                    return bool(value())
                except Exception:
                    return False
            if value is not None:
                return bool(value)
        return True

    @staticmethod
    def _protection_state_for_broker(broker: Any) -> str:
        value = getattr(broker, "protection_state", None)
        if isinstance(value, str) and value.strip():
            return value.strip().upper()
        verified = getattr(broker, "protection_verified", None)
        if verified is False:
            return PROTECTION_UNVERIFIED
        return PROTECTION_CONFIRMED

    def _apply_account_timing_controls(self, account_id: str, symbol: str) -> None:
        """Apply per-account cooldown and jitter to diversify execution timing.

        Jitter uses a per-minute seed bucket based on monotonic time to avoid
        wall-clock adjustments and reduce synchronization across instances.
        """
        cooldown_offset = self._account_cooldown_offsets.get(account_id)
        if cooldown_offset is None:
            cooldown_offset = self._compute_account_cooldown_offset(account_id)
            self._account_cooldown_offsets[account_id] = cooldown_offset

        cooldown_s = max(0.0, self._cooldown_base_s + cooldown_offset)
        last_ts = self._account_last_exec_ts.get(account_id, 0.0)
        if cooldown_s > 0 and last_ts > 0:
            elapsed = time.monotonic() - last_ts
            remaining = cooldown_s - elapsed
            if remaining > 0:
                logger.debug(
                    "[Broadcaster] cooldown delay %.3fs for account=%s",
                    remaining,
                    account_id,
                )
                time.sleep(remaining)

        jitter_s = max(0.0, self._execution_jitter_ms / 1000.0)
        if jitter_s > 0:
            jitter_bucket = int(time.monotonic() // JITTER_BUCKET_SECONDS)
            seed_base = self._seed_for_account(account_id)
            seed = self._seed_from_components(f"{seed_base}:{symbol}:{jitter_bucket}")
            rng = random.Random(seed)
            delay = rng.uniform(0.0, jitter_s)
            if delay > 0:
                logger.debug(
                    "[Broadcaster] jitter delay %.3fs for account=%s",
                    delay,
                    account_id,
                )
                time.sleep(delay)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_BROADCASTER: Optional[SignalBroadcaster] = None
_BROADCASTER_LOCK = threading.Lock()


def get_signal_broadcaster() -> SignalBroadcaster:
    """Return the process-wide SignalBroadcaster singleton."""
    global _BROADCASTER
    with _BROADCASTER_LOCK:
        if _BROADCASTER is None:
            _BROADCASTER = SignalBroadcaster()
            logger.info(
                "[Broadcaster] singleton created "
                "(risk_fraction=%.0f%% per account, max_retries=%d)",
                DEFAULT_RISK_FRACTION * 100,
                _BROADCASTER._retry_config.max_retries,
            )
    return _BROADCASTER
