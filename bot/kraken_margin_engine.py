"""Account-scoped Kraken margin permission, pair, sizing, and health controls.

NIJA uses this module as the single boundary for Kraken margin admission.  Margin
is never inferred solely from a global environment flag: the exact account must
pass private-API permission and TradeBalance health checks, and the exact pair
must advertise the requested leverage through Kraken AssetPairs.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from enum import Enum
import os
import threading
import time
from typing import Any, Dict, Iterator, Optional, Tuple

try:
    from bot.kraken_error_taxonomy import is_permission_error
except ImportError:  # pragma: no cover
    from kraken_error_taxonomy import is_permission_error  # type: ignore[import]


KRAKEN_MIN_LEVERAGE = 2
HARD_MAX_LEVERAGE = 3
MAINTENANCE_MARGIN_RATIO_FLOOR = 0.20  # 200% Kraken margin level
CRITICAL_MARGIN_RATIO_FLOOR = 0.10     # 100% Kraken margin level

_PERMISSION_CACHE_TTL_SECONDS = 300.0
_HEALTH_CACHE_TTL_SECONDS = 15.0
_PAIR_CACHE_TTL_SECONDS = 1800.0


class MarginPermissionState(str, Enum):
    UNKNOWN = "UNKNOWN"
    CONFIRMED = "CONFIRMED"
    DENIED = "DENIED"
    CHECK_FAILED = "CHECK_FAILED"


@dataclass(frozen=True)
class MarginHealthSnapshot:
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


@dataclass(frozen=True)
class MarginAdmissionPlan:
    allowed: bool
    account_id: str
    symbol: str
    side: str
    leverage: int
    spot_notional_usd: float
    leveraged_notional_usd: float
    buying_power_usd: float
    margin_mode: str
    reduce_only: bool
    reason: str
    pair_max_leverage: int = 1


class KrakenMarginEngine:
    """Fail-closed controller for one Kraken account's leveraged orders."""

    def __init__(self, account_id: str = "default", adapter: Any = None) -> None:
        self.account_id = str(account_id or "default").strip() or "default"
        self._adapter = adapter
        self._lock = threading.RLock()
        self._permission_state = MarginPermissionState.UNKNOWN
        self._permission_checked_at = 0.0
        self._last_snapshot: Optional[MarginHealthSnapshot] = None
        self._snapshot_ts = 0.0
        self._pair_cache: Dict[Tuple[str, str], Tuple[float, Tuple[int, ...]]] = {}
        self._total_notional_usd = 0.0
        self._total_borrowed_usd = 0.0
        self._position_count = 0.0

    def bind_adapter(self, adapter: Any) -> None:
        if adapter is not None:
            with self._lock:
                self._adapter = adapter

    @staticmethod
    def _env_truthy(name: str, default: bool = False) -> bool:
        value = os.getenv(name)
        if value is None:
            return default
        return str(value).strip().lower() in {"1", "true", "yes", "on", "y", "enabled"}

    @staticmethod
    def _to_float(value: Any, default: float = 0.0) -> float:
        try:
            if value is None:
                return default
            parsed = float(value)
            return parsed if parsed == parsed else default
        except (TypeError, ValueError, OverflowError):
            return default

    @staticmethod
    def _clamp_leverage(leverage: Any) -> int:
        try:
            lev = int(float(leverage))
        except (TypeError, ValueError, OverflowError):
            lev = 1
        if lev < KRAKEN_MIN_LEVERAGE:
            return 1
        return max(KRAKEN_MIN_LEVERAGE, min(HARD_MAX_LEVERAGE, lev))

    @staticmethod
    def _normalise_pair(symbol: str) -> str:
        text = str(symbol or "").upper().strip().replace("/", "").replace("-", "").replace("_", "")
        if text.startswith("BTC"):
            text = "XBT" + text[3:]
        if text.endswith("ZUSD"):
            return text
        if text.endswith("USD"):
            return text[:-3] + "USD"
        return text

    def invalidate_permission_cache(self) -> None:
        with self._lock:
            self._permission_checked_at = 0.0
            self._permission_state = MarginPermissionState.UNKNOWN

    def invalidate_health_cache(self) -> None:
        with self._lock:
            self._last_snapshot = None
            self._snapshot_ts = 0.0

    def invalidate_pair_cache(self) -> None:
        with self._lock:
            self._pair_cache.clear()

    def _resolve_adapter(self, adapter: Any = None) -> Any:
        resolved = adapter if adapter is not None else self._adapter
        if adapter is not None:
            self.bind_adapter(adapter)
        return resolved

    def check_permissions(self, adapter: Any = None) -> MarginPermissionState:
        """Confirm that this exact Kraken account can access private trade state."""
        adapter = self._resolve_adapter(adapter)
        if adapter is None:
            return self._permission_state
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
            if errors:
                state = (
                    MarginPermissionState.DENIED
                    if any(is_permission_error(error) for error in errors)
                    else MarginPermissionState.CHECK_FAILED
                )
            else:
                state = MarginPermissionState.CONFIRMED
        except Exception:
            state = MarginPermissionState.CHECK_FAILED
        with self._lock:
            self._permission_state = state
            self._permission_checked_at = now
        return state

    @staticmethod
    def _parse_leverage_values(value: Any) -> Tuple[int, ...]:
        values = value if isinstance(value, (list, tuple, set)) else [value]
        parsed = set()
        for item in values:
            try:
                lev = int(float(item))
            except (TypeError, ValueError, OverflowError):
                continue
            if KRAKEN_MIN_LEVERAGE <= lev <= HARD_MAX_LEVERAGE:
                parsed.add(lev)
        return tuple(sorted(parsed))

    def get_pair_leverages(self, symbol: str, side: str, adapter: Any = None) -> Tuple[int, ...]:
        """Return live Kraken-advertised leverage values for the exact pair/side."""
        adapter = self._resolve_adapter(adapter)
        side_key = "sell" if str(side or "").lower() in {"sell", "short"} else "buy"
        pair = self._normalise_pair(symbol)
        cache_key = (pair, side_key)
        now = time.time()
        with self._lock:
            cached = self._pair_cache.get(cache_key)
            if cached and now - cached[0] < _PAIR_CACHE_TTL_SECONDS:
                return cached[1]
        if adapter is None:
            return ()
        try:
            response = adapter._kraken_api_call("AssetPairs", {"pair": pair})
            errors = response.get("error") or [] if isinstance(response, dict) else []
            result = response.get("result", {}) if isinstance(response, dict) else {}
            if errors or not isinstance(result, dict):
                leverages: Tuple[int, ...] = ()
            else:
                merged = set()
                field = "leverage_sell" if side_key == "sell" else "leverage_buy"
                for item in result.values():
                    if isinstance(item, dict):
                        merged.update(self._parse_leverage_values(item.get(field, [])))
                leverages = tuple(sorted(merged))
        except Exception:
            leverages = ()
        with self._lock:
            self._pair_cache[cache_key] = (now, leverages)
        return leverages

    def get_pair_max_leverage(self, symbol: str, side: str, adapter: Any = None) -> int:
        values = self.get_pair_leverages(symbol, side, adapter=adapter)
        return max(values) if values else 1

    def build_order_margin_params(self, leverage: Any, *, is_reducing: bool = False) -> dict[str, Any]:
        """Return only fields accepted by Kraken AddOrder for spot margin."""
        if not self._env_truthy("NIJA_KRAKEN_MARGIN_ENABLED", default=True):
            return {}
        lev = self._clamp_leverage(leverage)
        params: dict[str, Any] = {}
        if lev >= KRAKEN_MIN_LEVERAGE:
            params["leverage"] = str(lev)
        if is_reducing:
            params["reduce_only"] = True
        return params

    def compute_leveraged_notional(
        self,
        *,
        spot_size_usd: float,
        leverage: Any,
        account_equity_usd: float,
        buying_power_usd: Optional[float] = None,
    ) -> float:
        """Scale a risk-approved spot size while preserving the hard 3× equity cap."""
        lev = self._clamp_leverage(leverage)
        if lev < KRAKEN_MIN_LEVERAGE:
            lev = 1
        raw_notional = max(0.0, float(spot_size_usd or 0.0)) * lev
        equity_cap = max(0.0, float(account_equity_usd or 0.0)) * HARD_MAX_LEVERAGE
        if equity_cap <= 0:
            return 0.0
        cap = equity_cap
        if buying_power_usd is not None and float(buying_power_usd or 0.0) > 0:
            cap = min(cap, float(buying_power_usd))
        return min(raw_notional, cap)

    def _build_snapshot(self, adapter: Any) -> MarginHealthSnapshot:
        response = adapter._kraken_api_call("TradeBalance", {"asset": "ZUSD"})
        errors = response.get("error") or [] if isinstance(response, dict) else []
        if errors:
            raise RuntimeError("TradeBalance rejected: " + ", ".join(str(x) for x in errors))
        data = response.get("result", {}) if isinstance(response, dict) else {}
        eb = self._to_float(data.get("eb"))
        tb = self._to_float(data.get("tb"))
        ml = self._to_float(data.get("ml"))
        mo = self._to_float(data.get("mo"))
        mf = self._to_float(data.get("mf"))
        pnl = self._to_float(data.get("n"))
        equivalent = self._to_float(data.get("e"), eb)
        borrowed = max(self._total_borrowed_usd, mo)
        enabled = self._env_truthy("NIJA_KRAKEN_MARGIN_ENABLED", default=True)
        permission = self._permission_state.value
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
        adapter = self._resolve_adapter(adapter)
        now = time.time()
        with self._lock:
            if self._last_snapshot is not None and now - self._snapshot_ts < _HEALTH_CACHE_TTL_SECONDS:
                return self._last_snapshot
        if adapter is not None:
            try:
                snapshot = self._build_snapshot(adapter)
            except Exception as exc:
                snapshot = MarginHealthSnapshot(
                    timestamp=now,
                    permission_state=self._permission_state.value,
                    equivalent_balance_usd=0.0,
                    trade_balance_free_usd=0.0,
                    margin_level_pct=0.0,
                    margin_obligation_usd=0.0,
                    free_margin_usd=0.0,
                    unrealised_pnl_usd=0.0,
                    borrowed_exposure_usd=self._total_borrowed_usd,
                    is_margin_enabled=self._env_truthy("NIJA_KRAKEN_MARGIN_ENABLED", default=True),
                    maintenance_margin_ok=False,
                    critical_margin_breach=False,
                    reason=f"health_check_failed:{exc}",
                )
        else:
            exposure = self.get_exposure_snapshot()
            snapshot = MarginHealthSnapshot(
                timestamp=now,
                permission_state=self._permission_state.value,
                equivalent_balance_usd=0.0,
                trade_balance_free_usd=0.0,
                margin_level_pct=0.0,
                margin_obligation_usd=0.0,
                free_margin_usd=0.0,
                unrealised_pnl_usd=0.0,
                borrowed_exposure_usd=exposure["total_borrowed_usd"],
                is_margin_enabled=self._env_truthy("NIJA_KRAKEN_MARGIN_ENABLED", default=True),
                maintenance_margin_ok=exposure["position_count"] <= 0,
                critical_margin_breach=False,
                reason="no_bound_adapter" if self._adapter is None else "cached_adapter_unavailable",
            )
        with self._lock:
            self._last_snapshot = snapshot
            self._snapshot_ts = snapshot.timestamp
        return snapshot

    def is_margin_trade_allowed(self, *, is_reducing: bool = False, adapter: Any = None) -> tuple[bool, str]:
        if not self._env_truthy("NIJA_KRAKEN_MARGIN_ENABLED", default=True):
            return False, "margin_disabled"
        adapter = self._resolve_adapter(adapter)
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
        if str(snapshot.reason).startswith("health_check_failed"):
            return False, snapshot.reason
        if snapshot.critical_margin_breach:
            return False, f"critical_margin:{snapshot.reason}"
        if not snapshot.maintenance_margin_ok and not is_reducing:
            return False, f"maintenance_low:{snapshot.reason}"
        return True, snapshot.reason or "margin_allowed"

    def plan_auto_margin(
        self,
        *,
        adapter: Any,
        symbol: str,
        side: str,
        spot_size_usd: float,
        account_equity_usd: float = 0.0,
        requested_leverage: Any = None,
        is_reducing: bool = False,
    ) -> MarginAdmissionPlan:
        """Build a live, account-and-pair-qualified margin plan.

        Automatic margin is long-only by default.  Existing margin exits may pass
        ``is_reducing=True`` and retain their ledger leverage separately.
        """
        self.bind_adapter(adapter)
        side_norm = "sell" if str(side or "").lower() in {"sell", "short"} else "buy"
        spot = max(0.0, self._to_float(spot_size_usd))
        desired = requested_leverage
        if desired is None:
            desired = os.getenv("NIJA_KRAKEN_MARGIN_DEFAULT_LEVERAGE", "2")
        leverage = self._clamp_leverage(desired)
        base_plan = dict(
            account_id=self.account_id,
            symbol=str(symbol or ""),
            side=side_norm,
            leverage=leverage,
            spot_notional_usd=spot,
            leveraged_notional_usd=spot,
            buying_power_usd=max(0.0, self._to_float(account_equity_usd)),
            margin_mode="cross",
            reduce_only=bool(is_reducing),
        )
        if not self._env_truthy("NIJA_KRAKEN_MARGIN_ENABLED", default=True):
            return MarginAdmissionPlan(False, reason="margin_disabled", pair_max_leverage=1, **base_plan)
        if not self._env_truthy("NIJA_KRAKEN_AUTO_MARGIN_ENABLED", default=True) and requested_leverage is None:
            return MarginAdmissionPlan(False, reason="auto_margin_disabled", pair_max_leverage=1, **base_plan)
        if leverage < KRAKEN_MIN_LEVERAGE:
            return MarginAdmissionPlan(False, reason="spot_leverage_requested", pair_max_leverage=1, **base_plan)
        if side_norm == "sell" and not is_reducing and self._env_truthy("NIJA_KRAKEN_AUTO_MARGIN_LONG_ONLY", default=True):
            return MarginAdmissionPlan(False, reason="auto_margin_long_only", pair_max_leverage=1, **base_plan)
        allowed, reason = self.is_margin_trade_allowed(is_reducing=is_reducing, adapter=adapter)
        if not allowed:
            return MarginAdmissionPlan(False, reason=reason, pair_max_leverage=1, **base_plan)
        pair_values = self.get_pair_leverages(symbol, side_norm, adapter=adapter)
        pair_max = max(pair_values) if pair_values else 1
        if leverage not in pair_values:
            return MarginAdmissionPlan(False, reason=f"pair_leverage_unavailable:{pair_values or 'none'}", pair_max_leverage=pair_max, **base_plan)
        snapshot = self.get_health_snapshot(adapter=adapter)
        equity = max(
            self._to_float(account_equity_usd),
            snapshot.equivalent_balance_usd,
            snapshot.trade_balance_free_usd,
        )
        collateral = snapshot.free_margin_usd or snapshot.trade_balance_free_usd or equity
        buying_power = max(0.0, collateral * leverage)
        leveraged = self.compute_leveraged_notional(
            spot_size_usd=spot,
            leverage=leverage,
            account_equity_usd=equity,
            buying_power_usd=buying_power,
        )
        if leveraged <= 0:
            return MarginAdmissionPlan(False, reason="no_margin_buying_power", pair_max_leverage=pair_max, **base_plan)
        return MarginAdmissionPlan(
            allowed=True,
            account_id=self.account_id,
            symbol=str(symbol or ""),
            side=side_norm,
            leverage=leverage,
            spot_notional_usd=spot,
            leveraged_notional_usd=leveraged,
            buying_power_usd=buying_power,
            margin_mode="cross",
            reduce_only=bool(is_reducing),
            reason=f"margin_eligible:{reason}",
            pair_max_leverage=pair_max,
        )

    def get_runtime_capability_overrides(self, account_id: Optional[str] = None) -> Dict[str, Any]:
        allowed = self._permission_state == MarginPermissionState.CONFIRMED
        return {
            "supports_margin": allowed,
            "supports_leverage": allowed,
            "supports_short": allowed and not self._env_truthy("NIJA_KRAKEN_AUTO_MARGIN_LONG_ONLY", default=True),
            "max_leverage": HARD_MAX_LEVERAGE if allowed else 1,
            "account_id": account_id or self.account_id,
        }

    def _borrowed_amount(self, notional_usd: float, leverage: Any) -> float:
        lev = self._clamp_leverage(leverage)
        if lev < KRAKEN_MIN_LEVERAGE:
            return 0.0
        notional = max(0.0, float(notional_usd or 0.0))
        return max(0.0, notional - (notional / lev))

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


