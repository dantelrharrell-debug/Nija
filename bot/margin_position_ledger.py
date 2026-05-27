from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.margin_ledger")


@dataclass
class AccountEquitySnapshot:
    broker: str
    account_id: str
    equity_usd: float
    free_balance_usd: float
    margin_obligation_usd: float
    free_margin_usd: float
    unrealised_pnl_usd: float
    ts: float


@dataclass
class PositionSnapshot:
    broker: str
    account_id: str
    symbol: str
    position_id: str
    side: str
    notional_usd: float
    leverage: float
    entry_price: float = 0.0
    mark_price: float = 0.0
    unrealised_pnl_usd: float = 0.0
    reduce_only: bool = False
    ts: float = 0.0


@dataclass
class MarginRiskSnapshot:
    broker: str
    account_id: str
    equivalent_balance_usd: float
    trade_balance_free_usd: float
    margin_level_pct: float
    margin_obligation_usd: float
    free_margin_usd: float
    unrealised_pnl_usd: float
    borrowed_exposure_usd: float
    used_margin_usd: float
    maintenance_margin_ratio: float
    net_leverage: float
    concentration_ratio: float
    reconciliation_status: str
    stale: bool
    ts: float


class MarginPositionLedger:
    """Broker-agnostic margin/position ledger; authoritative risk truth source."""

    def __init__(self, *, persist_path: Optional[str] = None, stale_after_s: float = 45.0) -> None:
        self._lock = threading.RLock()
        self._persist_path = (
            persist_path
            or os.getenv("NIJA_MARGIN_LEDGER_PATH", "./data/margin_position_ledger.json")
        )
        self._stale_after_s = max(1.0, float(stale_after_s))
        self._equity: Dict[Tuple[str, str], AccountEquitySnapshot] = {}
        self._positions: Dict[Tuple[str, str, str, str], PositionSnapshot] = {}
        self._reconciliation_status: Dict[Tuple[str, str], str] = {}
        self._last_update_ts: Dict[Tuple[str, str], float] = {}
        self._load_if_available()

    def ingest_account_snapshot(
        self,
        *,
        broker: str,
        account_id: str,
        equity_usd: float,
        free_balance_usd: float,
        margin_obligation_usd: float,
        free_margin_usd: float,
        unrealised_pnl_usd: float = 0.0,
        ts: Optional[float] = None,
    ) -> None:
        now_ts = float(ts if ts is not None else time.time())
        key = (str(broker).lower(), str(account_id))
        snap = AccountEquitySnapshot(
            broker=key[0],
            account_id=key[1],
            equity_usd=max(0.0, float(equity_usd)),
            free_balance_usd=max(0.0, float(free_balance_usd)),
            margin_obligation_usd=max(0.0, float(margin_obligation_usd)),
            free_margin_usd=max(0.0, float(free_margin_usd)),
            unrealised_pnl_usd=float(unrealised_pnl_usd),
            ts=now_ts,
        )
        with self._lock:
            self._equity[key] = snap
            self._last_update_ts[key] = now_ts
            self._reconciliation_status.setdefault(key, "ok")
            self._persist()

    def ingest_position_snapshot(
        self,
        *,
        broker: str,
        account_id: str,
        symbol: str,
        position_id: str,
        side: str,
        notional_usd: float,
        leverage: float,
        entry_price: float = 0.0,
        mark_price: float = 0.0,
        unrealised_pnl_usd: float = 0.0,
        reduce_only: bool = False,
        ts: Optional[float] = None,
    ) -> None:
        now_ts = float(ts if ts is not None else time.time())
        key = (str(broker).lower(), str(account_id), str(symbol), str(position_id))
        snap = PositionSnapshot(
            broker=key[0],
            account_id=key[1],
            symbol=key[2],
            position_id=key[3],
            side=str(side).lower(),
            notional_usd=max(0.0, float(notional_usd)),
            leverage=max(1.0, float(leverage)),
            entry_price=float(entry_price),
            mark_price=float(mark_price),
            unrealised_pnl_usd=float(unrealised_pnl_usd),
            reduce_only=bool(reduce_only),
            ts=now_ts,
        )
        with self._lock:
            self._positions[key] = snap
            acct_key = (key[0], key[1])
            self._last_update_ts[acct_key] = now_ts
            self._reconciliation_status.setdefault(acct_key, "ok")
            self._persist()

    def remove_position(self, *, broker: str, account_id: str, symbol: str, position_id: str) -> None:
        key = (str(broker).lower(), str(account_id), str(symbol), str(position_id))
        acct_key = (key[0], key[1])
        with self._lock:
            self._positions.pop(key, None)
            self._last_update_ts[acct_key] = time.time()
            self._persist()

    def reconcile_positions(
        self,
        *,
        broker: str,
        account_id: str,
        truth_positions: List[Dict[str, Any]],
    ) -> str:
        acct_key = (str(broker).lower(), str(account_id))
        seen: set[Tuple[str, str, str, str]] = set()
        with self._lock:
            for item in truth_positions:
                symbol = str(item.get("symbol") or "")
                position_id = str(item.get("position_id") or item.get("id") or f"{symbol}:{item.get('side','')}")
                key = (acct_key[0], acct_key[1], symbol, position_id)
                seen.add(key)
            current_keys = [k for k in self._positions if k[0] == acct_key[0] and k[1] == acct_key[1]]
            missing = [k for k in current_keys if k not in seen]
            for key in missing:
                self._positions.pop(key, None)
            status = "ok" if not missing else "diverged"
            self._reconciliation_status[acct_key] = status
            self._last_update_ts[acct_key] = time.time()
            self._persist()
            return status

    def ingest_execution_event(
        self,
        *,
        broker: str,
        account_id: str,
        symbol: str,
        side: str,
        notional_usd: float,
        leverage: float,
        position_id: Optional[str] = None,
        reduce_only: bool = False,
    ) -> None:
        pid = str(position_id or f"{symbol}:{int(time.time() * 1000)}")
        side_lower = str(side).lower()
        if reduce_only:
            self.remove_position(broker=broker, account_id=account_id, symbol=symbol, position_id=pid)
            return
        self.ingest_position_snapshot(
            broker=broker,
            account_id=account_id,
            symbol=symbol,
            position_id=pid,
            side=side_lower,
            notional_usd=notional_usd,
            leverage=leverage,
            reduce_only=reduce_only,
        )

    def get_account_risk_snapshot(self, *, broker: str, account_id: str) -> MarginRiskSnapshot:
        acct_key = (str(broker).lower(), str(account_id))
        with self._lock:
            eq = self._equity.get(
                acct_key,
                AccountEquitySnapshot(
                    broker=acct_key[0],
                    account_id=acct_key[1],
                    equity_usd=0.0,
                    free_balance_usd=0.0,
                    margin_obligation_usd=0.0,
                    free_margin_usd=0.0,
                    unrealised_pnl_usd=0.0,
                    ts=0.0,
                ),
            )
            positions = [p for k, p in self._positions.items() if k[0] == acct_key[0] and k[1] == acct_key[1]]
            total_notional = sum(max(0.0, p.notional_usd) for p in positions)
            total_borrowed = sum(max(0.0, p.notional_usd - (p.notional_usd / max(1.0, p.leverage))) for p in positions)
            used_margin = max(0.0, total_notional - total_borrowed)
            eq_with_pnl = max(0.0, float(eq.equity_usd) + float(eq.unrealised_pnl_usd))
            if eq.margin_obligation_usd > 0:
                margin_level_pct = (eq_with_pnl / eq.margin_obligation_usd) * 100.0
            elif used_margin > 0:
                margin_level_pct = (eq_with_pnl / max(used_margin, 1e-9)) * 100.0
            else:
                margin_level_pct = 0.0
            maintenance_ratio = 0.0
            if eq_with_pnl > 0:
                maintenance_ratio = max(0.0, min(1.0, eq.margin_obligation_usd / eq_with_pnl))
            net_leverage = (total_notional / max(eq_with_pnl, 1e-9)) if total_notional > 0 else 0.0
            concentration = (total_notional / max(eq_with_pnl, 1e-9)) if total_notional > 0 else 0.0
            ts = max(float(eq.ts), float(self._last_update_ts.get(acct_key, 0.0)))
            stale = (time.time() - ts) > self._stale_after_s if ts > 0 else True
            recon = self._reconciliation_status.get(acct_key, "unknown")
            if stale and recon == "ok":
                recon = "stale"
            return MarginRiskSnapshot(
                broker=acct_key[0],
                account_id=acct_key[1],
                equivalent_balance_usd=float(eq.equity_usd),
                trade_balance_free_usd=float(eq.free_balance_usd),
                margin_level_pct=float(margin_level_pct),
                margin_obligation_usd=float(eq.margin_obligation_usd),
                free_margin_usd=float(eq.free_margin_usd),
                unrealised_pnl_usd=float(eq.unrealised_pnl_usd),
                borrowed_exposure_usd=float(total_borrowed if total_borrowed > 0 else eq.margin_obligation_usd),
                used_margin_usd=float(used_margin),
                maintenance_margin_ratio=float(maintenance_ratio),
                net_leverage=float(net_leverage),
                concentration_ratio=float(concentration),
                reconciliation_status=recon,
                stale=stale,
                ts=ts,
            )

    def get_observability_snapshot(self, *, broker: str, account_id: str) -> Dict[str, Any]:
        snap = self.get_account_risk_snapshot(broker=broker, account_id=account_id)
        return asdict(snap)

    def get_runtime_capability_overrides(self, *, broker: str, account_id: str) -> Dict[str, Any]:
        snap = self.get_account_risk_snapshot(broker=broker, account_id=account_id)
        if snap.reconciliation_status in {"diverged", "stale", "unknown"}:
            return {"supports_margin": False, "supports_short": False, "max_leverage": 1.0}
        return {
            "supports_margin": True,
            "supports_short": True,
            "max_leverage": 3.0,
        }

    def _load_if_available(self) -> None:
        try:
            if not self._persist_path or not os.path.exists(self._persist_path):
                return
            with open(self._persist_path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            with self._lock:
                for item in raw.get("equity", []):
                    snap = AccountEquitySnapshot(**item)
                    self._equity[(snap.broker, snap.account_id)] = snap
                for item in raw.get("positions", []):
                    snap = PositionSnapshot(**item)
                    self._positions[(snap.broker, snap.account_id, snap.symbol, snap.position_id)] = snap
                for k, v in (raw.get("reconciliation_status", {}) or {}).items():
                    parts = str(k).split("::", 1)
                    if len(parts) == 2:
                        self._reconciliation_status[(parts[0], parts[1])] = str(v)
                for k, v in (raw.get("last_update_ts", {}) or {}).items():
                    parts = str(k).split("::", 1)
                    if len(parts) == 2:
                        self._last_update_ts[(parts[0], parts[1])] = float(v)
        except Exception as exc:
            logger.debug("MarginPositionLedger load skipped: %s", exc)

    def _persist(self) -> None:
        if not self._persist_path:
            return
        try:
            os.makedirs(os.path.dirname(self._persist_path) or ".", exist_ok=True)
            payload = {
                "equity": [asdict(v) for v in self._equity.values()],
                "positions": [asdict(v) for v in self._positions.values()],
                "reconciliation_status": {f"{k[0]}::{k[1]}": v for k, v in self._reconciliation_status.items()},
                "last_update_ts": {f"{k[0]}::{k[1]}": v for k, v in self._last_update_ts.items()},
            }
            tmp = f"{self._persist_path}.tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, sort_keys=True)
            os.replace(tmp, self._persist_path)
        except Exception as exc:
            logger.debug("MarginPositionLedger persist skipped: %s", exc)


_ledger_singleton: Optional[MarginPositionLedger] = None
_ledger_lock = threading.Lock()


def get_margin_position_ledger() -> MarginPositionLedger:
    global _ledger_singleton
    if _ledger_singleton is not None:
        return _ledger_singleton
    with _ledger_lock:
        if _ledger_singleton is None:
            _ledger_singleton = MarginPositionLedger()
    return _ledger_singleton
