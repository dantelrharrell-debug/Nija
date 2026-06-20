"""
Kraken margin permission, leverage, and health controls.

The engine provides the single boundary used by order submission and execution
authority gates to decide whether Kraken leverage parameters may be attached to
orders.  It is deliberately fail-closed for live margin entries: unknown
permission state, denied API permissions, critical margin, or stale/low margin
health all block leveraged entries while still allowing the rest of the platform
to fall back to spot orders where the caller supports that path.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import os
import threading
import time
from typing import Any, Optional

try:
    from bot.kraken_error_taxonomy import is_permission_error
except ImportError:  # pragma: no cover - package fallback for script execution
    from kraken_error_taxonomy import is_permission_error  # type: ignore[import]


KRAKEN_MIN_LEVERAGE = 2
HARD_MAX_LEVERAGE = 3
# Kraken TradeBalance returns margin level in percent.  The ratio constants are
# retained for sizing math while gates compare against percentage equivalents.
MAINTENANCE_MARGIN_RATIO_FLOOR = 0.20  # 200% margin level
CRITICAL_MARGIN_RATIO_FLOOR = 0.10     # 100% margin level

_PERMISSION_CACHE_TTL_SECONDS = 300.0
_HEALTH_CACHE_TTL_SECONDS = 15.0


class MarginPermissionState(str, Enum):
    """Cached Kraken margin API permission state."""

    UNKNOWN = "UNKNOWN"
    CONFIRMED = "CONFIRMED"
    DENIED = "DENIED"
    CHECK_FAILED = "CHECK_FAILED"


@dataclass(frozen=True)
class MarginHealthSnapshot:
    """Snapshot consumed by execution authority and pipeline gates."""

    timestamp: float
    permission_state: str
    equivalent_balance_usd: float
    trade_balance_free_usd: float
    margin_level_pct: float
    margin_obligation_usd: float
    free_margin_usd: float
    unrealised_pnl_usd: float
    borrowed_exposure_usd: float
    is_margin_enabled: bool
    maintenance_margin_ok: bool
    critical_margin_breach: bool
    reason: str


class KrakenMarginEngine:
    """Fail-closed controller for Kraken leveraged order admission."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._permission_state = MarginPermissionState.UNKNOWN
        self._permission_checked_at = 0.0
        self._last_snapshot: Optional[MarginHealthSnapshot] = None
        self._snapshot_ts = 0.0
        self._total_notional_usd = 0.0
        self._total_borrowed_usd = 0.0
        self._position_count = 0.0

    @staticmethod
    def _env_truthy(name: str, default: bool = False) -> bool:
        value = os.getenv(name)
        if value is None:
            return default
        return str(value).strip().lower() in {"1", "true", "yes", "on", "y"}

    @staticmethod
    def _to_float(value: Any, default: float = 0.0) -> float:
        try:
            if value is None:
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _clamp_leverage(leverage: Any) -> int:
        try:
            lev = int(float(leverage))
        except (TypeError, ValueError):
            lev = 1
        if lev < KRAKEN_MIN_LEVERAGE:
            return 1
        return max(KRAKEN_MIN_LEVERAGE, min(HARD_MAX_LEVERAGE, lev))

    def invalidate_permission_cache(self) -> None:
        with self._lock:
            self._permission_checked_at = 0.0
            self._permission_state = MarginPermissionState.UNKNOWN

    def invalidate_health_cache(self) -> None:
        with self._lock:
            self._last_snapshot = None
            self._snapshot_ts = 0.0

    def check_permissions(self, adapter: Any) -> MarginPermissionState:
        """Probe Kraken OpenPositions and cache whether margin access is usable."""

        now = time.time()
        with self._lock:
            if (
                self._permission_state in {MarginPermissionState.CONFIRMED, MarginPermissionState.DENIED}
                and now - self._permission_checked_at < _PERMISSION_CACHE_TTL_SECONDS
            ):
                return self._permission_state

        try:
            response = adapter._kraken_api_call("OpenPositions", {"docalcs": "true"})
            errors = response.get("error") or [] if isinstance(response, dict) else []
            if isinstance(errors, str):
                errors = [errors]
            state = (
                MarginPermissionState.DENIED
                if any(is_permission_error(error) for error in errors)
                else MarginPermissionState.CONFIRMED
            )
        except Exception:
            state = MarginPermissionState.CHECK_FAILED

        with self._lock:
            self._permission_state = state
            self._permission_checked_at = now
        return state

    def build_order_margin_params(self, leverage: Any, *, is_reducing: bool = False) -> dict[str, str]:
        """Return Kraken order parameters for leveraged/reduce-only orders."""

        if not self._env_truthy("NIJA_KRAKEN_MARGIN_ENABLED"):
            return {}
        lev = self._clamp_leverage(leverage)
        params: dict[str, str] = {}
        if lev >= KRAKEN_MIN_LEVERAGE:
            params["leverage"] = str(lev)
        if is_reducing:
            params["reduce_only"] = "true"
        return params

    def compute_leveraged_notional(
        self,
        *,
        spot_size_usd: float,
        leverage: Any,
        account_equity_usd: float,
    ) -> float:
        """Scale spot notional by leverage while enforcing the hard 3× equity cap."""

        lev = self._clamp_leverage(leverage)
        if lev < KRAKEN_MIN_LEVERAGE:
            lev = 1
        raw_notional = max(0.0, float(spot_size_usd or 0.0)) * lev
        cap = max(0.0, float(account_equity_usd or 0.0)) * HARD_MAX_LEVERAGE
        if cap <= 0:
            return 0.0
        return min(raw_notional, cap)

    def _build_snapshot(self, adapter: Any) -> MarginHealthSnapshot:
        """Build a health snapshot from Kraken TradeBalance data."""

        response = adapter._kraken_api_call("TradeBalance", {"asset": "ZUSD"})
        data = response.get("result", {}) if isinstance(response, dict) else {}
        eb = self._to_float(data.get("eb"))
        tb = self._to_float(data.get("tb"))
        ml = self._to_float(data.get("ml"))
        mo = self._to_float(data.get("mo"))
        mf = self._to_float(data.get("mf"))
        pnl = self._to_float(data.get("n"))
        equivalent = self._to_float(data.get("e"), eb)
        borrowed = max(self._total_borrowed_usd, mo)

        enabled = self._env_truthy("NIJA_KRAKEN_MARGIN_ENABLED")
        permission = self._permission_state.value if isinstance(self._permission_state, MarginPermissionState) else str(self._permission_state)

        if mo <= 0 and ml <= 0:
            maintenance_ok = True
            critical = False
            reason = "no_margin_positions"
        else:
            maintenance_floor_pct = MAINTENANCE_MARGIN_RATIO_FLOOR * 1000.0
            critical_floor_pct = CRITICAL_MARGIN_RATIO_FLOOR * 1000.0
            critical = ml > 0 and ml < critical_floor_pct
            maintenance_ok = ml == 0 or ml >= maintenance_floor_pct
            if critical:
                reason = f"critical_margin_level:{ml:.1f}%"
            elif not maintenance_ok:
                reason = f"low_margin_level:{ml:.1f}%"
            else:
                reason = f"margin_healthy:{ml:.1f}%"

        return MarginHealthSnapshot(
            timestamp=time.time(),
            permission_state=permission,
            equivalent_balance_usd=equivalent,
            trade_balance_free_usd=tb,
            margin_level_pct=ml,
            margin_obligation_usd=mo,
            free_margin_usd=mf,
            unrealised_pnl_usd=pnl,
            borrowed_exposure_usd=borrowed,
            is_margin_enabled=enabled,
            maintenance_margin_ok=maintenance_ok,
            critical_margin_breach=critical,
            reason=reason,
        )

    def get_health_snapshot(self, adapter: Any = None) -> MarginHealthSnapshot:
        """Return cached margin health, refreshing from Kraken when an adapter exists."""

        now = time.time()
        with self._lock:
            if self._last_snapshot is not None and now - self._snapshot_ts < _HEALTH_CACHE_TTL_SECONDS:
                return self._last_snapshot

        if adapter is not None:
            snapshot = self._build_snapshot(adapter)
        else:
            permission = self._permission_state.value if isinstance(self._permission_state, MarginPermissionState) else str(self._permission_state)
            enabled = self._env_truthy("NIJA_KRAKEN_MARGIN_ENABLED")
            exposure = self.get_exposure_snapshot()
            snapshot = MarginHealthSnapshot(
                timestamp=now,
                permission_state=permission,
                equivalent_balance_usd=0.0,
                trade_balance_free_usd=0.0,
                margin_level_pct=0.0,
                margin_obligation_usd=0.0,
                free_margin_usd=0.0,
                unrealised_pnl_usd=0.0,
                borrowed_exposure_usd=exposure["total_borrowed_usd"],
                is_margin_enabled=enabled,
                maintenance_margin_ok=True,
                critical_margin_breach=False,
                reason="no_margin_positions" if exposure["position_count"] <= 0 else "ledger_only_snapshot",
            )

        with self._lock:
            self._last_snapshot = snapshot
            self._snapshot_ts = snapshot.timestamp
        return snapshot

    def is_margin_trade_allowed(self, *, is_reducing: bool = False, adapter: Any = None) -> tuple[bool, str]:
        """Return whether a leveraged Kraken order may be submitted now."""

        if not self._env_truthy("NIJA_KRAKEN_MARGIN_ENABLED"):
            return False, "margin_disabled"

        if adapter is not None:
            self.check_permissions(adapter)

        state = self._permission_state
        if state == MarginPermissionState.DENIED:
            return False, "permission_denied"
        if state == MarginPermissionState.CHECK_FAILED:
            return False, "permission_check_failed"
        if state != MarginPermissionState.CONFIRMED:
            return False, "permission_unknown"

        snapshot = self.get_health_snapshot(adapter=adapter)
        if snapshot.critical_margin_breach:
            return False, f"critical_margin:{snapshot.reason}"
        if not snapshot.maintenance_margin_ok and not is_reducing:
            return False, f"maintenance_low:{snapshot.reason}"
        return True, snapshot.reason or "margin_allowed"

    def _borrowed_amount(self, notional_usd: float, leverage: Any) -> float:
        lev = self._clamp_leverage(leverage)
        if lev < KRAKEN_MIN_LEVERAGE:
            return 0.0
        notional = max(0.0, float(notional_usd or 0.0))
        equity_portion = notional / lev if lev > 0 else notional
        return max(0.0, notional - equity_portion)

    def record_open_position(self, *, notional_usd: float, leverage: Any) -> None:
        with self._lock:
            self._total_notional_usd += max(0.0, float(notional_usd or 0.0))
            self._total_borrowed_usd += self._borrowed_amount(notional_usd, leverage)
            self._position_count += 1.0
            self.invalidate_health_cache()

    def record_closed_position(self, *, notional_usd: float, leverage: Any) -> None:
        with self._lock:
            self._total_notional_usd = max(0.0, self._total_notional_usd - max(0.0, float(notional_usd or 0.0)))
            self._total_borrowed_usd = max(0.0, self._total_borrowed_usd - self._borrowed_amount(notional_usd, leverage))
            self._position_count = max(0.0, self._position_count - 1.0)
            self.invalidate_health_cache()

    def get_exposure_snapshot(self) -> dict[str, float]:
        with self._lock:
            equity = max(0.0, self._total_notional_usd - self._total_borrowed_usd)
            net_leverage = self._total_notional_usd / equity if equity > 0 else 0.0
            return {
                "total_notional_usd": self._total_notional_usd,
                "total_borrowed_usd": self._total_borrowed_usd,
                "position_count": self._position_count,
                "net_leverage": net_leverage,
            }


_MARGIN_ENGINE: Optional[KrakenMarginEngine] = None
_MARGIN_ENGINE_LOCK = threading.Lock()


def get_margin_engine() -> KrakenMarginEngine:
    """Return the process-wide Kraken margin engine singleton."""

    global _MARGIN_ENGINE
    with _MARGIN_ENGINE_LOCK:
        if _MARGIN_ENGINE is None:
            _MARGIN_ENGINE = KrakenMarginEngine()
        return _MARGIN_ENGINE


__all__ = [
    "CRITICAL_MARGIN_RATIO_FLOOR",
    "HARD_MAX_LEVERAGE",
    "KRAKEN_MIN_LEVERAGE",
    "MAINTENANCE_MARGIN_RATIO_FLOOR",
    "KrakenMarginEngine",
    "MarginHealthSnapshot",
    "MarginPermissionState",
    "get_margin_engine",
]