_MARGIN_ENGINES: Dict[str, KrakenMarginEngine] = {}
_MARGIN_ENGINE_LOCK = threading.Lock()
_CURRENT_MARGIN_ACCOUNT: ContextVar[str] = ContextVar("nija_kraken_margin_account", default="default")


def get_margin_engine(account_id: Optional[str] = None, adapter: Any = None) -> KrakenMarginEngine:
    key = str(account_id or _CURRENT_MARGIN_ACCOUNT.get() or "default").strip() or "default"
    with _MARGIN_ENGINE_LOCK:
        engine = _MARGIN_ENGINES.get(key)
        if engine is None:
            engine = KrakenMarginEngine(account_id=key, adapter=adapter)
            _MARGIN_ENGINES[key] = engine
    engine.bind_adapter(adapter)
    return engine


@contextmanager
def margin_account_scope(account_id: str, adapter: Any = None) -> Iterator[KrakenMarginEngine]:
    key = str(account_id or "default").strip() or "default"
    token = _CURRENT_MARGIN_ACCOUNT.set(key)
    try:
        yield get_margin_engine(key, adapter=adapter)
    finally:
        _CURRENT_MARGIN_ACCOUNT.reset(token)


def reset_margin_engines_for_tests() -> None:
    with _MARGIN_ENGINE_LOCK:
        _MARGIN_ENGINES.clear()


__all__ = [
    "CRITICAL_MARGIN_RATIO_FLOOR",
    "HARD_MAX_LEVERAGE",
    "KRAKEN_MIN_LEVERAGE",
    "MAINTENANCE_MARGIN_RATIO_FLOOR",
    "KrakenMarginEngine",
    "MarginAdmissionPlan",
    "MarginHealthSnapshot",
    "MarginPermissionState",
    "get_margin_engine",
    "margin_account_scope",
    "reset_margin_engines_for_tests",
]
